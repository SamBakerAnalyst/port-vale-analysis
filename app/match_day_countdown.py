"""Match Day Countdown — kick-off clock plus next dressing-room timing."""

from __future__ import annotations

import time
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app.home_dashboard import build_port_vale_fixtures
from app.paths import STANDALONE_DIR

# Vale Park, Burslem — default home ground weather.
_VALE_PARK = {"lat": 53.0497, "lon": -2.1928, "label": "Vale Park"}
_WEATHER_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_WEATHER_TTL = 10 * 60

_WMO: dict[int, str] = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Showers",
    82: "Heavy showers",
    85: "Snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm",
    99: "Thunderstorm",
}


def _wmo_label(code: Any) -> str:
    try:
        return _WMO.get(int(code), "—")
    except (TypeError, ValueError):
        return "—"


def _geocode_uk(name: str) -> dict[str, Any] | None:
    clean = (name or "").strip()
    if not clean:
        return None
    try:
        res = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": clean, "count": 3, "language": "en", "format": "json"},
            timeout=8,
        )
        res.raise_for_status()
        results = (res.json() or {}).get("results") or []
    except Exception:
        return None
    for row in results:
        if str(row.get("country_code") or "").upper() == "GB":
            return {
                "lat": float(row["latitude"]),
                "lon": float(row["longitude"]),
                "label": row.get("name") or clean,
            }
    if results:
        row = results[0]
        return {
            "lat": float(row["latitude"]),
            "lon": float(row["longitude"]),
            "label": row.get("name") or clean,
        }
    return None


def _fetch_weather(lat: float, lon: float, place: str) -> dict[str, Any]:
    res = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code,wind_speed_10m,precipitation",
            "wind_speed_unit": "mph",
            "timezone": "Europe/London",
        },
        timeout=8,
    )
    res.raise_for_status()
    current = (res.json() or {}).get("current") or {}
    return {
        "place": place,
        "temp_c": current.get("temperature_2m"),
        "wind_mph": current.get("wind_speed_10m"),
        "precip_mm": current.get("precipitation"),
        "code": current.get("weather_code"),
        "condition": _wmo_label(current.get("weather_code")),
    }


def build_match_day_weather(*, is_home: bool, opponent: str | None) -> dict[str, Any]:
    if is_home or not (opponent or "").strip():
        place = _VALE_PARK
    else:
        place = _geocode_uk(opponent or "") or _VALE_PARK
    cache_key = f"{place['lat']:.3f},{place['lon']:.3f}"
    now = time.time()
    cached = _WEATHER_CACHE.get(cache_key)
    if cached and now - cached[0] < _WEATHER_TTL:
        return cached[1]
    payload = _fetch_weather(place["lat"], place["lon"], place["label"])
    _WEATHER_CACHE[cache_key] = (now, payload)
    return payload


def register_match_day_countdown_routes(app: FastAPI) -> None:
    @app.get("/match-day-countdown", response_class=HTMLResponse)
    def match_day_countdown_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "match-day-countdown.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Match Day Countdown page missing.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/match-day-countdown/next")
    def match_day_countdown_next() -> JSONResponse:
        try:
            data = build_port_vale_fixtures()
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Could not load fixtures: {exc}"
            ) from exc
        upcoming = data.get("upcoming") or []
        return JSONResponse(
            {
                "fixture": data.get("next"),
                "upcoming": upcoming[:8],
                "generated_at": data.get("generated_at"),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/match-day-countdown/weather")
    def match_day_countdown_weather(
        is_home: bool = Query(True, alias="isHome"),
        opponent: str | None = Query(None),
    ) -> JSONResponse:
        try:
            payload = build_match_day_weather(is_home=is_home, opponent=opponent)
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Could not load weather: {exc}"
            ) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
