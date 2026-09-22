"""Bonus Tracker — provisions seed + matchday log."""

from app.apps_manifest import APPS, required_sidebar_titles
from app.bonus_tracker import APPEARANCE_BONUS_LABELS, build_bonus_payload, reseed_from_excel_seed


def test_bonus_tracker_on_admin_rail():
    assert "Bonus Tracker" in required_sidebar_titles()
    row = next(app for app in APPS if app["id"] == "bonus-tracker")
    assert row["group"] == "admin"


def test_bonus_seed_loads_players(tmp_path, monkeypatch):
    monkeypatch.setattr("app.bonus_tracker.DATA_DIR", tmp_path)
    monkeypatch.setattr("app.bonus_tracker.DATA_PATH", tmp_path / "bonuses.json")
    payload = reseed_from_excel_seed(replace_players=True)
    assert payload["summary"]["players"] >= 20
    assert payload["summary"]["with_provisions"] >= 10
    byers = next(p for p in payload["players"] if "Byers" in p["name"])
    assert byers["appearance_bonus"] == "league_start"
    assert "Goal" in byers["provisions"]


def test_appearance_bonus_labels():
    assert "league_start_or_sub" in APPEARANCE_BONUS_LABELS
