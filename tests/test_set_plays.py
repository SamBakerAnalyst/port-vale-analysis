from app.apps_manifest import APPS, LIVE_ESSENTIAL_IDS
from app.set_plays import build_plan, build_report, read_report
from app.set_plays_engine import (
    extract_match,
    league_table,
    points_per_goal,
    summarize,
    swing_of,
    target_zone,
)

VALE = 10
OPP = 20


def _ev(idx, squad, action_type, *, action=None, t=0.0, start=None, end=None, sp=None, main=False,
        receiver=None, body=None, result=None, player=1, duel=None, period=1):
    row = {
        "id": 1000 + idx,
        "index": idx,
        "periodId": period,
        "gameTime": {"gameTimeInSec": t},
        "squadId": squad,
        "player": {"id": player},
        "actionType": action_type,
        "action": action or action_type,
        "result": result,
        "bodyPartExtended": body,
    }
    if start:
        row["start"] = {"adjCoordinates": {"x": start[0], "y": start[1]}}
    if end:
        row["end"] = {"adjCoordinates": {"x": end[0], "y": end[1]}}
    if sp:
        row["setPiece"] = {"id": sp, "mainEvent": main}
    if receiver:
        row["pass"] = {"receiver": receiver}
    if duel:
        row["duel"] = duel
    return row


def _corner_goal_match():
    events = [
        # Vale right-footed corner from the right, headed in at the far post.
        _ev(1, VALE, "CORNER", t=100, start=(52.5, -34), end=(48.0, 5.0), sp=1, main=True, body="FOOT_RIGHT", player=7,
            receiver={"type": "TEAMMATE", "playerId": 9}),
        _ev(2, VALE, "SHOT", action="CLOSE_RANGE_SHOT", t=101, start=(48.0, 5.0), sp=1, body="HEAD", result="SUCCESS",
            player=9, duel={"duelType": "AERIAL_DUEL", "playerId": 55}),
        # Opposition short corner, worked into the box, cleared by Vale; Vale counter shot.
        _ev(3, OPP, "CORNER", t=500, start=(52.5, 34), end=(45.0, 28.0), sp=2, main=True, body="FOOT_LEFT", player=50),
        _ev(4, OPP, "PASS", action="HIGH_CROSS", t=503, start=(45.0, 28.0), end=(46.0, 2.0), sp=2, body="FOOT_LEFT", player=51),
        _ev(5, VALE, "CLEARANCE", t=504, start=(-46.0, -2.0), sp=2, body="HEAD", player=4),
        _ev(6, VALE, "SHOT", action="LONG_RANGE_SHOT", t=520, start=(30.0, 0.0), result="FAIL", player=8),
        # Penalty with no set-piece chain.
        _ev(7, OPP, "SHOT", action="PENALTY_KICK", t=900, start=(41.5, 0.0), result="SUCCESS", player=52),
        # Throw-in deep in our own half is ignored.
        _ev(8, VALE, "THROW_IN", t=1000, start=(-30.0, 34.0), end=(-20.0, 20.0), sp=3, main=True),
    ]
    kpis = [{"eventId": 1002, "kpiId": 82, "value": 0.4}, {"eventId": 1006, "kpiId": 82, "value": 0.05},
            {"eventId": 1007, "kpiId": 82, "value": 0.78}]
    return extract_match(events, kpis, 99)


def test_set_plays_is_an_analysis_tool():
    app = next(row for row in APPS if row["id"] == "set-plays")
    assert app["group"] == "analysis"
    assert app["router"] == "set_plays"
    assert "set-plays" in LIVE_ESSENTIAL_IDS


def test_swing_and_zones():
    assert swing_of("right", "R") == "out"
    assert swing_of("right", "L") == "in"
    assert swing_of("left", "R") == "in"
    assert target_zone(48.0, 5.0, -1) == "far_post"
    assert target_zone(48.0, -5.0, -1) == "near_post"
    assert target_zone(49.0, 0.0, 1) == "goalmouth"
    assert target_zone(30.0, 0.0, 1) == "outside"


def test_extract_corner_goal_short_corner_and_penalty():
    pack = _corner_goal_match()
    records = pack["records"]
    assert [r["type"] for r in records] == ["corner", "corner", "penalty"]
    vale_corner, opp_corner, pen = records
    assert vale_corner["sq"] == VALE and vale_corner["opp"] == OPP
    assert vale_corner["swing"] == "out"
    assert vale_corner["zone"] == "far_post"
    assert vale_corner["fc"]["team"] == "att" and vale_corner["fc"]["loser"] == 55
    assert vale_corner["shots"][0]["goal"] and vale_corner["shots"][0]["head"]
    assert opp_corner["sub"] == "short"
    assert opp_corner["fc"]["team"] == "def" and opp_corner["fc"]["pl"] == 4
    assert opp_corner["counter"]["shots"] == 1
    assert pen["shots"][0]["goal"] and pen["opp"] == VALE


def test_summary_perspective_and_league_table():
    records = _corner_goal_match()["records"]
    vale_against = [r for r in records if r["opp"] == VALE and r["type"] != "penalty"]
    defending = summarize(vale_against, 1, attacking=False)
    assert defending["fcWonPct"] == 100.0
    table = league_table(records, {VALE: 1, OPP: 1}, {VALE: "Port Vale", OPP: "Rivals"}, {VALE: 1, OPP: 1}, VALE)
    vale = next(r for r in table["rows"] if r["focus"])
    assert vale["goalsForTotal"] == 1 and vale["goalsAgainstTotal"] == 0
    assert vale["ranks"]["xgFor"] == 1


def test_points_per_goal_is_bounded():
    assert points_per_goal([]) == 0.75
    results = [(a, b, 2, 0) for a in range(1, 9) for b in range(1, 9) if a < b]
    assert 0.3 <= points_per_goal(results) <= 1.5


def test_plan_needs_enough_events():
    records = _corner_goal_match()["records"]
    assert build_plan(records, {VALE: 1, OPP: 1}, {}, VALE) == []


def test_build_report_from_packs():
    pack = _corner_goal_match()
    base = {
        "season": "26/27", "valeId": VALE, "competition": "League Two",
        "names": {str(VALE): "Port Vale", str(OPP): "Rivals"}, "players": {"9": "Big Header"},
        "matches": [{"matchId": 99, "date": "2026-08-01", "home": VALE, "away": OPP, "hg": 1, "ag": 1}],
    }
    report = build_report(base, {99: pack}, "season")
    assert report["headline"]["goalsFor"] == 1
    assert report["headline"]["goalsAgainst"] == 1
    assert report["headline"]["pensConceded"] == 1
    assert report["attack"]["goals"][0]["scorer"] == "Big Header"
    assert report["matches"][0]["goalsAgainst"] == 1


def test_read_report_never_calls_impect(monkeypatch):
    monkeypatch.setattr("app.set_plays._cache_read", lambda _kind, _key: None)
    report = read_report("26/27", "season", None)
    assert report["ready"] is False
    assert report["fromLake"] is True


def test_partial_event_feed_is_not_saved(monkeypatch):
    import app.set_plays as sp
    import app.set_plays_impect as impect

    saved = []
    monkeypatch.setattr(sp, "read_pack", lambda match_id: None)
    monkeypatch.setattr(sp, "_cache_write", lambda kind, key, payload: saved.append(key))
    monkeypatch.setattr(impect, "fetch_event_kpis", lambda match_id: [{"eventId": 1, "kpiId": 82, "value": 0.1}])

    monkeypatch.setattr(impect, "fetch_events", lambda match_id: [_ev(i, VALE, "PASS") for i in range(50)])
    sp.match_pack(1)
    assert saved == []

    monkeypatch.setattr(impect, "fetch_events", lambda match_id: [_ev(i, VALE, "PASS") for i in range(sp.MIN_COMPLETE_EVENTS)])
    sp.match_pack(2)
    assert saved == ["2"]


def test_attack_targets_only_count_balls_into_the_box():
    from app.set_plays import _attack_targets

    def record(zone, contact):
        return {"type": "free_kick", "zone": zone, "del": 9, "fc": {"team": "att", "pl": contact, "head": True}, "shots": []}

    rows = _attack_targets(
        [record("goalmouth", 5), record("far_post", 5), record("outside", 6), record("outside", 6), record("outside", 6)],
        {},
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[5]["fcWon"] == 2
    assert 6 not in by_id
