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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

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


def all_json(kind: str) -> list[dict[str, Any]]:
    """Every valid payload in a kind folder, newest first. Ignores TTL."""
    folder = _ensure_dir() / kind
    if not folder.is_dir():
        return []
    rows: list[tuple[float, dict[str, Any]]] = []
    for path in folder.glob("*.json"):
        try:
            mtime = path.stat().st_mtime
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            if int(payload.get("_cache_version") or 0) != ANALYSIS_CACHE_VERSION:
                continue
            body = payload.get("data")
            if isinstance(body, dict):
                rows.append((mtime, body))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    rows.sort(key=lambda item: item[0], reverse=True)
    return [body for _mtime, body in rows]


def newest_json(kind: str) -> dict[str, Any] | None:
    rows = all_json(kind)
    return rows[0] if rows else None


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


# Played pre-match packets stay valid; wiping them on Force refresh left old
# opposition two-pagers empty. The fixture list must NOT be preserved — that
# is how a finished game (Exeter 12 Sep 2026) stayed "upcoming" after refresh.
_PRESERVE_ON_FORCE = frozenset({"pre-match", "pre-match-meta"})

_RESULT_SCORE_RE = re.compile(r"^(\d+)\s*[:\-]\s*(\d+)")
KICKOFF_FINISH_GRACE = timedelta(hours=2)


def clear_volatile() -> dict[str, int]:
    counts: dict[str, int] = {}
    root = _ensure_dir()
    for child in root.iterdir():
        if child.is_dir() and child.name not in _PRESERVE_ON_FORCE:
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

    try:
        from app import blocks_analysis

        cache = getattr(blocks_analysis, "_payload_cache", None)
        if isinstance(cache, dict):
            cache.clear()
    except Exception:
        logger.exception("Could not clear blocks_analysis payload cache")


def parse_kickoff_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        when = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            when = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC)


def kickoff_should_have_result(
    value: Any,
    *,
    now: datetime | None = None,
    grace: timedelta = KICKOFF_FINISH_GRACE,
) -> bool:
    """True once kickoff plus a full-time grace period is in the past."""
    when = parse_kickoff_utc(value)
    if when is None:
        return False
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)
    return current >= when + grace


def goals_full_time(match: dict[str, Any]) -> tuple[int, int] | None:
    """Home/away full-time goals from the goals block or Impect's result string."""
    goals = match.get("goals") or {}
    home = (goals.get("home") or {}).get("fullTime")
    away = (goals.get("away") or {}).get("fullTime")
    if home is not None and away is not None:
        try:
            return int(home), int(away)
        except (TypeError, ValueError):
            pass
    result = str(match.get("result") or "").strip()
    matched = _RESULT_SCORE_RE.match(result)
    if matched:
        return int(matched.group(1)), int(matched.group(2))
    return None


def rows_missing_finished_results(
    rows: list[dict[str, Any]],
    *,
    date_key: str,
    is_played: Callable[[dict[str, Any]], bool],
) -> bool:
    for row in rows:
        if is_played(row):
            continue
        if kickoff_should_have_result(row.get(date_key)):
            return True
    return False


def analysis_results_incomplete() -> bool:
    """True if a Vale kickoff in the past is still cached as unplayed."""
    try:
        from app.blocks_analysis import _load_season_matches_disk

        matches = _load_season_matches_disk()
        if rows_missing_finished_results(
            matches,
            date_key="scheduledDate",
            is_played=lambda row: bool(row.get("outcome")),
        ):
            return True
    except Exception:
        logger.exception("Could not inspect blocks season matches")

    try:
        for body in all_json("pre-match-fixtures"):
            rows = body.get("fixtures")
            if not isinstance(rows, list):
                continue
            if rows_missing_finished_results(
                rows,
                date_key="scheduled_date",
                is_played=lambda row: bool(row.get("played")),
            ):
                return True
    except Exception:
        logger.exception("Could not inspect pre-match fixtures")
    return False


def _probe_newest_match_events() -> tuple[int | None, list[Any]]:
    """Newest Vale match that should already have a result, plus its events.

    Uses the iteration listing, not the completed-only xG fixture cache. That
    cache hid Exeter the morning after the game — provider_ready saw Salford
    (already complete, events published) and the daily job stopped for the day.
    """
    from app.pre_match import _impect, _resolve_port_vale_squad_id, _unwrap_items
    from app.squad_review import _default_port_vale_season, _resolve_port_vale_iteration

    iteration = _resolve_port_vale_iteration(_default_port_vale_season())
    iteration_id = int(iteration["id"])
    port_vale_id = _resolve_port_vale_squad_id(iteration_id)
    if not port_vale_id:
        return None, []

    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    past: list[dict[str, Any]] = []
    for match in matches:
        try:
            match_id = int(match.get("id") or 0)
            home_id = int(match.get("homeSquadId") or -1)
            away_id = int(match.get("awaySquadId") or -1)
        except (TypeError, ValueError):
            continue
        if not match_id or port_vale_id not in {home_id, away_id}:
            continue
        if kickoff_should_have_result(match.get("scheduledDate")):
            past.append(match)
    if not past:
        return None, []
    past.sort(key=lambda row: str(row.get("scheduledDate") or ""))
    match_id = int(past[-1]["id"])
    events = _unwrap_items(
        impect._impect_get(f"/v5/{impect._api_prefix()}/matches/{match_id}/events")[
            "data"
        ]
    )
    return match_id, list(events or [])


def provider_ready() -> dict[str, Any]:
    """Has Impect published event data for Vale's newest finished kickoff?

    There is no set upload time — it is whenever the provider finishes — so the
    scheduler polls this rather than guessing an hour. The probe is the newest
    Vale match whose kickoff is in the past, even if the iteration listing has
    not written full-time goals yet.
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
    from app.brand import is_demo

    if is_demo():
        return {
            "force": force,
            "demo": True,
            "detail": "Blank demo hub — club data refresh is disabled.",
            "steps": {},
        }

    started = time.time()
    result: dict[str, Any] = {"force": force, "steps": {}}

    if force:
        result["cleared"] = clear_volatile()
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

    # Pre-match + set-piece for every played opponent, plus the next two upcoming.
    next_iteration_id = 0
    next_squad_id = 0
    next_match_id: int | None = None
    try:
        from app.pre_match import (
            PreMatchReportRequest,
            _pick_next_fixture,
            build_pre_match_fixtures,
            build_pre_match_report,
            pre_match_meta,
        )
        from app.squad_review import _default_port_vale_season, _resolve_port_vale_iteration

        iteration = _resolve_port_vale_iteration(_default_port_vale_season())
        next_iteration_id = int(iteration["id"])
        fixtures = build_pre_match_fixtures(next_iteration_id, refresh=True)
        pre_match_meta(refresh=True)
        played = [row for row in fixtures if row.get("played")]
        upcoming = [row for row in fixtures if not row.get("played")]
        next_fix = _pick_next_fixture(upcoming) or _pick_next_fixture(fixtures)
        targets = list(played)
        for row in upcoming[:2]:
            if row not in targets:
                targets.append(row)
        built: list[str] = []
        failed: list[str] = []
        for row in targets:
            opponent = row.get("opponent") or {}
            squad_id = int(opponent.get("id") or 0)
            if not squad_id:
                continue
            match_id = int(row["match_id"]) if row.get("match_id") else None
            try:
                report = build_pre_match_report(
                    PreMatchReportRequest(
                        iteration_id=next_iteration_id,
                        squad_id=squad_id,
                        match_id=match_id,
                        refresh=True,
                    )
                )
                built.append(str((report.get("opponent") or {}).get("name") or squad_id))
            except Exception as exc:
                logger.exception("Analysis refresh: pre_match %s failed", opponent.get("name"))
                failed.append(str(exc))
        if next_fix:
            next_squad_id = int((next_fix.get("opponent") or {}).get("id") or 0)
            next_match_id = int(next_fix["match_id"]) if next_fix.get("match_id") else None
        result["steps"]["pre_match"] = {
            "ok": bool(built) and not failed,
            "opponent": built[-1] if built else None,
            "reports": built,
            "fixtures": len(fixtures),
            "error": "; ".join(failed) if failed else None,
        }
        if not fixtures:
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
