"""League Two Goals Analysis — clip ingest, taxonomy coding, club profiles."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from app.auth import current_user_payload
from app.handout_badges import fotmob_crest_url_for_club
from app.paths import DATA_ROOT, STANDALONE_DIR, ensure_data_dirs
from app.post_match.config import DEFAULT_ITERATION_ID, PORT_VALE_SQUAD_ID

FOCUS_TOKENS = ("port vale",)
COMPETITION = "League Two"

ORIGIN_ORDER = ("possession", "transition", "set_play")
ORIGIN_LABELS = {
    "possession": "Possession",
    "transition": "Transition",
    "set_play": "Set play",
}
SUBTYPES: dict[str, tuple[tuple[str, str], ...]] = {
    "possession": (
        ("passing", "Passing"),
        ("crossing", "Crossing"),
        ("solo", "Solo"),
    ),
    "transition": (
        ("full_transition", "Full transition"),
        ("fifty_fifty", "50/50"),
        ("high_regain", "High regain"),
    ),
    "set_play": (
        ("corner", "Corner"),
        ("wide_free_kick", "Wide free kick"),
        ("direct_free_kick", "Direct free kick"),
        ("deep_free_kick", "Deep free kick"),
        ("long_throw", "Long throw"),
        ("penalty", "Penalty"),
    ),
}
SUBTYPE_LABELS: dict[str, str] = {
    key: label for pairs in SUBTYPES.values() for key, label in pairs
}
PHASE_ORDER = ("first", "second")
PHASE_LABELS = {"first": "1st phase", "second": "Second phase"}

CLIP_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}
MAX_CLIP_BYTES = 150 * 1024 * 1024
# Wyscout / Hudl cuts: "C. Kavanagh - Goal - Right Foot-1.mov"
WYSCOUT_RE = re.compile(
    r"^([A-Za-z])\.\s*(.+?)\s+-\s+Goal\s+-\s+(.+?)-(\d+)\s*$",
    re.I,
)
FILENAME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})_([a-z0-9-]+)_vs_([a-z0-9-]+)_(\d+)_([a-z0-9-]+)",
    re.I,
)
FINISH_LABELS = {
    "right_foot": "Right Foot",
    "left_foot": "Left Foot",
    "head": "Head",
}

# Impect adjCoordinates: attack +x (own goal -52.5 → opp +52.5), left +y.
PITCH_X_HALF = 52.5
PITCH_Y_HALF = 34.0
PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0

CODING_FIELDS = (
    "origin",
    "subtype",
    "set_play_phase",
    "goal_xy",
    "assist_xy",
    "xy_source",
    "clip_file",
    "finish_type",
    "notes",
    "coded_at",
    "coded_by",
)

_lock = threading.Lock()
_catalog_lock = threading.Lock()


class CodeBody(BaseModel):
    origin: str | None = None
    subtype: str | None = None
    set_play_phase: str | None = None
    goal_xy: dict[str, float] | None = None
    assist_xy: dict[str, float] | None = None
    notes: str = ""
    clear_assist_xy: bool = False


class ScanBody(BaseModel):
    path: str = ""


class AttachClipBody(BaseModel):
    filename: str = Field(min_length=1)


def _store_root() -> Path:
    ensure_data_dirs()
    root = DATA_ROOT / "goals-analysis"
    root.mkdir(parents=True, exist_ok=True)
    return root


def videos_dir() -> Path:
    path = DATA_ROOT / "videos" / "goals-analysis"
    path.mkdir(parents=True, exist_ok=True)
    return path


def inbox_dir() -> Path:
    path = DATA_ROOT / "inbox" / "goals-analysis"
    path.mkdir(parents=True, exist_ok=True)
    return path


def catalog_path() -> Path:
    return _store_root() / "catalog.json"


def coding_path() -> Path:
    return _store_root() / "coding.json"


def taxonomy_payload() -> dict[str, Any]:
    return {
        "origins": [{"id": key, "label": ORIGIN_LABELS[key]} for key in ORIGIN_ORDER],
        "subtypes": {
            origin: [{"id": key, "label": label} for key, label in pairs]
            for origin, pairs in SUBTYPES.items()
        },
        "phases": [{"id": key, "label": PHASE_LABELS[key]} for key in PHASE_ORDER],
        "finishes": [{"id": key, "label": label} for key, label in FINISH_LABELS.items()],
        "pitch": {
            "length": PITCH_LENGTH,
            "width": PITCH_WIDTH,
            "x_min": -PITCH_X_HALF,
            "x_max": PITCH_X_HALF,
            "y_min": -PITCH_Y_HALF,
            "y_max": PITCH_Y_HALF,
            "attack": "right",
        },
    }


def club_slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(name or "").casefold()).strip("-")
    text = re.sub(r"^(afc|fc)-", "", text)
    text = re.sub(r"-(afc|fc)$", "", text)
    text = text.replace("football-club", "").strip("-")
    return re.sub(r"-+", "-", text)


def _is_focus_club(name: str) -> bool:
    lowered = str(name or "").casefold().replace(".", "")
    return any(token in lowered for token in FOCUS_TOKENS)


def _slugs_match(left: str, right: str) -> bool:
    a, b = club_slug(left), club_slug(right)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _scorer_token_matches(scorer: str, token: str) -> bool:
    needle = club_slug(token)
    full = club_slug(scorer)
    parts = [p for p in re.split(r"[^a-z0-9]+", str(scorer or "").casefold()) if p]
    last = parts[-1] if parts else ""
    if not needle:
        return False
    return needle in {full, last} or last in needle or needle in full


def _xy_payload(coords: tuple[float, float] | None) -> dict[str, float] | None:
    if coords is None:
        return None
    x_val, y_val = coords
    return {
        "x": round(float(x_val), 2),
        "y": round(float(y_val), 2),
    }


def clamp_xy(point: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(point, dict):
        return None
    try:
        x_val = float(point.get("x"))
        y_val = float(point.get("y"))
    except (TypeError, ValueError):
        return None
    return {
        "x": round(max(-PITCH_X_HALF, min(PITCH_X_HALF, x_val)), 2),
        "y": round(max(-PITCH_Y_HALF, min(PITCH_Y_HALF, y_val)), 2),
    }


def impect_to_pitch_pct(x: float, y: float) -> tuple[float, float]:
    """Map Impect XY onto a landscape pitch attacking right (percent)."""
    x_pct = ((float(x) + PITCH_X_HALF) / PITCH_LENGTH) * 100.0
    y_pct = ((PITCH_Y_HALF - float(y)) / PITCH_WIDTH) * 100.0
    return (
        round(max(0.0, min(100.0, x_pct)), 2),
        round(max(0.0, min(100.0, y_pct)), 2),
    )


def pitch_pct_to_impect(x_pct: float, y_pct: float) -> dict[str, float]:
    x_val = (float(x_pct) / 100.0) * PITCH_LENGTH - PITCH_X_HALF
    y_val = PITCH_Y_HALF - (float(y_pct) / 100.0) * PITCH_WIDTH
    return clamp_xy({"x": x_val, "y": y_val}) or {"x": 0.0, "y": 0.0}


def goal_id_for(match_id: int, event_id: int) -> str:
    return f"m{int(match_id)}-e{int(event_id)}"


def subtype_origin(subtype: str | None) -> str | None:
    key = str(subtype or "").strip()
    for origin, pairs in SUBTYPES.items():
        if any(item == key for item, _label in pairs):
            return origin
    return None


def is_coded(row: dict[str, Any]) -> bool:
    origin = str(row.get("origin") or "").strip()
    subtype = str(row.get("subtype") or "").strip()
    if origin not in ORIGIN_LABELS:
        return False
    if subtype_origin(subtype) != origin:
        return False
    if origin == "set_play" and subtype != "penalty":
        return str(row.get("set_play_phase") or "") in PHASE_LABELS
    return True


def suggested_filename(row: dict[str, Any]) -> str:
    parts = [p for p in re.split(r"\s+", str(row.get("scorer") or "").strip()) if p]
    if not parts:
        return "A. Player - Goal - Right Foot-1.mov"
    initial = parts[0][0].upper()
    last = parts[-1]
    finish = FINISH_LABELS.get(str(row.get("finish_type") or ""), "Right Foot")
    return f"{initial}. {last} - Goal - {finish}-1.mov"


def _finish_key(label: str) -> str:
    text = re.sub(r"[^a-z]+", " ", str(label or "").casefold()).strip()
    aliases = {
        "right foot": "right_foot",
        "left foot": "left_foot",
        "head": "head",
        "header": "head",
    }
    return aliases.get(text, text.replace(" ", "_") or "")


def _name_parts(name: str) -> tuple[str, str]:
    parts = [p for p in re.split(r"[^A-Za-z]+", str(name or "")) if p]
    if not parts:
        return "", ""
    return parts[0][0].upper(), parts[-1]


def _edits(left: str, right: str) -> int:
    a, b = left.casefold(), right.casefold()
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 1:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _last_names_close(left: str, right: str) -> bool:
    a, b = str(left or "").casefold(), str(right or "").casefold()
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    if min(len(a), len(b)) < 4:
        return False
    dist = _edits(a, b)
    if dist <= 1:
        return True
    prefix = 0
    for ca, cb in zip(a, b, strict=False):
        if ca != cb:
            break
        prefix += 1
    return dist <= 2 and prefix >= 2


def parse_clip_filename(name: str) -> dict[str, Any] | None:
    stem = Path(str(name or "")).stem
    wyscout = WYSCOUT_RE.match(stem)
    if wyscout:
        last = wyscout.group(2).strip()
        finish_label = wyscout.group(3).strip()
        return {
            "kind": "wyscout",
            "initial": wyscout.group(1).upper(),
            "last": last,
            "finish": _finish_key(finish_label),
            "finish_label": finish_label,
            "seq": int(wyscout.group(4)),
        }
    match = FILENAME_RE.match(stem)
    if not match:
        return None
    return {
        "kind": "fixture",
        "date": match.group(1),
        "home": match.group(2),
        "away": match.group(3),
        "minute": int(match.group(4)),
        "scorer": match.group(5),
    }


def clip_matches_goal(parsed: dict[str, Any], goal: dict[str, Any]) -> bool:
    if parsed.get("kind") == "wyscout":
        initial, last = _name_parts(str(goal.get("scorer") or ""))
        return initial == parsed.get("initial") and _last_names_close(last, str(parsed.get("last") or ""))
    if parsed.get("kind") != "fixture":
        return False
    if str(goal.get("date") or "") != parsed["date"]:
        return False
    if int(goal.get("minute") or -1) != int(parsed["minute"]):
        return False
    if not _slugs_match(str(goal.get("home") or ""), parsed["home"]):
        return False
    if not _slugs_match(str(goal.get("away") or ""), parsed["away"]):
        return False
    return _scorer_token_matches(str(goal.get("scorer") or ""), parsed["scorer"])


def _empty_catalog() -> dict[str, Any]:
    return {
        "version": 1,
        "competition": COMPETITION,
        "iteration_id": DEFAULT_ITERATION_ID,
        "updated_at": None,
        "error": None,
        "matches": 0,
        "goals": [],
    }


def load_catalog() -> dict[str, Any]:
    path = catalog_path()
    if not path.is_file():
        return _empty_catalog()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_catalog()
    if not isinstance(payload, dict):
        return _empty_catalog()
    goals = payload.get("goals")
    if not isinstance(goals, list):
        payload["goals"] = []
    return payload


def save_catalog(payload: dict[str, Any]) -> None:
    path = catalog_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_coding() -> dict[str, dict[str, Any]]:
    path = coding_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = payload.get("goals") if isinstance(payload, dict) else payload
    if not isinstance(rows, dict):
        return {}
    return {str(key): value for key, value in rows.items() if isinstance(value, dict)}


def save_coding(store: dict[str, dict[str, Any]]) -> None:
    path = coding_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"version": 1, "updated_at": _now_iso(), "goals": store}, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _coords(point: dict[str, Any] | None) -> tuple[float, float] | None:
    from app.pre_match_goals import _coords as impect_coords

    return impect_coords(point)


def _player_id(event: dict[str, Any]) -> int:
    player = event.get("player") if isinstance(event.get("player"), dict) else {}
    try:
        return int(player.get("id") or event.get("playerId") or 0)
    except (TypeError, ValueError):
        return 0


def _match_date(match: dict[str, Any]) -> str:
    raw = str(match.get("scheduledDate") or "")[:10]
    return raw if re.match(r"^\d{4}-\d{2}-\d{2}$", raw) else ""


def _scoreline(match: dict[str, Any]) -> tuple[int | None, int | None]:
    goals = match.get("goals") or {}
    try:
        home = (goals.get("home") or {}).get("fullTime")
        away = (goals.get("away") or {}).get("fullTime")
        home_n = int(home) if home is not None else None
        away_n = int(away) if away is not None else None
        return home_n, away_n
    except (TypeError, ValueError):
        return None, None


def _minute_from_event(event: dict[str, Any]) -> tuple[int, str]:
    from app.xg_chance_analysis import _parse_impect_minute

    game_time = event.get("gameTime") if isinstance(event.get("gameTime"), dict) else {}
    raw = str(game_time.get("gameTime") or "").strip()
    try:
        minute = int(round(_parse_impect_minute(game_time)))
    except (TypeError, ValueError):
        minute = 0
    label = raw.split("(")[0].strip() if raw else str(minute)
    if ":" in label:
        label = label.split(":")[0]
    stoppage = re.search(r"\(\+(\d+)", raw)
    if stoppage:
        base = 90 if raw.startswith("90") else 45 if raw.startswith("45") else minute
        label = f"{base}+{int(stoppage.group(1))}"
    elif not label:
        label = str(minute)
    return minute, label


def goal_from_event(
    match: dict[str, Any],
    event: dict[str, Any],
    assist: dict[str, Any] | None,
    squads: dict[int, str],
    player_names: dict[int, str],
) -> dict[str, Any] | None:
    from app.pre_match import _match_day_label
    from app.pre_match_goals import _event_player_name

    try:
        match_id = int(match.get("id") or 0)
        event_id = int(event.get("id") or 0)
        scorer_team_id = int(event.get("squadId") or 0)
    except (TypeError, ValueError):
        return None
    if match_id <= 0 or event_id <= 0 or scorer_team_id <= 0:
        return None
    home_id = int(match.get("homeSquadId") or 0)
    away_id = int(match.get("awaySquadId") or 0)
    home = squads.get(home_id, f"Squad {home_id}")
    away = squads.get(away_id, f"Squad {away_id}")
    scorer_team = squads.get(scorer_team_id, f"Squad {scorer_team_id}")
    conceding_id = away_id if scorer_team_id == home_id else home_id
    conceding = squads.get(conceding_id, f"Squad {conceding_id}")
    minute, minute_label = _minute_from_event(event)
    home_goals, away_goals = _scoreline(match)
    scorer_id = _player_id(event)
    assist_id = _player_id(assist) if assist else 0
    goal_xy = _xy_payload(_coords(event.get("start")))
    assist_xy = _xy_payload(_coords((assist or {}).get("start"))) if assist else None
    return {
        "id": goal_id_for(match_id, event_id),
        "match_id": match_id,
        "event_id": event_id,
        "iteration_id": int(match.get("iterationId") or DEFAULT_ITERATION_ID),
        "match_week": int(_match_day_label(match)),
        "date": _match_date(match),
        "home": home,
        "away": away,
        "home_id": home_id,
        "away_id": away_id,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "minute": minute,
        "minute_label": minute_label,
        "scorer": _event_player_name(event, player_names) or "Unknown",
        "scorer_id": scorer_id or None,
        "scorer_team": scorer_team,
        "scorer_team_id": scorer_team_id,
        "conceding_team": conceding,
        "conceding_team_id": conceding_id,
        "assist": _event_player_name(assist, player_names) if assist else "",
        "assist_id": assist_id or None,
        "goal_xy": goal_xy,
        "assist_xy": assist_xy,
        "xy_source": "impect" if goal_xy else "",
        "focus": _is_focus_club(home) or _is_focus_club(away),
    }


def extract_goals_from_match(
    match: dict[str, Any],
    events: list[dict[str, Any]],
    squads: dict[int, str],
    player_names: dict[int, str],
) -> list[dict[str, Any]]:
    from app.pre_match_goals import _find_assist, _shot_goals

    rows: list[dict[str, Any]] = []
    for event in _shot_goals(events):
        assist = _find_assist(events, event)
        row = goal_from_event(match, event, assist, squads, player_names)
        if row:
            rows.append(row)
    rows.sort(key=lambda item: (int(item.get("minute") or 0), int(item.get("event_id") or 0)))
    return rows


def _load_league_matches(iteration_id: int) -> tuple[list[dict[str, Any]], dict[int, str]]:
    from app.club_strategy import _league_matches, _squads_map

    squads = _squads_map(iteration_id)
    matches = _league_matches(iteration_id, COMPETITION)
    return matches, squads


def _events_for_match(match_id: int) -> list[dict[str, Any]]:
    from app.xg_chance_analysis import _fetch_match_events

    return _fetch_match_events(int(match_id))


def refresh_catalog(*, iteration_id: int | None = None) -> dict[str, Any]:
    iid = int(iteration_id or DEFAULT_ITERATION_ID)
    from app.xg_chance_analysis import _player_directory

    matches, squads = _load_league_matches(iid)
    player_names = _player_directory(iid)
    goals: list[dict[str, Any]] = []
    errors: list[str] = []

    def _one(match: dict[str, Any]) -> list[dict[str, Any]]:
        mid = int(match.get("id") or 0)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                events = _events_for_match(mid)
                return extract_goals_from_match(match, events, squads, player_names)
            except Exception as exc:  # noqa: BLE001 - retry rate limits, keep the rest
                last_error = exc
                if "429" in str(exc) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
        raise last_error or RuntimeError(f"match {mid} failed")

    workers = min(8, max(1, len(matches)))
    if matches:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_one, match): match for match in matches}
            for future in as_completed(futures):
                match = futures[future]
                try:
                    goals.extend(future.result())
                except Exception as exc:  # noqa: BLE001 - keep the rest of the league
                    mid = match.get("id")
                    errors.append(f"match {mid}: {exc}")

    goals.sort(
        key=lambda row: (
            int(row.get("match_week") or 0),
            str(row.get("date") or ""),
            str(row.get("home") or ""),
            int(row.get("minute") or 0),
            str(row.get("id") or ""),
        )
    )
    payload = {
        "version": 1,
        "competition": COMPETITION,
        "iteration_id": iid,
        "updated_at": _now_iso(),
        "error": "; ".join(errors[:8]) if errors else None,
        "matches": len(matches),
        "goals": goals,
    }
    with _catalog_lock:
        save_catalog(payload)
    return payload


def merge_goal(catalog_row: dict[str, Any], coding: dict[str, Any] | None) -> dict[str, Any]:
    row = dict(catalog_row)
    overlay = coding or {}
    for field in CODING_FIELDS:
        if field not in overlay:
            continue
        value = overlay[field]
        if value in (None, ""):
            if field in {
                "origin",
                "subtype",
                "set_play_phase",
                "notes",
                "clip_file",
                "xy_source",
                "finish_type",
            }:
                row[field] = ""
            elif field in {"goal_xy", "assist_xy"}:
                row[field] = None if field == "assist_xy" else row.get(field)
            continue
        row[field] = value
    if overlay.get("assist_override") and not row.get("assist"):
        row["assist"] = overlay["assist_override"]
    if overlay.get("goal_xy"):
        row["goal_xy"] = clamp_xy(overlay["goal_xy"])
        row["xy_source"] = overlay.get("xy_source") or "manual"
    if overlay.get("assist_xy"):
        row["assist_xy"] = clamp_xy(overlay["assist_xy"])
    elif overlay.get("clear_assist_xy"):
        row["assist_xy"] = None
    row["coded"] = is_coded(row)
    row["clip_url"] = clip_url(row)
    row["has_clip"] = bool(row.get("clip_file") and clip_file_path(row))
    row["suggested_filename"] = suggested_filename(row)
    row["club_key"] = club_slug(str(row.get("scorer_team") or ""))
    row["conceding_key"] = club_slug(str(row.get("conceding_team") or ""))
    if row.get("goal_xy"):
        x_pct, y_pct = impect_to_pitch_pct(row["goal_xy"]["x"], row["goal_xy"]["y"])
        row["goal_pct"] = {"x": x_pct, "y": y_pct}
    else:
        row["goal_pct"] = None
    if row.get("assist_xy"):
        x_pct, y_pct = impect_to_pitch_pct(row["assist_xy"]["x"], row["assist_xy"]["y"])
        row["assist_pct"] = {"x": x_pct, "y": y_pct}
    else:
        row["assist_pct"] = None
    row["badge_scorer"] = fotmob_crest_url_for_club(str(row.get("scorer_team") or ""))
    row["badge_home"] = fotmob_crest_url_for_club(str(row.get("home") or ""))
    row["badge_away"] = fotmob_crest_url_for_club(str(row.get("away") or ""))
    return row


def merged_goals(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = catalog if catalog is not None else load_catalog()
    store = load_coding()
    rows = []
    for item in payload.get("goals") or []:
        if not isinstance(item, dict):
            continue
        gid = str(item.get("id") or "")
        rows.append(merge_goal(item, store.get(gid)))
    return rows


def clip_url(row: dict[str, Any]) -> str:
    if not row.get("clip_file"):
        return ""
    return f"/api/goals-analysis/clip/{row['id']}"


def clip_file_path(row: dict[str, Any]) -> Path | None:
    name = str(row.get("clip_file") or "").strip()
    if not name:
        return None
    candidate = videos_dir() / os.path.basename(name)
    return candidate if candidate.is_file() else None


def _sanitize_clip_name(filename: str) -> str:
    stem = Path(str(filename or "")).name
    stem = os.path.basename(stem)
    suffix = Path(stem).suffix.lower()
    if suffix not in CLIP_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Clips must be one of: {', '.join(sorted(CLIP_TYPES))}.",
        )
    body = Path(stem).stem
    safe = re.sub(r"[^A-Za-z0-9 ._-]", "-", body)
    safe = re.sub(r"\s+", " ", safe).strip(" .-") or "clip"
    return f"{safe}{suffix}"


def store_clip_bytes(filename: str, blob: bytes) -> str:
    if not blob:
        raise HTTPException(status_code=400, detail="That file was empty.")
    if len(blob) > MAX_CLIP_BYTES:
        cap = MAX_CLIP_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Clip is too big — keep it under {cap}MB.")
    name = _sanitize_clip_name(filename)
    target = videos_dir() / name
    target.write_bytes(blob)
    return name


def copy_clip_into_store(source: Path) -> str:
    name = _sanitize_clip_name(source.name)
    target = videos_dir() / name
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return name


def _allowed_scan_root() -> Path:
    extra = os.getenv("GOALS_ANALYSIS_SCAN_ROOT", "").strip()
    return Path(extra).expanduser().resolve() if extra else DATA_ROOT.resolve()


def resolve_scan_dir(raw: str) -> Path:
    text = str(raw or "").strip()
    if not text:
        return inbox_dir()
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = DATA_ROOT / path
    resolved = path.resolve()
    allowed = (_allowed_scan_root(), DATA_ROOT.resolve())
    if not any(resolved == root or str(resolved).startswith(str(root) + os.sep) for root in allowed):
        raise HTTPException(status_code=400, detail="Scan path must sit under the hub data folder.")
    if not resolved.is_dir():
        raise HTTPException(status_code=404, detail="That folder does not exist.")
    return resolved


def match_clip_to_goals(filename: str, goals: list[dict[str, Any]]) -> dict[str, Any] | None:
    parsed = parse_clip_filename(filename)
    if not parsed:
        return None
    hits = [goal for goal in goals if clip_matches_goal(parsed, goal)]
    return hits[0] if len(hits) == 1 else None


def assign_clips(filenames: list[str], goals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map clip filenames onto catalog goals.

    Wyscout cuts are named ``C. Kavanagh - Goal - Right Foot-2.mov`` — one player,
    a finish type, and a sequence. Zip that player's clips (seq, then finish)
    onto their catalog goals in date/minute order so -1/-2 and Head/Left Foot
    both land on the right rows.
    """
    mapping: dict[str, dict[str, Any]] = {}
    claimed: set[str] = set()
    by_file = {str(goal.get("clip_file") or ""): goal for goal in goals if goal.get("clip_file")}
    for name in filenames:
        hit = by_file.get(name)
        if hit:
            mapping[name] = hit
            claimed.add(str(hit.get("id") or ""))

    remaining = [name for name in filenames if name not in mapping]
    fixture_files: list[tuple[str, dict[str, Any]]] = []
    wyscout_groups: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for name in remaining:
        parsed = parse_clip_filename(name)
        if not parsed:
            continue
        if parsed.get("kind") == "wyscout":
            wyscout_groups[(str(parsed.get("initial") or ""), str(parsed.get("last") or "").casefold())].append(
                (name, parsed)
            )
        else:
            fixture_files.append((name, parsed))

    for name, parsed in fixture_files:
        hits = [goal for goal in goals if clip_matches_goal(parsed, goal) and str(goal.get("id") or "") not in claimed]
        if len(hits) == 1:
            mapping[name] = hits[0]
            claimed.add(str(hits[0].get("id") or ""))

    for clips in wyscout_groups.values():
        parsed0 = clips[0][1]
        candidates = [
            goal for goal in goals if clip_matches_goal(parsed0, goal) and str(goal.get("id") or "") not in claimed
        ]
        candidates.sort(
            key=lambda goal: (
                str(goal.get("date") or ""),
                int(goal.get("minute") or 0),
                int(goal.get("event_id") or 0),
            )
        )
        clips_sorted = sorted(
            clips,
            key=lambda item: (int(item[1].get("seq") or 0), str(item[1].get("finish") or ""), item[0].casefold()),
        )
        for (name, _parsed), goal in zip(clips_sorted, candidates, strict=False):
            mapping[name] = goal
            claimed.add(str(goal.get("id") or ""))
    return mapping


def apply_clip_to_goal(
    goal_id: str,
    filename: str,
    *,
    staff: str = "",
    finish_type: str = "",
) -> dict[str, Any]:
    with _lock:
        store = load_coding()
        row = dict(store.get(goal_id) or {})
        row["clip_file"] = filename
        if finish_type:
            row["finish_type"] = finish_type
        row["coded_at"] = row.get("coded_at") or _now_iso()
        if staff:
            row["coded_by"] = staff
        store[goal_id] = row
        save_coding(store)
    return row


def _finish_from_filename(filename: str) -> str:
    parsed = parse_clip_filename(filename)
    if parsed and parsed.get("kind") == "wyscout":
        return str(parsed.get("finish") or "")
    return ""


def scan_clips(directory: Path | None = None) -> dict[str, Any]:
    folder = directory or inbox_dir()
    copied = 0
    for path in sorted(folder.iterdir() if folder.is_dir() else []):
        if not path.is_file() or path.suffix.lower() not in CLIP_TYPES:
            continue
        copy_clip_into_store(path)
        copied += 1

    video_names = [
        path.name
        for path in sorted(videos_dir().iterdir())
        if path.is_file() and path.suffix.lower() in CLIP_TYPES
    ]
    goals = merged_goals()
    mapping = assign_clips(video_names, goals)
    matched: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for name in video_names:
        hit = mapping.get(name)
        if not hit:
            unmatched.append(name)
            continue
        apply_clip_to_goal(str(hit["id"]), name, finish_type=_finish_from_filename(name))
        matched.append({"goal_id": hit["id"], "file": name, "scorer": hit.get("scorer")})
    return {
        "scanned": str(folder),
        "copied": copied,
        "matched": matched,
        "unmatched": unmatched,
    }


def apply_code(goal_id: str, body: CodeBody, *, staff: str = "") -> dict[str, Any]:
    catalog = {row["id"]: row for row in (load_catalog().get("goals") or []) if isinstance(row, dict)}
    if goal_id not in catalog:
        raise HTTPException(status_code=404, detail="Unknown goal.")
    origin = str(body.origin or "").strip()
    subtype = str(body.subtype or "").strip()
    phase = str(body.set_play_phase or "").strip()
    if origin and origin not in ORIGIN_LABELS:
        raise HTTPException(status_code=400, detail="Origin must be possession, transition, or set play.")
    if subtype:
        expected = subtype_origin(subtype)
        if not expected:
            raise HTTPException(status_code=400, detail="Unknown subtype.")
        if origin and expected != origin:
            raise HTTPException(status_code=400, detail="Subtype does not belong to that origin.")
        origin = origin or expected
    if origin == "set_play" and subtype and subtype != "penalty" and phase and phase not in PHASE_LABELS:
        raise HTTPException(status_code=400, detail="Set-play phase must be 1st or second.")
    if subtype == "penalty":
        phase = ""

    with _lock:
        store = load_coding()
        row = dict(store.get(goal_id) or {})
        if origin:
            row["origin"] = origin
        if subtype:
            row["subtype"] = subtype
        if origin == "set_play":
            row["set_play_phase"] = phase
        elif origin:
            row["set_play_phase"] = ""
        if body.goal_xy is not None:
            row["goal_xy"] = clamp_xy(body.goal_xy)
            row["xy_source"] = "manual"
        if body.clear_assist_xy:
            row["assist_xy"] = None
            row["clear_assist_xy"] = True
        elif body.assist_xy is not None:
            row["assist_xy"] = clamp_xy(body.assist_xy)
            row.pop("clear_assist_xy", None)
        if body.notes or "notes" in body.model_fields_set:
            row["notes"] = str(body.notes or "")
        row["coded_at"] = _now_iso()
        if staff:
            row["coded_by"] = staff
        store[goal_id] = row
        save_coding(store)
    return merge_goal(catalog[goal_id], row)


def _count_bars(rows: list[dict[str, Any]], field: str, order: tuple[str, ...], labels: dict[str, str]) -> list[dict[str, Any]]:
    counts = Counter(str(row.get(field) or "") for row in rows if row.get(field))
    total = sum(counts.values())
    bars = []
    for key in order:
        n = int(counts.get(key, 0))
        bars.append(
            {
                "id": key,
                "label": labels.get(key, key),
                "count": n,
                "pct": round(100.0 * n / total, 1) if total else 0.0,
            }
        )
    leftover = [key for key in counts if key not in order]
    for key in leftover:
        n = int(counts[key])
        bars.append(
            {
                "id": key,
                "label": labels.get(key, key),
                "count": n,
                "pct": round(100.0 * n / total, 1) if total else 0.0,
            }
        )
    return bars


def _side_breakdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    coded = [row for row in rows if row.get("coded")]
    subtype_order = tuple(key for pairs in SUBTYPES.values() for key, _label in pairs)
    return {
        "total": len(rows),
        "coded": len(coded),
        "origins": _count_bars(coded, "origin", ORIGIN_ORDER, ORIGIN_LABELS),
        "subtypes": _count_bars(coded, "subtype", subtype_order, SUBTYPE_LABELS),
        "phases": _count_bars(
            [row for row in coded if row.get("origin") == "set_play"],
            "set_play_phase",
            PHASE_ORDER,
            PHASE_LABELS,
        ),
        "goal_points": [
            {
                "id": row["id"],
                "x": row["goal_xy"]["x"],
                "y": row["goal_xy"]["y"],
                "pct": row.get("goal_pct"),
                "label": row.get("scorer"),
            }
            for row in rows
            if row.get("goal_xy")
        ],
        "assist_points": [
            {
                "id": row["id"],
                "x": row["assist_xy"]["x"],
                "y": row["assist_xy"]["y"],
                "pct": row.get("assist_pct"),
                "label": row.get("assist") or "Assist",
            }
            for row in rows
            if row.get("assist_xy")
        ],
    }


def player_key(row: dict[str, Any]) -> str:
    scorer_id = row.get("scorer_id")
    if scorer_id:
        return str(scorer_id)
    club = club_slug(str(row.get("scorer_team") or ""))
    name = club_slug(str(row.get("scorer") or "unknown"))
    return f"{club}--{name}"


def _goal_line(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "match_week": row.get("match_week"),
        "date": row.get("date"),
        "minute": row.get("minute"),
        "minute_label": row.get("minute_label") or row.get("minute"),
        "home": row.get("home"),
        "away": row.get("away"),
        "opponent": row.get("conceding_team"),
        "scorer": row.get("scorer"),
        "scorer_team": row.get("scorer_team"),
        "assist": row.get("assist") or "",
        "origin": row.get("origin") or "",
        "subtype": row.get("subtype") or "",
        "set_play_phase": row.get("set_play_phase") or "",
        "finish_type": row.get("finish_type") or "",
        "coded": bool(row.get("coded")),
        "has_clip": bool(row.get("has_clip")),
        "clip_file": row.get("clip_file") or "",
    }


def player_summaries(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    players: dict[str, dict[str, Any]] = {}
    for row in goals:
        key = player_key(row)
        name = str(row.get("scorer") or "Unknown")
        club = str(row.get("scorer_team") or "")
        bucket = players.setdefault(
            key,
            {
                "id": key,
                "name": name,
                "club": club,
                "club_key": club_slug(club),
                "badge": fotmob_crest_url_for_club(club),
                "goals": 0,
                "coded": 0,
                "clips": 0,
                "rows": [],
            },
        )
        bucket["goals"] += 1
        if row.get("coded"):
            bucket["coded"] += 1
        if row.get("has_clip"):
            bucket["clips"] += 1
        bucket["rows"].append(_goal_line(row))
    out = list(players.values())
    out.sort(key=lambda item: (-int(item["goals"]), str(item["name"]).casefold()))
    return out


def player_profile(goals: list[dict[str, Any]], key: str) -> dict[str, Any]:
    needle = str(key or "").strip()
    rows = player_summaries([row for row in goals if player_key(row) == needle])
    if not rows:
        raise HTTPException(status_code=404, detail="No goals for that player yet.")
    return rows[0]


def _origin_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _count_bars([row for row in rows if row.get("coded")], "origin", ORIGIN_ORDER, ORIGIN_LABELS)


def league_rows(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clubs: dict[str, dict[str, Any]] = {}
    scored_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    conceded_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in goals:
        for name, side in (
            (row.get("scorer_team"), "scored"),
            (row.get("conceding_team"), "conceded"),
        ):
            key = club_slug(str(name or ""))
            if not key:
                continue
            bucket = clubs.setdefault(
                key,
                {
                    "id": key,
                    "name": name,
                    "focus": _is_focus_club(str(name or "")),
                    "badge": fotmob_crest_url_for_club(str(name or "")),
                    "scored": 0,
                    "conceded": 0,
                    "coded_scored": 0,
                    "coded_conceded": 0,
                },
            )
            if side == "scored":
                bucket["scored"] += 1
                scored_rows[key].append(row)
                if row.get("coded"):
                    bucket["coded_scored"] += 1
            else:
                bucket["conceded"] += 1
                conceded_rows[key].append(row)
                if row.get("coded"):
                    bucket["coded_conceded"] += 1
    out = []
    for key, bucket in clubs.items():
        scored = scored_rows.get(key) or []
        conceded = conceded_rows.get(key) or []
        bucket["scored_origins"] = _origin_counts(scored)
        bucket["conceded_origins"] = _origin_counts(conceded)
        bucket["gd"] = int(bucket["scored"]) - int(bucket["conceded"])
        out.append(bucket)
    out.sort(key=lambda item: (-int(item["scored"]), int(item["conceded"]), str(item["name"]).casefold()))
    return out


def club_summaries(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clubs: dict[str, dict[str, Any]] = {}
    for row in goals:
        for name, side in (
            (row.get("scorer_team"), "scored"),
            (row.get("conceding_team"), "conceded"),
        ):
            key = club_slug(str(name or ""))
            if not key:
                continue
            bucket = clubs.setdefault(
                key,
                {
                    "id": key,
                    "name": name,
                    "focus": _is_focus_club(str(name or "")),
                    "badge": fotmob_crest_url_for_club(str(name or "")),
                    "scored": 0,
                    "conceded": 0,
                    "coded_scored": 0,
                    "coded_conceded": 0,
                },
            )
            if side == "scored":
                bucket["scored"] += 1
                if row.get("coded"):
                    bucket["coded_scored"] += 1
            else:
                bucket["conceded"] += 1
                if row.get("coded"):
                    bucket["coded_conceded"] += 1
    rows = list(clubs.values())
    rows.sort(key=lambda item: (not item["focus"], str(item["name"]).casefold()))
    return rows


def club_profile(goals: list[dict[str, Any]], club_key: str) -> dict[str, Any]:
    key = club_slug(club_key)
    scored = [row for row in goals if club_slug(str(row.get("scorer_team") or "")) == key]
    conceded = [row for row in goals if club_slug(str(row.get("conceding_team") or "")) == key]
    if not scored and not conceded:
        raise HTTPException(status_code=404, detail="No goals for that club yet.")
    name = str((scored or conceded)[0].get("scorer_team" if scored else "conceding_team") or club_key)
    if scored:
        name = str(scored[0].get("scorer_team") or name)
    elif conceded:
        name = str(conceded[0].get("conceding_team") or name)
    return {
        "id": key,
        "name": name,
        "focus": _is_focus_club(name),
        "badge": fotmob_crest_url_for_club(name),
        "scored": {**_side_breakdown(scored), "goals": scored},
        "conceded": {**_side_breakdown(conceded), "goals": conceded},
        "players": player_summaries(scored),
    }


def weeks_payload(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in goals:
        grouped[int(row.get("match_week") or 0)].append(row)
    weeks = []
    for week in sorted(k for k in grouped if k > 0):
        rows = grouped[week]
        fixtures = {(row.get("match_id"), row.get("home"), row.get("away")) for row in rows}
        weeks.append(
            {
                "week": week,
                "goals": len(rows),
                "fixtures": len(fixtures),
                "coded": sum(1 for row in rows if row.get("coded")),
                "clips": sum(1 for row in rows if row.get("has_clip")),
                "focus_goals": sum(1 for row in rows if row.get("focus")),
            }
        )
    return weeks


def build_payload() -> dict[str, Any]:
    catalog = load_catalog()
    goals = merged_goals(catalog)
    return {
        "competition": COMPETITION,
        "iteration_id": catalog.get("iteration_id") or DEFAULT_ITERATION_ID,
        "updated_at": catalog.get("updated_at"),
        "error": catalog.get("error"),
        "matches": int(catalog.get("matches") or 0),
        "needs_refresh": not goals,
        "taxonomy": taxonomy_payload(),
        "weeks": weeks_payload(goals),
        "clubs": club_summaries(goals),
        "league": league_rows(goals),
        "players": player_summaries(goals),
        "goals": goals,
        "totals": {
            "goals": len(goals),
            "coded": sum(1 for row in goals if row.get("coded")),
            "clips": sum(1 for row in goals if row.get("has_clip")),
            "weeks": len(weeks_payload(goals)),
        },
    }


def _norm_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _find_csv_goal(goals: list[dict[str, Any]], row: dict[str, str]) -> dict[str, Any] | None:
    date = str(row.get("date") or "").strip()[:10]
    minute_raw = str(row.get("minute") or "").strip()
    try:
        minute = int(re.sub(r"[^0-9].*$", "", minute_raw) or 0)
    except ValueError:
        minute = 0
    home = _norm_name(row.get("home") or "")
    away = _norm_name(row.get("away") or "")
    scorer = _norm_name(row.get("scorer") or "")
    hits = []
    for goal in goals:
        if date and str(goal.get("date") or "") != date:
            continue
        if minute and int(goal.get("minute") or 0) != minute:
            continue
        if home and _norm_name(goal.get("home") or "") != home and not _slugs_match(str(goal.get("home") or ""), str(row.get("home") or "")):
            continue
        if away and _norm_name(goal.get("away") or "") != away and not _slugs_match(str(goal.get("away") or ""), str(row.get("away") or "")):
            continue
        if scorer and not _scorer_token_matches(str(goal.get("scorer") or ""), str(row.get("scorer") or "")):
            continue
        hits.append(goal)
    return hits[0] if len(hits) == 1 else None


def _csv_origin(value: str) -> str:
    text = str(value or "").strip().casefold().replace("-", " ").replace("_", " ")
    mapping = {
        "possession": "possession",
        "transition": "transition",
        "set play": "set_play",
        "setplay": "set_play",
        "set_play": "set_play",
    }
    return mapping.get(text, "")


def _csv_subtype(value: str) -> str:
    text = str(value or "").strip().casefold().replace("-", " ").replace("_", " ")
    aliases = {
        "passing": "passing",
        "crossing": "crossing",
        "solo": "solo",
        "full transition": "full_transition",
        "full": "full_transition",
        "50/50": "fifty_fifty",
        "50 50": "fifty_fifty",
        "fifty fifty": "fifty_fifty",
        "high regain": "high_regain",
        "corner": "corner",
        "corners": "corner",
        "wide free kick": "wide_free_kick",
        "wide fk": "wide_free_kick",
        "direct free kick": "direct_free_kick",
        "direct fk": "direct_free_kick",
        "deep free kick": "deep_free_kick",
        "deep fk": "deep_free_kick",
        "long throw": "long_throw",
        "penalty": "penalty",
        "penalties": "penalty",
    }
    return aliases.get(text, "")


def _csv_phase(value: str) -> str:
    text = str(value or "").strip().casefold()
    if text in {"1", "1st", "first", "1st phase", "first phase"}:
        return "first"
    if text in {"2", "2nd", "second", "2nd phase", "second phase"}:
        return "second"
    return ""


def import_csv_text(raw: str, *, staff: str = "") -> dict[str, Any]:
    text = raw.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV needs a header row.")
    goals = merged_goals()
    applied = 0
    missed = 0
    for row in reader:
        lowered = {str(k or "").strip().casefold(): str(v or "").strip() for k, v in row.items()}
        hit = _find_csv_goal(goals, lowered)
        if not hit:
            missed += 1
            continue
        origin = _csv_origin(lowered.get("origin") or "")
        subtype = _csv_subtype(lowered.get("subtype") or lowered.get("type") or "")
        phase = _csv_phase(lowered.get("set_play_phase") or lowered.get("phase") or "")
        goal_xy = None
        assist_xy = None
        if lowered.get("goal_x") and lowered.get("goal_y"):
            goal_xy = clamp_xy({"x": lowered["goal_x"], "y": lowered["goal_y"]})
        if lowered.get("assist_x") and lowered.get("assist_y"):
            assist_xy = clamp_xy({"x": lowered["assist_x"], "y": lowered["assist_y"]})
        apply_code(
            str(hit["id"]),
            CodeBody(
                origin=origin or None,
                subtype=subtype or None,
                set_play_phase=phase or None,
                goal_xy=goal_xy,
                assist_xy=assist_xy,
                notes=lowered.get("notes") or "",
            ),
            staff=staff,
        )
        if lowered.get("assist") and not hit.get("assist"):
            with _lock:
                store = load_coding()
                overlay = dict(store.get(hit["id"]) or {})
                overlay["assist_override"] = lowered["assist"]
                store[hit["id"]] = overlay
                save_coding(store)
        applied += 1
    return {"applied": applied, "missed": missed}


def _event_match_id(event: dict[str, Any], fallback: int | None) -> int:
    for key in ("matchId", "match_id", "matchid"):
        try:
            value = int(event.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value:
            return value
    return int(fallback or 0)


def stamp_impect_xy(payload: Any, *, match_id: int | None = None) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    if isinstance(payload, list):
        events = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        nested = payload.get("events") or payload.get("data") or payload.get("goals")
        if isinstance(nested, list):
            events = [item for item in nested if isinstance(item, dict)]
        elif payload.get("id") and payload.get("start"):
            events = [payload]
        try:
            match_id = int(payload.get("matchId") or payload.get("match_id") or match_id or 0) or match_id
        except (TypeError, ValueError):
            pass
    catalog_rows = {
        (int(row.get("match_id") or 0), int(row.get("event_id") or 0)): row
        for row in (load_catalog().get("goals") or [])
        if isinstance(row, dict)
    }
    stamped = 0
    missed = 0
    with _lock:
        store = load_coding()
        for event in events:
            mid = _event_match_id(event, match_id)
            try:
                eid = int(event.get("id") or event.get("eventId") or event.get("event_id") or 0)
            except (TypeError, ValueError):
                eid = 0
            key = (mid, eid)
            row = catalog_rows.get(key)
            if not row:
                missed += 1
                continue
            goal_xy = clamp_xy(_xy_payload(_coords(event.get("start") or event.get("goal") or event)))
            assist_block = event.get("assist") if isinstance(event.get("assist"), dict) else None
            assist_xy = clamp_xy(_xy_payload(_coords((assist_block or {}).get("start") or assist_block)))
            overlay = dict(store.get(row["id"]) or {})
            if goal_xy:
                overlay["goal_xy"] = goal_xy
                overlay["xy_source"] = "impect"
                stamped += 1
            if assist_xy:
                overlay["assist_xy"] = assist_xy
            store[str(row["id"])] = overlay
        save_coding(store)
    return {"stamped": stamped, "missed": missed}


def list_video_files() -> list[dict[str, Any]]:
    goals = merged_goals()
    names = [
        path.name
        for path in sorted(videos_dir().iterdir())
        if path.is_file() and path.suffix.lower() in CLIP_TYPES
    ]
    by_file = {str(row.get("clip_file") or ""): row for row in goals if row.get("clip_file")}
    mapping = assign_clips(names, goals)
    rows = []
    for path in sorted(videos_dir().iterdir()):
        if not path.is_file() or path.suffix.lower() not in CLIP_TYPES:
            continue
        hit = by_file.get(path.name) or mapping.get(path.name)
        rows.append(
            {
                "filename": path.name,
                "bytes": path.stat().st_size,
                "goal_id": hit.get("id") if hit else None,
                "label": (
                    f"{hit.get('scorer')} {hit.get('minute_label')}' vs {hit.get('conceding_team')}"
                    if hit
                    else "Unmatched"
                ),
            }
        )
    return rows


def _csv_response(filename: str, headers: list[str], rows: list[list[Any]]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-") or "goals.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


def _bar_count(bars: list[dict[str, Any]] | None, origin_id: str) -> int:
    for bar in bars or []:
        if bar.get("id") == origin_id:
            return int(bar.get("count") or 0)
    return 0


def _coding_cells(goal: dict[str, Any]) -> list[str]:
    origin = str(goal.get("origin") or "")
    subtype = str(goal.get("subtype") or "")
    phase = str(goal.get("set_play_phase") or "")
    finish = str(goal.get("finish_type") or "")
    return [
        ORIGIN_LABELS.get(origin, origin),
        SUBTYPE_LABELS.get(subtype, subtype),
        PHASE_LABELS.get(phase, phase),
        FINISH_LABELS.get(finish, finish),
        str(goal.get("clip_file") or ""),
    ]


def export_league_csv(goals: list[dict[str, Any]] | None = None) -> Response:
    rows = league_rows(goals if goals is not None else merged_goals())
    body = []
    for club in rows:
        scored = club.get("scored_origins")
        conceded = club.get("conceded_origins")
        body.append(
            [
                club.get("name"),
                club.get("scored"),
                club.get("conceded"),
                club.get("gd"),
                club.get("coded_scored"),
                club.get("coded_conceded"),
                _bar_count(scored, "possession"),
                _bar_count(scored, "transition"),
                _bar_count(scored, "set_play"),
                _bar_count(conceded, "possession"),
                _bar_count(conceded, "transition"),
                _bar_count(conceded, "set_play"),
            ]
        )
    return _csv_response(
        "league-two-goals.csv",
        [
            "Club",
            "Scored",
            "Conceded",
            "GD",
            "Coded scored",
            "Coded conceded",
            "Possession scored",
            "Transition scored",
            "Set play scored",
            "Possession conceded",
            "Transition conceded",
            "Set play conceded",
        ],
        body,
    )


def export_team_csv(club_key: str, goals: list[dict[str, Any]] | None = None) -> Response:
    profile = club_profile(goals if goals is not None else merged_goals(), club_key)
    body: list[list[Any]] = []
    for player in profile.get("players") or []:
        lines = player.get("rows") or []
        if not lines:
            body.append([player.get("name"), player.get("goals"), "", "", "", "", "", "", "", "", "", ""])
            continue
        for index, goal in enumerate(lines):
            body.append(
                [
                    player.get("name") if index == 0 else "",
                    player.get("goals") if index == 0 else "",
                    f"MW{goal.get('match_week')}",
                    goal.get("date"),
                    goal.get("minute_label"),
                    goal.get("opponent"),
                    goal.get("assist"),
                    *_coding_cells(goal),
                ]
            )
    slug = club_slug(str(profile.get("name") or club_key)) or "club"
    return _csv_response(
        f"{slug}-goals.csv",
        [
            "Player",
            "Goals scored",
            "Week",
            "Date",
            "Minute",
            "Opponent",
            "Assist",
            "Origin",
            "Type",
            "Phase",
            "Finish",
            "Clip",
        ],
        body,
    )


def export_players_csv(player_id: str | None = None, goals: list[dict[str, Any]] | None = None) -> Response:
    all_goals = goals if goals is not None else merged_goals()
    players = [player_profile(all_goals, player_id)] if player_id else player_summaries(all_goals)
    body: list[list[Any]] = []
    for player in players:
        lines = player.get("rows") or [{}]
        for index, goal in enumerate(lines):
            body.append(
                [
                    player.get("name") if index == 0 else "",
                    player.get("club") if index == 0 else "",
                    player.get("goals") if index == 0 else "",
                    f"MW{goal.get('match_week')}" if goal.get("match_week") else "",
                    goal.get("date") or "",
                    goal.get("minute_label") or "",
                    goal.get("opponent") or "",
                    goal.get("assist") or "",
                    *_coding_cells(goal),
                ]
            )
    filename = "league-two-scorers.csv"
    if player_id and players:
        filename = f"{club_slug(str(players[0].get('name') or 'player'))}-goals.csv"
    return _csv_response(
        filename,
        [
            "Player",
            "Club",
            "Goals",
            "Week",
            "Date",
            "Minute",
            "Opponent",
            "Assist",
            "Origin",
            "Type",
            "Phase",
            "Finish",
            "Clip",
        ],
        body,
    )


def _staff_name(request: Request) -> str:
    try:
        payload = current_user_payload(request)
    except Exception:  # noqa: BLE001
        return ""
    return str(payload.get("display_name") or payload.get("username") or "")


def register_goals_analysis_routes(app: FastAPI) -> None:
    page_path = STANDALONE_DIR / "goals-analysis.html"

    @app.get("/goals-analysis", response_class=HTMLResponse)
    def goals_analysis_page() -> HTMLResponse:
        if not page_path.is_file():
            raise RuntimeError(f"Missing page: {page_path}")
        return HTMLResponse(page_path.read_text(encoding="utf-8"))

    @app.get("/api/goals-analysis")
    def goals_analysis_payload() -> dict[str, Any]:
        return build_payload()

    @app.post("/api/goals-analysis/refresh")
    def goals_analysis_refresh() -> dict[str, Any]:
        refresh_catalog()
        return build_payload()

    @app.get("/api/goals-analysis/teams/{club_key}")
    def goals_analysis_team(club_key: str) -> dict[str, Any]:
        return club_profile(merged_goals(), club_key)

    @app.get("/api/goals-analysis/players/{player_id}")
    def goals_analysis_player(player_id: str) -> dict[str, Any]:
        return player_profile(merged_goals(), player_id)

    @app.get("/api/goals-analysis/export/league.csv")
    def goals_analysis_export_league() -> Response:
        return export_league_csv()

    @app.get("/api/goals-analysis/export/team/{club_key}")
    def goals_analysis_export_team(club_key: str) -> Response:
        return export_team_csv(club_key)

    @app.get("/api/goals-analysis/export/players.csv")
    def goals_analysis_export_players() -> Response:
        return export_players_csv()

    @app.get("/api/goals-analysis/export/player/{player_id}")
    def goals_analysis_export_player(player_id: str) -> Response:
        return export_players_csv(player_id)

    @app.patch("/api/goals-analysis/goals/{goal_id}")
    def goals_analysis_code(goal_id: str, body: CodeBody, request: Request) -> dict[str, Any]:
        return apply_code(goal_id, body, staff=_staff_name(request))

    @app.post("/api/goals-analysis/videos/scan")
    def goals_analysis_scan(body: ScanBody) -> dict[str, Any]:
        folder = resolve_scan_dir(body.path)
        return scan_clips(folder)

    @app.get("/api/goals-analysis/videos")
    def goals_analysis_videos() -> dict[str, Any]:
        return {"files": list_video_files(), "inbox": str(inbox_dir())}

    @app.post("/api/goals-analysis/videos")
    async def goals_analysis_upload(files: list[UploadFile] = File(...)) -> dict[str, Any]:
        stored: list[str] = []
        for upload in files:
            blob = await upload.read()
            stored.append(store_clip_bytes(upload.filename or "clip.mp4", blob))
        inbox_dir()
        result = scan_clips(videos_dir())
        result["uploaded"] = stored
        return result

    @app.post("/api/goals-analysis/goals/{goal_id}/clip")
    async def goals_analysis_attach_clip(
        goal_id: str,
        request: Request,
        file: UploadFile | None = File(None),
    ) -> dict[str, Any]:
        catalog = {row["id"]: row for row in (load_catalog().get("goals") or []) if isinstance(row, dict)}
        if goal_id not in catalog:
            raise HTTPException(status_code=404, detail="Unknown goal.")
        if file is None:
            raise HTTPException(status_code=400, detail="Attach an mp4.")
        blob = await file.read()
        name = store_clip_bytes(file.filename or f"{goal_id}.mp4", blob)
        apply_clip_to_goal(
            goal_id,
            name,
            staff=_staff_name(request),
            finish_type=_finish_from_filename(file.filename or name),
        )
        return merge_goal(catalog[goal_id], load_coding().get(goal_id))

    @app.post("/api/goals-analysis/goals/{goal_id}/clip/link")
    def goals_analysis_link_clip(goal_id: str, body: AttachClipBody, request: Request) -> dict[str, Any]:
        name = os.path.basename(body.filename)
        if not (videos_dir() / name).is_file():
            raise HTTPException(status_code=404, detail="That clip is not in the store.")
        apply_clip_to_goal(
            goal_id,
            name,
            staff=_staff_name(request),
            finish_type=_finish_from_filename(name),
        )
        catalog = next(
            (row for row in (load_catalog().get("goals") or []) if isinstance(row, dict) and row.get("id") == goal_id),
            None,
        )
        if not catalog:
            raise HTTPException(status_code=404, detail="Unknown goal.")
        return merge_goal(catalog, load_coding().get(goal_id))

    @app.get("/api/goals-analysis/clip/{goal_id}")
    def goals_analysis_stream(goal_id: str) -> FileResponse:
        row = next((item for item in merged_goals() if item.get("id") == goal_id), None)
        if not row:
            raise HTTPException(status_code=404, detail="Unknown goal.")
        path = clip_file_path(row)
        if path is None:
            raise HTTPException(status_code=404, detail="No clip attached.")
        media = CLIP_TYPES.get(path.suffix.lower(), "video/mp4")
        return FileResponse(path, media_type=media)

    @app.post("/api/goals-analysis/import/csv")
    async def goals_analysis_import_csv(request: Request, file: UploadFile | None = File(None)) -> dict[str, Any]:
        if file is None:
            raise HTTPException(status_code=400, detail="Upload a CSV.")
        raw = (await file.read()).decode("utf-8", errors="replace")
        return import_csv_text(raw, staff=_staff_name(request))

    @app.post("/api/goals-analysis/import/impect")
    async def goals_analysis_import_impect(
        file: UploadFile | None = File(None),
        match_id: int | None = Query(None),
    ) -> dict[str, Any]:
        if file is None:
            raise HTTPException(status_code=400, detail="Upload Impect JSON.")
        try:
            payload = json.loads((await file.read()).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="JSON is not valid.") from exc
        return stamp_impect_xy(payload, match_id=match_id)
