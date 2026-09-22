"""Bonus Tracker — replaces Sam Baker first-team bonuses spreadsheet."""

from __future__ import annotations

import json
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
        out.append(
            {
                "id": str(row.get("id") or f"p-{uuid.uuid4().hex[:8]}"),
                "name": name,
                "surname": str(row.get("surname") or "").strip() or None,
                "first_name": str(row.get("first_name") or "").strip() or None,
                "appearance_bonus": appearance,
                "provisions": str(row.get("provisions") or "").strip(),
                "notes": "",
                "active": True,
            }
        )
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
    store = _load_store()
    matchday = list(store.get("matchday") or [])
    players_out: list[dict[str, Any]] = []
    for player in store.get("players") or []:
        if not isinstance(player, dict):
            continue
        if player.get("active") is False:
            continue
        pid = str(player.get("id") or "")
        appearance = str(player.get("appearance_bonus") or "none")
        players_out.append(
            {
                **player,
                "appearance_bonus_label": APPEARANCE_BONUS_LABELS.get(
                    appearance, appearance
                ),
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
            "matchday_logged": len(matchday),
            "unpaid": sum(1 for row in matchday if not row.get("paid")),
        },
        "note": (
            "Seeded from Sam Baker’s First Team Bonuses Tracker. Log matchday "
            "Appearance / Goal-Assist / Clean Sheet / Squad / Payment rows here. "
            "League starts & minutes live on Squad Availability → Playing time."
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
