import json

import pytest
from fastapi import FastAPI

import app.shadow_teams as shadow
from app.apps_manifest import APPS
from app.shadow_teams_context import SHADOW_CONTEXT


def _season(club, season, competition, pct, *, position=1, recruitment=True):
    return {
        "club": club,
        "season": season,
        "season_long": f"20{season[:2]}/{season[3:]}",
        "label": f"{competition} {season}",
        "competition": competition,
        "current": False,
        "teams": 24,
        "iteration_id": 1,
        "table": {"position": position, "played": 46, "points": 90, "xppg": 1.8, "outcome": "Champions"},
        "style": {
            "xg_against": {"value": 0.9, "rank_high": 22, "pct_high": pct["xg_against"]},
            "possession": {"value": 45.0, "rank_high": 12, "pct_high": pct["possession"]},
        },
        "squad": {"summary": {"avg_age": 27.0, "players_used": 28}, "players": [], "xi": [], "formations": []},
        "recruitment": {"covered": recruitment, "retained_share_prev": 70.0, "hit_rate": 50.0},
        "patterns": {
            "overall": {"p": 46}, "home": {"p": 23, "ppg": 2.1}, "away": {"p": 23, "ppg": 1.7},
            "vs_top7": {"p": 12, "ppg": 1.5}, "clean_sheets": 20, "points_from_behind": 10,
            "half_time": {"trailing": {"p": 10}, "leading": {"p": 20, "w": 18}},
        },
    }


def _raw():
    metrics = [
        {"key": "xg_against", "group": "chances", "label": "xG against", "unit": "/g", "digits": 2, "better": "low"},
        {"key": "possession", "group": "possession", "label": "Possession", "unit": "%", "digits": 1, "better": None},
    ]
    clubs = {}
    for i, key in enumerate(("lincoln", "stockport", "bradford")):
        clubs[key] = {
            "key": key, "squad_id": 900 + i, "name": key.title(), "short": key.title(),
            "seasons": [_season(key, SHADOW_CONTEXT[key]["spotlight_season"], "League One",
                                {"xg_against": 5 + i, "possession": 20 + 40 * i})],
        }
    vale = {"key": "vale", "squad_id": 882, "name": "Port Vale", "short": "Port Vale",
            "seasons": [_season("vale", "25/26", "League One", {"xg_against": 50, "possession": 50}, position=10)]}
    return {"metrics": metrics, "metric_groups": [], "clubs": clubs, "vale": vale, "leagues": {}}


def test_manifest_entry():
    app = next(a for a in APPS if a["id"] == "shadow-teams")
    assert app["group"] == "strategy"
    assert app["href"] == "/shadow-teams"
    assert app["router"] == "shadow_teams"


def test_template_marks_shared_traits():
    payload = shadow.build_payload(_raw())
    style = payload["template"]["style"]
    assert style["xg_against"]["shared"] == "low"
    assert style["possession"]["shared"] is None
    assert len(style["xg_against"]["by_season"]) == len(payload["template"]["seasons"])
    assert payload["club_order"] == ["lincoln", "stockport", "bradford"]
    assert payload["clubs"]["lincoln"]["pillars"]
    assert payload["vale"]["seasons"][0]["pattern_rates"]["home_ppg"] == 2.1


def test_goal_mix_shares():
    cs = {"goals": {
        "total": 10,
        "phases": {"possession": {"goals": 2}, "transition": {"goals": 5}, "set_piece": {"goals": 3}, "second_ball": {"goals": 0}},
        "actions": {"header": {"goals": 4}, "close_range": {"goals": 6}},
        "groups": {"ATT": {"goals": 6}, "DEF": {"goals": 4}},
        "against": {"total": 4, "matches": 2, "phases": {"set_piece": 1, "transition": 3}},
    }}
    mix = shadow.goal_mix(cs)
    assert mix["phases"]["transition"] == 50.0
    assert mix["groups"]["DEF"] == 40.0
    assert mix["against_phases"]["transition"] == 75.0
    assert shadow.goal_mix({"goals": {"total": 0}}) == {}


def test_routes_registered():
    app = FastAPI()
    shadow.register_shadow_teams_routes(app)
    paths = {route.path for route in app.routes}
    assert {"/shadow-teams", "/api/shadow-teams/data", "/api/shadow-teams/notes"} <= paths


def test_load_and_notes(tmp_path, monkeypatch):
    data_path = tmp_path / "shadow-teams.json"
    data_path.write_text(json.dumps(_raw()), encoding="utf-8")
    monkeypatch.setattr(shadow, "DATA_CANDIDATES", (data_path,))
    monkeypatch.setattr(shadow, "NOTES_PATH", tmp_path / "notes.json")
    monkeypatch.setattr(shadow, "_cache", {"mtime": None, "payload": None})

    body = shadow._load_raw()
    assert set(body["clubs"]) == {"lincoln", "stockport", "bradford"}
    assert "template" in body

    with pytest.raises(ValueError):
        shadow.add_note("lincoln", "  ", "staff")
    with pytest.raises(ValueError):
        shadow.add_note("nowhere", "x", "staff")
    note = shadow.add_note("lincoln", "Ask about the 4-2-3-1", "staff")
    assert shadow.read_notes()[0]["text"] == "Ask about the 4-2-3-1"
    assert shadow.delete_note(note["id"]) is True
    assert shadow.delete_note(note["id"]) is False
    assert shadow.read_notes() == []


def test_missing_data_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow, "DATA_CANDIDATES", (tmp_path / "missing.json",))
    monkeypatch.setattr(shadow, "_cache", {"mtime": None, "payload": None})
    with pytest.raises(FileNotFoundError):
        shadow._load_raw()
