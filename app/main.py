from __future__ import annotations

import base64
import binascii
import logging
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import register_auth
from app.label_utils import humanize_metric_label, humanize_profile_name
from app.profile_resolve import (
    FACTOR_SCORE_ALIASES,
    profile_match_tokens,
    resolve_factor_inverted,
    resolve_factor_label,
    resolve_factor_score_id,
    resolve_profile_definition,
)
from app.pdf_report import build_coach_report_pdf
from app.slide_export import build_coach_slides_pptx
from app.squad_photos import (
    fetch_photo_bytes,
    player_photo_available,
    resolve_local_photo_path,
    resolve_player_photo_url,
    save_local_player_photo,
)

load_dotenv()

logger = logging.getLogger("impect.dashboard")

# Ignore HTTP_PROXY/HTTPS_PROXY — Cursor/shell proxies often point at a dead local forwarder.
_http = requests.Session()
_http.trust_env = False

DEFAULT_POSITIONS = ["GOALKEEPER"]
ALLOWED_POSITIONS = (
    "GOALKEEPER",
    "LEFT_WINGBACK_DEFENDER",
    "RIGHT_WINGBACK_DEFENDER",
    "CENTRAL_DEFENDER",
    "DEFENSE_MIDFIELD",
    "CENTRAL_MIDFIELD",
    "ATTACKING_MIDFIELD",
    "LEFT_WINGER",
    "RIGHT_WINGER",
    "CENTER_FORWARD",
)
ALLOWED_COMPETITIONS = (
    "National League",
    "League One",
    "League Two",
    "Premier League 2",
    "Scottish Premiership",
    "Irish Premier Division",
)
BENCHMARK_COMPETITIONS = (
    "National League",
    "League Two",
    "Scottish Premiership",
)
BENCHMARK_MIN_MINUTES = 600
MAX_CHART_FACTORS = 7
MAX_BAR_FACTORS = 4  # drilldown bar grid is 2×2

POSITION_LABELS: dict[str, str] = {
    "GOALKEEPER": "Goalkeeper",
    "LEFT_WINGBACK_DEFENDER": "Left wing-back",
    "RIGHT_WINGBACK_DEFENDER": "Right wing-back",
    "CENTRAL_DEFENDER": "Centre-back",
    "DEFENSE_MIDFIELD": "Defensive midfield",
    "CENTRAL_MIDFIELD": "Central midfield",
    "ATTACKING_MIDFIELD": "Attacking midfield",
    "LEFT_WINGER": "Left winger",
    "RIGHT_WINGER": "Right winger",
    "CENTER_FORWARD": "Centre-forward",
}

POSITION_ABBREV: dict[str, str] = {
    "GOALKEEPER": "GK",
    "LEFT_WINGBACK_DEFENDER": "LWB",
    "RIGHT_WINGBACK_DEFENDER": "RWB",
    "CENTRAL_DEFENDER": "CB",
    "DEFENSE_MIDFIELD": "DM",
    "CENTRAL_MIDFIELD": "CM",
    "ATTACKING_MIDFIELD": "AM",
    "LEFT_WINGER": "LW",
    "RIGHT_WINGER": "RW",
    "CENTER_FORWARD": "CF",
}


@dataclass
class TokenCache:
    access_token: str = ""
    expires_at_epoch: float = 0.0


token_cache = TokenCache()
_players_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_benchmark_cache: dict[tuple[Any, ...], tuple[float, list[dict[str, Any]], dict[str, Any]]] = {}
_iteration_scores_cache: dict[tuple[Any, ...], tuple[float, list[dict[str, Any]]]] = {}
_last_n_iterations_cache: dict[tuple[Any, ...], tuple[float, list[int]]] = {}
_player_position_cache: dict[tuple[int, int, int], list[str]] = {}
_player_positions_scan_cache: dict[tuple[int, int, int, str], tuple[float, list[dict[str, Any]]]] = {}
_definitions_cache: dict[str, tuple[float, Any]] = {}
_squad_names_cache: dict[int, tuple[float, dict[int, str]]] = {}
_resolved_squad_cache: dict[tuple[str, int, int, str], int] = {}
_iterations_list_cache: tuple[float, list[dict[str, Any]]] | None = None
PLAYERS_CACHE_TTL_SECONDS = 3600
IMPECT_STALE_CACHE_TTL_SECONDS = 86400
CATALOG_SEARCH_SEASONS_PER_COMPETITION = 3
PLAYER_HISTORY_SEASONS_PER_COMPETITION = 4
POSITION_LOOKUP_MAX_SEASONS = 3
MAX_SEASON_LOOKBACK_FOR_LAST_N = 12
CACHE_VERSION = "5"
IMPECT_MAX_CONCURRENT_REQUESTS = 6

_impect_semaphore = threading.Semaphore(IMPECT_MAX_CONCURRENT_REQUESTS)
_impect_inflight_lock = threading.Lock()
_impect_inflight: dict[str, tuple[threading.Event, list[Any]]] = {}
_impect_stale_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_rate_limited_until: float = 0.0

ChartSource = Literal["metrics", "profiles"]


class ImpectQuery(BaseModel):
    iteration_ids: list[int] = Field(default_factory=list)
    competition_name: str | None = None
    positions: list[str] = Field(default_factory=list)
    min_games: float = 0
    player_key: str | None = None
    player_keys: list[str] = Field(default_factory=list)
    player_seasons: dict[str, list[int]] = Field(default_factory=dict)
    player_positions: dict[str, list[str]] = Field(default_factory=dict)
    player_catalog: dict[str, dict[str, Any]] = Field(default_factory=dict)
    independent_seasons: bool = False
    last_n_seasons: int | None = None
    chart_source: ChartSource = "profiles"


class PlayerCatalogRequest(BaseModel):
    competition_name: str | None = None
    search: str | None = None


class PlayerHistoryRequest(BaseModel):
    player_key: str
    player_catalog: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ChartRequest(ImpectQuery):
    player_name: str | None = None
    player_id: int | None = None
    profile: str | None = None
    profiles: list[str] = Field(default_factory=list)
    chart_source: ChartSource = "profiles"
    combine_seasons: bool = False
    include_drilldowns: bool = True
    drilldowns_only: bool = False


class PdfPlayerLine(BaseModel):
    player: str
    season_label: str = ""
    position_label: str = ""


class PdfDrilldownPlayer(BaseModel):
    player: str
    radar_values: list[float] = Field(default_factory=list)
    raw_values: list[float] = Field(default_factory=list)


class PdfDrilldown(BaseModel):
    profile: str
    labels: list[str] = Field(default_factory=list)
    players: list[PdfDrilldownPlayer] = Field(default_factory=list)


class PdfImageSection(BaseModel):
    title: str
    image_data: str


class PdfExportRequest(BaseModel):
    filename: str = "impect-report.pdf"
    generated_at: str = ""
    players: list[PdfPlayerLine] = Field(default_factory=list)
    benchmark_subtitle: str = ""
    profiles: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sections: list[PdfImageSection] = Field(default_factory=list)
    drilldowns: list[PdfDrilldown] = Field(default_factory=list)
    export_mode: str = "coach"


app = FastAPI(title="Impect Football Dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def pre_match_asset_no_cache(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/pre-match" or path.startswith("/pre-match/assets/") or path.startswith("/static/pre-match."):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


BASE_DIR = Path(__file__).resolve().parent.parent
register_auth(app, BASE_DIR / "standalone" / "login.html")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
PLAYER_PHOTOS_DIR = BASE_DIR / "static" / "player-photos"
PLAYER_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)


def _player_photo_api_url(name: str) -> str | None:
    if not player_photo_available(name):
        return None
    return f"/api/player-photo?name={quote(name)}"


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected server error occurred. Try again in a moment.",
        },
    )


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(
            status_code=500,
            detail=f"Missing environment variable: {name}",
        )
    return value


def get_access_token() -> str:
    now = time.time()
    if token_cache.access_token and now < token_cache.expires_at_epoch - 120:
        return token_cache.access_token

    token_url = _required_env("IMPECT_TOKEN_URL")
    username = _required_env("IMPECT_USERNAME")
    password = _required_env("IMPECT_PASSWORD")
    client_id = os.getenv("IMPECT_CLIENT_ID", "api")

    response = _http.post(
        token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_id": client_id,
            "grant_type": "password",
            "username": username,
            "password": password,
        },
        timeout=20,
    )
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Token request failed ({response.status_code}): {response.text}",
        )

    payload = response.json()
    access_token = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 3600))
    if not access_token:
        raise HTTPException(status_code=502, detail="Token response missing access_token")

    token_cache.access_token = access_token
    token_cache.expires_at_epoch = now + expires_in
    return access_token


def _resolve_url(endpoint: str) -> str:
    endpoint = endpoint.strip()
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    base_url = _required_env("IMPECT_BASE_URL").rstrip("/")
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return f"{base_url}{endpoint}"


def _api_prefix() -> str:
    return os.getenv("IMPECT_API_PREFIX", "customerapi").strip().strip("/")


def _scores_api_prefix() -> str:
    # Profile and player scores live on customerapi, not a separate scores host.
    return _api_prefix()


def _iterations_path() -> str:
    return f"/v5/{_api_prefix()}/iterations"


def _validate_positions(positions: list[str]) -> list[str]:
    cleaned = [position.strip().upper() for position in positions if position.strip()]
    invalid = [position for position in cleaned if position not in ALLOWED_POSITIONS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid position(s): {', '.join(invalid)}. "
                f"Choose from: {', '.join(ALLOWED_POSITIONS)}"
            ),
        )
    return cleaned


def _position_label(position: str) -> str:
    return POSITION_LABELS.get(position, position.replace("_", " ").title())


def _position_abbrev(position: str) -> str:
    return POSITION_ABBREV.get(position, position.replace("_", " ").title())


def _requested_positions_for_player(
    body: ImpectQuery,
    player_key: str,
) -> list[str]:
    per_player = body.player_positions.get(player_key, [])
    if per_player:
        return _validate_positions(per_player)
    if body.positions:
        return _validate_positions(body.positions)
    return []


def _positions_segment(positions: list[str]) -> str:
    cleaned = _validate_positions(positions) if positions else list(DEFAULT_POSITIONS)
    return ",".join(cleaned)


def _require_iterations(query: ImpectQuery) -> list[int]:
    if not query.iteration_ids:
        raise HTTPException(status_code=400, detail="Select at least one season/iteration")
    return query.iteration_ids


def _players_path(iteration_id: int) -> str:
    return f"/v5/{_api_prefix()}/iterations/{iteration_id}/players"


def _squads_path(iteration_id: int) -> str:
    return f"/v5/{_api_prefix()}/iterations/{iteration_id}/squads"


def _squad_scores_path(
    iteration_id: int, squad_id: int, positions: list[str], resource: str
) -> str:
    pos_segment = _positions_segment(positions)
    return (
        f"/v5/{_api_prefix()}/iterations/{iteration_id}/squads/{squad_id}"
        f"/positions/{pos_segment}/{resource}"
    )


def _impect_cache_key(path: str, params: dict[str, Any] | None) -> str:
  cleaned = tuple(sorted((key, str(value)) for key, value in (params or {}).items()))
  return f"{path}|{cleaned}"


def _impect_get_once(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    global _rate_limited_until
    access_token = get_access_token()
    url = _resolve_url(path)
    last_response: requests.Response | None = None
    cache_key = _impect_cache_key(path, params)

    for attempt in range(4):
        if time.time() < _rate_limited_until:
            time.sleep(min(2.0, _rate_limited_until - time.time()))
        try:
            with _impect_semaphore:
                response = _http.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params or {},
                    timeout=30,
                )
        except requests.RequestException as exc:
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise HTTPException(
                status_code=502,
                detail=f"Impect API unreachable: {exc}",
            ) from exc
        last_response = response
        if response.status_code == 429 and attempt < 3:
            retry_after = response.headers.get("Retry-After")
            if retry_after and str(retry_after).isdigit():
                delay = float(retry_after)
            else:
                delay = min(60.0, 5.0 * (2**attempt))
            _rate_limited_until = max(_rate_limited_until, time.time() + delay)
            time.sleep(delay)
            continue
        break

    assert last_response is not None
    if last_response.status_code == 429:
        stale = _impect_stale_cache.get(cache_key)
        if stale and time.time() - stale[0] < IMPECT_STALE_CACHE_TTL_SECONDS:
            payload = dict(stale[1])
            payload["stale"] = True
            return payload
        raise HTTPException(
            status_code=429,
            detail=(
                "Impect API rate limit reached — too many requests. "
                "Wait a few minutes, then hard-refresh and search again."
            ),
        )
    if last_response.status_code >= 400:
        raise HTTPException(
            status_code=last_response.status_code,
            detail=f"Impect API error: {last_response.text}",
        )
    try:
        payload_data = last_response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Impect API returned a non-JSON response.",
        ) from exc
    payload = {"url": url, "data": payload_data}
    _impect_stale_cache[cache_key] = (time.time(), payload)
    return payload


def _impect_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    cache_key = _impect_cache_key(path, params)
    with _impect_inflight_lock:
        inflight = _impect_inflight.get(cache_key)
        if inflight is not None:
            event, holder = inflight
            is_owner = False
        else:
            event = threading.Event()
            holder: list[Any] = [None, None]
            _impect_inflight[cache_key] = (event, holder)
            is_owner = True

    if not is_owner:
        if not event.wait(timeout=120):
            raise HTTPException(status_code=504, detail="Impect API request timed out.")
        if holder[1] is not None:
            raise holder[1]
        assert holder[0] is not None
        return holder[0]

    try:
        result = _impect_get_once(path, params)
        holder[0] = result
        return result
    except Exception as exc:
        holder[1] = exc
        raise
    finally:
        with _impect_inflight_lock:
            _impect_inflight.pop(cache_key, None)
        event.set()


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("items", "results", "data", "players"):
            maybe = payload.get(key)
            if isinstance(maybe, list):
                return [row for row in maybe if isinstance(row, dict)]
        return [payload]
    return []


def _extract_player_birthdate(player: dict[str, Any]) -> str | None:
    for key in ("birthdate", "birthDate", "dateOfBirth", "birth_date"):
        value = str(player.get(key, "")).strip()
        if value:
            return value
    return None


def _parse_birthdate(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned[:10], fmt).date()
        except ValueError:
            continue
    return None


def _player_age(player: dict[str, Any], ref: date | None = None) -> int | None:
    raw_age = player.get("age")
    if raw_age is not None:
        try:
            age = int(raw_age)
            if age > 0:
                return age
        except (TypeError, ValueError):
            pass

    birthdate = _extract_player_birthdate(player)
    if not birthdate:
        return None

    parsed = _parse_birthdate(birthdate)
    if parsed is None:
        return None

    today = ref or date.today()
    age = today.year - parsed.year
    if (today.month, today.day) < (parsed.month, parsed.day):
        age -= 1
    return age


def _extract_player_name(player: dict[str, Any]) -> str | None:
    common = str(player.get("commonname", "")).strip()
    if common:
        return common

    first = str(player.get("firstname", "")).strip()
    last = str(player.get("lastname", "")).strip()
    full = f"{first} {last}".strip()
    if full:
        return full

    for key in ("name", "playerName", "player_name", "athleteName"):
        value = str(player.get(key, "")).strip()
        if value:
            return value
    return None


def _player_key(name: str, player_id: int | None = None) -> str:
    normalized = name.lower().strip()
    if player_id is not None:
        return f"{normalized}|{player_id}"
    return normalized


def _extract_squad_id_from_player(player: dict[str, Any]) -> int | None:
    for key in ("squadId", "squad_id", "currentSquadId"):
        value = player.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue

    squads = player.get("squads")
    if isinstance(squads, list) and squads:
        first = squads[0]
        if isinstance(first, dict):
            squad_id = first.get("id")
            if squad_id is not None:
                return int(squad_id)
        else:
            try:
                return int(first)
            except (TypeError, ValueError):
                pass
    return None


def _squad_id_from_score_row(row: dict[str, Any]) -> int | None:
    for key in ("_squadId", "squadId", "squad_id"):
        value = row.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _annotate_score_rows_with_squad(
    rows: list[dict[str, Any]], squad_id: int
) -> list[dict[str, Any]]:
    for row in rows:
        if _squad_id_from_score_row(row) is None:
            row["_squadId"] = squad_id
    return rows


def _find_player_squad_in_iteration(
    iteration_id: int,
    player_id: int,
    player_name: str,
    chart_source: ChartSource = "metrics",
    *,
    skip_squad_id: int | None = None,
) -> int | None:
    """Find squad holding a player's scores — one squad at a time, not a full-iteration pull."""
    cache_key = (CACHE_VERSION, iteration_id, player_id, chart_source)
    cached = _resolved_squad_cache.get(cache_key)
    if cached is not None:
        return None if cached < 0 else cached

    fetch_squad = (
        _fetch_profile_scores if chart_source == "profiles" else _fetch_player_scores
    )
    for squad_id in _fetch_squad_ids(iteration_id):
        if skip_squad_id is not None and squad_id == skip_squad_id:
            continue
        try:
            score_rows, _ = fetch_squad(
                iteration_id, squad_id, list(ALLOWED_POSITIONS), 0
            )
            if _pick_score_row(score_rows, player_id, player_name, {}) is not None:
                _resolved_squad_cache[cache_key] = squad_id
                return squad_id
        except HTTPException as exc:
            if exc.status_code == 429:
                raise
            if exc.status_code not in {404, 403}:
                raise

    _resolved_squad_cache[cache_key] = -1
    return None


def _resolve_squad_id_for_player(
    iteration_id: int,
    player_id: int,
    player_name: str,
    hint_squad_id: int | None = None,
    chart_source: ChartSource = "metrics",
) -> int | None:
    cache_key = (CACHE_VERSION, iteration_id, player_id, chart_source)
    cached = _resolved_squad_cache.get(cache_key)
    if cached is not None and cached > 0:
        return cached

    fetch_squad = (
        _fetch_profile_scores if chart_source == "profiles" else _fetch_player_scores
    )
    if hint_squad_id is not None:
        try:
            score_rows, _ = fetch_squad(
                iteration_id, hint_squad_id, list(ALLOWED_POSITIONS), 0
            )
            if _pick_score_row(score_rows, player_id, player_name, {}) is not None:
                _resolved_squad_cache[cache_key] = hint_squad_id
                return hint_squad_id
        except HTTPException as exc:
            if exc.status_code == 429:
                raise
            if exc.status_code not in {404, 403}:
                raise

    return _find_player_squad_in_iteration(
        iteration_id,
        player_id,
        player_name,
        chart_source,
        skip_squad_id=hint_squad_id,
    )


def _latest_iteration_id_for_option(
    option: dict[str, Any],
    iteration_meta: dict[int, dict[str, str]] | None = None,
) -> int | None:
    ids_by_iteration = option.get("ids_by_iteration", {})
    if not ids_by_iteration:
        return None
    meta = iteration_meta or _iteration_meta_map()
    return max(
        (int(iteration_id_str) for iteration_id_str in ids_by_iteration),
        key=lambda iteration_id: _season_sort_key(
            meta.get(iteration_id, {}).get("season", "")
        ),
    )


def _resolve_squad_ids_for_option(
    option: dict[str, Any],
    *,
    iteration_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Resolve squads only for requested iterations (defaults to latest season)."""
    name = str(option.get("name", "")).strip()
    squads = dict(option.get("squad_ids_by_iteration", {}))
    ids_by_iteration = option.get("ids_by_iteration", {})
    if not ids_by_iteration:
        return option

    if iteration_ids is None:
        latest = _latest_iteration_id_for_option(option)
        iteration_ids = [latest] if latest is not None else []

    for iteration_id in iteration_ids:
        iteration_id_str = str(iteration_id)
        player_id = ids_by_iteration.get(iteration_id_str)
        if player_id is None:
            continue
        hint = squads.get(iteration_id_str)
        hint_int = int(hint) if hint is not None else None
        resolved = _resolve_squad_id_for_player(
            iteration_id,
            int(player_id),
            name,
            hint_int,
        )
        if resolved is not None:
            squads[iteration_id_str] = resolved
    option["squad_ids_by_iteration"] = squads
    return option


def _resolve_player_catalog_option(
    player_key: str,
    options_by_key: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    if player_key in options_by_key:
        return options_by_key[player_key], None

    if "|" in player_key:
        return None, f"Player '{player_key}' not found in Impect catalog."

    normalized = player_key.lower().strip()
    matches = [
        option
        for option in options_by_key.values()
        if str(option.get("name", "")).lower().strip() == normalized
    ]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        labels = ", ".join(
            str(match.get("label") or match.get("name", player_key)) for match in matches
        )
        return (
            None,
            f"Ambiguous player '{player_key}' — select a specific match: {labels}",
        )
    return None, f"Player '{player_key}' not found in Impect catalog."


def _player_label_name(player: dict[str, Any]) -> str:
    name = str(player.get("name", "")).strip()
    age = player.get("age")
    if age is not None:
        return f"{name} ({age})"
    return name


def _iteration_label(row: dict[str, Any]) -> str:
    competition = row.get("competition")
    competition_name = "Unknown competition"
    if isinstance(competition, dict):
        competition_name = str(competition.get("name", competition_name)).strip()
    season = str(row.get("season", "")).strip()
    if season:
        return f"{competition_name} — {season}"
    return competition_name


def _fetch_iterations() -> list[dict[str, Any]]:
    global _iterations_list_cache
    now = time.time()
    if (
        _iterations_list_cache is not None
        and now - _iterations_list_cache[0] < PLAYERS_CACHE_TTL_SECONDS
    ):
        return _iterations_list_cache[1]

    raw = _impect_get(_iterations_path())
    rows = _extract_rows(raw["data"])
    options: list[dict[str, Any]] = []
    for row in rows:
        iteration_id = row.get("id")
        if iteration_id is None:
            continue
        competition_name = (
            str((row.get("competition") or {}).get("name", "")).strip()
            if isinstance(row.get("competition"), dict)
            else ""
        )
        if competition_name not in ALLOWED_COMPETITIONS:
            continue
        options.append(
            {
                "id": int(iteration_id),
                "label": _iteration_label(row),
                "season": str(row.get("season", "")).strip(),
                "competition_name": competition_name,
            }
        )
    options.sort(key=lambda item: (item["competition_name"], item["season"]), reverse=True)
    _iterations_list_cache = (time.time(), options)
    return options


def _iteration_label_map(iteration_ids: list[int]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for row in _fetch_iterations():
        if row["id"] in iteration_ids:
            labels[row["id"]] = row["label"]
    for iteration_id in iteration_ids:
        labels.setdefault(iteration_id, f"Season {iteration_id}")
    return labels


def _fetch_players_for_iteration(iteration_id: int) -> list[dict[str, Any]]:
    now = time.time()
    cached = _players_cache.get(iteration_id)
    if cached and now - cached[0] < PLAYERS_CACHE_TTL_SECONDS:
        return cached[1]

    raw = _impect_get(_players_path(iteration_id))
    players = _extract_rows(raw["data"])
    _players_cache[iteration_id] = (now, players)
    return players


def _fetch_players_parallel(iteration_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    results: dict[int, list[dict[str, Any]]] = {}
    if not iteration_ids:
        return results

    max_workers = min(IMPECT_MAX_CONCURRENT_REQUESTS, len(iteration_ids))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_players_for_iteration, iteration_id): iteration_id
            for iteration_id in iteration_ids
        }
        for future in as_completed(futures):
            iteration_id = futures[future]
            results[iteration_id] = future.result()
    return results


def _season_sort_key(season: str) -> tuple[int, str]:
    token = season.split("/")[0].strip()
    if token.isdigit():
        year = int(token)
        if year < 100:
            year += 2000
        return year, season
    return 0, season


def _iteration_meta_map() -> dict[int, dict[str, str]]:
    meta: dict[int, dict[str, str]] = {}
    for row in _fetch_iterations():
        meta[row["id"]] = {
            "label": row["label"],
            "season": row["season"],
            "competition_name": row["competition_name"],
        }
    return meta


def _player_catalog_ids() -> list[int]:
    return [item["id"] for item in _fetch_iterations()]


def _latest_iteration_ids(
    iterations: list[dict[str, Any]],
    *,
    seasons_per_competition: int = CATALOG_SEARCH_SEASONS_PER_COMPETITION,
) -> list[int]:
    by_competition: dict[str, list[dict[str, Any]]] = {}
    for item in iterations:
        competition_name = item.get("competition_name", "")
        if competition_name not in ALLOWED_COMPETITIONS:
            continue
        by_competition.setdefault(competition_name, []).append(item)

    iteration_ids: list[int] = []
    for items in by_competition.values():
        items.sort(
            key=lambda row: _season_sort_key(str(row.get("season", ""))),
            reverse=True,
        )
        iteration_ids.extend(
            int(item["id"])
            for item in items[:seasons_per_competition]
            if item.get("id") is not None
        )
    return iteration_ids


def _search_name_variants(search: str) -> list[str]:
    lowered = search.lower().strip()
    variants = [lowered]
    if "elliott" in lowered:
        variants.append(lowered.replace("elliott", "elliot"))
    elif "elliot" in lowered:
        variants.append(lowered.replace("elliot", "elliott"))
    return variants


def _player_matches_search(name: str, search: str) -> bool:
    name_lower = name.lower()
    return any(variant in name_lower for variant in _search_name_variants(search))


def _catalog_iteration_ids(competition_name: str | None, search: str | None) -> list[int]:
    iterations = _fetch_iterations()
    if competition_name:
        if competition_name not in ALLOWED_COMPETITIONS:
            return []
        return [
            item["id"]
            for item in iterations
            if item.get("competition_name") == competition_name
        ]
    if search:
        return _latest_iteration_ids(iterations)
    return []


def _fetch_squad_names(iteration_id: int) -> dict[int, str]:
    now = time.time()
    cached = _squad_names_cache.get(iteration_id)
    if cached and now - cached[0] < PLAYERS_CACHE_TTL_SECONDS:
        return cached[1]

    raw = _impect_get(_squads_path(iteration_id))
    names: dict[int, str] = {}
    for row in _extract_rows(raw["data"]):
        squad_id = row.get("id")
        if squad_id is None:
            continue
        squad_name = str(row.get("name", "")).strip()
        if squad_name:
            names[int(squad_id)] = squad_name
    _squad_names_cache[iteration_id] = (now, names)
    return names


def _enrich_player_label(
    player: dict[str, Any],
    iteration_meta: dict[int, dict[str, str]],
    squad_names_by_iteration: dict[int, dict[int, str]] | None = None,
) -> dict[str, Any]:
    context_comp = ""
    context_club = ""

    chartable_seasons = sorted(
        (
            season
            for season in player.get("seasons", [])
            if season.get("chartable")
        ),
        key=lambda item: (
            _season_sort_key(item.get("season", "")),
            item.get("label", ""),
        ),
        reverse=True,
    )

    for season in chartable_seasons:
        iteration_id = season["iteration_id"]
        squad_id = player.get("squad_ids_by_iteration", {}).get(str(iteration_id))
        if squad_id is None:
            continue
        if squad_names_by_iteration is None:
            club = _fetch_squad_names(iteration_id).get(int(squad_id), "")
        else:
            club = squad_names_by_iteration.get(iteration_id, {}).get(int(squad_id), "")
        if club:
            context_club = club
            context_comp = season.get("competition_name", "") or iteration_meta.get(
                iteration_id, {}
            ).get("competition_name", "")
            break

    if not context_club:
        for iteration_id_str, squad_id in player.get("squad_ids_by_iteration", {}).items():
            iteration_id = int(iteration_id_str)
            if squad_names_by_iteration is None:
                club = _fetch_squad_names(iteration_id).get(int(squad_id), "")
            else:
                club = squad_names_by_iteration.get(iteration_id, {}).get(int(squad_id), "")
            if club:
                context_club = club
                context_comp = iteration_meta.get(iteration_id, {}).get("competition_name", "")
                break

    if player.get("age") is None and player.get("birthdate"):
        derived_age = _player_age({"birthdate": player["birthdate"]})
        if derived_age is not None:
            player["age"] = derived_age

    birthdate = player.get("birthdate")
    if birthdate:
        player["birthDate"] = birthdate

    name_part = _player_label_name(player)
    context = " · ".join(part for part in (context_comp, context_club) if part)
    if context:
        player["label"] = f"{name_part} — {context}"
    else:
        impect_player_id = player.get("impect_player_id")
        if impect_player_id is not None:
            player["label"] = f"{name_part} (ID {impect_player_id})"
        else:
            player["label"] = name_part

    player["club"] = context_club
    player["league"] = context_comp
    return player


def _catalog_squad_names(players: list[dict[str, Any]]) -> dict[int, dict[int, str]]:
    iteration_ids: set[int] = set()
    for player in players:
        for iteration_id_str in player.get("squad_ids_by_iteration", {}):
            iteration_ids.add(int(iteration_id_str))
    return {iteration_id: _fetch_squad_names(iteration_id) for iteration_id in iteration_ids}


def _all_allowed_iteration_ids() -> list[int]:
    return [
        int(item["id"])
        for item in _fetch_iterations()
        if item.get("competition_name") in ALLOWED_COMPETITIONS and item.get("id") is not None
    ]


def _expand_player_history(
    player_option: dict[str, Any],
    iteration_meta: dict[int, dict[str, str]] | None = None,
    *,
    max_squad_resolve: int = 8,
) -> dict[str, Any]:
    """Attach every allowed-competition season where this Impect player appears."""
    impect_player_id = player_option.get("impect_player_id")
    if impect_player_id is None:
        return player_option

    ids_by_iteration = dict(player_option.get("ids_by_iteration", {}))
    squads = dict(player_option.get("squad_ids_by_iteration", {}))
    recent_ids = _latest_iteration_ids(
        _fetch_iterations(),
        seasons_per_competition=PLAYER_HISTORY_SEASONS_PER_COMPETITION,
    )
    missing_ids = [
        iteration_id
        for iteration_id in recent_ids
        if str(iteration_id) not in ids_by_iteration
    ]

    if missing_ids:
        players_by_iteration = _fetch_players_parallel(missing_ids)
        target_id = int(impect_player_id)
        for iteration_id in missing_ids:
            for player in players_by_iteration.get(iteration_id, []):
                player_id = player.get("id")
                if player_id is None or int(player_id) != target_id:
                    continue
                ids_by_iteration[str(iteration_id)] = target_id
                break

    player_option["ids_by_iteration"] = ids_by_iteration
    player_option["squad_ids_by_iteration"] = squads
    if ids_by_iteration:
        meta = iteration_meta or _iteration_meta_map()
        resolve_ids = sorted(
            (int(iteration_id_str) for iteration_id_str in ids_by_iteration),
            key=lambda iteration_id: _season_sort_key(
                meta.get(iteration_id, {}).get("season", "")
            ),
            reverse=True,
        )[:max_squad_resolve]
        _resolve_squad_ids_for_option(player_option, iteration_ids=resolve_ids)
    return player_option


def _enrich_player_catalog(
    players: list[dict[str, Any]],
    label_map: dict[int, str],
    iteration_meta: dict[int, dict[str, str]],
    *,
    expand_history: bool = True,
) -> list[dict[str, Any]]:
    expanded = players
    if expand_history:
        expanded = [_expand_player_history(player, iteration_meta) for player in players]
    squad_names = _catalog_squad_names(expanded)
    enriched = [
        _enrich_player_seasons(player, label_map, iteration_meta, squad_names)
        for player in expanded
    ]
    return [
        _enrich_player_label(player, iteration_meta, squad_names)
        for player in enriched
    ]


def _enrich_player_seasons(
    player: dict[str, Any],
    label_map: dict[int, str],
    iteration_meta: dict[int, dict[str, str]],
    squad_names_by_iteration: dict[int, dict[int, str]] | None = None,
) -> dict[str, Any]:
    seasons: list[dict[str, Any]] = []
    for iteration_id_str in player["ids_by_iteration"]:
        iteration_id = int(iteration_id_str)
        squad_id = player.get("squad_ids_by_iteration", {}).get(iteration_id_str)
        meta = iteration_meta.get(iteration_id, {})
        season = meta.get("season", "")
        display_label = label_map.get(iteration_id, f"Season {iteration_id}")
        club = ""
        if squad_id is not None and squad_names_by_iteration is not None:
            club = squad_names_by_iteration.get(iteration_id, {}).get(int(squad_id), "")
        if club:
            display_label = f"{display_label} · {club}"
        seasons.append(
            {
                "iteration_id": iteration_id,
                "label": display_label,
                "season": season,
                "competition_name": meta.get("competition_name", ""),
                "club": club,
                "chartable": squad_id is not None,
            }
        )
    seasons.sort(
        key=lambda item: (_season_sort_key(item.get("season", "")), item["label"]),
        reverse=True,
    )
    player["seasons"] = seasons
    player["chartable_season_ids"] = [
        season["iteration_id"] for season in seasons if season["chartable"]
    ]
    return player


def _merge_player_options(
    iteration_ids: list[int], players_by_iteration: dict[int, list[dict[str, Any]]] | None = None
) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for iteration_id in iteration_ids:
        players = (
            players_by_iteration.get(iteration_id, [])
            if players_by_iteration is not None
            else _fetch_players_for_iteration(iteration_id)
        )
        for player in players:
            name = _extract_player_name(player)
            player_id = player.get("id")
            if not name or player_id is None:
                continue
            impect_player_id = int(player_id)
            if impect_player_id not in merged:
                merged[impect_player_id] = {
                    "key": _player_key(name, impect_player_id),
                    "name": name,
                    "impect_player_id": impect_player_id,
                    "ids_by_iteration": {},
                    "squad_ids_by_iteration": {},
                }
            birthdate = _extract_player_birthdate(player)
            if birthdate and not merged[impect_player_id].get("birthdate"):
                merged[impect_player_id]["birthdate"] = birthdate
                merged[impect_player_id]["birthDate"] = birthdate
            age = _player_age(player)
            if age is not None:
                existing_age = merged[impect_player_id].get("age")
                if existing_age is None or age > existing_age:
                    merged[impect_player_id]["age"] = age
            merged[impect_player_id]["ids_by_iteration"][str(iteration_id)] = impect_player_id
            squad_id = _extract_squad_id_from_player(player)
            if squad_id is not None:
                merged[impect_player_id]["squad_ids_by_iteration"][str(iteration_id)] = squad_id
    options = list(merged.values())
    options.sort(key=lambda item: (item["name"].lower(), item.get("impect_player_id", 0)))
    return options


def _player_name_map(players: list[dict[str, Any]]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for player in players:
        player_id = player.get("id")
        name = _extract_player_name(player)
        if player_id is not None and name:
            mapping[int(player_id)] = name
    return mapping


def _season_for_iteration(iteration_id: int) -> str:
    for row in _fetch_iterations():
        if row["id"] == iteration_id:
            return row.get("season", "")
    return ""


def _iterations_for_benchmark_season(season: str) -> list[int]:
    if not season:
        return []
    return [
        item["id"]
        for item in _fetch_iterations()
        if item.get("season") == season
        and item.get("competition_name") in BENCHMARK_COMPETITIONS
    ]


def _play_duration_minutes(row: dict[str, Any]) -> float | None:
    raw = _to_number(row.get("playDuration"))
    if raw is None:
        return None
    if raw >= 1000:
        return float(round(raw / 60.0))
    return float(round(raw))


def _meets_benchmark_minutes(row: dict[str, Any], min_minutes: float) -> bool:
    minutes = _play_duration_minutes(row)
    return minutes is not None and minutes >= min_minutes


def _low_minutes_warning(row: dict[str, Any], min_minutes: float) -> str | None:
    minutes = _play_duration_minutes(row)
    if minutes is None:
        return f"No minutes data available (benchmark uses {min_minutes:.0f}+ minutes)."
    if minutes < min_minutes:
        return (
            f"Low data: {minutes:.0f} minutes played "
            f"(cross-league benchmark requires {min_minutes:.0f}+ minutes)."
        )
    return None


def _fetch_benchmark_cohort(
    season: str,
    positions: list[str],
    chart_source: ChartSource,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache_key = ("benchmark", CACHE_VERSION, chart_source, season, tuple(positions), BENCHMARK_MIN_MINUTES)
    cached = _benchmark_cache.get(cache_key)
    if cached and time.time() - cached[0] < PLAYERS_CACHE_TTL_SECONDS:
        return cached[1], cached[2]

    iteration_ids = _iterations_for_benchmark_season(season)
    merged: list[dict[str, Any]] = []
    fetch_scores = (
        _fetch_iteration_profile_scores
        if chart_source == "profiles"
        else _fetch_iteration_player_scores
    )

    for iteration_id in iteration_ids:
        merged.extend(fetch_scores(iteration_id, positions, 0))

    eligible = [
        row for row in merged if _meets_benchmark_minutes(row, BENCHMARK_MIN_MINUTES)
    ]
    meta = {
        "season": season,
        "competitions": list(BENCHMARK_COMPETITIONS),
        "min_minutes": BENCHMARK_MIN_MINUTES,
        "cohort_size": len(eligible),
        "players_scanned": len(merged),
        "iterations_scanned": len(iteration_ids),
    }
    _benchmark_cache[cache_key] = (time.time(), eligible, meta)
    return eligible, meta


def _fetch_squad_ids(iteration_id: int) -> list[int]:
    raw = _impect_get(_squads_path(iteration_id))
    rows = _extract_rows(raw["data"])
    squad_ids: list[int] = []
    for row in rows:
        if row.get("access") is False:
            continue
        squad_id = row.get("id")
        if squad_id is not None:
            squad_ids.append(int(squad_id))
    return squad_ids


def _fetch_iteration_profile_scores(
    iteration_id: int,
    positions: list[str],
    min_games: float,
) -> list[dict[str, Any]]:
    cache_key = ("profiles", CACHE_VERSION, iteration_id, tuple(positions), min_games)
    cached = _iteration_scores_cache.get(cache_key)
    if cached and time.time() - cached[0] < PLAYERS_CACHE_TTL_SECONDS:
        return cached[1]

    squad_ids = _fetch_squad_ids(iteration_id)
    merged: list[dict[str, Any]] = []

    def load_squad(squad_id: int) -> list[dict[str, Any]]:
        try:
            rows, _ = _fetch_profile_scores(iteration_id, squad_id, positions, min_games)
            return _annotate_score_rows_with_squad(rows, squad_id)
        except HTTPException:
            return []

    max_workers = min(2, max(len(squad_ids), 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(load_squad, squad_id) for squad_id in squad_ids]
        for future in as_completed(futures):
            merged.extend(future.result())

    _iteration_scores_cache[cache_key] = (time.time(), merged)
    return merged


def _fetch_iteration_player_scores(
    iteration_id: int,
    positions: list[str],
    min_games: float,
) -> list[dict[str, Any]]:
    cache_key = ("metrics", CACHE_VERSION, iteration_id, tuple(positions), min_games)
    cached = _iteration_scores_cache.get(cache_key)
    if cached and time.time() - cached[0] < PLAYERS_CACHE_TTL_SECONDS:
        return cached[1]

    squad_ids = _fetch_squad_ids(iteration_id)
    merged: list[dict[str, Any]] = []

    def load_squad(squad_id: int) -> list[dict[str, Any]]:
        try:
            rows, _ = _fetch_player_scores(iteration_id, squad_id, positions, min_games)
            return _annotate_score_rows_with_squad(rows, squad_id)
        except HTTPException:
            return []

    max_workers = min(2, max(len(squad_ids), 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(load_squad, squad_id) for squad_id in squad_ids]
        for future in as_completed(futures):
            merged.extend(future.result())

    _iteration_scores_cache[cache_key] = (time.time(), merged)
    return merged


def _fetch_profile_scores(
    iteration_id: int,
    squad_id: int,
    positions: list[str],
    min_games: float,
) -> tuple[list[dict[str, Any]], str]:
    params: dict[str, Any] = {}
    if min_games:
        params["minGames"] = min_games
    raw = _impect_get(
        _squad_scores_path(iteration_id, squad_id, positions, "player-profile-scores"),
        params=params,
    )
    return _extract_rows(raw["data"]), raw["url"]


def _fetch_player_scores(
    iteration_id: int,
    squad_id: int,
    positions: list[str],
    min_games: float,
) -> tuple[list[dict[str, Any]], str]:
    params: dict[str, Any] = {}
    if min_games:
        params["minGames"] = min_games
    raw = _impect_get(
        _squad_scores_path(iteration_id, squad_id, positions, "player-scores"),
        params=params,
    )
    return _extract_rows(raw["data"]), raw["url"]


def _score_url_for_position(
    iteration_id: int,
    position: str,
    chart_source: ChartSource,
) -> str:
    score_kind = "player-profile-scores" if chart_source == "profiles" else "player-scores"
    return (
        f"https://api.impect.com/v5/customerapi/iterations/{iteration_id}"
        f"/positions/{position}/{score_kind}"
    )


def _scan_single_position_for_player(
    iteration_id: int,
    player_id: int,
    squad_id: int | None,
    player_name: str,
    name_map: dict[int, str],
    chart_source: ChartSource,
    position: str,
    min_games: float,
) -> dict[str, Any] | None:
    fetch_squad = (
        _fetch_profile_scores if chart_source == "profiles" else _fetch_player_scores
    )
    row: dict[str, Any] | None = None
    scores_url = _score_url_for_position(iteration_id, position, chart_source)

    if squad_id is not None:
        try:
            score_rows, squad_url = fetch_squad(
                iteration_id, squad_id, [position], min_games
            )
            row = _pick_score_row(score_rows, player_id, player_name, name_map)
            if row is not None:
                scores_url = squad_url
        except HTTPException as exc:
            if exc.status_code not in {404, 403}:
                raise

    # Squad already resolved: no row at this position means the player did not play there.
    # Do not scan every squad in the iteration (that was causing 30s+ hangs per player).
    if row is None and squad_id is None:
        other_squad = _find_player_squad_in_iteration(
            iteration_id,
            player_id,
            player_name,
            chart_source,
        )
        if other_squad is not None:
            try:
                score_rows, squad_url = fetch_squad(
                    iteration_id, other_squad, [position], min_games
                )
                row = _pick_score_row(score_rows, player_id, player_name, name_map)
                if row is not None:
                    scores_url = squad_url
            except HTTPException as exc:
                if exc.status_code not in {404, 403, 429}:
                    raise
                if exc.status_code == 429:
                    raise

    if row is None:
        return None

    minutes = _play_duration_minutes(row) or 0.0
    return {
        "position": position,
        "label": _position_label(position),
        "minutes": minutes,
        "row": row,
        "scores_url": scores_url,
    }


def _position_row_for_player(
    score_rows: list[dict[str, Any]],
    player_id: int,
    player_name: str,
    name_map: dict[int, str],
    position: str,
    scores_url: str,
) -> dict[str, Any] | None:
    row = _pick_score_row(score_rows, player_id, player_name, name_map)
    if row is None:
        return None
    minutes = _play_duration_minutes(row) or 0.0
    if minutes <= 0:
        return None
    return {
        "position": position,
        "label": _position_label(position),
        "minutes": minutes,
        "row": row,
        "scores_url": scores_url,
    }


def _scan_positions_for_player(
    iteration_id: int,
    player_id: int,
    squad_id: int | None,
    player_name: str,
    name_map: dict[int, str],
    chart_source: ChartSource,
    min_games: float = 0,
) -> list[dict[str, Any]]:
    effective_squad = squad_id
    resolved_squad = _resolve_squad_id_for_player(
        iteration_id,
        player_id,
        player_name,
        squad_id,
        chart_source,
    )
    if resolved_squad is not None:
        effective_squad = resolved_squad

    cache_key = (CACHE_VERSION, iteration_id, player_id, effective_squad or 0, chart_source)
    cached = _player_positions_scan_cache.get(cache_key)
    if cached and time.time() - cached[0] < PLAYERS_CACHE_TTL_SECONDS:
        return cached[1]

    fetch_squad = (
        _fetch_profile_scores if chart_source == "profiles" else _fetch_player_scores
    )
    results: list[dict[str, Any]] = []

    if effective_squad is not None:
        for position in ALLOWED_POSITIONS:
            try:
                score_rows, scores_url = fetch_squad(
                    iteration_id,
                    effective_squad,
                    [position],
                    min_games,
                )
            except HTTPException as exc:
                if exc.status_code in {404, 403}:
                    continue
                if exc.status_code == 429:
                    stale = _player_positions_scan_cache.get(cache_key)
                    if stale:
                        return stale[1]
                raise
            item = _position_row_for_player(
                score_rows,
                player_id,
                player_name,
                name_map,
                position,
                scores_url,
            )
            if item is not None:
                results.append(item)
    else:
        for position in ALLOWED_POSITIONS:
            item = _scan_single_position_for_player(
                iteration_id,
                player_id,
                effective_squad,
                player_name,
                name_map,
                chart_source,
                position,
                min_games,
            )
            if item is not None:
                results.append(item)

    results.sort(
        key=lambda item: (
            -float(item["minutes"]),
            ALLOWED_POSITIONS.index(item["position"]),
        )
    )
    _player_positions_scan_cache[cache_key] = (time.time(), results)
    return results


def _find_player_score_row(
    iteration_id: int,
    player_id: int,
    squad_id: int | None,
    player_name: str,
    name_map: dict[int, str],
    chart_source: ChartSource,
    requested_positions: list[str],
    min_games: float = 0,
) -> tuple[dict[str, Any] | None, list[str], str]:
    if requested_positions:
        positions_to_try = _validate_positions(requested_positions)
        fetch_squad = (
            _fetch_profile_scores if chart_source == "profiles" else _fetch_player_scores
        )

        squads_to_try: list[int] = []
        if squad_id is not None:
            squads_to_try.append(squad_id)
        resolved_squad = _find_player_squad_in_iteration(
            iteration_id,
            player_id,
            player_name,
            chart_source,
            skip_squad_id=squad_id,
        )
        if resolved_squad is not None and resolved_squad not in squads_to_try:
            squads_to_try.append(resolved_squad)

        for active_squad in squads_to_try:
            for position in positions_to_try:
                try:
                    score_rows, scores_url = fetch_squad(
                        iteration_id, active_squad, [position], min_games
                    )
                except HTTPException as exc:
                    if exc.status_code in {404, 403}:
                        continue
                    raise
                selected = _pick_score_row(score_rows, player_id, player_name, name_map)
                if selected is not None:
                    _player_position_cache[(iteration_id, active_squad, player_id)] = [position]
                    return selected, [position], scores_url

        return None, [], ""

    scanned = _scan_positions_for_player(
        iteration_id,
        player_id,
        squad_id,
        player_name,
        name_map,
        chart_source,
        min_games,
    )
    if not scanned:
        return None, [], ""

    best = scanned[0]
    position = str(best["position"])
    cache_key = (iteration_id, squad_id or 0, player_id)
    _player_position_cache[cache_key] = [position]
    return best["row"], [position], str(best.get("scores_url", ""))


def _resolve_positions_for_player(
    iteration_id: int,
    squad_id: int,
    player_id: int,
    requested_positions: list[str],
    chart_source: ChartSource,
    player_name: str = "",
    name_map: dict[int, str] | None = None,
) -> list[str]:
    if requested_positions:
        return _validate_positions(requested_positions)

    cache_key = (iteration_id, squad_id, player_id)
    cached = _player_position_cache.get(cache_key)
    if cached:
        return cached

    scanned = _scan_positions_for_player(
        iteration_id,
        player_id,
        squad_id,
        player_name,
        name_map or {},
        chart_source,
        0,
    )
    if not scanned:
        raise HTTPException(
            status_code=404,
            detail="No score data found for this player at any Impect position.",
        )

    resolved = [str(scanned[0]["position"])]
    _player_position_cache[cache_key] = resolved
    return resolved


def _extract_profile_names(score_rows: list[dict[str, Any]]) -> list[str]:
    names: set[str] = set()
    for row in score_rows:
        for profile_score in row.get("profileScores", []):
            if not isinstance(profile_score, dict):
                continue
            profile_name = _normalize_profile_name(profile_score.get("profileName"))
            if profile_name and _is_pv_profile(profile_name):
                names.add(profile_name)
    return sorted(names)


def _profile_scores_for_player(row: dict[str, Any]) -> list[dict[str, Any]]:
    scores = row.get("profileScores", [])
    if not isinstance(scores, list):
        return []
    return [score for score in scores if isinstance(score, dict)]


def _player_scores_for_player(row: dict[str, Any]) -> list[dict[str, Any]]:
    scores = row.get("playerScores", [])
    if not isinstance(scores, list):
        return []
    return [score for score in scores if isinstance(score, dict)]


def _player_has_score_data(
    iteration_id: int,
    player_id: int,
    squad_id: int | None,
    player_name: str,
    chart_source: ChartSource,
) -> bool:
    """Lightweight score check — one squad call with all positions, not a full position scan."""
    fetch_squad = (
        _fetch_profile_scores if chart_source == "profiles" else _fetch_player_scores
    )

    if squad_id is not None:
        try:
            score_rows, _ = fetch_squad(
                iteration_id, squad_id, list(ALLOWED_POSITIONS), 0
            )
            if _pick_score_row(score_rows, player_id, player_name, {}) is not None:
                return True
        except HTTPException as exc:
            if exc.status_code not in {404, 403}:
                raise

    return (
        _find_player_squad_in_iteration(
            iteration_id,
            player_id,
            player_name,
            chart_source,
            skip_squad_id=squad_id,
        )
        is not None
    )


def _pick_score_row(
    score_rows: list[dict[str, Any]],
    player_id: int | None,
    player_name: str | None,
    name_map: dict[int, str],
) -> dict[str, Any] | None:
    if not score_rows:
        return None

    if player_id is not None:
        for row in score_rows:
            if row.get("playerId") == player_id:
                return row

    if player_name:
        lowered = player_name.lower().strip()
        for row in score_rows:
            row_id = row.get("playerId")
            mapped_name = name_map.get(int(row_id)) if row_id is not None else None
            if mapped_name and lowered in mapped_name.lower():
                return row

    return None


def _normalize_profile_name(name: Any) -> str:
    return str(name or "").strip()


def _is_pv_profile(name: Any) -> bool:
    return _normalize_profile_name(name).upper().startswith("PV")


def _score_key_matches(key_name: str, score_value: Any, key_value: Any) -> bool:
    if key_name == "profileName":
        return _normalize_profile_name(score_value) == _normalize_profile_name(key_value)
    return score_value == key_value


def _cohort_values_for_key(
    score_rows: list[dict[str, Any]],
    key_name: str,
    key_value: Any,
    scores_field: str,
) -> list[float]:
    values: list[float] = []
    for row in score_rows:
        scores = row.get(scores_field, [])
        if not isinstance(scores, list):
            continue
        for score in scores:
            if not isinstance(score, dict):
                continue
            if not _score_key_matches(key_name, score.get(key_name), key_value):
                continue
            value = score.get("value")
            if value is not None:
                values.append(float(value))
    return values


def _to_number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _cohort_percentile(value: float, cohort_values: list[float]) -> float | None:
    """League-relative percentile on a 1–100 scale (never 0 — use None when unknown)."""
    if not cohort_values:
        return None

    n = len(cohort_values)
    if n == 1:
        return 50.0

    if len(set(cohort_values)) == 1:
        return 50.0

    less_than = sum(1 for cohort_value in cohort_values if cohort_value < value)
    equal = sum(1 for cohort_value in cohort_values if cohort_value == value)
    # Mid-rank within the cohort — fairer than the old (n-1) formula that forced 0 on the minimum.
    percentile = (less_than + 0.5 * equal) / n * 100.0
    return round(max(1.0, min(100.0, percentile)), 1)


def _selected_profiles(body: ChartRequest) -> list[str]:
    if body.profiles:
        return [
            name.strip()
            for name in body.profiles
            if name.strip() and _is_pv_profile(name)
        ]
    if body.profile and _is_pv_profile(body.profile):
        return [body.profile.strip()]
    return []


def _eligible_cohort_rows(score_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in score_rows if _meets_benchmark_minutes(row, BENCHMARK_MIN_MINUTES)
    ]


def _iteration_cohort_rows(
    iteration_id: int,
    positions: list[str],
    chart_source: ChartSource,
    *,
    min_minutes: float | None = BENCHMARK_MIN_MINUTES,
) -> list[dict[str, Any]]:
    fetch_scores = (
        _fetch_iteration_profile_scores
        if chart_source == "profiles"
        else _fetch_iteration_player_scores
    )
    rows = fetch_scores(iteration_id, positions, 0)
    if min_minutes is None:
        return rows
    return [
        row for row in rows if _meets_benchmark_minutes(row, min_minutes)
    ]


def _squad_cohort_rows(
    iteration_id: int,
    squad_id: int | None,
    positions: list[str],
    chart_source: ChartSource,
) -> list[dict[str, Any]]:
    if squad_id is None:
        return []
    if chart_source == "profiles":
        rows, _ = _fetch_profile_scores(iteration_id, squad_id, positions, 0)
        return rows
    rows, _ = _fetch_player_scores(iteration_id, squad_id, positions, 0)
    return rows


def _equivalent_profile_names(
    profile_name: str,
    definitions: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    names: list[str] = []
    normalized = _normalize_profile_name(profile_name)
    if normalized:
        names.append(normalized)

    definitions = definitions or _fetch_player_profile_definitions()
    resolved = resolve_profile_definition(
        profile_name,
        definitions,
        is_pv_profile=_is_pv_profile,
    )
    if resolved:
        resolved_name = _normalize_profile_name(resolved.get("name"))
        if resolved_name and resolved_name not in names:
            names.append(resolved_name)

    target_tokens = profile_match_tokens(profile_name)
    if target_tokens:
        for name in definitions:
            if not _is_pv_profile(name):
                continue
            if profile_match_tokens(name) == target_tokens and name not in names:
                names.append(name)
    return names


def _profile_cohort_values(
    profile_name: str,
    score_rows: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]] | None = None,
    squad_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[float], str]:
    profile_definitions = _fetch_player_profile_definitions()
    for candidate_name in _equivalent_profile_names(profile_name, profile_definitions):
        cohort_values = _cohort_values_for_key(
            score_rows, "profileName", candidate_name, "profileScores"
        )
        if cohort_values:
            return cohort_values, "benchmark"
    for candidate_name in _equivalent_profile_names(profile_name, profile_definitions):
        if fallback_rows:
            cohort_values = _cohort_values_for_key(
                fallback_rows, "profileName", candidate_name, "profileScores"
            )
            if cohort_values:
                return cohort_values, "league"
    for candidate_name in _equivalent_profile_names(profile_name, profile_definitions):
        if squad_rows:
            cohort_values = _cohort_values_for_key(
                squad_rows, "profileName", candidate_name, "profileScores"
            )
            if cohort_values:
                return cohort_values, "squad"
    return [], ""


def _build_profile_chart(
    score_rows: list[dict[str, Any]],
    selected: dict[str, Any],
    profile_filters: list[str],
    fallback_rows: list[dict[str, Any]] | None = None,
    squad_rows: list[dict[str, Any]] | None = None,
    league_fallback_profiles: list[str] | None = None,
    squad_fallback_profiles: list[str] | None = None,
    chart_label_for_profile: dict[str, str] | None = None,
) -> tuple[list[str], list[float], list[float]]:
    profile_scores = _profile_scores_for_player(selected)
    if profile_filters:
        allowed = {_normalize_profile_name(name) for name in profile_filters}
        profile_scores = [
            score
            for score in profile_scores
            if _normalize_profile_name(score.get("profileName")) in allowed
        ]
        profile_order = {
            _normalize_profile_name(name): index for index, name in enumerate(profile_filters)
        }
        profile_scores.sort(
            key=lambda score: profile_order.get(
                _normalize_profile_name(score.get("profileName", "")), 999
            )
        )

    labels: list[str] = []
    radar_values: list[float] = []
    pizza_values: list[float] = []

    for profile_score in profile_scores:
        profile_name = _normalize_profile_name(profile_score.get("profileName"))
        value = _to_number(profile_score.get("value"))
        if not profile_name or not _is_pv_profile(profile_name) or value is None:
            continue

        cohort_values, cohort_source = _profile_cohort_values(
            profile_name,
            score_rows,
            fallback_rows=fallback_rows,
            squad_rows=squad_rows,
        )
        if not cohort_values:
            continue

        if cohort_source == "league" and league_fallback_profiles is not None:
            league_fallback_profiles.append(profile_name)
        if cohort_source == "squad" and squad_fallback_profiles is not None:
            squad_fallback_profiles.append(profile_name)

        chart_label = (
            chart_label_for_profile.get(profile_name, profile_name)
            if chart_label_for_profile
            else profile_name
        )
        labels.append(chart_label)
        percentile = _cohort_percentile(value, cohort_values)
        if percentile is None:
            continue
        radar_values.append(percentile)
        pizza_values.append(percentile)

    if len(labels) > MAX_CHART_FACTORS:
        labels = labels[:MAX_CHART_FACTORS]
        radar_values = radar_values[:MAX_CHART_FACTORS]
        pizza_values = pizza_values[:MAX_CHART_FACTORS]

    return labels, radar_values, pizza_values


def _resolve_profile_filters_for_row(
    profile_filters: list[str],
    selected: dict[str, Any],
) -> tuple[list[str], dict[str, str]]:
    if not profile_filters:
        return [], {}
    return profile_filters, {}


def _catalog_path(resource: str) -> str:
    return f"/v5/{_api_prefix()}/{resource}"


def _cached_catalog(cache_key: str, loader: Any) -> Any:
    cached = _definitions_cache.get(cache_key)
    if cached and time.time() - cached[0] < PLAYERS_CACHE_TTL_SECONDS:
        return cached[1]
    value = loader()
    _definitions_cache[cache_key] = (time.time(), value)
    return value


def _fetch_player_profile_definitions() -> dict[str, dict[str, Any]]:
    def load() -> dict[str, dict[str, Any]]:
        rows = _extract_rows(_impect_get(_catalog_path("player-profiles"), {"language": "en"})["data"])
        definitions: dict[str, dict[str, Any]] = {}
        for row in rows:
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            factors = [
                factor
                for factor in row.get("factors", [])
                if isinstance(factor, dict) and str(factor.get("name", "")).strip()
            ]
            positions = [
                str(position.get("name", "")).strip()
                for position in row.get("positions", [])
                if isinstance(position, dict) and str(position.get("name", "")).strip()
            ]
            definitions[name] = {
                "name": name,
                "factors": factors,
                "positions": positions,
            }
        return definitions

    return _cached_catalog("player-profiles:en", load)


def _fetch_player_score_catalog() -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    def load() -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
        rows = _extract_rows(_impect_get(_catalog_path("player-scores"), {"language": "en"})["data"])
        by_id: dict[int, dict[str, Any]] = {}
        by_name: dict[str, dict[str, Any]] = {}
        for row in rows:
            score_id = row.get("id")
            name = str(row.get("name", "")).strip()
            if score_id is None or not name:
                continue
            entry = {
                "id": int(score_id),
                "name": name,
                "label": str((row.get("details") or {}).get("label", "")).strip() or name,
                "definition": str((row.get("details") or {}).get("definition", "")).strip(),
                "inverted": bool(row.get("inverted", False)),
            }
            by_id[entry["id"]] = entry
            by_name[name.casefold()] = entry
        return by_id, by_name

    return _cached_catalog("player-scores:en", load)


def _resolve_profile_definition(
    profile_name: str,
    definitions: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return resolve_profile_definition(
        profile_name,
        definitions,
        is_pv_profile=_is_pv_profile,
    )


def _normalize_factor_key(name: str) -> str:
    return str(name or "").strip().casefold().replace(" ", "_")


def _resolve_factor_score_id(
    factor: dict[str, Any],
    scores_by_name: dict[str, dict[str, Any]],
) -> int | None:
    return resolve_factor_score_id(factor, scores_by_name)


def _player_score_value(row: dict[str, Any], score_id: int) -> float | None:
    for score in _player_scores_for_player(row):
        if score.get("playerScoreId") == score_id:
            return _to_number(score.get("value"))
    return None


def _percentile_for_score(
    value: float,
    score_id: int,
    cohort_rows: list[dict[str, Any]],
    inverted: bool = False,
    fallback_rows: list[dict[str, Any]] | None = None,
    squad_rows: list[dict[str, Any]] | None = None,
) -> float | None:
    cohort_values: list[float] = []
    for rows in (cohort_rows, fallback_rows, squad_rows):
        if not rows:
            continue
        cohort_values = _cohort_values_for_key(
            rows, "playerScoreId", score_id, "playerScores"
        )
        if cohort_values:
            break
    if not cohort_values:
        return None
    percentile = _cohort_percentile(value, cohort_values)
    if percentile is None:
        return None
    if inverted:
        percentile = round(100.0 - percentile, 1)
        percentile = max(1.0, min(100.0, percentile))
    return percentile


def _build_single_profile_drilldown(
    profile_name: str,
    selected_metrics_row: dict[str, Any],
    metrics_cohort_rows: list[dict[str, Any]],
    profile_definitions: dict[str, dict[str, Any]],
    scores_by_name: dict[str, dict[str, Any]],
    metrics_fallback_rows: list[dict[str, Any]] | None = None,
    metrics_squad_rows: list[dict[str, Any]] | None = None,
    scores_by_id: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    definition = _resolve_profile_definition(profile_name, profile_definitions)
    if definition is None:
        return None

    missing_factors: list[str] = []
    resolved_factors: list[dict[str, Any]] = []

    for factor in definition.get("factors", []):
        score_id = _resolve_factor_score_id(factor, scores_by_name)
        factor_name = str(factor.get("name", "")).strip()
        if score_id is None:
            missing_factors.append(factor_name)
            continue

        value = _player_score_value(selected_metrics_row, score_id)
        if value is None:
            missing_factors.append(factor_name)
            continue

        catalog_entry = (scores_by_id or {}).get(int(score_id), {})
        if not catalog_entry:
            alias_name = FACTOR_SCORE_ALIASES.get(_normalize_factor_key(factor_name), "")
            catalog_entry = scores_by_name.get(alias_name, scores_by_name.get(factor_name.casefold(), {}))
        percentile = _percentile_for_score(
            value,
            score_id,
            metrics_cohort_rows,
            inverted=resolve_factor_inverted(factor, catalog_entry),
            fallback_rows=metrics_fallback_rows,
            squad_rows=metrics_squad_rows,
        )
        if percentile is None:
            missing_factors.append(factor_name)
            continue

        raw_label = resolve_factor_label(factor, catalog_entry)
        # Impect occasionally ships a blank catalog label (literally "None") for a
        # valid metric such as PXT. Fall back to the profile's own factor name so
        # the factor still shows instead of being dropped for every player.
        if not raw_label or raw_label.casefold() in {"none", "n/a", "null", "-"}:
            raw_label = factor_name
        if not raw_label or raw_label.casefold() in {"none", "n/a", "null", "-"}:
            missing_factors.append(factor_name)
            continue

        inverted = resolve_factor_inverted(factor, catalog_entry)
        resolved_factors.append(
            {
                "factor_name": factor_name,
                "score_id": int(score_id),
                "weight": float(factor.get("weight") or 0.0),
                "label": (
                    humanize_metric_label(raw_label)
                    if not factor_name.casefold().startswith("bypassed_")
                    else raw_label
                ),
                "radar_value": float(percentile),
                "raw_value": float(value),
                "inverted": inverted,
            }
        )

    if not resolved_factors:
        return None

    # One radar wedge per profile factor — do not merge different factors that share a score id.
    deduped_factors: dict[str, dict[str, Any]] = {}
    for item in resolved_factors:
        factor_key = str(item["factor_name"]).strip().casefold()
        existing = deduped_factors.get(factor_key)
        if existing is None:
            deduped_factors[factor_key] = dict(item)
            continue
        existing["weight"] = float(existing["weight"]) + float(item["weight"])

    resolved_factors = list(deduped_factors.values())
    factor_order = {
        str(factor.get("name", "")).strip().casefold(): index
        for index, factor in enumerate(definition.get("factors", []))
    }
    resolved_factors.sort(
        key=lambda item: factor_order.get(str(item["factor_name"]).strip().casefold(), 999),
    )

    chart_factors = resolved_factors[:MAX_CHART_FACTORS]
    labels = [item["label"] for item in chart_factors]
    radar_values = [item["radar_value"] for item in chart_factors]
    raw_values = [item["raw_value"] for item in chart_factors]
    bar_factors = sorted(
        resolved_factors,
        key=lambda item: float(item.get("weight") or 0.0),
        reverse=True,
    )[:MAX_BAR_FACTORS]
    profile_weight_total = sum(float(item["weight"]) for item in resolved_factors)

    return {
        "profile": profile_name,
        "labels": labels,
        "radar_values": radar_values,
        "raw_values": raw_values,
        "bar_labels": [item["label"] for item in bar_factors],
        "bar_radar_values": [item["radar_value"] for item in bar_factors],
        "bar_raw_values": [item["raw_value"] for item in bar_factors],
        "bar_weights": [
            round((float(item["weight"]) / profile_weight_total) * 100.0, 1)
            if profile_weight_total
            else 0.0
            for item in bar_factors
        ],
        "bar_inverted": [bool(item.get("inverted")) for item in bar_factors],
        "inverted": [bool(item.get("inverted")) for item in chart_factors],
        "factor_count": len(definition.get("factors", [])),
        "missing_factors": missing_factors,
    }


def _drilldown_coverage_warnings(
    player_name: str,
    profile_filters: list[str],
    drilldowns: list[dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    built_profiles = {item.get("profile") for item in drilldowns}

    def _profile_built(filter_name: str) -> bool:
        filter_norm = _normalize_profile_name(filter_name)
        return any(
            _normalize_profile_name(built) == filter_norm for built in built_profiles
        )

    missing_profiles = [name for name in profile_filters if not _profile_built(name)]
    if missing_profiles:
        warnings.append(
            f"{player_name}: no factor breakdown for "
            f"{', '.join(humanize_profile_name(name) for name in missing_profiles[:3])}"
            f"{'…' if len(missing_profiles) > 3 else ''}."
        )
    for item in drilldowns:
        missing_factors = item.get("missing_factors") or []
        factor_count = int(item.get("factor_count") or 0)
        if not missing_factors or not factor_count:
            continue
        warnings.append(
            f"{player_name}: {humanize_profile_name(item.get('profile', ''))} is missing "
            f"{len(missing_factors)} of {factor_count} underlying metrics in Impect."
        )
    return warnings


def _build_profile_drilldowns(
    profile_names: list[str],
    selected_metrics_row: dict[str, Any] | None,
    metrics_cohort_rows: list[dict[str, Any]],
    metrics_fallback_rows: list[dict[str, Any]] | None = None,
    metrics_squad_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not profile_names or selected_metrics_row is None:
        return []

    profile_definitions = _fetch_player_profile_definitions()
    scores_by_id, scores_by_name = _fetch_player_score_catalog()
    drilldowns: list[dict[str, Any]] = []

    for profile_name in profile_names:
        drilldown = _build_single_profile_drilldown(
            profile_name,
            selected_metrics_row,
            metrics_cohort_rows,
            profile_definitions,
            scores_by_name,
            metrics_fallback_rows,
            metrics_squad_rows,
            scores_by_id=scores_by_id,
        )
        if drilldown is not None:
            drilldowns.append(drilldown)

    return drilldowns


def _shared_drilldown_labels(
    profile_entries: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    labels_key: str,
    values_key: str,
) -> list[str]:
    """Labels where every compared player has a non-null value."""
    if not profile_entries:
        return []

    reference_drilldown = max(
        profile_entries,
        key=lambda entry: len(entry[1].get(labels_key, [])),
    )[1]
    ordered_labels = list(reference_drilldown.get(labels_key, []))
    shared: list[str] = []

    for label in ordered_labels:
        normalized = _normalize_profile_name(label)
        has_all = True
        for _, drilldown in profile_entries:
            label_index = {
                _normalize_profile_name(item): index
                for index, item in enumerate(drilldown.get(labels_key, []))
            }.get(normalized)
            if label_index is None:
                has_all = False
                break
            values = drilldown.get(values_key, [])
            if label_index >= len(values):
                has_all = False
                break
            if values[label_index] is None:
                has_all = False
                break
        if has_all:
            shared.append(label)

    return shared


def _values_for_labels(
    labels: list[str],
    source_labels: list[str],
    values: list[float],
) -> list[float]:
    by_label = {
        _normalize_profile_name(label): value
        for label, value in zip(source_labels, values)
    }
    return [float(by_label[_normalize_profile_name(label)]) for label in labels]


def _merge_profile_drilldowns(
    active_results: list[dict[str, Any]],
    profile_names: list[str],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []

    for profile_name in profile_names:
        profile_entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
        profile_norm = _normalize_profile_name(profile_name)
        for result in active_results:
            player_drilldown = next(
                (
                    item
                    for item in result.get("profile_drilldowns", [])
                    if _normalize_profile_name(item.get("profile", "")) == profile_norm
                ),
                None,
            )
            if player_drilldown is not None:
                profile_entries.append((result, player_drilldown))

        if not profile_entries:
            continue

        canonical_labels = _shared_drilldown_labels(
            profile_entries,
            labels_key="labels",
            values_key="radar_values",
        )[:MAX_CHART_FACTORS]
        canonical_bar_labels = _shared_drilldown_labels(
            profile_entries,
            labels_key="bar_labels",
            values_key="bar_radar_values",
        )[:MAX_BAR_FACTORS]

        if not canonical_labels:
            continue

        reference = max(
            profile_entries,
            key=lambda entry: len(entry[1].get("labels", [])),
        )[1]
        ref_bar_labels = list(reference.get("bar_labels", reference.get("labels", [])))
        ref_bar_weights = list(reference.get("bar_weights", []))
        ref_bar_inverted = list(reference.get("bar_inverted", []))
        bar_weights: list[float] = []
        bar_inverted: list[bool] = []
        for label in canonical_bar_labels:
            label_index = {
                _normalize_profile_name(item): index
                for index, item in enumerate(ref_bar_labels)
            }.get(_normalize_profile_name(label))
            if label_index is None:
                bar_weights.append(0.0)
                bar_inverted.append(False)
                continue
            bar_weights.append(
                float(ref_bar_weights[label_index]) if label_index < len(ref_bar_weights) else 0.0
            )
            bar_inverted.append(
                bool(ref_bar_inverted[label_index])
                if label_index < len(ref_bar_inverted)
                else False
            )

        players: list[dict[str, Any]] = []
        for result, player_drilldown in profile_entries:
            source_labels = list(player_drilldown.get("labels", []))
            source_bar_labels = list(
                player_drilldown.get("bar_labels", player_drilldown.get("labels", []))
            )
            players.append(
                {
                    "key": result.get("key", ""),
                    "player": result.get("player", ""),
                    "season_label": result.get("season_label", ""),
                    "position_label": result.get("position_label", ""),
                    "play_duration_minutes": result.get("play_duration_minutes"),
                    "photo_url": result.get("photo_url"),
                    "labels": canonical_labels,
                    "radar_values": _values_for_labels(
                        canonical_labels,
                        source_labels,
                        player_drilldown.get("radar_values", []),
                    ),
                    "raw_values": _values_for_labels(
                        canonical_labels,
                        source_labels,
                        player_drilldown.get("raw_values", []),
                    ),
                    "bar_labels": canonical_bar_labels,
                    "bar_radar_values": _values_for_labels(
                        canonical_bar_labels,
                        source_bar_labels,
                        player_drilldown.get("bar_radar_values", []),
                    ),
                    "bar_raw_values": _values_for_labels(
                        canonical_bar_labels,
                        source_bar_labels,
                        player_drilldown.get("bar_raw_values", []),
                    ),
                }
            )

        if canonical_labels and players:
            merged.append(
                {
                    "profile": profile_name,
                    "labels": canonical_labels,
                    "bar_labels": canonical_bar_labels,
                    "bar_weights": bar_weights,
                    "bar_inverted": bar_inverted,
                    "players": players,
                }
            )

    return merged


def _build_metrics_chart(
    score_rows: list[dict[str, Any]], selected: dict[str, Any]
) -> tuple[list[str], list[float], list[float]]:
    player_scores = _player_scores_for_player(selected)

    labels: list[str] = []
    radar_values: list[float] = []
    pizza_values: list[float] = []

    for player_score in player_scores:
        score_id = player_score.get("playerScoreId")
        value = _to_number(player_score.get("value"))
        if score_id is None or value is None:
            continue

        cohort_values = _cohort_values_for_key(
            score_rows, "playerScoreId", score_id, "playerScores"
        )
        if not cohort_values:
            continue

        labels.append(f"Metric {score_id}")
        percentile = _cohort_percentile(value, cohort_values)
        if percentile is None:
            continue
        radar_values.append(percentile)
        pizza_values.append(percentile)

    if len(labels) > MAX_CHART_FACTORS:
        labels = labels[:MAX_CHART_FACTORS]
        radar_values = radar_values[:MAX_CHART_FACTORS]
        pizza_values = pizza_values[:MAX_CHART_FACTORS]

    return labels, radar_values, pizza_values


def _resolve_player_by_key(
    player_key: str, player_options: list[dict[str, Any]]
) -> tuple[str, dict[int, int], dict[int, int]] | None:
    for option in player_options:
        if option["key"] == player_key:
            return (
                option["name"],
                {int(i): pid for i, pid in option["ids_by_iteration"].items()},
                {int(i): sid for i, sid in option.get("squad_ids_by_iteration", {}).items()},
            )
    return None


def _selected_player_keys(body: ChartRequest) -> list[str]:
    keys = [key.strip() for key in body.player_keys if key and key.strip()]
    if keys:
        return keys
    if body.player_key and body.player_key.strip():
        return [body.player_key.strip()]
    if body.player_name:
        return [_player_key(body.player_name)]
    raise HTTPException(status_code=400, detail="Select a player first")


def _map_iterations_for_player(
    selected_iteration_ids: list[int],
    ids_by_iteration: dict[int, int],
    squad_ids_by_iteration: dict[int, int],
    iteration_meta: dict[int, dict[str, str]],
) -> list[int]:
    mapped: list[int] = []
    for source_id in selected_iteration_ids:
        source_meta = iteration_meta.get(source_id, {})
        target_season = source_meta.get("season")
        if not target_season:
            if (
                source_id in ids_by_iteration
                and squad_ids_by_iteration.get(source_id) is not None
            ):
                mapped.append(source_id)
            continue

        candidates = [
            iteration_id
            for iteration_id in ids_by_iteration
            if iteration_meta.get(iteration_id, {}).get("season") == target_season
            and squad_ids_by_iteration.get(iteration_id) is not None
        ]
        if not candidates:
            continue

        source_comp = source_meta.get("competition_name")
        same_comp = [
            iteration_id
            for iteration_id in candidates
            if iteration_meta.get(iteration_id, {}).get("competition_name") == source_comp
        ]
        mapped.append(same_comp[0] if same_comp else candidates[0])
    return mapped


def _canonical_profile_labels(
    profile_filters: list[str],
    active_results: list[dict[str, Any]],
) -> list[str]:
    if not active_results:
        return []

    if not profile_filters:
        labels = [_normalize_profile_name(label) for label in active_results[0].get("labels", [])]
        return labels[:MAX_CHART_FACTORS]

    labels = [_normalize_profile_name(name) for name in profile_filters]
    for result in active_results:
        available = result.get("labels", [])
        available_norm = {_normalize_profile_name(label) for label in available}
        labels = [label for label in labels if label in available_norm]
    return labels[:MAX_CHART_FACTORS]


def _align_chart_series(
    canonical_labels: list[str],
    labels: list[str],
    radar_values: list[float],
    pizza_values: list[float],
    fill_missing: bool = False,
) -> tuple[list[float | None], list[float | None]] | None:
    by_label = {
        _normalize_profile_name(label): (radar, pizza)
        for label, radar, pizza in zip(labels, radar_values, pizza_values)
    }
    normalized_canonical = [_normalize_profile_name(label) for label in canonical_labels]
    if not fill_missing and any(label not in by_label for label in normalized_canonical):
        return None

    aligned_radar: list[float | None] = []
    aligned_pizza: list[float | None] = []
    for label in normalized_canonical:
        radar, pizza = by_label.get(label, (None, None))
        aligned_radar.append(radar)
        aligned_pizza.append(pizza)
    return aligned_radar, aligned_pizza


def _align_value_series(
    canonical_labels: list[str],
    labels: list[str],
    values: list[float],
    fill_missing: bool = False,
) -> list[float | None] | None:
    by_label = {
        _normalize_profile_name(label): value for label, value in zip(labels, values)
    }
    normalized_canonical = [_normalize_profile_name(label) for label in canonical_labels]
    if not fill_missing and any(label not in by_label for label in normalized_canonical):
        return None
    return [by_label.get(label) for label in normalized_canonical]


def _resolve_player_selection(
    body: ChartRequest, player_options: list[dict[str, Any]]
) -> tuple[str, dict[int, int], dict[int, int]]:
    if body.player_key:
        resolved = _resolve_player_by_key(body.player_key, player_options)
        if resolved:
            return resolved

    if body.player_name:
        resolved = _resolve_player_by_key(_player_key(body.player_name), player_options)
        if resolved:
            return resolved

    raise HTTPException(status_code=400, detail="Select a player first")


def _combine_season_series(
    season_series: list[dict[str, Any]],
) -> tuple[list[str], list[float], list[float]]:
    combined: dict[str, list[tuple[float, float]]] = {}
    for season in season_series:
        for label, radar, pizza in zip(
            season["labels"], season["radar_values"], season["pizza_values"]
        ):
            combined.setdefault(label, []).append((radar, pizza))

    labels = sorted(combined.keys())
    radar_values = [
        round(sum(values[0] for values in combined[label]) / len(combined[label]), 1)
        for label in labels
    ]
    pizza_values = [
        round(sum(values[1] for values in combined[label]) / len(combined[label]), 1)
        for label in labels
    ]
    return (
        labels[:MAX_CHART_FACTORS],
        radar_values[:MAX_CHART_FACTORS],
        pizza_values[:MAX_CHART_FACTORS],
    )


def _build_single_player_charts(
    body: ChartRequest,
    player_key: str,
    player_options: list[dict[str, Any]],
    catalog_ids: list[int],
    iteration_labels: dict[int, str],
    iteration_meta: dict[int, dict[str, str]],
    requested_iteration_ids: list[int],
    profile_filters: list[str],
) -> dict[str, Any]:
    resolved = _resolve_player_by_key(player_key, player_options)
    if resolved is None:
        return {
            "key": player_key,
            "player": player_key,
            "skipped": True,
            "skip_reason": f"Player '{player_key}' not found.",
        }

    display_name, ids_by_iteration, squad_ids_by_iteration = resolved
    iteration_ids = _map_iterations_for_player(
        requested_iteration_ids,
        ids_by_iteration,
        squad_ids_by_iteration,
        iteration_meta,
    )
    if body.drilldowns_only:
        if not iteration_ids or body.chart_source != "profiles" or not profile_filters:
            return {
                "key": player_key,
                "player": display_name,
                "profile_drilldowns": [],
                "labels": profile_filters,
            }
        player_positions = _requested_positions_for_player(body, player_key)
        profile_drilldowns: list[dict[str, Any]] = []
        source_urls: list[str] = []
        iteration_id = iteration_ids[0]
        player_id = ids_by_iteration.get(iteration_id)
        squad_id = squad_ids_by_iteration.get(iteration_id)
        if player_id is not None:
            resolved_squad = _resolve_squad_id_for_player(
                iteration_id,
                player_id,
                display_name,
                squad_id,
                "metrics",
            )
            if resolved_squad is not None:
                squad_id = resolved_squad
            players = _fetch_players_for_iteration(iteration_id)
            name_map = _player_name_map(players)
            metrics_selected, metric_positions, metrics_url = _find_player_score_row(
                iteration_id,
                player_id,
                squad_id,
                display_name,
                name_map,
                "metrics",
                player_positions,
                body.min_games,
            )
            if metrics_selected is not None:
                metric_positions = metric_positions or player_positions
                season = _season_for_iteration(iteration_id)
                metrics_cohort, _ = _fetch_benchmark_cohort(season, metric_positions, "metrics")
                metrics_league_cohort = _iteration_cohort_rows(
                    iteration_id, metric_positions, "metrics", min_minutes=None
                )
                metrics_squad_cohort = _squad_cohort_rows(
                    iteration_id, squad_id, metric_positions, "metrics"
                )
                impect_filters, _ = _resolve_profile_filters_for_row(
                    profile_filters,
                    metrics_selected,
                )
                profile_drilldowns = _build_profile_drilldowns(
                    impect_filters or profile_filters,
                    metrics_selected,
                    metrics_cohort,
                    metrics_league_cohort,
                    metrics_squad_cohort,
                )
                if metrics_url:
                    source_urls.append(metrics_url)
        return {
            "key": player_key,
            "player": display_name,
            "profile_drilldowns": profile_drilldowns,
            "labels": profile_filters,
            "source_urls": source_urls,
        }

    if not iteration_ids:
        requested_labels = [
            iteration_meta.get(iteration_id, {}).get("label", f"Season {iteration_id}")
            for iteration_id in requested_iteration_ids
        ]
        available_labels = _available_season_labels(
            ids_by_iteration, squad_ids_by_iteration, iteration_meta
        )
        return {
            "key": player_key,
            "player": display_name,
            "skipped": True,
            "skip_reason": (
                f"{display_name} has no data for {', '.join(requested_labels)}. "
                f"Available seasons: {', '.join(available_labels[:4])}"
                f"{'…' if len(available_labels) > 4 else ''}"
            ),
        }

    season_series: list[dict[str, Any]] = []
    all_score_rows: list[dict[str, Any]] = []
    source_urls: list[str] = []
    warnings: list[str] = []
    benchmark_meta: dict[str, Any] | None = None
    profile_drilldowns: list[dict[str, Any]] = []

    for iteration_id in iteration_ids:
        player_id = ids_by_iteration.get(iteration_id)
        squad_id = squad_ids_by_iteration.get(iteration_id)
        if player_id is None:
            continue

        resolved_squad = _resolve_squad_id_for_player(
            iteration_id,
            player_id,
            display_name,
            squad_id,
            body.chart_source,
        )
        if resolved_squad is not None:
            squad_id = resolved_squad

        players = _fetch_players_for_iteration(iteration_id)
        name_map = _player_name_map(players)

        player_positions = _requested_positions_for_player(body, player_key)
        selected, positions, scores_url = _find_player_score_row(
            iteration_id,
            player_id,
            squad_id,
            display_name,
            name_map,
            body.chart_source,
            player_positions,
            body.min_games,
        )
        if selected is None:
            continue

        season = _season_for_iteration(iteration_id)
        cohort_rows, cohort_meta = _fetch_benchmark_cohort(season, positions, body.chart_source)
        benchmark_meta = cohort_meta
        league_cohort_rows = _iteration_cohort_rows(
            iteration_id, positions, body.chart_source, min_minutes=None
        )
        squad_cohort_rows = _squad_cohort_rows(
            iteration_id, squad_id, positions, body.chart_source
        )

        if body.chart_source == "profiles":
            low_minutes = _low_minutes_warning(selected, BENCHMARK_MIN_MINUTES)
            if low_minutes:
                warnings.append(f"{display_name}: {low_minutes}")
            league_fallback_profiles: list[str] = []
            squad_fallback_profiles: list[str] = []
            impect_filters, chart_label_map = _resolve_profile_filters_for_row(
                profile_filters,
                selected,
            )
            labels, radar_values, pizza_values = _build_profile_chart(
                cohort_rows,
                selected,
                impect_filters or profile_filters,
                fallback_rows=league_cohort_rows,
                squad_rows=squad_cohort_rows,
                league_fallback_profiles=league_fallback_profiles,
                squad_fallback_profiles=squad_fallback_profiles,
                chart_label_for_profile=chart_label_map or None,
            )
            if league_fallback_profiles:
                warnings.append(
                    f"{display_name}: league cohort used for "
                    f"{', '.join(league_fallback_profiles)} "
                    "(club profiles not in cross-league benchmark)."
                )
            if squad_fallback_profiles:
                warnings.append(
                    f"{display_name}: squad cohort used for "
                    f"{', '.join(squad_fallback_profiles)} "
                    "(percentile vs Port Vale squad mates)."
                )
        else:
            low_minutes = _low_minutes_warning(selected, BENCHMARK_MIN_MINUTES)
            if low_minutes:
                warnings.append(f"{display_name}: {low_minutes}")
            labels, radar_values, pizza_values = _build_metrics_chart(cohort_rows, selected)

        if not labels:
            continue

        if (
            body.include_drilldowns
            and body.chart_source == "profiles"
            and not profile_drilldowns
            and profile_filters
        ):
            metrics_selected, metric_positions, metrics_url = _find_player_score_row(
                iteration_id,
                player_id,
                squad_id,
                display_name,
                name_map,
                "metrics",
                player_positions,
                body.min_games,
            )
            if metrics_selected is not None:
                metric_positions = metric_positions or positions
                metrics_cohort, _ = _fetch_benchmark_cohort(
                    season,
                    metric_positions,
                    "metrics",
                )
                metrics_league_cohort = _iteration_cohort_rows(
                    iteration_id, metric_positions, "metrics", min_minutes=None
                )
                metrics_squad_cohort = _squad_cohort_rows(
                    iteration_id, squad_id, metric_positions, "metrics"
                )
                profile_drilldowns = _build_profile_drilldowns(
                    impect_filters or profile_filters,
                    metrics_selected,
                    metrics_cohort,
                    metrics_league_cohort,
                    metrics_squad_cohort,
                )
                if metrics_url:
                    source_urls.append(metrics_url)
                warnings.extend(
                    _drilldown_coverage_warnings(
                        display_name,
                        profile_filters,
                        profile_drilldowns,
                    )
                )

        if scores_url:
            source_urls.append(scores_url)
        all_score_rows.extend(cohort_rows)
        season_series.append(
            {
                "iteration_id": iteration_id,
                "label": iteration_labels.get(iteration_id, f"Season {iteration_id}"),
                "labels": labels,
                "radar_values": radar_values,
                "pizza_values": pizza_values,
                "play_duration_minutes": _play_duration_minutes(selected),
                "positions": positions,
                "position_label": _position_label(positions[0]) if positions else "",
            }
        )

    if not season_series:
        mapped_labels = [
            iteration_labels.get(iteration_id, f"Season {iteration_id}")
            for iteration_id in iteration_ids
        ]
        player_option = next(
            (option for option in player_options if option["key"] == player_key),
            None,
        )
        score_seasons = (
            _seasons_with_score_data(player_option, iteration_meta, body.chart_source)
            if player_option
            else []
        )
        score_hint = ""
        if score_seasons:
            score_hint = f" Impect scores available in: {', '.join(score_seasons[:3])}."
        if body.chart_source == "profiles" and profile_filters:
            return {
                "key": player_key,
                "player": display_name,
                "skipped": True,
                "skip_reason": (
                    f"{display_name} has no Impect profile scores for "
                    f"{', '.join(mapped_labels)}.{score_hint} "
                    "Pick a season where both players have data — league does not "
                    "need to match, only the season (e.g. 24/25)."
                ),
            }
        return {
            "key": player_key,
            "player": display_name,
            "skipped": True,
            "skip_reason": (
                f"No chart data found for {display_name} in "
                f"{', '.join(mapped_labels)}.{score_hint}"
            ),
        }

    combine_seasons = body.combine_seasons or (
        body.last_n_seasons is not None and body.last_n_seasons > 1
    )
    if combine_seasons and len(season_series) > 1:
        labels, radar_values, pizza_values = _combine_season_series(season_series)
    else:
        primary = season_series[0]
        labels = primary["labels"]
        radar_values = primary["radar_values"]
        pizza_values = primary["pizza_values"]

    if combine_seasons and len(season_series) > 1:
        season_count = len(season_series)
        season_label = (
            f"Combined {season_count} season{'s' if season_count != 1 else ''} · "
            + ", ".join(season["label"] for season in season_series)
        )
    else:
        season_label = season_series[0]["label"] if season_series else ""

    resolved_position = ""
    resolved_position_label = ""
    if season_series:
        first_positions = season_series[0].get("positions") or []
        if first_positions:
            resolved_position = first_positions[0]
            resolved_position_label = _position_label(resolved_position)

    play_duration_minutes: float | None = None
    if season_series:
        minute_values = [
            season.get("play_duration_minutes")
            for season in season_series
            if season.get("play_duration_minutes") is not None
        ]
        if minute_values:
            if combine_seasons and len(season_series) > 1:
                play_duration_minutes = float(sum(minute_values))
            else:
                play_duration_minutes = float(minute_values[0])

    return {
        "key": player_key,
        "player": display_name,
        "season_label": season_label,
        "position": resolved_position,
        "position_label": resolved_position_label,
        "play_duration_minutes": play_duration_minutes,
        "photo_url": _player_photo_api_url(display_name),
        "labels": labels,
        "radar_values": radar_values,
        "pizza_values": pizza_values,
        "seasons": season_series,
        "rows_in_cohort": len(all_score_rows),
        "source_urls": source_urls,
        "benchmark": benchmark_meta,
        "warnings": warnings,
        "profile_drilldowns": profile_drilldowns,
        "skipped": False,
    }


def _last_n_iteration_ids_for_player(
    player_option: dict[str, Any],
    iteration_meta: dict[int, dict[str, str]],
    season_count: int,
    positions: list[str],
    chart_source: ChartSource = "profiles",
) -> list[int]:
    if season_count <= 0:
        return []

    ids_by_iteration, squad_ids_by_iteration = _player_iteration_maps(player_option)
    resolved_positions = _validate_positions(positions) if positions else []
    cache_key = (
        player_option.get("key", player_option.get("name", "")),
        season_count,
        tuple(resolved_positions),
        chart_source,
    )
    cached = _last_n_iterations_cache.get(cache_key)
    if cached and time.time() - cached[0] < PLAYERS_CACHE_TTL_SECONDS:
        return list(cached[1])

    candidates: list[tuple[int, str]] = []
    scan_limit = max(season_count * 4, MAX_SEASON_LOOKBACK_FOR_LAST_N)
    sorted_iteration_ids = sorted(
        [
            iteration_id
            for iteration_id in ids_by_iteration
            if squad_ids_by_iteration.get(iteration_id) is not None
        ],
        key=lambda iteration_id: _season_sort_key(
            iteration_meta.get(iteration_id, {}).get("season", "")
        ),
        reverse=True,
    )[:scan_limit]

    for iteration_id in sorted_iteration_ids:
        player_id = ids_by_iteration.get(iteration_id)
        if player_id is None:
            continue
        row, _, _ = _find_player_score_row(
            iteration_id,
            player_id,
            squad_ids_by_iteration.get(iteration_id),
            player_option["name"],
            {},
            chart_source,
            resolved_positions,
        )
        if row is None:
            continue
        candidates.append(
            (
                iteration_id,
                iteration_meta.get(iteration_id, {}).get("season", ""),
            )
        )
        if len(candidates) >= season_count:
            break

    candidates.sort(key=lambda item: _season_sort_key(item[1]), reverse=True)
    result = [iteration_id for iteration_id, _ in candidates[:season_count]]
    _last_n_iterations_cache[cache_key] = (time.time(), result)
    return result


def _resolve_player_iteration_ids(
    player_key: str,
    body: ImpectQuery,
    player_options: list[dict[str, Any]],
    primary_requested_ids: list[int],
    iteration_meta: dict[int, dict[str, str]],
    chart_source: ChartSource = "profiles",
) -> list[int]:
    custom_season_ids = [
        int(iteration_id)
        for iteration_id in body.player_seasons.get(player_key, [])
        if str(iteration_id).isdigit() or isinstance(iteration_id, int)
    ]
    if body.independent_seasons and custom_season_ids:
        return _iteration_ids_for_player_key(
            player_key,
            player_options,
            primary_requested_ids,
            iteration_meta,
            body.independent_seasons,
            body.player_seasons,
            chart_source,
        )

    last_n = body.last_n_seasons
    if last_n is not None and last_n > 0:
        player_option = next(
            (option for option in player_options if option["key"] == player_key),
            None,
        )
        if player_option is None:
            return []
        positions = _requested_positions_for_player(body, player_key)
        return _last_n_iteration_ids_for_player(
            player_option,
            iteration_meta,
            last_n,
            positions,
            chart_source,
        )

    return _iteration_ids_for_player_key(
        player_key,
        player_options,
        primary_requested_ids,
        iteration_meta,
        body.independent_seasons,
        body.player_seasons,
        chart_source,
    )


def _recent_player_iteration_ids(
    player_option: dict[str, Any],
    iteration_meta: dict[int, dict[str, str]],
    max_seasons: int = POSITION_LOOKUP_MAX_SEASONS,
) -> list[int]:
    ids_by_iteration, _ = _player_iteration_maps(player_option)
    ordered = sorted(
        ids_by_iteration,
        key=lambda iteration_id: _season_sort_key(
            iteration_meta.get(iteration_id, {}).get("season", "")
        ),
        reverse=True,
    )
    return ordered[: max(max_seasons, 0)]


def _best_iteration_ids_for_player(
    player_option: dict[str, Any],
    iteration_meta: dict[int, dict[str, str]],
    chart_source: ChartSource = "profiles",
    *,
    max_seasons: int | None = None,
) -> list[int]:
    ids_by_iteration, squad_ids_by_iteration = _player_iteration_maps(player_option)
    iteration_ids = (
        _recent_player_iteration_ids(player_option, iteration_meta, max_seasons)
        if max_seasons is not None
        else list(ids_by_iteration)
    )
    candidates: list[tuple[int, str]] = []
    for iteration_id in iteration_ids:
        player_id = ids_by_iteration.get(iteration_id)
        if player_id is None:
            continue
        if _player_has_score_data(
            iteration_id,
            int(player_id),
            squad_ids_by_iteration.get(iteration_id),
            player_option["name"],
            chart_source,
        ):
            candidates.append(
                (iteration_id, iteration_meta.get(iteration_id, {}).get("season", ""))
            )
    if not candidates:
        return []
    candidates.sort(key=lambda item: _season_sort_key(item[1]), reverse=True)
    return [candidates[0][0]]


def _iteration_ids_for_player_key(
    player_key: str,
    player_options: list[dict[str, Any]],
    primary_requested_ids: list[int],
    iteration_meta: dict[int, dict[str, str]],
    independent_seasons: bool,
    player_seasons: dict[str, list[int]],
    chart_source: ChartSource = "profiles",
    *,
    require_score_row: bool = True,
) -> list[int]:
    player_option = next(
        (option for option in player_options if option["key"] == player_key),
        None,
    )
    if player_option is None:
        return []

    ids_by_iteration, squad_ids_by_iteration = _player_iteration_maps(player_option)

    custom_ids = [
        int(iteration_id)
        for iteration_id in player_seasons.get(player_key, [])
        if str(iteration_id).isdigit() or isinstance(iteration_id, int)
    ]
    if custom_ids:
        validated: list[int] = []
        for iteration_id in custom_ids:
            player_id = ids_by_iteration.get(iteration_id)
            if player_id is None:
                continue
            if not require_score_row:
                validated.append(iteration_id)
                continue
            row, _, _ = _find_player_score_row(
                iteration_id,
                player_id,
                squad_ids_by_iteration.get(iteration_id),
                player_option["name"],
                {},
                chart_source,
                [],
            )
            if row is not None:
                validated.append(iteration_id)
        if validated:
            return validated
        if independent_seasons and require_score_row:
            return _best_iteration_ids_for_player(player_option, iteration_meta, chart_source)
        return custom_ids

    mapped = _map_iterations_for_player(
        primary_requested_ids,
        ids_by_iteration,
        squad_ids_by_iteration,
        iteration_meta,
    )
    if mapped:
        return mapped

    if independent_seasons:
        return _best_iteration_ids_for_player(player_option, iteration_meta, chart_source)

    return []


def _warm_comparison_caches(
    body: ChartRequest,
    player_keys: list[str],
    player_options: list[dict[str, Any]],
    requested_iteration_ids: list[int],
    iteration_meta: dict[int, dict[str, str]],
) -> None:
    """Prefetch cohort data in parallel so per-player chart builds hit warm caches."""
    seen_benchmark: set[tuple[str, tuple[str, ...], ChartSource]] = set()
    seen_iteration: set[tuple[int, tuple[str, ...], ChartSource]] = set()
    tasks: list[tuple[str, Any]] = []

    for player_key in player_keys:
        player_iteration_ids = _resolve_player_iteration_ids(
            player_key,
            body,
            player_options,
            requested_iteration_ids,
            iteration_meta,
            body.chart_source,
        )
        positions = _requested_positions_for_player(body, player_key)
        positions_key = tuple(positions)
        for iteration_id in player_iteration_ids:
            iter_key = (iteration_id, positions_key, body.chart_source)
            if iter_key not in seen_iteration:
                seen_iteration.add(iter_key)
                tasks.append(("iteration", iteration_id, positions, body.chart_source))
            season = _season_for_iteration(iteration_id)
            bench_key = (season, positions_key, body.chart_source)
            if bench_key not in seen_benchmark:
                seen_benchmark.add(bench_key)
                tasks.append(("benchmark", season, positions, body.chart_source))
            if body.include_drilldowns and body.chart_source == "profiles":
                metrics_iter_key = (iteration_id, positions_key, "metrics")
                if metrics_iter_key not in seen_iteration:
                    seen_iteration.add(metrics_iter_key)
                    tasks.append(("iteration", iteration_id, positions, "metrics"))
                metrics_bench_key = (season, positions_key, "metrics")
                if metrics_bench_key not in seen_benchmark:
                    seen_benchmark.add(metrics_bench_key)
                    tasks.append(("benchmark", season, positions, "metrics"))

    def run_task(task: tuple[str, Any]) -> None:
        kind = task[0]
        if kind == "iteration":
            _, iteration_id, positions, chart_source = task
            _iteration_cohort_rows(
                int(iteration_id),
                list(positions),
                chart_source,
                min_minutes=None,
            )
            return
        _, season, positions, chart_source = task
        _fetch_benchmark_cohort(str(season), list(positions), chart_source)

    if not tasks:
        return

    max_workers = min(6, len(tasks))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(run_task, tasks))


def _studio_port_vale_reference(
    position: str,
    canonical_labels: list[str],
) -> dict[str, Any] | None:
    """Port Vale player with the most position-attributed minutes this season."""
    from app.scouting import _load_iteration_bundle
    from app.squad_review import (
        _position_attributed_minutes,
        _resolve_port_vale_iteration,
        _resolve_port_vale_squad_id,
        _squad_total_minutes_by_player,
    )

    if position not in ALLOWED_POSITIONS or not canonical_labels:
        return None

    try:
        iteration = _resolve_port_vale_iteration(None)
    except HTTPException:
        return None

    iteration_id = int(iteration["id"])
    season_token = str(iteration.get("season", "")).strip()
    bundle = _load_iteration_bundle(iteration, position, 0)
    squad_names = bundle["squad_names"]
    port_vale_squad_id = _resolve_port_vale_squad_id(squad_names)
    if port_vale_squad_id is None:
        return None

    total_minutes = _squad_total_minutes_by_player(iteration, port_vale_squad_id)
    position_shares = bundle.get("position_shares")

    best_row: dict[str, Any] | None = None
    best_minutes = -1.0
    best_name = ""
    for row in bundle["score_rows"]:
        squad_id = row.get("_squadId") or row.get("squadId")
        if squad_id is None or int(squad_id) != port_vale_squad_id:
            continue
        player_id = row.get("playerId")
        if player_id is None:
            continue
        player_id = int(player_id)
        row_minutes = _play_duration_minutes(row) or 0.0
        minutes = _position_attributed_minutes(
            player_id,
            position,
            position_shares=position_shares,
            total_minutes_by_player=total_minutes,
            row_fallback_minutes=row_minutes,
        )
        if minutes > best_minutes:
            best_minutes = float(minutes)
            best_row = row
            catalog = bundle["player_lookup"].get((iteration_id, player_id), {})
            best_name = _extract_player_name(catalog) or f"Player {player_id}"

    if best_row is None or best_minutes <= 0:
        return None

    season = _season_for_iteration(iteration_id)
    positions = [position]
    cohort_rows, _ = _fetch_benchmark_cohort(season, positions, "profiles")
    league_cohort_rows = _iteration_cohort_rows(
        iteration_id, positions, "profiles", min_minutes=None
    )
    squad_cohort_rows = _squad_cohort_rows(
        iteration_id, port_vale_squad_id, positions, "profiles"
    )

    impect_filters, chart_label_map = _resolve_profile_filters_for_row(
        canonical_labels, best_row
    )
    labels, radar_values, _ = _build_profile_chart(
        cohort_rows,
        best_row,
        impect_filters or canonical_labels,
        fallback_rows=league_cohort_rows,
        squad_rows=squad_cohort_rows,
        chart_label_for_profile=chart_label_map or None,
    )

    profile_scores: dict[str, float] = {}
    for index, label in enumerate(labels):
        if index < len(radar_values) and radar_values[index] is not None:
            profile_scores[label] = float(radar_values[index])

    return {
        "player": best_name,
        "minutes": int(best_minutes),
        "season_label": f"Port Vale · {season_token}" if season_token else "Port Vale",
        "position": position,
        "position_label": _position_label(position),
        "photo_url": _player_photo_api_url(best_name),
        "profile_scores": profile_scores,
        "club": squad_names.get(port_vale_squad_id, "Port Vale FC"),
    }


def _build_season_charts(body: ChartRequest) -> dict[str, Any]:
    player_keys = _selected_player_keys(body)
    if not player_keys:
        raise HTTPException(status_code=400, detail="Select a player first")

    player_options = _player_options_for_keys(player_keys, body)
    lookup_iteration_ids = _iteration_ids_for_player_lookup(body, player_keys)
    if not lookup_iteration_ids:
        raise HTTPException(status_code=404, detail="No seasons found in Impect")

    iteration_meta = _iteration_meta_map()
    iteration_labels = _iteration_label_map(lookup_iteration_ids)

    primary_resolved = _resolve_player_by_key(player_keys[0], player_options)
    if primary_resolved is None:
        raise HTTPException(status_code=400, detail="Select a player first")

    _, primary_ids, primary_squads = primary_resolved
    primary_chartable = [
        iteration_id
        for iteration_id in primary_ids
        if primary_squads.get(iteration_id) is not None
    ]
    if not primary_chartable:
        raise HTTPException(
            status_code=404,
            detail="This player has no chartable seasons with squad data in this competition.",
        )

    if body.iteration_ids:
        requested_iteration_ids = [
            iteration_id
            for iteration_id in body.iteration_ids
            if iteration_id in primary_chartable
        ]
    else:
        requested_iteration_ids = primary_chartable

    if not requested_iteration_ids:
        raise HTTPException(
            status_code=400,
            detail="Select at least one season where this player has data.",
        )

    profile_filters = _selected_profiles(body)
    profile_warnings: list[str] = []
    if body.chart_source == "profiles":
        profile_filters, profile_warnings = _resolve_comparison_profiles(
            body,
            player_keys,
            player_options,
            requested_iteration_ids,
            iteration_meta,
        )
        if len(profile_filters) < 2:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Only {len(profile_filters)} profile(s) are shared by all "
                    f"{len(player_keys)} players for their selected season(s). "
                    "Compare players in the same position (e.g. all goalkeepers) "
                    "and use standard Impect profiles where club-specific ones "
                    "do not exist for everyone."
                ),
            )

    player_results: list[dict[str, Any]] = []
    benchmark_meta: dict[str, Any] | None = None
    all_warnings: list[str] = list(profile_warnings)
    all_source_urls: list[str] = []
    total_cohort_rows = 0

    player_jobs: list[tuple[str, list[int]]] = []
    for player_key in player_keys:
        player_iteration_ids = _resolve_player_iteration_ids(
            player_key,
            body,
            player_options,
            requested_iteration_ids,
            iteration_meta,
            body.chart_source,
        )
        if not player_iteration_ids:
            player_option = next(
                (option for option in player_options if option["key"] == player_key),
                None,
            )
            name = player_option["name"] if player_option else player_key
            score_seasons = (
                _seasons_with_score_data(player_option, iteration_meta, body.chart_source)
                if player_option
                else []
            )
            hint = f" Available: {', '.join(score_seasons[:3])}." if score_seasons else ""
            if body.last_n_seasons:
                skip_reason = (
                    f"{name} has no profile data for their selected position "
                    f"in their last {body.last_n_seasons} season(s) (or fewer)."
                )
            else:
                skip_reason = f"{name} has no data for the selected season(s).{hint}"
            player_results.append(
                {
                    "key": player_key,
                    "player": name,
                    "skipped": True,
                    "skip_reason": skip_reason,
                }
            )
            all_warnings.append(skip_reason)
            continue
        player_jobs.append((player_key, player_iteration_ids))

    _warm_comparison_caches(
        body,
        player_keys,
        player_options,
        requested_iteration_ids,
        iteration_meta,
    )

    def build_player_result(job: tuple[str, list[int]]) -> dict[str, Any]:
        player_key, player_iteration_ids = job
        return _build_single_player_charts(
            body,
            player_key,
            player_options,
            lookup_iteration_ids,
            iteration_labels,
            iteration_meta,
            player_iteration_ids,
            profile_filters,
        )

    if body.drilldowns_only:
        if body.chart_source != "profiles":
            return {"profile_drilldowns": []}
        built = []
        if player_jobs:
            max_workers = min(4, len(player_jobs))
            if max_workers <= 1:
                built = [build_player_result(job) for job in player_jobs]
            else:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    built = list(executor.map(build_player_result, player_jobs))
        profile_drilldowns = _merge_profile_drilldowns(built, profile_filters)
        return {"profile_drilldowns": profile_drilldowns}

    if player_jobs:
        max_workers = min(4, len(player_jobs))
        if max_workers <= 1:
            built = [build_player_result(job) for job in player_jobs]
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                built = list(executor.map(build_player_result, player_jobs))
        for result in built:
            player_results.append(result)
            if result.get("skipped"):
                all_warnings.append(str(result.get("skip_reason", "")))
                continue
            if result.get("benchmark"):
                benchmark_meta = result["benchmark"]
            all_warnings.extend(result.get("warnings", []))
            all_source_urls.extend(result.get("source_urls", []))
            total_cohort_rows += int(result.get("rows_in_cohort", 0))

    active = [result for result in player_results if not result.get("skipped")]
    if not active:
        raise HTTPException(
            status_code=404,
            detail="No chart data found for any selected player.",
        )

    profile_filters = profile_filters if body.chart_source == "profiles" else _selected_profiles(body)
    canonical_labels = (
        _canonical_profile_labels(
            profile_filters,
            active,
        )
        if body.chart_source == "profiles"
        else (profile_filters if profile_filters else active[0]["labels"])
    )

    if body.chart_source == "profiles" and profile_filters:
        dropped_profiles = [
            label for label in profile_filters if label not in canonical_labels
        ]
        if dropped_profiles:
            all_warnings.append(
                "Profiles skipped (no percentile data for this position/season): "
                + ", ".join(dropped_profiles)
            )

    if body.chart_source == "profiles" and len(canonical_labels) < 2:
        sample = active[0]
        available = ", ".join(sample.get("labels", [])[:6]) or "none"
        raise HTTPException(
            status_code=404,
            detail=(
                f"Fewer than 2 profiles have percentile data for {sample.get('player', 'this player')} "
                f"in the selected season. Available with data: {available}. "
                "Try fewer profiles, a different position, or another season."
            ),
        )

    chart_players: list[dict[str, Any]] = []
    for result in active:
        aligned = _align_chart_series(
            canonical_labels,
            result["labels"],
            result["radar_values"],
            result["pizza_values"],
        )
        if aligned is None:
            missing = [
                label
                for label in canonical_labels
                if label not in set(result.get("labels", []))
            ]
            all_warnings.append(
                f"{result['player']} is missing profile data for: {', '.join(missing)}."
            )
            continue

        radar_values, pizza_values = aligned
        chart_players.append(
            {
                "key": result["key"],
                "player": result["player"],
                "season_label": result.get("season_label", ""),
                "position": result.get("position", ""),
                "position_label": result.get("position_label", ""),
                "play_duration_minutes": result.get("play_duration_minutes"),
                "photo_url": _player_photo_api_url(result["player"]),
                "labels": canonical_labels,
                "radar_values": radar_values,
                "pizza_values": pizza_values,
            }
        )

    if not chart_players:
        names = ", ".join(result["player"] for result in active)
        raise HTTPException(
            status_code=404,
            detail=(
                f"No compared players could be aligned on the same profiles ({names}). "
                "Use profiles shared by everyone with data in the selected season, "
                "or compare players in the same position."
            ),
        )

    primary = chart_players[0]
    profile_drilldowns = (
        _merge_profile_drilldowns(
            active,
            canonical_labels,
        )
        if body.chart_source == "profiles"
        else []
    )
    if body.chart_source == "profiles" and profile_filters and not profile_drilldowns:
        all_warnings.append(
            "Profile factor breakdown unavailable — check Impect profile definitions."
        )
    elif body.chart_source == "profiles" and profile_drilldowns:
        for result in active:
            player_drilldowns = [
                item
                for item in result.get("profile_drilldowns", [])
                if any(
                    _normalize_profile_name(item.get("profile", ""))
                    == _normalize_profile_name(profile_filter)
                    for profile_filter in profile_filters
                )
            ]
            all_warnings.extend(
                _drilldown_coverage_warnings(
                    result.get("player", "Player"),
                    profile_filters,
                    player_drilldowns,
                )
            )

    port_vale_reference = None
    if body.chart_source == "profiles" and canonical_labels:
        reference_position = ""
        if body.player_positions:
            for player_key in player_keys:
                position_list = body.player_positions.get(player_key) or []
                if position_list:
                    reference_position = position_list[0]
                    break
        if not reference_position:
            reference_position = active[0].get("position") or ""
        if reference_position:
            port_vale_reference = _studio_port_vale_reference(
                reference_position,
                canonical_labels,
            )

    response: dict[str, Any] = {
        "players": chart_players,
        "player": primary["player"],
        "profiles": profile_filters,
        "profile_drilldowns": profile_drilldowns,
        "port_vale_reference": port_vale_reference,
        "chart_source": body.chart_source,
        "combine_seasons": body.combine_seasons or (
            body.last_n_seasons is not None and body.last_n_seasons > 1
        ),
        "last_n_seasons": body.last_n_seasons,
        "independent_seasons": body.independent_seasons,
        "seasons": active[0].get("seasons", []),
        "rows_in_cohort": total_cohort_rows,
        "source_urls": list(dict.fromkeys(all_source_urls)),
        "benchmark": benchmark_meta,
        "warnings": [warning for warning in dict.fromkeys(all_warnings) if warning],
        "labels": canonical_labels,
        "radar_values": primary["radar_values"],
        "pizza_values": primary["pizza_values"],
    }
    return response


def _player_iteration_maps(
    player_option: dict[str, Any],
) -> tuple[dict[int, int], dict[int, int]]:
    ids = {int(key): int(value) for key, value in player_option["ids_by_iteration"].items()}
    squads = {
        int(key): int(value)
        for key, value in player_option.get("squad_ids_by_iteration", {}).items()
    }
    return ids, squads


def _available_season_labels(
    ids_by_iteration: dict[int, int],
    squad_ids_by_iteration: dict[int, int],
    iteration_meta: dict[int, dict[str, str]],
) -> list[str]:
    labels: list[str] = []
    for iteration_id in ids_by_iteration:
        if squad_ids_by_iteration.get(iteration_id) is None:
            continue
        labels.append(iteration_meta.get(iteration_id, {}).get("label", f"Season {iteration_id}"))
    return labels


def _seasons_with_score_data(
    player_option: dict[str, Any],
    iteration_meta: dict[int, dict[str, str]],
    chart_source: ChartSource = "profiles",
    *,
    max_seasons: int | None = None,
) -> list[str]:
    ids_by_iteration, squad_ids_by_iteration = _player_iteration_maps(player_option)
    iteration_ids = (
        _recent_player_iteration_ids(player_option, iteration_meta, max_seasons)
        if max_seasons is not None
        else list(ids_by_iteration)
    )
    labeled: list[tuple[int, str]] = []
    for iteration_id in iteration_ids:
        player_id = ids_by_iteration.get(iteration_id)
        if player_id is None:
            continue
        if _player_has_score_data(
            iteration_id,
            int(player_id),
            squad_ids_by_iteration.get(iteration_id),
            player_option["name"],
            chart_source,
        ):
            labeled.append(
                (
                    iteration_id,
                    iteration_meta.get(iteration_id, {}).get("label", f"Season {iteration_id}"),
                )
            )
    labeled.sort(
        key=lambda item: _season_sort_key(
            iteration_meta.get(item[0], {}).get("season", "")
        ),
        reverse=True,
    )
    return [label for _, label in labeled]


def _profiles_for_player_option(
    player_option: dict[str, Any],
    iteration_ids: list[int],
    iteration_meta: dict[int, dict[str, str]],
    positions: list[str],
    min_games: float,
) -> set[str]:
    ids_by_iteration, squad_ids_by_iteration = _player_iteration_maps(player_option)
    profiles: set[str] = set()

    for iteration_id in iteration_ids:
        if iteration_id not in ids_by_iteration:
            continue
        player_id = ids_by_iteration.get(iteration_id)
        squad_id = squad_ids_by_iteration.get(iteration_id)
        if player_id is None:
            continue
        try:
            resolved_positions = _validate_positions(positions) if positions else []
            row, _, _ = _find_player_score_row(
                iteration_id,
                player_id,
                squad_id,
                player_option["name"],
                {},
                "profiles",
                resolved_positions,
                min_games,
            )
            if row is not None:
                profiles.update(
                    _normalize_profile_name(score.get("profileName"))
                    for score in _profile_scores_for_player(row)
                    if _is_pv_profile(score.get("profileName"))
                )
        except HTTPException:
            continue

    return profiles


def _shared_profiles_for_players(
    player_keys: list[str],
    player_options: list[dict[str, Any]],
    primary_requested_ids: list[int],
    iteration_meta: dict[int, dict[str, str]],
    positions: list[str],
    min_games: float,
    independent_seasons: bool = False,
    player_seasons: dict[str, list[int]] | None = None,
    player_positions: dict[str, list[str]] | None = None,
    last_n_seasons: int | None = None,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    player_seasons = player_seasons or {}
    player_positions = player_positions or {}
    profile_sets: list[set[str]] = []
    player_profile_details: list[tuple[str, list[str], int]] = []

    for player_key in player_keys:
        player_option = next(
            (option for option in player_options if option["key"] == player_key),
            None,
        )
        if player_option is None:
            warnings.append(f"Player '{player_key}' not found in Impect catalog.")
            continue

        player_position_filter = (
            _validate_positions(player_positions[player_key])
            if player_positions.get(player_key)
            else positions
        )
        custom_season_ids = [
            int(iteration_id)
            for iteration_id in player_seasons.get(player_key, [])
            if str(iteration_id).isdigit() or isinstance(iteration_id, int)
        ]
        if independent_seasons and custom_season_ids:
            iteration_ids = _iteration_ids_for_player_key(
                player_key,
                player_options,
                primary_requested_ids,
                iteration_meta,
                independent_seasons,
                player_seasons,
            )
        elif last_n_seasons is not None and last_n_seasons > 0:
            iteration_ids = _last_n_iteration_ids_for_player(
                player_option,
                iteration_meta,
                last_n_seasons,
                player_position_filter,
                "profiles",
            )
        else:
            iteration_ids = _iteration_ids_for_player_key(
                player_key,
                player_options,
                primary_requested_ids,
                iteration_meta,
                independent_seasons,
                player_seasons,
            )
        player_profiles = _profiles_for_player_option(
            player_option,
            iteration_ids,
            iteration_meta,
            player_position_filter,
            min_games,
        )
        if not player_profiles:
            warnings.append(
                f"{player_option['name']} has no profiles for the selected season(s) "
                f"across their league."
            )
            continue

        profile_sets.append(player_profiles)
        player_profile_details.append(
            (player_option["name"], player_position_filter, len(player_profiles))
        )

    if not profile_sets:
        return [], warnings

    shared = profile_sets[0].copy()
    for other in profile_sets[1:]:
        shared &= other
    if not shared and len(player_profile_details) >= 2:
        parts = []
        for name, position_filter, count in player_profile_details:
            position_code = (
                _position_abbrev(position_filter[0]) if position_filter else "?"
            )
            parts.append(f"{name} ({position_code}) has {count}")
        warnings.append(
            "No shared PV profiles: "
            + "; ".join(parts)
            + " — all players need the same position."
        )
    return sorted(shared), warnings


def _resolve_comparison_profiles(
    body: ChartRequest,
    player_keys: list[str],
    player_options: list[dict[str, Any]],
    primary_requested_ids: list[int],
    iteration_meta: dict[int, dict[str, str]],
) -> tuple[list[str], list[str]]:
    selected = _selected_profiles(body)
    if len(selected) >= 2:
        return selected, []

    positions = _validate_positions(body.positions) if body.positions else []
    shared, shared_warnings = _shared_profiles_for_players(
        player_keys,
        player_options,
        primary_requested_ids,
        iteration_meta,
        positions,
        body.min_games,
        body.independent_seasons,
        body.player_seasons,
        body.player_positions,
        body.last_n_seasons,
    )

    warnings = list(shared_warnings)
    if selected:
        usable = [profile for profile in selected if profile in shared]
        dropped = [profile for profile in selected if profile not in shared]
        if dropped:
            warnings.append(
                "Profiles skipped for some players (not available to all): "
                + ", ".join(dropped)
            )
        return usable, warnings

    return shared, warnings


def _query_player_keys(body: ImpectQuery) -> list[str]:
    player_keys = [key.strip() for key in body.player_keys if key and key.strip()]
    if not player_keys and body.player_key:
        player_keys = [body.player_key.strip()]
    return player_keys


def _profiles_for_player(body: ImpectQuery) -> list[str]:
    player_keys = _query_player_keys(body)
    if not player_keys:
        return []

    iteration_meta = _iteration_meta_map()
    player_options = _player_options_for_keys(player_keys, body)
    selected = next((option for option in player_options if option["key"] == player_keys[0]), None)
    if not selected:
        return []

    source_iteration_ids = body.iteration_ids or selected.get("chartable_season_ids", [])

    if len(player_keys) > 1:
        profiles, _ = _shared_profiles_for_players(
            player_keys,
            player_options,
            source_iteration_ids,
            iteration_meta,
            _validate_positions(body.positions) if body.positions else [],
            body.min_games,
            body.independent_seasons,
            body.player_seasons,
            body.player_positions,
            body.last_n_seasons,
        )
        return profiles

    iteration_ids = _resolve_player_iteration_ids(
        player_keys[0],
        body,
        player_options,
        source_iteration_ids,
        iteration_meta,
        "profiles",
    )
    single_positions = _requested_positions_for_player(body, player_keys[0])
    return sorted(
        _profiles_for_player_option(
            selected,
            iteration_ids,
            iteration_meta,
            single_positions,
            body.min_games,
        )
    )


def _iteration_ids_for_player_lookup(
    body: ImpectQuery,
    player_keys: list[str],
) -> list[int]:
    iteration_ids: set[int] = set(body.iteration_ids)
    for season_ids in body.player_seasons.values():
        for season_id in season_ids:
            if isinstance(season_id, int):
                iteration_ids.add(season_id)
            elif str(season_id).isdigit():
                iteration_ids.add(int(season_id))

    for player_key in player_keys:
        catalog_entry = body.player_catalog.get(player_key, {})
        for iteration_id_str in catalog_entry.get("ids_by_iteration", {}):
            if str(iteration_id_str).isdigit():
                iteration_ids.add(int(iteration_id_str))

    return sorted(iteration_ids)


def _player_options_for_keys(
    player_keys: list[str],
    body: ImpectQuery,
) -> list[dict[str, Any]]:
    iteration_meta = _iteration_meta_map()
    lookup_iteration_ids = _iteration_ids_for_player_lookup(body, player_keys)
    label_map = _iteration_label_map(lookup_iteration_ids)

    if body.player_catalog:
        options: list[dict[str, Any]] = []
        for player_key in player_keys:
            catalog_entry = body.player_catalog.get(player_key)
            if not catalog_entry:
                continue
            impect_player_id: int | None = None
            if "|" in player_key:
                suffix = player_key.rsplit("|", 1)[-1]
                if suffix.isdigit():
                    impect_player_id = int(suffix)
            option = {
                "key": player_key,
                "name": str(catalog_entry.get("name", player_key)).strip() or player_key,
                "impect_player_id": impect_player_id,
                "ids_by_iteration": catalog_entry.get("ids_by_iteration", {}),
                "squad_ids_by_iteration": catalog_entry.get("squad_ids_by_iteration", {}),
            }
            _resolve_squad_ids_for_option(option)
            options.append(option)
        catalog_iteration_ids = set(lookup_iteration_ids)
        for option in options:
            catalog_iteration_ids.update(
                int(iteration_id_str)
                for iteration_id_str in option.get("ids_by_iteration", {})
                if str(iteration_id_str).isdigit()
            )
        catalog_label_map = _iteration_label_map(sorted(catalog_iteration_ids))
        return _enrich_player_catalog(
            options,
            catalog_label_map,
            iteration_meta,
            expand_history=False,
        )

    if not lookup_iteration_ids:
        lookup_iteration_ids = _player_catalog_ids()

    players_by_iteration = _fetch_players_parallel(lookup_iteration_ids)
    merged = _merge_player_options(lookup_iteration_ids, players_by_iteration)
    by_key = {option["key"]: option for option in merged}

    missing_keys = [key for key in player_keys if key not in by_key]
    if missing_keys:
        expanded_ids: set[int] = set(lookup_iteration_ids)
        for option in merged:
            expanded_ids.update(int(key) for key in option["ids_by_iteration"])
        if expanded_ids != set(lookup_iteration_ids):
            expanded_body = body.model_copy(
                update={"iteration_ids": sorted(expanded_ids)}
            )
            return _player_options_for_keys(player_keys, expanded_body)

    resolved: list[dict[str, Any]] = []
    for key in player_keys:
        option, _ = _resolve_player_catalog_option(key, by_key)
        if option is not None:
            _resolve_squad_ids_for_option(option)
            resolved.append(option)
    return _enrich_player_catalog(resolved, label_map, iteration_meta, expand_history=False)


def _position_minutes_for_player(
    iteration_id: int,
    player_id: int,
    squad_id: int | None,
    player_name: str,
    position: str,
    chart_source: ChartSource,
    min_games: float,
) -> float:
    fetch_squad = (
        _fetch_profile_scores if chart_source == "profiles" else _fetch_player_scores
    )
    effective_squad = _resolve_squad_id_for_player(
        iteration_id,
        player_id,
        player_name,
        squad_id,
        chart_source,
    )
    if effective_squad is None:
        return 0.0
    try:
        score_rows, _ = fetch_squad(
            iteration_id, effective_squad, [position], min_games
        )
    except HTTPException as exc:
        if exc.status_code in {404, 403, 429}:
            return 0.0
        raise
    row = _pick_score_row(score_rows, player_id, player_name, {})
    if row is None:
        return 0.0
    return float(_play_duration_minutes(row) or 0.0)


def _aggregate_positions_for_player(
    player_option: dict[str, Any],
    iteration_ids: list[int],
    chart_source: ChartSource,
    min_games: float,
) -> list[dict[str, Any]]:
    if not iteration_ids:
        return []

    ids_by_iteration, squad_ids_by_iteration = _player_iteration_maps(player_option)
    primary_iteration_id = iteration_ids[0]
    player_id = ids_by_iteration.get(primary_iteration_id)
    if player_id is None:
        return []

    scanned = _scan_positions_for_player(
        primary_iteration_id,
        player_id,
        squad_ids_by_iteration.get(primary_iteration_id),
        player_option["name"],
        {},
        chart_source,
        min_games,
    )
    if not scanned:
        return []

    aggregated: dict[str, dict[str, Any]] = {}
    for item in scanned:
        position = item["position"]
        minutes = float(item["minutes"])
        aggregated[position] = {
            "position": position,
            "label": item["label"],
            "minutes": minutes,
            "season_count": 1 if minutes > 0 else 0,
        }

    for iteration_id in iteration_ids[1:]:
        season_player_id = ids_by_iteration.get(iteration_id)
        if season_player_id is None:
            continue
        squad_id = squad_ids_by_iteration.get(iteration_id)
        for position, entry in aggregated.items():
            minutes = _position_minutes_for_player(
                iteration_id,
                season_player_id,
                squad_id,
                player_option["name"],
                position,
                chart_source,
                min_games,
            )
            if minutes > 0:
                entry["minutes"] += minutes
                entry["season_count"] += 1

    results = list(aggregated.values())
    results.sort(
        key=lambda item: (
            -float(item["minutes"]),
            ALLOWED_POSITIONS.index(item["position"]),
        )
    )
    return results


def _build_player_position_entry(
    player_key: str,
    player_option: dict[str, Any],
    body: ImpectQuery,
    player_options: list[dict[str, Any]],
    iteration_meta: dict[int, dict[str, str]],
    source_iteration_ids: list[int],
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    iteration_ids = _iteration_ids_for_player_key(
        player_key,
        player_options,
        source_iteration_ids,
        iteration_meta,
        body.independent_seasons,
        body.player_seasons,
        body.chart_source,
        require_score_row=False,
    )
    if not iteration_ids:
        return (
            {
                "name": player_option["name"],
                "positions": [],
                "default_position": "",
                "default_label": "",
            },
            warnings,
        )

    iteration_id = iteration_ids[0]
    ids_by_iteration, squad_ids_by_iteration = _player_iteration_maps(player_option)
    player_id = ids_by_iteration.get(iteration_id)
    squad_id = squad_ids_by_iteration.get(iteration_id)
    if player_id is not None:
        resolved_squad = _resolve_squad_id_for_player(
            iteration_id,
            player_id,
            player_option["name"],
            squad_id,
            body.chart_source,
        )
        if resolved_squad is not None:
            squad_id = resolved_squad
            squad_ids_by_iteration[iteration_id] = resolved_squad
    if player_id is None:
        return (
            {
                "name": player_option["name"],
                "positions": [],
                "default_position": "",
                "default_label": "",
            },
            warnings,
        )

    requested = (
        _validate_positions(body.player_positions[player_key])
        if body.player_positions.get(player_key)
        else []
    )
    requested_iteration_id = iteration_id
    combine_seasons = body.last_n_seasons is not None and body.last_n_seasons > 1
    positions_out: list[dict[str, Any]] = []

    if combine_seasons:
        scan_iteration_ids = _recent_player_iteration_ids(
            player_option,
            iteration_meta,
            body.last_n_seasons or POSITION_LOOKUP_MAX_SEASONS,
        )
        if scan_iteration_ids:
            positions_out = _aggregate_positions_for_player(
                player_option,
                scan_iteration_ids,
                "metrics",
                body.min_games,
            )
    else:
        scanned = _scan_positions_for_player(
            iteration_id,
            player_id,
            squad_id,
            player_option["name"],
            {},
            "metrics",
            body.min_games,
        )
        positions_out = [
            {
                "position": item["position"],
                "label": item["label"],
                "minutes": item["minutes"],
            }
            for item in scanned
        ]

    seasons_with_data: list[str] = []
    suggested_iteration_id: int | None = None

    if not positions_out:
        suggested_ids = _best_iteration_ids_for_player(
            player_option,
            iteration_meta,
            "metrics",
            max_seasons=POSITION_LOOKUP_MAX_SEASONS,
        )
        suggested_iteration_id = suggested_ids[0] if suggested_ids else None

    if not positions_out and suggested_iteration_id is not None:
        fallback_id = suggested_iteration_id
        if fallback_id != iteration_id:
            old_label = iteration_meta.get(iteration_id, {}).get("label", "")
            new_label = iteration_meta.get(fallback_id, {}).get("label", "")
            iteration_id = fallback_id
            player_id = ids_by_iteration.get(iteration_id)
            squad_id = squad_ids_by_iteration.get(iteration_id)
            if player_id is not None:
                scanned = _scan_positions_for_player(
                    iteration_id,
                    player_id,
                    squad_id,
                    player_option["name"],
                    {},
                    "metrics",
                    body.min_games,
                )
                positions_out = [
                    {
                        "position": item["position"],
                        "label": item["label"],
                        "minutes": item["minutes"],
                    }
                    for item in scanned
                ]
                warnings.append(
                    f"{player_option['name']}: no position data for {old_label}; "
                    f"using {new_label} instead."
                )

    if not positions_out:
        seasons_with_data = _seasons_with_score_data(
            player_option,
            iteration_meta,
            "metrics",
            max_seasons=POSITION_LOOKUP_MAX_SEASONS,
        )
        requested_label = iteration_meta.get(requested_iteration_id, {}).get("label", "")
        if seasons_with_data:
            warnings.append(
                f"{player_option['name']} has no position data for {requested_label}. "
                f"Data available in: {', '.join(seasons_with_data)}."
            )
        else:
            warnings.append(
                f"{player_option['name']} has no Impect score data in any loaded season."
            )

    default_position = ""
    default_label = ""
    if requested:
        match = next(
            (item for item in positions_out if item["position"] in requested),
            None,
        )
        if match:
            default_position = match["position"]
            default_label = match["label"]
        elif positions_out:
            warnings.append(
                f"{player_option['name']}: selected position not available; "
                f"using {_position_label(positions_out[0]['position'])} instead."
            )
    if not default_position and positions_out:
        default_position = positions_out[0]["position"]
        default_label = positions_out[0]["label"]

    low_data_hint = ""
    if len(positions_out) > 1 and positions_out[0]["minutes"] < BENCHMARK_MIN_MINUTES:
        better = next(
            (
                item
                for item in positions_out[1:]
                if item["minutes"] >= BENCHMARK_MIN_MINUTES
            ),
            None,
        )
        if better:
            low_data_hint = (
                f"Auto-selected {_position_label(default_position)} "
                f"({positions_out[0]['minutes']:.0f} min). "
                f"{better['label']} has {better['minutes']:.0f} min — consider switching."
            )

    season_label = iteration_meta.get(iteration_id, {}).get("label", "")
    if combine_seasons and positions_out:
        season_count = max(
            int(item.get("season_count", 0)) for item in positions_out
        )
        if season_count > 1:
            season_label = f"Combined up to {season_count} seasons"

    return (
        {
            "name": player_option["name"],
            "positions": positions_out,
            "default_position": default_position,
            "default_label": default_label,
            "iteration_id": iteration_id,
            "season_label": season_label,
            "seasons_with_data": seasons_with_data,
            "suggested_iteration_id": suggested_iteration_id,
            "hint": low_data_hint,
            "combined_seasons": combine_seasons,
        },
        warnings,
    )


def _player_positions_payload(body: ImpectQuery) -> dict[str, Any]:
    player_keys = [key.strip() for key in body.player_keys if key and key.strip()]
    if not player_keys and body.player_key:
        player_keys = [body.player_key.strip()]
    if not player_keys:
        return {"players": {}}

    iteration_meta = _iteration_meta_map()
    player_options = _player_options_for_keys(player_keys, body)
    options_by_key = {option["key"]: option for option in player_options}

    primary, _ = _resolve_player_catalog_option(player_keys[0], options_by_key)
    source_iteration_ids = body.iteration_ids or (
        primary.get("chartable_season_ids", []) if primary else []
    )

    players_payload: dict[str, Any] = {}
    warnings: list[str] = []
    resolved_entries: list[tuple[str, dict[str, Any]]] = []

    for player_key in player_keys:
        option, resolve_warning = _resolve_player_catalog_option(player_key, options_by_key)
        if option is None:
            if resolve_warning:
                warnings.append(resolve_warning)
            continue
        resolved_entries.append((player_key, option))

    max_workers = min(2, max(len(resolved_entries), 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _build_player_position_entry,
                player_key,
                option,
                body,
                player_options,
                iteration_meta,
                source_iteration_ids,
            ): player_key
            for player_key, option in resolved_entries
        }
        for future in as_completed(futures):
            player_key = futures[future]
            entry, entry_warnings = future.result()
            players_payload[player_key] = entry
            warnings.extend(entry_warnings)

    return {"players": players_payload, "warnings": warnings}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html_path = SCOUTING_DIR / "hub.html"
    if not html_path.exists():
        raise HTTPException(status_code=503, detail="Hub page not found at standalone/hub.html")
    return HTMLResponse(
        html_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/hub", response_class=HTMLResponse)
def analysis_hub() -> HTMLResponse:
    return HTMLResponse(
        '<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0;url=/" /></head>'
        '<body><a href="/">Go to analysis hub</a></body></html>',
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/studio", response_class=HTMLResponse)
def player_studio() -> HTMLResponse:
    html = (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class EnsureServerRequest(BaseModel):
    server: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)


class PlayerPhotoUploadRequest(BaseModel):
    player_name: str = Field(..., min_length=1)
    image_data: str = Field(..., min_length=32)


@app.get("/api/servers")
def list_analysis_servers() -> dict[str, Any]:
    from app.server_launcher import list_servers

    return {"servers": list_servers()}


@app.post("/api/server/ensure")
def ensure_analysis_server(
    request: Request,
    body: EnsureServerRequest,
) -> dict[str, Any]:
    """Start a sibling analysis server if it is not already healthy."""
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Server launch is only allowed from localhost.")

    from app.server_launcher import ensure_server

    return ensure_server(server_id=body.server, port=body.port)


@app.post("/api/server/restart")
def restart_server(request: Request) -> dict[str, str]:
    """Restart (or start) the local uvicorn process on port 8000."""
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Restart is only allowed from localhost.")

    script = BASE_DIR / "restart.sh"
    if not script.is_file():
        raise HTTPException(status_code=503, detail="restart.sh not found.")

    subprocess.Popen(
        ["/bin/bash", str(script)],
        cwd=str(BASE_DIR),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"status": "restarting"}


@app.get("/api/iterations")
def list_iterations() -> dict[str, Any]:
    iterations = _fetch_iterations()
    competitions = sorted(ALLOWED_COMPETITIONS)
    return {"iterations": iterations, "competitions": competitions}


@app.post("/api/players")
def list_players(body: PlayerCatalogRequest) -> dict[str, Any]:
    search = (body.search or "").strip()
    if not search and not body.competition_name:
        return {
            "players": [],
            "player_count": 0,
            "season_count": 0,
            "message": "Type a player name to search across our five leagues.",
        }

    iteration_ids = _catalog_iteration_ids(body.competition_name, search or None)
    if not iteration_ids:
        return {"players": [], "player_count": 0, "season_count": 0}

    players_by_iteration = _fetch_players_parallel(iteration_ids)
    label_map = _iteration_label_map(iteration_ids)
    iteration_meta = _iteration_meta_map()
    merged = _merge_player_options(iteration_ids, players_by_iteration)

    if search:
        merged = [
            player for player in merged if _player_matches_search(player["name"], search)
        ]

    label_map = _iteration_label_map(iteration_ids)
    # Full history expansion runs when a player is added to comparison, not on search.
    players = _enrich_player_catalog(merged, label_map, iteration_meta, expand_history=False)

    message = None
    if search and not players:
        message = (
            f'No players matched "{search}". '
            "Check spelling (e.g. Elliot vs Elliott) and try the full name."
        )

    return {
        "players": players,
        "player_count": len(players),
        "season_count": len(iteration_ids),
        "search_scope": "all_leagues" if search and not body.competition_name else "competition",
        "message": message,
    }


@app.post("/api/player-history")
def fetch_player_history(body: PlayerHistoryRequest) -> dict[str, Any]:
    player_key = body.player_key.strip()
    if not player_key:
        raise HTTPException(status_code=400, detail="player_key is required")

    iteration_meta = _iteration_meta_map()
    catalog_entry = body.player_catalog.get(player_key, {})
    impect_player_id: int | None = None
    catalog_player_id = catalog_entry.get("impect_player_id")
    if catalog_player_id is not None:
        impect_player_id = int(catalog_player_id)
    elif "|" in player_key:
        suffix = player_key.rsplit("|", 1)[-1]
        if suffix.isdigit():
            impect_player_id = int(suffix)

    option = {
        "key": player_key,
        "name": str(catalog_entry.get("name", player_key)).strip() or player_key,
        "impect_player_id": impect_player_id,
        "ids_by_iteration": catalog_entry.get("ids_by_iteration", {}),
        "squad_ids_by_iteration": catalog_entry.get("squad_ids_by_iteration", {}),
    }
    _expand_player_history(option, iteration_meta)
    full_label_map = _iteration_label_map(
        _latest_iteration_ids(
            _fetch_iterations(),
            seasons_per_competition=PLAYER_HISTORY_SEASONS_PER_COMPETITION,
        )
    )
    enriched = _enrich_player_catalog([option], full_label_map, iteration_meta, expand_history=False)
    if not enriched:
        raise HTTPException(status_code=404, detail="Player not found in Impect catalog.")

    player = enriched[0]
    return {
        "player": player,
        "season_count": len(player.get("seasons", [])),
        "chartable_season_count": len(player.get("chartable_season_ids", [])),
    }


@app.post("/api/player-positions")
def fetch_player_positions(body: ImpectQuery) -> dict[str, Any]:
    return _player_positions_payload(body)


@app.post("/api/options")
def fetch_options(body: ImpectQuery) -> dict[str, Any]:
    player_keys = _query_player_keys(body)
    if len(player_keys) > 1:
        iteration_meta = _iteration_meta_map()
        player_options = _player_options_for_keys(player_keys, body)
        primary = next(
            (option for option in player_options if option["key"] == player_keys[0]),
            None,
        )
        source_iteration_ids = body.iteration_ids or (
            primary.get("chartable_season_ids", []) if primary else []
        )
        positions = _validate_positions(body.positions) if body.positions else []
        profiles, warnings = _shared_profiles_for_players(
            player_keys,
            player_options,
            source_iteration_ids,
            iteration_meta,
            positions,
            body.min_games,
            body.independent_seasons,
            body.player_seasons,
            body.player_positions,
            body.last_n_seasons,
        )
        return {
            "profiles": profiles,
            "warnings": warnings,
            "profile_scope": "shared",
        }

    profiles = _profiles_for_player(body) if player_keys else []
    return {"profiles": profiles, "profile_scope": "player"}


@app.post("/api/player-photo/upload")
def upload_player_photo(body: PlayerPhotoUploadRequest) -> dict[str, str]:
    payload = body.image_data.strip()
    if "," in payload:
        payload = payload.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid image data.") from exc

    try:
        saved_path = save_local_player_photo(body.player_name.strip(), image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    photo_url = _player_photo_api_url(body.player_name.strip())
    return {
        "photo_url": photo_url or f"/api/player-photo?name={quote(body.player_name.strip())}",
        "filename": saved_path.name,
    }


@app.get("/api/player-photo")
def player_photo(name: str = Query(..., min_length=1)) -> Response:
    local_path = resolve_local_photo_path(name)
    if local_path is not None:
        return FileResponse(local_path)

    source_url = resolve_player_photo_url(name)
    if not source_url:
        raise HTTPException(status_code=404, detail=f"No photo found for {name}")

    try:
        image_bytes, content_type = fetch_photo_bytes(source_url)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=image_bytes, media_type=content_type)


@app.post("/api/charts")
def build_chart_data(body: ChartRequest) -> dict[str, Any]:
    return _build_season_charts(body)


def _safe_export_filename(filename: str, default_ext: str = ".pdf") -> str:
    stem = Path(filename).stem or "impect-report"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-") or "impect-report"
    suffix = Path(filename).suffix or default_ext
    return f"{slug}{suffix}"


def _desktop_export_dir() -> Path:
    custom = os.getenv("EXPORT_DESKTOP_PATH", "").strip()
    target = Path(custom).expanduser() if custom else Path.home() / "Desktop"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _unique_desktop_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while True:
        candidate = directory / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _save_export_to_desktop(file_bytes: bytes, filename: str) -> Path | None:
    try:
        path = _unique_desktop_path(_desktop_export_dir(), filename)
        path.write_bytes(file_bytes)
        return path
    except OSError:
        return None


@app.post("/api/export-pdf")
def export_chart_pdf(body: PdfExportRequest) -> Response:
    try:
        pdf_bytes = build_coach_report_pdf(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = _safe_export_filename(body.filename)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    saved_path = _save_export_to_desktop(pdf_bytes, filename)
    if saved_path is not None:
        headers["X-Saved-Desktop-Path"] = str(saved_path)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers=headers,
    )


@app.post("/api/export-pptx")
def export_chart_slides(body: PdfExportRequest) -> Response:
    try:
        pptx_bytes = build_coach_slides_pptx(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = _safe_export_filename(body.filename, default_ext=".pptx")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    saved_path = _save_export_to_desktop(pptx_bytes, filename)
    if saved_path is not None:
        headers["X-Saved-Desktop-Path"] = str(saved_path)
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers=headers,
    )


from app.post_match.routes import register_post_match_routes
from app.pre_match import register_pre_match_routes
from app.pre_match_handout import register_pre_match_handout_routes
from app.scouting import register_scouting_routes, SCOUTING_DIR
from app.squad_review import register_squad_review_routes
from app.squad_planner import register_squad_planner_routes
from app.squad_balance import register_squad_balance_routes
from app.fixture_planner import register_fixture_planner_routes
from app.xg_chance_analysis import register_xg_chance_analysis_routes
from app.club_strategy import register_club_strategy_routes
from app.availability_tracker import register_availability_tracker_routes
from app.scouting_address import register_scouting_address_routes

register_post_match_routes(app)
register_scouting_routes(app)
register_squad_review_routes(app)
register_squad_planner_routes(app)
register_squad_balance_routes(app)
register_pre_match_routes(app)
register_pre_match_handout_routes(app)
register_fixture_planner_routes(app)
register_xg_chance_analysis_routes(app)
register_club_strategy_routes(app)
register_availability_tracker_routes(app)
register_scouting_address_routes(app)
