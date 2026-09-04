"""Durable Analysis-tool cache: click serves disk; Impect only in the background.

Used by Pre-Match, xG Chance, Player Cards, Blocks, and countdown fixtures.
The hub ``analysis`` scope rebuilds once Impect has published the match.
Set Piece keeps its own disk dir; that refresh warms it too.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from app.paths import CACHE_ROOT, ensure_data_dirs

logger = logging.getLogger(__name__)

ANALYSIS_CACHE_DIR = CACHE_ROOT / "impect-analysis"
ANALYSIS_CACHE_VERSION = 1

# Completed match packets stay warm for days; Force refresh bypasses.
REPORT_TTL_SECONDS = 7 * 24 * 3600
PACKET_TTL_SECONDS = 14 * 24 * 3600

_SAFE_KEY = re.compile(r"[^A-Za-z0-9._-]+")


def _ensure_dir() -> Path:
    ensure_data_dirs()
    ANALYSIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return ANALYSIS_CACHE_DIR


def _safe_key(key: str) -> str:
    cleaned = _SAFE_KEY.sub("_", str(key or "").strip())[:180]
    return cleaned or "empty"


def _path(kind: str, key: str) -> Path:
    return _ensure_dir() / kind / f"{_safe_key(key)}.json"


def read_json(
    kind: str, key: str, *, ttl: float, allow_stale: bool = False
) -> dict[str, Any] | None:
    path = _path(kind, key)
    try:
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if not allow_stale and age > ttl:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if int(payload.get("_cache_version") or 0) != ANALYSIS_CACHE_VERSION:
            return None
        body = payload.get("data")
        return body if isinstance(body, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def write_json(kind: str, key: str, data: dict[str, Any]) -> None:
    path = _path(kind, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_cache_version": ANALYSIS_CACHE_VERSION,
            "cached_at_epoch": time.time(),
            "data": data,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.exception("Failed to write analysis cache %s/%s", kind, key)


def read_list(
    kind: str, key: str, *, ttl: float, allow_stale: bool = False
) -> list[Any] | None:
    path = _path(kind, key)
    try:
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if not allow_stale and age > ttl:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if int(payload.get("_cache_version") or 0) != ANALYSIS_CACHE_VERSION:
            return None
        body = payload.get("data")
        return body if isinstance(body, list) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def click_json(kind: str, key: str) -> dict[str, Any] | None:
    """Click-path: serve disk forever. Rebuilds only via hub-snapshots."""
    return read_json(kind, key, ttl=REPORT_TTL_SECONDS, allow_stale=True)


def click_list(kind: str, key: str) -> list[Any] | None:
    """Click-path: serve disk forever. Rebuilds only via hub-snapshots."""
    return read_list(kind, key, ttl=PACKET_TTL_SECONDS, allow_stale=True)


def write_list(kind: str, key: str, data: list[Any]) -> None:
    path = _path(kind, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_cache_version": ANALYSIS_CACHE_VERSION,
            "cached_at_epoch": time.time(),
            "data": data,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.exception("Failed to write analysis cache list %s/%s", kind, key)


def clear_kind(kind: str) -> int:
    folder = _ensure_dir() / kind
    removed = 0
    if not folder.is_dir():
        return 0
    for path in folder.glob("*.json"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def clear_all() -> dict[str, int]:
    counts: dict[str, int] = {}
    root = _ensure_dir()
    for child in root.iterdir():
        if child.is_dir():
            counts[child.name] = clear_kind(child.name)
    return counts


def clear_tool_memory_caches() -> None:
    """Drop in-process TTLs so Force refresh actually hits Impect."""
    try:
        from app import pre_match

        pre_match._kpi_name_cache = None
        for name in (
            "_squad_kpi_cache",
            "_match_detail_cache",
            "_coaches_cache",
            "_player_match_stats_cache",
            "_squad_scores_cache",
        ):
            cache = getattr(pre_match, name, None)
            if isinstance(cache, dict):
                cache.clear()
    except Exception:
        logger.exception("Could not clear pre_match memory caches")

    try:
        from app import xg_chance_analysis as xg

        for name in (
            "_match_events_cache",
            "_ekpi_cache",
            "_player_directory_cache",
            "_iteration_matches_cache",
        ):
            cache = getattr(xg, name, None)
            if isinstance(cache, dict):
                cache.clear()
    except Exception:
        logger.exception("Could not clear xg_chance memory caches")

    try:
        from app import player_cards

        for name in ("_clubs_cache", "_squad_cache", "_fotmob_foot_cache"):
            cache = getattr(player_cards, name, None)
            if isinstance(cache, dict):
                cache.clear()
    except Exception:
        logger.exception("Could not clear player_cards memory caches")

    try:
        from app import home_dashboard as hd

        cache = getattr(hd, "_fixtures_cache", None)
        if isinstance(cache, dict):
            cache.clear()
    except Exception:
        logger.exception("Could not clear home_dashboard fixtures cache")


def _probe_newest_match_events() -> tuple[int | None, list[Any]]:
    """Newest played Vale match, plus whatever events the provider has for it."""
    from app.xg_chance_analysis import (
        _default_fixture_match_id,
        _impect,
        _unwrap_items,
        build_xg_chance_fixtures,
    )

    match_id = _default_fixture_match_id(build_xg_chance_fixtures(None, refresh=True))
    if match_id is None:
        return None, []

    impect = _impect()
    events = _unwrap_items(
        impect._impect_get(f"/v5/{impect._api_prefix()}/matches/{match_id}/events")[
            "data"
        ]
    )
    return match_id, list(events or [])


def provider_ready() -> dict[str, Any]:
    """Has Impect published event data for Vale's newest played match?

    There is no set upload time — it is whenever the provider finishes — so the
    scheduler polls this rather than guessing an hour. Refreshing too early
    caches a match with no events and then serves that until tomorrow.
    """
    try:
        match_id, events = _probe_newest_match_events()
    except Exception as exc:  # noqa: BLE001 - a provider outage must not kill the loop
        logger.warning("Analysis readiness check failed: %s", exc)
        return {"ready": False, "detail": f"Readiness check failed: {exc}"}

    if match_id is None:
        return {"ready": False, "detail": "No completed fixtures yet."}

    count = len(events)
    return {
        "ready": count > 0,
        "match_id": match_id,
        "event_count": count,
        "detail": (
            f"Match {match_id} has {count} events."
            if count
            else f"Provider has not published match {match_id} yet."
        ),
    }


def refresh_analysis_data(*, force: bool = True) -> dict[str, Any]:
    """Rebuild Analysis tool caches after Impect uploads (e.g. 10am post-match).

    Safe to run from the hub Force refresh button a couple of times a week.
    """
    started = time.time()
    result: dict[str, Any] = {"force": force, "steps": {}}

    if force:
        result["cleared"] = clear_all()
        clear_tool_memory_caches()

    # Blocks — already disk-backed; force rebuild KPIs.
    try:
        from app.blocks_analysis import build_blocks_analysis_payload

        payload = build_blocks_analysis_payload(force_refresh=force)
        result["steps"]["blocks"] = {
            "ok": True,
            "matches": len(payload.get("matches") or payload.get("blocks") or []),
        }
    except Exception as exc:
        logger.exception("Analysis refresh: blocks failed")
        result["steps"]["blocks"] = {"ok": False, "error": str(exc)}

    # Pre-match + set-piece for next upcoming opponent.
    next_iteration_id = 0
    next_squad_id = 0
    next_match_id: int | None = None
    try:
        from app.pre_match import (
            PreMatchReportRequest,
            build_pre_match_fixtures,
            build_pre_match_report,
        )
        from app.squad_review import _default_port_vale_season, _resolve_port_vale_iteration

        iteration = _resolve_port_vale_iteration(_default_port_vale_season())
        next_iteration_id = int(iteration["id"])
        fixtures = build_pre_match_fixtures(next_iteration_id, refresh=True)
        next_fix = fixtures[0] if fixtures else None
        if next_fix:
            opponent = next_fix.get("opponent") or {}
            next_squad_id = int(opponent.get("id") or 0)
            next_match_id = int(next_fix["match_id"]) if next_fix.get("match_id") else None
            if next_squad_id:
                from app.pre_match import pre_match_meta

                pre_match_meta(refresh=True)
                report = build_pre_match_report(
                    PreMatchReportRequest(
                        iteration_id=next_iteration_id,
                        squad_id=next_squad_id,
                        match_id=next_match_id,
                        refresh=True,
                    )
                )
                result["steps"]["pre_match"] = {
                    "ok": True,
                    "opponent": (report.get("opponent") or {}).get("name"),
                    "fixtures": len(fixtures),
                }
            else:
                result["steps"]["pre_match"] = {"ok": False, "error": "No opponent squad"}
        else:
            result["steps"]["pre_match"] = {"ok": False, "error": "No fixtures"}
    except Exception as exc:
        logger.exception("Analysis refresh: pre_match failed")
        result["steps"]["pre_match"] = {"ok": False, "error": str(exc)}

    try:
        from app.set_piece_pre_match import (
            SetPiecePreMatchRequest,
            build_set_piece_pre_match_report,
        )

        if next_iteration_id and next_squad_id:
            sp = build_set_piece_pre_match_report(
                SetPiecePreMatchRequest(
                    iteration_id=next_iteration_id,
                    squad_id=next_squad_id,
                    match_id=next_match_id,
                    refresh=True,
                )
            )
            result["steps"]["set_piece"] = {
                "ok": True,
                "opponent": (sp.get("opponent") or {}).get("name"),
            }
        else:
            result["steps"]["set_piece"] = {"ok": False, "error": "No next fixture"}
    except Exception as exc:
        logger.exception("Analysis refresh: set_piece failed")
        result["steps"]["set_piece"] = {"ok": False, "error": str(exc)}

    # xG chance — last completed Vale match + last6.
    try:
        from app.xg_chance_analysis import (
            build_xg_chance_fixtures,
            build_xg_chance_report,
            xg_chance_meta,
        )

        xg_chance_meta(refresh=True)
        build_xg_chance_fixtures(None, refresh=True)
        last = build_xg_chance_report(scope="match", refresh=True)
        last6 = build_xg_chance_report(scope="last6", refresh=True)
        result["steps"]["xg_chance"] = {
            "ok": True,
            "last_match_shots": last.get("shotCount"),
            "last6_shots": last6.get("shotCount"),
        }
    except Exception as exc:
        logger.exception("Analysis refresh: xg_chance failed")
        result["steps"]["xg_chance"] = {"ok": False, "error": str(exc)}

    # Player cards — Port Vale squad warm.
    try:
        from app.player_cards import build_player_cards_squad

        cards = build_player_cards_squad(club_name="Port Vale", refresh=True)
        result["steps"]["player_cards"] = {
            "ok": True,
            "players": len(cards.get("players") or []),
        }
    except Exception as exc:
        logger.exception("Analysis refresh: player_cards failed")
        result["steps"]["player_cards"] = {"ok": False, "error": str(exc)}

    # Match-day countdown fixtures (FotMob) — weather stays live elsewhere.
    try:
        from app.home_dashboard import build_port_vale_fixtures

        fixtures = build_port_vale_fixtures(force_refresh=True)
        upcoming = fixtures.get("fixtures") if isinstance(fixtures, dict) else fixtures
        result["steps"]["match_day_countdown"] = {
            "ok": True,
            "fixtures": len(upcoming or []) if isinstance(upcoming, list) else 1,
        }
    except Exception as exc:
        logger.exception("Analysis refresh: countdown fixtures failed")
        result["steps"]["match_day_countdown"] = {"ok": False, "error": str(exc)}

    step_ok = [
        bool(step.get("ok"))
        for step in result["steps"].values()
        if isinstance(step, dict)
    ]
    result["ok"] = bool(step_ok) and all(step_ok)
    result["elapsed_seconds"] = round(time.time() - started, 1)
    return result
