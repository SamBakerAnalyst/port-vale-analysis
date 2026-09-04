"""Test setup.

Logging is configured at import time in app.main, so the level has to be set
before anything imports it. Background refresh threads occasionally log a
provider failure mid-run, and a stray traceback in the output is easy to
mistake for a real test failure.
"""

from __future__ import annotations

import os

os.environ.setdefault("LOG_LEVEL", "CRITICAL")
os.environ.setdefault("TEAM_PASSWORD", "test")
