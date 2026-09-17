"""Player Reports — shared match conditions, general file, and player CMS.

Match weather / pitch are stored once per fixture so every player report on
that game loads the same conditions. Home/Away is inferred from the match
title (and the team sheet when we have it).
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.games_to_watch import _club_key, _core_club_key
from app.paths import DATA_ROOT, ensure_data_dirs
from app.player_report_schema import (
    clean_match_rating,
    clean_next_action,
    clean_physical,
    clean_pipeline_stage,
    clean_position,
    clean_profiles,
    clean_psychology,
    clean_pvfc_level,
    empty_physical,
    empty_psychology,
    option_fields,
    profile_entries_for_position,
)

PLAYER_REPORTS_PATH = DATA_ROOT / "player-reports.json"
_STORE_LOCK = threading.Lock()

WEATHER_OPTIONS: tuple[tuple[str, str], ...] = (
    ("dry", "Dry"),
    ("light-rain", "Light rain"),
    ("heavy-rain", "Heavy rain"),
    ("snow", "Snow"),
    ("windy", "Windy"),
    ("cold", "Cold"),
    ("hot", "Hot"),
    ("mixed", "Mixed"),
)

PITCH_OPTIONS: tuple[tuple[str, str], ...] = (
    ("excellent", "Excellent"),
    ("good", "Good"),
    ("average", "Average"),
    ("soft", "Soft / wet"),
    ("heavy", "Heavy"),
    ("worn", "Worn / patchy"),
    ("uneven", "Uneven / bobbly"),
    ("hard", "Hard / frozen"),
)

_WEATHER_IDS = {key for key, _label in WEATHER_OPTIONS}
_PITCH_IDS = {key for key, _label in PITCH_OPTIONS}
_VS_SPLIT = re.compile(r"\s+(?:vs\.?|v)\s+", re.I)


class MatchConditionsBody(BaseModel):
    fixture_id: str
    fixture_label: str = ""
    weather: str = ""
    weather_note: str = ""
    pitch: str = ""
    pitch_note: str = ""


class GeneralReportBody(BaseModel):
    player_id: int
    fixture_id: str
    fixture_label: str = ""
    weather: str = ""
    weather_note: str = ""
    pitch: str = ""
    pitch_note: str = ""
    notes: str = ""
    name: str = ""
    club: str = ""
    home_name: str = ""
    away_name: str = ""
    sheet_side: str = ""
    position_in_game: str = ""
    physical: dict[str, str] = Field(default_factory=dict)
    profiles: dict[str, str] = Field(default_factory=dict)


class DetailedReportBody(BaseModel):
    player_id: int
    fixture_id: str
    fixture_label: str = ""
    name: str = ""
    club: str = ""
    league: str = ""
    home_name: str = ""
    away_name: str = ""
    sheet_side: str = ""
    position: str = ""
    position_label: str = ""
    age: int | None = None
    position_in_game: str = ""
    physical: dict[str, str] = Field(default_factory=dict)
    profiles: dict[str, str] = Field(default_factory=dict)
    psychology: dict[str, str] = Field(default_factory=dict)
    write_up: str = ""
    next_steps: str = ""
    match_rating: float | None = None
    pvfc_level: str = ""
    add_to_pipeline: bool = False
    pipeline_stage: str = "video_scouted"
    next_action: str = ""


class PlayerCmsBody(BaseModel):
    player_id: int
    name: str = ""
    club: str = ""
    agent_name: str = ""
    agent_notes: str = ""
    contract_expires: str = ""
    contract_notes: str = ""
    wages_notes: str = ""
    other_notes: str = Field(default="", max_length=4000)


def option_catalog() -> dict[str, Any]:
    return {
        "weather": [{"id": key, "label": label} for key, label in WEATHER_OPTIONS],
        "pitch": [{"id": key, "label": label} for key, label in PITCH_OPTIONS],
        **option_fields(),
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _empty_store() -> dict[str, Any]:
    return {
        "version": 1,
        "match_conditions": {},
        "general_reports": {},
        "detailed_reports": {},
        "cms": {},
    }


def _load_store() -> dict[str, Any]:
    ensure_data_dirs()
    if not PLAYER_REPORTS_PATH.exists():
        return _empty_store()
    try:
        payload = json.loads(PLAYER_REPORTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(payload, dict):
        return _empty_store()
    out = _empty_store()
    for key in ("match_conditions", "general_reports", "detailed_reports", "cms"):
        rows = payload.get(key)
        if isinstance(rows, dict):
            out[key] = rows
    return out


def _save_store(store: dict[str, Any]) -> None:
    ensure_data_dirs()
    payload = {
        "version": 1,
        "match_conditions": store.get("match_conditions") or {},
        "general_reports": store.get("general_reports") or {},
        "detailed_reports": store.get("detailed_reports") or {},
        "cms": store.get("cms") or {},
    }
    with _STORE_LOCK:
        temp_path = PLAYER_REPORTS_PATH.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(PLAYER_REPORTS_PATH)


def _clean_choice(value: Any, allowed: set[str]) -> str:
    token = str(value or "").strip().casefold()
    return token if token in allowed else ""


def _clean_text(value: Any, *, limit: int = 400) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def clubs_match(left: str, right: str) -> bool:
    a = _club_key(left)
    b = _club_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    ca = _core_club_key(left)
    cb = _core_club_key(right)
    if ca and cb and (ca == cb or ca in cb or cb in ca):
        return True
    return a in b or b in a


def parse_fixture_sides(label: str) -> tuple[str, str]:
    raw = str(label or "").strip()
    if not raw:
        return "", ""
    parts = _VS_SPLIT.split(raw, maxsplit=1)
    if len(parts) != 2:
        return "", ""
    return parts[0].strip(), parts[1].strip()


def infer_home_away(
    *,
    club: str = "",
    fixture_label: str = "",
    home_name: str = "",
    away_name: str = "",
    sheet_side: str = "",
) -> dict[str, str]:
    side = str(sheet_side or "").strip().casefold()
    if side in {"home", "away"}:
        return {
            "side": side,
            "label": "Home" if side == "home" else "Away",
            "source": "team sheet",
        }

    home = str(home_name or "").strip()
    away = str(away_name or "").strip()
    if not home or not away:
        parsed_home, parsed_away = parse_fixture_sides(fixture_label)
        home = home or parsed_home
        away = away or parsed_away

    club_name = str(club or "").strip()
    source = "match title" if (home or away) else ""
    if club_name and home and clubs_match(club_name, home) and not clubs_match(club_name, away):
        return {"side": "home", "label": "Home", "source": source or "match title"}
    if club_name and away and clubs_match(club_name, away) and not clubs_match(club_name, home):
        return {"side": "away", "label": "Away", "source": source or "match title"}
    if club_name and home and clubs_match(club_name, home):
        return {"side": "home", "label": "Home", "source": source or "match title"}
    if club_name and away and clubs_match(club_name, away):
        return {"side": "away", "label": "Away", "source": source or "match title"}
    return {"side": "", "label": "", "source": ""}


def empty_match_conditions(fixture_id: str = "", fixture_label: str = "") -> dict[str, Any]:
    return {
        "fixture_id": str(fixture_id or ""),
        "fixture_label": str(fixture_label or ""),
        "weather": "",
        "weather_label": "",
        "weather_note": "",
        "pitch": "",
        "pitch_label": "",
        "pitch_note": "",
        "updated_by": "",
        "updated_at": "",
        "filled": False,
    }


def _label_for(value: str, options: tuple[tuple[str, str], ...]) -> str:
    for key, label in options:
        if key == value:
            return label
    return ""


def _decorate_conditions(row: dict[str, Any] | None, *, fixture_id: str = "", fixture_label: str = "") -> dict[str, Any]:
    base = empty_match_conditions(fixture_id, fixture_label)
    if not isinstance(row, dict):
        return base
    weather = _clean_choice(row.get("weather"), _WEATHER_IDS)
    pitch = _clean_choice(row.get("pitch"), _PITCH_IDS)
    label = str(row.get("fixture_label") or fixture_label or "").strip()
    return {
        "fixture_id": str(row.get("fixture_id") or fixture_id or ""),
        "fixture_label": label,
        "weather": weather,
        "weather_label": _label_for(weather, WEATHER_OPTIONS),
        "weather_note": _clean_text(row.get("weather_note"), limit=160),
        "pitch": pitch,
        "pitch_label": _label_for(pitch, PITCH_OPTIONS),
        "pitch_note": _clean_text(row.get("pitch_note"), limit=160),
        "updated_by": str(row.get("updated_by") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "filled": bool(weather or pitch),
    }


def match_conditions_for_fixture(fixture_id: str, *, fixture_label: str = "") -> dict[str, Any]:
    token = str(fixture_id or "").strip()
    if not token:
        return empty_match_conditions("", fixture_label)
    store = _load_store()
    row = store["match_conditions"].get(token)
    return _decorate_conditions(row if isinstance(row, dict) else None, fixture_id=token, fixture_label=fixture_label)


def save_match_conditions(
    *,
    fixture_id: str,
    fixture_label: str = "",
    weather: str = "",
    weather_note: str = "",
    pitch: str = "",
    pitch_note: str = "",
    staff: str = "Staff",
) -> dict[str, Any]:
    token = str(fixture_id or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="fixture_id is required")
    cleaned = _decorate_conditions(
        {
            "fixture_id": token,
            "fixture_label": fixture_label,
            "weather": weather,
            "weather_note": weather_note,
            "pitch": pitch,
            "pitch_note": pitch_note,
            "updated_by": str(staff or "").strip() or "Staff",
            "updated_at": _now(),
        },
        fixture_id=token,
        fixture_label=fixture_label,
    )
    store = _load_store()
    existing = store["match_conditions"].get(token)
    if isinstance(existing, dict) and existing.get("created_at"):
        cleaned["created_at"] = existing["created_at"]
        cleaned["created_by"] = existing.get("created_by") or cleaned["updated_by"]
    else:
        cleaned["created_at"] = cleaned["updated_at"]
        cleaned["created_by"] = cleaned["updated_by"]
    store["match_conditions"][token] = cleaned
    _save_store(store)
    return cleaned


def _report_key(player_id: int, fixture_id: str) -> str:
    return f"{int(player_id)}:{str(fixture_id or '').strip()}"


def empty_general_report(player_id: int = 0, fixture_id: str = "") -> dict[str, Any]:
    return {
        "player_id": int(player_id or 0),
        "fixture_id": str(fixture_id or ""),
        "position_in_game": "",
        "physical": empty_physical(),
        "profiles": {},
        "notes": "",
        "updated_by": "",
        "updated_at": "",
        "filled": False,
    }


def _general_from_row(player_id: int, fixture_id: str, row: dict[str, Any] | None) -> dict[str, Any]:
    base = empty_general_report(player_id, fixture_id)
    if not isinstance(row, dict):
        return base
    physical = clean_physical(row.get("physical"))
    profiles = clean_profiles(row.get("profiles"))
    notes = str(row.get("notes") or "").strip()
    position = clean_position(row.get("position_in_game"))
    base.update(
        {
            "position_in_game": position,
            "physical": physical,
            "profiles": profiles,
            "notes": notes,
            "updated_by": str(row.get("updated_by") or ""),
            "updated_at": str(row.get("updated_at") or ""),
            "filled": bool(
                position
                or notes
                or any(physical.values())
                or any(str(value or "").strip() for value in profiles.values())
            ),
        }
    )
    return base


def general_report_for_player(player_id: int, fixture_id: str) -> dict[str, Any]:
    if not player_id or not str(fixture_id or "").strip():
        return empty_general_report(player_id, fixture_id)
    store = _load_store()
    row = store["general_reports"].get(_report_key(player_id, fixture_id))
    return _general_from_row(player_id, fixture_id, row if isinstance(row, dict) else None)


def save_general_report(
    *,
    player_id: int,
    fixture_id: str,
    notes: str = "",
    position_in_game: str = "",
    physical: dict[str, str] | None = None,
    profiles: dict[str, str] | None = None,
    staff: str = "Staff",
) -> dict[str, Any]:
    if not player_id:
        raise HTTPException(status_code=400, detail="player_id is required")
    token = str(fixture_id or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="fixture_id is required")
    cleaned = _general_from_row(
        player_id,
        token,
        {
            "position_in_game": position_in_game,
            "physical": physical or {},
            "profiles": profiles or {},
            "notes": str(notes or "").strip()[:2000],
            "updated_by": str(staff or "").strip() or "Staff",
            "updated_at": _now(),
        },
    )
    store = _load_store()
    store["general_reports"][_report_key(player_id, token)] = cleaned
    _save_store(store)
    return cleaned


def empty_detailed_report(player_id: int = 0, fixture_id: str = "") -> dict[str, Any]:
    return {
        "player_id": int(player_id or 0),
        "fixture_id": str(fixture_id or ""),
        "position_in_game": "",
        "physical": empty_physical(),
        "profiles": {},
        "psychology": empty_psychology(),
        "write_up": "",
        "next_steps": "",
        "match_rating": None,
        "pvfc_level": "",
        "add_to_pipeline": False,
        "pipeline_stage": "video_scouted",
        "next_action": "",
        "updated_by": "",
        "updated_at": "",
        "filled": False,
    }


def _detailed_from_row(player_id: int, fixture_id: str, row: dict[str, Any] | None) -> dict[str, Any]:
    base = empty_detailed_report(player_id, fixture_id)
    if not isinstance(row, dict):
        return base
    physical = clean_physical(row.get("physical"))
    profiles = clean_profiles(row.get("profiles"))
    psychology = clean_psychology(row.get("psychology"))
    write_up = str(row.get("write_up") or "").strip()
    next_steps = str(row.get("next_steps") or "").strip()
    rating = clean_match_rating(row.get("match_rating"))
    level = clean_pvfc_level(row.get("pvfc_level"))
    action = clean_next_action(row.get("next_action"))
    stage = clean_pipeline_stage(row.get("pipeline_stage")) or "video_scouted"
    position = clean_position(row.get("position_in_game"))
    add = bool(row.get("add_to_pipeline"))
    if action == "sign":
        add = True
        if stage in ("", "video_scouted"):
            stage = "scout_identified"
    elif action == "not_to_standard":
        level = level or "D"
        if stage in ("", "video_scouted"):
            stage = "not_the_right_fit"
    base.update(
        {
            "position_in_game": position,
            "physical": physical,
            "profiles": profiles,
            "psychology": psychology,
            "write_up": write_up[:4000],
            "next_steps": next_steps[:4000],
            "match_rating": rating,
            "pvfc_level": level,
            "add_to_pipeline": add,
            "pipeline_stage": stage,
            "next_action": action,
            "updated_by": str(row.get("updated_by") or ""),
            "updated_at": str(row.get("updated_at") or ""),
            "filled": bool(
                position
                or write_up
                or next_steps
                or rating is not None
                or level
                or action
                or any(physical.values())
                or any(str(value or "").strip() for value in profiles.values())
                or any(str(value or "").strip() for value in psychology.values())
            ),
        }
    )
    return base


def detailed_report_for_player(player_id: int, fixture_id: str) -> dict[str, Any]:
    if not player_id or not str(fixture_id or "").strip():
        return empty_detailed_report(player_id, fixture_id)
    store = _load_store()
    row = store["detailed_reports"].get(_report_key(player_id, fixture_id))
    detailed = _detailed_from_row(player_id, fixture_id, row if isinstance(row, dict) else None)
    if detailed["filled"]:
        return detailed
    general = general_report_for_player(player_id, fixture_id)
    if not general.get("filled"):
        return detailed
    detailed["position_in_game"] = detailed["position_in_game"] or general.get("position_in_game") or ""
    if not any(detailed["physical"].values()):
        detailed["physical"] = dict(general.get("physical") or empty_physical())
    if not any(str(value or "").strip() for value in detailed["profiles"].values()):
        detailed["profiles"] = dict(general.get("profiles") or {})
    return detailed


def save_detailed_report(
    *,
    player_id: int,
    fixture_id: str,
    position_in_game: str = "",
    physical: dict[str, str] | None = None,
    profiles: dict[str, str] | None = None,
    psychology: dict[str, str] | None = None,
    write_up: str = "",
    next_steps: str = "",
    match_rating: float | None = None,
    pvfc_level: str = "",
    add_to_pipeline: bool = False,
    pipeline_stage: str = "video_scouted",
    next_action: str = "",
    staff: str = "Staff",
) -> dict[str, Any]:
    if not player_id:
        raise HTTPException(status_code=400, detail="player_id is required")
    token = str(fixture_id or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="fixture_id is required")
    cleaned = _detailed_from_row(
        player_id,
        token,
        {
            "position_in_game": position_in_game,
            "physical": physical or {},
            "profiles": profiles or {},
            "psychology": psychology or {},
            "write_up": write_up,
            "next_steps": next_steps,
            "match_rating": match_rating,
            "pvfc_level": pvfc_level,
            "add_to_pipeline": add_to_pipeline,
            "pipeline_stage": pipeline_stage,
            "next_action": next_action,
            "updated_by": str(staff or "").strip() or "Staff",
            "updated_at": _now(),
        },
    )
    store = _load_store()
    store["detailed_reports"][_report_key(player_id, token)] = cleaned
    _save_store(store)
    return cleaned


def empty_cms(player_id: int = 0) -> dict[str, Any]:
    return {
        "player_id": int(player_id or 0),
        "agent_name": "",
        "agent_notes": "",
        "contract_expires": "",
        "contract_notes": "",
        "wages_notes": "",
        "other_notes": "",
        "contract_expires_source": "",
        "updated_by": "",
        "updated_at": "",
        "filled": False,
    }


def _cms_from_row(player_id: int, row: dict[str, Any] | None) -> dict[str, Any]:
    base = empty_cms(player_id)
    if not isinstance(row, dict):
        return base
    for key in (
        "agent_name",
        "agent_notes",
        "contract_expires",
        "contract_notes",
        "wages_notes",
        "other_notes",
    ):
        base[key] = str(row.get(key) or "").strip()
    base["updated_by"] = str(row.get("updated_by") or "")
    base["updated_at"] = str(row.get("updated_at") or "")
    base["filled"] = any(
        base[key]
        for key in (
            "agent_name",
            "agent_notes",
            "contract_expires",
            "contract_notes",
            "wages_notes",
            "other_notes",
        )
    )
    return base


def _cached_contract_expires(name: str, club: str) -> str:
    if not name:
        return ""
    try:
        from app.player_web_enrichment import fetch_transfermarkt_player_profile

        tm = fetch_transfermarkt_player_profile(name, club_name=club or None, cached_only=True)
    except Exception:
        return ""
    if not isinstance(tm, dict):
        return ""
    return str(tm.get("contract_expires") or "").strip()


def cms_for_player(player_id: int, *, name: str = "", club: str = "") -> dict[str, Any]:
    if not player_id:
        return empty_cms()
    store = _load_store()
    row = store["cms"].get(str(int(player_id)))
    cms = _cms_from_row(player_id, row if isinstance(row, dict) else None)
    source = _cached_contract_expires(name, club)
    cms["contract_expires_source"] = source
    if not cms["contract_expires"] and source:
        cms["contract_expires"] = source
    return cms


def save_cms(
    *,
    player_id: int,
    agent_name: str = "",
    agent_notes: str = "",
    contract_expires: str = "",
    contract_notes: str = "",
    wages_notes: str = "",
    other_notes: str = "",
    staff: str = "Staff",
    name: str = "",
    club: str = "",
) -> dict[str, Any]:
    if not player_id:
        raise HTTPException(status_code=400, detail="player_id is required")
    cleaned = _cms_from_row(
        player_id,
        {
            "agent_name": _clean_text(agent_name, limit=80),
            "agent_notes": str(agent_notes or "").strip()[:2000],
            "contract_expires": _clean_text(contract_expires, limit=80),
            "contract_notes": str(contract_notes or "").strip()[:2000],
            "wages_notes": str(wages_notes or "").strip()[:2000],
            "other_notes": str(other_notes or "").strip()[:4000],
            "updated_by": str(staff or "").strip() or "Staff",
            "updated_at": _now(),
        },
    )
    store = _load_store()
    store["cms"][str(int(player_id))] = cleaned
    _save_store(store)
    cleaned["contract_expires_source"] = _cached_contract_expires(name, club)
    return cleaned


def report_file_for_player(
    *,
    player_id: int,
    club: str = "",
    name: str = "",
    fixture_id: str = "",
    fixture_label: str = "",
    home_name: str = "",
    away_name: str = "",
    sheet_side: str = "",
    position: str = "",
    player_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    conditions = match_conditions_for_fixture(fixture_id, fixture_label=fixture_label)
    general = general_report_for_player(player_id, fixture_id)
    detailed = detailed_report_for_player(player_id, fixture_id)
    role = (
        general.get("position_in_game")
        or detailed.get("position_in_game")
        or position
    )
    return {
        "options": option_catalog(),
        "match_conditions": conditions,
        "home_away": infer_home_away(
            club=club,
            fixture_label=fixture_label or conditions.get("fixture_label") or "",
            home_name=home_name,
            away_name=away_name,
            sheet_side=sheet_side,
        ),
        "report_profiles": profile_entries_for_position(
            role,
            player_profiles=player_profiles,
            player_position=position,
        ),
        "general_report": general,
        "detailed_report": detailed,
        "cms": cms_for_player(player_id, name=name, club=club),
    }
