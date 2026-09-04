"""Scoutable Teams — league → club Monday boards linked to Player Pipelines."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.auth import current_user_payload
from app.home_dashboard import STANDOUTS_LEAGUES, _overall_from_profile_scores
from app.label_utils import humanize_profile_name
from app.opponent_photos import opponent_photo_api_url
from app.paths import DATA_ROOT, STANDALONE_DIR, ensure_data_dirs
from app.player_pipelines import (
    POSITIONS,
    STAGES,
    pipeline_index_by_player_id,
    remove_pipeline_by_player_id,
    upsert_pipeline_from_scout,
)
from app.scouting import (
    POSITION_SHARE_THRESHOLD,
    SCOUTING_COMPETITION_TO_LEAGUE,
    SCOUTING_LEAGUE_TO_COMPETITION,
    _format_foot,
    _format_height,
    _get_position_shares,
    _get_primary_positions,
    _impect_profile_score,
    _normalize_profile_key,
    _profile_value_map,
    _profiles_for_position,
    _scouting_iteration_rows,
    _scouting_position_label,
)

from app.season_defaults import CURRENT_SEASON

logger = logging.getLogger(__name__)

_BOARD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SQUAD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
# The board is league → club structure, which barely moves across a season, so a
# short TTL just bought us a 6-league Impect round trip every half hour. Counts
# are attached fresh per request (_attach_board_counts), so they stay live.
_BOARD_TTL = 12 * 3600
_SQUAD_TTL = 6 * 3600
_MIN_MINUTES = 90.0
_CACHE_VERSION = 5  # no Other-profile dump; stronger primary fallback

SCOUT_NOTES_PATH = DATA_ROOT / "scoutable-teams-notes.json"
# Memory-only caching meant every deploy handed the next person a cold rebuild.
BOARD_DISK_CACHE = DATA_ROOT / "scoutable-teams-board-cache.json"
_notes_lock = threading.Lock()
WATCHED_STAGE = "watched"

LEAGUE_COLORS: dict[str, str] = {
    "League One": "#3d8bfd",
    "League Two": "#22c55e",
    "National League": "#a78bfa",
    "Scottish Prem": "#f59e0b",
    "PL2": "#06b6d4",
    "Irish Prem": "#f472b6",
}

POSITION_ORDER = [code for code, _ in POSITIONS]
POSITION_SHORT = {code: short for code, short in POSITIONS}


class SetStatusBody(BaseModel):
    player_id: int
    name: str = ""
    club: str = ""
    league: str = ""
    position: str = ""
    position_label: str = ""
    age: int | None = None
    # Empty / "none" = not on Player Pipelines.
    stage: str = ""
    reason: str = ""


class ScoutNotesBody(BaseModel):
    player_id: int
    scout_scores: dict[str, int | None] = Field(default_factory=dict)
    scout_comment: str = ""
    name: str = ""
    club: str = ""
    league: str = ""
    position: str = ""
    position_label: str = ""
    age: int | None = None


def _clean_scout_scores(raw: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        profile_key = str(key or "").strip()
        if not profile_key:
            continue
        if val is None:
            continue
        try:
            out[profile_key] = max(0, min(100, int(val)))
        except (TypeError, ValueError):
            continue
    return out


def _notes_now() -> str:
    return datetime.now(UTC).isoformat()


def _notes_staff(request: Request) -> str:
    payload = current_user_payload(request)
    return str(payload.get("display_name") or payload.get("username") or "Staff").strip() or "Staff"


def _empty_notes_store() -> dict[str, Any]:
    return {"version": 1, "notes": {}}


def _load_scout_notes_store() -> dict[str, Any]:
    ensure_data_dirs()
    if not SCOUT_NOTES_PATH.exists():
        return _empty_notes_store()
    try:
        payload = json.loads(SCOUT_NOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_notes_store()
    if not isinstance(payload, dict):
        return _empty_notes_store()
    notes = payload.get("notes")
    if not isinstance(notes, dict):
        notes = {}
    return {"version": 1, "notes": notes}


def _save_scout_notes_store(store: dict[str, Any]) -> None:
    ensure_data_dirs()
    payload = {"version": 1, "notes": store.get("notes") or {}}
    with _notes_lock:
        temp_path = SCOUT_NOTES_PATH.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(SCOUT_NOTES_PATH)


def _scout_notes_index() -> dict[int, dict[str, Any]]:
    store = _load_scout_notes_store()
    out: dict[int, dict[str, Any]] = {}
    for key, row in (store.get("notes") or {}).items():
        if not isinstance(row, dict):
            continue
        try:
            player_id = int(key)
        except (TypeError, ValueError):
            continue
        out[player_id] = row
    return out


def _player_scout_comment(player_id: int) -> str:
    row = _scout_notes_index().get(int(player_id)) or {}
    return str(row.get("scout_comment") or "").strip()


def _upsert_scout_notes(
    request: Request,
    *,
    player_id: int,
    scout_scores: dict[str, int | None] | None,
    scout_comment: str,
) -> dict[str, Any]:
    if not player_id:
        raise HTTPException(status_code=400, detail="player_id is required")
    cleaned_comment = " ".join(str(scout_comment or "").split())[:280]

    store = _load_scout_notes_store()
    notes = store.setdefault("notes", {})
    key = str(int(player_id))
    existing = notes.get(key) if isinstance(notes.get(key), dict) else {}
    merged_scores = _clean_scout_scores(scout_scores)
    staff = _notes_staff(request)
    now = _notes_now()

    if not merged_scores and not cleaned_comment:
        if key in notes:
            del notes[key]
            _save_scout_notes_store(store)
        return {
            "player_id": int(player_id),
            "scout_scores": {},
            "scout_comment": "",
            "removed": True,
        }

    row = {
        "scout_scores": merged_scores,
        "scout_comment": cleaned_comment,
        "updated_by": staff,
        "updated_at": now,
    }
    if existing.get("created_at"):
        row["created_at"] = existing["created_at"]
        row["created_by"] = existing.get("created_by") or staff
    else:
        row["created_at"] = now
        row["created_by"] = staff
    notes[key] = row
    _save_scout_notes_store(store)
    return {
        "player_id": int(player_id),
        "scout_scores": merged_scores,
        "scout_comment": cleaned_comment,
        "removed": False,
    }


def _attach_scout_notes(
    payload: dict[str, Any], notes_index: dict[int, dict[str, Any]] | None = None
) -> dict[str, Any]:
    index = notes_index if notes_index is not None else _scout_notes_index()
    for player in payload.get("players") or []:
        try:
            player_id = int(player.get("player_id") or 0)
        except (TypeError, ValueError):
            player_id = 0
        note = index.get(player_id) or {}
        player["scout_scores"] = _clean_scout_scores(note.get("scout_scores"))
        player["scout_comment"] = str(note.get("scout_comment") or "")
    return payload


def _attach_player_pipeline_status(
    payload: dict[str, Any], pipeline_index: dict[int, dict[str, Any]] | None = None
) -> dict[str, Any]:
    index = pipeline_index if pipeline_index is not None else pipeline_index_by_player_id()
    for player in payload.get("players") or []:
        target = index.get(int(player.get("player_id") or 0))
        if target:
            player["in_pipeline"] = True
            player["pipeline_stage"] = target.get("stage")
            player["pipeline_stage_title"] = next(
                (
                    stage["title"]
                    for stage in STAGES
                    if stage["id"] == target.get("stage")
                ),
                target.get("stage"),
            )
            player["pipeline_stage_color"] = next(
                (
                    stage["color"]
                    for stage in STAGES
                    if stage["id"] == target.get("stage")
                ),
                "#3d8bfd",
            )
            player["pipeline_target_id"] = target.get("id")
        else:
            player["in_pipeline"] = False
            player["pipeline_stage"] = ""
            player["pipeline_stage_title"] = ""
            player["pipeline_stage_color"] = ""
            player["pipeline_target_id"] = ""
    return payload


def _finalize_club_payload(payload: dict[str, Any]) -> dict[str, Any]:
    pipeline_index = pipeline_index_by_player_id()
    notes_index = _scout_notes_index()
    payload = _attach_scout_notes(payload, notes_index)
    return _attach_player_pipeline_status(payload, pipeline_index)


def _apply_pipeline_target_to_player(player: dict[str, Any], target: dict[str, Any]) -> None:
    stage = str(target.get("stage") or WATCHED_STAGE)
    player["in_pipeline"] = True
    player["pipeline_stage"] = stage
    player["pipeline_stage_title"] = next(
        (row["title"] for row in STAGES if row["id"] == stage),
        target.get("stage") or "Watched",
    )
    player["pipeline_stage_color"] = next(
        (row["color"] for row in STAGES if row["id"] == stage),
        target.get("stage_color") or "#eab308",
    )
    player["pipeline_target_id"] = target.get("id") or ""


def _ensure_watched_for_commented_player(
    request: Request,
    *,
    player_id: int,
    scout_comment: str,
    name: str = "",
    club: str = "",
    league: str = "",
    position: str = "",
    position_label: str = "",
    age: int | None = None,
) -> dict[str, Any] | None:
    if not player_id or not str(scout_comment or "").strip():
        return None
    result = upsert_pipeline_from_scout(
        request,
        player_id=player_id,
        name=name,
        club=club,
        league=league,
        position=position,
        position_label=position_label,
        age=age,
        stage=WATCHED_STAGE,
        only_create=True,
    )
    target = result.get("target")
    if not isinstance(target, dict):
        return None
    if result.get("created"):
        return target
    return None


def _club_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").casefold())


def _photo_url(name: str, club: str = "") -> str:
    url = opponent_photo_api_url(name, club_name=club or None)
    if url:
        return url
    from urllib.parse import quote

    if name:
        return f"/api/pre-match/player-photo?name={quote(name)}"
    return ""


def _squad_primary_and_shares(
    iteration_id: int, squad_id: int
) -> tuple[dict[int, str], dict[int, dict[str, float]], dict[int, dict[str, Any]]]:
    """Resolve positions for one club only — never scan the whole league.

    Full-league `_ensure_position_shares` hammers Impect and causes 429 /
    browser "Failed to fetch" when opening a club.
    """
    from app import main as impect

    cached_primary = _get_primary_positions(iteration_id) or {}
    cached_shares = _get_position_shares(iteration_id) or {}
    if cached_primary and cached_shares:
        return cached_primary, cached_shares, {}

    best: dict[int, tuple[float, str, dict[str, Any]]] = {}
    shares_out: dict[int, dict[str, float]] = {}
    rate_limited = False

    def fetch(position: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            rows, _ = impect._fetch_profile_scores(
                iteration_id, squad_id, [position], 0
            )
            return position, rows or []
        except HTTPException as exc:
            if int(getattr(exc, "status_code", 0) or 0) == 429:
                raise
            return position, []

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(fetch, position)
                for position in impect.ALLOWED_POSITIONS
            ]
            for future in as_completed(futures):
                position, rows = future.result()
                for row in rows:
                    try:
                        player_id = int(row.get("playerId") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not player_id:
                        continue
                    match_share = float(row.get("matchShare") or 0)
                    if match_share > 0:
                        shares_out.setdefault(player_id, {})[position] = match_share
                    current = best.get(player_id)
                    if current is None or match_share > current[0]:
                        best[player_id] = (match_share, position, row)
    except HTTPException as exc:
        if int(getattr(exc, "status_code", 0) or 0) == 429:
            rate_limited = True
        else:
            raise

    if rate_limited and not best:
        raise HTTPException(
            status_code=429,
            detail=(
                "Impect is rate-limiting right now. Wait a minute, then open "
                "the club again."
            ),
        )

    primary_out = {player_id: pos for player_id, (_, pos, _) in best.items()}
    rows_by_id = {player_id: row for player_id, (_, _, row) in best.items()}
    return primary_out, shares_out, rows_by_id


def _pick_iteration_for_competition(competition: str) -> dict[str, Any] | None:
    from app import main as impect

    with_squads: list[tuple[dict[str, Any], dict[int, str]]] = []
    for offset in (0, 1, 2):
        rows = _scouting_iteration_rows(
            [competition], season_offset=offset, combine_seasons=False
        )
        if not rows:
            continue
        iteration = rows[0]
        try:
            names = impect._fetch_squad_names(int(iteration["id"]))
        except HTTPException:
            continue
        if names:
            with_squads.append((iteration, names))

    if not with_squads:
        return None
    for iteration, names in with_squads:
        if str(iteration.get("season") or "").strip() == CURRENT_SEASON:
            return {"iteration": iteration, "squads": names}
    iteration, names = with_squads[0]
    return {"iteration": iteration, "squads": names}


def _load_board_disk(cache_key: str) -> tuple[float, dict[str, Any]] | None:
    """Board structure saved on the data volume, so it survives a redeploy."""
    try:
        if not BOARD_DISK_CACHE.exists():
            return None
        store = json.loads(BOARD_DISK_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entry = store.get(cache_key) if isinstance(store, dict) else None
    if not isinstance(entry, dict):
        return None
    payload = entry.get("payload")
    if not isinstance(payload, dict) or not payload.get("leagues"):
        return None
    return float(entry.get("saved_at") or 0), payload


def _save_board_disk(cache_key: str, payload: dict[str, Any]) -> None:
    try:
        ensure_data_dirs()
        store: dict[str, Any] = {}
        if BOARD_DISK_CACHE.exists():
            try:
                loaded = json.loads(BOARD_DISK_CACHE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    store = loaded
            except json.JSONDecodeError:
                store = {}
        store[cache_key] = {"saved_at": time.time(), "payload": payload}
        tmp = BOARD_DISK_CACHE.with_suffix(BOARD_DISK_CACHE.suffix + ".tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
        tmp.replace(BOARD_DISK_CACHE)
    except Exception:  # noqa: BLE001 - a cache write must not fail the request
        logger.exception("Failed to write scoutable teams board cache")


def build_leagues_board(*, force_refresh: bool = False) -> dict[str, Any]:
    cache_key = f"board:v{_CACHE_VERSION}"
    now = time.time()

    if not force_refresh:
        cached = _BOARD_CACHE.get(cache_key)
        if cached and now - cached[0] < _BOARD_TTL:
            return _attach_board_counts(dict(cached[1]))

        disk = _load_board_disk(cache_key)
        if disk and now - disk[0] < _BOARD_TTL:
            saved_at, payload = disk
            _BOARD_CACHE[cache_key] = (saved_at, payload)
            return _attach_board_counts(dict(payload))

    leagues: list[dict[str, Any]] = []
    for league in STANDOUTS_LEAGUES:
        competition = SCOUTING_LEAGUE_TO_COMPETITION.get(league)
        if not competition:
            continue
        picked = _pick_iteration_for_competition(competition)
        if not picked:
            leagues.append(
                {
                    "id": league,
                    "title": league,
                    "color": LEAGUE_COLORS.get(league, "#3d8bfd"),
                    "season": "",
                    "clubs": [],
                }
            )
            continue
        iteration = picked["iteration"]
        clubs = [
            {
                "id": int(squad_id),
                "name": name,
                "iteration_id": int(iteration["id"]),
                "league": league,
            }
            for squad_id, name in sorted(
                picked["squads"].items(), key=lambda item: str(item[1]).casefold()
            )
        ]
        leagues.append(
            {
                "id": league,
                "title": league,
                "color": LEAGUE_COLORS.get(league, "#3d8bfd"),
                "season": str(iteration.get("season") or ""),
                "clubs": clubs,
            }
        )

    payload = {
        "stages": list(STAGES),
        "positions": [{"id": code, "label": short} for code, short in POSITIONS],
        "leagues": leagues,
    }
    _BOARD_CACHE[cache_key] = (now, payload)
    _save_board_disk(cache_key, payload)
    return _attach_board_counts(dict(payload))


def _core_club_key(name: str) -> str:
    """Match Impect squad names to fixture planner labels (FC / AFC prefixes)."""
    key = _club_key(name)
    for prefix in ("afc", "fc", "cf", "sc"):
        if key.startswith(prefix) and len(key) > len(prefix) + 2:
            return key[len(prefix) :]
    return key


def _club_lookup_keys(name: str) -> list[str]:
    """Keys used to match Impect squad labels to fixture planner team names."""
    full = _club_key(name)
    core = _core_club_key(name)
    keys: list[str] = []
    for key in (full, core):
        if key and key not in keys:
            keys.append(key)
    return keys


def _load_fixture_assignments_for_counts() -> dict[str, Any]:
    """Assignments for watch badges — pick the richest store (Live mount on staging)."""
    from pathlib import Path

    paths: list[Path] = []
    live_path = Path("/live-data/cache/impect-fixture-planner/assignments.json")
    if live_path.exists():
        paths.append(live_path)

    env_live = str(os.environ.get("LIVE_ASSIGNMENTS_PATH") or "").strip()
    if env_live:
        paths.append(Path(env_live))

    try:
        from app.fixture_planner import ASSIGNMENTS_PATH

        paths.append(Path(ASSIGNMENTS_PATH))
    except Exception:  # noqa: BLE001
        pass

    best: dict[str, Any] = {"assignments": {}}
    best_count = -1
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        assignments = payload.get("assignments")
        if not isinstance(assignments, dict):
            continue
        count = len(assignments)
        if count > best_count:
            best = payload
            best_count = count
    return best


def _fixture_watch_counts_by_club() -> dict[str, dict[str, int]]:
    """Live / video assignment counts per club from the fixture planner store."""
    store = _load_fixture_assignments_for_counts()
    counts: dict[str, dict[str, int]] = {}
    for row in (store.get("assignments") or {}).values():
        if not isinstance(row, dict):
            continue
        watch = str(row.get("watch_type") or "").strip().upper()
        if watch not in {"LIVE", "VIDEO"}:
            continue
        for team_name in (row.get("home"), row.get("away")):
            for key in _club_lookup_keys(str(team_name or "")):
                bucket = counts.setdefault(key, {"live": 0, "video": 0})
                if watch == "LIVE":
                    bucket["live"] += 1
                else:
                    bucket["video"] += 1
    return counts


def _watch_counts_for_club(
    watch_counts: dict[str, dict[str, int]], club_name: str
) -> dict[str, int]:
    live = 0
    video = 0
    for key in _club_lookup_keys(club_name):
        row = watch_counts.get(key) or {}
        live = max(live, int(row.get("live") or 0))
        video = max(video, int(row.get("video") or 0))
    return {"live": live, "video": video, "total": live + video}


def _attach_board_counts(payload: dict[str, Any]) -> dict[str, Any]:
    index = pipeline_index_by_player_id()
    by_club: dict[str, int] = {}
    for target in index.values():
        for key in _club_lookup_keys(target.get("club") or ""):
            by_club[key] = by_club.get(key, 0) + 1

    watch_counts = _fixture_watch_counts_by_club()
    for league in payload.get("leagues") or []:
        for club in league.get("clubs") or []:
            name = str(club.get("name") or "")
            pipe = 0
            for key in _club_lookup_keys(name):
                pipe = max(pipe, by_club.get(key, 0))
            watches = _watch_counts_for_club(watch_counts, name)
            club["pipeline_count"] = pipe
            club["watch_live"] = watches["live"]
            club["watch_video"] = watches["video"]
            club["watch_total"] = watches["total"]
    return payload


def _score_row_to_player(
    *,
    row: dict[str, Any],
    catalog: dict[str, Any],
    player_id: int,
    iteration_id: int,
    club: str,
    league: str,
    season: str,
    position: str,
) -> dict[str, Any] | None:
    from app import main as impect

    values = _profile_value_map(row)
    profile_names = _profiles_for_position(position) if position else []
    profile_scores: dict[str, float | None] = {}
    if profile_names:
        for name in profile_names:
            profile_scores[name] = _impect_profile_score(
                values.get(_normalize_profile_key(name))
            )
    # Unpositioned players: still need an overall, but never dump every PV
    # profile into the UI (that blew up the "Other" group).
    if not profile_names:
        all_scores = {
            key: _impect_profile_score(raw) for key, raw in values.items()
        }
        overall_probe = _overall_from_profile_scores(all_scores)
        if overall_probe is None:
            return None
        scored_all = {k: float(v) for k, v in all_scores.items() if v is not None}
        top_api = max(scored_all, key=scored_all.get) if scored_all else ""
        name = impect._extract_player_name(catalog) or f"Player {player_id}"
        return {
            "player_id": player_id,
            "name": name,
            "age": impect._player_age(catalog),
            "height": _format_height(catalog),
            "foot": _format_foot(catalog.get("leg")),
            "club": club,
            "league": league,
            "season": season,
            "minutes": int(round(float(impect._play_duration_minutes(row) or 0))),
            "position": "",
            "position_label": "—",
            "overall": round(float(overall_probe)),
            "top_profile": humanize_profile_name(top_api) if top_api else "",
            "top_profile_score": round(scored_all[top_api]) if top_api else None,
            "profile_scores": {},
            "photo_url": _photo_url(name, club),
            "dossier_href": f"/player/{player_id}",
            "iteration_id": iteration_id,
        }
    if not any(value is not None for value in profile_scores.values()):
        return None
    overall = _overall_from_profile_scores(profile_scores)
    if overall is None:
        return None
    name = impect._extract_player_name(catalog) or f"Player {player_id}"
    top_profile = ""
    top_score = None
    scored = {k: float(v) for k, v in profile_scores.items() if v is not None}
    if scored:
        top_api = max(scored, key=scored.get)
        top_profile = humanize_profile_name(top_api)
        top_score = round(scored[top_api])
    return {
        "player_id": player_id,
        "name": name,
        "age": impect._player_age(catalog),
        "height": _format_height(catalog),
        "foot": _format_foot(catalog.get("leg")),
        "club": club,
        "league": league,
        "season": season,
        "minutes": int(round(float(impect._play_duration_minutes(row) or 0))),
        "position": position,
        "position_label": POSITION_SHORT.get(position) or _scouting_position_label(position),
        "overall": round(float(overall)),
        "top_profile": top_profile,
        "top_profile_score": top_score,
        "profile_scores": {
            name: (round(float(value)) if value is not None else None)
            for name, value in profile_scores.items()
        },
        "photo_url": _photo_url(name, club),
        "dossier_href": f"/player/{player_id}",
        "iteration_id": iteration_id,
    }


def build_club_board(
    *,
    club: str | None = None,
    squad_id: int | None = None,
    iteration_id: int | None = None,
    league: str | None = None,
) -> dict[str, Any]:
    from app import main as impect

    needle = str(club or "").strip()
    cache_key = (
        f"squad:v{_CACHE_VERSION}:"
        f"{iteration_id or 0}:{squad_id or 0}:{_club_key(needle)}:{league or ''}"
    )
    cached = _SQUAD_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _SQUAD_TTL:
        return _finalize_club_payload(dict(cached[1]))

    chosen: dict[str, Any] | None = None
    score_rows: list[dict[str, Any]] = []

    def _try_club_on_offset(offset: int, competitions: list[str]) -> bool:
        nonlocal chosen, score_rows
        for competition in competitions:
            for iteration in _scouting_iteration_rows(
                [competition], season_offset=offset, combine_seasons=False
            ):
                iid = int(iteration["id"])
                try:
                    names = impect._fetch_squad_names(iid)
                except HTTPException:
                    continue
                match = None
                for sid, squad_name in names.items():
                    if _club_key(squad_name) == _club_key(needle):
                        match = (int(sid), squad_name)
                        break
                if not match:
                    continue
                sid, club_name = match
                try:
                    rows, _ = impect._fetch_profile_scores(
                        iid, sid, list(impect.ALLOWED_POSITIONS), 0
                    )
                except HTTPException:
                    rows = []
                # Current season wins even with empty profile scores — do not
                # silently fall back to last season's full minutes.
                chosen = {
                    "iteration": iteration,
                    "iteration_id": iid,
                    "squad_id": sid,
                    "club_name": club_name,
                }
                score_rows = rows or []
                return True
        return False

    if iteration_id and squad_id:
        try:
            names = impect._fetch_squad_names(int(iteration_id))
            club_name = names.get(int(squad_id), needle or f"Squad {squad_id}")
            rows, _ = impect._fetch_profile_scores(
                int(iteration_id), int(squad_id), list(impect.ALLOWED_POSITIONS), 0
            )
            meta = next(
                (
                    item
                    for item in impect._fetch_iterations()
                    if int(item.get("id") or 0) == int(iteration_id)
                ),
                {},
            )
            chosen = {
                "iteration": meta,
                "iteration_id": int(iteration_id),
                "squad_id": int(squad_id),
                "club_name": club_name,
            }
            score_rows = rows or []
            # If the board still pointed at last season, upgrade to 26/27.
            if str(meta.get("season") or "").strip() != CURRENT_SEASON and needle:
                competitions: list[str] = []
                if league and league in SCOUTING_LEAGUE_TO_COMPETITION:
                    competitions.append(SCOUTING_LEAGUE_TO_COMPETITION[league])
                for name in STANDOUTS_LEAGUES:
                    competition = SCOUTING_LEAGUE_TO_COMPETITION.get(name)
                    if competition and competition not in competitions:
                        competitions.append(competition)
                _try_club_on_offset(0, competitions)
        except HTTPException:
            chosen = None

    if chosen is None:
        if not needle:
            raise HTTPException(status_code=400, detail="club or squad_id is required")
        competitions = []
        if league and league in SCOUTING_LEAGUE_TO_COMPETITION:
            competitions.append(SCOUTING_LEAGUE_TO_COMPETITION[league])
        for name in STANDOUTS_LEAGUES:
            competition = SCOUTING_LEAGUE_TO_COMPETITION.get(name)
            if competition and competition not in competitions:
                competitions.append(competition)
        # Current season first; only then previous — and only if club missing now.
        if not _try_club_on_offset(0, competitions):
            _try_club_on_offset(1, competitions)

    if not chosen:
        raise HTTPException(
            status_code=404,
            detail=f"No Impect squad matching “{needle or squad_id}”.",
        )

    iteration = chosen["iteration"]
    iid = int(chosen["iteration_id"])
    club_name = str(chosen["club_name"])
    competition = str(iteration.get("competition_name") or "")
    league_label = SCOUTING_COMPETITION_TO_LEAGUE.get(competition, competition) or (
        league or ""
    )
    season = str(iteration.get("season") or "")

    catalog_by_id: dict[int, dict[str, Any]] = {}
    try:
        for player in impect._fetch_players_for_iteration(iid):
            pid = player.get("id")
            if pid is not None:
                catalog_by_id[int(pid)] = player
    except HTTPException as exc:
        if int(getattr(exc, "status_code", 0) or 0) == 429:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Impect is rate-limiting right now. Wait a minute, then open "
                    "the club again."
                ),
            ) from exc
        catalog_by_id = {}

    try:
        primary, shares, rows_by_position = _squad_primary_and_shares(
            iid, int(chosen["squad_id"])
        )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        primary, shares, rows_by_position = {}, {}, {}

    # Prefer the primary-position score row when we fetched per-position.
    if rows_by_position:
        score_rows = list(rows_by_position.values())

    players: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in score_rows:
        try:
            player_id = int(row.get("playerId") or 0)
        except (TypeError, ValueError):
            continue
        if not player_id or player_id in seen:
            continue
        catalog = catalog_by_id.get(player_id) or {}
        player_shares = shares.get(player_id) or {}
        total = sum(player_shares.values()) if player_shares else 0.0
        positions: list[str] = []
        if total > 0:
            ranked = sorted(
                player_shares.items(), key=lambda item: item[1], reverse=True
            )
            positions = [
                pos
                for pos, value in ranked
                if (value / total) >= POSITION_SHARE_THRESHOLD
            ]
            # Always keep a primary even when share is below the usual threshold
            # (early-season / low minutes) so players don't dump into "Other".
            if not positions and ranked:
                positions = [ranked[0][0]]
        primary_pos = primary.get(player_id)
        if primary_pos:
            if primary_pos in positions:
                positions = [primary_pos] + [p for p in positions if p != primary_pos]
            else:
                positions.insert(0, primary_pos)
        position = positions[0] if positions else ""
        sheet = _score_row_to_player(
            row=row,
            catalog=catalog,
            player_id=player_id,
            iteration_id=iid,
            club=club_name,
            league=league_label,
            season=season,
            position=position,
        )
        if not sheet:
            continue
        if float(sheet.get("minutes") or 0) < (
            0.0 if season == CURRENT_SEASON else _MIN_MINUTES
        ):
            continue
        seen.add(player_id)
        players.append(sheet)

    players.sort(
        key=lambda row: (
            POSITION_ORDER.index(row["position"])
            if row.get("position") in POSITION_ORDER
            else 99,
            -(row.get("overall") or 0),
            str(row.get("name") or "").casefold(),
        )
    )

    profiles_by_position: dict[str, list[dict[str, str]]] = {}
    try:
        definitions = impect._fetch_player_profile_definitions()
        for code, _short in POSITIONS:
            names = [
                name
                for name, definition in definitions.items()
                if impect._is_pv_profile(name)
                and code in (definition.get("positions") or [])
            ]
            profiles_by_position[code] = [
                {"apiName": name, "label": humanize_profile_name(name)}
                for name in sorted(
                    names, key=lambda item: humanize_profile_name(item).casefold()
                )
            ]
    except Exception:  # noqa: BLE001
        for code, _short in POSITIONS:
            try:
                names = _profiles_for_position(code) or []
            except Exception:  # noqa: BLE001
                names = []
            profiles_by_position[code] = [
                {"apiName": name, "label": humanize_profile_name(name)} for name in names
            ]

    payload = {
        "club": club_name,
        "league": league_label,
        "season": season,
        "iteration_id": iid,
        "squad_id": int(chosen["squad_id"]),
        "player_count": len(players),
        "stages": list(STAGES),
        "positions": [{"id": code, "label": short} for code, short in POSITIONS],
        "profiles_by_position": profiles_by_position,
        "players": players,
    }
    _SQUAD_CACHE[cache_key] = (now, payload)
    return _finalize_club_payload(dict(payload))


def register_scoutable_teams_routes(app: FastAPI) -> None:
    @app.get("/scoutable-teams", response_class=HTMLResponse)
    def scoutable_teams_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "scoutable-teams.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Scoutable Teams UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/scoutable-teams")
    def scoutable_teams_board() -> dict[str, Any]:
        return build_leagues_board()

    @app.get("/api/scoutable-teams/club")
    def scoutable_teams_club(
        club: str | None = Query(None),
        squad_id: int | None = Query(None),
        iteration_id: int | None = Query(None),
        league: str | None = Query(None),
    ) -> dict[str, Any]:
        return build_club_board(
            club=club,
            squad_id=squad_id,
            iteration_id=iteration_id,
            league=league,
        )

    @app.post("/api/scoutable-teams/scout-notes")
    def scoutable_teams_save_notes(
        request: Request, body: ScoutNotesBody
    ) -> dict[str, Any]:
        result = _upsert_scout_notes(
            request,
            player_id=body.player_id,
            scout_scores=body.scout_scores,
            scout_comment=body.scout_comment,
        )
        if not result.get("removed") and str(result.get("scout_comment") or "").strip():
            target = _ensure_watched_for_commented_player(
                request,
                player_id=body.player_id,
                scout_comment=str(result.get("scout_comment") or ""),
                name=body.name,
                club=body.club,
                league=body.league,
                position=body.position,
                position_label=body.position_label,
                age=body.age,
            )
            if target:
                result["pipeline"] = target
        return result

    @app.post("/api/scoutable-teams/set-status")
    def scoutable_teams_set_status(
        request: Request, body: SetStatusBody
    ) -> dict[str, Any]:
        stage = str(body.stage or "").strip().lower()
        if stage == WATCHED_STAGE and not _player_scout_comment(int(body.player_id)):
            raise HTTPException(
                status_code=400,
                detail="Add scout comments before marking as Watched.",
            )
        if stage in ("", "none", "not_in_pipeline", "not-in-pipeline"):
            removed = remove_pipeline_by_player_id(int(body.player_id))
            return {
                "created": False,
                "moved": False,
                "removed": bool(removed.get("removed")),
                "target": None,
            }
        result = upsert_pipeline_from_scout(
            request,
            player_id=body.player_id,
            name=body.name,
            club=body.club,
            league=body.league,
            position=body.position,
            position_label=body.position_label,
            age=body.age,
            stage=body.stage,
            reason=body.reason,
        )
        result["removed"] = False
        return result
