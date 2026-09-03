from app.set_piece_pre_match import (
    _against_slide_incomplete,
    _for_slide_incomplete,
    _rank_goal_leaders,
    _rank_takers,
    _rank_xg_leaders,
    _side_payload,
)


def test_rank_takers_and_scorers():
    takers = {
        1: {"player_id": 1, "name": "Alpha", "takes": 7},
        2: {"player_id": 2, "name": "Bravo", "takes": 4},
        3: {"player_id": 3, "name": "Charlie", "takes": 0},
    }
    ranked = _rank_takers(takers, limit=4)
    assert [row["name"] for row in ranked] == ["Alpha", "Bravo"]

    scorers = {
        1: {"player_id": 1, "name": "Alpha", "goals": 2, "xg": 0.4},
        2: {"player_id": 2, "name": "Bravo", "goals": 0, "xg": 1.1},
        3: {"player_id": 3, "name": "Charlie", "goals": 1, "xg": 0.2},
    }
    assert [row["name"] for row in _rank_goal_leaders(scorers)] == ["Alpha", "Charlie"]
    assert [row["name"] for row in _rank_xg_leaders(scorers)] == ["Bravo", "Alpha", "Charlie"]


def test_side_payload_attaches_family_lists():
    empty = {
        "chains": 0.0,
        "successfulDeliveries": 0.0,
        "firstContacts": 0.0,
        "firstContactWon": 0.0,
        "shots": 0.0,
        "goals": 0.0,
        "shotXg": 0.0,
        "intoBox": 0.0,
        "deliverable": 0.0,
    }
    payload = _side_payload(
        empty,
        games=8,
        by_type={},
        corners=empty,
        free_kicks=empty,
        free_kick_by_type={},
        points=[],
        leaders={},
        trim_points=lambda points: points,
        takers_by_family={
            "corners": {9: {"player_id": 9, "name": "Taker", "takes": 3}},
            "freeKicks": {},
        },
        scorers_by_family={
            "corners": {8: {"player_id": 8, "name": "Finisher", "goals": 1, "xg": 0.31}},
            "freeKicks": {},
        },
        contact_by_family={
            "corners": {7: {"player_id": 7, "name": "Target", "contacts": 5, "into_box": 2}},
            "freeKicks": {},
        },
    )
    assert payload["corners"]["takers"][0]["name"] == "Taker"
    assert payload["corners"]["goalLeaders"][0]["name"] == "Finisher"
    assert payload["corners"]["xgLeaders"][0]["name"] == "Finisher"
    assert payload["corners"]["firstContactLeaders"][0]["name"] == "Target"
    assert payload["freeKicks"]["takers"] == []
    assert payload["left"]["label"] == "Left"
    assert payload["right"]["label"] == "Right"
    assert payload["goalPoints"] == []
    assert not _for_slide_incomplete({"set_plays": {"attacking": payload}})
    assert _for_slide_incomplete({"set_plays": {"attacking": {"corners": {}}}})
    assert _against_slide_incomplete({"set_plays": {"defending": {}}})
    assert _against_slide_incomplete({"set_plays": {"defending": {"goalPoints": []}}})
    assert not _against_slide_incomplete(
        {"set_plays": {"defending": {"goalPoints": [], "left": {}}}}
    )
