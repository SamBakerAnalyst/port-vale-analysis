from __future__ import annotations

import base64
import hashlib
import io
import math
import re
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from app.opponent_photos import (
    attach_pitch_player_photos,
    fetch_opponent_photo_bytes,
    player_on_transfermarkt_squad,
    resolve_opponent_photo_source_url,
    resolve_transfermarkt_club_id,
    transfermarkt_entry_is_loaned_out,
    transfermarkt_first_team_roster,
)
from app.paths import HUB_ROOT
from app.scouting import SCOUTING_DIR
from app.squad_photos import fetch_photo_bytes, resolve_local_photo_path

_PLAYER_PHOTO_CACHE_TTL_SECONDS = 6 * 60 * 60
_player_photo_bytes_cache: dict[str, tuple[float, bytes, str]] = {}


def _player_photo_cache_key(name: str, club: str | None, season: str | None) -> str:
    parts = [re.sub(r"\s+", " ", str(name or "").strip().casefold())]
    if club:
        parts.append(re.sub(r"\s+", " ", str(club).strip().casefold()))
    if season:
        parts.append(re.sub(r"\s+", " ", str(season).strip().casefold()))
    return "|".join(parts)


def _resolve_player_photo_bytes(
    name: str,
    *,
    club: str | None,
    season: str | None,
) -> tuple[bytes, str]:
    cache_key = _player_photo_cache_key(name, club, season)
    cached = _player_photo_bytes_cache.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _PLAYER_PHOTO_CACHE_TTL_SECONDS:
        return cached[1], cached[2]

    local_path = resolve_local_photo_path(name)
    if local_path is not None:
        image_bytes = local_path.read_bytes()
        ext = local_path.suffix.lower()
        content_type = {
            ".png": "image/png",
            ".webp": "image/webp",
            ".jpeg": "image/jpeg",
            ".jpg": "image/jpeg",
        }.get(ext, "image/jpeg")
        _player_photo_bytes_cache[cache_key] = (now, image_bytes, content_type)
        return image_bytes, content_type

    source_url = resolve_opponent_photo_source_url(
        name,
        club_name=club,
        season=season,
    )
    if not source_url:
        raise HTTPException(status_code=404, detail=f"No photo found for {name}")

    try:
        if "transfermarkt" in source_url:
            image_bytes, content_type = fetch_opponent_photo_bytes(source_url)
        else:
            image_bytes, content_type = fetch_photo_bytes(source_url)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _player_photo_bytes_cache[cache_key] = (now, image_bytes, content_type)
    return image_bytes, content_type

DEFAULT_COMPETITION = "League One"
PORT_VALE_TOKENS = ("port vale",)
# Current + previous League One season for the pre-match designer toggle.
PRE_MATCH_SEASON_LIMIT = 2
# While building the deck, open last season on a known completed fixture.
PRE_MATCH_DEFAULT_SEASON_INDEX = 1

# Impect occasionally omits squad crests (Burton Albion in 25/26). Fall back to FotMob.
_SQUAD_CREST_FOTMOB_IDS: dict[str, int] = {
    "burton albion": 9792,
}


def _normalize_club_key(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").casefold()).strip()


def _squad_crest_url(name: str | None, image_url: Any = None) -> str | None:
    if _is_port_vale(str(name or "")):
        return "/standalone/port-vale-badge.png?v=2"
    token = str(image_url or "").strip()
    if token.startswith("http"):
        return token
    fotmob_id = _SQUAD_CREST_FOTMOB_IDS.get(_normalize_club_key(name))
    if fotmob_id:
        return f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_id}.png"
    return None


def _enrich_team_crest(team: dict[str, Any], iteration_id: int) -> dict[str, Any]:
    """Prefer a same-origin crest so the UI and PDF export both render badges."""
    from app.handout_badges import resolve_handout_badge_url

    enriched = dict(team)
    badge_url = resolve_handout_badge_url(
        int(team.get("id") or 0) or None,
        iteration_id,
        str(team.get("name") or ""),
    )
    if badge_url:
        enriched["badge_url"] = badge_url
        enriched["image_url"] = badge_url
    elif not enriched.get("image_url"):
        fallback = _squad_crest_url(team.get("name"), None)
        if fallback:
            enriched["image_url"] = fallback
    return enriched
PRE_MATCH_DEFAULT_OPPONENT_NAMES: tuple[str, ...] = ("Lincoln City", "Mansfield Town")

_kpi_name_cache: tuple[float, dict[int, str]] | None = None
_squad_kpi_cache: dict[int, tuple[float, dict[int, dict[str, float]]]] = {}
_player_match_stats_cache: dict[tuple[Any, ...], tuple[float, dict[int, dict[str, Any]]]] = {}
_match_detail_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_coaches_cache: dict[int, tuple[float, dict[int, str]]] = {}

AVERAGE_SHAPE_MATCH_LIMIT = 8
MIN_PITCH_MINUTES = 45
PITCH_STARTER_LIMIT = 11
PREVIOUS_XI_LIMIT = 3
LAST_GAME_PHASE_LIMIT = 3

SIDE_X: dict[str, float] = {
    "LEFT": 12.0,
    "CENTRE_LEFT": 28.0,
    "CENTER_LEFT": 28.0,
    "CENTRE": 50.0,
    "CENTER": 50.0,
    "CENTRE_RIGHT": 72.0,
    "CENTER_RIGHT": 72.0,
    "RIGHT": 88.0,
}
BAND_Y: dict[str, float] = {
    "gk": 94.0,
    "def": 74.0,
    "mid": 48.0,
    "attack": 18.0,
}

POSITION_Y: dict[str, float] = {
    "GOALKEEPER": 94.0,
    "CENTRAL_DEFENDER": 76.0,
    "LEFT_WINGBACK_DEFENDER": 72.0,
    "RIGHT_WINGBACK_DEFENDER": 72.0,
    "DEFENSE_MIDFIELD": 54.0,
    "CENTRAL_MIDFIELD": 46.0,
    "ATTACKING_MIDFIELD": 30.0,
    "LEFT_WINGER": 20.0,
    "RIGHT_WINGER": 20.0,
    "CENTER_FORWARD": 12.0,
    "SECOND_STRIKER": 16.0,
}

# (slot position, x%, y%, preferred side)
# y% maps to pitch top: low = attack, high = defence/GK (matches reference handout layouts).
FORMATION_TEMPLATES: dict[str, list[tuple[str, float, float, str]]] = {
    "4-2-3-1": [
        ("GOALKEEPER", 50.0, 94.0, "any"),
        ("LEFT_WINGBACK_DEFENDER", 9.0, 74.0, "left"),
        ("CENTRAL_DEFENDER", 32.0, 76.0, "left"),
        ("CENTRAL_DEFENDER", 68.0, 76.0, "right"),
        ("RIGHT_WINGBACK_DEFENDER", 91.0, 74.0, "right"),
        ("DEFENSE_MIDFIELD", 34.0, 50.0, "left"),
        ("DEFENSE_MIDFIELD", 66.0, 50.0, "right"),
        ("LEFT_WINGER", 10.0, 24.0, "left"),
        ("ATTACKING_MIDFIELD", 50.0, 28.0, "center"),
        ("RIGHT_WINGER", 90.0, 24.0, "right"),
        ("CENTER_FORWARD", 50.0, 11.0, "center"),
    ],
    "4-4-2": [
        ("GOALKEEPER", 50.0, 94.0, "any"),
        ("LEFT_WINGBACK_DEFENDER", 9.0, 74.0, "left"),
        ("CENTRAL_DEFENDER", 32.0, 76.0, "left"),
        ("CENTRAL_DEFENDER", 68.0, 76.0, "right"),
        ("RIGHT_WINGBACK_DEFENDER", 91.0, 74.0, "right"),
        ("LEFT_WINGER", 10.0, 48.0, "left"),
        ("CENTRAL_MIDFIELD", 36.0, 48.0, "left"),
        ("CENTRAL_MIDFIELD", 64.0, 48.0, "right"),
        ("RIGHT_WINGER", 90.0, 48.0, "right"),
        ("CENTER_FORWARD", 36.0, 12.0, "left"),
        ("CENTER_FORWARD", 64.0, 12.0, "right"),
    ],
    "4-3-3": [
        ("GOALKEEPER", 50.0, 94.0, "any"),
        ("LEFT_WINGBACK_DEFENDER", 9.0, 74.0, "left"),
        ("CENTRAL_DEFENDER", 32.0, 76.0, "left"),
        ("CENTRAL_DEFENDER", 68.0, 76.0, "right"),
        ("RIGHT_WINGBACK_DEFENDER", 91.0, 74.0, "right"),
        ("DEFENSE_MIDFIELD", 50.0, 54.0, "center"),
        ("CENTRAL_MIDFIELD", 32.0, 44.0, "left"),
        ("CENTRAL_MIDFIELD", 68.0, 44.0, "right"),
        ("LEFT_WINGER", 12.0, 18.0, "left"),
        ("CENTER_FORWARD", 50.0, 11.0, "center"),
        ("RIGHT_WINGER", 88.0, 18.0, "right"),
    ],
    "5-3-2": [
        ("GOALKEEPER", 50.0, 94.0, "any"),
        ("LEFT_WINGBACK_DEFENDER", 8.0, 62.0, "left"),
        ("CENTRAL_DEFENDER", 27.0, 76.0, "left"),
        ("CENTRAL_DEFENDER", 50.0, 78.0, "center"),
        ("CENTRAL_DEFENDER", 73.0, 76.0, "right"),
        ("RIGHT_WINGBACK_DEFENDER", 92.0, 62.0, "right"),
        ("DEFENSE_MIDFIELD", 50.0, 52.0, "center"),
        ("CENTRAL_MIDFIELD", 32.0, 44.0, "left"),
        ("CENTRAL_MIDFIELD", 68.0, 44.0, "right"),
        ("CENTER_FORWARD", 34.0, 14.0, "left"),
        ("CENTER_FORWARD", 66.0, 14.0, "right"),
    ],
    "3-5-2": [
        ("GOALKEEPER", 50.0, 94.0, "any"),
        ("LEFT_WINGBACK_DEFENDER", 8.0, 58.0, "left"),
        ("CENTRAL_DEFENDER", 27.0, 76.0, "left"),
        ("CENTRAL_DEFENDER", 50.0, 78.0, "center"),
        ("CENTRAL_DEFENDER", 73.0, 76.0, "right"),
        ("RIGHT_WINGBACK_DEFENDER", 92.0, 58.0, "right"),
        ("DEFENSE_MIDFIELD", 50.0, 52.0, "center"),
        ("CENTRAL_MIDFIELD", 32.0, 42.0, "left"),
        ("CENTRAL_MIDFIELD", 68.0, 42.0, "right"),
        ("CENTER_FORWARD", 34.0, 14.0, "left"),
        ("CENTER_FORWARD", 66.0, 14.0, "right"),
    ],
    "5-2-2-1": [
        ("GOALKEEPER", 50.0, 94.0, "any"),
        ("LEFT_WINGBACK_DEFENDER", 7.0, 56.0, "left"),
        ("CENTRAL_DEFENDER", 28.0, 78.0, "left"),
        ("CENTRAL_DEFENDER", 50.0, 80.0, "center"),
        ("CENTRAL_DEFENDER", 72.0, 78.0, "right"),
        ("RIGHT_WINGBACK_DEFENDER", 93.0, 56.0, "right"),
        ("DEFENSE_MIDFIELD", 36.0, 52.0, "left"),
        ("DEFENSE_MIDFIELD", 64.0, 52.0, "right"),
        ("CENTRAL_MIDFIELD", 34.0, 34.0, "left"),
        ("CENTRAL_MIDFIELD", 66.0, 34.0, "right"),
        ("CENTER_FORWARD", 50.0, 11.0, "center"),
    ],
}

SLOT_ASSIGNMENT_PRIORITY: dict[str, int] = {
    "GOALKEEPER": 0,
    "CENTER_FORWARD": 10,
    "LEFT_WINGER": 20,
    "RIGHT_WINGER": 21,
    "DEFENSE_MIDFIELD": 30,
    "ATTACKING_MIDFIELD": 35,
    "CENTRAL_MIDFIELD": 36,
    "LEFT_WINGBACK_DEFENDER": 50,
    "RIGHT_WINGBACK_DEFENDER": 51,
    "CENTRAL_DEFENDER": 60,
}

POSITION_SLOT_ALIASES: dict[str, set[str]] = {
    "LEFT_WINGER": {"LEFT_WINGER", "LEFT_MIDFIELD"},
    "RIGHT_WINGER": {"RIGHT_WINGER", "RIGHT_MIDFIELD"},
    "CENTRAL_MIDFIELD": {"CENTRAL_MIDFIELD", "DEFENSE_MIDFIELD", "ATTACKING_MIDFIELD"},
    "DEFENSE_MIDFIELD": {"DEFENSE_MIDFIELD", "CENTRAL_MIDFIELD"},
    "ATTACKING_MIDFIELD": {"ATTACKING_MIDFIELD", "CENTRAL_MIDFIELD"},
    "CENTER_FORWARD": {"CENTER_FORWARD", "SECOND_STRIKER"},
}

CACHE_TTL_SECONDS = 3600

IN_POSSESSION_METRICS: tuple[dict[str, Any], ...] = (
    {"key": "SHOT_XG", "label": "xG", "higher_better": True},
    {"key": "GOALS", "label": "Goals Scored", "higher_better": True},
    {"key": "SHOT_AT_GOAL_NUMBER", "label": "Shots", "higher_better": True},
    {
        "key": "CROSSES",
        "label": "Crosses",
        "higher_better": True,
        "compute": lambda stats: (
            stats.get("SUCCESSFUL_PASSES_BY_ACTION_HIGH_CROSS", 0.0)
            + stats.get("SUCCESSFUL_PASSES_BY_ACTION_LOW_CROSS", 0.0)
            + stats.get("UNSUCCESSFUL_PASSES_BY_ACTION_HIGH_CROSS", 0.0)
            + stats.get("UNSUCCESSFUL_PASSES_BY_ACTION_LOW_CROSS", 0.0)
        ),
    },
    {
        "key": "POSSESSION_PROXY",
        "label": "In-possession touches",
        "higher_better": True,
        "compute": lambda stats: stats.get("OFFENSIVE_TOUCHES_AT_PHASE_IN_POSSESSION", 0.0),
    },
)

OUT_OF_POSSESSION_METRICS: tuple[dict[str, Any], ...] = (
    {"key": "CONCEDED_SHOT_XG", "label": "xG Against", "higher_better": False},
    {"key": "CONCEDED_GOALS", "label": "Goals Against", "higher_better": False},
    {
        "key": "NUMBER_OF_PRESSES",
        "label": "Presses",
        "higher_better": True,
    },
    {
        "key": "AERIAL_WIN_PCT",
        "label": "Aerial Win %",
        "higher_better": True,
        "percent": True,
        "compute": lambda stats: _aerial_win_pct(stats),
    },
)

# Compact key metrics for the Squad List side panel (in / out of possession columns).
SQUAD_LIST_IN_POSSESSION_METRICS: tuple[dict[str, Any], ...] = (
    {"key": "GOALS", "label": "Goals for", "higher_better": True},
    {"key": "SHOT_XG", "label": "xG", "higher_better": True},
    {"key": "SHOT_AT_GOAL_NUMBER", "label": "Shots", "higher_better": True},
    {"key": "BYPASSED_OPPONENTS", "label": "Bypassed opponents", "higher_better": True},
    {
        "key": "CROSSES",
        "label": "Crosses",
        "higher_better": True,
        "compute": lambda stats: (
            stats.get("SUCCESSFUL_PASSES_BY_ACTION_HIGH_CROSS", 0.0)
            + stats.get("SUCCESSFUL_PASSES_BY_ACTION_LOW_CROSS", 0.0)
            + stats.get("UNSUCCESSFUL_PASSES_BY_ACTION_HIGH_CROSS", 0.0)
            + stats.get("UNSUCCESSFUL_PASSES_BY_ACTION_LOW_CROSS", 0.0)
        ),
    },
)
SQUAD_LIST_OUT_OF_POSSESSION_METRICS: tuple[dict[str, Any], ...] = (
    {"key": "CONCEDED_GOALS", "label": "Goals against", "higher_better": False},
    {"key": "CONCEDED_SHOT_XG", "label": "xG against", "higher_better": False},
    {
        "key": "SUFFERED_BYPASSED_OPPONENTS",
        "label": "Bypassed against",
        "higher_better": False,
    },
    {
        # Impect UI "Offensive Interventions" = packing opponents removed on ball wins.
        "key": "BALL_WIN_REMOVED_OPPONENTS",
        "label": "Offensive interventions",
        "higher_better": True,
    },
    {
        "key": "BALL_WIN_REMOVED_OPPONENTS_DEFENDERS",
        "label": "Ball wins off defenders",
        "higher_better": True,
    },
)

# Tactical radar axes derived from Impect squad-scores (league percentile ranks).
TEAM_STYLE_RADAR_AXES: tuple[dict[str, Any], ...] = (
    {
        "key": "possession",
        "label": "Possession",
        "hint": "Ball retention vs the rest of the league",
        "scores": ((23, False),),
    },
    {
        "key": "pressing",
        "label": "Pressing",
        "hint": "Opening-ball press, PPDA, and average press height",
        "scores": ((63, False), (112, True), (57, False)),
    },
    {
        "key": "progression",
        "label": "Progression",
        "hint": "Bypassing opponents and positive packing threat",
        "scores": ((98, False), (48, False)),
    },
    {
        "key": "aerial",
        "label": "Aerial",
        "hint": "Aerial duel share vs the league",
        "scores": ((29, False),),
    },
    {
        "key": "direct",
        "label": "Direct play",
        "hint": "Vertical play — low reverse passing and bypassing opponents",
        "scores": ((5, True), (98, False)),
    },
    {
        "key": "transition",
        "label": "Transition",
        "hint": "Counter-press intensity and packing wins",
        "scores": ((61, False), (2, False)),
    },
)

TEAM_STYLE_ARCHETYPES: tuple[dict[str, Any], ...] = (
    {
        "key": "possession",
        "label": "Possession & control",
        "tagline": "Circulate · dominate · territory",
        "ideal": (88, 52, 74, 36, 32, 48),
        "stats": ("possession", "direct"),
    },
    {
        "key": "heavy_metal",
        "label": "Heavy metal",
        "tagline": "Intensity · gegenpress · vertical",
        "ideal": (58, 90, 68, 44, 52, 84),
        "stats": ("pressing", "transition"),
    },
    {
        "key": "underdog_press",
        "label": "Underdog pressing",
        "tagline": "Disrupt · compact · aggressive",
        "ideal": (40, 86, 54, 46, 48, 70),
        "stats": ("pressing", "transition"),
    },
    {
        "key": "direct_aerial",
        "label": "Direct & aerial",
        "tagline": "Long · second balls · wide",
        "ideal": (34, 46, 56, 84, 78, 42),
        "stats": ("direct", "aerial"),
    },
    {
        "key": "safety_first",
        "label": "Safety first",
        "tagline": "Structure · low risk · block",
        "ideal": (46, 30, 40, 50, 38, 34),
        "stats": ("pressing", "progression"),
    },
    {
        "key": "counter",
        "label": "Counter attacking",
        "tagline": "Transition · pace · vertical",
        "ideal": (38, 64, 58, 40, 62, 88),
        "stats": ("transition", "direct"),
    },
)

_squad_scores_cache: dict[int, tuple[float, dict[int, dict[int, float]]]] = {}


class PreMatchReportRequest(BaseModel):
    iteration_id: int
    squad_id: int
    match_id: int | None = None


class PreMatchPngExportPage(BaseModel):
    imageData: str = ""
    filename: str | None = None
    width: int = 0
    height: int = 0


class PreMatchPngExportRequest(BaseModel):
    pages: list[PreMatchPngExportPage] = []
    filename: str | None = None
    document_title: str | None = None
    opponent_name: str | None = None


def _impect():
    from app import main as impect_main

    return impect_main


def _unwrap_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        nested = payload.get("items") or payload.get("data")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    return []


def _unwrap_match_player_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    if isinstance(payload, dict):
        return payload
    return {}


def _aerial_win_pct(stats: dict[str, float]) -> float | None:
    won = stats.get("WON_AERIAL_DUELS")
    lost = stats.get("LOST_AERIAL_DUELS")
    if won is None or lost is None:
        return None
    total = won + lost
    if total <= 0:
        return None
    return (won / total) * 100.0


def _kpi_names() -> dict[int, str]:
    global _kpi_name_cache
    now = time.time()
    if _kpi_name_cache and now - _kpi_name_cache[0] < CACHE_TTL_SECONDS:
        return _kpi_name_cache[1]

    impect = _impect()
    raw = impect._impect_get(f"/v5/{impect._api_prefix()}/kpis")["data"]
    catalog = _unwrap_items(raw)
    mapping = {
        int(item["id"]): str(item.get("name") or "")
        for item in catalog
        if item.get("id") is not None
    }
    _kpi_name_cache = (now, mapping)
    return mapping


def _pivot_squad_kpis(kpi_rows: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    names = _kpi_names()
    table: dict[int, dict[str, float]] = {}
    for row in kpi_rows:
        squad_id = row.get("squadId")
        if squad_id is None:
            continue
        stats = table.setdefault(int(squad_id), {"matches": float(row.get("matches") or 0)})
        for item in row.get("kpis") or []:
            kpi_id = item.get("kpiId")
            if kpi_id is None:
                continue
            name = names.get(int(kpi_id))
            if not name:
                continue
            stats[name] = stats.get(name, 0.0) + float(item.get("value") or 0.0)
    return table


def _squad_kpi_table(iteration_id: int) -> dict[int, dict[str, float]]:
    cached = _squad_kpi_cache.get(iteration_id)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    impect = _impect()
    raw = impect._impect_get(
        f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/squad-kpis"
    )["data"]
    table = _pivot_squad_kpis(_unwrap_items(raw))
    _squad_kpi_cache[iteration_id] = (now, table)
    return table


def _squad_scores_table(iteration_id: int) -> dict[int, dict[int, float]]:
    cached = _squad_scores_cache.get(iteration_id)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    impect = _impect()
    raw = impect._impect_get(
        f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/squad-scores"
    )["data"]
    rows = raw if isinstance(raw, list) else _unwrap_items(raw)
    table: dict[int, dict[int, float]] = {}
    for row in rows:
        squad_id = row.get("squadId")
        if squad_id is None:
            continue
        scores: dict[int, float] = {}
        for item in row.get("squadScores") or []:
            score_id = item.get("squadScoreId")
            if score_id is None:
                continue
            try:
                scores[int(score_id)] = float(item.get("value") or 0.0)
            except (TypeError, ValueError):
                continue
        table[int(squad_id)] = scores
    _squad_scores_cache[iteration_id] = (now, table)
    return table


def _score_percentile_lookup(
    table: dict[int, dict[int, float]],
    score_id: int,
    *,
    invert: bool = False,
) -> dict[int, float]:
    pairs: list[tuple[int, float]] = []
    for squad_id, scores in table.items():
        if score_id not in scores:
            continue
        pairs.append((squad_id, scores[score_id]))
    if not pairs:
        return {}
    pairs.sort(key=lambda item: item[1], reverse=not invert)
    total = len(pairs)
    if total == 1:
        return {pairs[0][0]: 100.0}
    return {
        squad_id: round(1000 * (total - 1 - index) / (total - 1)) / 10
        for index, (squad_id, _) in enumerate(pairs)
    }


def _axis_percentile(
    table: dict[int, dict[int, float]],
    squad_id: int,
    axis: dict[str, Any],
) -> float | None:
    parts: list[float] = []
    for score_id, invert in axis.get("scores") or ():
        lookup = _score_percentile_lookup(table, int(score_id), invert=bool(invert))
        value = lookup.get(squad_id)
        if value is not None:
            parts.append(value)
    if not parts:
        return None
    return round(sum(parts) / len(parts), 1)


def _league_axis_percentiles(
    table: dict[int, dict[int, float]],
    axis: dict[str, Any],
) -> dict[int, float]:
    values: dict[int, float] = {}
    for squad_id in table:
        pct = _axis_percentile(table, squad_id, axis)
        if pct is not None:
            values[squad_id] = pct
    return values


def _percentile_to_rank(percentile: float, league_size: int) -> int:
    if league_size <= 1:
        return 1
    from_bottom = round(float(percentile) / 100 * (league_size - 1))
    return max(1, min(league_size, league_size - from_bottom))


def _build_team_style_summary(radar_axes: list[dict[str, Any]], league_size: int) -> list[str]:
    lines: list[str] = []
    by_key = {row["key"]: row for row in radar_axes}

    possession = by_key.get("possession")
    if possession and float(possession.get("value") or 0) >= 85:
        lines.append(
            f"Keeps the ball better than almost everyone in the league "
            f"({possession.get('rank_label')} for possession) — expect patience and circulation."
        )
    elif possession and float(possession.get("value") or 0) <= 25:
        lines.append(
            f"Rarely dominates possession ({possession.get('rank_label')}) — happier without the ball."
        )

    progression = by_key.get("progression")
    if progression and float(progression.get("value") or 0) <= 35:
        lines.append(
            f"Does not progress the ball much ({progression.get('rank_label')}) — "
            "compact shape and patience can force sideways play."
        )
    elif progression and float(progression.get("value") or 0) >= 70:
        lines.append(
            f"Breaks lines regularly ({progression.get('rank_label')}) — avoid leaving space in behind."
        )

    pressing = by_key.get("pressing")
    if pressing and float(pressing.get("value") or 0) >= 70:
        lines.append(
            f"High press profile ({pressing.get('rank_label')}) — build-up needs composure and exit routes."
        )

    if not lines:
        lines.append(
            "Balanced tactical profile across the league — no single extreme to exploit on this chart."
        )
    return lines[:3]


def _style_fit_score(team_values: list[float], ideal: tuple[float, ...]) -> float:
    if not team_values or len(team_values) != len(ideal):
        return 0.0
    distance = sum(abs(team - target) for team, target in zip(team_values, ideal)) / len(
        ideal
    )
    return round(max(0.0, 100.0 - distance * 1.15), 1)


def _style_highlights(
    radar_by_key: dict[str, dict[str, Any]],
    stat_keys: tuple[str, ...],
) -> list[dict[str, str]]:
    highlights: list[dict[str, str]] = []
    for key in stat_keys[:2]:
        axis = radar_by_key.get(key)
        if not axis:
            continue
        highlights.append(
            {
                "label": str(axis.get("label") or key),
                "rank_label": str(axis.get("rank_label") or "—"),
            }
        )
    return highlights


def _build_team_style(iteration_id: int, squad_id: int) -> dict[str, Any]:
    table = _squad_scores_table(iteration_id)
    if squad_id not in table:
        return {"available": False}

    league_size = len(table)
    radar_axes: list[dict[str, Any]] = []
    team_vector: list[float] = []
    for axis in TEAM_STYLE_RADAR_AXES:
        team_pct = _axis_percentile(table, squad_id, axis)
        league_axis = _league_axis_percentiles(table, axis)
        league_mid = (
            round(sum(league_axis.values()) / len(league_axis), 1) if league_axis else 50.0
        )
        if team_pct is not None:
            rank = _percentile_to_rank(team_pct, league_size)
            team_vector.append(team_pct)
            radar_axes.append(
                {
                    "key": axis["key"],
                    "label": axis["label"],
                    "hint": axis.get("hint"),
                    "value": team_pct,
                    "league_avg": league_mid,
                    "rank": rank,
                    "rank_label": _ordinal(rank),
                    "league_size": league_size,
                }
            )

    styles: list[dict[str, Any]] = []
    radar_by_key = {row["key"]: row for row in radar_axes}
    for archetype in TEAM_STYLE_ARCHETYPES:
        ideal = archetype["ideal"]
        if len(team_vector) != len(ideal):
            continue
        fit = _style_fit_score(team_vector, ideal)
        styles.append(
            {
                "key": archetype["key"],
                "label": archetype["label"],
                "tagline": archetype["tagline"],
                "fit_pct": fit,
                "highlights": _style_highlights(
                    radar_by_key,
                    tuple(archetype.get("stats") or ()),
                ),
            }
        )
    styles.sort(key=lambda row: (-row["fit_pct"], row["label"]))
    summary = _build_team_style_summary(radar_axes, league_size)

    return {
        "available": bool(radar_axes),
        "radar": radar_axes,
        "league_size": league_size,
        "styles": styles,
        "primary_style": styles[0] if styles else None,
        "secondary_style": styles[1] if len(styles) > 1 else None,
        "summary": summary,
        "methodology": (
            "Radar uses Impect squad-score league percentiles (100 = best in L1 on that trait). "
            "Pressing weights opening-ball pressure and PPDA over line height. "
            "Direct play measures verticality, not long-ball volume. "
            "Style labels are approximate resemblance — not Impect's official style models."
        ),
    }


def _metric_value(stats: dict[str, float], spec: dict[str, Any], matches: float) -> float | None:
    compute: Callable[[dict[str, float]], float | None] | None = spec.get("compute")
    if compute is not None:
        value = compute(stats)
    else:
        key = spec["key"]
        if key not in stats:
            return None
        value = stats[key]
    if value is None:
        return None
    if spec.get("percent"):
        return float(value)
    # Impect squad-kpis values are already per-match rates.
    return float(value)


def _ordinal(rank: int) -> str:
    if 10 <= rank % 100 <= 20:
        suffix = "TH"
    else:
        suffix = {1: "ST", 2: "ND", 3: "RD"}.get(rank % 10, "TH")
    return f"{rank}{suffix}"


def _rank_metric(
    table: dict[int, dict[str, float]],
    squad_id: int,
    spec: dict[str, Any],
    *,
    higher_better: bool,
) -> tuple[float | None, str | None]:
    values: list[tuple[int, float]] = []
    for sid, stats in table.items():
        matches = stats.get("matches") or 0.0
        if matches <= 0:
            continue
        value = _metric_value(stats, spec, matches)
        if value is None:
            continue
        values.append((sid, value))
    if not values:
        return None, None

    values.sort(key=lambda item: item[1], reverse=higher_better)
    rank_lookup = {sid: index + 1 for index, (sid, _) in enumerate(values)}
    rank = rank_lookup.get(squad_id)
    if rank is None:
        return None, None
    target = next(value for sid, value in values if sid == squad_id)
    return target, _ordinal(rank)


def _match_play_minutes(row: dict[str, Any]) -> float:
    impect = _impect()
    raw = impect._to_number(row.get("playDuration"))
    if raw is None or raw <= 0:
        return 0.0
    # Match-level playDuration is reported in seconds.
    return float(round(raw / 60.0))


TM_POSITION_TO_CODE: dict[str, str] = {
    "goalkeeper": "GOALKEEPER",
    "centre-back": "CENTRAL_DEFENDER",
    "center-back": "CENTRAL_DEFENDER",
    "left-back": "LEFT_WINGBACK_DEFENDER",
    "right-back": "RIGHT_WINGBACK_DEFENDER",
    "left midfield": "LEFT_WINGER",
    "right midfield": "RIGHT_WINGER",
    "central midfield": "CENTRAL_MIDFIELD",
    "defensive midfield": "DEFENSE_MIDFIELD",
    "attacking midfield": "ATTACKING_MIDFIELD",
    "left winger": "LEFT_WINGER",
    "right winger": "RIGHT_WINGER",
    "centre-forward": "CENTER_FORWARD",
    "center-forward": "CENTER_FORWARD",
    "second striker": "SECOND_STRIKER",
}


def _position_code_from_transfermarkt(label: str | None) -> str:
    text = re.sub(r"\s+", " ", str(label or "")).strip().casefold()
    if not text:
        return ""
    if text in TM_POSITION_TO_CODE:
        return TM_POSITION_TO_CODE[text]
    if "goalkeeper" in text:
        return "GOALKEEPER"
    if "back" in text or "defend" in text:
        return "CENTRAL_DEFENDER"
    if "midfield" in text:
        return "CENTRAL_MIDFIELD"
    if "winger" in text or "wing" in text:
        return "LEFT_WINGER"
    if "forward" in text or "striker" in text:
        return "CENTER_FORWARD"
    return ""


def _player_display_name(player: dict[str, Any]) -> str:
    return (
        str(player.get("commonname") or "").strip()
        or f"{player.get('firstname', '')} {player.get('lastname', '')}".strip()
        or f"Player {player.get('id')}"
    )


def _player_names_map(players: list[dict[str, Any]]) -> dict[int, str]:
    return {
        int(player["id"]): _player_display_name(player)
        for player in players
        if player.get("id") is not None
    }


def _player_age(player: dict[str, Any]) -> int | None:
    if player.get("age") is not None:
        try:
            return int(player["age"])
        except (TypeError, ValueError):
            pass
    birthdate = player.get("birthdate")
    if not birthdate:
        return None
    try:
        born = datetime.fromisoformat(str(birthdate).replace("Z", "+00:00"))
        today = datetime.now(tz=born.tzinfo or UTC)
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except ValueError:
        return None


def _format_foot(leg: Any) -> str:
    if not leg:
        return "—"
    return str(leg).replace("_", " ").title()


def _position_label(position: str | None) -> str:
    if not position:
        return "—"
    impect = _impect()
    return impect.POSITION_LABELS.get(position, position.replace("_", " ").title())


POSITION_BANDS: dict[str, tuple[str, ...]] = {
    "attack": ("CENTER_FORWARD", "LEFT_WINGER", "RIGHT_WINGER", "SECOND_STRIKER"),
    "mid": (
        "ATTACKING_MIDFIELD",
        "CENTRAL_MIDFIELD",
        "DEFENSE_MIDFIELD",
    ),
    "def": (
        "CENTRAL_DEFENDER",
        "LEFT_WINGBACK_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
    ),
    "gk": ("GOALKEEPER",),
}

POSITION_COLUMN: dict[str, str] = {
    "LEFT_WINGER": "left",
    "LEFT_WINGBACK_DEFENDER": "left",
    "RIGHT_WINGER": "right",
    "RIGHT_WINGBACK_DEFENDER": "right",
}


def _position_band(position: str | None) -> str:
    code = str(position or "").upper()
    for band, codes in POSITION_BANDS.items():
        if code in codes:
            return band
    if "FORWARD" in code or "STRIKER" in code:
        return "attack"
    if "MID" in code:
        return "mid"
    if "DEF" in code or "BACK" in code:
        return "def"
    if "GOAL" in code:
        return "gk"
    return "mid"


def _position_column(position: str | None) -> str:
    code = str(position or "").upper()
    return POSITION_COLUMN.get(code, "center")


def _fetch_match_detail(match_id: int) -> dict[str, Any]:
    cached = _match_detail_cache.get(match_id)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    impect = _impect()
    raw = impect._impect_get(f"/v5/{impect._api_prefix()}/matches/{match_id}")["data"]
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        raw = raw["data"]
    if not isinstance(raw, dict):
        raw = {}
    _match_detail_cache[match_id] = (now, raw)
    return raw


def _match_squad_block(match_detail: dict[str, Any], squad_id: int) -> dict[str, Any] | None:
    for side in ("squadHome", "squadAway"):
        squad = match_detail.get(side) or {}
        if int(squad.get("id") or -1) == squad_id:
            return squad
    return None


def _coaches_map(iteration_id: int) -> dict[int, str]:
    cached = _coaches_cache.get(iteration_id)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    impect = _impect()
    raw = impect._impect_get(
        f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/coaches"
    )["data"]
    mapping = {
        int(item["id"]): str(item.get("name") or "").strip()
        for item in _unwrap_items(raw)
        if item.get("id") is not None and item.get("name")
    }
    _coaches_cache[iteration_id] = (now, mapping)
    return mapping


def _coords_from_starting_position(
    position: str | None,
    position_side: str | None,
) -> tuple[float, float]:
    band = _position_band(position)
    y = BAND_Y.get(band, 50.0)
    side_key = str(position_side or "CENTRE").upper().replace("-", "_")
    x = SIDE_X.get(side_key, 50.0)
    code = str(position or "").upper()
    if code in ("LEFT_WINGER", "LEFT_WINGBACK_DEFENDER"):
        x = min(x, 16.0)
    elif code in ("RIGHT_WINGER", "RIGHT_WINGBACK_DEFENDER"):
        x = max(x, 84.0)
    elif code == "GOALKEEPER":
        x, y = 50.0, 94.0
    return x, y


def _side_from_column(column: str) -> str:
    mapping = {"left": "LEFT", "center": "CENTRE", "right": "RIGHT"}
    return mapping.get(column, "CENTRE")


def _normalize_formation_key(formation: str | None) -> str:
    text = str(formation or "").lower()
    if "4-2-3-1" in text or "4231" in text:
        return "4-2-3-1"
    if "4-4-2" in text or "442" in text:
        return "4-4-2"
    if "4-3-3" in text or "433" in text:
        return "4-3-3"
    if "5-3-2" in text or "532" in text:
        return "5-3-2"
    if "3-5-2" in text or "352" in text or "3-4-2" in text:
        return "5-3-2"
    if "5-2-2-1" in text or "5221" in text or "5-2-1-2" in text:
        return "5-2-2-1"
    return "4-2-3-1"


def _player_side_hint(player: dict[str, Any]) -> str:
    code = str(player.get("position") or "").upper()
    column = str(player.get("column") or "center").lower()
    if "LEFT" in code:
        return "left"
    if "RIGHT" in code:
        return "right"
    return column


def _positions_compatible(player_position: str, slot_position: str) -> bool:
    player_code = str(player_position or "").upper()
    slot_code = str(slot_position or "").upper()
    if player_code == slot_code:
        return True
    return player_code in POSITION_SLOT_ALIASES.get(slot_code, {slot_code})


def _slot_match_score(
    player: dict[str, Any],
    slot_position: str,
    slot_side: str,
) -> int:
    player_code = str(player.get("position") or "").upper()
    slot_code = str(slot_position or "").upper()
    score = 0
    if player_code == slot_code:
        score += 120
    elif _positions_compatible(player_code, slot_code):
        score += 80
    elif _position_band(player_code) == _position_band(slot_code):
        score += 35
    else:
        score -= 40

    side = _player_side_hint(player)
    if slot_side == "any":
        score += 15
    elif side == slot_side:
        score += 25
    elif slot_side == "center" and side == "center":
        score += 20

    score += min(int(player.get("starts") or 0), 8)
    return score


def _assign_outfield_slots(
    players: list[dict[str, Any]],
    slots: list[tuple[str, float, float, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pool = sorted(
        players,
        key=lambda item: (
            -int(item.get("starts") or 0),
            -int(item.get("minutes") or 0),
            str(item.get("name") or "").casefold(),
        ),
    )
    assigned: list[dict[str, Any]] = []
    used_ids: set[int] = set()

    for slot_position, x_pct, y_pct, slot_side in slots:
        best_player: dict[str, Any] | None = None
        best_score = -10_000
        for player in pool:
            player_id = int(player["player_id"])
            if player_id in used_ids:
                continue
            score = _slot_match_score(player, slot_position, slot_side)
            if score > best_score:
                best_score = score
                best_player = player
        if best_player is None:
            for player in pool:
                player_id = int(player["player_id"])
                if player_id in used_ids:
                    continue
                best_player = player
                break
        if best_player is None:
            continue
        used_ids.add(int(best_player["player_id"]))
        assigned.append(
            {
                **best_player,
                "x_pct": x_pct,
                "y_pct": y_pct,
                "formation_slot": slot_position,
                "position_locked": True,
            }
        )

    remaining = [player for player in pool if int(player["player_id"]) not in used_ids]
    return assigned, remaining


def _sort_assigned_players(assigned: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        assigned,
        key=lambda item: (
            float(item.get("y_pct") or 50),
            float(item.get("x_pct") or 50),
            str(item.get("name") or "").casefold(),
        ),
    )


def _assign_pivot_midfield_slots(
    players: list[dict[str, Any]],
    formation_key: str,
) -> list[dict[str, Any]]:
    """Single pivot DM with two advanced CMs — mirrors 4-3-3 / 5-3-2 reference layouts."""
    if not players:
        return []

    slots = FORMATION_TEMPLATES.get(formation_key, FORMATION_TEMPLATES["4-3-3"])
    outfield_slots = [
        slot
        for slot in slots
        if slot[0] not in {"DEFENSE_MIDFIELD", "CENTRAL_MIDFIELD"}
    ]
    assigned, mid_pool = _assign_outfield_slots(players, outfield_slots)
    mid_pool.sort(
        key=lambda player: (
            _midfield_depth_rank(str(player.get("position") or "")),
            _horizontal_rank(player),
            str(player.get("name") or "").casefold(),
        )
    )
    if len(mid_pool) < 3:
        return _assign_formation_slots(players, formation_key)

    pivot = mid_pool[0]
    cms = sorted(mid_pool[1:3], key=_horizontal_rank)
    pivot_coords = next(
        (slot for slot in slots if slot[0] == "DEFENSE_MIDFIELD"),
        ("DEFENSE_MIDFIELD", 50.0, 54.0, "center"),
    )
    cm_coords = [slot for slot in slots if slot[0] == "CENTRAL_MIDFIELD"][:2]
    if len(cm_coords) < 2:
        cm_coords = [
            ("CENTRAL_MIDFIELD", 36.0, 46.0, "left"),
            ("CENTRAL_MIDFIELD", 64.0, 46.0, "right"),
        ]

    assigned.append(
        {
            **pivot,
            "x_pct": pivot_coords[1],
            "y_pct": pivot_coords[2],
            "formation_slot": "DEFENSE_MIDFIELD",
            "position_locked": True,
        }
    )
    for player, (slot_position, x_pct, y_pct, _slot_side) in zip(cms, cm_coords, strict=False):
        assigned.append(
            {
                **player,
                "x_pct": x_pct,
                "y_pct": y_pct,
                "formation_slot": slot_position,
                "position_locked": True,
            }
        )

    return _sort_assigned_players(assigned)


def assign_lineup_formation_slots(
    players: list[dict[str, Any]],
    formation: str | None,
) -> list[dict[str, Any]]:
    formation_key = _normalize_formation_key(formation)
    if formation_key == "5-2-2-1":
        return _assign_five_two_two_one_slots(players)
    if formation_key in {"4-3-3", "5-3-2"}:
        return _assign_pivot_midfield_slots(players, formation_key)
    return _assign_formation_slots(players, formation)


def _assign_formation_slots(
    players: list[dict[str, Any]],
    formation: str | None,
) -> list[dict[str, Any]]:
    if not players:
        return []

    template_key = _normalize_formation_key(formation)
    slots = FORMATION_TEMPLATES.get(template_key, FORMATION_TEMPLATES["4-2-3-1"])
    ordered_slots = sorted(
        slots,
        key=lambda slot: (
            SLOT_ASSIGNMENT_PRIORITY.get(slot[0], 99),
            slot[1],
        ),
    )
    pool = sorted(
        players,
        key=lambda item: (
            -int(item.get("starts") or 0),
            -int(item.get("minutes") or 0),
            str(item.get("name") or "").casefold(),
        ),
    )
    assigned: list[dict[str, Any]] = []
    used_ids: set[int] = set()

    for slot_position, x_pct, y_pct, slot_side in ordered_slots:
        best_player: dict[str, Any] | None = None
        best_score = -10_000
        for player in pool:
            player_id = int(player["player_id"])
            if player_id in used_ids:
                continue
            score = _slot_match_score(player, slot_position, slot_side)
            if score > best_score:
                best_score = score
                best_player = player
        # Always fill every formation slot so the pitch never shows fewer than 11.
        if best_player is None:
            best_player = next(
                (player for player in pool if int(player["player_id"]) not in used_ids),
                None,
            )
        if best_player is None:
            continue
        used_ids.add(int(best_player["player_id"]))
        assigned.append(
            {
                **best_player,
                "x_pct": x_pct,
                "y_pct": y_pct,
                "formation_slot": slot_position,
                "position_locked": True,
            }
        )

    leftovers = [player for player in pool if int(player["player_id"]) not in used_ids]
    for player in leftovers:
        if len(assigned) >= PITCH_STARTER_LIMIT:
            break
        position = str(player.get("position") or "")
        band = str(player.get("band") or "mid")
        y_pct = _display_y_for_position(position, band)
        same_line = [
            item
            for item in assigned
            if abs(float(item.get("y_pct") or 50) - y_pct) < 3.0
        ]
        taken_x = [float(item.get("x_pct") or 50) for item in same_line]
        x_pct = float(player.get("x_pct") or 50)
        while any(abs(x_pct - value) < 12.0 for value in taken_x):
            x_pct += 12.0
        x_pct = max(12.0, min(88.0, x_pct))
        taken_x.append(x_pct)
        assigned.append(
            {
                **player,
                "x_pct": round(x_pct, 1),
                "y_pct": y_pct,
                "formation_slot": position,
            }
        )

    if len(assigned) < 8:
        return _layout_pitch_players(players)[:PITCH_STARTER_LIMIT]

    return sorted(
        assigned[:PITCH_STARTER_LIMIT],
        key=lambda item: (
            float(item.get("y_pct") or 50),
            float(item.get("x_pct") or 50),
            str(item.get("name") or "").casefold(),
        ),
    )


def _midfield_depth_rank(position: str | None) -> int:
    code = str(position or "").upper()
    if code in {"DEFENSE_MIDFIELD"} or "DEFENSE_MID" in code:
        return 0
    if code in {"CENTRAL_MIDFIELD"}:
        return 1
    if code in {"ATTACKING_MIDFIELD", "LEFT_MIDFIELD", "RIGHT_MIDFIELD", "LEFT_WINGER", "RIGHT_WINGER"}:
        return 2
    if "MID" in code:
        return 1
    return 1


def _horizontal_rank(player: dict[str, Any]) -> float:
    code = str(player.get("position") or "").upper()
    hint = _player_side_hint(player)
    if hint == "left" or "LEFT" in code:
        return 0.0
    if hint == "right" or "RIGHT" in code:
        return 2.0
    return 1.0


def _is_defensive_outfield_code(position: str) -> bool:
    code = str(position or "").upper()
    return any(
        token in code
        for token in (
            "DEFENDER",
            "WINGBACK",
            "BACK",
            "GOALKEEPER",
        )
    )


def _pick_best_for_slot(
    pool: list[dict[str, Any]],
    used_ids: set[int],
    slot_position: str,
    slot_side: str,
    *,
    min_score: int = 0,
) -> dict[str, Any] | None:
    best_player: dict[str, Any] | None = None
    best_score = -10_000
    for player in pool:
        player_id = int(player["player_id"])
        if player_id in used_ids:
            continue
        score = _slot_match_score(player, slot_position, slot_side)
        if score > best_score:
            best_score = score
            best_player = player
    if best_player is None or best_score < min_score:
        for player in pool:
            player_id = int(player["player_id"])
            if player_id in used_ids:
                continue
            return player
    return best_player


def _assign_five_two_two_one_slots(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """5-2-2-1: back three plus high wing-backs, then a midfield box and lone striker."""
    if not players:
        return []

    slots = FORMATION_TEMPLATES["5-2-2-1"]
    pool = sorted(
        players,
        key=lambda item: (
            -int(item.get("starts") or 0),
            -int(item.get("minutes") or 0),
            str(item.get("name") or "").casefold(),
        ),
    )
    assigned: list[dict[str, Any]] = []
    used_ids: set[int] = set()

    def place_slot(
        slot: tuple[str, float, float, str],
        player: dict[str, Any] | None,
    ) -> None:
        if player is None:
            return
        slot_position, x_pct, y_pct, _slot_side = slot
        used_ids.add(int(player["player_id"]))
        assigned.append(
            {
                **player,
                "x_pct": x_pct,
                "y_pct": y_pct,
                "formation_slot": slot_position,
                "position_locked": True,
            }
        )

    gk_slot = next(slot for slot in slots if slot[0] == "GOALKEEPER")
    place_slot(gk_slot, _pick_best_for_slot(pool, used_ids, "GOALKEEPER", "any", min_score=20))

    defenders = [
        player
        for player in pool
        if int(player["player_id"]) not in used_ids and _is_defensive_outfield_code(str(player.get("position") or ""))
    ]
    lwb_slot = next(slot for slot in slots if slot[0] == "LEFT_WINGBACK_DEFENDER")
    rwb_slot = next(slot for slot in slots if slot[0] == "RIGHT_WINGBACK_DEFENDER")
    place_slot(
        lwb_slot,
        _pick_best_for_slot(defenders or pool, used_ids, "LEFT_WINGBACK_DEFENDER", "left"),
    )
    place_slot(
        rwb_slot,
        _pick_best_for_slot(
            [player for player in defenders if int(player["player_id"]) not in used_ids] or pool,
            used_ids,
            "RIGHT_WINGBACK_DEFENDER",
            "right",
        ),
    )

    cb_slots = [slot for slot in slots if slot[0] == "CENTRAL_DEFENDER"]
    cb_candidates = sorted(
        [player for player in defenders if int(player["player_id"]) not in used_ids],
        key=lambda player: (
            -_slot_match_score(player, "CENTRAL_DEFENDER", _player_side_hint(player)),
            str(player.get("name") or "").casefold(),
        ),
    )
    for slot in cb_slots:
        slot_position, _x, _y, slot_side = slot
        pick = next(
            (
                player
                for player in cb_candidates
                if int(player["player_id"]) not in used_ids
                and _slot_match_score(player, slot_position, slot_side) >= 20
            ),
            None,
        )
        if pick is None:
            pick = next((player for player in cb_candidates if int(player["player_id"]) not in used_ids), None)
        place_slot(slot, pick)

    cf_slot = next(slot for slot in slots if slot[0] == "CENTER_FORWARD")
    outfield_pool = [player for player in pool if int(player["player_id"]) not in used_ids]
    place_slot(
        cf_slot,
        _pick_best_for_slot(outfield_pool, used_ids, "CENTER_FORWARD", "center", min_score=20),
    )

    mid_pool = [player for player in pool if int(player["player_id"]) not in used_ids]
    mid_pool.sort(
        key=lambda player: (
            _midfield_depth_rank(str(player.get("position") or "")),
            _horizontal_rank(player),
            str(player.get("name") or "").casefold(),
        )
    )
    if len(mid_pool) < 4:
        box_slots = [slot for slot in slots if slot[0] in {"DEFENSE_MIDFIELD", "CENTRAL_MIDFIELD"}]
        for player, slot in zip(mid_pool, box_slots, strict=False):
            place_slot(slot, player)
        leftovers = [player for player in pool if int(player["player_id"]) not in used_ids]
        for player in leftovers:
            band = str(player.get("band") or "mid")
            y_pct = _display_y_for_position(str(player.get("position") or ""), band)
            assigned.append(
                {
                    **player,
                    "x_pct": 50.0,
                    "y_pct": y_pct,
                    "formation_slot": str(player.get("position") or ""),
                }
            )
        return _sort_assigned_players(assigned)

    dm_pair = sorted(mid_pool[:2], key=_horizontal_rank)
    cm_pair = sorted(mid_pool[2:4], key=_horizontal_rank)
    dm_slots = [slot for slot in slots if slot[0] == "DEFENSE_MIDFIELD"]
    cm_slots = [slot for slot in slots if slot[0] == "CENTRAL_MIDFIELD"]
    for slot, player in zip(dm_slots, dm_pair, strict=False):
        place_slot(slot, player)
    for slot, player in zip(cm_slots, cm_pair, strict=False):
        place_slot(slot, player)

    for player in pool:
        if int(player["player_id"]) in used_ids:
            continue
        assigned.append(
            {
                **player,
                "x_pct": 50.0,
                "y_pct": 50.0,
                "formation_slot": str(player.get("position") or ""),
            }
        )

    return _sort_assigned_players(assigned)


def _display_y_for_position(position: str | None, band: str) -> float:
    code = str(position or "").upper()
    return POSITION_Y.get(code, BAND_Y.get(band, 50.0))


def _select_typical_starters(
    coord_samples: dict[int, dict[str, Any]],
    minutes_by_id: dict[int, int],
    *,
    limit: int = PITCH_STARTER_LIMIT,
) -> list[int]:
    if not coord_samples:
        return []
    if len(coord_samples) <= limit:
        return list(coord_samples.keys())

    gk_ids = [
        player_id
        for player_id, bucket in coord_samples.items()
        if bucket["positions"].get("GOALKEEPER", 0) > 0
    ]
    best_gk = (
        max(
            gk_ids,
            key=lambda player_id: (
                len(coord_samples[player_id]["xs"]),
                minutes_by_id.get(player_id, 0),
            ),
        )
        if gk_ids
        else None
    )

    outfield = [player_id for player_id in coord_samples if player_id != best_gk]
    outfield_ranked = sorted(
        outfield,
        key=lambda player_id: (
            -len(coord_samples[player_id]["xs"]),
            -minutes_by_id.get(player_id, 0),
            str(coord_samples[player_id]["name"]).casefold(),
        ),
    )
    outfield_slots = limit - (1 if best_gk is not None else 0)
    selected = outfield_ranked[:outfield_slots]
    if best_gk is not None:
        selected.append(best_gk)
    return selected


def _beautify_pitch_layout(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nudge the XI for clearer headshot spacing (lower GK, wider lines)."""
    if not players:
        return players

    for player in players:
        slot = str(player.get("formation_slot") or player.get("position") or "").upper()
        band = str(player.get("band") or _position_band(slot))
        if band == "gk" or slot == "GOALKEEPER":
            player["x_pct"] = 50.0
            player["y_pct"] = 94.0
            player["band"] = "gk"
        else:
            y_val = float(player.get("y_pct") or 50.0)
            # Keep attackers high and defenders clear of the keeper.
            if band == "attack":
                player["y_pct"] = round(max(9.0, min(28.0, y_val)), 1)
            elif band == "mid":
                player["y_pct"] = round(max(34.0, min(58.0, y_val)), 1)
            elif band == "def":
                player["y_pct"] = round(max(62.0, min(80.0, y_val)), 1)

    by_line: dict[int, list[dict[str, Any]]] = {}
    for player in players:
        if str(player.get("band") or "") == "gk":
            continue
        line_key = int(round(float(player.get("y_pct") or 50) / 2.0) * 2)
        by_line.setdefault(line_key, []).append(player)

    for line_players in by_line.values():
        line_players.sort(key=lambda item: float(item.get("x_pct") or 50))
        _spread_players_horizontally(line_players, min_gap=16.0, margin=7.0)

    return _sort_assigned_players(players)


def _spread_players_horizontally(
    players: list[dict[str, Any]],
    *,
    min_gap: float = 16.0,
    margin: float = 7.0,
) -> None:
    count = len(players)
    if count <= 1:
        if players:
            players[0]["x_pct"] = round(
                max(margin, min(100.0 - margin, float(players[0].get("x_pct") or 50))),
                1,
            )
        return

    min_x = margin
    max_x = 100.0 - margin
    xs = [float(player.get("x_pct") or 50) for player in players]
    needed = min_gap * (count - 1)
    available = max_x - min_x

    if max(xs) - min(xs) >= needed:
        adjusted = [max(min_x, min(max_x, xs[0]))]
        for index in range(1, count):
            adjusted.append(max(min_x, min(max_x, max(xs[index], adjusted[-1] + min_gap))))
        if adjusted[-1] > max_x:
            span = adjusted[-1] - adjusted[0]
            if span > 0:
                scale = available / span
                base = adjusted[0]
                adjusted = [min_x + (value - base) * scale for value in adjusted]
            else:
                adjusted = [min_x + available * index / max(count - 1, 1) for index in range(count)]
    else:
        adjusted = [min_x + available * index / max(count - 1, 1) for index in range(count)]

    for player, x_value in zip(players, adjusted):
        player["x_pct"] = round(max(min_x, min(max_x, x_value)), 1)


def _layout_pitch_players(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from collections import defaultdict

    for player in players:
        position = str(player.get("position") or "")
        band = str(player.get("band") or "mid")
        player["y_pct"] = _display_y_for_position(position, band)

    by_line: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        line_key = int(round(float(player.get("y_pct") or 50)))
        by_line[line_key].append(player)

    for line_players in by_line.values():
        line_players.sort(
            key=lambda item: (
                float(item.get("x_pct") or 50),
                str(item.get("name") or "").casefold(),
            )
        )
        _spread_players_horizontally(line_players)

    return sorted(
        players,
        key=lambda item: (
            float(item.get("y_pct") or 50),
            float(item.get("x_pct") or 50),
            str(item.get("name") or "").casefold(),
        ),
    )


def _spread_overlapping_players(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _layout_pitch_players(players)


def _parse_match_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _match_sort_key(match: dict[str, Any]) -> tuple[datetime, int, int]:
    dt = _parse_match_datetime(match.get("scheduledDate")) or datetime.min.replace(tzinfo=UTC)
    return (dt, _match_day_index(match), int(match.get("id") or 0))


def _recent_completed_matches(
    iteration_id: int,
    squad_id: int,
    *,
    limit: int | None = AVERAGE_SHAPE_MATCH_LIMIT,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
) -> list[dict[str, Any]]:
    """Most recent completed matches for a squad, newest first.

    When ``before`` is set (fixture kickoff), only matches strictly earlier than
    that timestamp are included — so backdata reports use form/lineups as of
    the day Port Vale faced them, not today's season end.
    """
    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    before_dt = _parse_match_datetime(before) if not isinstance(before, datetime) else before
    if before_dt is not None and before_dt.tzinfo is None:
        before_dt = before_dt.replace(tzinfo=UTC)
    exclude_id = int(exclude_match_id) if exclude_match_id is not None else None

    relevant: list[dict[str, Any]] = []
    for match in matches:
        match_id = match.get("id")
        if match_id is None:
            continue
        match_id = int(match_id)
        if exclude_id is not None and match_id == exclude_id:
            continue
        if (
            int(match.get("homeSquadId") or -1) != squad_id
            and int(match.get("awaySquadId") or -1) != squad_id
        ):
            continue
        if not _match_is_complete(match):
            continue
        if before_dt is not None:
            match_dt = _parse_match_datetime(match.get("scheduledDate"))
            if match_dt is None or match_dt >= before_dt:
                continue
        relevant.append(match)

    relevant.sort(key=_match_sort_key, reverse=True)
    if limit is None:
        return relevant
    return relevant[:limit]


def _opponent_squad_block(match_detail: dict[str, Any], squad_id: int) -> dict[str, Any] | None:
    for side in ("squadHome", "squadAway"):
        squad = match_detail.get(side) or {}
        if squad.get("id") is None:
            continue
        if int(squad.get("id")) != squad_id:
            return squad
    return None


def _clean_formation_label(formation: str | None) -> str | None:
    text = str(formation or "").strip()
    if not text or text.upper() == "UNKNOWN":
        return None
    return text


def _unique_formations_in_match(squad: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    starting = _clean_formation_label(squad.get("startingFormation"))
    if starting:
        seen.add(starting)
        ordered.append(starting)
    timeline = [
        row for row in (squad.get("formations") or []) if isinstance(row, dict)
    ]
    timeline.sort(key=lambda row: _parse_game_clock(row)[1])
    for row in timeline:
        formation = _clean_formation_label(row.get("formation"))
        if formation and formation not in seen:
            seen.add(formation)
            ordered.append(formation)
    return ordered


def _formation_time_segments(
    squad: dict[str, Any],
    *,
    match_duration_sec: int = 95 * 60,
) -> dict[str, int]:
    starting = _clean_formation_label(squad.get("startingFormation"))
    timeline = [
        row for row in (squad.get("formations") or []) if isinstance(row, dict)
    ]
    timeline.sort(key=lambda row: _parse_game_clock(row)[1])

    changes: list[tuple[int, str]] = []
    if starting:
        changes.append((0, starting))
    for row in timeline:
        sec = _parse_game_clock(row)[1]
        formation = _clean_formation_label(row.get("formation"))
        if not formation:
            continue
        if changes and changes[-1][0] == sec:
            changes[-1] = (sec, formation)
        else:
            changes.append((sec, formation))

    if not changes:
        return {starting: match_duration_sec} if starting else {}

    collapsed: list[tuple[int, str]] = []
    for sec, formation in changes:
        if collapsed and collapsed[-1][1] == formation:
            continue
        collapsed.append((sec, formation))

    totals: dict[str, int] = {}
    for idx, (start_sec, formation) in enumerate(collapsed):
        end_sec = collapsed[idx + 1][0] if idx + 1 < len(collapsed) else match_duration_sec
        duration = max(0, end_sec - start_sec)
        if duration:
            totals[formation] = totals.get(formation, 0) + duration
    return totals


def _primary_formation_token(label: str | None) -> str | None:
    cleaned = _clean_formation_label(label)
    if not cleaned:
        return None
    return cleaned.split("/")[0].strip() or None


def _formations_match(left: str | None, right: str | None) -> bool:
    left_token = _primary_formation_token(left)
    right_token = _primary_formation_token(right)
    return bool(left_token and right_token and left_token == right_token)


def _h2h_opponent_formations_vs_vale(
    iteration_id: int,
    opponent_id: int,
    vale_id: int,
    *,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    before_dt = _parse_match_datetime(before) if not isinstance(before, datetime) else before
    if before_dt is not None and before_dt.tzinfo is None:
        before_dt = before_dt.replace(tzinfo=UTC)
    exclude_id = int(exclude_match_id) if exclude_match_id is not None else None

    rows: list[dict[str, Any]] = []
    for match in matches:
        match_id = match.get("id")
        if match_id is None:
            continue
        match_id = int(match_id)
        if exclude_id is not None and match_id == exclude_id:
            continue
        home_id = int(match.get("homeSquadId") or -1)
        away_id = int(match.get("awaySquadId") or -1)
        if {home_id, away_id} != {opponent_id, vale_id}:
            continue
        if not _match_is_complete(match):
            continue
        if before_dt is not None:
            match_dt = _parse_match_datetime(match.get("scheduledDate"))
            if match_dt is None or match_dt >= before_dt:
                continue
        detail = _fetch_match_detail(match_id)
        squad = _match_squad_block(detail, opponent_id)
        if not squad:
            continue
        result, score, venue = _match_result_score_venue(match, opponent_id)
        shapes = _unique_formations_in_match(squad)
        rows.append(
            {
                "date": match.get("scheduledDate") or detail.get("dateTime"),
                "starting_formation": _clean_formation_label(squad.get("startingFormation"))
                or (shapes[0] if shapes else None),
                "formations_used": shapes,
                "phased": len(shapes) > 1,
                "result": result,
                "score": score,
                "venue": venue,
            }
        )

    rows.sort(
        key=lambda row: _parse_match_datetime(row.get("date"))
        or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return rows[:limit]


def _formation_insight(
    *,
    tone: str,
    title: str,
    body: str,
    detail: str | None = None,
    metric_label: str | None = None,
    metric_value: str | None = None,
) -> dict[str, Any]:
    parts = [title, body]
    if detail:
        parts.append(detail)
    if metric_label and metric_value:
        parts.append(f"{metric_value} {metric_label}")
    return {
        "tone": tone,
        "title": title,
        "body": body,
        "detail": detail,
        "metric_label": metric_label,
        "metric_value": metric_value,
        "text": " · ".join(part for part in parts if part),
    }


def _build_formation_insights(
    *,
    results_by_shape: list[dict[str, Any]],
    vs_opponent: list[dict[str, Any]],
    usage: list[dict[str, Any]],
    phased_pct: float,
    phased_matches: int,
    matches_analysed: int,
    in_game_shifts: list[dict[str, Any]],
    h2h_vale: list[dict[str, Any]],
    vale_formation: str | None,
) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []

    ranked = sorted(
        [row for row in results_by_shape if int(row.get("played") or 0) >= 2],
        key=lambda row: (-float(row.get("win_pct") or 0), -int(row.get("played") or 0)),
    )
    if ranked:
        best = ranked[0]
        if float(best.get("win_pct") or 0) >= 50:
            insights.append(
                _formation_insight(
                    tone="positive",
                    title="Best starting shape",
                    body=str(best["formation"]),
                    detail=f"{best['won']}W-{best['drawn']}D-{best['lost']}L",
                    metric_label="PPG",
                    metric_value=str(best.get("ppg", "—")),
                )
            )
        weak = sorted(
            ranked,
            key=lambda row: (float(row.get("win_pct") or 0), -int(row.get("played") or 0)),
        )
        if weak and float(weak[0].get("win_pct") or 0) <= 33:
            row = weak[0]
            insights.append(
                _formation_insight(
                    tone="attack",
                    title="Target when they start",
                    body=str(row["formation"]),
                    detail=f"{row['won']}W-{row['drawn']}D-{row['lost']}L",
                    metric_label="Starts",
                    metric_value=str(row["played"]),
                )
            )

    if usage:
        primary_form = usage[0]["formation"]
        primary_row = next(
            (row for row in results_by_shape if row.get("formation") == primary_form),
            None,
        )
        if (
            primary_row
            and int(primary_row.get("played") or 0) >= 3
            and float(primary_row.get("win_pct") or 100) < 45
        ):
            insights.append(
                _formation_insight(
                    tone="attack",
                    title="Default shape struggling",
                    body=str(primary_form),
                    detail=f"{primary_row['won']}W-{primary_row['drawn']}D-{primary_row['lost']}L",
                    metric_label="Win",
                    metric_value=f"{primary_row.get('win_pct', '—')}%",
                )
            )

    if vale_formation:
        vale_rows = [
            row
            for row in vs_opponent
            if _formations_match(row.get("opponent_formation"), vale_formation)
        ]
        if vale_rows:
            row = vale_rows[0]
            insights.append(
                _formation_insight(
                    tone="intel",
                    title=f"Vs {vale_formation} sides",
                    body=f"{row['won']}W-{row['drawn']}D-{row['lost']}L",
                    metric_label="Win",
                    metric_value=f"{row.get('win_pct', '—')}%",
                )
            )

    if phased_pct >= 45 and in_game_shifts:
        shift = in_game_shifts[0]
        insights.append(
            _formation_insight(
                tone="neutral",
                title="In-game phasing",
                body=f"{phased_matches}/{matches_analysed} games",
                detail=f"Often {shift['from']} → {shift['to']} ({shift['count']}×)",
            )
        )

    if h2h_vale:
        last = h2h_vale[0]
        shape = last.get("starting_formation") or "—"
        phased_note = (
            f", switched to {' / '.join(last.get('formations_used', [])[1:3])}"
            if last.get("phased")
            else ""
        )
        insights.append(
            _formation_insight(
                tone="vale",
                title="Last vs Vale",
                body=f"Started {shape}{phased_note}",
                detail=f"{last.get('score', '—')} {last.get('venue', '')}".strip(),
                metric_label="Result",
                metric_value=str(last.get("result") or "—"),
            )
        )
    elif len(usage) >= 2 and not insights:
        insights.append(
            _formation_insight(
                tone="intel",
                title="Shape split",
                body=f"{usage[0]['formation']} ({usage[0]['time_pct']}%)",
                detail=f"Main alternate {usage[1]['formation']}",
            )
        )

    return insights[:4]


def _build_formation_analysis(
    iteration_id: int,
    squad_id: int,
    *,
    limit: int | None = None,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
    vale_squad_id: int | None = None,
    vale_formation: str | None = None,
) -> dict[str, Any]:
    formation_seconds: dict[str, int] = {}
    starting_counts: dict[str, int] = {}
    shape_results: dict[str, dict[str, int | float]] = {}
    vs_buckets: dict[str, dict[str, int]] = {}
    shift_counts: dict[tuple[str, str], int] = {}
    matches_analysed = 0
    phased_matches = 0

    for match in _recent_completed_matches(
        iteration_id,
        squad_id,
        limit=limit,
        before=before,
        exclude_match_id=exclude_match_id,
    ):
        detail = _fetch_match_detail(int(match["id"]))
        squad = _match_squad_block(detail, squad_id)
        opponent = _opponent_squad_block(detail, squad_id)
        if not squad:
            continue

        matches_analysed += 1
        unique = _unique_formations_in_match(squad)
        if len(unique) > 1:
            phased_matches += 1
            shift_counts[(unique[0], unique[-1])] = (
                shift_counts.get((unique[0], unique[-1]), 0) + 1
            )

        for form, secs in _formation_time_segments(squad).items():
            formation_seconds[form] = formation_seconds.get(form, 0) + secs

        starting = _clean_formation_label(squad.get("startingFormation"))
        if not starting and unique:
            starting = unique[0]
        if starting:
            starting_counts[starting] = starting_counts.get(starting, 0) + 1
            result, score, _ = _match_result_score_venue(match, squad_id)
            try:
                gf, ga = (int(part) for part in str(score).split("-", 1))
            except (TypeError, ValueError):
                gf, ga = 0, 0
            bucket = shape_results.setdefault(
                starting,
                {
                    "played": 0,
                    "won": 0,
                    "drawn": 0,
                    "lost": 0,
                    "goals_for": 0,
                    "goals_against": 0,
                },
            )
            bucket["played"] = int(bucket["played"]) + 1
            bucket["goals_for"] = float(bucket["goals_for"]) + gf
            bucket["goals_against"] = float(bucket["goals_against"]) + ga
            if result == "W":
                bucket["won"] = int(bucket["won"]) + 1
            elif result == "D":
                bucket["drawn"] = int(bucket["drawn"]) + 1
            else:
                bucket["lost"] = int(bucket["lost"]) + 1

        opp_form = _clean_formation_label(opponent.get("startingFormation")) if opponent else None
        if not opp_form and opponent:
            opp_unique = _unique_formations_in_match(opponent)
            opp_form = opp_unique[0] if opp_unique else None
        if opp_form:
            result, _, _ = _match_result_score_venue(match, squad_id)
            bucket = vs_buckets.setdefault(
                opp_form,
                {"played": 0, "won": 0, "drawn": 0, "lost": 0},
            )
            bucket["played"] += 1
            if result == "W":
                bucket["won"] += 1
            elif result == "D":
                bucket["drawn"] += 1
            else:
                bucket["lost"] += 1

    total_seconds = sum(formation_seconds.values()) or 1
    usage = sorted(
        [
            {
                "formation": form,
                "minutes": round(secs / 60),
                "time_pct": round(1000 * secs / total_seconds) / 10,
                "matches_started": starting_counts.get(form, 0),
                "match_pct": round(
                    1000 * starting_counts.get(form, 0) / max(matches_analysed, 1)
                )
                / 10,
            }
            for form, secs in formation_seconds.items()
        ],
        key=lambda row: (-row["time_pct"], row["formation"]),
    )
    results_by_shape = sorted(
        [
            {
                "formation": form,
                "played": played,
                "won": won,
                "drawn": drawn,
                "lost": lost,
                "goals_for": round(float(counts["goals_for"]), 1),
                "goals_against": round(float(counts["goals_against"]), 1),
                "win_pct": round(1000 * won / played) / 10 if played else None,
                "ppg": round((won * 3 + drawn) / played, 2) if played else None,
                "goals_for_pg": round(float(counts["goals_for"]) / played, 2) if played else None,
                "goals_against_pg": round(float(counts["goals_against"]) / played, 2)
                if played
                else None,
            }
            for form, counts in shape_results.items()
            for played, won, drawn, lost in [
                (
                    int(counts["played"]),
                    int(counts["won"]),
                    int(counts["drawn"]),
                    int(counts["lost"]),
                )
            ]
        ],
        key=lambda row: (-float(row.get("win_pct") or 0), -int(row.get("played") or 0)),
    )
    vs_opponent = sorted(
        [
            {
                "opponent_formation": form,
                **counts,
                "win_pct": round(1000 * counts["won"] / counts["played"]) / 10
                if counts["played"]
                else None,
                "ppg": round((counts["won"] * 3 + counts["drawn"]) / counts["played"], 2)
                if counts["played"]
                else None,
                "matches_vale_shape": _formations_match(form, vale_formation),
            }
            for form, counts in vs_buckets.items()
        ],
        key=lambda row: (
            -int(row.get("matches_vale_shape") or False),
            -row["played"],
            row["opponent_formation"],
        ),
    )
    in_game_shifts = sorted(
        [
            {"from": left, "to": right, "count": count}
            for (left, right), count in shift_counts.items()
        ],
        key=lambda row: (-row["count"], row["from"]),
    )
    h2h_vale = (
        _h2h_opponent_formations_vs_vale(
            iteration_id,
            squad_id,
            vale_squad_id,
            before=before,
            exclude_match_id=exclude_match_id,
        )
        if vale_squad_id is not None
        else []
    )
    insights = _build_formation_insights(
        results_by_shape=results_by_shape,
        vs_opponent=vs_opponent,
        usage=usage,
        phased_pct=round(1000 * phased_matches / max(matches_analysed, 1)) / 10,
        phased_matches=phased_matches,
        matches_analysed=matches_analysed,
        in_game_shifts=in_game_shifts,
        h2h_vale=h2h_vale,
        vale_formation=vale_formation,
    )

    return {
        "scope": "season",
        "match_sample": matches_analysed,
        "matches_analysed": matches_analysed,
        "phased_matches": phased_matches,
        "phased_pct": round(1000 * phased_matches / max(matches_analysed, 1)) / 10,
        "usage": usage,
        "results_by_shape": results_by_shape,
        "vs_opponent": vs_opponent,
        "in_game_shifts": in_game_shifts,
        "h2h_vale": h2h_vale,
        "vale_formation": vale_formation,
        "insights": insights,
    }


def _formation_usage_from_matches(
    iteration_id: int,
    squad_id: int,
    *,
    limit: int = AVERAGE_SHAPE_MATCH_LIMIT,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
) -> str | None:
    formation_counts: dict[str, int] = {}
    for match in _recent_completed_matches(
        iteration_id,
        squad_id,
        limit=limit,
        before=before,
        exclude_match_id=exclude_match_id,
    ):
        detail = _fetch_match_detail(int(match["id"]))
        squad = _match_squad_block(detail, squad_id)
        if not squad:
            continue
        formation = str(squad.get("startingFormation") or "").strip()
        if formation:
            formation_counts[formation] = formation_counts.get(formation, 0) + 1
    if not formation_counts:
        return None
    ranked = sorted(formation_counts.items(), key=lambda item: (-item[1], item[0]))
    return " / ".join(label for label, _count in ranked[:2])


def _manager_as_of(
    iteration_id: int,
    squad_id: int,
    *,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
) -> str | None:
    """Manager for the opponent as of a fixture — from their latest prior match."""
    coaches = _coaches_map(iteration_id)
    for match in _recent_completed_matches(
        iteration_id,
        squad_id,
        limit=AVERAGE_SHAPE_MATCH_LIMIT,
        before=before,
        exclude_match_id=exclude_match_id,
    ):
        detail = _fetch_match_detail(int(match["id"]))
        squad = _match_squad_block(detail, squad_id)
        if not squad:
            continue
        coach_id = squad.get("coachId")
        if coach_id is None:
            continue
        name = coaches.get(int(coach_id))
        if name:
            return name
    return None


def _aggregate_average_pitch_players(
    iteration_id: int,
    squad_id: int,
    player_names: dict[int, str],
    squad_rows: list[dict[str, Any]],
    match_stats: dict[int, dict[str, Any]],
    *,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
) -> tuple[list[dict[str, Any]], str | None, int | None, str | None]:
    recent_matches = _recent_completed_matches(
        iteration_id,
        squad_id,
        before=before,
        exclude_match_id=exclude_match_id,
    )
    coord_samples: dict[int, dict[str, Any]] = {}
    reference_match_id: int | None = None
    reference_date: str | None = None

    for match in recent_matches:
        match_id = int(match["id"])
        detail = _fetch_match_detail(match_id)
        squad = _match_squad_block(detail, squad_id)
        if not squad:
            continue
        if reference_match_id is None:
            reference_match_id = match_id
            reference_date = match.get("scheduledDate") or detail.get("dateTime")

        for row in squad.get("startingPositions") or []:
            if not isinstance(row, dict):
                continue
            player_id = int(row.get("playerId") or 0)
            if not player_id:
                continue
            position = str(row.get("position") or "")
            x, y = _coords_from_starting_position(position, row.get("positionSide"))
            bucket = coord_samples.setdefault(
                player_id,
                {
                    "xs": [],
                    "ys": [],
                    "positions": {},
                    "name": player_names.get(player_id, f"Player {player_id}"),
                },
            )
            bucket["xs"].append(x)
            bucket["ys"].append(y)
            bucket["positions"][position] = bucket["positions"].get(position, 0) + 1

    minutes_by_id = {int(row["id"]): int(row.get("minutes") or 0) for row in squad_rows}
    current_ids = {
        int(row["id"])
        for row in squad_rows
        if row.get("id") is not None and row.get("current", True)
    }
    # Prefer players still at the club so leavers don't dominate the typical XI.
    if current_ids:
        coord_samples = {
            player_id: bucket
            for player_id, bucket in coord_samples.items()
            if player_id in current_ids
        }
        minutes_by_id = {
            player_id: minutes
            for player_id, minutes in minutes_by_id.items()
            if player_id in current_ids
        }
    starter_ids = _select_typical_starters(coord_samples, minutes_by_id)

    pitch_players: list[dict[str, Any]] = []
    for player_id in starter_ids:
        bucket = coord_samples.get(player_id)
        if not bucket or not bucket["xs"]:
            continue
        primary_position = max(bucket["positions"], key=bucket["positions"].get)
        band = _position_band(primary_position)
        pitch_players.append(
            {
                "player_id": player_id,
                "name": bucket["name"],
                "position": primary_position,
                "band": band,
                "column": _position_column(primary_position),
                "x_pct": round(sum(bucket["xs"]) / len(bucket["xs"]), 1),
                "y_pct": _display_y_for_position(primary_position, band),
                "minutes": minutes_by_id.get(player_id, 0),
                "starts": len(bucket["xs"]),
            }
        )

    pitch_players = _backfill_pitch_players(pitch_players, squad_rows)
    pitch_players = pitch_players[:PITCH_STARTER_LIMIT]
    for player in pitch_players:
        player["short_name"] = _player_surname(str(player.get("name") or ""))
    pitch_players.sort(
        key=lambda item: (
            float(item.get("y_pct") or 50),
            float(item.get("x_pct") or 50),
            str(item.get("name") or "").casefold(),
        )
    )
    manager = _manager_as_of(
        iteration_id,
        squad_id,
        before=before,
        exclude_match_id=exclude_match_id,
    )
    return pitch_players, manager, reference_match_id, reference_date


def _backfill_pitch_players(
    pitch_players: list[dict[str, Any]],
    squad_rows: list[dict[str, Any]],
    *,
    limit: int = PITCH_STARTER_LIMIT,
) -> list[dict[str, Any]]:
    """Fill leftover formation slots from the current squad when recent XI data is thin."""
    if len(pitch_players) >= limit:
        return pitch_players[:limit]

    used_ids = {
        int(player["player_id"])
        for player in pitch_players
        if player.get("player_id") is not None
    }
    candidates = sorted(
        [
            row
            for row in squad_rows
            if row.get("id") is not None and int(row["id"]) not in used_ids
        ],
        key=lambda row: (
            -int(row.get("starts") or 0),
            -int(row.get("minutes") or 0),
            str(row.get("name") or "").casefold(),
        ),
    )
    for row in candidates:
        if len(pitch_players) >= limit:
            break
        player_id = int(row["id"])
        position = str(row.get("position_code") or "")
        band = str(row.get("band") or _position_band(position) or "mid")
        pitch_players.append(
            {
                "player_id": player_id,
                "name": str(row.get("name") or f"Player {player_id}"),
                "position": position or "CENTRAL_MIDFIELD",
                "band": band,
                "column": _position_column(position),
                "x_pct": float(SIDE_X.get("CENTRE", 50.0)),
                "y_pct": _display_y_for_position(position, band),
                "minutes": int(row.get("minutes") or 0),
                "starts": int(row.get("starts") or 0),
                "backfill": True,
            }
        )
        used_ids.add(player_id)
    return pitch_players


def _team_payload(squad: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(squad.get("id") or 0),
        "name": str(squad.get("name") or ""),
        "image_url": _squad_crest_url(squad.get("name"), squad.get("imageUrl")),
    }


def _format_kickoff(scheduled: str | None) -> tuple[str | None, str | None]:
    if not scheduled:
        return None, None
    try:
        normalized = str(scheduled).replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        return (
            dt.strftime("%A %d %B %Y"),
            dt.strftime("%H:%M"),
        )
    except (TypeError, ValueError):
        return str(scheduled)[:10], None


def _build_fixture_context(
    iteration_id: int,
    opponent_squad_id: int,
    match_id: int | None,
    iteration: dict[str, Any],
) -> dict[str, Any]:
    squads = _squads_map(iteration_id)
    port_vale_id = _resolve_port_vale_squad_id(iteration_id)
    opponent_squad = squads.get(opponent_squad_id, {})
    port_vale_squad = (
        squads.get(port_vale_id, {"name": "Port Vale"})
        if port_vale_id is not None
        else {"id": 0, "name": "Port Vale", "imageUrl": None}
    )

    scheduled: str | None = None
    is_home = True
    match_day: int | None = None

    if match_id:
        impect = _impect()
        matches = _unwrap_items(
            impect._impect_get(
                f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
            )["data"]
        )
        match_row = next(
            (row for row in matches if int(row.get("id") or -1) == int(match_id)),
            None,
        )
        if match_row:
            home_id = int(match_row.get("homeSquadId") or -1)
            scheduled = match_row.get("scheduledDate")
            match_day = _match_day_label(match_row)
            if port_vale_id is not None:
                is_home = port_vale_id == home_id
            else:
                away_id = int(match_row.get("awaySquadId") or -1)
                is_home = opponent_squad_id == away_id

        detail = _fetch_match_detail(int(match_id))
        if detail.get("dateTime"):
            scheduled = str(detail.get("dateTime"))

    date_label, time_label = _format_kickoff(scheduled)
    port_vale = _enrich_team_crest(_team_payload(port_vale_squad), iteration_id)
    opponent = _enrich_team_crest(_team_payload(opponent_squad), iteration_id)
    pv_name = port_vale["name"] or "Port Vale"
    opp_name = opponent["name"] or "Opponent"
    fixture_line = f"{pv_name} vs {opp_name}" if is_home else f"{opp_name} vs {pv_name}"

    competition = str(iteration.get("competition_name") or DEFAULT_COMPETITION)
    season = str(iteration.get("season") or "")
    competition_line = f"{competition} {season}".strip()
    if match_day:
        competition_line = f"{competition_line} · MD{match_day}".strip(" ·")

    return {
        "port_vale": port_vale,
        "opponent": opponent,
        "is_home": is_home,
        "scheduled_date": scheduled,
        "date_label": date_label,
        "time_label": time_label,
        "venue": "Home" if is_home else "Away",
        "fixture_line": fixture_line,
        "competition_line": competition_line,
        "match_day": match_day,
    }


def _squads_map(iteration_id: int) -> dict[int, dict[str, Any]]:
    impect = _impect()
    squads = _unwrap_items(impect._impect_get(impect._squads_path(iteration_id))["data"])
    return {
        int(item["id"]): item
        for item in squads
        if item.get("id") is not None
    }


def _resolve_port_vale_squad_id(iteration_id: int) -> int | None:
    for squad_id, squad in _squads_map(iteration_id).items():
        if _is_port_vale(str(squad.get("name") or "")):
            return squad_id
    return None


def _match_is_complete(match: dict[str, Any]) -> bool:
    goals = match.get("goals") or {}
    home_ft = (goals.get("home") or {}).get("fullTime")
    away_ft = (goals.get("away") or {}).get("fullTime")
    return home_ft is not None and away_ft is not None


def _last_completed_match(
    iteration_id: int,
    squad_id: int,
) -> dict[str, Any] | None:
    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    relevant = [
        match
        for match in matches
        if match.get("id") is not None
        and (
            int(match.get("homeSquadId") or -1) == squad_id
            or int(match.get("awaySquadId") or -1) == squad_id
        )
        and _match_is_complete(match)
    ]
    relevant.sort(key=_match_day_index, reverse=True)
    return relevant[0] if relevant else None


def _formation_label_from_match(match: dict[str, Any], squad_id: int) -> str | None:
    home_id = int(match.get("homeSquadId") or -1)
    if home_id == squad_id:
        formations = match.get("squadHomeFormations") or []
    else:
        formations = match.get("squadAwayFormations") or []
    if not formations:
        return None
    latest = formations[-1] if isinstance(formations, list) else formations
    if isinstance(latest, dict):
        return str(latest.get("formation") or latest.get("name") or "") or None
    return str(latest) if latest else None


def _players_on_pitch_from_match(
    match_id: int,
    squad_id: int,
    iteration_id: int,
    player_names: dict[int, str],
) -> list[dict[str, Any]]:
    impect = _impect()
    payload = _unwrap_match_player_payload(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/matches/{match_id}/player-kpis"
        )["data"]
    )
    players: list[dict[str, Any]] = []
    for side in ("squadHome", "squadAway"):
        squad = payload.get(side) or {}
        if int(squad.get("id") or -1) != squad_id:
            continue
        for row in squad.get("players") or []:
            if not isinstance(row, dict):
                continue
            player_id = int(row.get("id") or 0)
            if not player_id:
                continue
            position = str(row.get("position") or "")
            match_share = float(row.get("matchShare") or 0.0)
            players.append(
                {
                    "player_id": player_id,
                    "name": player_names.get(player_id, f"Player {player_id}"),
                    "shirt_number": row.get("shirtNumber"),
                    "position": position,
                    "band": _position_band(position),
                    "column": _position_column(position),
                    "minutes": _match_play_minutes(row),
                    "starter": match_share >= 0.85,
                }
            )
    players.sort(
        key=lambda item: (
            {"gk": 0, "def": 1, "mid": 2, "attack": 3}.get(item["band"], 9),
            {"left": 0, "center": 1, "right": 2}.get(item["column"], 1),
            -(item.get("minutes") or 0),
            item["name"],
        )
    )
    return players


def _player_surname(name: str) -> str:
    parts = str(name or "").strip().split()
    return parts[-1] if parts else str(name or "")


SQUAD_BAND_ORDER: tuple[str, ...] = ("gk", "def", "mid", "attack")
SQUAD_BAND_LABELS: dict[str, str] = {
    "gk": "Goalkeepers",
    "def": "Defenders",
    "mid": "Midfielders",
    "attack": "Forwards",
}


def _attach_shirt_numbers(
    pitch_players: list[dict[str, Any]],
    squad_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    shirts = {
        int(row["id"]): row.get("shirt_number")
        for row in squad_rows
        if row.get("id") is not None and row.get("shirt_number") is not None
    }
    for player in pitch_players:
        player_id = player.get("player_id")
        if player_id is None:
            continue
        shirt = shirts.get(int(player_id))
        if shirt is not None:
            player["shirt_number"] = shirt
    return pitch_players


def _build_squad_groups(
    squad_rows: list[dict[str, Any]],
    pitch_players: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pitch_ids = {int(player["player_id"]) for player in pitch_players}
    pitch_bands = {int(player["player_id"]): player["band"] for player in pitch_players}
    grouped: dict[str, list[dict[str, Any]]] = {band: [] for band in SQUAD_BAND_ORDER}

    for row in squad_rows:
        player_id = int(row["id"])
        band = pitch_bands.get(player_id) or str(row.get("band") or "mid")
        if band not in grouped:
            band = "mid"
        grouped[band].append(
            {
                "id": player_id,
                "name": row["name"],
                "shirt_number": row.get("shirt_number"),
                "on_pitch": player_id in pitch_ids,
                "minutes": int(row.get("minutes") or 0),
                "position": row.get("position") or "—",
            }
        )

    groups: list[dict[str, Any]] = []
    for band in SQUAD_BAND_ORDER:
        players = grouped[band]
        if not players:
            continue
        players.sort(
            key=lambda item: (
                not item["on_pitch"],
                -item["minutes"],
                str(item["name"]).casefold(),
            )
        )
        groups.append(
            {
                "label": SQUAD_BAND_LABELS[band],
                "band": band,
                "players": players,
            }
        )
    return groups


def _match_result_score_venue(
    match: dict[str, Any],
    squad_id: int,
) -> tuple[str, str, str]:
    home_id = int(match.get("homeSquadId") or -1)
    away_id = int(match.get("awaySquadId") or -1)
    goals = match.get("goals") or {}
    home_goals = int((goals.get("home") or {}).get("fullTime") or 0)
    away_goals = int((goals.get("away") or {}).get("fullTime") or 0)
    is_home = home_id == squad_id
    goals_for = home_goals if is_home else away_goals
    goals_against = away_goals if is_home else home_goals
    if goals_for > goals_against:
        result = "W"
    elif goals_for < goals_against:
        result = "L"
    else:
        result = "D"
    return result, f"{goals_for}-{goals_against}", "H" if is_home else "A"


def _lineup_players_from_match_detail(
    detail: dict[str, Any],
    squad_id: int,
    player_names: dict[int, str],
) -> list[dict[str, Any]]:
    squad = _match_squad_block(detail, squad_id)
    if not squad:
        return []
    shirts: dict[int, int] = {}
    for row in squad.get("players") or []:
        if not isinstance(row, dict):
            continue
        player_id = int(row.get("id") or 0)
        shirt = row.get("shirtNumber")
        if not player_id or shirt is None:
            continue
        try:
            shirts[player_id] = int(shirt)
        except (TypeError, ValueError):
            continue
    players: list[dict[str, Any]] = []
    for row in squad.get("startingPositions") or []:
        if not isinstance(row, dict):
            continue
        player_id = int(row.get("playerId") or 0)
        if not player_id:
            continue
        position = str(row.get("position") or "")
        x_pct, y_pct = _coords_from_starting_position(position, row.get("positionSide"))
        name = player_names.get(player_id, f"Player {player_id}")
        players.append(
            {
                "player_id": player_id,
                "name": name,
                "short_name": _player_surname(name),
                "shirt_number": shirts.get(player_id),
                "position": position,
                "band": _position_band(position),
                "column": _position_column(position),
                "x_pct": x_pct,
                "y_pct": y_pct,
                "starts": 1,
                "minutes": 0,
            }
        )
    return players


def _build_previous_xi_slides(
    iteration_id: int,
    squad_id: int,
    *,
    player_names: dict[int, str],
    club_name: str,
    season: str | None,
    limit: int = PREVIOUS_XI_LIMIT,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
) -> list[dict[str, Any]]:
    """Last N completed starting XIs before the fixture (oldest → newest)."""
    squads = _squads_map(iteration_id)
    slides: list[dict[str, Any]] = []
    # Newest first from the helper; reverse at the end so the UI reads
    # oldest on the left → most recent on the right.
    for match in _recent_completed_matches(
        iteration_id,
        squad_id,
        limit=limit,
        before=before,
        exclude_match_id=exclude_match_id,
    ):
        match_id = int(match["id"])
        detail = _fetch_match_detail(match_id)
        squad = _match_squad_block(detail, squad_id)
        if not squad:
            continue
        players = _lineup_players_from_match_detail(detail, squad_id, player_names)
        if not players:
            continue
        home_id = int(match.get("homeSquadId") or -1)
        away_id = int(match.get("awaySquadId") or -1)
        is_home = home_id == squad_id
        opponent_id = away_id if is_home else home_id
        opponent_name = str(squads.get(opponent_id, {}).get("name") or "Opponent")
        result, score, venue = _match_result_score_venue(match, squad_id)
        formation = str(squad.get("startingFormation") or "").strip() or None
        players = assign_lineup_formation_slots(players, formation)
        players = _beautify_pitch_layout(players)
        slides.append(
            {
                "match_id": match_id,
                "date": match.get("scheduledDate") or detail.get("dateTime"),
                "opponent": opponent_name,
                "venue": venue,
                "result": result,
                "score": score,
                "formation": formation,
                "pitch_players": players[:PITCH_STARTER_LIMIT],
            }
        )
    slides.reverse()
    return slides


def _parse_game_clock(raw: Any) -> tuple[int, int, str]:
    """Return (minute, sort_seconds, label like 54')."""
    text = ""
    fallback_sec = 0.0
    if isinstance(raw, dict):
        text = str(raw.get("gameTime") or "")
        try:
            fallback_sec = float(raw.get("gameTimeInSec") or 0.0)
        except (TypeError, ValueError):
            fallback_sec = 0.0
    else:
        text = str(raw or "")
    match = re.search(r"(\d+)\s*:\s*(\d+)", text)
    if match:
        minute = int(match.group(1))
        second = int(match.group(2))
        return minute, minute * 60 + second, f"{minute}'"
    minute = int(fallback_sec // 60) if fallback_sec else 0
    return minute, int(fallback_sec), f"{minute}'"


def _shirt_map_from_squad_block(squad: dict[str, Any]) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for row in squad.get("players") or []:
        if not isinstance(row, dict):
            continue
        player_id = int(row.get("id") or 0)
        shirt = row.get("shirtNumber")
        if not player_id or shirt is None:
            continue
        try:
            mapping[player_id] = int(shirt)
        except (TypeError, ValueError):
            continue
    return mapping


def _on_pitch_entry(
    *,
    player_id: int,
    name: str,
    position: str,
    position_side: str | None,
    shirt_number: int | None,
) -> dict[str, Any]:
    x_pct, y_pct = _coords_from_starting_position(position, position_side)
    return {
        "player_id": player_id,
        "name": name,
        "short_name": _player_surname(name),
        "shirt_number": shirt_number,
        "position": position,
        "position_side": position_side,
        "band": _position_band(position),
        "column": _position_column(position),
        "x_pct": x_pct,
        "y_pct": y_pct,
        "starts": 1,
        "minutes": 0,
    }


def _formation_at_time(
    formations: list[dict[str, Any]],
    sort_seconds: int,
    *,
    fallback: str | None,
) -> str | None:
    current = fallback
    for row in formations:
        if not isinstance(row, dict):
            continue
        _minute, row_sort, _label = _parse_game_clock(row)
        if row_sort > sort_seconds:
            break
        formation = str(row.get("formation") or "").strip()
        if formation and formation.upper() != "UNKNOWN":
            current = formation
    return current


def _place_red_card_ghosts(
    live_players: list[dict[str, Any]],
    ghosts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep sent-off markers clear of whoever fills their slot (labels need room)."""
    if not ghosts:
        return live_players

    placed: list[dict[str, Any]] = []
    occupied = [
        (float(player.get("x_pct") or 50), float(player.get("y_pct") or 50))
        for player in live_players
    ]
    # Name pills on the mini pitches are wide — need more than circle clearance.
    min_dx = 20.0
    min_dy = 16.0
    # Prefer vacant pockets near the old slot (higher / wider / deeper) before far corners.
    offsets = (
        (0.0, -16.0),
        (18.0, -12.0),
        (-18.0, -12.0),
        (22.0, 0.0),
        (-22.0, 0.0),
        (16.0, 14.0),
        (-16.0, 14.0),
        (0.0, 18.0),
        (28.0, -8.0),
        (-28.0, -8.0),
        (0.0, -26.0),
        (34.0, 12.0),
        (-34.0, 12.0),
        (12.0, -22.0),
        (-12.0, -22.0),
    )

    def clear(x: float, y: float) -> bool:
        return all(
            abs(x - ox) >= min_dx or abs(y - oy) >= min_dy for ox, oy in occupied
        )

    def score(x: float, y: float, base_x: float, base_y: float) -> float:
        # Prefer nearby clear spots so the red marker still reads as "this slot".
        nearest = min(
            ((x - ox) ** 2 + (y - oy) ** 2) ** 0.5 for ox, oy in occupied
        ) if occupied else 99.0
        home = ((x - base_x) ** 2 + (y - base_y) ** 2) ** 0.5
        return nearest * 2.0 - home * 0.35

    for ghost in ghosts:
        base_x = float(ghost.get("x_pct") or 50)
        base_y = float(ghost.get("y_pct") or 50)
        best: tuple[float, float] | None = None
        best_score = -1e9
        for dx, dy in offsets:
            candidate_x = max(10.0, min(90.0, base_x + dx))
            candidate_y = max(12.0, min(88.0, base_y + dy))
            if not clear(candidate_x, candidate_y):
                continue
            ranked = score(candidate_x, candidate_y, base_x, base_y)
            if ranked > best_score:
                best_score = ranked
                best = (candidate_x, candidate_y)
        if best is None:
            # Last resort: walk a loose ring until something clears.
            for radius in (18.0, 24.0, 30.0, 36.0):
                for angle in range(0, 360, 30):
                    rad = angle * 3.14159265 / 180.0
                    candidate_x = max(
                        10.0, min(90.0, base_x + radius * math.cos(rad))
                    )
                    candidate_y = max(
                        12.0, min(88.0, base_y + radius * math.sin(rad))
                    )
                    if clear(candidate_x, candidate_y):
                        best = (candidate_x, candidate_y)
                        break
                if best is not None:
                    break
        chosen = best or (
            max(10.0, min(90.0, base_x + 24.0)),
            max(12.0, min(88.0, base_y - 18.0)),
        )
        marker = {
            **ghost,
            "x_pct": round(chosen[0], 1),
            "y_pct": round(chosen[1], 1),
            "highlight": "red",
            "ghost": True,
        }
        placed.append(marker)
        occupied.append(chosen)

    return [*live_players, *placed]


def _snapshot_pitch_players(
    on_pitch: dict[int, dict[str, Any]],
    *,
    formation: str | None,
    ghosts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    players = [dict(player) for player in on_pitch.values()]
    if not players and not ghosts:
        return []
    # Full XI → slot to formation. Short-handed / red-card phases keep real
    # positions so midfield numbers don't collapse into a mess.
    if len(players) >= PITCH_STARTER_LIMIT:
        players = assign_lineup_formation_slots(players, formation)
        players = _beautify_pitch_layout(players)
    elif players:
        for player in players:
            x_pct, y_pct = _coords_from_starting_position(
                str(player.get("position") or ""),
                player.get("position_side"),
            )
            player["x_pct"] = x_pct
            player["y_pct"] = y_pct
            player["formation_slot"] = player.get("position")
        players = _beautify_pitch_layout(players)
    if ghosts:
        players = _place_red_card_ghosts(players, ghosts)
    limit = PITCH_STARTER_LIMIT + len(ghosts or [])
    return players[:limit]


def _build_last_game_detail(
    iteration_id: int,
    squad_id: int,
    *,
    player_names: dict[int, str],
    club_name: str,
    season: str | None,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
) -> dict[str, Any] | None:
    """Starting XI + in-game sub / shape phases for the opponent's last match."""
    matches = _recent_completed_matches(
        iteration_id,
        squad_id,
        limit=1,
        before=before,
        exclude_match_id=exclude_match_id,
    )
    if not matches:
        return None

    match = matches[0]
    match_id = int(match["id"])
    detail = _fetch_match_detail(match_id)
    squad = _match_squad_block(detail, squad_id)
    if not squad:
        return None

    starters = list(squad.get("startingPositions") or [])
    if not starters:
        return None

    shirts = _shirt_map_from_squad_block(squad)
    squads = _squads_map(iteration_id)
    home_id = int(match.get("homeSquadId") or -1)
    away_id = int(match.get("awaySquadId") or -1)
    is_home = home_id == squad_id
    opponent_id = away_id if is_home else home_id
    opponent_name = str(squads.get(opponent_id, {}).get("name") or "Opponent")
    result, score, venue = _match_result_score_venue(match, squad_id)
    starting_formation = str(squad.get("startingFormation") or "").strip() or None
    formation_timeline = [
        row for row in (squad.get("formations") or []) if isinstance(row, dict)
    ]
    formation_timeline.sort(key=lambda row: _parse_game_clock(row)[1])

    on_pitch: dict[int, dict[str, Any]] = {}
    for row in starters:
        if not isinstance(row, dict):
            continue
        player_id = int(row.get("playerId") or 0)
        if not player_id:
            continue
        name = player_names.get(player_id, f"Player {player_id}")
        on_pitch[player_id] = _on_pitch_entry(
            player_id=player_id,
            name=name,
            position=str(row.get("position") or "CENTRAL_MIDFIELD"),
            position_side=row.get("positionSide"),
            shirt_number=shirts.get(player_id),
        )

    phases: list[dict[str, Any]] = [
        {
            "kind": "start",
            "label": "Starting XI",
            "minute_labels": [],
            "on_names": [],
            "off_names": [],
            "formation": starting_formation,
            "formation_changed": False,
            "pitch_players": _snapshot_pitch_players(on_pitch, formation=starting_formation),
        }
    ]

    events: list[dict[str, Any]] = []
    for row in squad.get("substitutions") or []:
        if not isinstance(row, dict):
            continue
        event_type = str(row.get("substitutionType") or "").upper()
        if event_type not in {"SUB_ON", "POSITION_CHANGE", "RED_CARD"}:
            continue
        minute, sort_seconds, label = _parse_game_clock(row.get("gameTime"))
        events.append(
            {
                "type": event_type,
                "minute": minute,
                "sort_seconds": sort_seconds,
                "label": label,
                "player_id": int(row.get("playerId") or 0),
                "exchanged_player_id": int(row.get("exchangedPlayerId") or 0) or None,
                "to_position": str(row.get("toPosition") or ""),
                "to_side": row.get("positionSide"),
                "from_position": str(row.get("fromPosition") or ""),
                "from_side": row.get("fromPositionSide"),
            }
        )
    events.sort(key=lambda item: (item["sort_seconds"], item["type"] != "SUB_ON"))

    wave: list[dict[str, Any]] = []
    wave_start = -10_000

    def flush_wave() -> None:
        nonlocal wave, wave_start
        if not wave:
            return

        # Only this wave's changes are highlighted on the pitch.
        for entry in on_pitch.values():
            entry.pop("highlight", None)
            entry.pop("ghost", None)

        on_names: list[str] = []
        off_names: list[str] = []
        off_kinds: list[str] = []
        minute_labels: list[str] = []
        ghosts: list[dict[str, Any]] = []
        for event in wave:
            player_id = int(event["player_id"] or 0)
            if not player_id:
                continue
            name = player_names.get(player_id, f"Player {player_id}")
            surname = _player_surname(name)
            label = str(event["label"])
            if label not in minute_labels:
                minute_labels.append(label)

            if event["type"] == "SUB_ON":
                exchanged_id = event.get("exchanged_player_id")
                if exchanged_id and exchanged_id in on_pitch:
                    off_names.append(_player_surname(on_pitch[exchanged_id]["name"]))
                    off_kinds.append("sub")
                    del on_pitch[exchanged_id]
                on_pitch[player_id] = _on_pitch_entry(
                    player_id=player_id,
                    name=name,
                    position=str(event.get("to_position") or "CENTRAL_MIDFIELD"),
                    position_side=event.get("to_side"),
                    shirt_number=shirts.get(player_id),
                )
                on_pitch[player_id]["highlight"] = "sub"
                on_names.append(surname)
            elif event["type"] == "RED_CARD":
                if player_id in on_pitch:
                    victim = on_pitch[player_id]
                    off_names.append(_player_surname(victim["name"]))
                    off_kinds.append("red")
                    ghosts.append(
                        {
                            **victim,
                            "highlight": "red",
                            "ghost": True,
                        }
                    )
                    del on_pitch[player_id]
            elif event["type"] == "POSITION_CHANGE":
                if player_id not in on_pitch:
                    continue
                current = on_pitch[player_id]
                prev_highlight = current.get("highlight")
                on_pitch[player_id] = _on_pitch_entry(
                    player_id=player_id,
                    name=current["name"],
                    position=str(event.get("to_position") or current.get("position") or ""),
                    position_side=event.get("to_side") or current.get("position_side"),
                    shirt_number=current.get("shirt_number"),
                )
                # Keep sub colour if they came on in the same wave.
                on_pitch[player_id]["highlight"] = (
                    "sub" if prev_highlight == "sub" else "moved"
                )

        sort_seconds = max(int(event["sort_seconds"]) for event in wave)
        previous_formation = str(phases[-1].get("formation") or "") if phases else ""
        formation = _formation_at_time(
            formation_timeline,
            sort_seconds,
            fallback=previous_formation or starting_formation,
        )
        header_bits = []
        if minute_labels:
            header_bits.append(", ".join(minute_labels))
        if on_names:
            header_bits.append(f"On {', '.join(on_names)}")
        if off_names:
            header_bits.append(f"Off {', '.join(off_names)}")
        if formation and formation != previous_formation:
            header_bits.append(f"→ {formation}")
        phases.append(
            {
                "kind": "change",
                "label": " · ".join(header_bits) if header_bits else "In-game change",
                "minute_labels": minute_labels,
                "on_names": on_names,
                "off_names": off_names,
                "off_kinds": off_kinds,
                "formation": formation,
                "formation_changed": bool(
                    formation and previous_formation and formation != previous_formation
                ),
                "pitch_players": _snapshot_pitch_players(
                    on_pitch,
                    formation=formation,
                    ghosts=ghosts,
                ),
            }
        )
        wave = []

    for event in events:
        if not wave:
            wave = [event]
            wave_start = int(event["sort_seconds"])
            continue
        if int(event["sort_seconds"]) - wave_start <= 45:
            wave.append(event)
            continue
        flush_wave()
        wave = [event]
        wave_start = int(event["sort_seconds"])
    flush_wave()

    # Prefer kick-off + latest states so late reds / shape changes still show.
    if len(phases) > LAST_GAME_PHASE_LIMIT:
        keep_tail = LAST_GAME_PHASE_LIMIT - 1
        phases = [phases[0], *phases[-keep_tail:]]

    formations_used = []
    for phase in phases:
        formation = phase.get("formation")
        if formation and formation not in formations_used:
            formations_used.append(formation)

    return {
        "match_id": match_id,
        "date": match.get("scheduledDate") or detail.get("dateTime"),
        "opponent": opponent_name,
        "venue": venue,
        "result": result,
        "score": score,
        "starting_formation": starting_formation,
        "formations_used": formations_used,
        "formation_changed": len(formations_used) > 1,
        "phases": phases,
    }


def _build_squad_list_slide(
    iteration_id: int,
    squad_id: int,
    squad_rows: list[dict[str, Any]],
    match_stats: dict[int, dict[str, Any]],
    *,
    player_names: dict[int, str],
    league_position: int | None,
    club_name: str,
    season: str | None,
    key_stats: dict[str, list[dict[str, Any]]] | list[dict[str, Any]] | None = None,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
    vale_squad_id: int | None = None,
    vale_formation: str | None = None,
) -> dict[str, Any]:
    # Side roster uses the curated squad payload (Impect current + TM first-team).
    roster_source = squad_rows
    roster_names = {int(row["id"]): str(row["name"]) for row in roster_source if row.get("id")}
    names = {**player_names, **roster_names}
    pitch_players, manager, reference_match_id, reference_date = _aggregate_average_pitch_players(
        iteration_id,
        squad_id,
        names,
        roster_source,
        match_stats,
        before=before,
        exclude_match_id=exclude_match_id,
    )
    formation = _formation_usage_from_matches(
        iteration_id,
        squad_id,
        before=before,
        exclude_match_id=exclude_match_id,
    )
    formation_analysis = _build_formation_analysis(
        iteration_id,
        squad_id,
        before=before,
        exclude_match_id=exclude_match_id,
        vale_squad_id=vale_squad_id,
        vale_formation=vale_formation,
    )
    pitch_players = assign_lineup_formation_slots(pitch_players, formation)
    pitch_players = _beautify_pitch_layout(pitch_players)
    pitch_players = _backfill_pitch_players(pitch_players, roster_source)
    pitch_players = pitch_players[:PITCH_STARTER_LIMIT]
    pitch_players = _attach_shirt_numbers(pitch_players, roster_source)
    pitch_players = attach_pitch_player_photos(
        pitch_players,
        club_name=club_name,
        season=season,
    )
    pitch_names = {player["name"] for player in pitch_players}
    squad_groups = _build_squad_groups(roster_source, pitch_players)

    return {
        "reference_match_id": reference_match_id,
        "reference_date": reference_date,
        "formation": formation,
        "formation_analysis": formation_analysis,
        "league_position": league_position,
        "manager": manager,
        "pitch_players": pitch_players,
        "pitch_names": sorted(pitch_names),
        "squad_names": [row["name"] for row in roster_source],
        "squad_groups": squad_groups,
        "key_stats": key_stats or {"in_possession": [], "out_of_possession": []},
    }


def _kickoff_label(scheduled_date: str | None, is_home: bool) -> str:
    if not scheduled_date:
        return "vs"
    try:
        day = str(scheduled_date)[5:10].replace("-", "/")
    except (TypeError, IndexError):
        day = ""
    prefix = "H" if is_home else "A"
    return f"{prefix} {day}".strip() if day else prefix


def build_pre_match_fixtures(iteration_id: int) -> list[dict[str, Any]]:
    port_vale_id = _resolve_port_vale_squad_id(iteration_id)
    squads = _squads_map(iteration_id)

    if port_vale_id is None:
        return _all_opponent_squads(squads, exclude_id=None)

    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )

    fixtures: list[dict[str, Any]] = []
    for match in matches:
        match_id = match.get("id")
        if match_id is None:
            continue
        home_id = int(match.get("homeSquadId") or -1)
        away_id = int(match.get("awaySquadId") or -1)
        if port_vale_id not in (home_id, away_id):
            continue
        if _match_is_complete(match):
            continue
        is_home = port_vale_id == home_id
        opponent_id = away_id if is_home else home_id
        opponent = squads.get(opponent_id, {})
        fixtures.append(
            {
                "match_id": int(match_id),
                "match_day": _match_day_index(match),
                "scheduled_date": match.get("scheduledDate"),
                "kickoff_label": _kickoff_label(match.get("scheduledDate"), is_home),
                "is_home": is_home,
                "opponent": {
                    "id": opponent_id,
                    "name": str(opponent.get("name") or f"Squad {opponent_id}"),
                    "image_url": _squad_crest_url(
                        opponent.get("name"), opponent.get("imageUrl")
                    ),
                },
            }
        )

    fixtures.sort(
        key=lambda row: (
            int(row.get("match_day") or 0),
            str(row.get("scheduled_date") or ""),
        )
    )
    if fixtures:
        return fixtures

    return _completed_opponent_fixtures(iteration_id, port_vale_id, squads, matches)


def _all_opponent_squads(
    squads: dict[int, dict[str, Any]],
    *,
    exclude_id: int | None,
    require_access: bool = False,
) -> list[dict[str, Any]]:
    return [
        {
            "match_id": 0,
            "scheduled_date": None,
            "kickoff_label": "—",
            "is_home": False,
            "opponent": {
                "id": squad_id,
                "name": str(squad.get("name") or f"Squad {squad_id}"),
                "image_url": _squad_crest_url(squad.get("name"), squad.get("imageUrl")),
            },
        }
        for squad_id, squad in sorted(
            squads.items(),
            key=lambda item: str(item[1].get("name") or "").casefold(),
        )
        if squad_id != exclude_id and (not require_access or squad.get("access", True))
    ]


def _completed_opponent_fixtures(
    iteration_id: int,
    port_vale_id: int,
    squads: dict[int, dict[str, Any]],
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """List every Port Vale match in the season, in game order (matchday)."""
    fixtures: list[dict[str, Any]] = []
    for match in matches:
        match_id = match.get("id")
        if match_id is None or not _match_is_complete(match):
            continue
        home_id = int(match.get("homeSquadId") or -1)
        away_id = int(match.get("awaySquadId") or -1)
        if port_vale_id not in (home_id, away_id):
            continue
        is_home = port_vale_id == home_id
        opponent_id = away_id if is_home else home_id
        opponent = squads.get(opponent_id, {})
        match_day = _match_day_index(match)
        goals = match.get("goals") or {}
        home_goals = (goals.get("home") or {}).get("fullTime")
        away_goals = (goals.get("away") or {}).get("fullTime")
        score = (
            f"{home_goals}-{away_goals}"
            if home_goals is not None and away_goals is not None
            else ""
        )
        fixtures.append(
            {
                "match_id": int(match_id),
                "match_day": match_day,
                "scheduled_date": match.get("scheduledDate"),
                "kickoff_label": score or _kickoff_label(match.get("scheduledDate"), is_home),
                "is_home": is_home,
                "opponent": {
                    "id": opponent_id,
                    "name": str(opponent.get("name") or f"Squad {opponent_id}"),
                    "image_url": _squad_crest_url(
                        opponent.get("name"), opponent.get("imageUrl")
                    ),
                },
            }
        )

    fixtures.sort(
        key=lambda row: (
            int(row.get("match_day") or 0),
            str(row.get("scheduled_date") or ""),
        )
    )
    if fixtures:
        return fixtures

    # Last resort: every accessible squad in the iteration except Port Vale.
    return _all_opponent_squads(squads, exclude_id=port_vale_id)


def _is_port_vale(name: str) -> bool:
    lowered = str(name or "").casefold().replace(".", "")
    return any(token in lowered for token in PORT_VALE_TOKENS)


def _player_match_stats(
    iteration_id: int,
    squad_id: int,
    *,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
) -> dict[int, dict[str, Any]]:
    before_token = ""
    if isinstance(before, datetime):
        before_token = before.isoformat()
    elif before:
        before_token = str(before)
    exclude_token = int(exclude_match_id) if exclude_match_id is not None else 0
    cache_key = (iteration_id, squad_id, before_token, exclude_token)
    cached = _player_match_stats_cache.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    impect = _impect()
    names = _kpi_names()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    before_dt = _parse_match_datetime(before) if not isinstance(before, datetime) else before
    if before_dt is not None and before_dt.tzinfo is None:
        before_dt = before_dt.replace(tzinfo=UTC)
    exclude_id = int(exclude_match_id) if exclude_match_id is not None else None

    squad_matches: list[dict[str, Any]] = []
    for match in matches:
        match_id = match.get("id")
        if match_id is None:
            continue
        match_id = int(match_id)
        if exclude_id is not None and match_id == exclude_id:
            continue
        if (
            int(match.get("homeSquadId") or -1) != squad_id
            and int(match.get("awaySquadId") or -1) != squad_id
        ):
            continue
        if before_dt is not None:
            match_dt = _parse_match_datetime(match.get("scheduledDate"))
            if match_dt is None or match_dt >= before_dt:
                continue
        squad_matches.append(match)

    totals: dict[int, dict[str, Any]] = {}
    shirts: dict[int, int] = {}
    first_seen: dict[int, datetime] = {}
    for match in squad_matches:
        match_id = int(match["id"])
        match_dt = _parse_match_datetime(match.get("scheduledDate"))
        detail = _fetch_match_detail(match_id)
        squad_block = _match_squad_block(detail, squad_id) or {}
        for row in squad_block.get("players") or []:
            if not isinstance(row, dict):
                continue
            player_id = int(row.get("id") or 0)
            if not player_id:
                continue
            if match_dt is not None:
                previous = first_seen.get(player_id)
                if previous is None or match_dt < previous:
                    first_seen[player_id] = match_dt
            shirt = row.get("shirtNumber")
            if shirt is not None:
                try:
                    shirts[player_id] = int(shirt)
                except (TypeError, ValueError):
                    pass

        payload = _unwrap_match_player_payload(
            impect._impect_get(
                f"/v5/{impect._api_prefix()}/matches/{match_id}/player-kpis"
            )["data"]
        )
        for side in ("squadHome", "squadAway"):
            squad = payload.get(side) or {}
            if int(squad.get("id") or -1) != squad_id:
                continue
            per_match_best: dict[int, dict[str, Any]] = {}
            for row in squad.get("players") or []:
                player_id = row.get("id")
                if player_id is None:
                    continue
                player_id = int(player_id)
                minutes = _match_play_minutes(row)
                match_share = float(row.get("matchShare") or 0.0)
                existing = per_match_best.get(player_id)
                if existing is None or minutes > existing["minutes"]:
                    per_match_best[player_id] = {
                        "minutes": minutes,
                        "match_share": match_share,
                        "position": row.get("position"),
                        "kpis": row.get("kpis") or [],
                    }

            for player_id, match_row in per_match_best.items():
                bucket = totals.setdefault(
                    player_id,
                    {
                        "appearances": 0,
                        "starts": 0,
                        "minutes": 0.0,
                        "goals": 0,
                        "assists": 0,
                        "positions": set(),
                        "on_squad_list": True,
                    },
                )
                bucket["appearances"] += 1
                bucket["minutes"] += match_row["minutes"]
                if match_row["match_share"] >= 0.5:
                    bucket["starts"] += 1
                if match_row["position"]:
                    bucket["positions"].add(str(match_row["position"]))
                for kpi in match_row["kpis"]:
                    label = names.get(int(kpi.get("kpiId") or -1))
                    value = float(kpi.get("value") or 0.0)
                    if label == "GOALS":
                        bucket["goals"] += int(round(value))
                    elif label == "ASSISTS":
                        bucket["assists"] += int(round(value))

        # Matchday sitters (0 minutes) still belong on the squad list.
        for row in squad_block.get("players") or []:
            if not isinstance(row, dict):
                continue
            player_id = int(row.get("id") or 0)
            if not player_id:
                continue
            bucket = totals.setdefault(
                player_id,
                {
                    "appearances": 0,
                    "starts": 0,
                    "minutes": 0.0,
                    "goals": 0,
                    "assists": 0,
                    "positions": set(),
                    "on_squad_list": True,
                },
            )
            bucket["on_squad_list"] = True

    for player_id, shirt in shirts.items():
        bucket = totals.setdefault(
            player_id,
            {
                "appearances": 0,
                "starts": 0,
                "minutes": 0.0,
                "goals": 0,
                "assists": 0,
                "positions": set(),
                "on_squad_list": True,
            },
        )
        bucket["shirt_number"] = shirt
    for player_id, seen in first_seen.items():
        if player_id in totals:
            totals[player_id]["first_seen"] = seen.isoformat()

    _player_match_stats_cache[cache_key] = (now, totals)
    return totals


def _tm_registered_to_parent_or_youth(
    entry: dict[str, str] | None,
    *,
    parent_club_id: int | None,
    club_name: str,
) -> bool:
    """True when TM still ties the player to the parent club / its youth sides."""
    if not entry:
        return False
    registered_id = str(entry.get("registered_club_id") or "").strip()
    registered_name = str(entry.get("registered_club") or "")
    if parent_club_id and registered_id.isdigit() and int(registered_id) == int(parent_club_id):
        return True
    club_key = re.sub(r"[^a-z0-9]+", "", club_name.casefold())
    registered_key = re.sub(r"[^a-z0-9]+", "", registered_name.casefold())
    if club_key and club_key in registered_key:
        return True
    if any(token in registered_name.casefold() for token in ("u18", "u21", "u23", "youth", "reserve")):
        if club_key and club_key[:6] in registered_key:
            return True
    return False


def _match_transfermarkt_entries(
    players_by_id: dict[int, dict[str, Any]],
    player_names: dict[int, str],
    tm_roster: dict[str, dict[str, str]],
) -> dict[int, dict[str, str]]:
    matched: dict[int, dict[str, str]] = {}
    if not tm_roster:
        return matched
    for player_id, player in players_by_id.items():
        name = player_names.get(player_id) or _player_display_name(player)
        entry = player_on_transfermarkt_squad(name, tm_roster)
        if entry:
            matched[player_id] = entry
    return matched


def _build_fixture_squad_rows(
    *,
    squad_id: int,
    club_name: str,
    season: str | None,
    players_by_id: dict[int, dict[str, Any]],
    player_names: dict[int, str],
    match_stats: dict[int, dict[str, Any]],
    before: str | datetime | None = None,
) -> list[dict[str, Any]]:
    """Everyone at the club as of the fixture: matchday lists + TM first team."""
    tm_roster = transfermarkt_first_team_roster(club_name, season)
    tm_club_id = resolve_transfermarkt_club_id(club_name)
    tm_by_player_id = _match_transfermarkt_entries(players_by_id, player_names, tm_roster)

    roster_ids: set[int] = set(match_stats.keys())
    for player_id, player in players_by_id.items():
        if int(player.get("currentSquadId") or -1) == squad_id:
            roster_ids.add(player_id)

    for player_id, entry in tm_by_player_id.items():
        stats = match_stats.get(player_id) or {}
        appeared = int(stats.get("appearances") or 0) > 0 or bool(stats.get("on_squad_list"))
        if appeared:
            roster_ids.add(player_id)
            continue
        if _tm_registered_to_parent_or_youth(
            entry,
            parent_club_id=tm_club_id,
            club_name=club_name,
        ):
            roster_ids.add(player_id)
            continue
        if not transfermarkt_entry_is_loaned_out(entry, parent_club_id=tm_club_id):
            roster_ids.add(player_id)
            continue
        # Loaned-out keepers still listable for awareness (legacy behaviour).
        tm_code = _position_code_from_transfermarkt(entry.get("position"))
        if tm_code == "GOALKEEPER":
            roster_ids.add(player_id)

    squad_rows: list[dict[str, Any]] = []
    for player_id in roster_ids:
        player = players_by_id.get(player_id)
        stats = match_stats.get(player_id, {})
        positions = stats.get("positions") or set()
        primary_position = sorted(positions)[0] if positions else ""
        tm_entry = tm_by_player_id.get(player_id) or {}
        if not primary_position:
            primary_position = _position_code_from_transfermarkt(tm_entry.get("position"))
        name = player_names.get(player_id)
        if not name and player is not None:
            name = _player_display_name(player)
        if not name:
            name = f"Player {player_id}"
        shirt = stats.get("shirt_number")
        if shirt is None and str(tm_entry.get("shirt_number") or "").isdigit():
            shirt = int(tm_entry["shirt_number"])
        squad_rows.append(
            {
                "id": player_id,
                "name": name,
                "age": _player_age(player or {}),
                "foot": _format_foot(player.get("leg") if player else None),
                "position": _position_label(primary_position) if primary_position else "—",
                "position_code": primary_position,
                "band": _position_band(primary_position),
                "appearances": int(stats.get("appearances") or 0),
                "starts": int(stats.get("starts") or 0),
                "minutes": int(round(float(stats.get("minutes") or 0.0))),
                "goals": int(stats.get("goals") or 0),
                "assists": int(stats.get("assists") or 0),
                "shirt_number": shirt,
                "current": int(player.get("currentSquadId") or -1) == squad_id if player else False,
            }
        )
    squad_rows.sort(
        key=lambda row: (
            -int(row["minutes"] or 0),
            -int(row["appearances"] or 0),
            str(row["name"] or "").casefold(),
        )
    )
    return squad_rows


def _league_table(
    iteration_id: int,
    *,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
    form_limit: int = 5,
) -> list[dict[str, Any]]:
    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    squads = {
        int(item["id"]): str(item.get("name") or "")
        for item in _unwrap_items(impect._impect_get(impect._squads_path(iteration_id))["data"])
        if item.get("id") is not None
    }
    before_dt = _parse_match_datetime(before) if not isinstance(before, datetime) else before
    if before_dt is not None and before_dt.tzinfo is None:
        before_dt = before_dt.replace(tzinfo=UTC)
    exclude_id = int(exclude_match_id) if exclude_match_id is not None else None

    table: dict[int, dict[str, Any]] = {
        squad_id: {
            "squad_id": squad_id,
            "name": name,
            "played": 0,
            "won": 0,
            "drawn": 0,
            "lost": 0,
            "goals_for": 0,
            "goals_against": 0,
            "points": 0,
            "_form_events": [],
        }
        for squad_id, name in squads.items()
    }

    for match in matches:
        match_id = match.get("id")
        if match_id is None:
            continue
        match_id = int(match_id)
        if exclude_id is not None and match_id == exclude_id:
            continue
        if before_dt is not None:
            match_dt = _parse_match_datetime(match.get("scheduledDate"))
            if match_dt is None or match_dt >= before_dt:
                continue
        home_id = match.get("homeSquadId")
        away_id = match.get("awaySquadId")
        goals = match.get("goals") or {}
        home_goals = (goals.get("home") or {}).get("fullTime")
        away_goals = (goals.get("away") or {}).get("fullTime")
        if home_id is None or away_id is None:
            continue
        if home_goals is None or away_goals is None:
            continue
        home_id = int(home_id)
        away_id = int(away_id)
        home_goals = int(home_goals)
        away_goals = int(away_goals)
        sort_key = _match_sort_key(match)
        for squad_id in (home_id, away_id):
            table.setdefault(
                squad_id,
                {
                    "squad_id": squad_id,
                    "name": squads.get(squad_id, f"Squad {squad_id}"),
                    "played": 0,
                    "won": 0,
                    "drawn": 0,
                    "lost": 0,
                    "goals_for": 0,
                    "goals_against": 0,
                    "points": 0,
                    "_form_events": [],
                },
            )
        table[home_id]["played"] += 1
        table[away_id]["played"] += 1
        table[home_id]["goals_for"] += home_goals
        table[home_id]["goals_against"] += away_goals
        table[away_id]["goals_for"] += away_goals
        table[away_id]["goals_against"] += home_goals
        if home_goals > away_goals:
            table[home_id]["won"] += 1
            table[home_id]["points"] += 3
            table[away_id]["lost"] += 1
            table[home_id]["_form_events"].append((sort_key, "W"))
            table[away_id]["_form_events"].append((sort_key, "L"))
        elif away_goals > home_goals:
            table[away_id]["won"] += 1
            table[away_id]["points"] += 3
            table[home_id]["lost"] += 1
            table[away_id]["_form_events"].append((sort_key, "W"))
            table[home_id]["_form_events"].append((sort_key, "L"))
        else:
            table[home_id]["drawn"] += 1
            table[away_id]["drawn"] += 1
            table[home_id]["points"] += 1
            table[away_id]["points"] += 1
            table[home_id]["_form_events"].append((sort_key, "D"))
            table[away_id]["_form_events"].append((sort_key, "D"))

    rows = list(table.values())
    rows.sort(
        key=lambda row: (
            -int(row["points"]),
            -(int(row["goals_for"]) - int(row["goals_against"])),
            -int(row["goals_for"]),
            str(row["name"]).casefold(),
        )
    )
    for index, row in enumerate(rows, start=1):
        events = sorted(row.pop("_form_events"), key=lambda item: item[0])
        form = [result for _key, result in events[-form_limit:]]
        row["position"] = index
        row["goal_difference"] = int(row["goals_for"]) - int(row["goals_against"])
        row["form"] = form
    return rows


def _venue_split_block(events: list[dict[str, Any]]) -> dict[str, Any]:
    played = len(events)
    won = sum(1 for item in events if item["result"] == "W")
    drawn = sum(1 for item in events if item["result"] == "D")
    lost = sum(1 for item in events if item["result"] == "L")
    goals_for = sum(int(item["goals_for"]) for item in events)
    goals_against = sum(int(item["goals_against"]) for item in events)
    clean_sheets = sum(1 for item in events if int(item["goals_against"]) == 0)
    points = won * 3 + drawn
    goal_difference = goals_for - goals_against
    return {
        "played": played,
        "won": won,
        "drawn": drawn,
        "lost": lost,
        "record": f"{won}-{drawn}-{lost}",
        "goals_for": goals_for,
        "goals_against": goals_against,
        "goal_difference": goal_difference,
        "goal_difference_label": (
            f"+{goal_difference}" if goal_difference > 0 else str(goal_difference)
        ),
        "goals_for_pg": round(goals_for / played, 2) if played else None,
        "goals_against_pg": round(goals_against / played, 2) if played else None,
        "clean_sheets": clean_sheets,
        "clean_sheet_pct": round(100.0 * clean_sheets / played, 1) if played else None,
        "points": points,
        "ppg": round(points / played, 2) if played else None,
        "win_pct": round(100.0 * won / played, 1) if played else None,
        "form": [item["result"] for item in events[-5:]],
    }


def _home_away_splits(
    iteration_id: int,
    squad_id: int,
    *,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
) -> dict[str, Any]:
    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    before_dt = _parse_match_datetime(before) if not isinstance(before, datetime) else before
    if before_dt is not None and before_dt.tzinfo is None:
        before_dt = before_dt.replace(tzinfo=UTC)
    exclude_id = int(exclude_match_id) if exclude_match_id is not None else None

    home_events: list[dict[str, Any]] = []
    away_events: list[dict[str, Any]] = []
    completed: list[tuple[Any, dict[str, Any]]] = []
    for match in matches:
        match_id = match.get("id")
        if match_id is None:
            continue
        match_id = int(match_id)
        if exclude_id is not None and match_id == exclude_id:
            continue
        home_id = int(match.get("homeSquadId") or -1)
        away_id = int(match.get("awaySquadId") or -1)
        if squad_id not in (home_id, away_id):
            continue
        if before_dt is not None:
            match_dt = _parse_match_datetime(match.get("scheduledDate"))
            if match_dt is None or match_dt >= before_dt:
                continue
        goals = match.get("goals") or {}
        home_goals = (goals.get("home") or {}).get("fullTime")
        away_goals = (goals.get("away") or {}).get("fullTime")
        if home_goals is None or away_goals is None:
            continue
        home_goals = int(home_goals)
        away_goals = int(away_goals)
        is_home = home_id == squad_id
        goals_for = home_goals if is_home else away_goals
        goals_against = away_goals if is_home else home_goals
        if goals_for > goals_against:
            result = "W"
        elif goals_for < goals_against:
            result = "L"
        else:
            result = "D"
        event = {
            "result": result,
            "goals_for": goals_for,
            "goals_against": goals_against,
        }
        completed.append((_match_sort_key(match), event, is_home))

    completed.sort(key=lambda item: item[0])
    for _key, event, is_home in completed:
        (home_events if is_home else away_events).append(event)

    return {
        "home": _venue_split_block(home_events),
        "away": _venue_split_block(away_events),
    }


def _match_day_index(match: dict[str, Any]) -> int:
    match_day = match.get("matchDay")
    if isinstance(match_day, dict):
        return int(match_day.get("index") or 0)
    try:
        return int(match_day or 0)
    except (TypeError, ValueError):
        return 0


def _match_day_label(match: dict[str, Any]) -> int:
    """Human matchday number (MD1, MD2, …). Impect index is zero-based."""
    return _match_day_index(match) + 1


def _recent_form(
    iteration_id: int,
    squad_id: int,
    *,
    limit: int = 8,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
) -> list[dict[str, Any]]:
    from app.handout_badges import resolve_handout_badge_url

    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    squads = {
        int(item["id"]): {
            "name": str(item.get("name") or ""),
            "image_url": _squad_crest_url(item.get("name"), item.get("imageUrl")),
        }
        for item in _unwrap_items(impect._impect_get(impect._squads_path(iteration_id))["data"])
        if item.get("id") is not None
    }
    before_dt = _parse_match_datetime(before) if not isinstance(before, datetime) else before
    if before_dt is not None and before_dt.tzinfo is None:
        before_dt = before_dt.replace(tzinfo=UTC)
    exclude_id = int(exclude_match_id) if exclude_match_id is not None else None

    relevant: list[dict[str, Any]] = []
    for match in matches:
        match_id = match.get("id")
        if match_id is None:
            continue
        match_id = int(match_id)
        if exclude_id is not None and match_id == exclude_id:
            continue
        if (
            int(match.get("homeSquadId") or -1) != squad_id
            and int(match.get("awaySquadId") or -1) != squad_id
        ):
            continue
        if before_dt is not None:
            match_dt = _parse_match_datetime(match.get("scheduledDate"))
            if match_dt is None or match_dt >= before_dt:
                continue
        relevant.append(match)
    relevant.sort(key=_match_sort_key, reverse=True)

    form: list[dict[str, Any]] = []
    for match in relevant[:limit]:
        home_id = int(match.get("homeSquadId") or -1)
        away_id = int(match.get("awaySquadId") or -1)
        goals = match.get("goals") or {}
        home_goals = (goals.get("home") or {}).get("fullTime")
        away_goals = (goals.get("away") or {}).get("fullTime")
        if home_goals is None or away_goals is None:
            continue
        home_goals = int(home_goals)
        away_goals = int(away_goals)
        is_home = home_id == squad_id
        goals_for = home_goals if is_home else away_goals
        goals_against = away_goals if is_home else home_goals
        opponent_id = away_id if is_home else home_id
        if goals_for > goals_against:
            result = "W"
        elif goals_for < goals_against:
            result = "L"
        else:
            result = "D"
        opponent = squads.get(opponent_id) or {}
        badge_url = resolve_handout_badge_url(
            opponent_id,
            iteration_id,
            str(opponent.get("name") or ""),
        )
        form.append(
            {
                "match_id": match.get("id"),
                "date": match.get("scheduledDate"),
                "match_day": _match_day_index(match),
                "venue": "H" if is_home else "A",
                "opponent": opponent.get("name") or f"Squad {opponent_id}",
                "opponent_id": opponent_id,
                "opponent_image_url": badge_url or opponent.get("image_url"),
                "score": f"{goals_for}-{goals_against}",
                "goals_for": goals_for,
                "goals_against": goals_against,
                "result": result,
            }
        )
    return list(reversed(form))


def build_pre_match_report(body: PreMatchReportRequest) -> dict[str, Any]:
    impect = _impect()
    iteration_id = int(body.iteration_id)
    squad_id = int(body.squad_id)

    iterations = impect._fetch_iterations()
    iteration = next((item for item in iterations if int(item["id"]) == iteration_id), None)
    if iteration is None:
        raise HTTPException(status_code=404, detail="Season not found.")

    squads = _unwrap_items(impect._impect_get(impect._squads_path(iteration_id))["data"])
    squad = next((item for item in squads if int(item.get("id") or -1) == squad_id), None)
    if squad is None:
        raise HTTPException(status_code=404, detail="Opponent squad not found.")

    players = _unwrap_items(impect._impect_get(impect._players_path(iteration_id))["data"])
    players_by_id = {
        int(player["id"]): player
        for player in players
        if player.get("id") is not None
    }
    player_names = _player_names_map(players)
    club_name = str(squad.get("name") or "")
    season = iteration.get("season")

    fixture = _build_fixture_context(
        iteration_id,
        squad_id,
        body.match_id,
        iteration,
    )
    before_date = fixture.get("scheduled_date")
    exclude_match_id = int(body.match_id) if body.match_id else None

    match_stats = _player_match_stats(
        iteration_id,
        squad_id,
        before=before_date,
        exclude_match_id=exclude_match_id,
    )
    kpi_table = _squad_kpi_table(iteration_id)
    squad_stats = kpi_table.get(squad_id, {})
    matches_played = float(squad_stats.get("matches") or 0.0)

    squad_rows = _build_fixture_squad_rows(
        squad_id=squad_id,
        club_name=club_name,
        season=season,
        players_by_id=players_by_id,
        player_names=player_names,
        match_stats=match_stats,
        before=before_date,
    )

    in_possession = []
    for spec in IN_POSSESSION_METRICS:
        value, rank = _rank_metric(
            kpi_table,
            squad_id,
            spec,
            higher_better=bool(spec.get("higher_better", True)),
        )
        in_possession.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "value": round(value, 2) if value is not None else None,
                "rank": rank,
            }
        )

    out_of_possession = []
    for spec in OUT_OF_POSSESSION_METRICS:
        value, rank = _rank_metric(
            kpi_table,
            squad_id,
            spec,
            higher_better=bool(spec.get("higher_better", True)),
        )
        out_of_possession.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "value": round(value, 2) if value is not None else None,
                "rank": rank,
            }
        )

    def _build_key_stat_rows(specs: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for spec in specs:
            value, rank = _rank_metric(
                kpi_table,
                squad_id,
                spec,
                higher_better=bool(spec.get("higher_better", True)),
            )
            rows.append(
                {
                    "key": spec["key"],
                    "label": spec["label"],
                    "value": round(value, 2) if value is not None else None,
                    "rank": rank,
                    "higher_better": bool(spec.get("higher_better", True)),
                }
            )
        return rows

    key_stats = {
        "in_possession": _build_key_stat_rows(SQUAD_LIST_IN_POSSESSION_METRICS),
        "out_of_possession": _build_key_stat_rows(SQUAD_LIST_OUT_OF_POSSESSION_METRICS),
    }
    team_style = _build_team_style(iteration_id, squad_id)

    league_table = _league_table(
        iteration_id,
        before=before_date,
        exclude_match_id=exclude_match_id,
    )
    league_position = next(
        (row["position"] for row in league_table if int(row["squad_id"]) == squad_id),
        None,
    )
    home_away = _home_away_splits(
        iteration_id,
        squad_id,
        before=before_date,
        exclude_match_id=exclude_match_id,
    )
    form = _recent_form(
        iteration_id,
        squad_id,
        limit=9,
        before=before_date,
        exclude_match_id=exclude_match_id,
    )
    from app.pre_match_goals import build_goals_analysis
    from app.pre_match_player_rankings import build_player_rankings

    goals_analysis = build_goals_analysis(
        iteration_id,
        squad_id,
        before=before_date,
        exclude_match_id=exclude_match_id,
        player_names=player_names,
    )
    player_positions = {
        int(row["id"]): str(row.get("position_code") or row.get("position") or "")
        for row in squad_rows
        if row.get("id") is not None
    }
    player_rankings = build_player_rankings(
        iteration_id,
        squad_id,
        before=before_date,
        exclude_match_id=exclude_match_id,
        player_names=player_names,
        player_positions=player_positions,
        club_name=club_name,
        season=str(season) if season else None,
    )

    vale_squad_id = _resolve_port_vale_squad_id(iteration_id)
    vale_formation = (
        _formation_usage_from_matches(
            iteration_id,
            vale_squad_id,
            before=before_date,
            exclude_match_id=exclude_match_id,
        )
        if vale_squad_id is not None
        else None
    )

    squad_list = _build_squad_list_slide(
        iteration_id,
        squad_id,
        squad_rows,
        match_stats,
        player_names=player_names,
        league_position=league_position,
        club_name=club_name,
        season=season,
        key_stats=key_stats,
        before=before_date,
        exclude_match_id=exclude_match_id,
        vale_squad_id=vale_squad_id,
        vale_formation=vale_formation,
    )
    previous_xis = _build_previous_xi_slides(
        iteration_id,
        squad_id,
        player_names=player_names,
        club_name=club_name,
        season=season,
        before=before_date,
        exclude_match_id=exclude_match_id,
    )
    last_game = _build_last_game_detail(
        iteration_id,
        squad_id,
        player_names=player_names,
        club_name=club_name,
        season=season,
        before=before_date,
        exclude_match_id=exclude_match_id,
    )
    formations = [squad_list["formation"]] if squad_list.get("formation") else []

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "competition": iteration.get("competition_name"),
        "season": iteration.get("season"),
        "iteration_id": iteration_id,
        "fixture": fixture,
        "opponent": {
            "id": squad_id,
            "name": str(squad.get("name") or ""),
            "image_url": _squad_crest_url(squad.get("name"), squad.get("imageUrl")),
            "league_position": league_position,
            "matches_played": int(matches_played),
        },
        "overview": {
            "manager": squad_list.get("manager"),
            "formations": formations,
            "league_table_size": len(league_table),
        },
        "squad_list": squad_list,
        "previous_xis": previous_xis,
        "last_game": last_game,
        "squad": squad_rows,
        "team_metrics": {
            "in_possession": in_possession,
            "out_of_possession": out_of_possession,
        },
        "league_table": league_table,
        "home_away": home_away,
        "form": form,
        "goals_analysis": goals_analysis,
        "player_rankings": player_rankings,
        "team_style": team_style,
        "sections": [
            {"id": "overview", "label": "Squad overview", "status": "live"},
        {"id": "team_style", "label": "Team style & metrics", "status": "live"},
            {"id": "lineups", "label": "Previous XIs", "status": "live"},
            {"id": "form", "label": "Form & team stats", "status": "live"},
            {"id": "squad", "label": "Squad data", "status": "live"},
            {"id": "player_rankings", "label": "Player rankings", "status": "live"},
            {"id": "goals", "label": "Goals analysis", "status": "live"},
            {"id": "phases", "label": "Phase maps", "status": "planned"},
            {"id": "set_plays", "label": "Set plays", "status": "planned"},
        ],
    }


def _default_designer_fixture(iteration_id: int) -> dict[str, Any] | None:
    fixtures = build_pre_match_fixtures(iteration_id)
    if not fixtures:
        return None
    for preferred_name in PRE_MATCH_DEFAULT_OPPONENT_NAMES:
        match = next(
            (
                fixture
                for fixture in fixtures
                if str(fixture.get("opponent", {}).get("name") or "") == preferred_name
            ),
            None,
        )
        if match:
            return match
    with_match_id = [fixture for fixture in fixtures if fixture.get("match_id")]
    if with_match_id:
        return with_match_id[-1]
    return fixtures[0]


def pre_match_meta(competition_name: str = DEFAULT_COMPETITION) -> dict[str, Any]:
    impect = _impect()
    iterations = impect._fetch_iterations()
    competition_iterations = [
        item
        for item in iterations
        if str(item.get("competition_name", "")).strip() == competition_name
    ]
    competition_iterations.sort(
        key=lambda row: impect._season_sort_key(str(row.get("season", ""))),
        reverse=True,
    )
    competition_iterations = competition_iterations[:PRE_MATCH_SEASON_LIMIT]
    if not competition_iterations:
        raise HTTPException(
            status_code=404,
            detail=f"No {competition_name} seasons available.",
        )

    default_iteration = competition_iterations[
        min(PRE_MATCH_DEFAULT_SEASON_INDEX, len(competition_iterations) - 1)
    ]
    iteration_id = int(default_iteration["id"])
    default_fixture = _default_designer_fixture(iteration_id)
    squads = _unwrap_items(impect._impect_get(impect._squads_path(iteration_id))["data"])
    opponents = [
        {
            "id": int(item["id"]),
            "name": str(item.get("name") or ""),
            "is_port_vale": _is_port_vale(str(item.get("name") or "")),
        }
        for item in squads
        if item.get("id") is not None and item.get("access", True)
    ]
    opponents.sort(key=lambda row: row["name"].casefold())

    return {
        "competition": competition_name,
        "default_iteration_id": iteration_id,
        "default_fixture": (
            {
                "match_id": default_fixture.get("match_id"),
                "opponent_id": default_fixture.get("opponent", {}).get("id"),
                "opponent_name": default_fixture.get("opponent", {}).get("name"),
            }
            if default_fixture
            else None
        ),
        "default_opponent_names": list(PRE_MATCH_DEFAULT_OPPONENT_NAMES),
        "iterations": [
            {
                "id": int(item["id"]),
                "season": item.get("season"),
                "label": item.get("label") or item.get("season"),
            }
            for item in competition_iterations
            if item.get("id") is not None
        ],
        "opponents": opponents,
    }


def _decode_export_image_data(image_data: str) -> bytes:
    raw = str(image_data or "").strip()
    if not raw:
        raise ValueError("Empty image payload.")
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Invalid image data.") from exc


def _safe_png_entry_name(name: str | None, index: int) -> str:
    raw = str(name or f"slide-{index}")
    raw = re.sub(r"(?i)\.png$", "", raw)
    raw = re.sub(r"^\d+[-_\s]+", "", raw)
    cleaned = re.sub(r"[^\w\s\-]+", "", raw, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "-", cleaned).strip("-._") or f"slide-{index}"
    return f"{index:02d}-{cleaned[:60]}.png"


def build_pre_match_png_zip(body: PreMatchPngExportRequest) -> tuple[bytes, list[tuple[str, bytes]]]:
    if not body.pages:
        raise ValueError("No export pages provided.")
    entries: list[tuple[str, bytes]] = []
    for index, page in enumerate(body.pages, start=1):
        png_bytes = _decode_export_image_data(page.imageData)
        if not png_bytes:
            raise ValueError(f"Page {index} has no image data.")
        entries.append((_safe_png_entry_name(page.filename, index), png_bytes))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, png_bytes in entries:
            archive.writestr(name, png_bytes)
    return buffer.getvalue(), entries


def build_pre_match_whatsapp_pdf(body: PreMatchPngExportRequest) -> bytes:
    """One full-bleed 16:9 page per slide — 1920×1080 capture for WhatsApp sharing."""
    from app.pdf_report import SlideDeckPDF

    if not body.pages:
        raise ValueError("No export pages provided.")
    pdf = SlideDeckPDF()
    for index, page in enumerate(body.pages, start=1):
        if not page.imageData:
            raise ValueError(f"Page {index} has no image data.")
        pdf.add_full_bleed_image(page.imageData)
    output = pdf.output()
    if isinstance(output, bytearray):
        return bytes(output)
    if isinstance(output, bytes):
        return output
    return output.encode("latin-1")


def _save_png_bundle_to_desktop(
    zip_bytes: bytes,
    zip_filename: str,
    entries: list[tuple[str, bytes]],
) -> tuple[Path | None, Path | None]:
    from app.main import _desktop_export_dir, _unique_desktop_path

    zip_path = None
    folder_path = None
    try:
        desktop = _desktop_export_dir()
        zip_path = _unique_desktop_path(desktop, zip_filename)
        zip_path.write_bytes(zip_bytes)

        folder_stem = zip_path.stem
        folder_path = desktop / folder_stem
        counter = 2
        while folder_path.exists():
            folder_path = desktop / f"{folder_stem}-{counter}"
            counter += 1
        folder_path.mkdir(parents=True, exist_ok=False)
        for name, png_bytes in entries:
            (folder_path / name).write_bytes(png_bytes)
    except OSError:
        return zip_path, folder_path
    return zip_path, folder_path


def register_pre_match_routes(app: FastAPI) -> None:
    pre_match_static = HUB_ROOT / "static"
    no_cache_headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    def _pre_match_asset_build() -> str:
        """Content hash — changes automatically whenever JS/CSS change on deploy."""
        digest = hashlib.sha256()
        for name in ("pre-match.js", "pre-match.css"):
            path = pre_match_static / name
            if path.exists():
                digest.update(path.read_bytes())
        return digest.hexdigest()[:12]

    def _prepare_pre_match_html(raw_html: str) -> str:
        build = _pre_match_asset_build()
        html = raw_html
        html = re.sub(
            r'href="/static/pre-match\.css(?:\?[^"]*)?"',
            f'href="/pre-match/assets/app.css?b={build}"',
            html,
        )
        html = re.sub(
            r'src="/static/pre-match\.js(?:\?[^"]*)?"',
            f'src="/pre-match/assets/app.js?b={build}"',
            html,
        )
        html = re.sub(
            r'<meta name="pm-build" content="[^"]*"\s*/>',
            f'<meta name="pm-build" content="{build}" />',
            html,
        )
        html = re.sub(
            r'(<span class="pm-build-badge"[^>]*>)[^<]*(</span>)',
            rf"\g<1>{build[:8]}\2",
            html,
        )
        return html

    def _pre_match_page_template() -> Path:
        for name in ("pre-match.page.html", "pre-match.html"):
            path = SCOUTING_DIR / name
            if path.exists():
                return path
        raise HTTPException(status_code=404, detail="Pre-match UI template not found.")

    @app.get("/pre-match/assets/app.js")
    def pre_match_app_js() -> FileResponse:
        path = pre_match_static / "pre-match.js"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Pre-match JS not found.")
        return FileResponse(
            path,
            media_type="application/javascript",
            headers=no_cache_headers,
        )

    @app.get("/pre-match/assets/app.css")
    def pre_match_app_css() -> FileResponse:
        path = pre_match_static / "pre-match.css"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Pre-match CSS not found.")
        return FileResponse(
            path,
            media_type="text/css",
            headers=no_cache_headers,
        )

    @app.get("/api/pre-match/build")
    def pre_match_build_info() -> dict[str, Any]:
        js_path = pre_match_static / "pre-match.js"
        css_path = pre_match_static / "pre-match.css"
        build = _pre_match_asset_build()
        return {
            "build": build,
            "hub_root": str(HUB_ROOT),
            "html_source": str(_pre_match_page_template()),
            "js_path": str(js_path),
            "css_path": str(css_path),
            "js_bytes": js_path.stat().st_size if js_path.exists() else 0,
            "css_bytes": css_path.stat().st_size if css_path.exists() else 0,
            "js_has_goals_unit": "pm-goal-phase__unit" in (js_path.read_text(encoding="utf-8") if js_path.exists() else ""),
            "team_url": "/pre-match",
        }

    @app.get("/pre-match", response_class=HTMLResponse)
    def pre_match_page() -> HTMLResponse:
        html_path = _pre_match_page_template()
        return HTMLResponse(
            _prepare_pre_match_html(html_path.read_text(encoding="utf-8")),
            headers=no_cache_headers,
        )

    @app.get("/api/pre-match/meta")
    def pre_match_meta_route(
        competition: str = Query(DEFAULT_COMPETITION, min_length=1),
    ) -> dict[str, Any]:
        return pre_match_meta(competition)

    @app.get("/api/pre-match/opponents")
    def pre_match_opponents(iteration_id: int = Query(..., ge=1)) -> dict[str, Any]:
        impect = _impect()
        squads = _unwrap_items(impect._impect_get(impect._squads_path(iteration_id))["data"])
        opponents = [
            {
                "id": int(item["id"]),
                "name": str(item.get("name") or ""),
                "is_port_vale": _is_port_vale(str(item.get("name") or "")),
            }
            for item in squads
            if item.get("id") is not None and item.get("access", True)
        ]
        opponents.sort(key=lambda row: row["name"].casefold())
        return {"opponents": opponents}

    @app.get("/api/pre-match/fixtures")
    def pre_match_fixtures(iteration_id: int = Query(..., ge=1)) -> dict[str, Any]:
        return {"fixtures": build_pre_match_fixtures(iteration_id)}

    @app.post("/api/pre-match/report")
    def pre_match_report(body: PreMatchReportRequest) -> dict[str, Any]:
        return build_pre_match_report(body)

    @app.get("/api/pre-match/player-photo")
    def pre_match_player_photo(
        name: str = Query(..., min_length=1),
        club: str | None = Query(None),
        season: str | None = Query(None),
    ) -> Response:
        image_bytes, content_type = _resolve_player_photo_bytes(
            name,
            club=club,
            season=season,
        )
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.post("/api/pre-match/export-pngs")
    def pre_match_export_pngs(body: PreMatchPngExportRequest) -> Response:
        from app.main import _safe_export_filename

        if not body.pages:
            raise HTTPException(status_code=400, detail="No export pages provided.")
        try:
            zip_bytes, entries = build_pre_match_png_zip(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        opponent = re.sub(r"[^\w\s\-]+", "", str(body.opponent_name or "opponent"))
        opponent = re.sub(r"\s+", "-", opponent).strip("-") or "opponent"
        default_name = f"port-vale-pre-match-{opponent}-slides.zip"
        filename = _safe_export_filename(body.filename or default_name, default_ext=".zip")
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        zip_path, folder_path = _save_png_bundle_to_desktop(zip_bytes, filename, entries)
        if zip_path is not None:
            headers["X-Saved-Desktop-Path"] = str(zip_path)
        if folder_path is not None:
            headers["X-Saved-Desktop-Folder"] = str(folder_path)
        return Response(content=zip_bytes, media_type="application/zip", headers=headers)

    @app.post("/api/pre-match/export-whatsapp-pdf")
    def pre_match_export_whatsapp_pdf(body: PreMatchPngExportRequest) -> Response:
        from app.main import _safe_export_filename, _save_export_to_desktop

        if not body.pages:
            raise HTTPException(status_code=400, detail="No export pages provided.")
        try:
            pdf_bytes = build_pre_match_whatsapp_pdf(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        opponent = re.sub(r"[^\w\s\-]+", "", str(body.opponent_name or "opponent"))
        opponent = re.sub(r"\s+", "-", opponent).strip("-") or "opponent"
        default_name = f"port-vale-pre-match-{opponent}-whatsapp.pdf"
        filename = _safe_export_filename(body.filename or default_name, default_ext=".pdf")
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        saved_path = _save_export_to_desktop(pdf_bytes, filename)
        if saved_path is not None:
            headers["X-Saved-Desktop-Path"] = str(saved_path)
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
