"""Shared recruitment player pipelines (kanban + table)."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.apps_manifest import is_app_live
from app.auth import current_user_payload
from app.label_utils import humanize_profile_name
from app.opponent_photos import opponent_photo_api_url
from app.paths import DATA_ROOT, STANDALONE_DIR, ensure_data_dirs
from app.scouting import _format_foot, _format_height
from app.squad_planner import (
    SQUAD_PLANNER_POSITION_IDS,
    SquadPlannerPlayerRequest,
    build_squad_planner_player,
)

PIPELINES_PATH = DATA_ROOT / "player-pipelines.json"
_lock = threading.Lock()
# v3 = Impect 0–100 scores + minutes-by-position breakdown.
# v4 = Watch list mins = newest season only (not 2-season sum).
# v5 = Watch list overall = newest-season Impect avg (Who To Scout parity).
STATS_SCORE_VERSION = 5

STAGES: tuple[dict[str, Any], ...] = (
    {
        "id": "watch_list",
        "title": "Watch list",
        "hint": "Found on Who To Scout / Stand outs — not in the pipeline yet",
        "color": "#38bdf8",
        "watch_list_only": True,
    },
    {
        "id": "watched",
        "title": "Watched",
        "hint": "Scout notes only — watching, not touted to progress yet",
        "color": "#eab308",
    },
    {
        "id": "data_identified",
        "title": "Data identified",
        "hint": "On the pipeline from data — not videoed yet",
        "color": "#3d8bfd",
    },
    {
        "id": "scout_identified",
        "title": "Scout identified",
        "hint": "Scout wants to push this one forward — not videoed yet",
        "color": "#06b6d4",
    },
    {
        "id": "video_scouted",
        "title": "Video scouted",
        "hint": "Watched on video",
        "color": "#a78bfa",
    },
    {
        "id": "live_scouted",
        "title": "Live scouted",
        "hint": "Seen in person",
        "color": "#22c55e",
    },
    {
        "id": "gone_elsewhere",
        "title": "Gone / turned us down",
        "hint": "Went elsewhere or said no",
        "color": "#f59e0b",
    },
    {
        "id": "not_the_right_fit",
        "title": "Not the right fit",
        "hint": "We've decided not to pursue — a reason is required",
        "color": "#ef4444",
        "require_reason": True,
    },
)
STAGE_IDS = tuple(row["id"] for row in STAGES)
WATCH_LIST_STAGE = "watch_list"
PIPELINE_STAGE_IDS = tuple(
    row["id"] for row in STAGES if not row.get("watch_list_only")
)
STAGE_COLORS = {row["id"]: str(row["color"]) for row in STAGES}
REASON_STAGES = frozenset(
    row["id"] for row in STAGES if row.get("require_reason")
)

POSITIONS: tuple[tuple[str, str], ...] = (
    ("GOALKEEPER", "GK"),
    ("RIGHT_WINGBACK_DEFENDER", "RB"),
    ("LEFT_WINGBACK_DEFENDER", "LB"),
    ("CENTRAL_DEFENDER", "CB"),
    ("DEFENSE_MIDFIELD", "DM"),
    ("CENTRAL_MIDFIELD", "CM"),
    ("ATTACKING_MIDFIELD", "AM"),
    ("LEFT_WINGER", "LW"),
    ("RIGHT_WINGER", "RW"),
    ("CENTER_FORWARD", "ST"),
)
POSITION_LABELS = {code: short for code, short in POSITIONS}
POSITION_SECTION_TITLES: dict[str, str] = {
    "GOALKEEPER": "Goalkeepers",
    "RIGHT_WINGBACK_DEFENDER": "Right backs",
    "LEFT_WINGBACK_DEFENDER": "Left backs",
    "CENTRAL_DEFENDER": "Centre backs",
    "DEFENSE_MIDFIELD": "Defensive midfield",
    "CENTRAL_MIDFIELD": "Central midfield",
    "ATTACKING_MIDFIELD": "Attacking midfield",
    "LEFT_WINGER": "Left wing",
    "RIGHT_WINGER": "Right wing",
    "CENTER_FORWARD": "Strikers",
}


def _position_sort_key(position: Any) -> int:
    code = str(position or "").strip()
    order = [item[0] for item in POSITIONS]
    try:
        return order.index(code)
    except ValueError:
        return len(order)

DEFAULT_TAGS: tuple[str, ...] = (
    "Agent contacted",
    "Watching",
    "Priority",
    "Loan",
    "Offer made",
    "Medical",
    "Contract talks",
    "Turned us down",
    "Signed elsewhere",
)


class AddTargetBody(BaseModel):
    player_id: int | None = None
    name: str = ""
    club: str = ""
    league: str = ""
    position: str = ""
    position_label: str = ""
    age: int | None = None
    photo_url: str = ""
    stage: str = "data_identified"
    tags: list[str] = Field(default_factory=list)
    manual: bool = False
    iteration_ids: list[int] = Field(default_factory=list)
    # Optional seed from Who To Scout so add stays instant (no Impect round-trip).
    overall_score: float | None = None
    minutes: int | None = None
    top_profile: str = ""
    top_profile_score: float | None = None
    enrich: bool = False


class PromoteWatchListBody(BaseModel):
    stage: str = "data_identified"
    reason: str = ""


class RefreshStatsBody(BaseModel):
    target_ids: list[str] = Field(default_factory=list)


class MoveTargetBody(BaseModel):
    stage: str
    before_id: str | None = None
    reason: str = ""


class PatchTargetBody(BaseModel):
    tags: list[str] | None = None
    position: str | None = None
    position_label: str | None = None
    name: str | None = None
    club: str | None = None
    league: str | None = None
    age: int | None = None


class NoteBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _staff(request: Request) -> str:
    payload = current_user_payload(request)
    return str(payload.get("display_name") or payload.get("username") or "Staff").strip() or "Staff"


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "targets": []}


def _load() -> dict[str, Any]:
    ensure_data_dirs()
    if not PIPELINES_PATH.exists():
        return _empty_store()
    try:
        payload = json.loads(PIPELINES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(payload, dict):
        return _empty_store()
    targets = payload.get("targets")
    if not isinstance(targets, list):
        targets = []
    return {"version": 1, "targets": targets}


def _stage_rank(stage: str | None) -> int:
    stage_id = str(stage or "").strip()
    try:
        return STAGE_IDS.index(stage_id)
    except ValueError:
        return -1


def _dedupe_targets_by_player_id(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manual: list[dict[str, Any]] = []
    by_player: dict[int, dict[str, Any]] = {}
    for row in targets:
        if not isinstance(row, dict):
            continue
        try:
            player_id = int(row.get("player_id") or 0)
        except (TypeError, ValueError):
            player_id = 0
        if not player_id:
            manual.append(row)
            continue
        current = by_player.get(player_id)
        if current is None:
            by_player[player_id] = row
            continue
        if _stage_rank(row.get("stage")) > _stage_rank(current.get("stage")):
            by_player[player_id] = row
            continue
        if _stage_rank(row.get("stage")) == _stage_rank(current.get("stage")):
            if str(row.get("moved_at") or "") >= str(current.get("moved_at") or ""):
                by_player[player_id] = row
    return manual + list(by_player.values())


def _persist_targets(targets: list[dict[str, Any]]) -> None:
    ensure_data_dirs()
    payload = {"version": 1, "targets": _dedupe_targets_by_player_id(targets)}
    temp_path = PIPELINES_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(PIPELINES_PATH)


def _save(store: dict[str, Any]) -> None:
    with _lock:
        _persist_targets(store.get("targets") or [])


def _clean_tags(raw: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in raw or []:
        label = " ".join(str(item or "").split())[:40]
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out[:20]


def _clean_stage(value: str | None) -> str:
    stage = str(value or "").strip()
    return stage if stage in STAGE_IDS else "data_identified"


def _photo_url(name: str, club: str = "") -> str:
    url = opponent_photo_api_url(name, club_name=club or None)
    if url:
        return url
    if name:
        return f"/api/pre-match/player-photo?name={quote(name)}"
    return ""


def _discover_player_iteration_ids(player_id: int) -> list[int]:
    from app import main as impect_main

    iterations = impect_main._fetch_iterations()
    iteration_ids = impect_main._latest_iteration_ids(iterations)
    if not iteration_ids:
        return []
    players_by_iteration = impect_main._fetch_players_parallel(iteration_ids)
    found: list[int] = []
    for iteration_id in iteration_ids:
        for catalog_row in players_by_iteration.get(iteration_id, []):
            try:
                catalog_id = int(catalog_row.get("id", 0))
            except (TypeError, ValueError):
                continue
            if catalog_id == player_id:
                found.append(iteration_id)
                break
    return found


def _attach_catalog_details(row: dict[str, Any], iteration_id: int, player_id: int) -> None:
    from app import main as impect_main

    players_by_iteration = impect_main._fetch_players_parallel([iteration_id])
    for catalog_row in players_by_iteration.get(iteration_id, []):
        try:
            catalog_id = int(catalog_row.get("id", 0))
        except (TypeError, ValueError):
            continue
        if catalog_id != player_id:
            continue
        row["foot"] = _format_foot(catalog_row.get("leg"))
        row["height"] = _format_height(catalog_row)
        if row.get("age") in (None, ""):
            row["age"] = impect_main._player_age(catalog_row)
        break


def _minutes_by_position(
    *,
    player_id: int,
    iteration_id: int,
    focus_position: str,
    focus_minutes: int | None,
) -> list[dict[str, Any]]:
    """Minutes at each role, scaled so the tracked position matches Impect's figure."""
    from app.scouting import _ensure_position_shares

    focus = str(focus_position or "").strip()
    focus_mins = int(focus_minutes) if focus_minutes is not None else None
    try:
        _, shares_map = _ensure_position_shares(int(iteration_id))
    except Exception:
        shares_map = None
    shares = (shares_map or {}).get(int(player_id)) or {}

    if not shares:
        if focus and focus_mins and focus_mins > 0:
            return [
                {
                    "position": focus,
                    "label": POSITION_LABELS.get(focus, focus),
                    "minutes": focus_mins,
                }
            ]
        return []

    focus_share = float(shares.get(focus) or 0.0)
    rows: list[dict[str, Any]] = []
    if focus and focus_mins and focus_mins > 0 and focus_share > 0:
        scale = float(focus_mins) / focus_share
        for position, share in shares.items():
            minutes = int(round(float(share or 0.0) * scale))
            if minutes <= 0:
                continue
            rows.append(
                {
                    "position": position,
                    "label": POSITION_LABELS.get(position, position),
                    "minutes": minutes,
                }
            )
    else:
        total_share = sum(float(v or 0.0) for v in shares.values())
        if total_share <= 0:
            return []
        # No reliable focus minutes — still expose relative roles using share weights
        # against the focus minutes if we have them, else skip absolute numbers.
        if focus_mins and focus_mins > 0:
            for position, share in shares.items():
                minutes = int(round(focus_mins * (float(share or 0.0) / total_share)))
                if minutes <= 0:
                    continue
                rows.append(
                    {
                        "position": position,
                        "label": POSITION_LABELS.get(position, position),
                        "minutes": minutes,
                    }
                )

    rows.sort(
        key=lambda row: (
            0 if row["position"] == focus else 1,
            -int(row["minutes"]),
            str(row["label"]),
        )
    )
    return rows[:6]


def _enrich_target_stats(
    row: dict[str, Any],
    iteration_ids: list[int] | None = None,
) -> None:
    if row.get("manual") or not row.get("player_id"):
        return
    position = str(row.get("position") or "").strip()
    if position not in SQUAD_PLANNER_POSITION_IDS:
        return

    player_id = int(row["player_id"])
    name = str(row.get("name") or "")
    ids = [int(i) for i in (iteration_ids or []) if int(i) > 0]
    if not ids:
        ids = _discover_player_iteration_ids(player_id)
    if not ids:
        return

    try:
        payload = build_squad_planner_player(
            SquadPlannerPlayerRequest(
                position=position,
                player_key=f"pipeline:{row.get('id', player_id)}",
                iteration_id=ids[0],
                iteration_ids=ids,
                impect_player_id=player_id,
                name=name,
            )
        )
    except HTTPException:
        return

    # Prefer newest-season Impect profiles so Overall matches Who To Scout
    # (squad planner profileScoresImpect blends the last 2 seasons).
    scores = (
        payload.get("profileScoresImpectNewest")
        or payload.get("profileScoresImpect")
        or {}
    )
    values = [float(v) for v in scores.values() if v is not None]
    if values:
        # One decimal then display rounds — same as Who To Scout overall.
        row["overall_score"] = round(sum(values) / len(values), 1)
        top_api = max(
            (k for k, v in scores.items() if v is not None),
            key=lambda key: float(scores[key] or 0),
            default="",
        )
        row["top_profile"] = humanize_profile_name(top_api) if top_api else ""
        # Keep one decimal so a true 99.6 doesn't round up to a fake "100".
        row["top_profile_score"] = (
            round(float(scores[top_api]), 1)
            if top_api and scores.get(top_api) is not None
            else None
        )
    else:
        row["overall_score"] = None
        row["top_profile"] = ""
        row["top_profile_score"] = None

    minutes = payload.get("minutes")
    # Squad planner combines the last 2 seasons for profiles — that double-counts
    # for a Watch list "mins" column. Prefer newest season only (same as Who To Scout).
    season_slices = (
        (payload.get("scoring") or {}).get("positionMinutes")
        if isinstance(payload.get("scoring"), dict)
        else None
    )
    if isinstance(season_slices, list) and season_slices:
        try:
            newest = int(season_slices[0].get("minutes") or 0)
            if newest > 0:
                minutes = newest
        except (TypeError, ValueError, AttributeError):
            pass
    row["minutes"] = int(minutes) if minutes is not None else None
    if payload.get("club") and not str(row.get("club") or "").strip():
        row["club"] = payload["club"]
    if payload.get("league") and not str(row.get("league") or "").strip():
        row["league"] = payload["league"]
    if payload.get("positionLabel") and not str(row.get("position_label") or "").strip():
        row["position_label"] = payload["positionLabel"]

    iteration_id = payload.get("iterationId")
    if iteration_id is not None:
        _attach_catalog_details(row, int(iteration_id), player_id)
        row["minutes_by_position"] = _minutes_by_position(
            player_id=player_id,
            iteration_id=int(iteration_id),
            focus_position=position,
            focus_minutes=row.get("minutes"),
        )
    else:
        row["minutes_by_position"] = []
    row["stats_updated_at"] = _now()
    row["stats_score_version"] = STATS_SCORE_VERSION
    try:
        from app.hub_snapshots import snapshot_from_row

        snapshot_from_row(row)
    except Exception:
        pass


def _stats_need_refresh(row: dict[str, Any]) -> bool:
    if row.get("manual") or not row.get("player_id"):
        return False
    if not str(row.get("position") or "").strip():
        return False
    try:
        version = int(row.get("stats_score_version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version < STATS_SCORE_VERSION:
        return True
    return row.get("overall_score") is None or row.get("minutes") is None


def _public_target(row: dict[str, Any]) -> dict[str, Any]:
    notes = row.get("notes") if isinstance(row.get("notes"), list) else []
    name = row.get("name") or "Unknown"
    club = row.get("club") or ""
    league = row.get("league") or ""
    stage = _clean_stage(row.get("stage"))
    player_id = row.get("player_id")
    try:
        player_id_int = int(player_id) if player_id not in (None, "") else None
    except (TypeError, ValueError):
        player_id_int = None
    if player_id_int == 0:
        player_id_int = None
    manual = bool(row.get("manual")) or player_id_int is None
    return {
        "id": row.get("id"),
        "player_id": player_id_int,
        "manual": manual,
        "name": name,
        "club": club,
        "league": league,
        "position": row.get("position") or "",
        "position_label": row.get("position_label")
        or POSITION_LABELS.get(str(row.get("position") or ""), ""),
        "age": row.get("age"),
        "photo_url": _photo_url(name, club),
        "stage": stage,
        "stage_color": STAGE_COLORS.get(stage, "#3d8bfd"),
        "tags": _clean_tags(row.get("tags")),
        "added_by": row.get("added_by") or "",
        "added_at": row.get("added_at") or "",
        "moved_by": row.get("moved_by") or "",
        "moved_at": row.get("moved_at") or "",
        "close_reason": row.get("close_reason") or "",
        "close_reason_by": row.get("close_reason_by") or "",
        "close_reason_at": row.get("close_reason_at") or "",
        "sort": int(row.get("sort") or 0),
        "notes": [
            {
                "id": note.get("id"),
                "text": note.get("text") or "",
                "author": note.get("author") or "",
                "created_at": note.get("created_at") or "",
            }
            for note in notes
            if isinstance(note, dict)
        ],
        "dossier_href": f"/player/{player_id_int}" if player_id_int else "",
        "overall_score": row.get("overall_score"),
        "minutes": row.get("minutes"),
        "minutes_by_position": [
            {
                "position": item.get("position") or "",
                "label": item.get("label") or "",
                "minutes": int(item.get("minutes") or 0),
            }
            for item in (row.get("minutes_by_position") or [])
            if isinstance(item, dict) and int(item.get("minutes") or 0) > 0
        ],
        "foot": row.get("foot") or "",
        "height": row.get("height") or "",
        "top_profile": row.get("top_profile") or "",
        "top_profile_score": row.get("top_profile_score"),
        "stats_updated_at": row.get("stats_updated_at") or "",
    }


def _board_payload() -> dict[str, Any]:
    from app.hub_snapshots import apply_player_stats_to_row

    store = _load()
    dirty = False
    for row in store.get("targets") or []:
        if not isinstance(row, dict):
            continue
        if apply_player_stats_to_row(row):
            dirty = True
    if dirty:
        _save(store)
    targets = [_public_target(row) for row in store["targets"] if isinstance(row, dict)]
    targets.sort(key=lambda row: (STAGE_IDS.index(row["stage"]), row["sort"], row["name"].lower()))
    return {
        "stages": list(STAGES),
        "pipeline_stage_ids": list(PIPELINE_STAGE_IDS),
        "watch_list_stage": WATCH_LIST_STAGE,
        "positions": [{"id": code, "label": short} for code, short in POSITIONS],
        "default_tags": list(DEFAULT_TAGS),
        "targets": targets,
    }


def _next_sort(targets: list[dict[str, Any]], stage: str) -> int:
    values = [int(row.get("sort") or 0) for row in targets if row.get("stage") == stage]
    return (max(values) + 1) if values else 0


def _find_by_player(targets: list[dict[str, Any]], player_id: int) -> dict[str, Any] | None:
    if not player_id:
        return None
    for row in targets:
        try:
            existing = int(row.get("player_id") or 0)
        except (TypeError, ValueError):
            continue
        if existing and existing == player_id:
            return row
    return None


def pipeline_index_by_player_id() -> dict[int, dict[str, Any]]:
    """Public snapshot of pipeline targets keyed by Impect player id."""
    store = _load()
    out: dict[int, dict[str, Any]] = {}
    for row in _dedupe_targets_by_player_id(store.get("targets") or []):
        if not isinstance(row, dict):
            continue
        try:
            player_id = int(row.get("player_id") or 0)
        except (TypeError, ValueError):
            continue
        if player_id:
            out[player_id] = _public_target(row)
    return out


def remove_pipeline_by_player_id(player_id: int) -> dict[str, Any]:
    """Remove an Impect player from the shared pipelines board."""
    if not player_id:
        raise HTTPException(status_code=400, detail="player_id is required")
    store = _load()
    existing = _find_by_player(store["targets"], int(player_id))
    if existing is None:
        return {"removed": False, "target": None}
    target = _public_target(existing)
    store["targets"] = [
        row for row in store["targets"] if str(row.get("id") or "") != str(existing.get("id") or "")
    ]
    _save(store)
    return {"removed": True, "target": target}


def upsert_pipeline_from_scout(
    request: Request,
    *,
    player_id: int,
    name: str,
    club: str = "",
    league: str = "",
    position: str = "",
    position_label: str = "",
    age: int | None = None,
    stage: str = "data_identified",
    reason: str = "",
    only_create: bool = False,
) -> dict[str, Any]:
    """Add or move a player on the shared Player Pipelines board."""
    if not player_id:
        raise HTTPException(status_code=400, detail="player_id is required")
    staff = _staff(request)
    stage_id = _clean_stage(stage)

    with _lock:
        store = _load()
        existing = _find_by_player(store.get("targets") or [], int(player_id))
        if existing is not None and only_create:
            return {
                "created": False,
                "moved": False,
                "target": _public_target(existing),
            }
        if existing is None:
            position_code = str(position or "").strip()
            row = {
                "id": str(uuid.uuid4()),
                "player_id": int(player_id),
                "manual": False,
                "name": " ".join((name or f"Player {player_id}").split()),
                "club": " ".join((club or "").split()),
                "league": " ".join((league or "").split()),
                "position": position_code,
                "position_label": (
                    str(position_label or "").strip()
                    or POSITION_LABELS.get(position_code, "")
                ),
                "age": age,
                "photo_url": _photo_url(name, club),
                "stage": stage_id,
                "tags": [],
                "added_by": staff,
                "added_at": _now(),
                "moved_by": staff,
                "moved_at": _now(),
                "sort": _next_sort(store["targets"], stage_id),
                "notes": [],
            }
            if stage_id in REASON_STAGES:
                cleaned = " ".join(str(reason or "").split())
                if len(cleaned) < 8:
                    raise HTTPException(
                        status_code=400,
                        detail="Add a reason (at least a short sentence) before marking not the right fit.",
                    )
                row["close_reason"] = cleaned
                row["close_reason_by"] = staff
                row["close_reason_at"] = _now()
                row["notes"].append(
                    {
                        "id": str(uuid.uuid4()),
                        "text": f"Not the right fit — {cleaned}",
                        "author": staff,
                        "created_at": _now(),
                    }
                )
            if position_code and stage_id != WATCH_LIST_STAGE:
                _enrich_target_stats(row)
            store["targets"].append(row)
            _persist_targets(store["targets"])
            return {"created": True, "moved": False, "target": _public_target(row)}

        previous = _clean_stage(existing.get("stage"))
        if stage_id != previous:
            if stage_id in REASON_STAGES:
                cleaned = " ".join(str(reason or "").split())
                if len(cleaned) < 8:
                    raise HTTPException(
                        status_code=400,
                        detail="Add a reason (at least a short sentence) before marking not the right fit.",
                    )
                existing["close_reason"] = cleaned
                existing["close_reason_by"] = staff
                existing["close_reason_at"] = _now()
                notes = existing.get("notes") if isinstance(existing.get("notes"), list) else []
                notes.append(
                    {
                        "id": str(uuid.uuid4()),
                        "text": f"Not the right fit — {cleaned}",
                        "author": staff,
                        "created_at": _now(),
                    }
                )
                existing["notes"] = notes
            existing["stage"] = stage_id
            existing["moved_by"] = staff
            existing["moved_at"] = _now()
            existing["sort"] = _next_sort(
                [row for row in store["targets"] if row is not existing],
                stage_id,
            )
            _persist_targets(store["targets"])
            return {"created": False, "moved": True, "target": _public_target(existing)}

        return {"created": False, "moved": False, "target": _public_target(existing)}


def _find_by_id(targets: list[dict[str, Any]], target_id: str) -> dict[str, Any] | None:
    for row in targets:
        if str(row.get("id") or "") == target_id:
            return row
    return None


def _reorder(targets: list[dict[str, Any]], stage: str, moved_id: str, before_id: str | None) -> None:
    column = [row for row in targets if row.get("stage") == stage]
    moved = next((row for row in column if str(row.get("id")) == moved_id), None)
    if moved is None:
        return
    rest = [row for row in column if str(row.get("id")) != moved_id]
    insert_at = len(rest)
    if before_id:
        for idx, row in enumerate(rest):
            if str(row.get("id")) == before_id:
                insert_at = idx
                break
    rest.insert(insert_at, moved)
    for idx, row in enumerate(rest):
        row["sort"] = idx


def register_player_pipelines_routes(app: FastAPI) -> None:
    @app.get("/player-pipelines", response_class=HTMLResponse)
    def player_pipelines_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "player-pipelines.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Player pipelines UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/watch-list", response_class=HTMLResponse)
    def watch_list_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "watch-list.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Watch list UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/player-pipelines")
    def player_pipelines_board() -> dict[str, Any]:
        # Fast path — never block Who To Scout / hub boot on Impect enrich.
        # Missing/stale scores refresh via /api/player-pipelines/refresh-stats
        # or when opening Watch list.
        return _board_payload()

    @app.get("/api/player-pipelines/track-index")
    def player_pipelines_track_index() -> dict[str, Any]:
        """Tiny payload for Who To Scout Track chips — no enrich."""
        store = _load()
        rows: list[dict[str, Any]] = []
        for row in store.get("targets") or []:
            if not isinstance(row, dict):
                continue
            try:
                pid = int(row.get("player_id") or 0)
            except (TypeError, ValueError):
                pid = 0
            if not pid:
                continue
            rows.append(
                {
                    "id": str(row.get("id") or ""),
                    "player_id": pid,
                    "stage": _clean_stage(row.get("stage")),
                    "name": str(row.get("name") or ""),
                }
            )
        return {
            "targets": rows,
            "count": len(rows),
            "pipelines_live": is_app_live("player-pipelines"),
        }

    @app.get("/api/watch-list")
    def watch_list_board() -> dict[str, Any]:
        from app.hub_snapshots import load_meta

        payload = _board_payload()
        watch_targets = [
            row
            for row in payload["targets"]
            if str(row.get("stage") or "") == WATCH_LIST_STAGE
        ]
        watch_targets.sort(
            key=lambda row: (
                _position_sort_key(row.get("position")),
                -(float(row.get("overall_score")) if row.get("overall_score") is not None else -1),
                str(row.get("name") or "").casefold(),
            )
        )
        missing = sum(
            1
            for row in watch_targets
            if not row.get("manual")
            and row.get("player_id")
            and (row.get("overall_score") is None or row.get("minutes") is None)
        )
        return {
            **payload,
            "targets": watch_targets,
            "count": len(watch_targets),
            "stats_pending": 0,
            "stats_missing": missing,
            "snapshot": load_meta(),
            # Hide promote controls while Pipelines is held back, so nobody
            # moves a player onto a board they cannot open.
            "pipelines_live": is_app_live("player-pipelines"),
            "position_sections": [
                {"id": code, "label": short, "title": POSITION_SECTION_TITLES.get(code, short)}
                for code, short in POSITIONS
            ],
        }

    @app.post("/api/watch-list/promote/{target_id}")
    def watch_list_promote(
        request: Request,
        target_id: str,
        body: PromoteWatchListBody,
    ) -> dict[str, Any]:
        """Move a watch-list player onto a chosen pipeline stage."""
        payload = body
        store = _load()
        row = _find_by_id(store["targets"], target_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Target not found.")
        if str(row.get("stage") or "") != WATCH_LIST_STAGE:
            return {
                "promoted": False,
                "target": _public_target(row),
                "detail": "Already on the pipeline.",
            }
        stage = _clean_stage(payload.stage)
        if stage == WATCH_LIST_STAGE or stage not in PIPELINE_STAGE_IDS:
            raise HTTPException(
                status_code=400,
                detail="Pick a pipeline stage (not Watch list).",
            )
        staff = _staff(request)
        if stage in REASON_STAGES:
            reason = " ".join(str(payload.reason or "").split())
            if len(reason) < 8:
                raise HTTPException(
                    status_code=400,
                    detail="Add a reason (at least a short sentence) before moving them here.",
                )
            row["close_reason"] = reason
            row["close_reason_by"] = staff
            row["close_reason_at"] = _now()
            notes = list(row.get("notes") or [])
            notes.append(
                {
                    "id": str(uuid.uuid4()),
                    "text": f"Not the right fit — {reason}",
                    "author": staff,
                    "created_at": _now(),
                }
            )
            row["notes"] = notes
        stage_title = next(
            (str(item.get("title") or stage) for item in STAGES if item.get("id") == stage),
            stage,
        )
        row["stage"] = stage
        row["moved_by"] = staff
        row["moved_at"] = _now()
        row["sort"] = _next_sort(store["targets"], stage)
        notes = list(row.get("notes") or [])
        notes.append(
            {
                "id": str(uuid.uuid4()),
                "text": f"Moved from Watch list → {stage_title}.",
                "author": staff,
                "created_at": _now(),
            }
        )
        row["notes"] = notes
        _save(store)
        return {"promoted": True, "target": _public_target(row), "stage": stage}

    @app.get("/api/player-pipelines/status")
    def player_pipelines_status(player_id: int) -> dict[str, Any]:
        store = _load()
        row = _find_by_player(store["targets"], player_id)
        if row is None:
            return {"in_pipeline": False, "target": None}
        return {"in_pipeline": True, "target": _public_target(row)}

    @app.post("/api/player-pipelines/targets")
    def player_pipelines_add(request: Request, body: AddTargetBody) -> dict[str, Any]:
        store = _load()
        is_manual = bool(body.manual) or body.player_id in (None, 0)
        name = " ".join((body.name or "").split())
        if is_manual and not name:
            raise HTTPException(status_code=400, detail="Name is required for a manual player.")

        if not is_manual and body.player_id:
            existing = _find_by_player(store["targets"], int(body.player_id))
            if existing is not None:
                return {"created": False, "target": _public_target(existing)}

        staff = _staff(request)
        stage = _clean_stage(body.stage)
        position = str(body.position or "").strip()
        position_label = str(body.position_label or "").strip() or POSITION_LABELS.get(position, "")
        club = " ".join((body.club or "").split())
        league = " ".join((body.league or "").split())
        if not name and body.player_id:
            name = f"Player {body.player_id}"
        photo = _photo_url(name, club)
        row = {
            "id": str(uuid.uuid4()),
            "player_id": None if is_manual else int(body.player_id or 0),
            "manual": is_manual,
            "name": name,
            "club": club,
            "league": league,
            "position": position,
            "position_label": position_label,
            "age": body.age,
            "photo_url": photo,
            "stage": stage,
            "tags": _clean_tags(body.tags),
            "added_by": staff,
            "added_at": _now(),
            "moved_by": staff,
            "moved_at": _now(),
            "sort": _next_sort(store["targets"], stage),
            "notes": [],
        }
        # Prefer client-seeded scores (Who To Scout) so Watch list add is instant.
        if body.overall_score is not None:
            try:
                row["overall_score"] = round(float(body.overall_score))
            except (TypeError, ValueError):
                pass
        if body.minutes is not None:
            try:
                row["minutes"] = int(body.minutes)
            except (TypeError, ValueError):
                pass
        if str(body.top_profile or "").strip():
            row["top_profile"] = str(body.top_profile).strip()
        if body.top_profile_score is not None:
            try:
                row["top_profile_score"] = round(float(body.top_profile_score), 1)
            except (TypeError, ValueError):
                pass
        if row.get("overall_score") is not None or row.get("top_profile_score") is not None:
            # Provisional seed only — leave score version unset so Watch list can
            # still upgrade to Impect profileScoresImpect on next enrich pass.
            row["stats_updated_at"] = _now()
        elif bool(body.enrich) and not is_manual and body.player_id and position:
            # Opt-in only — default path must stay fast for Who To Scout ticks.
            _enrich_target_stats(row, body.iteration_ids)

        store["targets"].append(row)
        _save(store)
        return {"created": True, "target": _public_target(row)}

    @app.patch("/api/player-pipelines/targets/{target_id}")
    def player_pipelines_patch(
        request: Request, target_id: str, body: PatchTargetBody
    ) -> dict[str, Any]:
        store = _load()
        row = _find_by_id(store["targets"], target_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Target not found.")
        if body.tags is not None:
            row["tags"] = _clean_tags(body.tags)
        if body.name is not None:
            cleaned = " ".join(body.name.split())
            if cleaned:
                row["name"] = cleaned
        if body.club is not None:
            row["club"] = " ".join(body.club.split())
        if body.league is not None:
            row["league"] = " ".join(body.league.split())
        if body.age is not None:
            row["age"] = body.age
        if body.position is not None:
            row["position"] = str(body.position).strip()
            row["position_label"] = (
                str(body.position_label or "").strip()
                or POSITION_LABELS.get(row["position"], "")
            )
        elif body.position_label is not None:
            row["position_label"] = str(body.position_label).strip()
        if body.position is not None and row.get("player_id") and not row.get("manual"):
            _enrich_target_stats(row)
        _save(store)
        return {"target": _public_target(row)}

    @app.post("/api/player-pipelines/targets/{target_id}/move")
    def player_pipelines_move(
        request: Request, target_id: str, body: MoveTargetBody
    ) -> dict[str, Any]:
        store = _load()
        row = _find_by_id(store["targets"], target_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Target not found.")
        stage = _clean_stage(body.stage)
        if stage == WATCH_LIST_STAGE:
            raise HTTPException(
                status_code=400,
                detail="Use the Watch list for intake — do not move pipeline cards onto Watch list from this board.",
            )
        previous = _clean_stage(row.get("stage"))
        if stage in REASON_STAGES and previous != stage:
            reason = " ".join(str(body.reason or "").split())
            if len(reason) < 8:
                raise HTTPException(
                    status_code=400,
                    detail="Add a reason (at least a short sentence) before moving them here.",
                )
            staff = _staff(request)
            row["close_reason"] = reason
            row["close_reason_by"] = staff
            row["close_reason_at"] = _now()
            notes = row.get("notes") if isinstance(row.get("notes"), list) else []
            notes.append(
                {
                    "id": str(uuid.uuid4()),
                    "text": f"Not the right fit — {reason}",
                    "author": staff,
                    "created_at": _now(),
                }
            )
            row["notes"] = notes
        row["stage"] = stage
        row["moved_by"] = _staff(request)
        row["moved_at"] = _now()
        _reorder(store["targets"], stage, target_id, body.before_id)
        _save(store)
        return {"target": _public_target(row)}

    @app.delete("/api/player-pipelines/targets/{target_id}")
    def player_pipelines_delete(target_id: str) -> dict[str, bool]:
        store = _load()
        before = len(store["targets"])
        store["targets"] = [
            row for row in store["targets"] if str(row.get("id") or "") != target_id
        ]
        if len(store["targets"]) == before:
            raise HTTPException(status_code=404, detail="Target not found.")
        _save(store)
        return {"ok": True}

    @app.post("/api/player-pipelines/refresh-stats")
    def player_pipelines_refresh_stats(body: RefreshStatsBody) -> dict[str, Any]:
        store = _load()
        wanted = {str(item).strip() for item in body.target_ids if str(item).strip()}
        updated: list[dict[str, Any]] = []
        for row in store["targets"]:
            if not isinstance(row, dict):
                continue
            target_id = str(row.get("id") or "")
            if wanted and target_id not in wanted:
                continue
            if row.get("manual") or not row.get("player_id"):
                continue
            if not wanted and not _stats_need_refresh(row):
                continue
            _enrich_target_stats(row)
            updated.append(_public_target(row))
        if updated:
            _save(store)
        return {"targets": updated, "count": len(updated)}

    @app.post("/api/player-pipelines/targets/{target_id}/notes")
    def player_pipelines_add_note(
        request: Request, target_id: str, body: NoteBody
    ) -> dict[str, Any]:
        store = _load()
        row = _find_by_id(store["targets"], target_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Target not found.")
        text = " ".join(body.text.split())
        if not text:
            raise HTTPException(status_code=400, detail="Note cannot be empty.")
        notes = row.get("notes") if isinstance(row.get("notes"), list) else []
        note = {
            "id": str(uuid.uuid4()),
            "text": text,
            "author": _staff(request),
            "created_at": _now(),
        }
        notes.append(note)
        row["notes"] = notes
        _save(store)
        return {"target": _public_target(row), "note": note}
