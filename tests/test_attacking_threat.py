from app.apps_manifest import APPS, LIVE_ESSENTIAL_IDS
from app.attacking_threat import (
    action_family,
    action_label,
    build_league_table,
    league_slice_ranks,
    merge_summaries,
    read_attacking_threat_report,
    summarize_match,
    threat_by_event,
)


def _event(**overrides):
    row = {
        "id": 1,
        "squadId": 10,
        "action": "LOW_PASS",
        "actionType": "PASS",
        "phase": "IN_POSSESSION",
        "currentAttackingSquadId": 10,
        "player": {"id": 5, "commonname": "Ben Garrity"},
        "start": {"packingZone": "CMC", "adjCoordinates": {"x": 0, "y": 0}},
        "end": {"packingZone": "AMC", "adjCoordinates": {"x": 16, "y": 2}},
    }
    row.update(overrides)
    return row


def test_attacking_threat_is_an_analysis_tool():
    app = next(row for row in APPS if row["id"] == "attacking-threat")
    assert app["group"] == "analysis"
    assert app["title"] == "Attacking Threat"
    assert app["router"] == "attacking_threat"
    assert "attacking-threat" in LIVE_ESSENTIAL_IDS


def test_negative_threat_and_other_kpis_are_ignored():
    totals = threat_by_event([
        {"eventId": 1, "kpiId": 1404, "value": 0.2},
        {"eventId": 1, "kpiId": 1404, "value": -0.5},
        {"eventId": 1, "kpiId": 82, "value": 0.9},
        {"eventId": 2, "kpiId": 1405, "value": 0.05},
    ])
    assert totals == {1: 0.2, 2: 0.05}


def test_actions_phases_zones_and_pass_map():
    summary = summarize_match([
        _event(id=1, action="LOW_CROSS", start={"packingZone": "WL", "adjCoordinates": {"x": 22, "y": 24}}, end={"packingZone": "IBC", "adjCoordinates": {"x": 42, "y": 1}}),
        _event(id=2, action="LOW_PASS", player={"id": 6, "commonname": "George Byers"}),
        _event(id=3, action="LOW_PASS", phase="IN_POSSESSION", currentAttackingSquadId=99, player={"id": 7, "commonname": "Connor Hall"}),
        _event(id=4, action="CLOSE_RANGE_SHOT", actionType="SHOT", phase="SET_PIECE", end={}, start={"packingZone": "AMC", "adjCoordinates": {"x": 36, "y": 4}}),
    ], [
        {"eventId": 1, "kpiId": 1404, "value": 0.42},
        {"eventId": 2, "kpiId": 1404, "value": 0.11},
        {"eventId": 3, "kpiId": 1404, "value": 0.08},
        {"eventId": 4, "kpiId": 1408, "value": 0.2},
    ])
    vale = summary["squads"]["10"]
    assert vale["actions"]["LOW_CROSS"] == 0.42
    assert vale["actions"]["LOW_PASS"] == 0.19
    assert vale["phases"]["IN_POSSESSION"] == 0.53
    assert "ATTACKING_TRANSITION" not in vale["phases"]
    assert vale["phases"]["OUT_OF_POSSESSION"] == 0.08
    assert vale["phases"]["SET_PIECE"] == 0.2
    assert vale["zonesStart"]["WL"] == 0.42
    assert vale["zonesEnd"]["IB"] == 0.42
    assert vale["zonesStart"]["CM"] == 0.19
    assert action_label("LOW_CROSS") == "Low cross"
    assert action_family("LOW_CROSS") == "cross"
    assert action_family("LOW_PASS") == "pass"
    cross = next(row for row in vale["passes"] if row["action"] == "LOW_CROSS")
    assert cross["startZone"] == "WL" and cross["endZone"] == "IB"
    shot = next(row for row in vale["passes"] if row["action"] == "CLOSE_RANGE_SHOT")
    assert shot["x2"] == 52.5 and shot["family"] == "shot"
    assert vale["players"]["5"]["name"] == "Ben Garrity"


def test_merge_and_league_ranks():
    left = summarize_match([_event(id=1, action="LOW_CROSS")], [{"eventId": 1, "kpiId": 1404, "value": 0.4}])["squads"]["10"]
    right = summarize_match([_event(id=2, action="HIGH_CROSS", squadId=11, currentAttackingSquadId=11)], [{"eventId": 2, "kpiId": 1404, "value": 0.1}])["squads"]["11"]
    merged = merge_summaries([left, left], keep_passes=True)
    assert merged["actions"]["LOW_CROSS"] == 0.8
    assert len(merged["passes"]) == 2
    table = build_league_table(
        {10: {1633: 1.4, 1404: 0.9, 1405: 0.1, 1408: 0.2, 1406: 0.1, 1409: 0.05}, 11: {1633: 2.1, 1404: 1.2, 1405: 0.2, 1408: 0.3, 1406: 0.2, 1409: 0.1}},
        {10: 8, 11: 8, 12: 0},
        {10: "Port Vale", 11: "Bromley"},
        10,
    )
    assert table["focus"]["rank"] == 2
    assert table["rows"][0]["club"] == "Bromley"
    assert table["components"][0]["rank"] == 2
    ranks = league_slice_ranks({10: {"LOW_CROSS": 0.8, "HIGH_CROSS": 0.1}, 11: right["actions"]}, {10: 2, 11: 1}, 10)
    assert ranks["LOW_CROSS"]["rank"] == 1
    assert ranks["HIGH_CROSS"]["of"] == 2


def test_opening_the_page_reads_the_lake_and_does_not_call_impect(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("Impect was called on the click path")

    monkeypatch.setattr("app.attacking_threat._resolve_season", boom)
    monkeypatch.setattr("app.attacking_threat._cache_read", lambda _kind, _key: None)
    monkeypatch.setattr("app.analysis_cache.all_json", lambda _kind: [])
    report = read_attacking_threat_report("26/27", "season", None)
    assert report["ready"] is False
    assert report["fromLake"] is True
    assert "data lake" in report["message"]


def test_opening_the_page_returns_the_saved_pack(monkeypatch):
    saved = {"season": "26/27", "scope": "season", "table": [{"club": "Port Vale"}], "matchCount": 8}

    def read(kind, _key):
        return saved if kind == "at-report" else None

    monkeypatch.setattr("app.attacking_threat._cache_read", read)
    report = read_attacking_threat_report("26/27", "season", None)
    assert report["ready"] is True
    assert report["fromLake"] is True
    assert report["table"][0]["club"] == "Port Vale"


def _ev(event_id, index, seq, squad, action_type, action, player, *, att=None, receiver=None, result="SUCCESS", x1=0.0, x2=10.0):
    event = {
        "id": event_id, "index": index, "periodId": 1, "sequenceIndex": seq, "squadId": squad,
        "currentAttackingSquadId": att or squad, "actionType": action_type, "action": action,
        "player": {"id": player}, "phase": "IN_POSSESSION", "result": result,
        "gameTime": {"gameTimeInSec": 60.0 * index},
        "start": {"adjCoordinates": {"x": x1, "y": 0.0}}, "end": {"adjCoordinates": {"x": x2, "y": 5.0}},
    }
    if receiver:
        event["pass"] = {"receiver": {"playerId": receiver, "type": "TEAM"}}
    return event


def test_threat_chains_links_and_insights():
    from app.attacking_threat import action_family, action_label, FAMILY_COLORS
    from app.attacking_threat_chains import (
        analyse_chains, analyse_links, build_insights, chain_record, compact_events, possessions,
    )

    vale, opp = 1, 2
    events = [
        _ev(1, 1, 5, vale, "LOOSE_BALL_REGAIN", "LOOSE_BALL_REGAIN", 10, x1=25.0),
        _ev(2, 2, 5, vale, "PASS", "LOW_PASS", 10, receiver=11, x1=25.0, x2=35.0),
        {**_ev(3, 3, 5, vale, "RECEPTION", "RECEPTION", 11)},
        _ev(4, 4, 5, vale, "PASS", "LOW_CROSS", 11, receiver=12, x1=35.0, x2=48.0),
        _ev(5, 5, 5, vale, "SHOT", "HEADER", 12, result="SUCCESS", x1=48.0),
        _ev(6, 6, 6, opp, "PASS", "LOW_PASS", 20, receiver=21),
        _ev(7, 7, 7, vale, "CORNER", "CORNER", 13, receiver=12, x1=50.0),
        _ev(8, 8, 7, vale, "SHOT", "HEADER", 12, result="FAIL", x1=47.0),
    ]
    kpis = [
        {"eventId": 2, "kpiId": 1404, "value": 0.10},
        {"eventId": 4, "kpiId": 1404, "value": 0.30},
        {"eventId": 5, "kpiId": 1408, "value": 0.20},
        {"eventId": 5, "kpiId": 82, "value": 0.45},
        {"eventId": 6, "kpiId": 1404, "value": 0.50},
        {"eventId": 7, "kpiId": 1406, "value": 0.05},
        {"eventId": 8, "kpiId": 1408, "value": 0.02},
        {"eventId": 4, "kpiId": 1404, "value": -0.4},
    ]
    pack = compact_events(events, kpis)
    assert all(row["at"] != "RECEPTION" for row in pack)
    found = possessions(pack, vale, 99)
    assert len(found) == 2
    chains = [chain_record(item, action_label, action_family) for item in found]
    goal_chain = next(chain for chain in chains if chain["goal"])
    assert goal_chain["threat"] == 0.6
    assert goal_chain["xg"] == 0.45
    assert goal_chain["origin"] == "regain_high"
    assert goal_chain["patternKey"] == "Low pass → Low cross → Header"
    corner = next(chain for chain in chains if not chain["goal"])
    assert corner["origin"] == "set_piece"

    names = {10: "Ten", 11: "Eleven", 12: "Twelve", 13: "Thirteen"}
    view = analyse_chains(chains, 1, names, {99: {"opponent": "Bromley", "home": True}},
                          labeler=action_label, familier=action_family, colors=FAMILY_COLORS)
    assert view["summary"]["goals"] == 1
    assert view["patterns"][0]["key"] == "Low pass → Low cross → Header"
    assert view["top"][0]["opponent"] == "Bromley"
    assert view["top"][0]["steps"][-1]["goal"] is True

    links = analyse_links(found, 1, names, labeler=action_label)
    top = links["pairs"][0]
    assert (top["fromName"], top["toName"]) == ("Eleven", "Twelve")
    assert top["passThreat"] == 0.3 and top["followThreat"] == 0.2
    assert (top["shots"], top["goals"]) == (1, 1)
    assert top["lines"][0]["shot"] is True and top["lines"][0]["x2"] == 48.0
    assert "matrix" in links["network"]
    assert links["trios"][0]["names"] == ["Ten", "Eleven", "Twelve"]
    assert links["trios"][0]["threat"] == 0.6

    insights = build_insights({"detail": {"actions": []}, "chains": view, "links": links})
    assert any(item["title"] == "Strongest link" for item in insights)


def test_minutes_and_links_without_receiver_label():
    from app.attacking_threat_chains import analyse_links, match_minute

    assert match_minute(17.6) == 1
    assert match_minute(10000.0) == 46
    assert match_minute(11980.0) == 79
    steps = [
        {"i": 1, "pl": 7, "at": "PASS", "a": "LOW_PASS", "res": "SUCCESS", "v": 0.1, "x1": 0, "y1": 0},
        {"i": 2, "pl": 9, "at": "SHOT", "a": "HEADER", "res": "FAIL", "v": 0.2, "x1": 40, "y1": 0},
    ]
    links = analyse_links([{"steps": steps}], 1, {7: "Seven", 9: "Nine"})
    assert links["pairs"][0]["toName"] == "Nine"
    assert links["pairs"][0]["total"] == 0.3


def test_league_squad_table_counts_crosses_per_game():
    from app.attacking_threat import league_squad_table

    summaries = {
        1: {"squads": {"10": {"total": 1.0, "actions": {"LOW_CROSS": 0.3, "HIGH_CROSS": 0.1, "LOW_PASS": 0.6}, "actionCounts": {"LOW_CROSS": 3, "HIGH_CROSS": 1, "LOW_PASS": 9}}}},
        2: {"squads": {"10": {"total": 0.5, "actions": {"LOW_CROSS": 0.2, "DRIBBLE": 0.3}, "actionCounts": {"LOW_CROSS": 2, "DRIBBLE": 4}}}},
    }
    row = league_squad_table(summaries)["10"]
    assert row["games"] == 2
    assert row["cross"] == 0.3
    assert row["crossCount"] == 3.0
    assert row["pass"] == 0.3


def test_match_trend_created_vs_conceded():
    from app.attacking_threat import match_trend

    selected = [{"matchId": 1, "opponent": "York City", "opponentId": 9, "home": False, "score": "2-1"}]
    loaded = {1: {"squads": {"882": {"total": 1.5, "actions": {"HEADER": 0.9, "LOW_PASS": 0.6}}, "9": {"total": 2.0}}}}
    row = match_trend(selected, loaded, 882)[0]
    assert row["created"] == 1.5 and row["conceded"] == 2.0
    assert (row["goalsFor"], row["goalsAgainst"]) == (1, 2)
    assert row["topAction"] == "Header"
