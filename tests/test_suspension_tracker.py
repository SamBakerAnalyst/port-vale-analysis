"""Suspension Tracker — offence codes + FotMob bucket split."""

from app.apps_manifest import APPS, required_sidebar_titles
from app.suspension_tracker import (
    YELLOW_OFFENCE_OPTIONS,
    _bucket_for_league,
    _risk_for_yellows,
    set_card_offence,
)


def test_suspension_tracker_is_on_admin_rail():
    titles = required_sidebar_titles()
    assert "Suspension Tracker" in titles
    row = next(app for app in APPS if app["id"] == "suspension-tracker")
    assert row["group"] == "admin"
    assert row["href"] == "/suspension-tracker"


def test_league_two_bucket_split():
    assert _bucket_for_league(109, "League Two") == "league_two"
    assert _bucket_for_league(133, "EFL Cup") == "efl_cup"
    assert _bucket_for_league(142, "EFL Trophy Northern Grp. D") == "efl_trophy"
    assert _bucket_for_league(0, "FA Cup") == "fa_cup"
    assert _bucket_for_league(0, "Friendly") == "other"


def test_yellow_offence_codes_cover_c1_subtypes_and_c2_to_c7():
    values = {row["value"] for row in YELLOW_OFFENCE_OPTIONS}
    assert "C1-FT" in values
    assert "C1-DI" in values
    assert "C2" in values
    assert "C2-SINBIN" in values
    assert "C7" in values


def test_risk_thresholds():
    league = (
        {"cards": 5, "label": "1-match ban"},
        {"cards": 10, "label": "2-match ban"},
        {"cards": 15, "label": "3-match ban"},
    )
    assert _risk_for_yellows(3, thresholds=league)[0] == "OK"
    assert _risk_for_yellows(4, thresholds=league)[0] == "Watch"
    assert _risk_for_yellows(5, thresholds=league)[0] == "Watch"
    assert _risk_for_yellows(15, thresholds=league)[0] == "Banned"


def test_offence_persist_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.suspension_tracker.DATA_PATH", tmp_path / "offences.json"
    )
    monkeypatch.setattr(
        "app.suspension_tracker.DATA_DIR", tmp_path
    )
    saved = set_card_offence("123-456-789", "C1-FT")
    assert saved["offence_code"] == "C1-FT"
    cleared = set_card_offence("123-456-789", None)
    assert cleared["offence_code"] is None
