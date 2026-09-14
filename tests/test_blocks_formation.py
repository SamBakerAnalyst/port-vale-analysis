"""Coach shape: Exeter 5-3-2 with Byers in midfield, Salford stays 5-2-3."""

from __future__ import annotations

from app.blocks_analysis import (
    BYERS_PLAYER_ID,
    LYNCH_PLAYER_ID,
    _coach_formation_from_lineup,
    _retouch_byers_532_stats,
    _unit_baselines_for_formation,
    _unit_for_position,
)


def _xi(*rows: tuple[int, str]) -> list[dict]:
    return [{"playerId": pid, "position": pos} for pid, pos in rows]


EXETER_XI = _xi(
    (111341, "GOALKEEPER"),
    (59106, "CENTRAL_DEFENDER"),
    (69201, "CENTRAL_DEFENDER"),
    (77595, "CENTRAL_DEFENDER"),
    (59430, "RIGHT_WINGBACK_DEFENDER"),
    (80000, "LEFT_WINGBACK_DEFENDER"),
    (24992, "DEFENSE_MIDFIELD"),
    (69194, "DEFENSE_MIDFIELD"),
    (BYERS_PLAYER_ID, "ATTACKING_MIDFIELD"),
    (50215, "ATTACKING_MIDFIELD"),
    (LYNCH_PLAYER_ID, "CENTER_FORWARD"),
)

SALFORD_XI = _xi(
    (111341, "GOALKEEPER"),
    (59106, "CENTRAL_DEFENDER"),
    (69201, "CENTRAL_DEFENDER"),
    (77595, "CENTRAL_DEFENDER"),
    (59430, "RIGHT_WINGBACK_DEFENDER"),
    (80000, "LEFT_WINGBACK_DEFENDER"),
    (24992, "DEFENSE_MIDFIELD"),
    (69194, "DEFENSE_MIDFIELD"),
    (105282, "ATTACKING_MIDFIELD"),
    (1, "ATTACKING_MIDFIELD"),
    (LYNCH_PLAYER_ID, "CENTER_FORWARD"),
)


def test_exeter_impect_5221_is_coach_532():
    assert _coach_formation_from_lineup("5-2-2-1", EXETER_XI) == "5-3-2"


def test_salford_impect_5221_stays_523():
    assert _coach_formation_from_lineup("5-2-2-1", SALFORD_XI) == "5-2-3"


def test_byers_is_midfield_in_532():
    assert (
        _unit_for_position(
            "ATTACKING_MIDFIELD", "5-3-2", player_id=BYERS_PLAYER_ID
        )
        == "MID"
    )
    assert (
        _unit_for_position("ATTACKING_MIDFIELD", "5-3-2", player_id=50215) == "ATT"
    )
    assert _unit_for_position("CENTER_FORWARD", "5-3-2", player_id=LYNCH_PLAYER_ID) == "ATT"
    assert _unit_for_position("DEFENSE_MIDFIELD", "5-3-2", player_id=24992) == "MID"


def test_532_baselines_are_three_man_midfield():
    assert _unit_baselines_for_formation("5-3-2") == {"DEF": 5, "MID": 3, "ATT": 2}


def test_cached_523_payload_moves_byers_into_midfield():
    stats = {
        "formation": "5-2-3",
        "unitBaselines": {"DEF": 5, "MID": 2, "ATT": 3},
        "players": [
            {
                "playerId": 69194,
                "name": "Ben Garrity",
                "unit": "MID",
                "started": True,
                "xg": 0.1,
                "defensiveInterventions": 10,
            },
            {
                "playerId": 24992,
                "name": "Kyle Dempsey",
                "unit": "MID",
                "started": True,
                "xg": 0.2,
                "defensiveInterventions": 10,
            },
            {
                "playerId": BYERS_PLAYER_ID,
                "name": "George Byers",
                "unit": "ATT",
                "started": True,
                "xg": 0.3,
                "defensiveInterventions": 15,
            },
            {
                "playerId": LYNCH_PLAYER_ID,
                "name": "Oliver Lynch",
                "unit": "ATT",
                "started": True,
                "xg": 0.1,
                "defensiveInterventions": 5,
            },
        ],
    }
    assert _retouch_byers_532_stats(stats) is True
    assert stats["formation"] == "5-3-2"
    assert stats["unitBaselines"] == {"DEF": 5, "MID": 3, "ATT": 2}
    assert stats["units"]["MID"]["starters"] == 3
    assert "Byers" in stats["units"]["MID"]["starterNames"]
    assert stats["units"]["MID"]["xg"] == 0.6
    assert stats["units"]["ATT"]["starters"] == 1
