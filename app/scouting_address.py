from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.scouting import SCOUTING_DIR

from app.paths import STADIUMS_PATH

LEAGUE_META: dict[str, dict[str, str]] = {
    "Championship": {"color": "#ef4444", "label": "Championship"},
    "League One": {"color": "#3d8bfd", "label": "League One"},
    "League Two": {"color": "#34d399", "label": "League Two"},
    "National League": {"color": "#fbbf24", "label": "National League"},
    "National League North": {"color": "#f97316", "label": "NL North"},
    "National League South": {"color": "#ec4899", "label": "NL South"},
    "Scottish Prem": {"color": "#a78bfa", "label": "Scottish Prem"},
    "Scottish Champ": {"color": "#6366f1", "label": "Scottish Champ"},
}

LEAGUE_TO_FIXTURE: dict[str, str] = {
    "Championship": "Championship",
    "League One": "League One",
    "League Two": "League Two",
    "National League": "National League",
    "Scottish Prem": "Scottish Prem",
}

OSRM_TABLE_URL = "https://router.project-osrm.org/table/v1/driving"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
POSTCODES_IO_URL = "https://api.postcodes.io/postcodes"
USER_AGENT = "ImpectScoutingAddressTool/1.0 (Port Vale FC scouting)"
UK_POSTCODE_RE = re.compile(
    r"^\s*[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2}\s*$",
    re.IGNORECASE,
)

_http = requests.Session()
_http.headers.update({"User-Agent": USER_AGENT})


class ReachableRequest(BaseModel):
    lat: float
    lng: float
    max_minutes: int = Field(default=60, ge=5, le=180)
    leagues: list[str] | None = None


def _load_stadiums() -> list[dict[str, Any]]:
    if not STADIUMS_PATH.exists():
        raise HTTPException(status_code=500, detail="Stadium database not found.")
    with STADIUMS_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return [row for row in data if row.get("lat") is not None and row.get("lng") is not None]


def _http_get_json(url: str, *, params: dict[str, Any] | None = None, timeout: float = 20.0) -> Any:
    response = _http.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _normalize_postcode(query: str) -> str | None:
    compact = re.sub(r"\s+", "", query.strip().upper())
    if len(compact) < 5 or len(compact) > 8:
        return None
    outward = compact[:-3]
    inward = compact[-3:]
    candidate = f"{outward} {inward}"
    return candidate if UK_POSTCODE_RE.match(candidate) else None


def _geocode_uk_postcode(postcode: str) -> dict[str, Any]:
    response = _http.get(f"{POSTCODES_IO_URL}/{requests.utils.quote(postcode)}", timeout=15)
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Postcode not found: {postcode}")
    response.raise_for_status()
    payload = response.json()
    row = payload.get("result") or {}
    if row.get("latitude") is None or row.get("longitude") is None:
        raise HTTPException(status_code=404, detail=f"Postcode not found: {postcode}")
    parish = ", ".join(part for part in (row.get("admin_ward"), row.get("postcode")) if part)
    return {
        "lat": float(row["latitude"]),
        "lng": float(row["longitude"]),
        "label": parish or postcode,
        "source": "postcodes.io",
    }


def _geocode_nominatim(query: str) -> dict[str, Any]:
    results = _http_get_json(
        NOMINATIM_URL,
        params={
            "q": query,
            "format": "json",
            "limit": 1,
            "countrycodes": "gb",
        },
        timeout=20.0,
    )
    if not results:
        raise HTTPException(status_code=404, detail=f"Address not found: {query}")
    row = results[0]
    return {
        "lat": float(row["lat"]),
        "lng": float(row["lon"]),
        "label": row.get("display_name", query),
        "source": "nominatim",
    }


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _estimate_drive_minutes(distance_km: float) -> int:
    # UK average ~55 mph / 88 km/h for fallback when OSRM unavailable
    if distance_km <= 0:
        return 0
    return max(1, round((distance_km / 88.0) * 60))


def _geocode_address(query: str) -> dict[str, Any]:
    cleaned = query.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Address is required.")

    postcode = _normalize_postcode(cleaned)
    if postcode:
        try:
            return _geocode_uk_postcode(postcode)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        except requests.RequestException:
            pass

    try:
        return _geocode_nominatim(cleaned)
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail="Geocoding service unavailable. Check your connection and try again.",
        ) from exc


def _osrm_durations_seconds(origin_lat: float, origin_lng: float, destinations: list[tuple[float, float]]) -> list[int | None]:
    if not destinations:
        return []

    # OSRM public API limits URL length — batch in chunks of 50 destinations.
    batch_size = 50
    merged: list[int | None] = []
    for start in range(0, len(destinations), batch_size):
        chunk = destinations[start : start + batch_size]
        coords = ";".join([f"{origin_lng},{origin_lat}"] + [f"{lng},{lat}" for lat, lng in chunk])
        url = f"{OSRM_TABLE_URL}/{coords}"
        try:
            payload = _http_get_json(
                url,
                params={"sources": "0", "annotations": "duration"},
                timeout=30.0,
            )
        except requests.RequestException:
            merged.extend([None] * len(chunk))
            continue

        if payload.get("code") != "Ok":
            merged.extend([None] * len(chunk))
            continue

        durations = payload.get("durations") or []
        if not durations or not durations[0]:
            merged.extend([None] * len(chunk))
            continue
        merged.extend(
            int(value) if value is not None else None for value in durations[0][1:]
        )
    return merged


def _travel_times(origin_lat: float, origin_lng: float, stadiums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    destinations = [(row["lat"], row["lng"]) for row in stadiums]
    osrm_seconds = _osrm_durations_seconds(origin_lat, origin_lng, destinations)

    enriched: list[dict[str, Any]] = []
    for index, stadium in enumerate(stadiums):
        drive_minutes: int | None = None
        source = "estimate"
        if index < len(osrm_seconds) and osrm_seconds[index] is not None:
            drive_minutes = max(1, round(osrm_seconds[index] / 60))
            source = "osrm"
        else:
            distance_km = _haversine_km(origin_lat, origin_lng, stadium["lat"], stadium["lng"])
            drive_minutes = _estimate_drive_minutes(distance_km)

        enriched.append(
            {
                **stadium,
                "drive_minutes": drive_minutes,
                "drive_source": source,
            }
        )
    return enriched


def scouting_address_meta() -> dict[str, Any]:
    stadiums = _load_stadiums()
    by_league: dict[str, int] = {}
    for row in stadiums:
        by_league[row["league"]] = by_league.get(row["league"], 0) + 1
    return {
        "leagues": [
            {"id": league_id, **meta, "count": by_league.get(league_id, 0)}
            for league_id, meta in LEAGUE_META.items()
        ],
        "stadium_count": len(stadiums),
        "default_max_minutes": 60,
        "seasons": ["26/27", "25/26"],
    }


def register_scouting_address_routes(app: FastAPI) -> None:
    @app.get("/scouting-address", response_class=HTMLResponse)
    def scouting_address_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "scouting-address.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Scouting address UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/scouting-address/meta")
    def scouting_address_meta_route() -> dict[str, Any]:
        return scouting_address_meta()

    @app.get("/api/scouting-address/stadiums")
    def scouting_address_stadiums_route(
        leagues: str | None = Query(default=None, description="Comma-separated league ids"),
    ) -> dict[str, Any]:
        stadiums = _load_stadiums()
        if leagues:
            allowed = {part.strip() for part in leagues.split(",") if part.strip()}
            stadiums = [row for row in stadiums if row["league"] in allowed]
        return {"stadiums": stadiums}

    @app.get("/api/scouting-address/geocode")
    def scouting_address_geocode_route(q: str = Query(min_length=3)) -> dict[str, Any]:
        return _geocode_address(q.strip())

    @app.post("/api/scouting-address/reachable")
    def scouting_address_reachable_route(body: ReachableRequest) -> dict[str, Any]:
        stadiums = _load_stadiums()
        if body.leagues:
            allowed = set(body.leagues)
            stadiums = [row for row in stadiums if row["league"] in allowed]

        timed = _travel_times(body.lat, body.lng, stadiums)
        reachable = [row for row in timed if row["drive_minutes"] <= body.max_minutes]
        reachable.sort(key=lambda row: row["drive_minutes"])
        return {
            "origin": {"lat": body.lat, "lng": body.lng},
            "max_minutes": body.max_minutes,
            "reachable": reachable,
            "reachable_count": len(reachable),
            "total_checked": len(timed),
        }
