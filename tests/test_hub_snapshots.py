from app.hub_snapshots import apply_player_stats_to_row, player_stat_key, put_player_stats


def test_player_stat_key():
    assert player_stat_key(12, "ATTACKING_MIDFIELD") == "12|ATTACKING_MIDFIELD"


def test_put_and_apply_player_stats(tmp_path, monkeypatch):
    monkeypatch.setattr("app.hub_snapshots.HUB_SNAPSHOTS_DIR", tmp_path)
    monkeypatch.setattr("app.hub_snapshots.PLAYERS_PATH", tmp_path / "players.json")
    monkeypatch.setattr("app.hub_snapshots.META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr("app.hub_snapshots.STANDINGS_PATH", tmp_path / "standings.json")

    put_player_stats(
        99,
        "ATTACKING_MIDFIELD",
        {
            "overall_score": 61.2,
            "minutes": 412,
            "top_profile": "Creator",
            "top_profile_score": 74.1,
            "minutes_by_position": [{"position": "ATTACKING_MIDFIELD", "label": "AM", "minutes": 412}],
            "stats_score_version": 5,
        },
        name="Test Player",
    )
    row = {
        "player_id": 99,
        "position": "ATTACKING_MIDFIELD",
        "name": "Test Player",
        "overall_score": None,
        "minutes": None,
    }
    assert apply_player_stats_to_row(row) is True
    assert row["overall_score"] == 61.2
    assert row["minutes"] == 412
    assert row["top_profile"] == "Creator"


# --- Analysis cache refresh timing ------------------------------------------
# Impect have no fixed upload time, so the analysis refresh polls for the data
# instead of firing on a clock. These pin that it waits rather than caching a
# match the provider has not finished publishing.

from datetime import datetime
from zoneinfo import ZoneInfo

import app.analysis_cache as analysis_cache
import app.hub_snapshots as hub_snapshots

LONDON = ZoneInfo("Europe/London")


def _freeze(monkeypatch, when: datetime):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return when if tz is None else when.astimezone(tz)

    monkeypatch.setattr(hub_snapshots, "datetime", FrozenDatetime)


def test_window_opens_immediately_when_already_inside_it(monkeypatch):
    _freeze(monkeypatch, datetime(2026, 9, 4, 11, 0, tzinfo=LONDON))
    assert hub_snapshots._seconds_until_analysis_window() == 0.0


def test_window_waits_until_morning_when_too_early(monkeypatch):
    _freeze(monkeypatch, datetime(2026, 9, 4, 6, 0, tzinfo=LONDON))
    delay = hub_snapshots._seconds_until_analysis_window()
    assert delay == 2 * 3600


def test_window_rolls_to_tomorrow_after_give_up(monkeypatch):
    _freeze(monkeypatch, datetime(2026, 9, 4, 23, 0, tzinfo=LONDON))
    delay = hub_snapshots._seconds_until_analysis_window()
    # 23:00 -> 08:00 next day
    assert delay == 9 * 3600


def test_give_up_hour_is_after_window_start():
    assert hub_snapshots.ANALYSIS_WINDOW_START_HOUR < hub_snapshots.ANALYSIS_GIVE_UP_HOUR
    assert hub_snapshots.ANALYSIS_POLL_MINUTES > 0


def test_provider_not_ready_when_no_events_published(monkeypatch):
    """A played match with zero events means Impect have not finished."""
    monkeypatch.setattr(
        analysis_cache,
        "_probe_newest_match_events",
        lambda: (270749, []),
        raising=False,
    )
    result = analysis_cache.provider_ready()
    assert result["ready"] is False
    assert "270749" in result["detail"]


def test_provider_ready_when_events_published(monkeypatch):
    monkeypatch.setattr(
        analysis_cache,
        "_probe_newest_match_events",
        lambda: (270749, [{"id": 1}, {"id": 2}]),
        raising=False,
    )
    result = analysis_cache.provider_ready()
    assert result["ready"] is True
    assert result["event_count"] == 2


def test_provider_not_ready_when_no_completed_fixtures(monkeypatch):
    monkeypatch.setattr(
        analysis_cache, "_probe_newest_match_events", lambda: (None, []), raising=False
    )
    assert analysis_cache.provider_ready()["ready"] is False


def test_readiness_probe_never_raises(monkeypatch):
    """A provider outage must not kill the refresh thread."""

    def boom():
        raise RuntimeError("Impect 503")

    monkeypatch.setattr(
        analysis_cache, "_probe_newest_match_events", boom, raising=False
    )
    result = analysis_cache.provider_ready()
    assert result["ready"] is False
    assert "Impect 503" in result["detail"]


def test_daily_refresh_scopes_include_strategy_reports():
    assert "strategy_tracker" in hub_snapshots.VALID_SCOPES
    assert "win_drivers" in hub_snapshots.VALID_SCOPES
    assert "standings" in hub_snapshots.VALID_SCOPES


def test_refresh_win_drivers_forces_impect_rebuild(monkeypatch):
    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        "app.win_drivers.win_drivers_meta",
        lambda force_refresh=False: (
            calls.append(("meta", force_refresh))
            or {"seasons": [{"iteration_id": 99}]}
        ),
    )
    monkeypatch.setattr(
        "app.win_drivers.build_history",
        lambda force_refresh=False: calls.append(("history", force_refresh)) or {},
    )
    monkeypatch.setattr(
        "app.win_drivers.build_table",
        lambda iid, force_refresh=False: calls.append(("table", force_refresh)) or {},
    )
    monkeypatch.setattr(hub_snapshots, "_write_meta", lambda updates: updates)

    result = hub_snapshots.refresh_win_drivers()
    assert result["seasons_rebuilt"] == [99]
    assert ("meta", True) in calls
    assert ("history", True) in calls
    assert ("table", True) in calls


def test_refresh_strategy_tracker_forces_impect_rebuild(monkeypatch):
    calls: list[bool] = []

    monkeypatch.setattr(
        "app.strategy_tracker.build_strategy_tracker",
        lambda competition="League Two", force_refresh=False: (
            calls.append(force_refresh)
            or {"iteration_id": 11, "season": "2026-2027", "generated_at": "now"}
        ),
    )
    monkeypatch.setattr(hub_snapshots, "_write_meta", lambda updates: updates)

    hub_snapshots.refresh_strategy_tracker()
    assert calls == [True]


def test_daily_refresh_scope_includes_scouting():
    """Who To Scout / Scoutable Teams build lazily, so the 5am job must warm them."""
    assert "scouting" in hub_snapshots.VALID_SCOPES


def test_refresh_scouting_forces_a_rebuild_of_both_tools(monkeypatch):
    import app.main  # noqa: F401 - resolves the router import order

    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        "app.who_to_scout._load_standouts_raw_payload",
        lambda *, period, force_refresh=False, **kw: (
            calls.append(("who-to-scout", force_refresh))
            or {"players": [{"id": 1}, {"id": 2}]}
        ),
    )
    monkeypatch.setattr(
        "app.scoutable_teams.build_leagues_board",
        lambda force_refresh=False: (
            calls.append(("scoutable-teams", force_refresh))
            or {"leagues": [{"clubs": [{"id": 1}, {"id": 2}, {"id": 3}]}]}
        ),
    )
    monkeypatch.setattr(hub_snapshots, "_write_meta", lambda updates: updates)

    result = hub_snapshots.refresh_scouting()

    # A non-forced call would return a "building" placeholder and leave the page polling.
    assert ("who-to-scout", True) in calls
    assert ("scoutable-teams", True) in calls
    assert result["who_to_scout"] == {"ok": True, "players": 2}
    assert result["scoutable_teams"] == {"ok": True, "clubs": 3}


def test_refresh_scouting_reports_one_tool_failing_without_losing_the_other(monkeypatch):
    import app.main  # noqa: F401

    monkeypatch.setattr(
        "app.who_to_scout._load_standouts_raw_payload",
        lambda *, period, force_refresh=False, **kw: (_ for _ in ()).throw(
            RuntimeError("impect down")
        ),
    )
    monkeypatch.setattr(
        "app.scoutable_teams.build_leagues_board",
        lambda force_refresh=False: {"leagues": [{"clubs": [{"id": 1}]}]},
    )
    monkeypatch.setattr(hub_snapshots, "_write_meta", lambda updates: updates)

    result = hub_snapshots.refresh_scouting()
    assert result["who_to_scout"]["ok"] is False
    assert "impect down" in result["who_to_scout"]["error"]
    assert result["scoutable_teams"]["ok"] is True
