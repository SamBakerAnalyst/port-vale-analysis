"""Bonus Tracker — provisions seed + clause progress."""

import pytest

from app.apps_manifest import APPS, required_sidebar_titles
from app.bonus_tracker import (
    APPEARANCE_BONUS_LABELS,
    _match_playing_time,
    build_bonus_payload,
    parse_provision_clauses,
    reseed_from_excel_seed,
    same_player_name,
)


@pytest.fixture
def _no_availability_calls(monkeypatch):
    monkeypatch.setattr("app.bonus_tracker._playing_time_index", lambda season: {})


def test_bonus_tracker_on_admin_rail():
    assert "Bonus Tracker" in required_sidebar_titles()
    row = next(app for app in APPS if app["id"] == "bonus-tracker")
    assert row["group"] == "admin"


def test_bonus_seed_loads_players(tmp_path, monkeypatch, _no_availability_calls):
    monkeypatch.setattr("app.bonus_tracker.DATA_DIR", tmp_path)
    monkeypatch.setattr("app.bonus_tracker.DATA_PATH", tmp_path / "bonuses.json")
    payload = reseed_from_excel_seed(replace_players=True)
    names = {p["name"] for p in payload["players"]}
    assert payload["summary"]["players"] >= 20
    assert payload["summary"]["with_provisions"] >= 10
    assert "Maleace Asamoah" not in names
    assert "Jasper Moon" not in names
    byers = next(p for p in payload["players"] if "Byers" in p["name"])
    assert byers["appearance_bonus"] == "league_start"
    assert "Goal" in byers["provisions"]
    assert byers["clauses"]


def test_players_without_bonus_or_clause_are_dropped(tmp_path, monkeypatch, _no_availability_calls):
    monkeypatch.setattr("app.bonus_tracker.DATA_DIR", tmp_path)
    monkeypatch.setattr("app.bonus_tracker.DATA_PATH", tmp_path / "bonuses.json")
    store = {
        "players": [
            {
                "id": "empty-one",
                "name": "No Clause",
                "appearance_bonus": "none",
                "provisions": "",
                "active": True,
            },
            {
                "id": "has-clause",
                "name": "Matthew Craig",
                "appearance_bonus": "none",
                "provisions": "Basic increase after 30 and 60 league starts",
                "active": True,
            },
        ],
        "matchday": [],
    }
    (tmp_path / "bonuses.json").write_text(__import__("json").dumps(store), encoding="utf-8")
    payload = build_bonus_payload()
    names = [row["name"] for row in payload["players"]]
    assert names == ["Matthew Craig"]


def test_parse_app_and_start_thresholds():
    bussell = parse_provision_clauses(
        "Goal/Assist/Clean Sheet bonus when won/drawn - Basic pay increases after 5, 14 and 28 league apps"
    )
    assert bussell[0]["kind"] == "matchday"
    assert bussell[1]["kind"] == "league_apps"
    assert bussell[1]["targets"] == [5, 14, 28]

    craig = parse_provision_clauses("Basic increase after 30 and 60 league starts")
    assert craig[0]["kind"] == "league_starts"
    assert craig[0]["targets"] == [30, 60]

    montsma = parse_provision_clauses("Option year after 23 league starts")
    assert montsma[0]["targets"] == [23]


def test_playing_time_index_reads_availability_roster(monkeypatch):
    monkeypatch.setattr("app.availability_tracker.fotmob_league_playing_time", lambda season: {})
    monkeypatch.setattr(
        "app.availability_tracker.build_availability_payload",
        lambda season, refresh=False: {
            "roster": [
                {
                    "name": "George Byers",
                    "impact": {
                        "league_starts": 8,
                        "league_appearances": 9,
                        "league_minutes": 720,
                    },
                }
            ]
        },
    )
    from app.bonus_tracker import _match_playing_time, _playing_time_index

    index = _playing_time_index("26/27")
    assert _match_playing_time("George Byers", index)["league_starts"] == 8


def test_oli_lynch_matches_oliver_lynch():
    assert same_player_name("Oli Lynch", "Oliver Lynch")
    assert same_player_name("Cam Humphreys", "Cameron Humphreys")
    assert not same_player_name("Connor Hall", "George Hall")
    index = {
        "oliverlynch": {
            "_name": "Oliver Lynch",
            "league_starts": 7,
            "league_appearances": 7,
            "league_minutes": 536,
            "league_goals": 0,
            "league_assists": 0,
            "goal_contributions": 0,
        },
        "aaronomcgowan": {
            "_name": "Aaron McGowan",
            "league_starts": 3,
            "league_appearances": 3,
            "league_minutes": 270,
            "league_goals": 0,
            "league_assists": 0,
            "goal_contributions": 0,
        },
    }
    assert _match_playing_time("Oli Lynch", index)["league_starts"] == 7
    assert _match_playing_time("Aaron McGowan", index)["league_starts"] == 3


def test_clause_progress_uses_playing_time(tmp_path, monkeypatch):
    # local playing-time stub — do not use the empty-index fixture
    monkeypatch.setattr("app.bonus_tracker.DATA_DIR", tmp_path)
    monkeypatch.setattr("app.bonus_tracker.DATA_PATH", tmp_path / "bonuses.json")
    monkeypatch.setattr(
        "app.bonus_tracker._playing_time_index",
        lambda season: {
            "charliebussell": {
                "league_starts": 4,
                "league_appearances": 16,
                "league_minutes": 1100,
            }
        },
    )
    store = {
        "players": [
            {
                "id": "charlie-bussell",
                "name": "Charlie Bussell",
                "appearance_bonus": "none",
                "provisions": "Basic pay increases after 5, 14 and 28 league apps",
                "active": True,
            }
        ],
        "matchday": [],
    }
    (tmp_path / "bonuses.json").write_text(__import__("json").dumps(store), encoding="utf-8")
    payload = build_bonus_payload()
    row = payload["players"][0]
    assert row["playing_time"]["league_appearances"] == 16
    apps = next(clause for clause in row["clauses"] if clause["kind"] == "league_apps")
    assert apps["thresholds"][0]["met"] is True
    assert apps["thresholds"][1]["met"] is True
    assert apps["thresholds"][2]["met"] is False
    assert apps["thresholds"][2]["remaining"] == 12
    assert apps["next_target"] == 28


def test_appearance_bonus_labels():
    assert "league_start_or_sub" in APPEARANCE_BONUS_LABELS


def test_fotmob_named_stat_reads_goals():
    from app.availability_tracker import _extract_fotmob_named_stat

    row = {
        "stats": [
            {
                "stats": {
                    "Minutes played": {"stat": {"value": 90}},
                    "Goals": {"stat": {"value": 2}},
                    "Assists": {"stat": {"value": 1}},
                }
            }
        ]
    }
    assert _extract_fotmob_named_stat(row, ("Goals", "Goals scored", "Goal")) == 2
    assert _extract_fotmob_named_stat(row, ("Assists", "Assist")) == 1


def test_byers_goal_contribution_progress(tmp_path, monkeypatch):
    monkeypatch.setattr("app.bonus_tracker.DATA_DIR", tmp_path)
    monkeypatch.setattr("app.bonus_tracker.DATA_PATH", tmp_path / "bonuses.json")
    monkeypatch.setattr(
        "app.bonus_tracker._playing_time_index",
        lambda season: {
            "georgebyers": {
                "league_starts": 4,
                "league_appearances": 4,
                "league_minutes": 242,
                "league_goals": 2,
                "league_assists": 0,
                "goal_contributions": 2,
            }
        },
    )
    store = {
        "players": [
            {
                "id": "george-byers",
                "name": "George Byers",
                "appearance_bonus": "league_start",
                "provisions": "Goal bonus - Bonus after 20 goal contributions",
                "active": True,
            }
        ],
        "matchday": [],
    }
    (tmp_path / "bonuses.json").write_text(__import__("json").dumps(store), encoding="utf-8")
    payload = build_bonus_payload()
    row = payload["players"][0]
    assert row["playing_time"]["league_goals"] == 2
    goal = next(c for c in row["clauses"] if c["text"] == "Goal bonus")
    assert goal["current"] == 2
    contrib = next(c for c in row["clauses"] if "20 goal contributions" in c["text"])
    assert contrib["thresholds"][0]["label"] == "2 / 20 goal contributions"
    assert contrib["thresholds"][0]["remaining"] == 18
