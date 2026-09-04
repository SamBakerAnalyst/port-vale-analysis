"""Local Impect-derived snapshots so hub pages read disk, not live API.

Daily refresh (and a manual Refresh button) rebuild player stats + league
standings into ``data/cache/hub-snapshots/``. Click paths should prefer these
files over calling Impect.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.paths import HUB_SNAPSHOTS_DIR, ensure_data_dirs

logger = logging.getLogger(__name__)

LONDON = ZoneInfo("Europe/London")
DAILY_REFRESH_HOUR = 5  # 05:00 Europe/London
PLAYERS_PATH = HUB_SNAPSHOTS_DIR / "players.json"
STANDINGS_PATH = HUB_SNAPSHOTS_DIR / "standings-league-two.json"
META_PATH = HUB_SNAPSHOTS_DIR / "meta.json"

_lock = threading.Lock()
_refresh_lock = threading.Lock()
_refreshing = False
_scheduler_started = False

PLAYER_STAT_KEYS = (
    "overall_score",
    "minutes",
    "top_profile",
    "top_profile_score",
    "minutes_by_position",
    "club",
    "league",
    "age",
    "foot",
    "height",
    "position_label",
    "stats_updated_at",
    "stats_score_version",
)


class RefreshBody(BaseModel):
    scope: str = Field(
        default="all",
        description="all | players | standings | win_drivers | strategy_tracker | analysis",
    )


VALID_SCOPES = frozenset(
    {"all", "players", "standings", "win_drivers", "strategy_tracker", "analysis"}
)

# Impect finish whenever they finish — there is no set upload time. So the
# analysis cache waits for the data to actually land instead of firing on a
# clock and then sitting on a half-built match for the rest of the day.
ANALYSIS_WINDOW_START_HOUR = 8  # earliest we start looking, Europe/London
ANALYSIS_GIVE_UP_HOUR = 22  # stop looking; tomorrow's window tries again
ANALYSIS_POLL_MINUTES = 20


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_dir() -> None:
    ensure_data_dirs()
    HUB_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    _ensure_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def player_stat_key(player_id: int, position: str) -> str:
    return f"{int(player_id)}|{str(position or '').strip()}"


def load_meta() -> dict[str, Any]:
    meta = _read_json(META_PATH)
    return {
        "players_updated_at": str(meta.get("players_updated_at") or ""),
        "standings_updated_at": str(meta.get("standings_updated_at") or ""),
        "win_drivers_updated_at": str(meta.get("win_drivers_updated_at") or ""),
        "strategy_tracker_updated_at": str(meta.get("strategy_tracker_updated_at") or ""),
        "analysis_updated_at": str(meta.get("analysis_updated_at") or ""),
        "last_refresh_started_at": str(meta.get("last_refresh_started_at") or ""),
        "last_refresh_finished_at": str(meta.get("last_refresh_finished_at") or ""),
        "last_refresh_status": str(meta.get("last_refresh_status") or "never"),
        "last_refresh_error": str(meta.get("last_refresh_error") or ""),
        "last_refresh_scope": str(meta.get("last_refresh_scope") or ""),
        "players_count": int(meta.get("players_count") or 0),
        "refreshing": _refreshing,
    }


def _write_meta(updates: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        meta = _read_json(META_PATH)
        meta.update(updates)
        _atomic_write(META_PATH, meta)
        return meta


def load_players_store() -> dict[str, Any]:
    payload = _read_json(PLAYERS_PATH)
    players = payload.get("players")
    if not isinstance(players, dict):
        players = {}
    return {
        "updated_at": str(payload.get("updated_at") or ""),
        "version": int(payload.get("version") or 1),
        "players": players,
    }


def get_player_stats(player_id: int, position: str) -> dict[str, Any] | None:
    if not player_id or not str(position or "").strip():
        return None
    store = load_players_store()
    row = store["players"].get(player_stat_key(player_id, position))
    return dict(row) if isinstance(row, dict) else None


def put_player_stats(
    player_id: int,
    position: str,
    stats: dict[str, Any],
    *,
    name: str = "",
) -> None:
    if not player_id or not str(position or "").strip():
        return
    key = player_stat_key(player_id, position)
    blob = {
        "player_id": int(player_id),
        "position": str(position).strip(),
        "name": str(name or stats.get("name") or ""),
        "updated_at": _now_iso(),
    }
    for field in PLAYER_STAT_KEYS:
        if field in stats:
            blob[field] = stats.get(field)
    with _lock:
        store = load_players_store()
        store["players"][key] = blob
        store["updated_at"] = _now_iso()
        store["version"] = 1
        _atomic_write(PLAYERS_PATH, store)
        meta = _read_json(META_PATH)
        meta["players_updated_at"] = store["updated_at"]
        meta["players_count"] = len(store["players"])
        _atomic_write(META_PATH, meta)


def apply_player_stats_to_row(row: dict[str, Any]) -> bool:
    """Copy snapshot stats onto a pipeline/watch-list row. Returns True if applied."""
    try:
        player_id = int(row.get("player_id") or 0)
    except (TypeError, ValueError):
        return False
    position = str(row.get("position") or "").strip()
    snap = get_player_stats(player_id, position)
    if not snap:
        return False
    changed = False
    for field in PLAYER_STAT_KEYS:
        if field not in snap:
            continue
        if row.get(field) != snap.get(field):
            row[field] = snap.get(field)
            changed = True
    return changed


def snapshot_from_row(row: dict[str, Any]) -> None:
    """Persist a pipeline row's stats into the shared player snapshot."""
    try:
        player_id = int(row.get("player_id") or 0)
    except (TypeError, ValueError):
        return
    position = str(row.get("position") or "").strip()
    if not player_id or not position:
        return
    if row.get("overall_score") is None and row.get("minutes") is None:
        return
    put_player_stats(
        player_id,
        position,
        {key: row.get(key) for key in PLAYER_STAT_KEYS},
        name=str(row.get("name") or ""),
    )


def load_standings_snapshot() -> dict[str, Any] | None:
    payload = _read_json(STANDINGS_PATH)
    if not payload.get("standings"):
        return None
    return payload


def refresh_standings() -> dict[str, Any]:
    from app.club_strategy import build_club_strategy_report, club_strategy_meta

    meta = club_strategy_meta("League Two", force_refresh=True)
    iteration_id = int(meta.get("default_iteration_id") or 0)
    if not iteration_id:
        raise RuntimeError("No League Two iteration found for standings snapshot.")
    report = build_club_strategy_report(iteration_id, force_refresh=True)
    try:
        from app.club_strategy import build_first_goal_report

        build_first_goal_report(iteration_id, force_refresh=True)
    except Exception:
        logger.exception("First-goal warm after standings snapshot failed")
    payload = {
        "updated_at": _now_iso(),
        "competition": "League Two",
        "iteration_id": iteration_id,
        "season": report.get("season"),
        "standings": report.get("standings") or [],
        "averages": report.get("averages") or {},
        "generated_at": report.get("generated_at"),
    }
    _atomic_write(STANDINGS_PATH, payload)
    _write_meta({"standings_updated_at": payload["updated_at"]})
    # Warm home strategy disk cache too.
    try:
        from app.home_dashboard import build_strategy_snapshot

        build_strategy_snapshot(
            competition="League Two",
            force_refresh=True,
            detail=True,
            _from_background=True,
        )
    except Exception:
        logger.exception("Home strategy warm after standings snapshot failed")
    return {
        "standings_count": len(payload["standings"]),
        "updated_at": payload["updated_at"],
        "iteration_id": iteration_id,
    }


def refresh_players() -> dict[str, Any]:
    from app.player_pipelines import (
        _enrich_target_stats,
        _load,
        _save,
        _stats_need_refresh,
    )

    store = _load()
    refreshed = 0
    skipped = 0
    failed = 0
    dirty = False
    for row in store.get("targets") or []:
        if not isinstance(row, dict):
            continue
        if row.get("manual") or not row.get("player_id"):
            skipped += 1
            continue
        if not str(row.get("position") or "").strip():
            skipped += 1
            continue
        try:
            if _stats_need_refresh(row):
                _enrich_target_stats(row)
                refreshed += 1
                dirty = True

            # Ensure the shared player snapshot exists for cards even if
            # we didn't need to re-pull from Impect.
            snapshot_from_row(row)
        except Exception:
            failed += 1
            logger.exception(
                "Player snapshot refresh failed for %s",
                row.get("player_id"),
            )
    if dirty:
        _save(store)
    updated_at = _now_iso()
    _write_meta(
        {
            "players_updated_at": updated_at,
            "players_count": len(load_players_store()["players"]),
        }
    )
    return {
        "refreshed": refreshed,
        "skipped": skipped,
        "failed": failed,
        "updated_at": updated_at,
        "needed_refresh_before": sum(
            1
            for row in (store.get("targets") or [])
            if isinstance(row, dict) and _stats_need_refresh(row)
        ),
    }


def refresh_win_drivers() -> dict[str, Any]:
    from app.win_drivers import build_history, build_table, win_drivers_meta

    meta = win_drivers_meta(force_refresh=True)
    seasons = list(meta.get("seasons") or [])

    iteration_ids: list[int] = []
    for row in seasons[:3]:
        try:
            iid = int(row.get("iteration_id") or 0)
        except (TypeError, ValueError):
            iid = 0
        if iid > 0:
            iteration_ids.append(iid)

    if not iteration_ids:
        updated_at = _now_iso()
        _write_meta({"win_drivers_updated_at": updated_at})
        return {"updated_at": updated_at, "seasons_rebuilt": []}

    # Daily / Refresh button must rebuild from Impect, then click paths
    # serve the saved files until the next 05:00 pull.
    build_history(force_refresh=True)

    rebuilt: list[int] = []
    for iid in iteration_ids:
        build_table(iid, force_refresh=True)
        rebuilt.append(iid)

    updated_at = _now_iso()
    _write_meta({"win_drivers_updated_at": updated_at})
    return {"updated_at": updated_at, "seasons_rebuilt": rebuilt}


def refresh_strategy_tracker() -> dict[str, Any]:
    from app.strategy_tracker import build_strategy_tracker

    payload = build_strategy_tracker(competition="League Two", force_refresh=True)
    updated_at = _now_iso()
    _write_meta({"strategy_tracker_updated_at": updated_at})
    return {
        "updated_at": updated_at,
        "iteration_id": payload.get("iteration_id"),
        "season": payload.get("season"),
        "generated_at": payload.get("generated_at"),
    }


def refresh_analysis() -> dict[str, Any]:
    from app.analysis_cache import refresh_analysis_data

    payload = refresh_analysis_data(force=True)
    _write_meta({"analysis_updated_at": _now_iso()})
    return payload


def refresh_snapshots(scope: str = "all") -> dict[str, Any]:
    global _refreshing
    scope_key = str(scope or "all").strip().lower()
    if scope_key not in VALID_SCOPES:
        raise ValueError(
            "scope must be all, players, standings, win_drivers, "
            "strategy_tracker, or analysis"
        )

    with _refresh_lock:
        if _refreshing:
            return {"started": False, "detail": "Refresh already running.", **load_meta()}
        _refreshing = True

    _write_meta(
        {
            "last_refresh_started_at": _now_iso(),
            "last_refresh_status": "running",
            "last_refresh_error": "",
            "last_refresh_scope": scope_key,
        }
    )
    started = time.time()
    result: dict[str, Any] = {"scope": scope_key, "started": True}
    try:
        if scope_key in {"all", "standings"}:
            result["standings"] = refresh_standings()
        if scope_key in {"all", "players"}:
            result["players"] = refresh_players()
        if scope_key in {"all", "strategy_tracker"}:
            result["strategy_tracker"] = refresh_strategy_tracker()
        if scope_key in {"all", "win_drivers"}:
            result["win_drivers"] = refresh_win_drivers()
        # Analysis is heavy (Impect match packets) — only on explicit scope / 10:30 job.
        if scope_key == "analysis":
            result["analysis"] = refresh_analysis()
        _write_meta(
            {
                "last_refresh_finished_at": _now_iso(),
                "last_refresh_status": "ok",
                "last_refresh_error": "",
            }
        )
        result["ok"] = True
    except Exception as exc:
        logger.exception("Hub snapshot refresh failed (%s)", scope_key)
        _write_meta(
            {
                "last_refresh_finished_at": _now_iso(),
                "last_refresh_status": "error",
                "last_refresh_error": str(exc),
            }
        )
        result["ok"] = False
        result["error"] = str(exc)
    finally:
        with _refresh_lock:
            _refreshing = False
        result["elapsed_seconds"] = round(time.time() - started, 1)
        result["meta"] = load_meta()
    return result


def schedule_refresh(scope: str = "all") -> dict[str, Any]:
    """Kick a background refresh; returns immediately."""
    meta = load_meta()
    if meta.get("refreshing"):
        return {"started": False, "detail": "Refresh already running.", **meta}

    def _run() -> None:
        refresh_snapshots(scope)

    threading.Thread(
        target=_run,
        name=f"hub-snapshot-refresh-{scope}",
        daemon=True,
    ).start()
    return {
        "started": True,
        "detail": "Refresh started in the background.",
        "scope": scope,
        **load_meta(),
        "refreshing": True,
        "last_refresh_status": "running",
    }


def _seconds_until_daily_refresh() -> float:
    now = datetime.now(LONDON)
    target = now.replace(
        hour=DAILY_REFRESH_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    if now >= target:
        target += timedelta(days=1)
    return max(60.0, (target - now).total_seconds())


def _seconds_until_analysis_window() -> float:
    """Wait until today's window opens, or tomorrow's if we are past give-up."""
    now = datetime.now(LONDON)
    target = now.replace(
        hour=ANALYSIS_WINDOW_START_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    if now >= target:
        # Inside the window already — start looking now rather than waiting a day.
        if now.hour < ANALYSIS_GIVE_UP_HOUR:
            return 0.0
        target += timedelta(days=1)
    return max(0.0, (target - now).total_seconds())


def _meta_is_stale(max_age_hours: float = 36.0) -> bool:
    meta = load_meta()
    keys = [
        "players_updated_at",
        "standings_updated_at",
        "win_drivers_updated_at",
        "strategy_tracker_updated_at",
    ]
    now = datetime.now(UTC)
    for key in keys:
        stamp = meta.get(key) or ""
        if not stamp:
            return True
        try:
            when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            return True
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        age = now - when.astimezone(UTC)
        if age > timedelta(hours=max_age_hours):
            return True
    return False


def start_daily_scheduler() -> None:
    """Start the once-daily refresh loop (idempotent)."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    _ensure_dir()

    def _loop() -> None:
        # If never refreshed (or very stale), warm shortly after boot.
        if _meta_is_stale():
            time.sleep(20)
            try:
                refresh_snapshots("all")
            except Exception:
                logger.exception("Boot snapshot refresh failed")
        while True:
            delay = _seconds_until_daily_refresh()
            logger.info(
                "Next hub snapshot refresh in %.0f minutes (daily %02d:00 London)",
                delay / 60.0,
                DAILY_REFRESH_HOUR,
            )
            time.sleep(delay)
            try:
                refresh_snapshots("all")
            except Exception:
                logger.exception("Daily hub snapshot refresh failed")

    def _analysis_loop() -> None:
        from app.analysis_cache import provider_ready

        handled_date = None  # day we already refreshed (or gave up on)
        while True:
            now = datetime.now(LONDON)
            today = now.date()
            in_window = ANALYSIS_WINDOW_START_HOUR <= now.hour < ANALYSIS_GIVE_UP_HOUR

            if handled_date == today or not in_window:
                delay = _seconds_until_analysis_window()
                logger.info(
                    "Analysis cache idle — next window in %.0f minutes", delay / 60.0
                )
                time.sleep(max(60.0, delay))
                continue

            check = provider_ready()
            _write_meta(
                {
                    "analysis_checked_at": _now_iso(),
                    "analysis_waiting_for_provider": not bool(check.get("ready")),
                    "analysis_provider_detail": str(check.get("detail") or ""),
                }
            )

            if check.get("ready"):
                logger.info("Provider data ready — refreshing Analysis cache")
                try:
                    refresh_snapshots("analysis")
                except Exception:
                    logger.exception("Analysis cache refresh failed")
                handled_date = today
                continue

            if now.hour >= ANALYSIS_GIVE_UP_HOUR - 1:
                logger.warning(
                    "Provider data still missing near give-up: %s", check.get("detail")
                )
                handled_date = today
                continue

            logger.info("Waiting on provider: %s", check.get("detail"))
            time.sleep(ANALYSIS_POLL_MINUTES * 60)

    threading.Thread(target=_loop, name="hub-snapshot-daily", daemon=True).start()
    threading.Thread(
        target=_analysis_loop, name="hub-analysis-provider-poll", daemon=True
    ).start()


def register_hub_snapshots_routes(app: FastAPI) -> None:
    @app.get("/api/hub-snapshots/status")
    def hub_snapshots_status() -> dict[str, Any]:
        return load_meta()

    @app.post("/api/hub-snapshots/refresh")
    def hub_snapshots_refresh(
        body: RefreshBody | None = None,
        scope: str = Query("all"),
    ) -> dict[str, Any]:
        chosen = (body.scope if body else None) or scope or "all"
        chosen = str(chosen).strip().lower()
        if chosen not in VALID_SCOPES:
            raise HTTPException(
                status_code=400,
                detail="scope must be all, players, standings, win_drivers, strategy_tracker, or analysis",
            )
        return schedule_refresh(chosen)

    @app.on_event("startup")
    def _start_hub_snapshot_scheduler() -> None:
        start_daily_scheduler()
