"""Versioned /static and standalone JS/CSS may be cached; HTML and /api may not."""

from app.static_cache import VERSIONED_ASSET_CACHE_CONTROL, versioned_static_cache_control

CACHEABLE = VERSIONED_ASSET_CACHE_CONTROL


def test_versioned_static_js_is_cacheable():
    assert versioned_static_cache_control("/static/pre-match.js", {"v": "b1"}) == CACHEABLE
    assert versioned_static_cache_control("/static/pre-match.css", {"b": "hash"}) == CACHEABLE


def test_versioned_standalone_js_css_are_cacheable():
    assert versioned_static_cache_control("/standalone/hub-home.js", {"v": "b1"}) == CACHEABLE
    assert versioned_static_cache_control("/standalone/apps.css", {"b": "2"}) == CACHEABLE


def test_html_and_api_stay_uncached():
    assert versioned_static_cache_control("/", {"v": "b1"}) is None
    assert versioned_static_cache_control("/standalone/hub.html", {"v": "b1"}) is None
    assert versioned_static_cache_control("/api/apps", {"v": "b1"}) is None
    assert versioned_static_cache_control("/api/auth/me", {}) is None


def test_unversioned_and_non_js_standalone_stay_uncached():
    assert versioned_static_cache_control("/static/pre-match.js", {}) is None
    assert versioned_static_cache_control("/standalone/hub-home.js", {}) is None
    assert versioned_static_cache_control("/standalone/port-vale-badge.png", {"v": "2"}) is None
