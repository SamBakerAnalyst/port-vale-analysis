"""Opposition Hub — opponent dossier built from the analysis lake only."""

from __future__ import annotations

import app.analysis_cache as analysis_cache
from app import opposition_hub as oh
from app.analysis_cache import write_json
from app.apps_manifest import APPS, required_sidebar_titles

VALE, OPP, C, D = 882, 953, 901, 954


def _match(mid, home, away, hg, ag, day):
    return {"matchId": mid, "date": f"2026-09-{day:02d}T14:00:00Z", "home": home, "away": away, "hg": hg, "ag": ag}


MATCHES = [
    _match(1, OPP, C, 2, 0, 1),
    _match(2, VALE, D, 1, 1, 1),
    _match(3, D, OPP, 1, 1, 8),
    _match(4, C, VALE, 0, 3, 8),
    _match(5, OPP, VALE, 0, 2, 15),
    _match(6, C, D, 2, 2, 15),
]


def _threat_block(total, cross=0.0, transition=0.0, player=(1001, "Andy Cook")):
    return {
        "total": total,
        "count": 10,
        "actions": {"LOW_PASS": total - cross, "LOW_CROSS": cross} if cross else {"LOW_PASS": total},
        "actionCounts": {"LOW_PASS": 6, "LOW_CROSS": 4},
        "phases": {"IN_POSSESSION": total - transition, "ATTACKING_TRANSITION": transition},
        "zonesStart": {"WL": total / 2, "CB": total / 2},
        "zonesEnd": {"IB": total / 2, "IBWR": total / 2},
        "players": {str(player[0]): {"id": player[0], "name": player[1], "pxt": total, "count": 10}},
        "passes": [{"id": 9, "action": "LOW_CROSS", "label": "Low cross", "family": "cross", "color": "#38bdf8",
                    "pxt": 0.2, "x1": 30, "y1": 25, "x2": 48, "y2": 2, "phase": "IN_POSSESSION",
                    "player": player[1], "playerId": player[0], "matchId": 0}],
    }


def _iv(bw, aw, al):
    return {"bw": bw, "di": 200.0, "oi": 210.0, "bwd": 10.0, "gw": 30.0, "gl": 30.0, "aw": aw, "al": al, "threat": 0.5}


def _xg(count, xg, goals=0):
    blank = {"count": 0, "goals": 0, "xg": 0.0, "penCount": 0, "penGoals": 0, "penXg": 0.0}
    return {
        "excellent": {**blank, "count": 1, "goals": goals, "xg": 0.4},
        "very_good": dict(blank),
        "ok": dict(blank),
        "poor": {**blank, "count": count, "xg": xg},
        "very_poor": dict(blank),
    }


def _seed(tmp_path, monkeypatch, *, with_squad=True):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    oh.clear_memo()
    write_json("sp-base", "26-27", {
        "season": "26/27", "iterationId": 2120, "competition": "League Two", "valeId": VALE,
        "names": {str(VALE): "Port Vale", str(OPP): "Grimsby Town", str(C): "Crawley Town", str(D): "Northampton Town"},
        "players": {"1001": "Andy Cook", "2002": "Jaheim Headley"},
        "matches": MATCHES,
    })
    for match in MATCHES:
        mid, home, away = match["matchId"], match["home"], match["away"]
        opp_cross = 0.4 if OPP in (home, away) else 0.1
        write_json("at-match", str(mid), {"matchId": mid, "squads": {
            str(home): _threat_block(1.5 if home == OPP else 1.0, cross=opp_cross if home == OPP else 0.1, transition=0.3),
            str(away): _threat_block(1.5 if away == OPP else 0.8, cross=opp_cross if away == OPP else 0.1, transition=0.2,
                                     player=(2002, "Jaheim Headley")),
        }})
        write_json("iv-league-match", str(mid), {"matchId": mid, "squads": {
            str(home): _iv(190.0, 40.0 if home != OPP else 20.0, 40.0),
            str(away): _iv(185.0, 40.0 if away != OPP else 20.0, 40.0),
        }})
        write_json("xg-league-match", str(mid), {"homeSquadId": home, "awaySquadId": away, "squads": {
            str(home): _xg(8, 0.6, goals=match["hg"]), str(away): _xg(6, 0.4, goals=match["ag"]),
        }})
    write_json("pre-match-fixtures", "fixtures_2120", {"fixtures": [
        {"match_id": 5, "scheduled_date": "2026-09-15T14:00:00Z", "is_home": False, "played": True,
         "opponent": {"id": OPP, "name": "Grimsby Town"}},
        {"match_id": 99, "scheduled_date": "2099-10-10T14:00:00Z", "is_home": True, "played": False,
         "opponent": {"id": OPP, "name": "Grimsby Town"}},
    ]})
    if with_squad:
        write_json("pre-match", "report_2120_953_99", {
            "generated_at": "2026-09-16T10:00:00Z",
            "iteration_id": 2120,
            "opponent": {"id": OPP, "name": "Grimsby Town"},
            "fixture": {"match_id": 99, "scheduled_date": "2099-10-10T14:00:00Z"},
            "overview": {"manager": "David Artell", "formations": ["4-3-3"]},
            "squad_list": {"formation_analysis": {"usage": [{"formation": "4-3-3", "time_pct": 90.0, "minutes": 270}]}},
            "form": [{"date": f["date"]} for f in oh.team_fixtures({"matches": MATCHES, "names": {}}, OPP)],
            "squad": [{
                "id": 1001, "name": "Andy Cook", "position": "Centre forward", "position_code": "CENTER_FORWARD",
                "band": "attack", "age": 35, "foot": "Left", "appearances": 3, "starts": 3, "minutes": 270,
                "goals": 2, "assists": 0, "shirt_number": 9, "current": True,
                "match_log": [{"m": 1, "min": 90, "s": True, "g": 1, "a": 0}, {"m": 3, "min": 90, "s": True, "g": 1, "a": 0},
                              {"m": 5, "min": 90, "s": True, "g": 0, "a": 0}],
            }],
            "previous_xis": [],
            "team_style": {"radar": []},
            "goals_analysis": {},
            "player_rankings": {},
        })


def _no_impect(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("Opposition Hub click path must not call Impect")

    from app import main as impect_main

    monkeypatch.setattr(impect_main, "_impect_get", boom)


def test_opposition_hub_is_a_reports_tool():
    row = next(app for app in APPS if app["id"] == "opposition-hub")
    assert row["href"] == "/opposition-hub"
    assert row["group"] == "reports"
    assert row["router"] == "opposition_hub"
    assert "/api/opposition-hub" in row["api_prefixes"]
    assert "Opposition Hub" in required_sidebar_titles()


def test_fixtures_record_and_table():
    base = {"matches": MATCHES, "names": {str(OPP): "Grimsby Town"}}
    fixtures = oh.team_fixtures(base, OPP)
    assert [f["result"] for f in fixtures] == ["W", "D", "L"]
    assert fixtures[1]["home"] is False and fixtures[1]["score"] == "1-1"
    rec = oh.record(fixtures)
    assert (rec["w"], rec["d"], rec["l"], rec["pts"], rec["gf"], rec["ga"]) == (1, 1, 1, 4, 3, 3)
    table = oh.league_table(base)
    assert table[0]["squadId"] == VALE and table[0]["pts"] == 7
    assert oh.select_window(fixtures, "last6") == fixtures


def test_metric_row_ranks_low_is_better():
    row = oh.metric_row("xgAgainst", "xG against", {1: 1.2, 2: 0.8, 3: 1.5}, 2, higher=False)
    assert row["rank"] == 1 and row["of"] == 3


def test_report_reads_lake_only(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    _no_impect(monkeypatch)
    report = oh.read_report("26/27", OPP, "season")
    assert report["ready"] is True
    assert report["club"]["name"] == "Grimsby Town"
    assert report["games"] == 3
    assert report["record"]["pts"] == 4
    assert report["fixture"]["matchId"] == 99 and report["fixture"]["valeHome"] is True
    assert [row["matchId"] for row in report["h2h"]] == [5]
    metrics = report["metrics"]
    assert metrics["threatFor"]["rank"] == 1
    assert metrics["famFor:cross"]["rank"] == 1
    assert metrics["aerialPct"]["rank"] == 4
    assert report["threat"]["games"] == 3 and report["threat"]["players"][0]["name"] == "Andy Cook"
    assert report["xg"]["trend"] and len(report["interventions"]["trend"]) == 3
    assert any(row["side"] == "battle" for row in report["matchup"])
    strengths = {item["metric"] for item in report["plan"]["strengths"]}
    weaknesses = {item["metric"] for item in report["plan"]["weaknesses"]}
    assert "famFor:cross" in strengths
    assert "aerialPct" in weaknesses
    squad = report["squad"]
    assert squad["ready"] is True and squad["manager"] == "David Artell"
    cook = squad["players"][0]
    assert cook["log"][-1]["min"] == 90 and cook["minutesShare"] == 100
    assert "Ever-present" in cook["tags"]
    assert cook["threat"] is not None


def test_report_without_squad_offers_build(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, with_squad=False)
    _no_impect(monkeypatch)
    report = oh.build_report("26/27", OPP, "last6")
    assert report["ready"] is True
    assert report["squad"]["ready"] is False
    assert report["window"] == "last6"


def test_meta_lists_teams_and_next_opponent(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    meta = oh.read_meta()
    assert meta["ready"] is True
    assert VALE not in {team["id"] for team in meta["teams"]}
    assert meta["next"]["squadId"] == OPP and meta["next"]["matchId"] == 99


def test_meta_fixture_strip_has_badges_and_vale_results(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    strip = oh.read_meta()["fixtures"]
    assert [row["matchId"] for row in strip] == [5, 99]
    played, upcoming = strip
    assert played["badge"] and played["played"] is True
    vale_row = next(row for row in oh.team_fixtures(oh.season_base("26/27"), VALE) if row["matchId"] == 5)
    assert played["score"] == vale_row["score"] and played["result"] == vale_row["result"]
    assert upcoming["played"] is False and upcoming["score"] is None and upcoming["home"] is True


def test_empty_lake_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    oh.clear_memo()
    assert oh.read_meta()["ready"] is False
    assert oh.build_report("26/27", OPP)["ready"] is False
