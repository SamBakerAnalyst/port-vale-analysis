"""Boot warm has to survive Impect rate-limiting us at startup.

Live ran with an empty Who To Scout cache from 20 August. The cause was not the
cache writer — it was that several Impect jobs start together at boot (this
warm, the analysis readiness probe, the recruitment snapshot), trip Impect's
rate limit against each other, and the rebuild gave up on the first 429. The
cache then stayed empty, so every visitor triggered a four-minute build.
"""

from __future__ import annotations

import app.main  # noqa: F401 - initialise the app so router imports resolve
from app import hub_snapshots


RATE_LIMIT = "429: Impect API rate limit reached — too many requests."


def _flaky(fail_times: int, exc_text: str = RATE_LIMIT):
    """A loader that fails a set number of times, then succeeds."""
    calls: list[int] = []

    def load(*, period, force_refresh=False, **kw):
        calls.append(len(calls) + 1)
        if len(calls) <= fail_times:
            raise RuntimeError(exc_text)
        return {"players": [{"id": 1}]}

    return load, calls


def test_a_rate_limited_rebuild_is_retried_and_succeeds(monkeypatch):
    monkeypatch.setattr(hub_snapshots.time, "sleep", lambda _s: None)
    load, calls = _flaky(fail_times=1)

    result = hub_snapshots._rebuild_standouts_with_retry(load, attempts=3, wait=0.01)

    assert len(calls) == 2, "should have tried again after the 429"
    assert result == "rebuilt on attempt 2"


def test_it_gives_up_after_the_attempt_limit(monkeypatch):
    monkeypatch.setattr(hub_snapshots.time, "sleep", lambda _s: None)
    load, calls = _flaky(fail_times=99)

    result = hub_snapshots._rebuild_standouts_with_retry(load, attempts=3, wait=0.01)

    assert len(calls) == 3, "must not retry forever and pin the provider"
    assert result.startswith("failed:")
    assert "429" in result


def test_a_first_time_success_does_not_wait(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(hub_snapshots.time, "sleep", lambda s: slept.append(s))
    load, calls = _flaky(fail_times=0)

    result = hub_snapshots._rebuild_standouts_with_retry(load, attempts=3, wait=120)

    assert result == "rebuilt"
    assert calls == [1]
    assert slept == [], "no reason to pause when it worked"


def test_the_backoff_widens_between_attempts(monkeypatch):
    """The rate limit is per window, so the second wait must be longer."""
    slept: list[float] = []
    monkeypatch.setattr(hub_snapshots.time, "sleep", lambda s: slept.append(s))
    load, _ = _flaky(fail_times=99)

    hub_snapshots._rebuild_standouts_with_retry(load, attempts=3, wait=100)

    assert slept == [100, 200]


def test_the_rebuild_is_forced_every_attempt(monkeypatch):
    """An unforced call returns a 'building' placeholder and writes nothing."""
    monkeypatch.setattr(hub_snapshots.time, "sleep", lambda _s: None)
    forced: list[bool] = []

    def load(*, period, force_refresh=False, **kw):
        forced.append(force_refresh)
        if len(forced) < 2:
            raise RuntimeError(RATE_LIMIT)
        return {"players": []}

    hub_snapshots._rebuild_standouts_with_retry(load, attempts=3, wait=0.01)

    assert forced == [True, True]


def test_boot_warm_uses_the_retry_path(monkeypatch):
    """Wire-up check — the retry is useless if warm_scouting_from_disk skips it."""
    monkeypatch.setattr(hub_snapshots.time, "sleep", lambda _s: None)
    monkeypatch.setattr("app.scoutable_teams.build_leagues_board", lambda **kw: {})
    monkeypatch.setattr("app.home_dashboard._load_standouts_disk", lambda key: None)

    load, calls = _flaky(fail_times=1)
    monkeypatch.setattr("app.who_to_scout._load_standouts_raw_payload", load)

    result = hub_snapshots.warm_scouting_from_disk(rebuild_attempts=3, retry_wait=0.01)

    assert len(calls) == 2
    assert result["who_to_scout"] == "rebuilt on attempt 2"


def test_boot_warm_still_reads_disk_when_the_cache_is_good(monkeypatch):
    """The cheap path must stay cheap — no forced Impect work."""
    monkeypatch.setattr("app.scoutable_teams.build_leagues_board", lambda **kw: {})
    monkeypatch.setattr(
        "app.home_dashboard._load_standouts_disk", lambda key: (0.0, {"players": [1]})
    )
    forced: list[bool] = []
    monkeypatch.setattr(
        "app.who_to_scout._load_standouts_raw_payload",
        lambda *, period, force_refresh=False, **kw: forced.append(force_refresh) or {},
    )

    result = hub_snapshots.warm_scouting_from_disk()

    assert result["who_to_scout"] == "warm"
    assert forced == [False]


def test_boot_warm_waits_long_enough_to_clear_the_other_startup_jobs():
    """15s put this inside the same rate-limit window as the analysis probe."""
    import inspect

    source = inspect.getsource(hub_snapshots.start_daily_scheduler)
    assert "time.sleep(90)" in source, "boot warm delay was shortened"
