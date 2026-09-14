"""Transfer Centre — summer-market board + transfer-report dashboard."""

from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.auth import current_user_payload
from app.efl_transfer_report import load_report
from app.paths import DATA_ROOT, HUB_ROOT, STANDALONE_DIR, ensure_data_dirs

BOARD_PATH = DATA_ROOT / "transfer-centre-board.json"
POSITION_CACHE_NAME = "transfer-centre-positions.json"
POSITION_CACHE_TTL_SECONDS = 7 * 24 * 3600
_lock = threading.Lock()
_position_warm_lock = threading.Lock()
_position_warm_started = False

FLAGS: tuple[dict[str, str], ...] = (
    {
        "id": "manager_liked",
        "label": "Manager liked",
        "short": "Manager",
        "color": "#22c55e",
    },
    {
        "id": "recruitment_liked",
        "label": "Recruitment team liked",
        "short": "Rec team",
        "color": "#3d8bfd",
    },
    {
        "id": "too_expensive_transfer",
        "label": "Too expensive transfer",
        "short": "£ fee",
        "color": "#f59e0b",
    },
    {
        "id": "too_expensive_wages",
        "label": "Too expensive wages",
        "short": "£ wages",
        "color": "#f97316",
    },
    {
        "id": "player_turned_down",
        "label": "Player turned down",
        "short": "Turned down",
        "color": "#ef4444",
    },
)
FLAG_IDS = tuple(row["id"] for row in FLAGS)

INTEREST_OPTIONS: tuple[dict[str, Any], ...] = (
    {"id": "interested", "label": "Interested", "out": False},
    {"id": "not_interested", "label": "Not interested", "out": True},
    {"id": "unrealistic", "label": "Unrealistic", "out": True},
    # The board lists every club's signings, so our own departures appear on it
    # too — Stockley to Wimbledon, Shipley to Cheltenham, Clark to Swindon.
    # Those are settled business, not players we looked at and passed on.
    {"id": "released_by_us", "label": "Released / transferred by us", "out": True},
)
INTEREST_IDS = tuple(row["id"] for row in INTEREST_OPTIONS)
# Off the list of live targets, which is what dims the row. Derived from the
# options themselves so the board and the browser cannot drift apart.
OUT_INTEREST = frozenset(row["id"] for row in INTEREST_OPTIONS if row["out"])

POSITIONS: tuple[str, ...] = (
    "GK",
    "RB",
    "RWB",
    "CB",
    "LB",
    "LWB",
    "DM",
    "CM",
    "AM",
    "RW",
    "LW",
    "ST",
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_NAME_JUNK_RE = re.compile(
    r"\s*(?:re-?sign(?:ing|s|ed)?(?:\s+for\s+the\s+new\s+season)?|"
    r"for\s+the\s+new\s+season|returns?(?:\s+to\b.*)?|"
    r"loan(?:\s+spell)?\s+ended)\s*$",
    re.I,
)
IMPECT_TO_BOARD: dict[str, str] = {
    "GOALKEEPER": "GK",
    "LEFT_WINGBACK_DEFENDER": "LB",
    "RIGHT_WINGBACK_DEFENDER": "RB",
    "CENTRAL_DEFENDER": "CB",
    "DEFENSE_MIDFIELD": "DM",
    "CENTRAL_MIDFIELD": "CM",
    "ATTACKING_MIDFIELD": "AM",
    "LEFT_WINGER": "LW",
    "RIGHT_WINGER": "RW",
    "CENTER_FORWARD": "ST",
    "GK": "GK",
    "LB": "LB",
    "LWB": "LWB",
    "RB": "RB",
    "RWB": "RWB",
    "CB": "CB",
    "DM": "DM",
    "CM": "CM",
    "AM": "AM",
    "LW": "LW",
    "RW": "RW",
    "ST": "ST",
    "CF": "ST",
    "FW": "ST",
    "CH": "CB",
    "SS": "ST",
    "LM": "LW",
    "RM": "RW",
}
TM_LABEL_TO_BOARD: dict[str, str] = {
    "goalkeeper": "GK",
    "centre-back": "CB",
    "center-back": "CB",
    "sweeper": "CB",
    "left-back": "LB",
    "right-back": "RB",
    "left wing-back": "LWB",
    "right wing-back": "RWB",
    "defensive midfield": "DM",
    "central midfield": "CM",
    "attacking midfield": "AM",
    "left midfield": "LW",
    "right midfield": "RW",
    "left winger": "LW",
    "right winger": "RW",
    "centre-forward": "ST",
    "center-forward": "ST",
    "second striker": "ST",
    "striker": "ST",
}
_catalog_lock = threading.Lock()
_catalog_cache: tuple[float, dict[str, dict[str, Any]]] | None = None
CATALOG_TTL_SECONDS = 3600


class PatchIncomingBody(BaseModel):
    flags: dict[str, bool] | None = None
    name: str | None = None
    clear_name: bool = False
    position: str | None = None
    clear_position: bool = False
    age: int | None = Field(default=None, ge=15, le=50)
    clear_age: bool = False
    interest: str | None = None
    clear_interest: bool = False


class NoteBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _staff(request: Request) -> str:
    payload = current_user_payload(request)
    return str(payload.get("display_name") or payload.get("username") or "Staff").strip() or "Staff"


def _slug(value: Any) -> str:
    text = _SLUG_RE.sub("-", str(value or "").strip().casefold()).strip("-")
    return text or "player"


def _name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def clean_report_name(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = _NAME_JUNK_RE.sub("", text).strip(" -–,")
    text = re.sub(r"\s+\([^)]*\)\s*$", "", text).strip()
    return text


def label_to_board_position(value: Any) -> str:
    raw = " ".join(str(value or "").split())
    if not raw:
        return ""
    compact = raw.upper().replace(" ", "_").replace("-", "_")
    mapped = IMPECT_TO_BOARD.get(compact) or IMPECT_TO_BOARD.get(raw.upper())
    if mapped in POSITIONS:
        return mapped
    text = raw.casefold().replace("–", "-").replace("—", "-")
    mapped = TM_LABEL_TO_BOARD.get(text)
    if mapped in POSITIONS:
        return mapped
    if "goalkeeper" in text:
        return "GK"
    if "centre-back" in text or "center-back" in text:
        return "CB"
    if "left-back" in text:
        return "LB"
    if "right-back" in text:
        return "RB"
    if "wing-back" in text and "left" in text:
        return "LWB"
    if "wing-back" in text and "right" in text:
        return "RWB"
    if "defensive midfield" in text:
        return "DM"
    if "attacking midfield" in text:
        return "AM"
    if "central midfield" in text:
        return "CM"
    if "left winger" in text or "left midfield" in text:
        return "LW"
    if "right winger" in text or "right midfield" in text:
        return "RW"
    if "forward" in text or "striker" in text:
        return "ST"
    return ""


def _board_position(value: Any) -> str:
    mapped = label_to_board_position(value)
    if mapped:
        return mapped
    return _clean_position(value)


def _position_cache_paths() -> list[Path]:
    return [DATA_ROOT / POSITION_CACHE_NAME, HUB_ROOT / "data" / POSITION_CACHE_NAME]


def _load_position_cache() -> dict[str, dict[str, Any]]:
    for path in _position_cache_paths():
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        players = payload.get("players")
        if not isinstance(players, dict):
            continue
        out: dict[str, dict[str, Any]] = {}
        for key, row in players.items():
            if not isinstance(key, str) or not isinstance(row, dict):
                continue
            position = label_to_board_position(row.get("position"))
            if position not in POSITIONS:
                continue
            name = clean_report_name(row.get("name")) or key
            out[_name_key(name) or key] = {
                "name": name,
                "position": position,
                "source": str(row.get("source") or "transfermarkt"),
            }
        if out:
            return out
    return {}


def _save_position_cache(players: dict[str, dict[str, Any]]) -> None:
    ensure_data_dirs()
    payload = {
        "version": 1,
        "updated_at": time.time(),
        "players": {
            key: {
                "name": row.get("name") or "",
                "position": row.get("position") or "",
                "source": row.get("source") or "transfermarkt",
            }
            for key, row in players.items()
            if label_to_board_position(row.get("position")) in POSITIONS
        },
    }
    path = DATA_ROOT / POSITION_CACHE_NAME
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(path)
    seed = HUB_ROOT / "data" / POSITION_CACHE_NAME
    if seed.resolve() != path.resolve():
        try:
            seed.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass


def _positions_need_warm(cache: dict[str, dict[str, Any]]) -> bool:
    if len(cache) < 80:
        return True
    for path in _position_cache_paths():
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            updated = float(payload.get("updated_at") or 0)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        return time.time() - updated > POSITION_CACHE_TTL_SECONDS
    return True


def _club_position_index(club_name: str) -> dict[str, dict[str, Any]]:
    name = " ".join(str(club_name or "").split())
    if not name or name.casefold() in {"released", "unattached", "free", "undisclosed"}:
        return {}
    try:
        from app.opponent_photos import transfermarkt_first_team_roster

        roster = transfermarkt_first_team_roster(name, None)
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(roster, dict):
        return out
    for row in roster.values():
        if not isinstance(row, dict):
            continue
        player_name = clean_report_name(row.get("name"))
        position = label_to_board_position(row.get("position"))
        key = _name_key(player_name)
        if not key or position not in POSITIONS:
            continue
        out[key] = {
            "name": player_name,
            "position": position,
            "source": "transfermarkt",
        }
    return out


def report_club_names(report: dict[str, Any] | None = None) -> list[str]:
    payload = report if isinstance(report, dict) else load_report()
    names: list[str] = []
    seen: set[str] = set()
    for league in payload.get("leagues") or []:
        if not isinstance(league, dict):
            continue
        for team in league.get("teams") or []:
            if not isinstance(team, dict):
                continue
            text = " ".join(str(team.get("name") or "").split())
            key = _name_key(text)
            if text and key not in seen:
                seen.add(key)
                names.append(text)
    return names


def warm_transfer_positions(club_names: list[str] | None = None) -> dict[str, dict[str, Any]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    names = [item for item in (club_names or report_club_names()) if item]
    merged = _load_position_cache()
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(_club_position_index, name) for name in names]
        for future in as_completed(futures):
            try:
                merged.update(future.result() or {})
            except Exception:
                continue
    if merged:
        _save_position_cache(merged)
    with _catalog_lock:
        global _catalog_cache
        _catalog_cache = None
    return merged


def _schedule_position_warm(club_names: list[str]) -> None:
    global _position_warm_started
    with _position_warm_lock:
        if _position_warm_started:
            return
        _position_warm_started = True

    def _run() -> None:
        try:
            warm_transfer_positions(club_names)
        except Exception:
            pass

    threading.Thread(target=_run, name="transfer-centre-positions", daemon=True).start()


def merge_position_suggestions(
    index: dict[str, dict[str, Any]],
    positions: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    catalog = positions if isinstance(positions, dict) else {}
    pos_index: dict[str, dict[str, Any]] = {}
    for key, row in catalog.items():
        if not isinstance(row, dict):
            continue
        position = label_to_board_position(row.get("position"))
        name = clean_report_name(row.get("name")) or key
        if position not in POSITIONS:
            continue
        pos_index[_name_key(name) or key] = {
            "name": name,
            "position": position,
            "age": None,
            "impect_id": None,
            "club_keys": set(),
        }
    for key, row in pos_index.items():
        existing = index.get(key)
        if existing is None:
            index[key] = dict(row)
            continue
        if not existing.get("position"):
            existing["position"] = row["position"]
    for row in index.values():
        if row.get("position"):
            continue
        hit = _match_suggestion(str(row.get("name") or ""), suggestions=pos_index)
        if hit.get("position") in POSITIONS:
            row["position"] = hit["position"]
    return index


def _position_codes_from_catalog(player: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for key in ("position", "mainPosition", "primaryPosition"):
        raw = player.get(key)
        if raw and str(raw).upper() not in codes:
            codes.append(str(raw).upper())
    positions = player.get("positions")
    if isinstance(positions, list):
        for item in positions:
            if isinstance(item, dict):
                raw = item.get("position") or item.get("name") or item.get("code")
            else:
                raw = item
            if raw and str(raw).upper() not in codes:
                codes.append(str(raw).upper())
    return codes


def _catalog_club_keys(player: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for key in ("squadName", "currentSquad", "teamName", "club", "clubName"):
        value = player.get(key)
        if isinstance(value, dict):
            value = value.get("name")
        text = _name_key(value)
        if text:
            keys.add(re.sub(r"^fc", "", text))
    return keys


def _load_impect_suggestions() -> dict[str, dict[str, Any]]:
    global _catalog_cache
    now = time.time()
    cached = _catalog_cache
    if cached and now - cached[0] < CATALOG_TTL_SECONDS:
        return cached[1]
    with _catalog_lock:
        cached = _catalog_cache
        if cached and now - cached[0] < CATALOG_TTL_SECONDS:
            return cached[1]
        index: dict[str, dict[str, Any]] = {}
        try:
            from app import main as impect_main

            iterations = impect_main._fetch_iterations()
            iteration_ids = impect_main._latest_iteration_ids(iterations)
            players_by_iteration = impect_main._fetch_players_parallel(iteration_ids)
            for iteration_id in iteration_ids:
                for row in players_by_iteration.get(iteration_id, []):
                    name = impect_main._extract_player_name(row)
                    if not name:
                        continue
                    key = _name_key(name)
                    if not key:
                        continue
                    try:
                        player_id = int(row.get("id") or 0)
                    except (TypeError, ValueError):
                        player_id = 0
                    position = ""
                    for code in _position_codes_from_catalog(row):
                        position = label_to_board_position(code)
                        if position in POSITIONS:
                            break
                    suggestion = {
                        "name": name,
                        "position": position if position in POSITIONS else "",
                        "age": impect_main._player_age(row),
                        "impect_id": player_id or None,
                        "club_keys": _catalog_club_keys(row),
                    }
                    existing = index.get(key)
                    if existing is None:
                        index[key] = suggestion
                        continue
                    if suggestion["position"] and not existing.get("position"):
                        index[key] = suggestion
        except Exception:
            index = cached[1] if cached else {}
        merge_position_suggestions(index, _load_position_cache())
        _catalog_cache = (now, index)
        return index


def _match_suggestion(
    name: str,
    *,
    from_club: str = "",
    team_name: str = "",
    suggestions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cleaned = clean_report_name(name)
    key = _name_key(cleaned)
    direct = suggestions.get(key)
    if direct:
        return direct
    parts = [part for part in re.split(r"\s+", cleaned) if part]
    if len(parts) < 2:
        return {}
    first, last = parts[0].casefold(), parts[-1].casefold()
    club_keys = {_name_key(from_club), _name_key(team_name)}
    club_keys = {re.sub(r"^fc", "", item) for item in club_keys if item}
    candidates: list[dict[str, Any]] = []
    for row in suggestions.values():
        bits = str(row.get("name") or "").split()
        if len(bits) < 2:
            continue
        if bits[-1].casefold() != last:
            continue
        other_first = bits[0].casefold()
        if other_first.startswith(first[:3]) or first.startswith(other_first[:3]):
            candidates.append(row)
    if not candidates:
        initial_hits = []
        for row in suggestions.values():
            bits = str(row.get("name") or "").split()
            if len(bits) < 2:
                continue
            if bits[-1].casefold() != last:
                continue
            if bits[0].casefold()[:1] == first[:1]:
                initial_hits.append(row)
        if len(initial_hits) == 1:
            return initial_hits[0]
        return {}
    if club_keys:
        club_hits = [
            row
            for row in candidates
            if club_keys.intersection(row.get("club_keys") or set())
        ]
        if len(club_hits) == 1:
            return club_hits[0]
        if club_hits:
            candidates = club_hits
    if len(candidates) == 1:
        return candidates[0]
    exact = [row for row in candidates if str(row.get("name") or "").split()[0].casefold() == first]
    if len(exact) == 1:
        return exact[0]
    return {}


def incoming_row_id(team_id: str, player: str, other: str, kind: str, seen: dict[str, int]) -> str:
    base = f"{_slug(team_id)}::{_slug(player)}::{_slug(other)}::{_slug(kind)}"
    count = seen.get(base, 0) + 1
    seen[base] = count
    return base if count == 1 else f"{base}::{count}"


def _empty_flags() -> dict[str, bool]:
    return {flag_id: False for flag_id in FLAG_IDS}


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "players": {}}


def _load_store() -> dict[str, Any]:
    ensure_data_dirs()
    if not BOARD_PATH.exists():
        return _empty_store()
    try:
        payload = json.loads(BOARD_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(payload, dict):
        return _empty_store()
    players = payload.get("players")
    if not isinstance(players, dict):
        players = {}
    cleaned: dict[str, Any] = {}
    for key, row in players.items():
        if isinstance(key, str) and isinstance(row, dict):
            cleaned[key] = row
    return {"version": 1, "players": cleaned}


def _persist_store(store: dict[str, Any]) -> None:
    ensure_data_dirs()
    payload = {"version": 1, "players": store.get("players") or {}}
    temp_path = BOARD_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(BOARD_PATH)


def _save_store(store: dict[str, Any]) -> None:
    with _lock:
        _persist_store(store)


def _clean_position(value: Any) -> str:
    text = " ".join(str(value or "").split()).upper()
    if text in POSITIONS:
        return text
    return " ".join(str(value or "").split())[:12]


def _clean_interest(value: Any) -> str:
    # Slashes and stray punctuation collapse too, so the label a client happens
    # to echo back ("Released / transferred by us") lands on its own id.
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    aliases = {
        "interested": "interested",
        "not_interested": "not_interested",
        "uninterested": "not_interested",
        "unrealistic": "unrealistic",
        "unrealstic": "unrealistic",
        "released_by_us": "released_by_us",
        "released": "released_by_us",
        "transferred_by_us": "released_by_us",
        "transfered_by_us": "released_by_us",
        "released_transferred_by_us": "released_by_us",
        "released_transfered_by_us": "released_by_us",
    }
    return aliases.get(text, "")


def _clean_age(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        age = int(value)
    except (TypeError, ValueError):
        return None
    if 15 <= age <= 50:
        return age
    return None


def _clean_notes(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            continue
        out.append(
            {
                "id": str(item.get("id") or uuid.uuid4()),
                "text": text[:4000],
                "author": str(item.get("author") or "Staff").strip() or "Staff",
                "created_at": str(item.get("created_at") or ""),
            }
        )
    return out


def _overlay_row(raw: Any) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    flags = _empty_flags()
    incoming_flags = row.get("flags") if isinstance(row.get("flags"), dict) else {}
    for flag_id in FLAG_IDS:
        flags[flag_id] = bool(incoming_flags.get(flag_id))
    position = _clean_position(row.get("position"))
    age = _clean_age(row.get("age"))
    name = clean_report_name(row.get("name"))
    interest = _clean_interest(row.get("interest"))
    return {
        "name": name,
        "name_manual": bool(row.get("name_manual")),
        "position": position,
        "position_manual": bool(row.get("position_manual")) or bool(position),
        "age": age,
        "age_manual": bool(row.get("age_manual")) or age is not None,
        "interest": interest,
        "flags": flags,
        "notes": _clean_notes(row.get("notes")),
        "updated_at": str(row.get("updated_at") or ""),
        "updated_by": str(row.get("updated_by") or ""),
    }


def apply_incoming_patch(
    store: dict[str, Any],
    player_id: str,
    *,
    flags: dict[str, bool] | None = None,
    name: str | None = None,
    clear_name: bool = False,
    position: str | None = None,
    clear_position: bool = False,
    age: int | None = None,
    clear_age: bool = False,
    interest: str | None = None,
    clear_interest: bool = False,
    staff: str = "Staff",
) -> dict[str, Any]:
    players = store.setdefault("players", {})
    raw = dict(players.get(player_id) or {})
    current = _overlay_row(raw)
    if flags:
        for flag_id, value in flags.items():
            if flag_id in FLAG_IDS:
                current["flags"][flag_id] = bool(value)
        raw["flags"] = current["flags"]
    if clear_name:
        raw.pop("name", None)
        raw["name_manual"] = False
    elif name is not None:
        raw["name"] = clean_report_name(name)
        raw["name_manual"] = True
    if clear_position:
        raw["position"] = ""
        raw["position_manual"] = True
    elif position is not None:
        raw["position"] = _clean_position(position)
        raw["position_manual"] = True
    if clear_age:
        raw["age"] = None
        raw["age_manual"] = True
    elif age is not None:
        raw["age"] = _clean_age(age)
        raw["age_manual"] = True
    if clear_interest:
        raw["interest"] = ""
    elif interest is not None:
        raw["interest"] = _clean_interest(interest)
    raw["notes"] = current["notes"]
    raw["updated_at"] = _now()
    raw["updated_by"] = staff
    players[player_id] = raw
    return _overlay_row(raw)


def add_incoming_note(
    store: dict[str, Any],
    player_id: str,
    *,
    text: str,
    staff: str = "Staff",
) -> tuple[dict[str, Any], dict[str, str]]:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        raise ValueError("Note cannot be empty.")
    players = store.setdefault("players", {})
    raw = dict(players.get(player_id) or {})
    current = _overlay_row(raw)
    note = {
        "id": str(uuid.uuid4()),
        "text": cleaned[:4000],
        "author": staff,
        "created_at": _now(),
    }
    current["notes"].append(note)
    raw["notes"] = current["notes"]
    raw["updated_at"] = note["created_at"]
    raw["updated_by"] = staff
    players[player_id] = raw
    return _overlay_row(raw), note


def _incoming_player(
    *,
    player_id: str,
    signed: dict[str, Any],
    overlay: dict[str, Any],
    team_name: str = "",
    suggestions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    saved = _overlay_row(overlay)
    source_name = str(signed.get("player") or "").strip()
    from_club = str(signed.get("other") or "").strip()
    suggested = _match_suggestion(
        source_name,
        from_club=from_club,
        team_name=team_name,
        suggestions=suggestions or {},
    )
    cleaned = clean_report_name(source_name) or source_name
    if saved["name_manual"] and saved["name"]:
        display_name = saved["name"]
        name_source = "staff"
    elif suggested.get("name"):
        display_name = str(suggested["name"])
        name_source = "impect"
    else:
        display_name = cleaned
        name_source = "report"
    if saved["position_manual"]:
        position = saved["position"]
        position_source = "staff" if saved["position"] else "staff"
    elif suggested.get("position"):
        position = str(suggested["position"])
        position_source = "api"
    else:
        position = saved["position"]
        position_source = "report" if position else ""
    if saved["age_manual"]:
        age = saved["age"]
        age_source = "staff"
    elif suggested.get("age") is not None:
        age = suggested["age"]
        age_source = "impect"
    else:
        age = saved["age"]
        age_source = "report" if age is not None else ""
    return {
        "id": player_id,
        "player": display_name,
        "source_name": source_name,
        "from_club": from_club,
        "kind": str(signed.get("kind") or "").strip(),
        "fee": str(signed.get("fee") or "").strip(),
        "position": position,
        "age": age,
        "name_source": name_source,
        "position_source": position_source,
        "age_source": age_source,
        "impect_id": suggested.get("impect_id"),
        "interest": saved["interest"],
        "is_out": saved["interest"] in OUT_INTEREST,
        "flags": saved["flags"],
        "notes": saved["notes"],
        "note_count": len(saved["notes"]),
        "updated_at": saved["updated_at"],
        "updated_by": saved["updated_by"],
    }


def build_market_board(
    report: dict[str, Any] | None = None,
    store: dict[str, Any] | None = None,
    suggestions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = report if isinstance(report, dict) else load_report()
    overlay = store if isinstance(store, dict) else _load_store()
    saved_players = overlay.get("players") if isinstance(overlay.get("players"), dict) else {}
    lookup = suggestions if suggestions is not None else _load_impect_suggestions()
    seen: dict[str, int] = {}
    leagues: list[dict[str, Any]] = []
    totals = {
        "teams": 0,
        "incomings": 0,
        **{flag_id: 0 for flag_id in FLAG_IDS},
        **{f"interest_{item}": 0 for item in INTEREST_IDS},
        "interest_out": 0,
    }

    for league in payload.get("leagues") or []:
        if not isinstance(league, dict):
            continue
        league_id = str(league.get("id") or "").strip()
        league_name = str(league.get("name") or league_id).strip()
        teams_out: list[dict[str, Any]] = []
        for team in league.get("teams") or []:
            if not isinstance(team, dict):
                continue
            team_id = str(team.get("id") or "").strip()
            players_out: list[dict[str, Any]] = []
            for signed in team.get("signed") or []:
                if not isinstance(signed, dict):
                    continue
                name = str(signed.get("player") or "").strip()
                if not name:
                    continue
                row_id = incoming_row_id(
                    team_id,
                    name,
                    str(signed.get("other") or ""),
                    str(signed.get("kind") or ""),
                    seen,
                )
                player = _incoming_player(
                    player_id=row_id,
                    signed=signed,
                    overlay=saved_players.get(row_id) or {},
                    team_name=str(team.get("name") or ""),
                    suggestions=lookup,
                )
                players_out.append(player)
                totals["incomings"] += 1
                for flag_id in FLAG_IDS:
                    if player["flags"].get(flag_id):
                        totals[flag_id] += 1
                interest = player.get("interest") or ""
                if interest in INTEREST_IDS:
                    totals[f"interest_{interest}"] += 1
                if player.get("is_out"):
                    totals["interest_out"] += 1
            teams_out.append(
                {
                    "id": team_id,
                    "name": str(team.get("name") or team_id).strip(),
                    "badge_url": str(team.get("badge_url") or ""),
                    "incomings": players_out,
                }
            )
            totals["teams"] += 1
        leagues.append(
            {
                "id": league_id,
                "name": league_name,
                "teams": teams_out,
                "incoming_count": sum(len(team["incomings"]) for team in teams_out),
            }
        )

    return {
        "window": str(payload.get("window") or "Summer 2026"),
        "season": str(payload.get("season") or ""),
        "updated": str(payload.get("updated") or ""),
        "flags": [dict(row) for row in FLAGS],
        "interest_options": [dict(row) for row in INTEREST_OPTIONS],
        "positions": list(POSITIONS),
        "leagues": leagues,
        "totals": totals,
    }


def transfer_reports(report: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = report if isinstance(report, dict) else load_report()
    incoming = 0
    clubs = 0
    league_bits: list[str] = []
    for league in payload.get("leagues") or []:
        if not isinstance(league, dict):
            continue
        teams = league.get("teams") or []
        clubs += len(teams)
        league_bits.append(str(league.get("name") or ""))
        for team in teams:
            if isinstance(team, dict):
                incoming += len(team.get("signed") or [])
    return [
        {
            "id": "efl-transfer-report",
            "title": str(payload.get("title") or "EFL Transfer Report"),
            "href": "/efl-transfer-report",
            "icon": "🔁",
            "window": str(payload.get("window") or "Summer 2026"),
            "updated": str(payload.get("updated") or ""),
            "description": (
                "Summer 2026 window — every League One, League Two, National League "
                "and Scottish Prem club: who they signed and who they released."
            ),
            "meta": f"{incoming} incomings · {clubs} clubs · {', '.join(bit for bit in league_bits if bit)}",
        }
    ]


def board_payload() -> dict[str, Any]:
    report = load_report()
    clubs = report_club_names(report)
    positions = _load_position_cache()
    pending = _positions_need_warm(positions)
    if pending:
        _schedule_position_warm(clubs)
    board = build_market_board(report)
    board["reports"] = transfer_reports(report)
    filled = 0
    for league in board.get("leagues") or []:
        for team in league.get("teams") or []:
            for player in team.get("incomings") or []:
                if player.get("position"):
                    filled += 1
    board["catalog"] = {
        "positions_pending": pending and filled < 80,
        "positions_cached": len(positions),
        "positions_filled": filled,
    }
    return board


def _board_player(player_id: str, store: dict[str, Any] | None = None) -> dict[str, Any] | None:
    board = build_market_board(store=store)
    for league in board.get("leagues") or []:
        for team in league.get("teams") or []:
            for player in team.get("incomings") or []:
                if player.get("id") == player_id:
                    return player
    return None


def register_transfer_centre_routes(app: FastAPI) -> None:
    @app.get("/transfer-centre", response_class=HTMLResponse)
    @app.get("/transfer-centre/", response_class=HTMLResponse)
    def transfer_centre_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "transfer-centre.html"
        if not html_path.is_file():
            raise HTTPException(status_code=404, detail="Transfer Centre missing.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/transfer-centre")
    def transfer_centre_data() -> dict[str, Any]:
        try:
            return board_payload()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/transfer-centre/players/{player_id}")
    def transfer_centre_patch(
        request: Request, player_id: str, body: PatchIncomingBody
    ) -> dict[str, Any]:
        player_key = str(player_id or "").strip()
        if not player_key or len(player_key) > 180:
            raise HTTPException(status_code=400, detail="Unknown incoming player.")
        with _lock:
            store = _load_store()
            saved = apply_incoming_patch(
                store,
                player_key,
                flags=body.flags,
                name=body.name,
                clear_name=body.clear_name,
                position=body.position,
                clear_position=body.clear_position,
                age=None if body.clear_age else body.age,
                clear_age=body.clear_age,
                interest=None if body.clear_interest else body.interest,
                clear_interest=body.clear_interest,
                staff=_staff(request),
            )
            _persist_store(store)
        merged = _board_player(player_key, store)
        return {"player": merged or {"id": player_key, **saved}}

    @app.post("/api/transfer-centre/players/{player_id}/notes")
    def transfer_centre_add_note(
        request: Request, player_id: str, body: NoteBody
    ) -> dict[str, Any]:
        player_key = str(player_id or "").strip()
        if not player_key or len(player_key) > 180:
            raise HTTPException(status_code=400, detail="Unknown incoming player.")
        try:
            with _lock:
                store = _load_store()
                saved, note = add_incoming_note(
                    store,
                    player_key,
                    text=body.text,
                    staff=_staff(request),
                )
                _persist_store(store)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        merged = _board_player(player_key, store)
        return {"player": merged or {"id": player_key, **saved}, "note": note}
