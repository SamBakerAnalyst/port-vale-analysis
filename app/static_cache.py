"""Browser cache rules for versioned hub assets."""

from __future__ import annotations

from typing import Mapping

VERSIONED_ASSET_CACHE_CONTROL = "public, max-age=86400"


def versioned_static_cache_control(path: str, query_params: Mapping[str, str]) -> str | None:
    """Cache versioned JS/CSS for a day. HTML and /api stay no-store."""
    if path.startswith("/api/"):
        return None
    lower = path.lower()
    if lower.endswith((".html", ".htm")):
        return None
    if "v" not in query_params and "b" not in query_params:
        return None
    if path.startswith("/static/"):
        return VERSIONED_ASSET_CACHE_CONTROL
    if path.startswith("/standalone/") and lower.endswith((".js", ".css")):
        return VERSIONED_ASSET_CACHE_CONTROL
    return None
