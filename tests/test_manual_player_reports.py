"""Manual player reports — search any player, file without a match XI, credit the real scout."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

import app.main  # noqa: F401 - initialise the app so the router imports resolve

from app import player_catalog as catalog
from app import player_reports as reports
from app import reports_library as library
from app import video_watch as vw
from app.player_reports import DetailedReportBody, GeneralReportBody


STANDOUTS = [
    {"playerId": 501, "name": "Jamie Ndlovu", "club": "Barnet", "league": "National League",
     "age": 23, "position": "CENTER_FORWARD", "positionLabel": "Centre-forward", "minutes": 900},
    {"playerId": 501, "name": "Jamie Ndlovu", "club": "Barnet", "league": "National League",
     "age": 23, "position": "CENTER_FORWARD", "positionLabel": "Centre-forward", "minutes": 100},
    {"playerId": 502, "name": "José Álvarez", "club": "Crewe Alexandra", "league": "League Two",
     "age": 21, "position": "LEFT_MIDFIELD", "positionLabel": "Left midfield", "minutes": 400},
    {"playerId": 503, "name": "Sam Jameson", "club": "Walsall", "league": "League Two",
     "age": 28, "position": "GOALKEEPER", "positionLabel": "Goalkeeper", "minutes": 1200},
]


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "PLAYER_REPORTS_PATH", tmp_path / "player-reports.json")
    monkeypatch.setattr(catalog, "_standouts_rows", lambda: list(STANDOUTS))
    monkeypatch.setattr(catalog, "_pipeline_rows", lambda: {})
    monkeypatch.setattr(library._PlayerFallback, "_pipeline_index", lambda self: {})
    monkeypatch.setattr(vw, "_pipeline_for_player", lambda _pid: None)
    monkeypatch.setattr(vw, "_real_activity", lambda pid, name: {"notes": [], "reports": [], "ability": None})
    monkeypatch.setattr(vw, "scout_notes_for_player", lambda pid: {})
    monkeypatch.setattr(reports, "_cached_contract_expires", lambda name, club: "")
    return tmp_path


class _Response:
    def __init__(self, data):
        self._data = data
        self.status_code = 200
        self.text = json.dumps(data, default=str)

    def json(self):
        return self._data


class _Client:
    """Calls the registered route handlers directly, as the logged-in user Sam."""

    _BODIES = {
        "/api/video-watch/general-report": GeneralReportBody,
        "/api/video-watch/detailed-report": DetailedReportBody,
    }

    def __init__(self):
        from fastapi import FastAPI

        api = FastAPI()
        vw.register_video_watch_routes(api)
        library.register_reports_library_routes(api)
        self._routes = {(route.path, method): route.endpoint for route in api.routes
                        for method in getattr(route, "methods", ())}

    def post(self, path, json):
        handler = self._routes[(path, "POST")]
        return _Response(handler(request=None, body=self._BODIES[path](**json)))

    def get(self, path, params=None):
        import inspect

        handler = self._routes[(path, "GET")]
        kwargs = {
            name: getattr(param.default, "default", param.default)
            for name, param in inspect.signature(handler).parameters.items()
            if param.default is not inspect.Parameter.empty
        }
        kwargs.update(params or {})
        return _Response(handler(**kwargs))


def _client(monkeypatch=None):
    return _Client()


@pytest.fixture(autouse=True)
def _as_sam(monkeypatch):
    monkeypatch.setattr(vw, "_staff_name", lambda request: "Sam")


def test_search_finds_players_across_the_catalog_not_one_team_sheet(isolated):
    rows = catalog.search_players("jam")["players"]
    assert [row["player_id"] for row in rows] == [501, 503]
    assert rows[0]["club"] == "Barnet" and rows[0]["position_short"] == "ST"
    accent = catalog.search_players("jose alvarez")["players"]
    assert [row["player_id"] for row in accent] == [502]
    assert [r["player_id"] for r in catalog.search_players("jam", club="wals")["players"]] == [503]
    assert [r["player_id"] for r in catalog.search_players("a", club="crewe", position="LEFT_WINGER")["players"]] == [502]
    empty = catalog.search_players("zzzz")
    assert empty["players"] == [] and "add him" in empty["message"]
    assert catalog.search_players("j")["players"] == []


def test_player_stub_is_reused_and_searchable(isolated):
    first = reports.create_player_stub(name="Unknown Winger", club="Gateshead", position="LEFT_WINGER", staff="Sam")
    again = reports.create_player_stub(name="unknown winger", club="gateshead")
    assert first["player_id"] == again["player_id"] >= reports.STUB_PLAYER_ID_START
    rows = catalog.search_players("unknown")["players"]
    assert rows[0]["player_id"] == first["player_id"]
    assert rows[0]["source"] == "stub" and rows[0]["is_stub"] is True
    with pytest.raises(HTTPException):
        reports.create_player_stub(name=" ")


def test_manual_report_saves_without_a_fixture_and_credits_the_scout(isolated):
    client = _client()
    res = client.post("/api/video-watch/general-report", json={
        "player_id": 501,
        "fixture_id": "",
        "source": "manual",
        "scout": "Tom Fry",
        "match_info": {"competition": "FA Trophy", "opponent": "Woking", "match_date": "2026-09-27",
                       "viewing": "live", "home_away": "away"},
        "position_in_game": "CENTER_FORWARD",
        "notes": "Sharp movement in the box.",
        "match_rating": 7,
        "pvfc_level": "B",
        "next_action": "high_priority",
    })
    assert res.status_code == 200, res.text
    data = res.json()
    token = data["fixture_id"]
    assert token.startswith("manual-") and data["source"] == "manual"
    assert data["player"]["name"] == "Jamie Ndlovu"
    assert data["player"]["report_context"]["scout"] == "Tom Fry"
    assert data["player"]["home_away"]["label"] == "Away"

    stored = json.loads((isolated / "player-reports.json").read_text())["general_reports"][f"501:{token}"]
    assert stored["source"] == "manual"
    assert stored["scout"] == "Tom Fry"
    assert stored["fixture_label"] == "Woking vs Barnet"
    assert stored["match_info"]["viewing"] == "live"

    payload = client.get("/api/reports-library").json()
    row = payload["reports"][0]
    assert payload["counts"]["manual"] == 1
    assert row["source"] == "manual" and row["scout"] == "Tom Fry"
    assert row["name"] == "Jamie Ndlovu" and row["club"] == "Barnet"
    assert row["match_rating"] == 7 and row["pvfc_level"] == "B" and row["next_action"] == "high_priority"
    assert row["home_away"] == "Away" and row["competition"] == "FA Trophy" and row["viewing_label"] == "Live"

    detail = client.get("/api/reports-library/report", params={
        "kind": "general", "player_id": 501, "fixture_id": token}).json()
    assert detail["summary"]["scout"] == "Tom Fry"
    assert detail["meta"]["match_info"]["opponent"] == "Woking"


def test_manual_report_edit_and_detailed_reuse_the_same_token(isolated):
    client = _client()
    token = client.post("/api/video-watch/general-report", json={
        "player_id": 503, "source": "manual", "scout": "Lee Darnbrough", "notes": "First look.",
    }).json()["fixture_id"]
    edit = client.post("/api/video-watch/general-report", json={
        "player_id": 503, "fixture_id": token, "source": "manual", "notes": "Second look.",
        "match_info": {"opponent": "Crewe"},
    })
    assert edit.json()["fixture_id"] == token
    detailed = client.post("/api/video-watch/detailed-report", json={
        "player_id": 503, "fixture_id": token, "source": "manual", "write_up": "Commanding.",
        "match_info": {"opponent": "Crewe"},
    })
    assert detailed.json()["fixture_id"] == token
    rows = client.get("/api/reports-library").json()["reports"]
    assert len(rows) == 2
    assert {row["scout"] for row in rows} == {"Lee Darnbrough"}
    general = next(row for row in rows if row["kind"] == "general")
    assert general["scout"] == "Lee Darnbrough"
    assert general["excerpt"] == "Second look."
    assert general["has_detailed"] is True
    reopened = client.get("/api/video-watch/player", params={"player_id": 503, "fixture_id": token}).json()["player"]
    assert reopened["name"] == "Sam Jameson"
    assert reopened["general_report"]["notes"] == "Second look."
    assert reopened["report_context"]["source"] == "manual"


def test_manual_save_cannot_overwrite_a_real_fixture(isolated):
    body = GeneralReportBody(player_id=501, fixture_id="real-fixture-9", source="manual")
    with pytest.raises(HTTPException):
        vw._prepare_report_body(body)


def test_fixture_reports_are_unchanged_but_can_credit_a_scout(isolated):
    body = DetailedReportBody(player_id=501, fixture_id="f1", name="Jamie Ndlovu", club="Barnet")
    vw._prepare_report_body(body)
    assert body.fixture_id == "f1" and body.source == "fixture"
    reports.save_general_report(player_id=501, fixture_id="f1", notes="Old flow.", staff="Sam",
                                meta={"name": "Jamie Ndlovu", "fixture_label": "Barnet vs Woking"})
    reports.save_general_report(player_id=501, fixture_id="f1", notes="Credited.", staff="Sam",
                                meta={"scout": "Martin Foyle"})
    reports.save_general_report(player_id=501, fixture_id="f1", notes="Edited again.", staff="Sam", meta={})
    row = library.list_reports()["reports"][0]
    assert row["source"] == "fixture"
    assert row["scout"] == "Martin Foyle"
    assert row["fixture_label"] == "Barnet vs Woking"
    assert "Martin Foyle" in reports.known_scouts()


def test_stub_reports_list_with_their_details(isolated):
    stub = reports.create_player_stub(name="Trialist Keeper", club="Hednesford", league="Northern Premier")
    reports.save_general_report(
        player_id=stub["player_id"], fixture_id=reports.new_manual_fixture_id(), notes="Big frame.",
        meta={"source": "manual", "scout": "Tommy Johnson"},
    )
    row = library.list_reports()["reports"][0]
    assert row["name"] == "Trialist Keeper" and row["club"] == "Hednesford"
    assert row["is_stub"] is True and row["scout"] == "Tommy Johnson"
