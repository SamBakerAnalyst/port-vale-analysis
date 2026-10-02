from app.apps_manifest import APPS, role_path_prefixes
from app.interventions import (
    POINT_KINDS,
    battle_table,
    build_league_table,
    build_report,
    encode_points,
    headline_stats,
    merge_squads,
    read_report,
    summarize_match,
    unit_of,
    zone_of,
)

VALE = 10
OPP = 20


def _event(event_id, squad, player, position, x, y, action_type="INTERCEPTION", **extra):
    row = {
        "id": event_id,
        "squadId": squad,
        "actionType": action_type,
        "action": action_type,
        "player": {"id": player, "position": position},
        "start": {"adjCoordinates": {"x": x, "y": y}},
        "gameTime": {"gameTimeInSec": 600},
        "periodId": 1,
    }
    row.update(extra)
    return row


def _kpi(event_id, kpi_id, value, player, position=""):
    return {"eventId": event_id, "kpiId": kpi_id, "value": value, "playerId": player, "position": position}


def _match():
    events = [
        _event(1, VALE, 5, "CENTRAL_DEFENDER", -40, 0),
        _event(2, VALE, 6, "CENTER_FORWARD", 30, -25, "LOOSE_BALL_REGAIN"),
        _event(3, VALE, 5, "CENTRAL_DEFENDER", -10, 12, "GROUND_DUEL",
               duel={"duelType": "GROUND_DUEL", "playerId": 7}),
        _event(4, OPP, 7, "LEFT_WINGER", 20, 5, "PASS"),
        _event(5, OPP, 7, "LEFT_WINGER", 35, 0, "LOOSE_BALL_REGAIN"),
    ]
    kpis = [
        _kpi(1, 23, 4.0, 5), _kpi(1, 24, 1.0, 5),
        _kpi(2, 23, 1.0, 6), _kpi(2, 24, 6.0, 6), _kpi(2, 25, 2.0, 6), _kpi(2, 1409, 0.03, 6),
        _kpi(3, 23, 2.0, 5), _kpi(3, 24, 2.0, 5),
        _kpi(3, 94, 1, 5, "CENTRAL_DEFENDER"), _kpi(3, 95, 1, 7, "LEFT_WINGER"),
        _kpi(5, 23, 3.0, 7), _kpi(5, 24, 0.5, 7),
        _kpi(4, 82, 0.5, 7),
    ]
    summary = summarize_match(events, kpis)
    summary["matchId"] = 99
    return summary


def test_interventions_is_an_analysis_tool():
    app = next(row for row in APPS if row["id"] == "interventions")
    assert app["group"] == "analysis"
    assert app["router"] == "interventions"
    assert "/api/interventions" in role_path_prefixes("analysis")


def test_zones_and_units():
    assert zone_of(-40, 0) == "D-C"
    assert zone_of(30, -25) == "F-R"
    assert zone_of(0, 15) == "M-LH"
    assert unit_of("LEFT_WINGBACK_DEFENDER") == "DEF"
    assert unit_of("DEFENSE_MIDFIELD") == "MID"
    assert unit_of("RIGHT_WINGER") == "ATT"
    assert unit_of("GOALKEEPER") == "GK"


def test_ball_wins_sum_event_kpis_by_zone_unit_and_player():
    vale = _match()["squads"][str(VALE)]
    assert vale["bw"] == 3
    assert vale["oi"] == 9.0
    assert vale["di"] == 7.0
    assert vale["bwd"] == 2.0
    assert vale["high"] == 1 and vale["deep"] == 1 and vale["mid"] == 1
    assert vale["zones"]["F-R"]["bwd"] == 2.0
    assert vale["units"]["DEF"]["bw"] == 2
    assert vale["players"]["6"]["oi"] == 6.0
    assert vale["types"]["GROUND_DUEL"] == 1


def test_ball_win_count_kpi_counts_regains_without_intervention_values():
    events = [_event(1, VALE, 5, "CENTRAL_DEFENDER", -40, 0, "LOOSE_BALL_REGAIN"), _event(2, OPP, 7, "LEFT_WINGER", 0, 0, "PASS")]
    vale = summarize_match(events, [_kpi(1, 27, 1.0, 5)])["squads"][str(VALE)]
    assert vale["bw"] == 1
    assert vale["oi"] == 0.0


def test_second_half_clock_starts_at_ten_thousand_seconds():
    from app.interventions import _period_bucket

    assert _period_bucket({"periodId": 1, "gameTime": {"gameTimeInSec": 2884}}) == "30-45"
    assert _period_bucket({"periodId": 2, "gameTime": {"gameTimeInSec": 10000}}) == "45-60"
    assert _period_bucket({"periodId": 2, "gameTime": {"gameTimeInSec": 11000}}) == "60-75"
    assert _period_bucket({"periodId": 2, "gameTime": {"gameTimeInSec": 13544}}) == "75-90"


def test_duel_loser_is_credited_to_the_other_side_with_flipped_location():
    summary = _match()
    vale = summary["squads"][str(VALE)]
    opp = summary["squads"][str(OPP)]
    assert vale["gw"] == 1 and vale["gl"] == 0
    assert opp["gl"] == 1
    lost = next(p for p in summary["points"] if p["k"] == "gl")
    assert lost["s"] == OPP and lost["x"] == 10 and lost["y"] == -12
    assert opp["zones"]["M-RH"]["gl"] == 1


def test_headline_and_merge_per_game():
    summary = _match()
    merged = merge_squads([summary["squads"][str(VALE)], summary["squads"][str(VALE)]])
    stats = headline_stats(merged, 2)
    assert stats["bw"] == 3.0
    assert stats["oi"] == 9.0
    assert stats["duelPct"] == 100.0
    assert merged["games"]["5"] == 2


def test_battles_compare_sides_and_rank_by_points_gap():
    obs = [
        {"stats": {"bwd": 3, "gw": 5, "gl": 1}, "opp": {"bwd": 1, "gw": 1, "gl": 5}, "pts": 3},
        {"stats": {"bwd": 1, "gw": 1, "gl": 5}, "opp": {"bwd": 3, "gw": 5, "gl": 1}, "pts": 0},
        {"stats": {"bwd": 2, "gw": 2, "gl": 2}, "opp": {"bwd": 1, "gw": 2, "gl": 2}, "pts": 1},
    ]
    rows = {row["id"]: row for row in battle_table(obs)}
    assert rows["bwd"]["won"]["games"] == 2
    assert rows["bwd"]["won"]["ppg"] == 2.0
    assert rows["bwd"]["lost"]["ppg"] == 0.0
    assert rows["groundPct"]["level"] == 1
    assert rows["groundPct"]["ppgGap"] == 3.0


def test_league_table_ranks_defensive_interventions_lower_is_better():
    table = build_league_table(
        {VALE: {23: 180, 24: 190, 25: 6, 94: 30, 95: 30, 96: 20, 97: 25}, OPP: {23: 220, 24: 170, 25: 9, 94: 32, 95: 28, 96: 22, 97: 20}},
        {VALE: 7, OPP: 7},
        {VALE: "Port Vale", OPP: "Rivals"},
        VALE,
    )
    vale = table["focus"]
    assert vale["ranks"]["di"] == 1
    assert vale["ranks"]["bwd"] == 2
    assert vale["duelPct"] == 47.6


def test_points_encode_compactly_and_drop_opponent_duels():
    summary = _match()
    points = encode_points([summary], {99: OPP}, {99: 0})
    assert all(len(row) == 10 for row in points)
    assert not any(row[0] == 1 and POINT_KINDS[row[1]] != "bw" for row in points)
    assert sum(1 for row in points if row[0] == 0 and POINT_KINDS[row[1]] == "bw") == 3


def test_build_report_from_lake(monkeypatch):
    summary = _match()
    monkeypatch.setattr("app.interventions._load_summaries", lambda ids, lake_only=False: {99: summary})
    base = {
        "season": "26/27", "valeId": VALE, "players": {5: "Connor Hall", 6: "Jayden Stockley"},
        "fixtures": [{"matchId": 99, "opponent": "Rivals", "opponentId": OPP, "home": True, "score": "2-0", "date": "2026-09-01"}],
        "table": {}, "evidence": {"stats": []},
    }
    report = build_report(base, "season", lake_only=True)
    assert report["us"]["bw"] == 3.0
    assert report["them"]["bw"] == 1.0
    assert report["trend"][0]["result"] == "W"
    assert report["players"][0]["name"] == "Connor Hall"
    assert report["insights"]


def test_click_path_is_empty_without_lake(monkeypatch):
    monkeypatch.setattr("app.interventions._cache_read", lambda kind, key: None)
    payload = read_report("26/27", "season")
    assert payload["ready"] is False
