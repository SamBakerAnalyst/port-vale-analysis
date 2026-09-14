from app.xg_chance_analysis import (
    apply_penalty_filter,
    _is_penalty_event,
    _is_penalty_shot,
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
