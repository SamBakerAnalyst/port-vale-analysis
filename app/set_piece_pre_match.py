"""Set Piece Pre-Match — opponent set-play prep from Impect."""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from app.handout_badges import enrich_team_badge
from app.opponent_photos import (
    TM_HEADERS,
    _normalize_name_key,
    _season_year,
    attach_pitch_player_photos,
    opponent_photo_api_url,
    resolve_transfermarkt_club_id,
)
from app.paths import SET_PIECE_CACHE_DIR, STANDALONE_DIR, STATIC_DIR, ensure_data_dirs
from app.pre_match import (
    DEFAULT_COMPETITION,
    PreMatchPngExportRequest,
    PreMatchReportRequest,
    _fetch_match_detail,
    _format_foot,
    _kpi_names,
    _match_squad_block,
    _metric_value,
    _ordinal,
    _player_age,
    _player_display_name,
    _player_surname,
    _position_label,
    _rank_metric,
    _recent_completed_matches,
    _squad_kpi_table,
    _unwrap_items,
    _unwrap_match_player_payload,
    build_pre_match_fixtures,
    build_pre_match_whatsapp_pdf,
    pre_match_meta,
)
from app.match_player_utils import POSITION_ABBR, _height_short
from app.post_match.impect_client import impect_get, v5_path
from app.post_match.set_plays import (
    SHOT_XG_KPI_ID,
    TYPE_LABELS,
    _annotate_first_contact_perspective,
    _chain_is_delivery_threat,
    _is_corner_chain,
    _is_free_kick_chain,
    _parse_chains,
    _player_initials,
    _summarize_chains,
    PENALTY_BOX_HALF_WIDTH_M,
    PENALTY_BOX_MIN_X,
)
from app.post_match.crosses import FINAL_THIRD_MIN_X, PITCH_GOAL_X, PITCH_WIDTH_M
from app.post_match.report import _player_directory

SET_PIECE_MATCH_LIMIT = 8
_SEASON_SET_PLAY_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_SEASON_SET_PLAY_TTL = 6 * 60 * 60
_MATCH_VIEW_MEM_CACHE: dict[tuple[int, int, int], tuple[float, dict[str, Any]]] = {}
_MATCH_VIEW_TTL = 7 * 24 * 60 * 60
_REPORT_MEM_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_REPORT_TTL = 6 * 60 * 60
_TM_SQUAD_CACHE: dict[tuple[int, int], tuple[float, dict[str, dict[str, Any]]]] = {}
_TM_HEIGHT_TTL = 6 * 60 * 60

_TM_POSITION_ABBR: dict[str, str] = {
    "goalkeeper": "GK",
    "centre-back": "CH",
    "center-back": "CH",
    "left-back": "LB",
    "right-back": "RB",
    "defensive midfield": "DM",
    "central midfield": "CM",
    "attacking midfield": "AM",
    "left midfield": "LM",
    "right midfield": "RM",
    "left winger": "LW",
    "right winger": "RW",
    "centre-forward": "CF",
    "center-forward": "CF",
    "second striker": "SS",
}

TEAM_METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "PXT_SETPIECE",
        "label": "Set Play Threat (PXT)",
        "higher_better": True,
        "format": "decimal",
    },
    {
        "key": "SHOT_XG_AT_PHASE_SET_PIECE",
        "label": "Shot xG (Set Play)",
        "higher_better": True,
        "format": "decimal",
    },
    {
        "key": "GOALS_AT_PHASE_SET_PIECE",
        "label": "Goals (Set Play)",
        "higher_better": True,
        "format": "decimal",
    },
    {
        "key": "SHOT_XG_BY_ACTION_CORNER",
        "label": "Corner xG",
        "higher_better": True,
        "format": "decimal",
    },
    {
        "key": "SHOT_XG_BY_ACTION_FREE_KICK",
        "label": "Free Kick xG",
        "higher_better": True,
        "format": "decimal",
    },
    {
        "key": "BYPASSED_DEFENDERS_AT_PHASE_SET_PIECE",
        "label": "Bypassed Defenders",
        "higher_better": True,
        "format": "decimal",
    },
    {
        "key": "WON_AERIAL_DUELS_AT_PHASE_SET_PIECE",
        "label": "Aerials Won (Set Play)",
        "higher_better": True,
        "format": "decimal",
    },
    {
        "key": "LOST_AERIAL_DUELS_AT_PHASE_SET_PIECE",
        "label": "Aerials Lost (Set Play)",
        "higher_better": False,
        "format": "decimal",
    },
)

PLAYER_KPI_IDS = {
    "WON_AERIAL_DUELS_AT_PHASE_SET_PIECE": 1189,
    "LOST_AERIAL_DUELS_AT_PHASE_SET_PIECE": 1216,
    "SHOT_XG_AT_PHASE_SET_PIECE": 1282,
    "GOALS_AT_PHASE_SET_PIECE": 1249,
    "SHOT_AT_GOAL_NUMBER_AT_PHASE_SET_PIECE": 1315,
    "BYPASSED_DEFENDERS_AT_PHASE_SET_PIECE": 226,
}


class SetPiecePreMatchRequest(BaseModel):
    iteration_id: int = Field(..., ge=1)
    squad_id: int = Field(..., ge=1)
    match_id: int | None = None
    # Kept for backwards compatibility; reports always include last-8 + season.
    window: str | None = None
    # Force rebuild past disk/memory caches (Refresh data).
    refresh: bool = False


def _impect():
    from app import main as impect_main

    return impect_main


def _ensure_set_piece_cache_dir() -> Path:
    ensure_data_dirs()
    SET_PIECE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return SET_PIECE_CACHE_DIR


def _read_json_cache(path: Path, *, ttl: float) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > ttl:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _write_json_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        _ensure_set_piece_cache_dir()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _report_cache_key(
    iteration_id: int,
    squad_id: int,
    *,
    before: str | None,
    exclude_match_id: int | None,
) -> str:
    before_part = (before or "latest").replace(":", "").replace("+", "")
    exclude_part = exclude_match_id or 0
    return f"report_{iteration_id}_{squad_id}_{before_part}_{exclude_part}"


def _report_cache_path(cache_key: str) -> Path:
    return _ensure_set_piece_cache_dir() / f"{cache_key}.json"


def _match_view_cache_path(match_id: int, squad_id: int) -> Path:
    return _ensure_set_piece_cache_dir() / f"match_{match_id}_{squad_id}_v5.json"


def _load_cached_report(cache_key: str) -> dict[str, Any] | None:
    cached = _REPORT_MEM_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _REPORT_TTL:
        return cached[1]
    disk = _read_json_cache(_report_cache_path(cache_key), ttl=_REPORT_TTL)
    if disk:
        _REPORT_MEM_CACHE[cache_key] = (now, disk)
        return disk
    return None


def _store_cached_report(cache_key: str, report: dict[str, Any]) -> None:
    now = time.time()
    _REPORT_MEM_CACHE[cache_key] = (now, report)
    _write_json_cache(_report_cache_path(cache_key), report)


def _height_cm(player: dict[str, Any]) -> int | None:
    for key in ("heightCm", "height", "bodyHeight"):
        raw = player.get(key)
        if raw is None or raw == "":
            continue
        try:
            cm = int(float(raw))
        except (TypeError, ValueError):
            continue
        if cm > 0:
            return cm
    return None


def _height_label_from_cm(cm: int | None) -> str:
    """Format cm as feet/inches. Reject nonsense values (avoids 0'0 from bad data)."""
    try:
        value = int(round(float(cm))) if cm is not None else 0
    except (TypeError, ValueError):
        return "—"
    # Senior/academy footballers are almost never under 140cm or over 220cm.
    if value < 140 or value > 220:
        return "—"
    feet = int(value // 30.48)
    inches = int(round((value / 2.54) % 12))
    if inches == 12:
        feet += 1
        inches = 0
    if feet <= 0:
        return "—"
    return f"{feet}'{inches}\""


def _parse_tm_height_cm(text: str) -> int | None:
    """Parse Transfermarkt height cells: '1,88 m', '1.88m', or UK '6 ft 3 in'."""
    raw = str(text or "")
    metric = re.search(r"(\d)[,.](\d{2})\s*m\b", raw, flags=re.I)
    if metric:
        try:
            return int(metric.group(1)) * 100 + int(metric.group(2))
        except (TypeError, ValueError):
            return None
    imperial = re.search(
        r"(\d+)\s*(?:ft|'|’)\s*(\d{1,2})\s*(?:in|\"|”)?",
        raw,
        flags=re.I,
    )
    if imperial:
        try:
            inches = int(imperial.group(1)) * 12 + int(imperial.group(2))
        except (TypeError, ValueError):
            return None
        if 48 <= inches <= 90:
            return int(round(inches * 2.54))
    return None


def _tm_position_abbr(position: str | None) -> str:
    text = re.sub(r"\s+", " ", str(position or "").strip()).casefold()
    if not text:
        return "—"
    if text in _TM_POSITION_ABBR:
        return _TM_POSITION_ABBR[text]
    if "goalkeeper" in text:
        return "GK"
    return text[:3].upper()


def _parse_tm_foot(text: str) -> str | None:
    raw = str(text or "").casefold()
    if not raw:
        return None
    if "left" in raw:
        return "LEFT"
    if "right" in raw:
        return "RIGHT"
    if "both" in raw:
        return "BOTH"
    return None


def _tm_profiles_disk_path(club_id: int, season_year: int) -> Path:
    return _ensure_set_piece_cache_dir() / f"tm_{int(club_id)}_{int(season_year)}.json"


def _tm_profiles_have_heights(profiles: dict[str, Any] | None) -> bool:
    if not profiles:
        return False
    return any(
        isinstance(row, dict) and row.get("height_cm")
        for row in profiles.values()
    )


def _backfill_tm_heights_from_previous_season(
    profiles: dict[str, dict[str, Any]],
    club_id: int,
    season_year: int,
) -> dict[str, dict[str, Any]]:
    """Copy last season's TM height onto this season's row when the new table has '-'."""
    if not profiles:
        return profiles
    prev = _read_json_cache(
        _tm_profiles_disk_path(int(club_id), int(season_year) - 1),
        ttl=90 * 24 * 60 * 60,
    )
    if not isinstance(prev, dict):
        return profiles
    for key, row in profiles.items():
        if not isinstance(row, dict) or row.get("height_cm"):
            continue
        prior = prev.get(key)
        if not isinstance(prior, dict) or not prior.get("height_cm"):
            continue
        try:
            row["height_cm"] = int(prior["height_cm"])
        except (TypeError, ValueError):
            continue
    return profiles


def _height_chart_incomplete(report: dict[str, Any] | None) -> bool:
    if not isinstance(report, dict):
        return True
    chart = report.get("height_chart")
    if not isinstance(chart, dict):
        return True
    assigned = int(chart.get("count") or 0)
    unknown = int(chart.get("unknown_count") or len(chart.get("unknown") or []))
    if int(chart.get("version") or 0) < HEIGHT_CHART_VERSION:
        return True
    return assigned == 0 and unknown > 0


def _for_slide_incomplete(report: dict[str, Any] | None) -> bool:
    if not isinstance(report, dict):
        return True
    attacking = (report.get("set_plays") or {}).get("attacking") or {}
    return "left" not in attacking


def _against_slide_incomplete(report: dict[str, Any] | None) -> bool:
    if not isinstance(report, dict):
        return True
    defending = (report.get("set_plays") or {}).get("defending") or {}
    return "goalPoints" not in defending or "left" not in defending


def _store_tm_profiles(
    profiles: dict[str, dict[str, Any]],
    *,
    club_id: int,
    season_year: int,
    now: float,
    cache_key: tuple[int, int],
    disk_path: Path,
) -> dict[str, dict[str, Any]]:
    profiles = _backfill_tm_heights_from_previous_season(profiles, club_id, season_year)
    if _tm_profiles_have_heights(profiles):
        _TM_SQUAD_CACHE[cache_key] = (now, profiles)
        _write_json_cache(disk_path, profiles)
    return profiles


def _fetch_transfermarkt_squad_profiles(
    club_name: str, season: str | None
) -> dict[str, dict[str, Any]]:
    """Name-key → Transfermarkt squad profile (height, position, shirt, GK)."""
    club_id = resolve_transfermarkt_club_id(club_name)
    if not club_id:
        return {}
    season_year = _season_year(season)
    cache_key = (int(club_id), int(season_year))
    cached = _TM_SQUAD_CACHE.get(cache_key)
    now = time.time()
    # Only reuse successful caches that actually have heights. Failed scrapes
    # (or the old metric-only parser) must not poison the chart for the TTL.
    if (
        cached
        and _tm_profiles_have_heights(cached[1])
        and now - cached[0] < _TM_HEIGHT_TTL
    ):
        return _store_tm_profiles(
            cached[1],
            club_id=int(club_id),
            season_year=int(season_year),
            now=now,
            cache_key=cache_key,
            disk_path=_tm_profiles_disk_path(int(club_id), int(season_year)),
        )

    disk_path = _tm_profiles_disk_path(int(club_id), int(season_year))
    disk = _read_json_cache(disk_path, ttl=_TM_HEIGHT_TTL)
    if _tm_profiles_have_heights(disk):
        return _store_tm_profiles(
            disk,
            club_id=int(club_id),
            season_year=int(season_year),
            now=now,
            cache_key=cache_key,
            disk_path=disk_path,
        )

    url = (
        f"https://www.transfermarkt.co.uk/startseite/kader/verein/"
        f"{club_id}/saison_id/{season_year}/plus/1"
    )
    profiles: dict[str, dict[str, Any]] = {}
    try:
        response = requests.get(url, timeout=30, headers=TM_HEADERS)
        if response.status_code >= 400:
            # Live servers are often blocked by Transfermarkt — keep last good disk seed.
            stale = _read_json_cache(disk_path, ttl=30 * 24 * 60 * 60)
            if _tm_profiles_have_heights(stale):
                return _store_tm_profiles(
                    stale,
                    club_id=int(club_id),
                    season_year=int(season_year),
                    now=now,
                    cache_key=cache_key,
                    disk_path=disk_path,
                )
            return {}
        html = response.text
    except requests.RequestException:
        stale = _read_json_cache(disk_path, ttl=30 * 24 * 60 * 60)
        if _tm_profiles_have_heights(stale):
            return _store_tm_profiles(
                stale,
                club_id=int(club_id),
                season_year=int(season_year),
                now=now,
                cache_key=cache_key,
                disk_path=disk_path,
            )
        return {}

    chunks = re.split(r'(?=<td[^>]*rueckennummer)', html, flags=re.I)
    for chunk in chunks[1:]:
        head = chunk[:2500]
        name_match = re.search(
            r'href="/[^"]+/profil/spieler/\d+"\s*>\s*([^<]+)',
            head,
            flags=re.I,
        ) or re.search(
            r'data-src="https://img\.a\.transfermarkt\.technology/portrait/[^"]+"[^>]*alt="([^"]+)"',
            head,
            flags=re.I,
        ) or re.search(r'alt="([^"]+)"', head, flags=re.I)
        if not name_match:
            continue
        clean_name = re.sub(r"\s+", " ", name_match.group(1)).strip()
        key = _normalize_name_key(clean_name)
        if not key:
            continue
        # Club-badge alts (e.g. "Milton Keynes Dons") sneak in when a row has
        # no player profile link — skip those so they never land on the chart.
        if "/profil/spieler/" not in head.casefold() and "portrait/" not in head.casefold():
            continue

        title_match = re.search(r'title="([^"]+)"', head[:260], flags=re.I)
        title = title_match.group(1).strip() if title_match else ""
        pos_match = re.search(
            r"<tr>\s*<td>\s*([A-Za-z][^<]*?)\s*</td>\s*</tr>\s*</table>",
            head,
            flags=re.S | re.I,
        )
        position = (pos_match.group(1).strip() if pos_match else title).strip()
        shirt_match = re.search(
            r'class=["\']?rn_nummer["\']?[^>]*>\s*([^<]+)',
            head[:400],
            flags=re.I,
        )
        shirt_number = None
        if shirt_match:
            raw_shirt = shirt_match.group(1).strip()
            if raw_shirt.isdigit():
                shirt_number = int(raw_shirt)
        cm = _parse_tm_height_cm(head)
        foot = _parse_tm_foot(head)
        pos_l = f"{position} {title}".casefold()
        is_gk = (
            "goalkeeper" in pos_l
            or "torwart" in pos_l
            or "bg_torwart" in head[:220].casefold()
        )
        profiles[key] = {
            "name": clean_name,
            "height_cm": cm,
            "foot": foot,
            "position": position or None,
            "position_abbr": _tm_position_abbr(position) if position else ("GK" if is_gk else "—"),
            "shirt_number": shirt_number,
            "is_gk": is_gk,
        }

    if _tm_profiles_have_heights(profiles):
        return _store_tm_profiles(
            profiles,
            club_id=int(club_id),
            season_year=int(season_year),
            now=now,
            cache_key=cache_key,
            disk_path=disk_path,
        )

    # Empty / height-less scrape (common on the live IP) — fall back to a
    # previously seeded file, but only if it actually has heights.
    stale = _read_json_cache(disk_path, ttl=30 * 24 * 60 * 60)
    if _tm_profiles_have_heights(stale):
        return _store_tm_profiles(
            stale,
            club_id=int(club_id),
            season_year=int(season_year),
            now=now,
            cache_key=cache_key,
            disk_path=disk_path,
        )
    return _backfill_tm_heights_from_previous_season(profiles, int(club_id), int(season_year))


def _fetch_transfermarkt_heights(club_name: str, season: str | None) -> dict[str, int]:
    """Name-key → height cm from Transfermarkt detailed squad table."""
    profiles = _fetch_transfermarkt_squad_profiles(club_name, season)
    return {
        key: int(profile["height_cm"])
        for key, profile in profiles.items()
        if profile.get("height_cm")
    }


def _lookup_tm_profile_key(player_name: str, profiles: dict[str, Any]) -> str | None:
    if not player_name or not profiles:
        return None
    direct = _normalize_name_key(player_name)
    if direct in profiles:
        return direct
    parts = [part for part in re.split(r"\s+", player_name.strip()) if part]
    if not parts:
        return None
    last = _normalize_name_key(parts[-1])
    first = _normalize_name_key(parts[0]) if len(parts) > 1 else ""
    candidates = [
        key for key in profiles if key.endswith(last) or last in key
    ]
    if len(candidates) == 1:
        return candidates[0]
    for key in candidates:
        if first and key.startswith(first[:3]):
            return key
    return None


def _lookup_tm_profile(
    player_name: str, profiles: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    key = _lookup_tm_profile_key(player_name, profiles)
    return profiles.get(key) if key else None


def _lookup_tm_height(player_name: str, heights: dict[str, int]) -> int | None:
    if not player_name or not heights:
        return None
    # heights may be legacy int map OR full profiles with height_cm
    sample = next(iter(heights.values()), None)
    if isinstance(sample, dict):
        profile = _lookup_tm_profile(player_name, heights)  # type: ignore[arg-type]
        cm = profile.get("height_cm") if profile else None
        return int(cm) if cm else None
    direct = heights.get(_normalize_name_key(player_name))
    if direct:
        return int(direct)
    parts = [part for part in re.split(r"\s+", player_name.strip()) if part]
    if not parts:
        return None
    last = _normalize_name_key(parts[-1])
    first = _normalize_name_key(parts[0]) if len(parts) > 1 else ""
    candidates = [(key, cm) for key, cm in heights.items() if key.endswith(last) or last in key]
    if len(candidates) == 1:
        return int(candidates[0][1])
    for key, cm in candidates:
        if first and key.startswith(first[:3]):
            return int(cm)
    return None


def _position_abbr(position: str | None) -> str:
    code = str(position or "").upper()
    if not code:
        return "—"
    return POSITION_ABBR.get(code, _position_label(position)[:3].upper())


def _format_metric(value: float | None, *, fmt: str = "decimal") -> str | None:
    if value is None:
        return None
    if fmt == "int":
        return str(int(round(value)))
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _team_set_piece_rankings(iteration_id: int, squad_id: int) -> list[dict[str, Any]]:
    table = _squad_kpi_table(iteration_id)
    rankings: list[dict[str, Any]] = []
    for spec in TEAM_METRIC_SPECS:
        value, rank = _rank_metric(
            table,
            squad_id,
            spec,
            higher_better=bool(spec.get("higher_better", True)),
        )
        rankings.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "value": round(value, 2) if value is not None else None,
                "display": _format_metric(value, fmt=str(spec.get("format") or "decimal")),
                "rank": rank,
                "higher_better": bool(spec.get("higher_better", True)),
            }
        )
    return rankings


def _pass_volume(stats: dict[str, float], *, action: str) -> float | None:
    successful = float(stats.get(f"SUCCESSFUL_PASSES_BY_ACTION_{action}") or 0.0)
    unsuccessful = float(stats.get(f"UNSUCCESSFUL_PASSES_BY_ACTION_{action}") or 0.0)
    total = successful + unsuccessful
    return total if total > 0 else None


def _pass_success_pct(stats: dict[str, float], *, action: str) -> float | None:
    successful = float(stats.get(f"SUCCESSFUL_PASSES_BY_ACTION_{action}") or 0.0)
    unsuccessful = float(stats.get(f"UNSUCCESSFUL_PASSES_BY_ACTION_{action}") or 0.0)
    total = successful + unsuccessful
    if total <= 0:
        return None
    return round(100.0 * successful / total)


def _set_piece_aerial_win_pct(stats: dict[str, float]) -> float | None:
    won = float(stats.get("WON_AERIAL_DUELS_AT_PHASE_SET_PIECE") or 0.0)
    lost = float(stats.get("LOST_AERIAL_DUELS_AT_PHASE_SET_PIECE") or 0.0)
    total = won + lost
    if total <= 0:
        return None
    return round(100.0 * won / total)


FAMILY_RANK_SPECS: dict[str, tuple[dict[str, Any], ...]] = {
    "corners": (
        {
            "field": "avgChains",
            "higher_better": True,
            "compute": lambda stats: _pass_volume(stats, action="CORNER"),
        },
        {
            "field": "deliverySuccessPct",
            "higher_better": True,
            "compute": lambda stats: _pass_success_pct(stats, action="CORNER"),
        },
        {
            "field": "firstContactWonPct",
            "higher_better": True,
            "compute": _set_piece_aerial_win_pct,
        },
        {
            "field": "avgShotXg",
            "higher_better": True,
            "key": "SHOT_XG_BY_ACTION_CORNER",
        },
        {
            "field": "goals",
            "higher_better": True,
            "key": "GOALS_BY_ACTION_CORNER",
        },
        {
            "field": "shots",
            "higher_better": True,
            "key": "SHOT_AT_GOAL_NUMBER_BY_ACTION_CORNER",
        },
        {
            "field": "avgGoals",
            "higher_better": True,
            "key": "GOALS_BY_ACTION_CORNER",
        },
    ),
    "freeKicks": (
        {
            "field": "avgChains",
            "higher_better": True,
            "compute": lambda stats: _pass_volume(stats, action="FREE_KICK"),
        },
        {
            "field": "deliverySuccessPct",
            "higher_better": True,
            "compute": lambda stats: _pass_success_pct(stats, action="FREE_KICK"),
        },
        {
            "field": "firstContactWonPct",
            "higher_better": True,
            "compute": _set_piece_aerial_win_pct,
        },
        {
            "field": "avgShotXg",
            "higher_better": True,
            "key": "SHOT_XG_BY_ACTION_FREE_KICK",
        },
        {
            "field": "goals",
            "higher_better": True,
            "key": "GOALS_BY_ACTION_FREE_KICK",
        },
        {
            "field": "shots",
            "higher_better": True,
            "key": "SHOT_AT_GOAL_NUMBER_BY_ACTION_FREE_KICK",
        },
        {
            "field": "avgGoals",
            "higher_better": True,
            "key": "GOALS_BY_ACTION_FREE_KICK",
        },
    ),
}


def _league_metric_values(
    table: dict[int, dict[str, float]],
    spec: dict[str, Any],
) -> list[float]:
    values: list[float] = []
    for stats in table.values():
        matches = stats.get("matches") or 0.0
        if matches <= 0:
            continue
        value = _metric_value(stats, spec, matches)
        if value is None:
            continue
        values.append(float(value))
    return values


def _ordinal_for_value(
    value: float | None,
    sample: list[float],
    *,
    higher_better: bool,
) -> str | None:
    if value is None or not sample:
        return None
    better = 0
    for other in sample:
        if higher_better:
            if other > value:
                better += 1
        elif other < value:
            better += 1
    return _ordinal(min(better + 1, len(sample)))


def _family_block_ranks(
    table: dict[int, dict[str, float]],
    squad_id: int,
    family_key: str,
    block: dict[str, Any],
    *,
    defending: bool = False,
    use_squad_season_rank: bool = False,
) -> dict[str, Any]:
    """Attach league ranks for a corner / free-kick KPI block."""
    specs = FAMILY_RANK_SPECS.get(family_key) or ()
    value_aliases = {"goals": "avgGoals", "shots": "avgShots"}
    ranks: dict[str, str] = {}
    higher_better_map: dict[str, bool] = {}
    for spec in specs:
        field = str(spec["field"])
        base_higher = bool(spec.get("higher_better", True))
        if defending and field != "firstContactWonPct":
            higher_better = not base_higher
        else:
            higher_better = base_higher
        higher_better_map[field] = higher_better

        if use_squad_season_rank and not defending:
            _value, rank = _rank_metric(
                table,
                squad_id,
                spec,
                higher_better=higher_better,
            )
        else:
            source_field = value_aliases.get(field, field)
            raw = block.get(source_field)
            try:
                numeric = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                numeric = None
            sample = _league_metric_values(table, spec)
            rank = _ordinal_for_value(numeric, sample, higher_better=higher_better)
        if rank:
            ranks[field] = rank
    return {"ranks": ranks, "rankHigherBetter": higher_better_map}


def _decorate_family_block(
    block: dict[str, Any],
    *,
    table: dict[int, dict[str, float]],
    squad_id: int,
    family_key: str,
    defending: bool,
    use_squad_season_rank: bool = False,
) -> dict[str, Any]:
    return {
        **block,
        **_family_block_ranks(
            table,
            squad_id,
            family_key,
            block,
            defending=defending,
            use_squad_season_rank=use_squad_season_rank,
        ),
    }


def _merge_dual_windows(
    recent: dict[str, Any],
    season: dict[str, Any],
    *,
    iteration_id: int,
    squad_id: int,
) -> dict[str, Any]:
    """Keep last-8 maps/leaders; nest full-season family KPIs + ranks beside them."""
    table = _squad_kpi_table(iteration_id)
    out = dict(recent)
    for side_key, defending in (("attacking", False), ("defending", True)):
        side = dict(out.get(side_key) or {})
        season_side = season.get(side_key) or {}
        for family_key, recent_key in (("corners", "corners"), ("freeKicks", "freeKicks")):
            recent_block = dict(side.get(recent_key) or {})
            season_block = dict(season_side.get(recent_key) or {})
            recent_decorated = _decorate_family_block(
                recent_block,
                table=table,
                squad_id=squad_id,
                family_key=family_key,
                defending=defending,
                use_squad_season_rank=False,
            )
            season_decorated = _decorate_family_block(
                season_block,
                table=table,
                squad_id=squad_id,
                family_key=family_key,
                defending=defending,
                use_squad_season_rank=not defending,
            )
            recent_decorated["season"] = season_decorated
            side[recent_key] = recent_decorated
        side["season"] = _side_kpi_snapshot(season_side)
        out[side_key] = side
    out["seasonGameCount"] = int(season.get("gameCount") or 0)
    return out


def _cached_season_set_plays(
    iteration_id: int,
    squad_id: int,
    *,
    before: str | None,
    exclude_match_id: int | None,
    player_names: dict[int, str] | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    cache_key = (iteration_id, squad_id, before, exclude_match_id)
    cached = _SEASON_SET_PLAY_CACHE.get(cache_key)
    now = time.time()
    if not refresh and cached and now - cached[0] < _SEASON_SET_PLAY_TTL:
        return cached[1]
    payload = _aggregate_recent_set_plays(
        iteration_id,
        squad_id,
        before=before,
        exclude_match_id=exclude_match_id,
        limit=None,
        include_details=False,
        player_names=player_names,
        refresh=refresh,
    )
    _SEASON_SET_PLAY_CACHE[cache_key] = (now, payload)
    return payload


def _empty_chain_totals() -> dict[str, float]:
    return {
        "chains": 0.0,
        "successfulDeliveries": 0.0,
        "firstContacts": 0.0,
        "firstContactWon": 0.0,
        "shots": 0.0,
        "goals": 0.0,
        "shotXg": 0.0,
        "intoBox": 0.0,
        "deliverable": 0.0,
    }


def _accumulate_summary(totals: dict[str, float], summary: dict[str, Any]) -> None:
    for key in totals:
        totals[key] += float(summary.get(key) or 0.0)


def _finalize_totals(totals: dict[str, float], games: int) -> dict[str, Any]:
    denom = max(games, 1)
    delivery_pct = None
    if totals["chains"]:
        delivery_pct = round((totals["successfulDeliveries"] / totals["chains"]) * 100)
    fc_pct = None
    if totals["firstContacts"]:
        fc_pct = round((totals["firstContactWon"] / totals["firstContacts"]) * 100)
    into_box_pct = None
    if totals["deliverable"]:
        into_box_pct = round((totals["intoBox"] / totals["deliverable"]) * 100)
    return {
        "gameCount": games,
        "chains": int(round(totals["chains"])),
        "avgChains": round(totals["chains"] / denom, 1),
        "deliverySuccessPct": delivery_pct,
        "firstContactWonPct": fc_pct,
        "intoBoxPct": into_box_pct,
        "shots": int(round(totals["shots"])),
        "avgShots": round(totals["shots"] / denom, 2),
        "goals": int(round(totals["goals"])),
        "avgGoals": round(totals["goals"] / denom, 2),
        "shotXg": round(totals["shotXg"], 2),
        "avgShotXg": round(totals["shotXg"] / denom, 2),
    }


_SIDE_KPI_KEYS = (
    "gameCount",
    "chains",
    "avgChains",
    "deliverySuccessPct",
    "firstContactWonPct",
    "intoBoxPct",
    "shots",
    "avgShots",
    "goals",
    "avgGoals",
    "shotXg",
    "avgShotXg",
)


def _side_kpi_snapshot(side: dict[str, Any]) -> dict[str, Any]:
    return {key: side.get(key) for key in _SIDE_KPI_KEYS}


def _opponent_id_for_match(match: dict[str, Any], squad_id: int) -> int | None:
    home = int(match.get("homeSquadId") or 0)
    away = int(match.get("awaySquadId") or 0)
    if home == squad_id and away:
        return away
    if away == squad_id and home:
        return home
    return None


def _delivery_side(chain: dict[str, Any]) -> str | None:
    side = str(chain.get("side") or "").strip().lower()
    if side in {"left", "right"}:
        return side
    coords = chain.get("startCoords") or chain.get("deliveryCoords")
    if not coords or len(coords) < 2:
        return None
    try:
        wing_y = float(coords[1])
    except (TypeError, ValueError, IndexError):
        return None
    if wing_y > 0:
        return "left"
    if wing_y < 0:
        return "right"
    return None


def _is_delivery_set_play(chain: dict[str, Any]) -> bool:
    if _is_corner_chain(chain):
        return True
    if _is_free_kick_chain(chain):
        return _chain_is_delivery_threat(chain)
    return False


def _normalize_attacking_third_coords(
    coords: list[float] | tuple[float, float] | None,
) -> tuple[float, float] | None:
    """Flip to the +x attacking third so both ends share one final-third map."""
    if not coords or len(coords) < 2:
        return None
    try:
        x, y = float(coords[0]), float(coords[1])
    except (TypeError, ValueError, IndexError):
        return None
    if x < 0:
        return -x, -y
    return x, y


def _empty_match_view(*, defending: bool = False) -> dict[str, Any]:
    empty_summary = _summarize_chains([], defending=defending)
    return {
        "summary": empty_summary,
        "summaryCorners": empty_summary,
        "summaryFreeKicks": empty_summary,
        "summaryLeft": empty_summary,
        "summaryRight": empty_summary,
        "firstContactPoints": [],
        "contactLeaders": {},
        "contactLeadersByFamily": {"corners": {}, "freeKicks": {}},
        "takersByFamily": {"corners": {}, "freeKicks": {}},
        "scorersByFamily": {"corners": {}, "freeKicks": {}},
        "contactLeadersBySide": {"left": {}, "right": {}},
        "takersBySide": {"left": {}, "right": {}},
        "scorersBySide": {"left": {}, "right": {}},
        "goalPoints": [],
    }


def _fetch_match_events_and_xg(match_id: int) -> tuple[list[Any], dict[int, float]]:
    events_payload = impect_get(v5_path(f"/matches/{match_id}/events"))["data"]
    events = events_payload.get("data") if isinstance(events_payload, dict) else events_payload
    if not isinstance(events, list):
        return [], {}

    ekpi_payload = impect_get(v5_path(f"/matches/{match_id}/event-kpis"))["data"]
    ekpi_rows = ekpi_payload.get("data") if isinstance(ekpi_payload, dict) else ekpi_payload
    xg_by_event: dict[int, float] = {}
    if isinstance(ekpi_rows, list):
        for row in ekpi_rows:
            if row.get("kpiId") == SHOT_XG_KPI_ID and row.get("eventId") is not None:
                try:
                    xg_by_event[int(row["eventId"])] = float(row.get("value") or 0)
                except (TypeError, ValueError):
                    continue
    return events, xg_by_event


def _match_delivery_set_play_view(
    match_id: int,
    attacking_squad_id: int,
    player_names: dict[int, str],
    *,
    defending: bool = False,
    include_details: bool = True,
    events: list[Any] | None = None,
    xg_by_event: dict[int, float] | None = None,
) -> dict[str, Any]:
    """Corners + attacking-third FKs with first-contact map points and leaders."""
    empty = _empty_match_view(defending=defending)
    if events is None or xg_by_event is None:
        events, xg_by_event = _fetch_match_events_and_xg(match_id)
    if not events:
        return empty

    chains = _parse_chains(events, attacking_squad_id, player_names, xg_by_event)
    chains = [chain for chain in chains if _is_delivery_set_play(chain)]
    chains = _annotate_first_contact_perspective(chains, defending=defending)
    corner_chains = [chain for chain in chains if _is_corner_chain(chain)]
    free_kick_chains = [chain for chain in chains if _is_free_kick_chain(chain)]
    left_chains = [chain for chain in chains if _delivery_side(chain) == "left"]
    right_chains = [chain for chain in chains if _delivery_side(chain) == "right"]
    summary = _summarize_chains(chains, defending=defending)
    summary_corners = _summarize_chains(corner_chains, defending=defending)
    summary_free_kicks = _summarize_chains(free_kick_chains, defending=defending)
    summary_left = _summarize_chains(left_chains, defending=defending)
    summary_right = _summarize_chains(right_chains, defending=defending)

    if not include_details:
        return {
            "summary": summary,
            "summaryCorners": summary_corners,
            "summaryFreeKicks": summary_free_kicks,
            "summaryLeft": summary_left,
            "summaryRight": summary_right,
            "firstContactPoints": [],
            "contactLeaders": {},
            "contactLeadersByFamily": {"corners": {}, "freeKicks": {}},
            "takersByFamily": {"corners": {}, "freeKicks": {}},
            "scorersByFamily": {"corners": {}, "freeKicks": {}},
            "contactLeadersBySide": {"left": {}, "right": {}},
            "takersBySide": {"left": {}, "right": {}},
            "scorersBySide": {"left": {}, "right": {}},
            "goalPoints": [],
        }

    points: list[dict[str, Any]] = []
    goal_points: list[dict[str, Any]] = []
    leaders: dict[int, dict[str, Any]] = {}
    contact_by_family: dict[str, dict[int, dict[str, Any]]] = {"corners": {}, "freeKicks": {}}
    takers_by_family: dict[str, dict[int, dict[str, Any]]] = {"corners": {}, "freeKicks": {}}
    scorers_by_family: dict[str, dict[int, dict[str, Any]]] = {"corners": {}, "freeKicks": {}}
    contact_by_side: dict[str, dict[int, dict[str, Any]]] = {"left": {}, "right": {}}
    takers_by_side: dict[str, dict[int, dict[str, Any]]] = {"left": {}, "right": {}}
    scorers_by_side: dict[str, dict[int, dict[str, Any]]] = {"left": {}, "right": {}}
    for chain in chains:
        family_key = "corners" if _is_corner_chain(chain) else "freeKicks"
        delivery_side = _delivery_side(chain)
        deliverer_id = chain.get("delivererId")
        deliverer_name = chain.get("delivererName")
        taker_row = _ensure_player_row(
            takers_by_family[family_key],
            deliverer_id,
            name=deliverer_name,
            initials=chain.get("delivererInitials") or _player_initials(deliverer_name),
        )
        if taker_row:
            taker_row["takes"] += 1
        if delivery_side in takers_by_side:
            side_taker = _ensure_player_row(
                takers_by_side[delivery_side],
                deliverer_id,
                name=deliverer_name,
                initials=chain.get("delivererInitials") or _player_initials(deliverer_name),
            )
            if side_taker:
                side_taker["takes"] += 1

        chain_has_goal = False
        for shot in chain.get("shots") or []:
            scorer_row = _ensure_player_row(
                scorers_by_family[family_key],
                shot.get("playerId"),
                name=shot.get("playerName"),
                initials=_player_initials(shot.get("playerName")),
            )
            if scorer_row:
                scorer_row["shots"] += 1
                scorer_row["xg"] = round(
                    float(scorer_row.get("xg") or 0.0) + float(shot.get("xg") or 0.0), 3
                )
            if delivery_side in scorers_by_side:
                side_scorer = _ensure_player_row(
                    scorers_by_side[delivery_side],
                    shot.get("playerId"),
                    name=shot.get("playerName"),
                    initials=_player_initials(shot.get("playerName")),
                )
                if side_scorer:
                    side_scorer["shots"] += 1
                    side_scorer["xg"] = round(
                        float(side_scorer.get("xg") or 0.0) + float(shot.get("xg") or 0.0), 3
                    )
            if not shot.get("isGoal"):
                continue
            chain_has_goal = True
            if scorer_row:
                scorer_row["goals"] += 1
            if delivery_side in scorers_by_side:
                side_goal = _ensure_player_row(
                    scorers_by_side[delivery_side],
                    shot.get("playerId"),
                    name=shot.get("playerName"),
                    initials=_player_initials(shot.get("playerName")),
                )
                if side_goal:
                    side_goal["goals"] += 1
            goal_coords = _normalize_attacking_third_coords(
                shot.get("coords") or chain.get("firstContactCoords")
            )
            if not goal_coords:
                continue
            shooter_name = shot.get("playerName")
            goal_points.append(
                {
                    "kind": "goal",
                    "impectX": float(goal_coords[0]),
                    "impectY": float(goal_coords[1]),
                    "playerId": shot.get("playerId"),
                    "playerName": shooter_name,
                    "playerInitials": _player_initials(shooter_name),
                    "typeLabel": chain.get("typeLabel"),
                    "restartFamily": "corner" if _is_corner_chain(chain) else "freeKick",
                    "deliverySide": delivery_side,
                    "minuteLabel": chain.get("minuteLabel"),
                    "xg": shot.get("xg"),
                }
            )

        first = chain.get("firstContact") or {}
        coords = _normalize_attacking_third_coords(chain.get("firstContactCoords"))
        player_id = first.get("playerId")
        player_name = first.get("playerName")
        won = first.get("won")
        same_team = first.get("sameTeam")

        # Focus-team first contacts:
        # attacking → sameTeam; defending → not sameTeam.
        is_focus_contact = (
            bool(same_team) if not defending else (same_team is False)
        )

        if coords:
            into_box = bool(chain.get("intoBox"))
            if not into_box:
                # Re-check on normalised coords (original end may be -x goal).
                try:
                    into_box = (
                        float(coords[0]) >= PENALTY_BOX_MIN_X
                        and abs(float(coords[1])) <= PENALTY_BOX_HALF_WIDTH_M
                    )
                except (TypeError, ValueError):
                    into_box = False
            points.append(
                {
                    "kind": "firstContact",
                    "impectX": float(coords[0]),
                    "impectY": float(coords[1]),
                    "won": won,
                    "sameTeam": same_team,
                    "defending": defending,
                    "focusContact": is_focus_contact,
                    "playerId": player_id,
                    "playerName": player_name,
                    "playerInitials": first.get("playerInitials")
                    or _player_initials(player_name),
                    "typeLabel": chain.get("typeLabel"),
                    "restartFamily": "corner" if _is_corner_chain(chain) else "freeKick",
                    "deliverySide": delivery_side,
                    "minuteLabel": chain.get("minuteLabel"),
                    "intoBox": into_box,
                    "ledToGoal": chain_has_goal,
                }
            )

        if not is_focus_contact or player_id is None:
            continue
        try:
            pid = int(player_id)
        except (TypeError, ValueError):
            continue
        bucket = leaders.setdefault(
            pid,
            {
                "player_id": pid,
                "name": player_name or player_names.get(pid) or f"Player {pid}",
                "initials": first.get("playerInitials")
                or _player_initials(player_name or player_names.get(pid)),
                "contacts": 0,
                "into_box": 0,
            },
        )
        bucket["contacts"] += 1
        if chain.get("intoBox"):
            bucket["into_box"] += 1
        if player_name and bucket["name"].startswith("Player "):
            bucket["name"] = player_name
        family_contact = _ensure_player_row(
            contact_by_family[family_key],
            pid,
            name=bucket["name"],
            initials=bucket.get("initials"),
        )
        if family_contact:
            family_contact["contacts"] += 1
            if chain.get("intoBox"):
                family_contact["into_box"] += 1
        if delivery_side in contact_by_side:
            side_contact = _ensure_player_row(
                contact_by_side[delivery_side],
                pid,
                name=bucket["name"],
                initials=bucket.get("initials"),
            )
            if side_contact:
                side_contact["contacts"] += 1
                if chain.get("intoBox"):
                    side_contact["into_box"] += 1

    return {
        "summary": summary,
        "summaryCorners": summary_corners,
        "summaryFreeKicks": summary_free_kicks,
        "summaryLeft": summary_left,
        "summaryRight": summary_right,
        "firstContactPoints": points,
        "goalPoints": goal_points,
        "contactLeaders": leaders,
        "contactLeadersByFamily": contact_by_family,
        "takersByFamily": takers_by_family,
        "scorersByFamily": scorers_by_family,
        "contactLeadersBySide": contact_by_side,
        "takersBySide": takers_by_side,
        "scorersBySide": scorers_by_side,
    }


def _strip_match_view_details(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": view.get("summary") or _summarize_chains([], defending=False),
        "summaryCorners": view.get("summaryCorners") or _summarize_chains([], defending=False),
        "summaryFreeKicks": view.get("summaryFreeKicks") or _summarize_chains([], defending=False),
        "summaryLeft": view.get("summaryLeft") or _summarize_chains([], defending=False),
        "summaryRight": view.get("summaryRight") or _summarize_chains([], defending=False),
        "firstContactPoints": [],
        "contactLeaders": {},
        "contactLeadersByFamily": {"corners": {}, "freeKicks": {}},
        "takersByFamily": {"corners": {}, "freeKicks": {}},
        "scorersByFamily": {"corners": {}, "freeKicks": {}},
        "contactLeadersBySide": {"left": {}, "right": {}},
        "takersBySide": {"left": {}, "right": {}},
        "scorersBySide": {"left": {}, "right": {}},
        "goalPoints": [],
    }


def _match_view_has_family_maps(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    for_view = payload.get("for") or {}
    return isinstance((for_view.get("summaryLeft")), dict)


def _read_legacy_match_view(match_id: int, squad_id: int) -> dict[str, Any] | None:
    cache_dir = _ensure_set_piece_cache_dir()
    for name in (
        f"match_{match_id}_{squad_id}_v4.json",
        f"match_{match_id}_{squad_id}_v3.json",
        f"match_{match_id}_{squad_id}_v2.json",
        f"match_{match_id}_{squad_id}.json",
    ):
        disk = _read_json_cache(cache_dir / name, ttl=_MATCH_VIEW_TTL)
        if disk and isinstance(disk.get("for"), dict) and isinstance(disk.get("against"), dict):
            return disk
    return None


def _split_match_view_payload(
    payload: dict[str, Any],
    *,
    include_details: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    for_view = payload.get("for") or _empty_match_view(defending=False)
    against_view = payload.get("against") or _empty_match_view(defending=True)
    if not include_details:
        return _strip_match_view_details(for_view), _strip_match_view_details(against_view)
    return for_view, against_view


def _match_both_sides_set_play_view(
    match: dict[str, Any],
    squad_id: int,
    player_names: dict[int, str],
    *,
    include_details: bool = True,
    refresh: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load events once per match (disk-cached) and build for + against views."""
    match_id = int(match["id"])
    cache_key = (match_id, squad_id, 5)
    now = time.time()

    if not refresh:
        mem = _MATCH_VIEW_MEM_CACHE.get(cache_key)
        if mem and now - mem[0] < _MATCH_VIEW_TTL:
            payload = mem[1]
            if not include_details or _match_view_has_family_maps(payload):
                return _split_match_view_payload(payload, include_details=include_details)

        disk = _read_json_cache(
            _match_view_cache_path(match_id, squad_id),
            ttl=_MATCH_VIEW_TTL,
        )
        if disk and isinstance(disk.get("for"), dict) and isinstance(disk.get("against"), dict):
            if not include_details or _match_view_has_family_maps(disk):
                _MATCH_VIEW_MEM_CACHE[cache_key] = (now, disk)
                return _split_match_view_payload(disk, include_details=include_details)

        if not include_details:
            legacy = _read_legacy_match_view(match_id, squad_id)
            if legacy:
                return _split_match_view_payload(legacy, include_details=False)

    events, xg_by_event = _fetch_match_events_and_xg(match_id)
    for_view = _match_delivery_set_play_view(
        match_id,
        squad_id,
        player_names,
        defending=False,
        include_details=True,
        events=events,
        xg_by_event=xg_by_event,
    )
    opp_id = _opponent_id_for_match(match, squad_id)
    against_view = (
        _match_delivery_set_play_view(
            match_id,
            opp_id,
            player_names,
            defending=True,
            include_details=True,
            events=events,
            xg_by_event=xg_by_event,
        )
        if opp_id
        else _empty_match_view(defending=True)
    )
    payload = {
        "for": for_view,
        "against": against_view,
        "match_id": match_id,
        "squad_id": squad_id,
    }
    _MATCH_VIEW_MEM_CACHE[cache_key] = (now, payload)
    _write_json_cache(_match_view_cache_path(match_id, squad_id), payload)
    if not include_details:
        return _strip_match_view_details(for_view), _strip_match_view_details(against_view)
    return for_view, against_view



def _ensure_player_row(
    store: dict[int, dict[str, Any]],
    player_id: Any,
    *,
    name: str | None = None,
    initials: str | None = None,
) -> dict[str, Any] | None:
    if player_id is None or player_id == "":
        return None
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    bucket = store.setdefault(
        pid,
        {
            "player_id": pid,
            "name": name or f"Player {pid}",
            "initials": initials or "?",
            "takes": 0,
            "contacts": 0,
            "into_box": 0,
            "goals": 0,
            "xg": 0.0,
            "shots": 0,
        },
    )
    if name and str(bucket.get("name") or "").startswith("Player "):
        bucket["name"] = name
    if initials:
        bucket["initials"] = initials
    return bucket


def _merge_player_maps(
    target: dict[int, dict[str, Any]],
    incoming: dict[int, dict[str, Any]] | None,
) -> None:
    for player_id, row in (incoming or {}).items():
        bucket = _ensure_player_row(
            target,
            player_id,
            name=row.get("name"),
            initials=row.get("initials"),
        )
        if not bucket:
            continue
        bucket["takes"] += int(row.get("takes") or 0)
        bucket["contacts"] += int(row.get("contacts") or 0)
        bucket["into_box"] += int(row.get("into_box") or 0)
        bucket["goals"] += int(row.get("goals") or 0)
        bucket["shots"] += int(row.get("shots") or 0)
        bucket["xg"] = round(float(bucket.get("xg") or 0.0) + float(row.get("xg") or 0.0), 3)


def _merge_family_player_maps(
    target: dict[str, dict[int, dict[str, Any]]],
    incoming: dict[str, dict[int, dict[str, Any]]] | None,
) -> None:
    incoming = incoming or {}
    for family_key in ("corners", "freeKicks"):
        _merge_player_maps(target.setdefault(family_key, {}), incoming.get(family_key) or {})


def _rank_takers(leaders: dict[int, dict[str, Any]], *, limit: int = 4) -> list[dict[str, Any]]:
    rows = [row for row in leaders.values() if int(row.get("takes") or 0) > 0]
    rows.sort(
        key=lambda row: (
            -int(row.get("takes") or 0),
            str(row.get("name") or "").casefold(),
        )
    )
    return rows[:limit]


def _rank_goal_leaders(leaders: dict[int, dict[str, Any]], *, limit: int = 4) -> list[dict[str, Any]]:
    rows = [row for row in leaders.values() if int(row.get("goals") or 0) > 0]
    rows.sort(
        key=lambda row: (
            -int(row.get("goals") or 0),
            -float(row.get("xg") or 0),
            str(row.get("name") or "").casefold(),
        )
    )
    return rows[:limit]


def _rank_xg_leaders(leaders: dict[int, dict[str, Any]], *, limit: int = 4) -> list[dict[str, Any]]:
    rows = [row for row in leaders.values() if float(row.get("xg") or 0) > 0]
    rows.sort(
        key=lambda row: (
            -float(row.get("xg") or 0),
            -int(row.get("goals") or 0),
            str(row.get("name") or "").casefold(),
        )
    )
    return rows[:limit]


def _merge_contact_leaders(
    target: dict[int, dict[str, Any]],
    incoming: dict[int, dict[str, Any]],
) -> None:
    for player_id, row in incoming.items():
        bucket = target.setdefault(
            int(player_id),
            {
                "player_id": int(player_id),
                "name": row.get("name") or f"Player {player_id}",
                "initials": row.get("initials") or "?",
                "contacts": 0,
                "into_box": 0,
            },
        )
        bucket["contacts"] += int(row.get("contacts") or 0)
        bucket["into_box"] += int(row.get("into_box") or 0)
        if row.get("name") and (
            not bucket.get("name") or str(bucket["name"]).startswith("Player ")
        ):
            bucket["name"] = row["name"]
        if row.get("initials"):
            bucket["initials"] = row["initials"]


def _rank_contact_leaders(leaders: dict[int, dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    rows = list(leaders.values())
    rows.sort(
        key=lambda row: (
            -int(row.get("contacts") or 0),
            -int(row.get("into_box") or 0),
            str(row.get("name") or "").casefold(),
        )
    )
    return rows[:limit]


def _pitch_meta() -> dict[str, Any]:
    return {
        "goalX": PITCH_GOAL_X,
        "minX": FINAL_THIRD_MIN_X,
        "widthM": PITCH_WIDTH_M,
        "depthM": PITCH_GOAL_X - FINAL_THIRD_MIN_X,
        "penaltySpotM": 11.0,
        "penaltyArcM": 9.15,
        "penaltyBoxDepthM": 16.5,
        "penaltyBoxWidthM": 40.32,
        "sixYardDepthM": 5.5,
        "sixYardWidthM": 18.32,
    }


def _fixture_window_args(fixture: dict[str, Any]) -> tuple[str | None, int | None]:
    """Only clip recent matches before kickoff when the fixture is still upcoming."""
    scheduled = fixture.get("scheduled_date")
    match_id = fixture.get("match_id")
    if not scheduled:
        return None, int(match_id) if match_id else None
    try:
        dt = datetime.fromisoformat(str(scheduled).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None, int(match_id) if match_id else None
    now = datetime.now(UTC)
    if dt > now:
        return str(scheduled), int(match_id) if match_id else None
    # Past / backdata fixture: use latest completed matches in the season.
    return None, None


def _by_type_rows(counts: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {"label": label, "count": count}
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _side_payload(
    totals: dict[str, float],
    *,
    games: int,
    by_type: dict[str, int],
    corners: dict[str, float],
    free_kicks: dict[str, float],
    free_kick_by_type: dict[str, int],
    points: list[dict[str, Any]],
    leaders: dict[int, dict[str, Any]],
    trim_points,
    contact_by_family: dict[str, dict[int, dict[str, Any]]] | None = None,
    takers_by_family: dict[str, dict[int, dict[str, Any]]] | None = None,
    scorers_by_family: dict[str, dict[int, dict[str, Any]]] | None = None,
    contact_by_side: dict[str, dict[int, dict[str, Any]]] | None = None,
    takers_by_side: dict[str, dict[int, dict[str, Any]]] | None = None,
    scorers_by_side: dict[str, dict[int, dict[str, Any]]] | None = None,
    left: dict[str, float] | None = None,
    right: dict[str, float] | None = None,
    goal_points: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    contact_by_family = contact_by_family or {"corners": {}, "freeKicks": {}}
    takers_by_family = takers_by_family or {"corners": {}, "freeKicks": {}}
    scorers_by_family = scorers_by_family or {"corners": {}, "freeKicks": {}}
    contact_by_side = contact_by_side or {"left": {}, "right": {}}
    takers_by_side = takers_by_side or {"left": {}, "right": {}}
    scorers_by_side = scorers_by_side or {"left": {}, "right": {}}
    left = left or _empty_chain_totals()
    right = right or _empty_chain_totals()
    corner_block = {
        **_finalize_totals(corners, games),
        "label": "Corners",
        "firstContactLeaders": _rank_contact_leaders(contact_by_family.get("corners") or {}, limit=4),
        "takers": _rank_takers(takers_by_family.get("corners") or {}),
        "goalLeaders": _rank_goal_leaders(scorers_by_family.get("corners") or {}),
        "xgLeaders": _rank_xg_leaders(scorers_by_family.get("corners") or {}),
    }
    free_kick_block = {
        **_finalize_totals(free_kicks, games),
        "label": "Free kicks",
        "byType": _by_type_rows(free_kick_by_type),
        "firstContactLeaders": _rank_contact_leaders(contact_by_family.get("freeKicks") or {}, limit=4),
        "takers": _rank_takers(takers_by_family.get("freeKicks") or {}),
        "goalLeaders": _rank_goal_leaders(scorers_by_family.get("freeKicks") or {}),
        "xgLeaders": _rank_xg_leaders(scorers_by_family.get("freeKicks") or {}),
    }
    left_block = {
        **_finalize_totals(left, games),
        "label": "Left",
        "firstContactLeaders": _rank_contact_leaders(contact_by_side.get("left") or {}, limit=4),
        "takers": _rank_takers(takers_by_side.get("left") or {}),
        "goalLeaders": _rank_goal_leaders(scorers_by_side.get("left") or {}),
        "xgLeaders": _rank_xg_leaders(scorers_by_side.get("left") or {}),
    }
    right_block = {
        **_finalize_totals(right, games),
        "label": "Right",
        "firstContactLeaders": _rank_contact_leaders(contact_by_side.get("right") or {}, limit=4),
        "takers": _rank_takers(takers_by_side.get("right") or {}),
        "goalLeaders": _rank_goal_leaders(scorers_by_side.get("right") or {}),
        "xgLeaders": _rank_xg_leaders(scorers_by_side.get("right") or {}),
    }
    return {
        **_finalize_totals(totals, games),
        "byType": _by_type_rows(by_type),
        "corners": corner_block,
        "freeKicks": free_kick_block,
        "left": left_block,
        "right": right_block,
        "firstContactPoints": trim_points(points),
        "goalPoints": list(goal_points or []),
        "firstContactLeaders": _rank_contact_leaders(leaders),
        "firstContactTotal": len(points),
    }


def _attach_family_ranks(
    set_plays: dict[str, Any],
    *,
    iteration_id: int,
    squad_id: int,
) -> dict[str, Any]:
    """Legacy single-window rank attach — prefer _merge_dual_windows."""
    table = _squad_kpi_table(iteration_id)
    for side_key, defending in (("attacking", False), ("defending", True)):
        side = set_plays.get(side_key) or {}
        corners = side.get("corners") or {}
        free_kicks = side.get("freeKicks") or {}
        side["corners"] = _decorate_family_block(
            corners,
            table=table,
            squad_id=squad_id,
            family_key="corners",
            defending=defending,
            use_squad_season_rank=not defending,
        )
        side["freeKicks"] = _decorate_family_block(
            free_kicks,
            table=table,
            squad_id=squad_id,
            family_key="freeKicks",
            defending=defending,
            use_squad_season_rank=not defending,
        )
        set_plays[side_key] = side
    return set_plays


def _aggregate_recent_set_plays(
    iteration_id: int,
    squad_id: int,
    *,
    before: str | None = None,
    exclude_match_id: int | None = None,
    limit: int | None = SET_PIECE_MATCH_LIMIT,
    include_details: bool = True,
    player_names: dict[int, str] | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    recent = _recent_completed_matches(
        iteration_id,
        squad_id,
        limit=limit,
        before=before,
        exclude_match_id=exclude_match_id,
    )
    attacking = _empty_chain_totals()
    defending = _empty_chain_totals()
    attacking_corners = _empty_chain_totals()
    defending_corners = _empty_chain_totals()
    attacking_free_kicks = _empty_chain_totals()
    defending_free_kicks = _empty_chain_totals()
    attacking_left = _empty_chain_totals()
    defending_left = _empty_chain_totals()
    attacking_right = _empty_chain_totals()
    defending_right = _empty_chain_totals()
    by_type_for: dict[str, int] = {}
    by_type_against: dict[str, int] = {}
    fk_by_type_for: dict[str, int] = {}
    fk_by_type_against: dict[str, int] = {}
    attacking_points: list[dict[str, Any]] = []
    defending_points: list[dict[str, Any]] = []
    attacking_goal_points: list[dict[str, Any]] = []
    defending_goal_points: list[dict[str, Any]] = []
    attacking_leaders: dict[int, dict[str, Any]] = {}
    defending_leaders: dict[int, dict[str, Any]] = {}
    attacking_contact_by_family: dict[str, dict[int, dict[str, Any]]] = {
        "corners": {},
        "freeKicks": {},
    }
    defending_contact_by_family: dict[str, dict[int, dict[str, Any]]] = {
        "corners": {},
        "freeKicks": {},
    }
    attacking_takers_by_family: dict[str, dict[int, dict[str, Any]]] = {
        "corners": {},
        "freeKicks": {},
    }
    defending_takers_by_family: dict[str, dict[int, dict[str, Any]]] = {
        "corners": {},
        "freeKicks": {},
    }
    attacking_scorers_by_family: dict[str, dict[int, dict[str, Any]]] = {
        "corners": {},
        "freeKicks": {},
    }
    defending_scorers_by_family: dict[str, dict[int, dict[str, Any]]] = {
        "corners": {},
        "freeKicks": {},
    }
    attacking_contact_by_side: dict[str, dict[int, dict[str, Any]]] = {"left": {}, "right": {}}
    defending_contact_by_side: dict[str, dict[int, dict[str, Any]]] = {"left": {}, "right": {}}
    attacking_takers_by_side: dict[str, dict[int, dict[str, Any]]] = {"left": {}, "right": {}}
    defending_takers_by_side: dict[str, dict[int, dict[str, Any]]] = {"left": {}, "right": {}}
    attacking_scorers_by_side: dict[str, dict[int, dict[str, Any]]] = {"left": {}, "right": {}}
    defending_scorers_by_side: dict[str, dict[int, dict[str, Any]]] = {"left": {}, "right": {}}
    games = 0
    names = player_names if player_names is not None else _player_directory(iteration_id)

    def _job(match: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        return _match_both_sides_set_play_view(
            match,
            squad_id,
            names,
            include_details=include_details,
            refresh=refresh,
        )

    if recent:
        # Keep concurrency low — parallel event pulls trip Impect 429s on the live box.
        # Season (limit=None) runs sequentially; last-8 uses at most 2 workers.
        workers = 1 if limit is None else min(2, len(recent))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_job, match) for match in recent]
            for future in as_completed(futures):
                try:
                    for_view, against_view = future.result()
                except Exception:  # noqa: BLE001 - keep report usable if one match fails
                    continue
                games += 1
                for_summary = for_view["summary"]
                against_summary = against_view["summary"]
                _accumulate_summary(attacking, for_summary)
                _accumulate_summary(defending, against_summary)
                _accumulate_summary(attacking_corners, for_view.get("summaryCorners") or {})
                _accumulate_summary(defending_corners, against_view.get("summaryCorners") or {})
                _accumulate_summary(attacking_free_kicks, for_view.get("summaryFreeKicks") or {})
                _accumulate_summary(
                    defending_free_kicks, against_view.get("summaryFreeKicks") or {}
                )
                _accumulate_summary(attacking_left, for_view.get("summaryLeft") or {})
                _accumulate_summary(defending_left, against_view.get("summaryLeft") or {})
                _accumulate_summary(attacking_right, for_view.get("summaryRight") or {})
                _accumulate_summary(defending_right, against_view.get("summaryRight") or {})
                for label, count in (for_summary.get("byType") or {}).items():
                    by_type_for[label] = by_type_for.get(label, 0) + int(count)
                    if label != "Corner":
                        fk_by_type_for[label] = fk_by_type_for.get(label, 0) + int(count)
                for label, count in (against_summary.get("byType") or {}).items():
                    by_type_against[label] = by_type_against.get(label, 0) + int(count)
                    if label != "Corner":
                        fk_by_type_against[label] = (
                            fk_by_type_against.get(label, 0) + int(count)
                        )
                if include_details:
                    attacking_points.extend(for_view.get("firstContactPoints") or [])
                    defending_points.extend(against_view.get("firstContactPoints") or [])
                    attacking_goal_points.extend(for_view.get("goalPoints") or [])
                    defending_goal_points.extend(against_view.get("goalPoints") or [])
                    _merge_contact_leaders(attacking_leaders, for_view.get("contactLeaders") or {})
                    _merge_contact_leaders(defending_leaders, against_view.get("contactLeaders") or {})
                    _merge_family_player_maps(
                        attacking_contact_by_family, for_view.get("contactLeadersByFamily")
                    )
                    _merge_family_player_maps(
                        defending_contact_by_family, against_view.get("contactLeadersByFamily")
                    )
                    _merge_family_player_maps(
                        attacking_takers_by_family, for_view.get("takersByFamily")
                    )
                    _merge_family_player_maps(
                        defending_takers_by_family, against_view.get("takersByFamily")
                    )
                    _merge_family_player_maps(
                        attacking_scorers_by_family, for_view.get("scorersByFamily")
                    )
                    _merge_family_player_maps(
                        defending_scorers_by_family, against_view.get("scorersByFamily")
                    )
                    for side_key in ("left", "right"):
                        _merge_player_maps(
                            attacking_contact_by_side[side_key],
                            (for_view.get("contactLeadersBySide") or {}).get(side_key),
                        )
                        _merge_player_maps(
                            defending_contact_by_side[side_key],
                            (against_view.get("contactLeadersBySide") or {}).get(side_key),
                        )
                        _merge_player_maps(
                            attacking_takers_by_side[side_key],
                            (for_view.get("takersBySide") or {}).get(side_key),
                        )
                        _merge_player_maps(
                            defending_takers_by_side[side_key],
                            (against_view.get("takersBySide") or {}).get(side_key),
                        )
                        _merge_player_maps(
                            attacking_scorers_by_side[side_key],
                            (for_view.get("scorersBySide") or {}).get(side_key),
                        )
                        _merge_player_maps(
                            defending_scorers_by_side[side_key],
                            (against_view.get("scorersBySide") or {}).get(side_key),
                        )

    # Prefer into-box contacts on the map if we have many points.
    def _trim_points(points: list[dict[str, Any]], *, cap: int = 70) -> list[dict[str, Any]]:
        if len(points) <= cap:
            return points
        into_box = [pt for pt in points if pt.get("intoBox")]
        if len(into_box) >= min(cap, 20):
            return into_box[-cap:]
        return points[-cap:]

    return {
        "gameCount": games,
        "matchLimit": limit,
        "attacking": _side_payload(
            attacking,
            games=games,
            by_type=by_type_for,
            corners=attacking_corners,
            free_kicks=attacking_free_kicks,
            free_kick_by_type=fk_by_type_for,
            points=attacking_points,
            leaders=attacking_leaders,
            trim_points=_trim_points,
            contact_by_family=attacking_contact_by_family,
            takers_by_family=attacking_takers_by_family,
            scorers_by_family=attacking_scorers_by_family,
            contact_by_side=attacking_contact_by_side,
            takers_by_side=attacking_takers_by_side,
            scorers_by_side=attacking_scorers_by_side,
            left=attacking_left,
            right=attacking_right,
            goal_points=attacking_goal_points,
        ),
        "defending": _side_payload(
            defending,
            games=games,
            by_type=by_type_against,
            corners=defending_corners,
            free_kicks=defending_free_kicks,
            free_kick_by_type=fk_by_type_against,
            points=defending_points,
            leaders=defending_leaders,
            trim_points=_trim_points,
            contact_by_family=defending_contact_by_family,
            takers_by_family=defending_takers_by_family,
            scorers_by_family=defending_scorers_by_family,
            contact_by_side=defending_contact_by_side,
            takers_by_side=defending_takers_by_side,
            scorers_by_side=defending_scorers_by_side,
            left=defending_left,
            right=defending_right,
            goal_points=defending_goal_points,
        ),
        "pitch": _pitch_meta(),
        "typeLabels": dict(TYPE_LABELS),
        "scopeNote": "Corners and attacking-third free kicks only (throw-ins / deep FKs excluded).",
    }


def _accumulate_player_kpis(
    totals: dict[int, dict[str, float]],
    player_id: int,
    kpis: list[dict[str, Any]],
) -> None:
    name_by_id = _kpi_names()
    wanted = set(PLAYER_KPI_IDS.values())
    bucket = totals.setdefault(
        player_id,
        {key: 0.0 for key in PLAYER_KPI_IDS},
    )
    for item in kpis or []:
        kpi_id = item.get("kpiId")
        if kpi_id is None:
            continue
        kpi_id = int(kpi_id)
        if kpi_id not in wanted:
            continue
        name = name_by_id.get(kpi_id)
        if not name or name not in bucket:
            continue
        try:
            bucket[name] += float(item.get("value") or 0.0)
        except (TypeError, ValueError):
            continue


def _recent_player_set_piece_stats(
    iteration_id: int,
    squad_id: int,
    *,
    before: str | None = None,
    exclude_match_id: int | None = None,
    limit: int | None = SET_PIECE_MATCH_LIMIT,
) -> dict[int, dict[str, float]]:
    impect = _impect()
    recent = _recent_completed_matches(
        iteration_id,
        squad_id,
        limit=limit,
        before=before,
        exclude_match_id=exclude_match_id,
    )
    totals: dict[int, dict[str, float]] = {}

    def _job(match_id: int) -> list[tuple[int, list[dict[str, Any]]]]:
        payload = _unwrap_match_player_payload(
            impect._impect_get(
                f"/v5/{impect._api_prefix()}/matches/{match_id}/player-kpis"
            )["data"]
        )
        rows: list[tuple[int, list[dict[str, Any]]]] = []
        for side in ("squadHome", "squadAway"):
            squad = payload.get(side) or {}
            if int(squad.get("id") or -1) != squad_id:
                continue
            for row in squad.get("players") or []:
                player_id = row.get("id")
                if player_id is None:
                    continue
                rows.append((int(player_id), list(row.get("kpis") or [])))
        return rows

    if not recent:
        return totals

    with ThreadPoolExecutor(max_workers=min(4, len(recent))) as pool:
        futures = [pool.submit(_job, int(match["id"])) for match in recent]
        for future in as_completed(futures):
            try:
                rows = future.result()
            except Exception:  # noqa: BLE001
                continue
            for player_id, kpis in rows:
                _accumulate_player_kpis(totals, player_id, kpis)
    return totals


def _build_squad_rows(
    *,
    players_catalog: list[dict[str, Any]],
    squad_id: int,
    player_names: dict[int, str],
    set_piece_stats: dict[int, dict[str, float]],
    appearance_stats: dict[int, dict[str, Any]] | None = None,
    tm_heights: dict[str, int] | None = None,
    tm_profiles: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    appearance_stats = appearance_stats or {}
    tm_profiles = tm_profiles or {}
    tm_heights = tm_heights or {
        key: int(profile["height_cm"])
        for key, profile in tm_profiles.items()
        if profile.get("height_cm")
    }
    current = [
        player
        for player in players_catalog
        if int(player.get("currentSquadId") or -1) == squad_id
    ]
    seen_ids = {int(p["id"]) for p in current if p.get("id") is not None}
    catalog_by_id = {
        int(player["id"]): player
        for player in players_catalog
        if player.get("id") is not None
    }
    for player_id in set_piece_stats:
        if player_id not in seen_ids and player_id in catalog_by_id:
            current.append(catalog_by_id[player_id])
            seen_ids.add(player_id)
    # Recent match appearances (e.g. loanees / short-term) even without SP KPIs.
    for player_id in appearance_stats:
        if player_id not in seen_ids and player_id in catalog_by_id:
            current.append(catalog_by_id[player_id])
            seen_ids.add(player_id)

    rows: list[dict[str, Any]] = []
    matched_tm_keys: set[str] = set()
    for player in current:
        player_id = int(player["id"])
        apps = appearance_stats.get(player_id, {})
        positions = apps.get("positions") or set()
        primary = sorted(positions)[0] if positions else str(player.get("position") or "")
        sp = set_piece_stats.get(player_id, {})
        won = float(sp.get("WON_AERIAL_DUELS_AT_PHASE_SET_PIECE") or 0.0)
        lost = float(sp.get("LOST_AERIAL_DUELS_AT_PHASE_SET_PIECE") or 0.0)
        aerial_total = won + lost
        aerial_pct = round((won / aerial_total) * 100) if aerial_total else None
        name = player_names.get(player_id) or _player_display_name(player) or f"Player {player_id}"
        tm_key = _lookup_tm_profile_key(name, tm_profiles)
        profile = tm_profiles.get(tm_key) if tm_key else None
        if tm_key:
            matched_tm_keys.add(tm_key)
        cm = _height_cm(player) or (
            int(profile["height_cm"]) if profile and profile.get("height_cm") else None
        ) or _lookup_tm_height(name, tm_heights)
        height_label = _height_short(player) if _height_cm(player) else _height_label_from_cm(cm)
        position_label = _position_label(primary) if primary else "—"
        position_abbr = _position_abbr(primary)
        shirt_number = player.get("shirtNumber") or apps.get("shirt_number")
        if profile:
            if profile.get("is_gk") or str(profile.get("position_abbr") or "").upper() == "GK":
                position_label = "Goalkeeper"
                position_abbr = "GK"
            elif position_abbr in {"—", ""} and profile.get("position"):
                position_label = str(profile.get("position") or "—")
                position_abbr = str(profile.get("position_abbr") or _tm_position_abbr(position_label))
            if shirt_number is None and profile.get("shirt_number") is not None:
                shirt_number = profile.get("shirt_number")
        rows.append(
            {
                "player_id": player_id,
                "name": name,
                "surname": _player_surname(name),
                "shirt_number": shirt_number,
                "position": position_label,
                "position_abbr": position_abbr,
                "age": _player_age(player),
                "foot": _format_foot(player.get("leg")),
                "height_cm": cm,
                "height": height_label,
                "appearances": int(apps.get("appearances") or 0),
                "minutes": int(round(float(apps.get("minutes") or 0.0))),
                "aerial_won_sp": round(won, 1),
                "aerial_lost_sp": round(lost, 1),
                "aerial_win_pct_sp": aerial_pct,
                "shot_xg_sp": round(float(sp.get("SHOT_XG_AT_PHASE_SET_PIECE") or 0.0), 2),
                "goals_sp": round(float(sp.get("GOALS_AT_PHASE_SET_PIECE") or 0.0), 1),
                "shots_sp": round(float(sp.get("SHOT_AT_GOAL_NUMBER_AT_PHASE_SET_PIECE") or 0.0), 1),
                "bypassed_defenders_sp": round(
                    float(sp.get("BYPASSED_DEFENDERS_AT_PHASE_SET_PIECE") or 0.0), 1
                ),
                "tm_matched": bool(tm_key),
            }
        )

    # Transfermarkt-only outfield players missing from the Impect catalog.
    for key, profile in tm_profiles.items():
        if key in matched_tm_keys:
            continue
        if profile.get("is_gk") or str(profile.get("position_abbr") or "").upper() == "GK":
            continue
        name = str(profile.get("name") or key)
        cm = int(profile["height_cm"]) if profile.get("height_cm") else None
        rows.append(
            {
                "player_id": f"tm:{key}",
                "name": name,
                "surname": _player_surname(name),
                "shirt_number": profile.get("shirt_number"),
                "position": profile.get("position") or "—",
                "position_abbr": profile.get("position_abbr") or _tm_position_abbr(profile.get("position")),
                "age": None,
                "foot": "—",
                "height_cm": cm,
                "height": _height_label_from_cm(cm),
                "appearances": 0,
                "minutes": 0,
                "aerial_won_sp": 0.0,
                "aerial_lost_sp": 0.0,
                "aerial_win_pct_sp": None,
                "shot_xg_sp": 0.0,
                "goals_sp": 0.0,
                "shots_sp": 0.0,
                "bypassed_defenders_sp": 0.0,
                "tm_matched": True,
                "tm_only": True,
            }
        )

    rows.sort(
        key=lambda row: (
            -(row.get("height_cm") or 0),
            -float(row.get("aerial_won_sp") or 0),
            str(row.get("name") or "").casefold(),
        )
    )
    return rows


HEIGHT_BAND_DEFS: tuple[tuple[str, int | None, int | None], ...] = (
    # label, min_inches inclusive, max_inches inclusive (None = open)
    ("6'4\"+", 76, None),
    ("6'3\"", 75, 75),
    ("6'2\"", 74, 74),
    ("6'1\"", 73, 73),
    ("6'0\"", 72, 72),
    ("5'11\"", 71, 71),
    ("5'10\"", 70, 70),
    ("<5'9\"", None, 69),
)
HEIGHT_UNKNOWN_BAND = "No height"
HEIGHT_CHART_VERSION = 2


def _cm_to_total_inches(cm: int) -> int:
    return int(round(float(cm) / 2.54))


def _height_band_label(cm: int) -> str:
    inches = _cm_to_total_inches(cm)
    for label, min_in, max_in in HEIGHT_BAND_DEFS:
        if min_in is not None and inches < min_in:
            continue
        if max_in is not None and inches > max_in:
            continue
        return label
    return "<5'9\""


def _is_goalkeeper_row(row: dict[str, Any]) -> bool:
    abbr = str(row.get("position_abbr") or "").strip().upper()
    position = str(row.get("position") or "").strip().upper()
    if abbr in {"GK", "GKP", "GOALKEEPER"}:
        return True
    if "GOALKEEPER" in position or position in {"GK", "GKP"}:
        return True
    if row.get("is_gk") is True:
        return True
    return False


def _empty_height_chart(*, excluded_gk: int = 0) -> dict[str, Any]:
    return {
        "bands": [
            {"label": label, "players": []}
            for label, _, _ in HEIGHT_BAND_DEFS
        ],
        "unknown": [],
        "players": [],
        "avg_cm": None,
        "max_cm": None,
        "min_cm": None,
        "count": 0,
        "unknown_count": 0,
        "excluded_gk": excluded_gk,
        "version": HEIGHT_CHART_VERSION,
    }


def _height_chart(
    rows: list[dict[str, Any]],
    *,
    club_name: str | None = None,
    season: str | None = None,
) -> dict[str, Any]:
    outfield = [row for row in rows if not _is_goalkeeper_row(row)]
    excluded_gk = len(rows) - len(outfield)
    with_height = [row for row in outfield if row.get("height_cm")]
    without_height = [row for row in outfield if not row.get("height_cm")]
    if not with_height and not without_height:
        return _empty_height_chart(excluded_gk=excluded_gk)

    photo_seed = [
        {
            "name": row["name"],
            "player_id": row["player_id"],
        }
        for row in [*with_height, *without_height]
    ]
    if club_name:
        attach_pitch_player_photos(photo_seed, club_name=club_name, season=season)
    photo_by_id = {
        row["player_id"]: row.get("photo_url")
        for row in photo_seed
        if row.get("player_id") is not None
    }

    def _entry(row: dict[str, Any], *, band: str) -> dict[str, Any]:
        photo_url = photo_by_id.get(row["player_id"]) or opponent_photo_api_url(
            str(row["name"]),
            club_name=club_name,
            season=season,
        )
        return {
            "player_id": row["player_id"],
            "name": row["name"],
            "surname": row["surname"],
            "shirt_number": row.get("shirt_number"),
            "position_abbr": row.get("position_abbr"),
            "height_cm": row.get("height_cm"),
            "height": row.get("height") or "—",
            "band": band,
            "photo_url": photo_url,
        }

    band_players: dict[str, list[dict[str, Any]]] = {label: [] for label, _, _ in HEIGHT_BAND_DEFS}
    chart_players: list[dict[str, Any]] = []
    for row in sorted(with_height, key=lambda item: int(item["height_cm"]), reverse=True):
        label = _height_band_label(int(row["height_cm"]))
        entry = _entry(row, band=label)
        band_players.setdefault(label, []).append(entry)
        chart_players.append(entry)

    unknown_players: list[dict[str, Any]] = []
    for row in sorted(
        without_height,
        key=lambda item: (
            str(item.get("surname") or "").casefold(),
            str(item.get("name") or "").casefold(),
        ),
    ):
        entry = _entry(row, band=HEIGHT_UNKNOWN_BAND)
        unknown_players.append(entry)
        chart_players.append(entry)

    for label in band_players:
        band_players[label].sort(
            key=lambda item: (
                -int(item.get("height_cm") or 0),
                str(item.get("surname") or "").casefold(),
            )
        )

    cms = [int(row["height_cm"]) for row in with_height]
    return {
        "bands": [
            {"label": label, "players": band_players.get(label, [])}
            for label, _, _ in HEIGHT_BAND_DEFS
        ],
        "unknown": unknown_players,
        "players": chart_players,
        "avg_cm": round(sum(cms) / len(cms)) if cms else None,
        "max_cm": max(cms) if cms else None,
        "min_cm": min(cms) if cms else None,
        "count": len(with_height),
        "unknown_count": len(unknown_players),
        "excluded_gk": excluded_gk,
        "version": HEIGHT_CHART_VERSION,
    }



def _aerial_leaders(rows: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    ranked = [
        row
        for row in rows
        if float(row.get("aerial_won_sp") or 0) > 0 or float(row.get("aerial_lost_sp") or 0) > 0
    ]
    ranked.sort(
        key=lambda row: (
            -float(row.get("aerial_won_sp") or 0),
            -(row.get("aerial_win_pct_sp") or 0),
            str(row.get("name") or "").casefold(),
        )
    )
    return ranked[:limit]


def _threat_leaders(rows: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    ranked = [
        row
        for row in rows
        if float(row.get("shot_xg_sp") or 0) > 0
        or float(row.get("goals_sp") or 0) > 0
        or float(row.get("shots_sp") or 0) > 0
    ]
    ranked.sort(
        key=lambda row: (
            -float(row.get("shot_xg_sp") or 0),
            -float(row.get("goals_sp") or 0),
            -float(row.get("shots_sp") or 0),
        )
    )
    return ranked[:limit]


def build_set_piece_pre_match_report(body: SetPiecePreMatchRequest | PreMatchReportRequest) -> dict[str, Any]:
    iteration_id = int(body.iteration_id)
    squad_id = int(body.squad_id)
    match_limit = SET_PIECE_MATCH_LIMIT
    refresh = bool(getattr(body, "refresh", False))
    impect = _impect()

    fixtures = build_pre_match_fixtures(iteration_id)
    fixture = next(
        (
            row
            for row in fixtures
            if int(row.get("opponent", {}).get("id") or -1) == squad_id
            and (body.match_id is None or int(row.get("match_id") or -1) == int(body.match_id or -1))
        ),
        None,
    )
    if fixture is None:
        fixture = next(
            (
                row
                for row in fixtures
                if int(row.get("opponent", {}).get("id") or -1) == squad_id
            ),
            None,
        )
    if fixture is None:
        from app.pre_match import _squads_map

        squads = _squads_map(iteration_id)
        opponent = squads.get(squad_id) or {"id": squad_id, "name": f"Squad {squad_id}"}
        fixture = {
            "match_id": body.match_id,
            "scheduled_date": None,
            "is_home": True,
            "opponent": opponent,
            "port_vale": {"name": "Port Vale"},
        }

    before, exclude_match_id = _fixture_window_args(fixture)
    report_key = _report_cache_key(
        iteration_id,
        squad_id,
        before=before,
        exclude_match_id=exclude_match_id,
    )
    if not refresh:
        cached_report = _load_cached_report(report_key)
        if cached_report and not _height_chart_incomplete(cached_report) and not _for_slide_incomplete(cached_report) and not _against_slide_incomplete(cached_report):
            cached_report = dict(cached_report)
            cached_report["cache"] = {"hit": True, "refreshed": False}
            return cached_report

    try:
        return _build_set_piece_pre_match_report_uncached(
            body,
            fixture=fixture,
            before=before,
            exclude_match_id=exclude_match_id,
            report_key=report_key,
            refresh=refresh,
            match_limit=match_limit,
            impect=impect,
        )
    except HTTPException as exc:
        if exc.status_code == 429:
            stale = _load_cached_report(report_key)
            if stale:
                stale = dict(stale)
                stale["cache"] = {
                    "hit": True,
                    "refreshed": False,
                    "stale": True,
                    "note": "Served cached report because Impect rate-limited a rebuild.",
                }
                return stale
        raise


def _build_set_piece_pre_match_report_uncached(
    body: SetPiecePreMatchRequest | PreMatchReportRequest,
    *,
    fixture: dict[str, Any],
    before: str | None,
    exclude_match_id: int | None,
    report_key: str,
    refresh: bool,
    match_limit: int,
    impect: Any,
) -> dict[str, Any]:
    iteration_id = int(body.iteration_id)
    squad_id = int(body.squad_id)

    players = _unwrap_items(impect._impect_get(impect._players_path(iteration_id))["data"])
    player_names = {
        int(player["id"]): _player_display_name(player)
        for player in players
        if player.get("id") is not None
    }

    opponent = fixture.get("opponent") or {"id": squad_id, "name": "Opponent"}
    opponent_name = str(opponent.get("name") or "Opponent")
    season_label = ""
    try:
        iterations = impect._fetch_iterations()
        season_label = next(
            (
                str(item.get("season") or "")
                for item in iterations
                if int(item.get("id") or -1) == iteration_id
            ),
            "",
        )
    except Exception:  # noqa: BLE001
        season_label = ""

    appearance_stats: dict[int, dict[str, Any]] = {}
    for match in _recent_completed_matches(
        iteration_id,
        squad_id,
        limit=match_limit,
        before=before,
        exclude_match_id=exclude_match_id,
    ):
        detail = _fetch_match_detail(int(match["id"]))
        squad_block = _match_squad_block(detail, squad_id) or {}
        for row in squad_block.get("players") or []:
            if not isinstance(row, dict):
                continue
            player_id = int(row.get("id") or 0)
            if not player_id:
                continue
            bucket = appearance_stats.setdefault(
                player_id,
                {"appearances": 0, "minutes": 0.0, "positions": set(), "shirt_number": None},
            )
            bucket["appearances"] += 1
            pos = row.get("position")
            if pos:
                bucket["positions"].add(str(pos))
            shirt = row.get("shirtNumber")
            if shirt is not None and bucket["shirt_number"] is None:
                try:
                    bucket["shirt_number"] = int(shirt)
                except (TypeError, ValueError):
                    pass

    with ThreadPoolExecutor(max_workers=3) as pool:
        rankings_future = pool.submit(_team_set_piece_rankings, iteration_id, squad_id)
        player_sp_future = pool.submit(
            _recent_player_set_piece_stats,
            iteration_id,
            squad_id,
            before=before,
            exclude_match_id=exclude_match_id,
            limit=match_limit,
        )
        heights_future = pool.submit(
            _fetch_transfermarkt_squad_profiles, opponent_name, season_label
        )
        rankings = rankings_future.result()
        player_sp = player_sp_future.result()
        tm_profiles = heights_future.result()

    # One window: every completed match (no last-8 vs season split).
    set_plays = _aggregate_recent_set_plays(
        iteration_id,
        squad_id,
        before=before,
        exclude_match_id=exclude_match_id,
        limit=None,
        include_details=True,
        player_names=player_names,
        refresh=refresh,
    )
    set_plays = _attach_family_ranks(
        set_plays,
        iteration_id=iteration_id,
        squad_id=squad_id,
    )
    tm_heights = {
        key: int(profile["height_cm"])
        for key, profile in tm_profiles.items()
        if profile.get("height_cm")
    }

    squad_rows = _build_squad_rows(
        players_catalog=players,
        squad_id=squad_id,
        player_names=player_names,
        set_piece_stats=player_sp,
        appearance_stats=appearance_stats,
        tm_heights=tm_heights,
        tm_profiles=tm_profiles,
    )
    height_chart = _height_chart(
        squad_rows,
        club_name=opponent_name,
        season=season_label,
    )

    fixture_out = {
        **fixture,
        "port_vale": enrich_team_badge(
            fixture.get("port_vale") or {"name": "Port Vale"},
            iteration_id,
        ),
        "opponent": enrich_team_badge(
            {**opponent, "id": squad_id},
            iteration_id,
        ),
    }
    opponent_badge = (
        (fixture_out.get("opponent") or {}).get("badge_url")
        or (fixture_out.get("opponent") or {}).get("image")
        or (fixture_out.get("opponent") or {}).get("image_url")
    )

    games_used = int(set_plays.get("gameCount") or 0)
    season_games = games_used

    report = {
        "fixture": fixture_out,
        "opponent": {
            "id": squad_id,
            "name": opponent_name,
            "image": opponent_badge,
            "badge_url": opponent_badge,
        },
        "season": season_label,
        "iteration_id": iteration_id,
        "match_window": games_used,
        "match_window_label": f"{games_used} games" if games_used else "Season",
        "season_games": season_games,
        "team_metrics": rankings,
        "set_plays": set_plays,
        "squad": squad_rows,
        "height_chart": height_chart,
        "aerial_leaders": _aerial_leaders(squad_rows),
        "threat_leaders": _threat_leaders(squad_rows),
        "cache": {"hit": False, "refreshed": refresh},
        "source": {
            "note": (
                f"Set-play cards use every completed match this season "
                f"({season_games or 'all'}). Maps show first contacts won, split by "
                "left / right delivery. Team rankings use full-season Impect squad KPIs. "
                "Heights from Transfermarkt; headshots from club site when available. "
                "Reports are disk-cached — use Refresh data to rebuild."
            ),
            "endpoints": [
                "iterations/{id}/squad-kpis",
                "matches/{id}/events",
                "matches/{id}/event-kpis",
                "matches/{id}/player-kpis",
                "iterations/{id}/players",
                "Transfermarkt kader (heights)",
                "Club website / Transfermarkt (photos)",
            ],
        },
    }
    _store_cached_report(report_key, report)
    return report


def register_set_piece_pre_match_routes(app: FastAPI) -> None:
    no_cache = {
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    @app.get("/set-piece-pre-match", response_class=HTMLResponse)
    def set_piece_pre_match_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "set-piece-pre-match.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Set Piece Pre-Match page not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"), headers=no_cache)

    @app.get("/set-piece-pre-match/assets/app.js")
    def set_piece_pre_match_js() -> FileResponse:
        path = STATIC_DIR / "set-piece-pre-match.js"
        if not path.exists():
            raise HTTPException(status_code=404, detail="JS not found.")
        return FileResponse(path, media_type="application/javascript", headers=no_cache)

    @app.get("/set-piece-pre-match/assets/app.css")
    def set_piece_pre_match_css() -> FileResponse:
        path = STATIC_DIR / "set-piece-pre-match.css"
        if not path.exists():
            raise HTTPException(status_code=404, detail="CSS not found.")
        return FileResponse(path, media_type="text/css", headers=no_cache)

    @app.get("/api/set-piece-pre-match/meta")
    def set_piece_pre_match_meta_route(
        competition: str = Query(DEFAULT_COMPETITION, min_length=1),
    ) -> dict[str, Any]:
        return pre_match_meta(competition)

    @app.get("/api/set-piece-pre-match/fixtures")
    def set_piece_pre_match_fixtures(iteration_id: int = Query(..., ge=1)) -> dict[str, Any]:
        return {"fixtures": build_pre_match_fixtures(iteration_id)}

    @app.post("/api/set-piece-pre-match/report")
    def set_piece_pre_match_report(body: SetPiecePreMatchRequest) -> dict[str, Any]:
        return build_set_piece_pre_match_report(body)

    @app.post("/api/set-piece-pre-match/export-whatsapp-pdf")
    def set_piece_pre_match_export_whatsapp_pdf(body: PreMatchPngExportRequest) -> Response:
        from app.main import _safe_export_filename, _save_export_to_desktop

        if not body.html_pages and not body.pages:
            raise HTTPException(status_code=400, detail="No export pages provided.")
        try:
            pdf_bytes = build_pre_match_whatsapp_pdf(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        opponent = re.sub(r"[^\w\s\-]+", "", str(body.opponent_name or "opponent"))
        opponent = re.sub(r"\s+", "-", opponent).strip("-") or "opponent"
        default_name = f"port-vale-set-piece-{opponent}-whatsapp.pdf"
        filename = _safe_export_filename(body.filename or default_name, default_ext=".pdf")
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        saved_path = _save_export_to_desktop(pdf_bytes, filename)
        if saved_path is not None:
            headers["X-Saved-Desktop-Path"] = str(saved_path)
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
