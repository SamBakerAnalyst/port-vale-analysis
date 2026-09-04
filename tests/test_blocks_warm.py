"""Blocks Analysis should be warm before a coach opens it.

Its match-KPI cache lapses after six hours, so whoever opened the page next
rebuilt it themselves and sat on "Loading…" for about a minute. That happened
at 14:28 on 4 Sep, three minutes after a deploy — the cache files on Live carry
that exact timestamp because the page load is what wrote them.
"""

from __future__ import annotations

import app.main  # noqa: F401 - initialise the app so router imports resolve
from app import hub_snapshots


def test_warm_reports_the_blocks_it_built(monkeypatch):
    monkeypatch.setattr(
        "app.blocks_analysis.build_blocks_analysis_payload",
        lambda force_refresh=False: {"blocks": [{"id": i} for i in range(9)]},
    )

    assert hub_snapshots.warm_blocks_analysis() == {"ok": True, "blocks": 9}


def test_warm_does_not_force_a_rebuild(monkeypatch):
    """Forcing would refetch from Impect every boot for no reason."""
    seen: list[bool] = []
    monkeypatch.setattr(
        "app.blocks_analysis.build_blocks_analysis_payload",
        lambda force_refresh=False: seen.append(force_refresh) or {"blocks": []},
    )

    hub_snapshots.warm_blocks_analysis()

    assert seen == [False]


def test_a_failing_warm_is_reported_not_raised(monkeypatch):
    """A provider wobble at boot must not stop the app coming up."""
    def boom(force_refresh=False):
        raise RuntimeError("Impect said no")

    monkeypatch.setattr("app.blocks_analysis.build_blocks_analysis_payload", boom)

    result = hub_snapshots.warm_blocks_analysis()

    assert result["ok"] is False
    assert "Impect said no" in result["error"]


def test_the_daily_analysis_refresh_includes_blocks(monkeypatch):
    """Covers the six-hour KPI expiry without a person triggering it."""
    calls: list[str] = []
    monkeypatch.setattr(
        hub_snapshots, "refresh_analysis", lambda: calls.append("analysis") or {}
    )
    monkeypatch.setattr(
        hub_snapshots,
        "warm_blocks_analysis",
        lambda: calls.append("blocks") or {"ok": True, "blocks": 9},
    )
    monkeypatch.setattr(hub_snapshots, "_write_meta", lambda updates: updates)

    result = hub_snapshots.refresh_snapshots("analysis")

    assert "blocks" in calls
    assert result["blocks_analysis"] == {"ok": True, "blocks": 9}


def test_boot_warm_covers_blocks_as_well_as_scouting():
    """Wire-up check — the warm is useless if boot never calls it."""
    import inspect

    source = inspect.getsource(hub_snapshots.start_daily_scheduler)
    assert "warm_blocks_analysis()" in source
    # and it must come after the scouting warm, not compete with it
    assert source.index("warm_scouting_from_disk()") < source.index(
        "warm_blocks_analysis()"
    )
