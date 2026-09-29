"""Bonus Tracker — replaces Sam Baker first-team bonuses spreadsheet."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.paths import BONUS_TRACKER_DATA_DIR, DATA_ROOT, HUB_ROOT, STANDALONE_DIR, ensure_data_dirs
from app.season_defaults import CURRENT_SEASON

DATA_DIR = BONUS_TRACKER_DATA_DIR
DATA_PATH = DATA_DIR / "bonuses.json"
# Baked into the image under HUB_ROOT/data; DATA_ROOT is the persistent volume (/data).
_SEED_CANDIDATES = (
    HUB_ROOT / "data" / "bonus-provisions-seed.json",
    DATA_ROOT / "bonus-provisions-seed.json",
    Path(__file__).resolve().parent.parent / "data" / "bonus-provisions-seed.json",
)
_store_lock = threading.Lock()

APPEARANCE_BONUS_LABELS = {
    "none": "No appearance bonus",
    "league_start": "League Start Bonus",
    "league_start_or_sub": "League Start / Substitute Bonus",
}

MATCHDAY_TYPES = (
    {"id": "appearance", "label": "Appearance"},
    {"id": "goal_assist", "label": "Goal / Assist"},
    {"id": "clean_sheet", "label": "Clean Sheet"},
    {"id": "squad_bonus", "label": "Squad Bonus"},
    {"id": "personal_win", "label": "Bonus Payment"},
)

_CLAUSE_SPLIT = re.compile(r"\s+[-–—]\s+")
_KIND_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"goal contributions?", "goal_contributions"),
    (r"league assists|\bassists\b", "league_assists"),
    (r"league goals|\bgoals\b", "league_goals"),
    (r"league starts|\bstarts\b", "league_starts"),
    (r"league apps|league appearances|\bappearances\b|\bapps\b", "league_apps"),
    (r"minutes", "league_minutes"),
)
_KIND_STAT = {
    "league_starts": "league_starts",
    "league_apps": "league_appearances",
    "league_minutes": "league_minutes",
    "league_goals": "league_goals",
    "league_assists": "league_assists",
    "goal_contributions": "goal_contributions",
}
_KIND_UNIT = {
    "league_starts": "league starts",
    "league_apps": "league apps",
    "league_minutes": "league minutes",
    "league_goals": "league goals",
    "league_assists": "league assists",
    "goal_contributions": "goal contributions",
}


def _has_bonus_or_clause(player: dict[str, Any]) -> bool:
    appearance = str(player.get("appearance_bonus") or "none")
    if appearance != "none":
        return True
    return bool(str(player.get("provisions") or "").strip())


def parse_provision_clauses(text: str) -> list[dict[str, Any]]:
    """Split Sam’s provision line into trackable clauses."""
    raw = str(text or "").strip()
    if not raw:
        return []
    parts = [part.strip(" -–—") for part in _CLAUSE_SPLIT.split(raw) if part.strip(" -–—")]
    if not parts:
        parts = [raw]
    clauses: list[dict[str, Any]] = []
    for part in parts:
        kind = "other"
        for pattern, token in _KIND_PATTERNS:
            if re.search(pattern, part, re.I):
                kind = token
                break
        if kind == "other" and re.search(r"goal|assist|clean sheet", part, re.I):
            kind = "matchday"
        numbers = [int(token) for token in re.findall(r"\d+", part)]
        # "10 goals or 10 assists" — keep both kinds, same thresholds.
        if re.search(r"\bor\b", part, re.I) and re.search(r"goal", part, re.I) and re.search(
            r"assist", part, re.I
        ):
            kind = "goals_or_assists"
        clauses.append({"text": part, "kind": kind, "targets": numbers})
    return clauses


_FIRST_NAME_CANON = {
    "oli": "oliver",
    "olly": "oliver",
    "ollie": "oliver",
    "oliver": "oliver",
    "cam": "cameron",
    "cameron": "cameron",
    "mo": "mohammed",
    "mohamed": "mohammed",
    "mohammed": "mohammed",
    "joe": "joseph",
    "joseph": "joseph",
    "ben": "benjamin",
    "benjamin": "benjamin",
    "matt": "matthew",
    "matty": "matthew",
    "matthew": "matthew",
}


def _empty_playing_time() -> dict[str, int]:
    return {
        "league_starts": 0,
        "league_appearances": 0,
        "league_minutes": 0,
        "league_goals": 0,
        "league_assists": 0,
        "goal_contributions": 0,
    }


def _stats_only(row: dict[str, Any]) -> dict[str, int]:
    stats = {
        "league_starts": int(row.get("league_starts") or 0),
        "league_appearances": int(row.get("league_appearances") or 0),
        "league_minutes": int(row.get("league_minutes") or 0),
        "league_goals": int(row.get("league_goals") or 0),
        "league_assists": int(row.get("league_assists") or 0),
        "goal_contributions": int(row.get("goal_contributions") or 0),
    }
    if not stats["goal_contributions"]:
        stats["goal_contributions"] = stats["league_goals"] + stats["league_assists"]
    return stats


def _name_parts(name: str) -> tuple[str, str]:
    parts = [part for part in re.split(r"\s+", str(name or "").strip()) if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0].casefold(), ""
    return parts[0].casefold(), parts[-1].casefold()


def same_player_name(left: str, right: str) -> bool:
    """Oli Lynch == Oliver Lynch; Cam Humphreys == Cameron Humphreys."""
    if not left or not right:
        return False
    try:
        from app.availability_tracker import _normalize_player_key
    except Exception:
        return left.casefold() == right.casefold()
    left_key, right_key = _normalize_player_key(left), _normalize_player_key(right)
    if left_key == right_key:
        return True
    if left_key and right_key and (left_key in right_key or right_key in left_key):
        if min(len(left_key), len(right_key)) >= 6:
            return True
    left_first, left_last = _name_parts(left)
    right_first, right_last = _name_parts(right)
    if not left_last or left_last != right_last:
        return False
    if not left_first or not right_first:
        return False
    if _FIRST_NAME_CANON.get(left_first, left_first) == _FIRST_NAME_CANON.get(
        right_first, right_first
    ):
        return True
    if min(len(left_first), len(right_first)) >= 3 and (
        left_first.startswith(right_first) or right_first.startswith(left_first)
    ):
        return True
    return False


def _playing_time_index(season: str) -> dict[str, dict[str, Any]]:
    """League starts / apps / minutes / goals from FotMob (+ availability roster)."""
    index: dict[str, dict[str, Any]] = {}
    try:
        from app.availability_tracker import (
            _normalize_player_key,
            build_availability_payload,
            fotmob_league_playing_time,
        )
    except Exception:
        return {}

    try:
        fotmob = fotmob_league_playing_time(season)
    except Exception:
        fotmob = {}
    for key, row in (fotmob or {}).items():
        if not key:
            continue
        index[key] = {**_stats_only(row), "_name": str(row.get("name") or key)}

    try:
        payload = build_availability_payload(season=season, refresh=False)
    except Exception:
        payload = {}
    for row in (payload or {}).get("roster") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        impact = row.get("impact") or {}
        stats = _stats_only(impact)
        key = _normalize_player_key(name)
        if key:
            index[key] = {**stats, "_name": name}
    return index


def _match_playing_time(name: str, index: dict[str, dict[str, Any]]) -> dict[str, int]:
    if not index:
        return _empty_playing_time()
    try:
        from app.availability_tracker import _normalize_player_key
    except Exception:
        return _empty_playing_time()
    key = _normalize_player_key(name)
    if key in index:
        return _stats_only(index[key])

    hits = [
        row
        for row in index.values()
        if same_player_name(name, str(row.get("_name") or ""))
    ]
    if len(hits) == 1:
        return _stats_only(hits[0])

    _, last = _name_parts(name)
    if last:
        last_hits = [
            row
            for row in index.values()
            if _name_parts(str(row.get("_name") or ""))[1] == last
        ]
        if len(last_hits) == 1:
            return _stats_only(last_hits[0])
    return _empty_playing_time()


def _current_for_kind(kind: str, playing: dict[str, int]) -> int | None:
    if kind == "goals_or_assists":
        return max(int(playing.get("league_goals") or 0), int(playing.get("league_assists") or 0))
    stat = _KIND_STAT.get(kind)
    if not stat:
        return None
    return int(playing.get(stat) or 0)


def _decorate_clauses(
    player: dict[str, Any], playing: dict[str, int]
) -> list[dict[str, Any]]:
    appearance = str(player.get("appearance_bonus") or "none")
    clauses: list[dict[str, Any]] = []
    if appearance == "league_start":
        clauses.append(
            {
                "text": "League Start Bonus",
                "kind": "league_starts",
                "targets": [],
                "per_game": True,
            }
        )
    elif appearance == "league_start_or_sub":
        clauses.append(
            {
                "text": "League Start / Substitute Bonus",
                "kind": "league_apps",
                "targets": [],
                "per_game": True,
            }
        )
    clauses.extend(parse_provision_clauses(str(player.get("provisions") or "")))

    decorated: list[dict[str, Any]] = []
    for clause in clauses:
        kind = str(clause.get("kind") or "other")
        targets = [int(n) for n in (clause.get("targets") or []) if int(n) > 0]
        current = _current_for_kind(kind, playing)
        per_game = bool(clause.get("per_game"))
        unit = _KIND_UNIT.get(kind)
        if kind == "matchday":
            text_l = str(clause.get("text") or "").casefold()
            if "goal" in text_l and "assist" in text_l:
                current = int(playing.get("goal_contributions") or 0)
                unit = "goal contributions"
                per_game = True
            elif "goal" in text_l and "clean sheet" not in text_l:
                current = int(playing.get("league_goals") or 0)
                unit = "league goals"
                per_game = True
        thresholds: list[dict[str, Any]] = []
        for target in targets:
            met = current is not None and current >= target
            remaining = None if current is None else max(0, target - current)
            thresholds.append(
                {
                    "target": target,
                    "current": current,
                    "met": met,
                    "remaining": remaining,
                    "label": (
                        f"{current} / {target} {_KIND_UNIT.get(kind, '')}".strip()
                        if current is not None
                        else f"{target} {_KIND_UNIT.get(kind, '')}".strip()
                    ),
                }
            )
        next_target = next((row["target"] for row in thresholds if not row["met"]), None)
        decorated.append(
            {
                "text": clause["text"],
                "kind": kind,
                "per_game": per_game,
                "current": current,
                "unit": unit,
                "thresholds": thresholds,
                "next_target": next_target,
                "met": bool(thresholds) and all(row["met"] for row in thresholds),
            }
        )
    return decorated


class PlayerUpsert(BaseModel):
    id: str | None = None
    name: str = Field(..., min_length=1, max_length=120)
    surname: str | None = Field(default=None, max_length=80)
    first_name: str | None = Field(default=None, max_length=80)
    appearance_bonus: Literal["none", "league_start", "league_start_or_sub"] = "none"
    provisions: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=2000)
    active: bool = True


class MatchdayBonusCreate(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=80)
    date: str = Field(..., min_length=8, max_length=12)
    opponent: str = Field(..., min_length=1, max_length=120)
    result: str = Field(default="", max_length=40)
    bonus_type: Literal[
        "appearance", "goal_assist", "clean_sheet", "squad_bonus", "personal_win"
    ]
    amount: float | None = None
    tracking: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=500)


class MatchdayBonusUpdate(BaseModel):
    tracking: str | None = Field(default=None, max_length=200)
    amount: float | None = None
    notes: str | None = Field(default=None, max_length=500)
    paid: bool | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_store() -> None:
    ensure_data_dirs()
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_seed_path() -> Path:
    for candidate in _SEED_CANDIDATES:
        if candidate.is_file():
            return candidate
    return _SEED_CANDIDATES[0]


def _load_seed_players() -> list[dict[str, Any]]:
    seed_path = _resolve_seed_path()
    if not seed_path.is_file():
        return []
    try:
        payload = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("players") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        appearance = str(row.get("appearance_bonus") or "none")
        if appearance not in APPEARANCE_BONUS_LABELS:
            appearance = "none"
        player = {
            "id": str(row.get("id") or f"p-{uuid.uuid4().hex[:8]}"),
            "name": name,
            "surname": str(row.get("surname") or "").strip() or None,
            "first_name": str(row.get("first_name") or "").strip() or None,
            "appearance_bonus": appearance,
            "provisions": str(row.get("provisions") or "").strip(),
            "notes": "",
            "active": True,
        }
        if not _has_bonus_or_clause(player):
            continue
        out.append(player)
    return out


def _blank_store() -> dict[str, Any]:
    seed_path = _resolve_seed_path()
    return {
        "updated_at": _now(),
        "seeded_from": seed_path.name if seed_path.is_file() else None,
        "players": _load_seed_players(),
        "matchday": [],
    }


def _save_store(store: dict[str, Any]) -> None:
    _ensure_store()
    store["updated_at"] = _now()
    with _store_lock:
        temp = DATA_PATH.with_suffix(".json.tmp")
        temp.write_text(json.dumps(store, indent=2), encoding="utf-8")
        temp.replace(DATA_PATH)


def _load_store() -> dict[str, Any]:
    _ensure_store()
    with _store_lock:
        if not DATA_PATH.exists():
            store = _blank_store()
            temp = DATA_PATH.with_suffix(".json.tmp")
            temp.write_text(json.dumps(store, indent=2), encoding="utf-8")
            temp.replace(DATA_PATH)
            return store
        try:
            payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _blank_store()
    if not isinstance(payload, dict):
        return _blank_store()
    payload.setdefault("players", [])
    payload.setdefault("matchday", [])
    # First deploy wrote an empty store before the seed path was fixed — backfill once.
    if not payload.get("players"):
        seeded = _load_seed_players()
        if seeded:
            payload["players"] = seeded
            payload["seeded_from"] = _resolve_seed_path().name
            _save_store(payload)
    return payload


def _player_totals(matchday: list[dict[str, Any]], player_id: str) -> dict[str, Any]:
    totals = {
        "appearance": 0,
        "goal_assist": 0,
        "clean_sheet": 0,
        "squad_bonus": 0,
        "personal_win": 0,
        "amount": 0.0,
        "unpaid": 0,
    }
    for row in matchday:
        if str(row.get("player_id")) != player_id:
            continue
        btype = str(row.get("bonus_type") or "")
        if btype in totals:
            totals[btype] += 1
        try:
            totals["amount"] += float(row.get("amount") or 0)
        except (TypeError, ValueError):
            pass
        if not row.get("paid"):
            totals["unpaid"] += 1
    totals["amount"] = round(float(totals["amount"]), 2)
    return totals


def build_bonus_payload(season: str | None = None) -> dict[str, Any]:
    season_key = season or CURRENT_SEASON
    store = _load_store()
    matchday = list(store.get("matchday") or [])
    playing_index = _playing_time_index(season_key)
    players_out: list[dict[str, Any]] = []
    for player in store.get("players") or []:
        if not isinstance(player, dict):
            continue
        if player.get("active") is False:
            continue
        if not _has_bonus_or_clause(player):
            continue
        pid = str(player.get("id") or "")
        appearance = str(player.get("appearance_bonus") or "none")
        playing = _match_playing_time(str(player.get("name") or ""), playing_index)
        clauses = _decorate_clauses(player, playing)
        players_out.append(
            {
                **player,
                "appearance_bonus_label": APPEARANCE_BONUS_LABELS.get(
                    appearance, appearance
                ),
                "playing_time": playing,
                "clauses": clauses,
                "totals": _player_totals(matchday, pid),
            }
        )
    players_out.sort(
        key=lambda row: (
            str(row.get("surname") or row.get("name") or "").casefold(),
            str(row.get("first_name") or "").casefold(),
        )
    )
    return {
        "season": season or CURRENT_SEASON,
        "updated_at": store.get("updated_at"),
        "seeded_from": store.get("seeded_from"),
        "matchday_types": list(MATCHDAY_TYPES),
        "appearance_bonus_types": [
            {"id": key, "label": label} for key, label in APPEARANCE_BONUS_LABELS.items()
        ],
        "players": players_out,
        "matchday": sorted(
            matchday,
            key=lambda row: (str(row.get("date") or ""), str(row.get("player_name") or "")),
            reverse=True,
        ),
        "summary": {
            "players": len(players_out),
            "with_provisions": sum(
                1 for row in players_out if str(row.get("provisions") or "").strip()
            ),
            "appearance_bonus_players": sum(
                1
                for row in players_out
                if str(row.get("appearance_bonus") or "none") != "none"
            ),
            "thresholds_met": sum(
                1
                for row in players_out
                for clause in row.get("clauses") or []
                for step in clause.get("thresholds") or []
                if step.get("met")
            ),
            "matchday_logged": len(matchday),
            "unpaid": sum(1 for row in matchday if not row.get("paid")),
        },
        "note": (
            "Each clause is read from the contract line. Starts, apps and minutes "
            "come from Squad Availability (League Two). Players with no bonus or "
            "clause are left off this board."
        ),
    }


def upsert_player(body: PlayerUpsert) -> dict[str, Any]:
    store = _load_store()
    players = list(store.get("players") or [])
    name = body.name.strip()
    pid = (body.id or "").strip() or f"p-{uuid.uuid4().hex[:8]}"
    found = False
    for idx, row in enumerate(players):
        if str(row.get("id")) != pid:
            continue
        players[idx] = {
            **row,
            "id": pid,
            "name": name,
            "surname": (body.surname or "").strip() or row.get("surname"),
            "first_name": (body.first_name or "").strip() or row.get("first_name"),
            "appearance_bonus": body.appearance_bonus,
            "provisions": body.provisions.strip(),
            "notes": body.notes.strip(),
            "active": body.active,
        }
        found = True
        break
    if not found:
        players.append(
            {
                "id": pid,
                "name": name,
                "surname": (body.surname or "").strip() or None,
                "first_name": (body.first_name or "").strip() or None,
                "appearance_bonus": body.appearance_bonus,
                "provisions": body.provisions.strip(),
                "notes": body.notes.strip(),
                "active": body.active,
            }
        )
    store["players"] = players
    _save_store(store)
    return build_bonus_payload()


def add_matchday_bonus(body: MatchdayBonusCreate) -> dict[str, Any]:
    store = _load_store()
    players = {
        str(row.get("id")): row
        for row in (store.get("players") or [])
        if isinstance(row, dict)
    }
    player = players.get(body.player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    entry = {
        "id": f"b-{uuid.uuid4().hex[:10]}",
        "player_id": body.player_id,
        "player_name": player.get("name"),
        "date": body.date[:10],
        "opponent": body.opponent.strip(),
        "result": body.result.strip(),
        "bonus_type": body.bonus_type,
        "amount": body.amount,
        "tracking": body.tracking.strip(),
        "notes": body.notes.strip(),
        "paid": False,
        "created_at": _now(),
    }
    matchday = list(store.get("matchday") or [])
    matchday.append(entry)
    store["matchday"] = matchday
    _save_store(store)
    return build_bonus_payload()


def update_matchday_bonus(bonus_id: str, body: MatchdayBonusUpdate) -> dict[str, Any]:
    store = _load_store()
    matchday = list(store.get("matchday") or [])
    found = False
    for idx, row in enumerate(matchday):
        if str(row.get("id")) != bonus_id:
            continue
        updated = dict(row)
        if body.tracking is not None:
            updated["tracking"] = body.tracking.strip()
        if body.amount is not None:
            updated["amount"] = body.amount
        if body.notes is not None:
            updated["notes"] = body.notes.strip()
        if body.paid is not None:
            updated["paid"] = bool(body.paid)
        matchday[idx] = updated
        found = True
        break
    if not found:
        raise HTTPException(status_code=404, detail="Bonus row not found")
    store["matchday"] = matchday
    _save_store(store)
    return build_bonus_payload()


def delete_matchday_bonus(bonus_id: str) -> dict[str, Any]:
    store = _load_store()
    before = list(store.get("matchday") or [])
    after = [row for row in before if str(row.get("id")) != bonus_id]
    if len(after) == len(before):
        raise HTTPException(status_code=404, detail="Bonus row not found")
    store["matchday"] = after
    _save_store(store)
    return build_bonus_payload()


def reseed_from_excel_seed(*, replace_players: bool = False) -> dict[str, Any]:
    store = _load_store()
    seeded = _load_seed_players()
    if replace_players or not store.get("players"):
        store["players"] = seeded
    else:
        existing_ids = {str(row.get("id")) for row in store.get("players") or []}
        for row in seeded:
            if row["id"] not in existing_ids:
                store.setdefault("players", []).append(row)
    store["seeded_from"] = _resolve_seed_path().name
    _save_store(store)
    return build_bonus_payload()


def register_bonus_tracker_routes(app: FastAPI) -> None:
    page_path = STANDALONE_DIR / "bonus-tracker.html"

    @app.get("/bonus-tracker", response_class=HTMLResponse)
    def bonus_tracker_page() -> HTMLResponse:
        if not page_path.is_file():
            raise HTTPException(status_code=404, detail="Bonus Tracker UI not found.")
        return HTMLResponse(page_path.read_text(encoding="utf-8"))

    @app.get("/api/bonus-tracker")
    def bonus_tracker_get(season: str = Query(CURRENT_SEASON)) -> dict[str, Any]:
        return build_bonus_payload(season)

    @app.post("/api/bonus-tracker/reseed")
    def bonus_tracker_reseed(
        replace_players: bool = Query(False),
    ) -> dict[str, Any]:
        return reseed_from_excel_seed(replace_players=replace_players)

    @app.put("/api/bonus-tracker/player")
    def bonus_tracker_upsert_player(body: PlayerUpsert) -> dict[str, Any]:
        return upsert_player(body)

    @app.post("/api/bonus-tracker/matchday")
    def bonus_tracker_add_matchday(body: MatchdayBonusCreate) -> dict[str, Any]:
        return add_matchday_bonus(body)

    @app.patch("/api/bonus-tracker/matchday/{bonus_id}")
    def bonus_tracker_patch_matchday(
        bonus_id: str, body: MatchdayBonusUpdate
    ) -> dict[str, Any]:
        return update_matchday_bonus(bonus_id, body)

    @app.delete("/api/bonus-tracker/matchday/{bonus_id}")
    def bonus_tracker_delete_matchday(bonus_id: str) -> dict[str, Any]:
        return delete_matchday_bonus(bonus_id)
