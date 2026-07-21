"""Central path configuration — all directories resolve from env vars or repo root."""

from __future__ import annotations

import os
from pathlib import Path

# Repo root (parent of app/)
HUB_ROOT = Path(os.environ.get("HUB_ROOT", Path(__file__).resolve().parent.parent))

# Persistent data (caches, uploads) — mount as a volume in Docker/production
DATA_ROOT = Path(os.environ.get("DATA_ROOT", HUB_ROOT / "data"))

# Frontend HTML pages
STANDALONE_DIR = Path(os.environ.get("STANDALONE_DIR", HUB_ROOT / "standalone"))

# League Two strategy report slides
STRATEGY_REPORTS_DIR = Path(
    os.environ.get("STRATEGY_REPORTS_DIR", HUB_ROOT / "strategy-reports")
)

# Static assets (JS/CSS served at /static)
STATIC_DIR = Path(os.environ.get("STATIC_DIR", HUB_ROOT / "static"))

# Jinja templates (player studio)
TEMPLATES_DIR = Path(os.environ.get("TEMPLATES_DIR", HUB_ROOT / "templates"))

# Club badge used in PDF exports
PORT_VALE_BADGE = STANDALONE_DIR / "port-vale-badge.png"

# Stadium coordinates for scouting address tool
STADIUMS_PATH = Path(os.environ.get("STADIUMS_PATH", STATIC_DIR / "stadiums.json"))

# Per-tool disk caches (shared across team when DATA_ROOT is on a volume)
CACHE_ROOT = Path(os.environ.get("CACHE_ROOT", DATA_ROOT / "cache"))

SCOUTING_DISK_CACHE_DIR = CACHE_ROOT / "impect-scouting"
AVAILABILITY_DATA_DIR = CACHE_ROOT / "impect-availability"
FIXTURE_PLANNER_DATA_DIR = CACHE_ROOT / "impect-fixture-planner"
CLUB_STRATEGY_CACHE_DIR = CACHE_ROOT / "impect-club-strategy"

# Optional legacy pre-match standalone (port 8002) — not bundled in hub
PRE_MATCH_STANDALONE_DIR = Path(
    os.environ.get("PRE_MATCH_STANDALONE_DIR", HUB_ROOT / "services" / "pre-match")
)


def ensure_data_dirs() -> None:
    """Create cache/data directories if they do not exist."""
    for path in (
        DATA_ROOT,
        CACHE_ROOT,
        SCOUTING_DISK_CACHE_DIR,
        AVAILABILITY_DATA_DIR,
        FIXTURE_PLANNER_DATA_DIR,
        CLUB_STRATEGY_CACHE_DIR,
        STATIC_DIR / "player-photos",
        STATIC_DIR / "post-match-badges",
        DATA_ROOT / "feedback-screenshots",
    ):
        path.mkdir(parents=True, exist_ok=True)
