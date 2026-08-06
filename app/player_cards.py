"""Opponent blank player cards — club website roster + Impect height/foot."""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
import requests

from app.fixture_planner import (
    ALLOWED_FIXTURE_SEASONS,
    _fetch_fotmob_fixtures,
    _iteration_for_competition,
)
from app.opponent_photos import (
    _normalize_name_key,
    opponent_photo_api_url,
    transfermarkt_first_team_roster,
)
from app.pre_match import (
    _format_foot,
    _is_port_vale,
    _player_age,
    _player_display_name,
    _player_surname,
    _position_label,
    _squads_map,
)
from app.pre_match_handout import _height_short
from app.scouting import SCOUTING_DIR
from app.set_piece_pre_match import _fetch_transfermarkt_squad_profiles
from app.squad_photos import (
    club_squad_page_url,
    fetch_club_squad_roster_for,
)
from app.squad_review import _normalize_season_token, _port_vale_candidate_iterations

DEFAULT_SEASON = "26/27"
DEFAULT_LEAGUE = "League Two"

# EFL leagues available in Player Cards (FotMob ids; Impect where licensed).
PLAYER_CARDS_LEAGUES: tuple[dict[str, Any], ...] = (
    {
        "ui": "Championship",
        "competition": "Championship",
        "competition_aliases": ("Championship", "EFL Championship", "Sky Bet Championship"),
        "fotmob_id": 48,
    },
    {
        "ui": "League One",
        "competition": "League One",
        "competition_aliases": ("League One",),
        "fotmob_id": 108,
    },
    {
        "ui": "League Two",
        "competition": "League Two",
        "competition_aliases": ("League Two",),
        "fotmob_id": 109,
    },
)
PLAYER_CARDS_LEAGUE_BY_UI = {row["ui"]: row for row in PLAYER_CARDS_LEAGUES}
PLAYER_CARDS_LEAGUE_UIS = [row["ui"] for row in PLAYER_CARDS_LEAGUES]

_clubs_cache: dict[str, tuple[float, tuple[list[dict[str, Any]], str | None]]] = {}
_CLUBS_CACHE_TTL = 600.0

POSITION_CARD_LABELS: dict[str, str] = {
    "GOALKEEPER": "GK",
    "CENTRAL_DEFENDER": "CB",
    "LEFT_WINGBACK_DEFENDER": "LWB",
    "RIGHT_WINGBACK_DEFENDER": "RWB",
    "LEFT_BACK": "LB",
    "RIGHT_BACK": "RB",
    "DEFENSE_MIDFIELD": "DM",
    "CENTRAL_MIDFIELD": "CM",
    "ATTACKING_MIDFIELD": "ATT MID",
    "LEFT_MIDFIELD": "LM",
    "RIGHT_MIDFIELD": "RM",
    "LEFT_WINGER": "LW",
    "RIGHT_WINGER": "RW",
    "CENTER_FORWARD": "CF",
    "SECOND_STRIKER": "SS",
}

CLUB_GROUP_LABELS: dict[str, str] = {
    "GK": "GK",
    "CB": "CB",
    "WB": "LWB",
    "CM": "CM",
    "ATT": "ATT",
}

BAND_ORDER: dict[str, int] = {"GK": 0, "CB": 1, "WB": 2, "CM": 3, "ATT": 4}

_squad_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_SQUAD_CACHE_TTL = 30 * 60
_fotmob_foot_cache: dict[int, tuple[float, str | None]] = {}
_FOTMOB_FOOT_TTL = 24 * 60 * 60


def _impect():
    from app import main as impect_main

    return impect_main


def _card_foot_label(leg: Any) -> str:
    raw = str(leg or "").strip().upper().replace("_", " ")
    if raw in {"L", "LEFT FOOT"} or "LEFT" in raw:
        return "LEFT"
    if raw in {"R", "RIGHT FOOT"} or "RIGHT" in raw:
        return "RIGHT"
    if raw in {"BOTH", "BOTH FEET"} or "BOTH" in raw:
        return "BOTH"
    formatted = _format_foot(leg)
    if formatted == "—":
        return "—"
    if formatted == "L":
        return "LEFT"
    if formatted == "R":
        return "RIGHT"
    return formatted.upper()


def _card_position_label(position_code: str | None, *, club_group: str | None = None) -> str:
    if position_code:
        code = str(position_code).upper()
        if code in POSITION_CARD_LABELS:
            return POSITION_CARD_LABELS[code]
        return _position_label(position_code).upper()
    if club_group and club_group in CLUB_GROUP_LABELS:
        return CLUB_GROUP_LABELS[club_group]
    return "—"


def _position_codes_from_player(player: dict[str, Any] | None) -> list[str]:
    if not player:
        return []
    codes: list[str] = []
    for key in ("position", "mainPosition", "primaryPosition"):
        raw = player.get(key)
        if raw and str(raw).upper() not in codes:
            codes.append(str(raw).upper())
    positions = player.get("positions")
    if isinstance(positions, list):
        for item in positions:
            if isinstance(item, dict):
                raw = item.get("position") or item.get("name")
            else:
                raw = item
            if raw and str(raw).upper() not in codes:
                codes.append(str(raw).upper())
    return codes


def _card_position_text(
    player: dict[str, Any] | None,
    *,
    tm_profile: dict[str, Any] | None = None,
    club_group: str | None = None,
) -> str:
    codes = _position_codes_from_player(player)
    if codes:
        labels = [_card_position_label(code) for code in codes[:2]]
        return " / ".join(label for label in labels if label and label != "—")
    if tm_profile and tm_profile.get("position_abbr"):
        return str(tm_profile["position_abbr"]).upper()
    return _card_position_label(None, club_group=club_group)


def _match_impect_player(name: str, players_by_key: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    key = _normalize_name_key(name)
    if key in players_by_key:
        return players_by_key[key]

    parts = [part for part in re.split(r"\s+", str(name or "").strip()) if part]
    if not parts:
        return None
    last = parts[-1].casefold()
    first = parts[0].casefold() if parts else ""

    candidates: list[dict[str, Any]] = []
    for candidate in players_by_key.values():
        candidate_name = str(candidate.get("_display_name") or "")
        candidate_parts = candidate_name.split()
        if not candidate_parts:
            continue
        candidate_last = candidate_parts[-1].casefold()
        if candidate_last != last:
            continue
        candidate_first = candidate_parts[0].casefold()
        if first and candidate_first:
            if (
                candidate_first.startswith(first[:3])
                or first.startswith(candidate_first[:3])
                or candidate_first.startswith(first)
                or first.startswith(candidate_first)
            ):
                candidates.append(candidate)
        else:
            candidates.append(candidate)

    if len(candidates) == 1:
        return candidates[0]
    for candidate in candidates:
        candidate_parts = str(candidate.get("_display_name") or "").split()
        if candidate_parts and candidate_parts[0].casefold() == first:
            return candidate
    return candidates[0] if candidates else None


def _canonical_club_key(name: str) -> str:
    key = _normalize_name_key(name)
    return re.sub(r"^fc", "", key)


def _fetch_fotmob_squad_roster(fotmob_id: str | int | None) -> list[dict[str, Any]]:
    """FotMob team squad — names, shirts, height, age when Impect/TM unavailable."""
    token = str(fotmob_id or "").strip()
    if not token:
        return []

    from app.fixture_planner import _http

    try:
        response = _http.get(
            "https://www.fotmob.com/api/data/teams",
            params={"id": token},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=25,
        )
        if not response.ok:
            return []
        payload = response.json()
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    groups = (payload.get("squad") or {}).get("squad") or []
    if not isinstance(groups, list):
        return rows

    for group in groups:
        if not isinstance(group, dict):
            continue
        if str(group.get("title") or "").casefold() == "coach":
            continue
        members = group.get("members") or []
        if not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            role = member.get("role")
            if isinstance(role, dict) and str(role.get("key") or "").casefold() == "coach":
                continue
            name = str(member.get("name") or "").strip()
            if not name:
                continue
            shirt_raw = member.get("shirtNumber")
            shirt_number = None
            if shirt_raw is not None:
                try:
                    shirt_number = int(shirt_raw)
                except (TypeError, ValueError):
                    shirt_number = None
            rows.append(
                {
                    "name": name,
                    "shirt_number": shirt_number,
                    "photo_url": None,
                    "fotmob_player_id": member.get("id"),
                    "position_group": None,
                    "position_label": str(member.get("positionIdsDesc") or "").strip() or None,
                    "height_cm": member.get("height"),
                    "age": member.get("age"),
                    "source": "fotmob",
                }
            )
    return rows


def _fetch_fotmob_preferred_foot(player_id: Any) -> str | None:
    """LEFT / RIGHT from FotMob playerData preferred foot, when available."""
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None

    now = time.time()
    cached = _fotmob_foot_cache.get(pid)
    if cached and now - cached[0] < _FOTMOB_FOOT_TTL:
        return cached[1]

    foot: str | None = None
    try:
        from app.fixture_planner import _http

        response = _http.get(
            "https://www.fotmob.com/api/data/playerData",
            params={"id": pid},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        if response.ok:
            payload = response.json()
            for row in payload.get("playerInformation") or []:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or "")
                key = str(row.get("translationKey") or "")
                if key != "preferred_foot" and "preferred foot" not in title.casefold():
                    continue
                value = row.get("value")
                raw = None
                if isinstance(value, dict):
                    raw = value.get("key") or value.get("fallback")
                else:
                    raw = value
                labelled = _card_foot_label(raw)
                if labelled in {"LEFT", "RIGHT", "BOTH"}:
                    foot = labelled
                break
    except Exception:
        foot = None

    _fotmob_foot_cache[pid] = (now, foot)
    return foot


def _fotmob_feet_for_ids(player_ids: list[Any], *, deadline_s: float = 8.0) -> dict[int, str]:
    ids: list[int] = []
    for raw in player_ids:
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            ids.append(pid)
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}

    out: dict[int, str] = {}
    missing: list[int] = []
    now = time.time()
    for pid in ids:
        cached = _fotmob_foot_cache.get(pid)
        if cached and now - cached[0] < _FOTMOB_FOOT_TTL:
            if cached[1]:
                out[pid] = cached[1]
        else:
            missing.append(pid)

    if not missing:
        return out

    started = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch_fotmob_preferred_foot, pid): pid for pid in missing}
        try:
            for future in as_completed(futures, timeout=max(0.1, deadline_s)):
                if time.time() - started >= deadline_s:
                    break
                pid = futures[future]
                try:
                    foot = future.result(timeout=0.1)
                except Exception:
                    foot = None
                if foot:
                    out[pid] = foot
        except TimeoutError:
            pass
    return out


def _height_from_cm(cm: Any) -> str:
    try:
        value = int(float(cm))
    except (TypeError, ValueError):
        return "—"
    if value <= 0:
        return "—"
    feet = int(value // 30.48)
    inches = int(round((value / 2.54) % 12))
    return f"{feet}'{inches}\""


def _fotmob_player_photo_url(player_id: Any) -> str | None:
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    return f"https://images.fotmob.com/image_resources/playerimages/{pid}.png"


def _format_position_label(label: str | None) -> str:
    text = str(label or "").strip()
    if not text:
        return "—"
    if "," not in text:
        return text.upper()
    parts = [part.strip().upper() for part in text.split(",") if part.strip()]
    return " / ".join(parts[:3])


def _resolve_card_photo_urls(
    name: str,
    club: str,
    season: str,
    row: dict[str, Any],
) -> tuple[str | None, str | None, list[str]]:
    """Primary photo URL plus FotMob direct URL and ordered fallbacks."""
    fallbacks: list[str] = []
    primary: str | None = None

    club_url = row.get("photo_url")
    if club_url:
        primary = str(club_url)
        fallbacks.append(primary)

    fotmob_url = _fotmob_player_photo_url(row.get("fotmob_player_id"))
    if fotmob_url and fotmob_url not in fallbacks:
        fallbacks.append(fotmob_url)
        if not primary:
            primary = fotmob_url

    proxy_url = opponent_photo_api_url(name, club_name=club, season=season)
    if proxy_url and proxy_url not in fallbacks:
        fallbacks.append(proxy_url)
        if not primary:
            primary = proxy_url

    return primary, fotmob_url, fallbacks


def _normalize_league_ui(league: str | None) -> str:
    raw = str(league or "").strip()
    if raw in PLAYER_CARDS_LEAGUE_BY_UI:
        return raw
    lowered = raw.casefold()
    for ui in PLAYER_CARDS_LEAGUE_UIS:
        if ui.casefold() == lowered:
            return ui
    return DEFAULT_LEAGUE


def _league_iteration(league: str, season: str) -> dict[str, Any] | None:
    """Impect iteration for an EFL league season when available."""
    config = PLAYER_CARDS_LEAGUE_BY_UI.get(_normalize_league_ui(league))
    if not config:
        return None
    aliases = config.get("competition_aliases") or (config.get("competition"),)
    try:
        for name in aliases:
            iteration = _iteration_for_competition(str(name), season)
            if iteration:
                return iteration
        # Port Vale candidate iterations often cover League Two even if the
        # generic competition lookup is empty.
        if _normalize_league_ui(league) == DEFAULT_LEAGUE:
            target = _normalize_season_token(season)
            impect = _impect()
            for iteration in _port_vale_candidate_iterations(impect):
                if str(iteration.get("season") or "").strip() != target:
                    continue
                if str(iteration.get("competition_name") or "").strip() != DEFAULT_LEAGUE:
                    continue
                return iteration
    except Exception:
        return None
    return None


def _league_two_iteration(season: str) -> dict[str, Any] | None:
    """Back-compat wrapper — League Two Impect iteration."""
    return _league_iteration(DEFAULT_LEAGUE, season)


def _squad_ids_by_name(iteration_id: int) -> dict[str, int]:
    try:
        squads = _squads_map(iteration_id)
    except Exception:
        return {}
    by_name: dict[str, int] = {}
    for squad_id, row in squads.items():
        if not isinstance(row, dict):
            by_name[_normalize_name_key(str(row))] = int(squad_id)
            continue
        name = str(row.get("name") or "").strip()
        if name:
            by_name[_normalize_name_key(name)] = int(squad_id)
    return by_name


def _upsert_club_row(
    clubs: dict[str, dict[str, Any]],
    *,
    name: str,
    league: str,
    squad_id: Any = None,
    iteration_id: Any = None,
    fotmob_id: Any = None,
) -> None:
    if not name:
        return
    key = _canonical_club_key(name)
    existing = clubs.get(key)
    if existing is None:
        clubs[key] = {
            "name": name,
            "squad_id": squad_id,
            "iteration_id": iteration_id,
            "fotmob_id": str(fotmob_id).strip() if fotmob_id not in (None, "") else None,
            "league": league,
            "club_site_url": club_squad_page_url(name),
            "fixture_count": 0,
        }
        return

    if not str(existing.get("name") or "").startswith("FC ") and name.startswith("FC "):
        pass
    elif str(existing.get("name") or "").startswith("FC ") and not name.startswith("FC "):
        existing["name"] = name
    if squad_id and not existing.get("squad_id"):
        existing["squad_id"] = squad_id
    if iteration_id and not existing.get("iteration_id"):
        existing["iteration_id"] = iteration_id
    if fotmob_id and not existing.get("fotmob_id"):
        existing["fotmob_id"] = str(fotmob_id).strip()


def _clubs_for_league(
    league: str,
    season: str,
    *,
    enrich_impect: bool = True,
) -> tuple[list[dict[str, Any]], str | None]:
    """All clubs in an EFL league for the season (FotMob first, Impect ids when available)."""
    league_ui = _normalize_league_ui(league)
    cache_key = f"{season}|{league_ui}|impect={int(bool(enrich_impect))}"
    cached = _clubs_cache.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _CLUBS_CACHE_TTL:
        return cached[1][0], cached[1][1]

    config = PLAYER_CARDS_LEAGUE_BY_UI[league_ui]
    clubs: dict[str, dict[str, Any]] = {}
    upcoming_opponent: str | None = None

    # FotMob is the fast, reliable club list for all three EFL divisions.
    try:
        fotmob_fixtures = _fetch_fotmob_fixtures(
            int(config["fotmob_id"]),
            league_ui=league_ui,
            season=season,
        )
    except Exception:
        fotmob_fixtures = []

    fotmob_fixtures_sorted = sorted(
        fotmob_fixtures,
        key=lambda row: (
            str(row.get("date") or ""),
            str(row.get("kickoff_utc") or ""),
        ),
    )

    for fixture in fotmob_fixtures_sorted:
        for side in ("home", "away"):
            team = fixture.get(side) if isinstance(fixture.get(side), dict) else {}
            name = str(team.get("name") or "").strip()
            if not name:
                continue
            if league_ui == DEFAULT_LEAGUE and _is_port_vale(name):
                continue
            key = _canonical_club_key(name)
            _upsert_club_row(
                clubs,
                name=name,
                league=league_ui,
                fotmob_id=team.get("fotmob_id"),
            )
            clubs[key]["fixture_count"] = int(clubs[key].get("fixture_count") or 0) + 1

        if league_ui == DEFAULT_LEAGUE and upcoming_opponent is None:
            home_name = str((fixture.get("home") or {}).get("name") or "")
            away_name = str((fixture.get("away") or {}).get("name") or "")
            if _is_port_vale(home_name):
                upcoming_opponent = away_name
            elif _is_port_vale(away_name):
                upcoming_opponent = home_name

    iteration_id = None
    squad_ids: dict[str, int] = {}
    if enrich_impect:
        # Optional Impect enrichment (height/foot) — never required for the dropdown.
        iteration = _league_iteration(league_ui, season)
        iteration_id = int(iteration["id"]) if iteration else None
        squad_ids = _squad_ids_by_name(iteration_id) if iteration_id else {}

        if iteration_id and squad_ids:
            try:
                squads = _squads_map(iteration_id)
            except Exception:
                squads = {}
            for squad_id, row in squads.items():
                if isinstance(row, dict):
                    name = str(row.get("name") or "").strip()
                else:
                    name = str(row or "").strip()
                if not name:
                    continue
                if league_ui == DEFAULT_LEAGUE and _is_port_vale(name):
                    continue
                _upsert_club_row(
                    clubs,
                    name=name,
                    league=league_ui,
                    squad_id=int(squad_id),
                    iteration_id=iteration_id,
                )

    rows = sorted(clubs.values(), key=lambda row: str(row.get("name") or "").casefold())
    for row in rows:
        if not row.get("squad_id") and iteration_id:
            row["squad_id"] = squad_ids.get(_normalize_name_key(row.get("name") or ""))
        if not row.get("iteration_id") and iteration_id:
            row["iteration_id"] = iteration_id

    _clubs_cache[cache_key] = (now, (rows, upcoming_opponent))
    return rows, upcoming_opponent


def _opponents_from_fixtures(season: str) -> tuple[list[dict[str, Any]], str | None]:
    """Back-compat — League Two clubs for the season."""
    return _clubs_for_league(DEFAULT_LEAGUE, season, enrich_impect=False)


def _find_club_row(
    club_name: str,
    *,
    season: str,
    league: str | None = None,
) -> dict[str, Any] | None:
    leagues = (
        [_normalize_league_ui(league)]
        if league
        else list(PLAYER_CARDS_LEAGUE_UIS)
    )
    target = _normalize_name_key(club_name)
    for league_ui in leagues:
        clubs, _ = _clubs_for_league(league_ui, season, enrich_impect=False)
        for row in clubs:
            if _normalize_name_key(row.get("name")) == target:
                return row
    return None


def _resolve_squad_context(
    club_name: str,
    *,
    season: str,
    squad_id: int | None = None,
    iteration_id: int | None = None,
    league: str | None = None,
) -> tuple[int | None, int | None]:
    if iteration_id and squad_id:
        return int(iteration_id), int(squad_id)

    opponent = _find_club_row(club_name, season=season, league=league)
    if opponent:
        resolved_iteration = opponent.get("iteration_id")
        resolved_squad = opponent.get("squad_id")
        if resolved_iteration and resolved_squad:
            return int(resolved_iteration), int(resolved_squad)

    # Only probe Impect when the club actually belongs to this league list.
    # Avoids hanging lookups when the UI sends a mismatched club/league pair.
    if opponent is None and league:
        return iteration_id, squad_id

    league_ui = _normalize_league_ui(league) if league else None
    search_leagues = [league_ui] if league_ui else list(PLAYER_CARDS_LEAGUE_UIS)
    for lg in search_leagues:
        try:
            iteration = _league_iteration(lg, season)
        except Exception:
            continue
        if not iteration:
            continue
        iter_id = int(iteration["id"])
        squad_ids = _squad_ids_by_name(iter_id)
        sid = squad_ids.get(_normalize_name_key(club_name))
        if sid:
            return iter_id, sid

    return iteration_id, squad_id


def _impect_players_for_squad(
    iteration_id: int | None,
    squad_id: int | None,
) -> dict[str, dict[str, Any]]:
    if not iteration_id or not squad_id:
        return {}

    impect = _impect()
    try:
        players = impect._fetch_players_for_iteration(int(iteration_id))
    except Exception:
        return {}

    by_key: dict[str, dict[str, Any]] = {}
    for player in players:
        if impect._extract_squad_id_from_player(player) != int(squad_id):
            continue
        name = _player_display_name(player)
        if not name:
            continue
        enriched = dict(player)
        enriched["_display_name"] = name
        by_key[_normalize_name_key(name)] = enriched
    return by_key


def _sort_key_for_card(card: dict[str, Any]) -> tuple[Any, ...]:
    shirt = card.get("shirt_number")
    try:
        shirt_sort = int(shirt)
    except (TypeError, ValueError):
        shirt_sort = 999
    band = str(card.get("position_band") or "CM")
    return (BAND_ORDER.get(band, 5), shirt_sort, str(card.get("surname") or "").casefold())


def build_player_cards_squad(
    *,
    club_name: str,
    season: str = DEFAULT_SEASON,
    league: str | None = None,
    squad_id: int | None = None,
    iteration_id: int | None = None,
    fotmob_id: str | int | None = None,
) -> dict[str, Any]:
    if season not in ALLOWED_FIXTURE_SEASONS:
        raise ValueError(f"Season must be one of: {', '.join(ALLOWED_FIXTURE_SEASONS)}")

    club = str(club_name or "").strip()
    if not club:
        raise ValueError("Club name is required.")

    league_ui = _normalize_league_ui(league) if league else None
    cache_key = (
        f"v2feet|{season}|{league_ui or ''}|{_normalize_name_key(club)}|"
        f"{squad_id or ''}|{iteration_id or ''}|{fotmob_id or ''}"
    )
    cached = _squad_cache.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _SQUAD_CACHE_TTL:
        return cached[1]

    club_row = _find_club_row(club, season=season, league=league_ui)
    if club_row is None and league_ui:
        # Mismatched league/club from a stale UI — recover FotMob id from any division.
        club_row = _find_club_row(club, season=season, league=None)
        if club_row:
            league_ui = str(club_row.get("league") or league_ui) or league_ui
    if club_row and not league_ui:
        league_ui = str(club_row.get("league") or "") or None
    if not fotmob_id and club_row:
        fotmob_id = club_row.get("fotmob_id")

    resolved_iteration_id, resolved_squad_id = _resolve_squad_context(
        club,
        season=season,
        squad_id=squad_id or (club_row.get("squad_id") if club_row else None),
        iteration_id=iteration_id or (club_row.get("iteration_id") if club_row else None),
        league=league_ui,
    )
    try:
        impect_by_key = _impect_players_for_squad(resolved_iteration_id, resolved_squad_id)
    except Exception:
        impect_by_key = {}
    try:
        tm_profiles = _fetch_transfermarkt_squad_profiles(club, season) or {}
    except Exception:
        tm_profiles = {}
    try:
        tm_photo_roster = transfermarkt_first_team_roster(club, season) or {}
    except Exception:
        tm_photo_roster = {}
    try:
        club_roster = fetch_club_squad_roster_for(club) or []
    except Exception:
        club_roster = []
    club_site_url = club_squad_page_url(club)

    roster_rows: list[dict[str, Any]] = []
    if club_roster:
        for row in club_roster:
            roster_rows.append(
                {
                    "name": row.get("name"),
                    "shirt_number": row.get("shirt_number"),
                    "photo_url": row.get("photo_url"),
                    "position_group": row.get("position_group"),
                    "source": "club_website",
                }
            )
    else:
        seen_names: set[str] = set()
        for key, player in impect_by_key.items():
            name = str(player.get("_display_name") or "")
            if not name or key in seen_names:
                continue
            seen_names.add(key)
            tm = tm_profiles.get(key) or {}
            roster_rows.append(
                {
                    "name": name,
                    "shirt_number": tm.get("shirt_number"),
                    "photo_url": tm_photo_roster.get(key, {}).get("url"),
                    "position_group": None,
                    "source": "impect",
                }
            )
        for key, tm in tm_profiles.items():
            if key in seen_names:
                continue
            name = str(tm.get("name") or "").strip()
            if not name:
                continue
            seen_names.add(key)
            roster_rows.append(
                {
                    "name": name,
                    "shirt_number": tm.get("shirt_number"),
                    "photo_url": tm_photo_roster.get(key, {}).get("url"),
                    "position_group": None,
                    "source": "transfermarkt",
                }
            )
        for key, entry in tm_photo_roster.items():
            if key in seen_names:
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            seen_names.add(key)
            tm = tm_profiles.get(key) or {}
            roster_rows.append(
                {
                    "name": name,
                    "shirt_number": tm.get("shirt_number"),
                    "photo_url": entry.get("url"),
                    "position_group": None,
                    "source": "transfermarkt",
                }
            )
        if not roster_rows and fotmob_id:
            for row in _fetch_fotmob_squad_roster(fotmob_id):
                key = _normalize_name_key(str(row.get("name") or ""))
                if key in seen_names:
                    continue
                seen_names.add(key)
                roster_rows.append(row)

    # Attach FotMob player IDs (and later preferred foot) when we have a club fotmob id,
    # even if the roster itself came from Impect / club site.
    if fotmob_id:
        fotmob_by_key = {
            _normalize_name_key(str(row.get("name") or "")): row
            for row in _fetch_fotmob_squad_roster(fotmob_id)
            if row.get("name")
        }
        for row in roster_rows:
            if row.get("fotmob_player_id"):
                continue
            match = fotmob_by_key.get(_normalize_name_key(str(row.get("name") or "")))
            if not match:
                # loose surname match
                parts = str(row.get("name") or "").strip().split()
                surname = _normalize_name_key(parts[-1]) if parts else ""
                candidates = [
                    item
                    for key, item in fotmob_by_key.items()
                    if surname and (key.endswith(surname) or surname in key)
                ]
                match = candidates[0] if len(candidates) == 1 else None
            if match and match.get("fotmob_player_id"):
                row["fotmob_player_id"] = match.get("fotmob_player_id")
                if not row.get("height_cm") and match.get("height_cm"):
                    row["height_cm"] = match.get("height_cm")
                if row.get("age") is None and match.get("age") is not None:
                    row["age"] = match.get("age")

    fotmob_feet = _fotmob_feet_for_ids(
        [row.get("fotmob_player_id") for row in roster_rows if row.get("fotmob_player_id")]
    )

    cards: list[dict[str, Any]] = []
    for row in roster_rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        name_key = _normalize_name_key(name)
        impect_player = _match_impect_player(name, impect_by_key)
        tm_profile = tm_profiles.get(name_key) or {}

        shirt_number = row.get("shirt_number")
        if shirt_number is None and tm_profile.get("shirt_number") is not None:
            shirt_number = tm_profile.get("shirt_number")

        surname = _player_surname(name).upper()
        header = f"{shirt_number}. {surname}" if shirt_number is not None else surname

        height = _height_short(impect_player or {})
        if height == "—" and row.get("height_cm"):
            height = _height_from_cm(row.get("height_cm"))
        if height == "—" and tm_profile.get("height_cm"):
            cm = int(tm_profile["height_cm"])
            feet = int(cm // 30.48)
            inches = int(round((cm / 2.54) % 12))
            height = f"{feet}'{inches}\""

        age_val = _player_age(impect_player or {})
        if age_val is None and row.get("age") is not None:
            try:
                age_val = int(row["age"])
            except (TypeError, ValueError):
                age_val = None
        age = f"{age_val} Y/O" if age_val is not None else "—"

        foot = _card_foot_label(impect_player.get("leg") if impect_player else None)
        if foot == "—" and tm_profile.get("foot"):
            foot = _card_foot_label(tm_profile.get("foot"))
        if foot == "—":
            try:
                fotmob_pid = int(row["fotmob_player_id"]) if row.get("fotmob_player_id") is not None else None
            except (TypeError, ValueError):
                fotmob_pid = None
            if fotmob_pid and fotmob_feet.get(fotmob_pid):
                foot = fotmob_feet[fotmob_pid]
        position = _card_position_text(
            impect_player,
            tm_profile=tm_profile,
            club_group=str(row.get("position_group") or "") or None,
        )
        if position == "—" and row.get("position_label"):
            position = _format_position_label(str(row.get("position_label")))
        position_band = str(row.get("position_group") or "")
        if not position_band and impect_player:
            codes = _position_codes_from_player(impect_player)
            if codes:
                position_band = _card_position_label(codes[0])
        if position_band in CLUB_GROUP_LABELS:
            position_band = position_band
        elif position.startswith("GK"):
            position_band = "GK"
        elif position.startswith("CB") or position.startswith("LWB") or position.startswith("RWB"):
            position_band = "CB"
        elif position.startswith("CM") or position.startswith("DM") or position.startswith("ATT MID"):
            position_band = "CM"
        else:
            position_band = "ATT"

        photo_url, fotmob_photo_url, photo_fallbacks = _resolve_card_photo_urls(
            name,
            club,
            season,
            row,
        )

        cards.append(
            {
                "name": name,
                "surname": surname,
                "header": header,
                "shirt_number": shirt_number,
                "photo_url": photo_url,
                "fotmob_photo_url": fotmob_photo_url,
                "photo_fallbacks": photo_fallbacks,
                "height": height,
                "age": age,
                "foot": foot,
                "position": position,
                "position_band": position_band,
                "player_id": impect_player.get("id") if impect_player else None,
                "fotmob_player_id": row.get("fotmob_player_id"),
                "sources": {
                    "identity": row.get("source") or "unknown",
                    "photo": (
                        "club_website"
                        if row.get("photo_url")
                        else ("fotmob" if fotmob_photo_url and photo_url == fotmob_photo_url else "proxy")
                    ),
                    "metrics": "impect" if impect_player else row.get("source") or "unknown",
                },
            }
        )

    cards.sort(key=_sort_key_for_card)

    payload = {
        "club": club,
        "season": season,
        "league": league_ui or DEFAULT_LEAGUE,
        "iteration_id": resolved_iteration_id,
        "squad_id": resolved_squad_id,
        "club_site_url": club_site_url,
        "club_site_available": bool(club_site_url),
        "players": cards,
        "player_count": len(cards),
    }
    _squad_cache[cache_key] = (now, payload)
    return payload


def player_cards_meta(
    *,
    season: str = DEFAULT_SEASON,
    league: str | None = None,
) -> dict[str, Any]:
    use_season = season if season in ALLOWED_FIXTURE_SEASONS else DEFAULT_SEASON
    league_ui = _normalize_league_ui(league) if league else DEFAULT_LEAGUE
    opponents, upcoming = _clubs_for_league(league_ui, use_season, enrich_impect=False)
    default_club = upcoming if league_ui == DEFAULT_LEAGUE else None
    if not default_club and opponents:
        default_club = opponents[0]["name"]
    return {
        "seasons": [DEFAULT_SEASON],
        "default_season": DEFAULT_SEASON,
        "leagues": list(PLAYER_CARDS_LEAGUE_UIS),
        "default_league": DEFAULT_LEAGUE,
        "league": league_ui,
        "opponents": opponents,
        "clubs": opponents,
        "default_club": default_club,
        "upcoming_opponent": upcoming if league_ui == DEFAULT_LEAGUE else None,
    }


class PlayerCardsExportPage(BaseModel):
    imageData: str = ""
    filename: str | None = None
    width: int = 0
    height: int = 0


class PlayerCardsExportRequest(BaseModel):
    pages: list[PlayerCardsExportPage] = []
    filename: str | None = None
    club_name: str | None = None


def build_player_cards_export_pdf(body: PlayerCardsExportRequest) -> bytes:
    """A4 landscape — one captured page (6 cards) per PDF page."""
    from io import BytesIO

    from fpdf import FPDF

    from app.pdf_report import decode_image_data

    if not body.pages:
        raise ValueError("No export pages provided.")

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(0, 0, 0)

    for index, page in enumerate(body.pages, start=1):
        if not page.imageData:
            raise ValueError(f"Page {index} has no image data.")
        pdf.add_page()
        pdf.image(
            BytesIO(decode_image_data(page.imageData)),
            x=0,
            y=0,
            w=pdf.w,
            h=pdf.h,
        )

    output = pdf.output()
    if isinstance(output, bytearray):
        return bytes(output)
    if isinstance(output, bytes):
        return output
    return output.encode("latin-1")


def register_player_cards_routes(app: FastAPI) -> None:
    @app.get("/player-cards", response_class=HTMLResponse)
    def player_cards_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "player-cards.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Player Cards UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/player-cards/meta")
    def player_cards_meta_route(
        season: str | None = Query(None),
        league: str | None = Query(None),
    ) -> dict[str, Any]:
        use_season = season if season in ALLOWED_FIXTURE_SEASONS else DEFAULT_SEASON
        return player_cards_meta(season=use_season, league=league)

    @app.get("/api/player-cards/squad")
    def player_cards_squad_route(
        club: str = Query(...),
        season: str | None = Query(DEFAULT_SEASON),
        league: str | None = Query(None),
        squad_id: int | None = Query(None, alias="squadId"),
        iteration_id: int | None = Query(None, alias="iterationId"),
        fotmob_id: str | None = Query(None, alias="fotmobId"),
    ) -> JSONResponse:
        try:
            payload = build_player_cards_squad(
                club_name=club,
                season=season or DEFAULT_SEASON,
                league=league,
                squad_id=squad_id,
                iteration_id=iteration_id,
                fotmob_id=fotmob_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/player-cards/image-proxy")
    def player_cards_image_proxy(url: str = Query(...)) -> Response:
        """Same-origin proxy so print/PDF can lock the exact on-screen headshot."""
        token = str(url or "").strip()
        if not token.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Invalid image URL.")
        allowed_hosts = (
            "images.fotmob.com",
            "www.fotmob.com",
            "img.a.transfermarkt.technology",
            "tmssl.akamaized.net",
            "cdn.clubcast.co.uk",
            "portvale.co.uk",
            "www.portvale.co.uk",
        )
        from urllib.parse import urlparse

        host = (urlparse(token).hostname or "").lower()
        if not host or not any(host == h or host.endswith("." + h) for h in allowed_hosts):
            # Also allow our own absolute URLs
            if host not in {"178.128.161.215", "analysis.port-vale.co.uk", "localhost", "127.0.0.1"}:
                raise HTTPException(status_code=400, detail="Image host not allowed.")

        try:
            upstream = requests.get(
                token,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.fotmob.com/"},
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail="Could not fetch image.") from exc
        if upstream.status_code >= 400 or not upstream.content:
            raise HTTPException(status_code=502, detail="Image unavailable.")

        content_type = upstream.headers.get("Content-Type") or "image/jpeg"
        if "image" not in content_type and "octet-stream" not in content_type:
            raise HTTPException(status_code=502, detail="Upstream was not an image.")

        return Response(
            content=upstream.content,
            media_type=content_type.split(";")[0].strip(),
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.post("/api/player-cards/export-pdf")
    def player_cards_export_pdf_route(body: PlayerCardsExportRequest) -> Response:
        from app.main import _safe_export_filename, _save_export_to_desktop

        if not body.pages:
            raise HTTPException(status_code=400, detail="No export pages provided.")
        try:
            pdf_bytes = build_player_cards_export_pdf(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        club = re.sub(r"[^\w\s\-]+", "", str(body.club_name or "opponent"))
        club = re.sub(r"\s+", "-", club).strip("-") or "opponent"
        default_name = f"player-cards-{club}.pdf"
        filename = _safe_export_filename(body.filename or default_name, default_ext=".pdf")
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        saved_path = _save_export_to_desktop(pdf_bytes, filename)
        if saved_path is not None:
            headers["X-Saved-Desktop-Path"] = str(saved_path)
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
