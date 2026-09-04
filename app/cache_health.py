"""Is our saved data actually there, and is it fresh?

Who To Scout spent a fortnight rebuilding from Impect on every cold start
because its cache file on Live was a 3-byte stub dated 20 August. Nothing was
broken loudly enough to notice — the page was just slow, and slow reads as
"the tools are slow" rather than "a cache is not being written".

So each cache gets a size floor as well as an age limit. A file that exists but
is far too small is the failure mode we actually hit; "exists" on its own tells
you nothing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.paths import (
    ANALYSIS_CACHE_DIR,
    BLOCKS_ANALYSIS_DATA_DIR,
    CLUB_STRATEGY_CACHE_DIR,
    DATA_ROOT,
    FIXTURE_PLANNER_DATA_DIR,
    HUB_SNAPSHOTS_DIR,
    WIN_DRIVERS_CACHE_DIR,
)

logger = logging.getLogger(__name__)

OK = "ok"
STALE = "stale"
THIN = "thin"  # present but far too small to be real data
MISSING = "missing"


@dataclass(frozen=True)
class CacheCheck:
    id: str
    label: str
    tool: str
    path: Path
    max_age_hours: float
    min_bytes: int
    is_dir: bool = False


CHECKS: tuple[CacheCheck, ...] = (
    CacheCheck(
        id="standouts",
        label="Player scores by league",
        tool="Who To Scout",
        path=DATA_ROOT / "home-standouts-cache.json",
        max_age_hours=36,
        # A real payload is ~1.9 MB across six leagues. Live's broken copy was 3 bytes.
        min_bytes=200_000,
    ),
    CacheCheck(
        id="scoutable_board",
        label="League and club board",
        tool="Scoutable Teams",
        path=DATA_ROOT / "scoutable-teams-board-cache.json",
        max_age_hours=36,
        min_bytes=2_000,
    ),
    CacheCheck(
        id="hub_snapshots",
        label="Daily snapshot (players, standings)",
        tool="Hub home",
        path=HUB_SNAPSHOTS_DIR,
        max_age_hours=36,
        min_bytes=1_000,
        is_dir=True,
    ),
    CacheCheck(
        id="analysis",
        label="Match packets",
        tool="Pre-Match / xG Chance",
        path=ANALYSIS_CACHE_DIR,
        max_age_hours=48,
        min_bytes=1_000,
        is_dir=True,
    ),
    # No check for the scouting report bundles, deliberately. paths.py defines
    # SCOUTING_DISK_CACHE_DIR as /data/cache/impect-scouting, but scouting.py
    # ignores that and declares its own pointing at ~/.cache/impect-scouting.
    # The volume directory only holds two abandoned files from July, so watching
    # it reports a fault that is not real — and a panel that is always amber is
    # a panel people stop reading.
    #
    # The live path is inside the container, so those bundles are lost on every
    # deploy. Worth moving onto the volume, but that is a change to scouting.py
    # rather than something to paper over here.
    CacheCheck(
        id="fixture_planner",
        label="Assignments and coverage",
        tool="Fixture Planner",
        path=FIXTURE_PLANNER_DATA_DIR,
        max_age_hours=24 * 14,  # only changes when staff edit it
        min_bytes=100,
        is_dir=True,
    ),
    CacheCheck(
        id="blocks_analysis",
        label="Match KPIs and unit form",
        tool="Blocks Analysis",
        path=BLOCKS_ANALYSIS_DATA_DIR,
        # The match-KPI file inside lapses at 6h; 18 allows for a quiet evening
        # without crying wolf, while still catching a warm job that has stopped.
        max_age_hours=18,
        min_bytes=5_000,
        is_dir=True,
    ),
    CacheCheck(
        id="win_drivers",
        label="League tables and history",
        tool="What Wins Games",
        path=WIN_DRIVERS_CACHE_DIR,
        max_age_hours=48,
        min_bytes=1_000,
        is_dir=True,
    ),
    CacheCheck(
        id="club_strategy",
        label="Strategy board",
        tool="Club Strategy",
        path=CLUB_STRATEGY_CACHE_DIR,
        max_age_hours=48,
        min_bytes=1_000,
        is_dir=True,
    ),
)


def _measure(check: CacheCheck) -> tuple[int, float | None]:
    """Total bytes and age in hours of the newest file."""
    if check.is_dir:
        if not check.path.is_dir():
            return 0, None
        files = [p for p in check.path.rglob("*") if p.is_file()]
        if not files:
            return 0, None
        total = sum(p.stat().st_size for p in files)
        newest = max(p.stat().st_mtime for p in files)
        return total, (time.time() - newest) / 3600.0

    if not check.path.is_file():
        return 0, None
    stat = check.path.stat()
    return stat.st_size, (time.time() - stat.st_mtime) / 3600.0


def _humanise_duration(hours: float) -> str:
    """A span of time, without any sense of direction — callers add "ago"."""
    if hours < 1:
        return f"{hours * 60:.0f} minutes"
    if hours < 48:
        return f"{hours:.1f} hours"
    return f"{hours / 24:.1f} days"


def _verdict(check: CacheCheck, size: int, age_hours: float | None) -> tuple[str, str]:
    if age_hours is None:
        return MISSING, "Nothing saved — the next visitor rebuilds it from Impect."
    if size < check.min_bytes:
        return THIN, (
            f"Only {size:,} bytes saved, expected at least {check.min_bytes:,}. "
            "Something is failing to write."
        )
    if age_hours > check.max_age_hours:
        return STALE, (
            f"Last written {_humanise_duration(age_hours)} ago; expected inside "
            f"{_humanise_duration(check.max_age_hours)}."
        )
    return OK, f"Written {_humanise_duration(age_hours)} ago."


def build_cache_health() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for check in CHECKS:
        try:
            size, age = _measure(check)
            status, detail = _verdict(check, size, age)
        except OSError as exc:
            size, age = 0, None
            status, detail = MISSING, f"Could not read {check.path}: {exc}"
        rows.append(
            {
                "id": check.id,
                "label": check.label,
                "tool": check.tool,
                "path": str(check.path),
                "status": status,
                "detail": detail,
                "size_bytes": size,
                "age_hours": None if age is None else round(age, 2),
                "max_age_hours": check.max_age_hours,
            }
        )

    problems = [r for r in rows if r["status"] != OK]
    return {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "healthy": not problems,
        "problem_count": len(problems),
        # Worst first, so the panel leads with what is actually broken.
        "caches": sorted(rows, key=lambda r: (r["status"] == OK, r["tool"])),
    }


def register_cache_health_routes(app: FastAPI) -> None:
    @app.get("/api/cache-health")
    def cache_health() -> dict[str, Any]:
        payload = build_cache_health()
        if not payload["healthy"]:
            for row in payload["caches"]:
                if row["status"] != OK:
                    logger.warning(
                        "Cache %s (%s) is %s: %s",
                        row["id"],
                        row["tool"],
                        row["status"],
                        row["detail"],
                    )
        return payload
