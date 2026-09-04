"""Who To Scout must not serve an ancient disk cache forever.

The disk copy has no expiry of its own. Reading it without checking `saved_at`
created a loop: the memory cache rejects the old entry, the disk read accepts it
again unchanged, and the same stale scores go out on every request. Staging was
handing out numbers built 28 hours earlier with nothing on screen to say so.

The fix is stale-while-revalidate — serve it, but rebuild behind it — so these
tests check both halves. Serving nothing would mean a four-minute wait.
"""

from __future__ import annotations

import time

import app.main  # noqa: F401 - initialise the app so router imports resolve
from app import who_to_scout as wts
from app.home_dashboard import STANDOUTS_CACHE_TTL


def _payload(tag: str) -> dict:
    return {"players": [{"id": 1, "name": tag}], "player_count": 1}


def _setup(monkeypatch, *, age_hours: float):
    """Put a disk cache of a given age in place and record refresh calls."""
    saved_at = time.time() - age_hours * 3600
    scheduled: list[str] = []
    built: list[str] = []

    monkeypatch.setattr(
        wts, "_load_standouts_disk", lambda key: (saved_at, _payload("from-disk"))
    )
    monkeypatch.setattr(
        wts,
        "_schedule_standouts_refresh",
        lambda period, **kw: scheduled.append(period),
    )
    monkeypatch.setattr(
        wts,
        "_build_standouts_season_payload",
        lambda: built.append("rebuild") or _payload("rebuilt"),
    )
    monkeypatch.setattr(wts, "_attach_scout_coverage", lambda payload, **kw: payload)
    wts._standouts_cache.clear()
    return scheduled, built


def test_a_stale_disk_cache_still_answers_immediately(monkeypatch):
    """Nobody should watch a four-minute rebuild because the cache lapsed."""
    scheduled, built = _setup(monkeypatch, age_hours=28)

    payload = wts._load_standouts_raw_payload(period="season")

    assert payload["players"][0]["name"] == "from-disk"
    assert built == [], "must not rebuild inline while someone is waiting"


def test_a_stale_disk_cache_triggers_a_background_refresh(monkeypatch):
    """This is the bit that was missing — it was served stale forever."""
    scheduled, _ = _setup(monkeypatch, age_hours=28)

    wts._load_standouts_raw_payload(period="season")

    assert scheduled == ["season"], "stale cache must queue a rebuild"


def test_a_fresh_disk_cache_does_not_trigger_a_refresh(monkeypatch):
    scheduled, built = _setup(monkeypatch, age_hours=1)

    payload = wts._load_standouts_raw_payload(period="season")

    assert payload["players"][0]["name"] == "from-disk"
    assert scheduled == [], "a fresh cache must not queue needless Impect work"
    assert built == []


def test_the_refresh_job_itself_does_not_queue_another_one(monkeypatch):
    """_from_background guards against a job re-scheduling itself in a loop."""
    scheduled, _ = _setup(monkeypatch, age_hours=28)

    wts._load_standouts_raw_payload(period="season", _from_background=True)

    assert scheduled == []


def test_the_boundary_is_the_shared_ttl(monkeypatch):
    """Just inside the limit is fresh; just outside queues a rebuild."""
    scheduled, _ = _setup(monkeypatch, age_hours=(STANDOUTS_CACHE_TTL / 3600) - 0.1)
    wts._load_standouts_raw_payload(period="season")
    assert scheduled == []

    scheduled, _ = _setup(monkeypatch, age_hours=(STANDOUTS_CACHE_TTL / 3600) + 0.1)
    wts._load_standouts_raw_payload(period="season")
    assert scheduled == ["season"]


def test_stale_entry_is_not_promoted_as_though_it_were_fresh(monkeypatch):
    """The memory copy keeps the original timestamp, not 'now'.

    Rewriting saved_at to now would hide the staleness for another full TTL and
    the background refresh would never be queued again.
    """
    _setup(monkeypatch, age_hours=28)

    wts._load_standouts_raw_payload(period="season")

    key = wts._standouts_raw_cache_key("season")
    cached_at, _ = wts._standouts_cache[key]
    assert time.time() - cached_at > STANDOUTS_CACHE_TTL
