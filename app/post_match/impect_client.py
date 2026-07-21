from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests
from fastapi import HTTPException


@dataclass
class TokenCache:
    access_token: str = ""
    expires_at_epoch: float = 0.0


_token_cache = TokenCache()


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing environment variable: {name}")
    return value


def _api_prefix() -> str:
    return os.getenv("IMPECT_API_PREFIX", "customerapi").strip().strip("/")


def get_access_token() -> str:
    now = time.time()
    if _token_cache.access_token and now < _token_cache.expires_at_epoch - 120:
        return _token_cache.access_token

    response = requests.post(
        _required_env("IMPECT_TOKEN_URL"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_id": os.getenv("IMPECT_CLIENT_ID", "api"),
            "grant_type": "password",
            "username": _required_env("IMPECT_USERNAME"),
            "password": _required_env("IMPECT_PASSWORD"),
        },
        timeout=20,
    )
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Token request failed ({response.status_code})",
        )

    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="Token response missing access_token")

    _token_cache.access_token = access_token
    _token_cache.expires_at_epoch = now + int(payload.get("expires_in", 3600))
    return access_token


def _resolve_url(path: str) -> str:
    path = path.strip()
    if path.startswith("http://") or path.startswith("https://"):
        return path
    base = _required_env("IMPECT_BASE_URL").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def impect_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    access_token = get_access_token()
    url = _resolve_url(path)
    last_response: requests.Response | None = None

    for attempt in range(4):
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params or {},
                timeout=45,
            )
        except requests.RequestException as exc:
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise HTTPException(status_code=502, detail=f"Impect API unreachable: {exc}") from exc

        last_response = response
        if response.status_code == 429 and attempt < 3:
            time.sleep(min(60.0, 5.0 * (2**attempt)))
            continue
        break

    assert last_response is not None
    if last_response.status_code == 429:
        raise HTTPException(status_code=429, detail="Impect API rate limit — wait a few minutes.")
    if last_response.status_code >= 400:
        raise HTTPException(
            status_code=last_response.status_code,
            detail=f"Impect API error: {last_response.text[:500]}",
        )

    try:
        payload = last_response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Impect API returned non-JSON.") from exc

    return {"url": url, "data": payload}


def extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("items", "results", "data", "players", "kpis"):
            maybe = payload.get(key)
            if isinstance(maybe, list):
                return [row for row in maybe if isinstance(row, dict)]
        return [payload]
    return []


def unwrap_match_payload(raw_data: Any) -> dict[str, Any]:
    if isinstance(raw_data, dict) and isinstance(raw_data.get("data"), dict):
        return raw_data["data"]
    if isinstance(raw_data, dict):
        return raw_data
    return {}


def v5_path(suffix: str) -> str:
    suffix = suffix.strip()
    if not suffix.startswith("/"):
        suffix = "/" + suffix
    return f"/v5/{_api_prefix()}{suffix}"
