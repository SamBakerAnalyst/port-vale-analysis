from app.xg_chance_analysis import (
    apply_penalty_filter,
    build_xg_chance_league_table,
    league_rows_from_tallies,
    tally_league_matches,
    _is_penalty_event,
    _is_penalty_shot,
    _league_shots_for_match,
    _looks_like_penalty_xg,
)


def _shot(**overrides):
    row = {
        "eventId": 1,
        "matchId": 10,
        "team": "vale",
        "playerName": "George Byers",
        "minute": 40,
        "second": 12,
        "xg": 0.779,
        "chanceRating": {"id": "excellent", "label": "Excellent", "color": "#166534"},
        "inBox": True,
        "inBoxLabel": "IN",
        "onTarget": True,
        "outcome": "goal",
        "outcomeLabel": "GOAL",
        "gameState": "drawing",
        "gameStateLabel": "DRAWING",
        "half": "first",
        "halfLabel": "1ST",
        "manpower": "11 v 11",
        "seconds": 2412,
        "action": "OPEN_PLAY_SHOT",
        "isPenalty": False,
    }
    row.update(overrides)
    return row


def test_penalty_event_from_action():
    assert _is_penalty_event({"action": "PENALTY_KICK", "actionType": "SHOT"}) is True
    assert _is_penalty_event({"action": "PENALTY", "actionType": "SHOT"}) is True
    assert _is_penalty_event({"action": "MID_RANGE_SHOT", "actionType": "SHOT"}) is False
    assert _is_penalty_event({"setPiece": {"category": "PENALTY"}}) is True


def test_cached_shot_heuristic_flags_typical_penalty_xg():
    assert _looks_like_penalty_xg({"xg": 0.779, "inBox": True}) is True
    assert _looks_like_penalty_xg({"xg": 0.198, "inBox": True}) is False
    assert _looks_like_penalty_xg({"xg": 0.779, "inBox": False}) is False
    assert _is_penalty_shot({"xg": 0.779, "inBox": True}) is True
    assert _is_penalty_shot({"xg": 0.779, "inBox": True, "isPenalty": False, "action": "OPEN_PLAY"}) is False


def test_remove_penalties_drops_penalty_xg_and_keeps_score():
    report = {
        "scope": "match",
        "matches": [
            {
                "matchId": 10,
                "valeGoals": 1,
                "oppGoals": 0,
                "valeXg": 1.609,
                "oppXg": 0.462,
                "valeShots": 10,
                "oppShots": 8,
            }
        ],
        "shots": [
            _shot(isPenalty=True, action="PENALTY_KICK"),
            _shot(
                eventId=2,
                playerName="Ben Garrity",
                xg=0.198,
                chanceRating={"id": "very_good", "label": "Very Good", "color": "#22c55e"},
                outcome="miss",
                outcomeLabel="MISS",
                onTarget=False,
                isPenalty=False,
            ),
            _shot(
                eventId=3,
                team="opp",
                playerName="Reece Cole",
                xg=0.109,
                chanceRating={"id": "ok", "label": "OK", "color": "#facc15"},
                outcome="miss",
                isPenalty=False,
            ),
        ],
        "dismissals": [],
    }

    kept = apply_penalty_filter(report, exclude_penalties=False)
    assert kept["penaltySummary"]["count"] == 1
    assert kept["penaltySummary"]["valeXg"] == 0.779
    assert kept["matches"][0]["valeGoals"] == 1
    assert kept["matches"][0]["valeXg"] == 0.977
    assert kept["xgCreated"]["totals"]["cumulativeXg"] == 0.977
    assert kept["heroStats"]["bestChance"]["isPenalty"] is True
    assert kept["excludePenalties"] is False

    stripped = apply_penalty_filter(report, exclude_penalties=True)
    assert stripped["excludePenalties"] is True
    assert stripped["penaltySummary"]["excluded"] is True
    assert stripped["penaltySummary"]["count"] == 1
    assert stripped["shotCount"] == 2
    assert stripped["matches"][0]["valeGoals"] == 1
    assert stripped["matches"][0]["valeXg"] == 0.198
    assert stripped["xgCreated"]["totals"]["cumulativeXg"] == 0.198
    assert all(not shot.get("isPenalty") for shot in stripped["shots"])
    assert stripped["playerBreakdown"]["vale"][0]["playerName"] == "Ben Garrity"
    assert stripped["heroStats"]["bestChance"]["isPenalty"] is False


def test_league_rows_rank_excellent_then_very_good_then_ok():
    tallies = tally_league_matches(
        [
            {
                "homeSquadId": 1,
                "awaySquadId": 2,
                "shots": [
                    {"squadId": 1, "ratingId": "excellent", "isPenalty": False},
                    {"squadId": 1, "ratingId": "ok", "isPenalty": False},
                    {"squadId": 2, "ratingId": "excellent", "isPenalty": False},
                    {"squadId": 2, "ratingId": "excellent", "isPenalty": False},
                    {"squadId": 2, "ratingId": "poor", "isPenalty": False},
                ],
            },
            {
                "homeSquadId": 2,
                "awaySquadId": 3,
                "shots": [
                    {"squadId": 3, "ratingId": "excellent", "isPenalty": False},
                    {"squadId": 3, "ratingId": "very_good", "isPenalty": False},
                    {"squadId": 2, "ratingId": "very_good", "isPenalty": False},
                ],
            },
        ]
    )
    rows = league_rows_from_tallies(
        tallies,
        {1: "Accrington", 2: "Port Vale", 3: "Walsall"},
    )
    assert [row["teamName"] for row in rows] == ["Port Vale", "Walsall", "Accrington"]
    vale = rows[0]
    assert vale["isPortVale"] is True
    assert vale["rank"] == 1
    assert vale["matches"] == 2
    assert vale["bands"]["excellent"]["count"] == 2
    assert vale["bands"]["excellent"]["share"] == 50.0
    assert vale["bands"]["excellent"]["perMatch"] == 1.0
    assert vale["bands"]["very_good"]["count"] == 1
    assert vale["shots"] == 4
    assert vale["qualityCount"] == 3
    walsall = rows[1]
    assert walsall["bands"]["excellent"]["count"] == 1
    assert walsall["bands"]["very_good"]["count"] == 1
    accrington = rows[2]
    assert accrington["bands"]["excellent"]["count"] == 1
    assert accrington["bands"]["very_good"]["count"] == 0
    assert accrington["bands"]["ok"]["count"] == 1


def test_league_rows_drop_penalties_from_band_counts():
    tallies = tally_league_matches(
        [
            {
                "homeSquadId": 1,
                "awaySquadId": 2,
                "shots": [
                    {"squadId": 1, "ratingId": "excellent", "isPenalty": True},
                    {"squadId": 1, "ratingId": "ok", "isPenalty": False},
                    {"squadId": 2, "ratingId": "very_good", "isPenalty": False},
                ],
            }
        ]
    )
    rows = league_rows_from_tallies(tallies, {1: "Port Vale", 2: "Walsall"}, exclude_penalties=True)
    vale = next(row for row in rows if row["teamName"] == "Port Vale")
    assert vale["bands"]["excellent"]["count"] == 0
    assert vale["bands"]["ok"]["count"] == 1
    assert vale["shots"] == 1
    assert vale["bands"]["ok"]["share"] == 100.0
    assert vale["qualityCount"] == 1


def test_league_match_shots_use_page_bands(monkeypatch):
    monkeypatch.setattr(
        "app.xg_chance_analysis._fetch_match_events",
        lambda mid, refresh=False: [
            {"id": 1, "actionType": "SHOT", "action": "OPEN_PLAY_SHOT", "squadId": 10, "start": {}},
            {"id": 2, "actionType": "SHOT", "action": "OPEN_PLAY_SHOT", "squadId": 10, "start": {}},
            {
                "id": 3,
                "actionType": "SHOT",
                "action": "PENALTY_KICK",
                "squadId": 20,
                "start": {"pitchPosition": "OPPONENT_BOX"},
            },
        ],
    )
    monkeypatch.setattr(
        "app.xg_chance_analysis._shot_xg_map",
        lambda mid, refresh=False: {1: 0.35, 2: 0.19, 3: 0.09},
    )
    shots = _league_shots_for_match(1)
    assert [shot["ratingId"] for shot in shots] == ["excellent", "very_good", "ok"]
    assert shots[2]["isPenalty"] is True


def test_build_league_table_uses_season_competition(monkeypatch):
    monkeypatch.setattr(
        "app.xg_chance_analysis._resolve_port_vale_iteration",
        lambda season=None: {"id": 9, "season": "26/27", "competition_name": "League Two"},
    )
    monkeypatch.setattr(
        "app.xg_chance_analysis._iteration_matches_by_id",
        lambda iid: {
            1: {
                "id": 1,
                "homeSquadId": 10,
                "awaySquadId": 20,
                "goals": {"home": {"fullTime": 1}, "away": {"fullTime": 0}},
            },
            2: {"id": 2, "homeSquadId": 10, "awaySquadId": 30},
        },
    )
    monkeypatch.setattr(
        "app.xg_chance_analysis._squads_map",
        lambda iid: {
            10: {"name": "Port Vale"},
            20: {"name": "Walsall"},
            30: {"name": "Not played"},
        },
    )

    def shots(match_id, *, refresh=False):
        assert match_id == 1
        return [
            {"squadId": 10, "ratingId": "excellent", "isPenalty": False},
            {"squadId": 20, "ratingId": "ok", "isPenalty": False},
        ]

    monkeypatch.setattr("app.xg_chance_analysis._league_shots_for_match", shots)
    monkeypatch.setattr("app.analysis_cache.read_json", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.analysis_cache.write_json", lambda *args, **kwargs: None)

    table = build_xg_chance_league_table(season="26/27", refresh=True)
    assert table["season"] == "26/27"
    assert table["competition"] == "League Two"
    assert table["windowLabel"] == "League Two 26/27 · all completed matches"
    assert table["sort"]["label"] == "Most Excellent, then Very Good, then OK"
    assert [band["label"] for band in table["bands"]] == ["Excellent", "Very Good", "OK"]
    assert table["bands"][0]["min"] == 0.35
    assert table["bands"][1]["min"] == 0.19
    assert table["bands"][2]["min"] == 0.09
    assert table["matchCount"] == 1
    assert [row["teamName"] for row in table["rows"]] == ["Port Vale", "Walsall"]
    assert table["rows"][0]["bands"]["excellent"]["count"] == 1
    assert table["rows"][1]["bands"]["ok"]["count"] == 1
    assert "Not played" not in [row["teamName"] for row in table["rows"]]
