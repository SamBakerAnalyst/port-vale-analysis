"""Pinned match formations + top-7 Req per shape (4-4-2, 4-3-3, 4-2-3-1, 3-5-2, 3-4-3)."""

from __future__ import annotations

import pytest

import app.blocks_analysis as ba


def _player(pid, position, *, started=True, replaced=None, **kpis):
    row = {
        "playerId": pid,
        "name": f"Player {pid}",
        "position": position,
        "started": started,
        "unit": None,
        **kpis,
    }
    if replaced:
        row["replacedPlayerId"] = replaced
    return row


BACK_THREE_XI = [
    _player(1, "GOALKEEPER"),
    _player(2, "CENTRAL_DEFENDER"),
    _player(3, "CENTRAL_DEFENDER"),
    _player(4, "CENTRAL_DEFENDER"),
    _player(5, "LEFT_WINGBACK_DEFENDER"),
    _player(6, "RIGHT_WINGBACK_DEFENDER"),
    _player(7, "DEFENSE_MIDFIELD"),
    _player(8, "DEFENSE_MIDFIELD"),
    _player(9, "ATTACKING_MIDFIELD"),
    _player(10, "ATTACKING_MIDFIELD"),
    _player(11, "CENTER_FORWARD"),
]


def _units(players):
    out = {"DEF": [], "MID": [], "ATT": []}
    for player in players:
        if player.get("unit") in out:
            out[player["unit"]].append(player["playerId"])
    return out


def test_pinned_352_puts_wingbacks_in_midfield():
    players = [dict(row) for row in BACK_THREE_XI]
    assert ba._assign_units_for_formation(players, "3-5-2")
    units = _units(players)
    assert units["DEF"] == [2, 3, 4]
    assert sorted(units["MID"]) == [5, 6, 7, 8, 9]
    assert sorted(units["ATT"]) == [10, 11]


def test_pinned_442_fills_four_two_four():
    players = [
        _player(1, "GOALKEEPER"),
        _player(2, "CENTRAL_DEFENDER"),
        _player(3, "CENTRAL_DEFENDER"),
        _player(4, "LEFT_WINGBACK_DEFENDER"),
        _player(5, "RIGHT_WINGBACK_DEFENDER"),
        _player(6, "DEFENSE_MIDFIELD"),
        _player(7, "DEFENSE_MIDFIELD"),
        _player(8, "LEFT_WINGER"),
        _player(9, "RIGHT_WINGER"),
        _player(10, "ATTACKING_MIDFIELD"),
        _player(11, "CENTER_FORWARD"),
    ]
    assert ba._assign_units_for_formation(players, "4-4-2")
    units = _units(players)
    assert len(units["DEF"]) == 4
    assert sorted(units["MID"]) == [6, 7]
    assert sorted(units["ATT"]) == [8, 9, 10, 11]


def test_subs_take_the_unit_of_the_player_they_replaced():
    players = [dict(row) for row in BACK_THREE_XI] + [
        _player(20, "CENTER_FORWARD", started=False, replaced=6),
    ]
    ba._assign_units_for_formation(players, "3-4-3")
    sub = next(row for row in players if row["playerId"] == 20)
    assert sub["unit"] == "MID"


def test_slot_sums_count_subs_in_the_replaced_slot():
    roles = {
        2: {"started": True, "position": "CENTRAL_DEFENDER"},
        3: {"started": True, "position": "CENTRAL_DEFENDER"},
        5: {"started": True, "position": "LEFT_WINGBACK_DEFENDER"},
        11: {"started": True, "position": "CENTER_FORWARD"},
        20: {"started": False, "position": "CENTRAL_MIDFIELD", "replaced": 11},
    }
    report = [
        {"playerId": 2, "defendersBypassed": 4, "duelWon": 5, "duelTotal": 10},
        {"playerId": 3, "defendersBypassed": 2, "duelWon": 3, "duelTotal": 5},
        {"playerId": 5, "defendersBypassed": 6},
        {"playerId": 11, "shots": 2},
        {"playerId": 20, "shots": 1},
    ]
    out = ba._slot_sums_from_report(report, roles)
    assert out["starters"] == {"CB": 2, "FB": 1, "CF": 1}
    assert out["sums"]["CB"]["defendersBypassed"] == 6
    assert out["sums"]["CF"]["shots"] == 3
    assert "CM" not in out["sums"]


def _slot(**values):
    row = {key: 0.0 for key in ba.SLOT_SUM_KEYS}
    row.update(values)
    return row


def test_formation_targets_sum_slots_per_unit():
    per_slot = {
        "CB": _slot(defendersBypassed=2.0, duelWon=6.0, duelTotal=10.0),
        "FB": _slot(defendersBypassed=3.0, duelWon=4.0, duelTotal=10.0),
        "WB": _slot(defendersBypassed=5.0, duelWon=5.0, duelTotal=10.0),
        "DM": _slot(defendersBypassed=4.0, duelWon=5.0, duelTotal=10.0),
        "CM": _slot(defendersBypassed=6.0, duelWon=5.0, duelTotal=10.0),
        "AM": _slot(defendersBypassed=7.0, duelWon=4.0, duelTotal=10.0),
        "WIDE": _slot(defendersBypassed=8.0, duelWon=4.0, duelTotal=10.0, shots=1.0),
        "CF": _slot(defendersBypassed=1.0, duelWon=3.0, duelTotal=10.0, shots=2.0),
    }
    targets = ba._formation_targets_from_slots(per_slot)
    assert set(ba.FORMATION_OPTIONS) <= set(targets)
    # 4-4-2 DEF = 2 CB + 2 FB
    assert targets["4-4-2"]["DEF"]["defendersBypassed"] == 10.0
    assert targets["4-4-2"]["DEF"]["duelRate"] == 50.0
    # 3-5-2 DEF = 3 CB; MID = 2 WB + DM + 2 CM
    assert targets["3-5-2"]["DEF"]["defendersBypassed"] == 6.0
    assert targets["3-5-2"]["DEF"]["duelRate"] == 60.0
    assert targets["3-5-2"]["MID"]["defendersBypassed"] == 26.0
    # 4-2-3-1 ATT = AM + 2 WIDE + CF; 4-4-2 ATT = 2 WIDE + 2 CF
    assert targets["4-2-3-1"]["ATT"]["defendersBypassed"] == 24.0
    assert targets["4-4-2"]["ATT"]["shots"] == 6.0
    assert targets["3-4-3"]["MID"]["defendersBypassed"] == 20.0


def test_missing_slot_falls_back_to_nearest_role():
    per_slot = {"CB": _slot(defendersBypassed=2.0), "FB": _slot(defendersBypassed=3.0)}
    targets = ba._formation_targets_from_slots(per_slot)
    # No wing-back sample → 3-5-2 MID still gets the FB line for the WB slots.
    assert targets["3-5-2"]["MID"]["defendersBypassed"] == 6.0


def test_override_store_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "FORMATIONS_PATH", tmp_path / "formations.json")
    monkeypatch.setattr(ba, "DATA_DIR", tmp_path)
    assert ba._save_formation_override(123, "4-4-2") == {"123": "4-4-2"}
    assert ba._save_formation_override(456, "3-5-2") == {"123": "4-4-2", "456": "3-5-2"}
    assert ba._save_formation_override(123, None) == {"456": "3-5-2"}


def test_formation_choice_validation():
    assert ba._normalize_formation_choice("442") == "4-4-2"
    assert ba._normalize_formation_choice("4-2-3-1") == "4-2-3-1"
    assert ba._normalize_formation_choice("auto") is None
    with pytest.raises(ValueError):
        ba._normalize_formation_choice("4-1-4-1")


def test_apply_overrides_retags_units_and_attaches_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "FORMATIONS_PATH", tmp_path / "formations.json")
    monkeypatch.setattr(ba, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ba, "formation_unit_targets", lambda **_: {"3-5-2": {"DEF": {}}})
    ba._save_formation_override(999, "3-5-2")
    players = [dict(row, defendersBypassed=1) for row in BACK_THREE_XI]
    payload = {
        "blocks": [
            {
                "id": 2,
                "totals": {},
                "fixtures": [
                    {
                        "matchId": 999,
                        "played": True,
                        "stats": {"played": True, "formation": "5-2-3", "players": players},
                    },
                    {"matchId": 1000, "played": False, "stats": {"formation": None}},
                ],
            }
        ],
        "benchmarks": {},
    }
    out = ba.apply_formation_overrides(payload)
    fixture = out["blocks"][0]["fixtures"][0]
    stats = fixture["stats"]
    assert stats["formation"] == "3-5-2"
    assert stats["autoFormation"] == "5-2-3"
    assert stats["formationSource"] == "manual"
    assert stats["unitBaselines"] == {"DEF": 3, "MID": 5, "ATT": 2}
    assert stats["units"]["DEF"]["starters"] == 3
    assert stats["units"]["MID"]["starters"] == 5
    assert out["blocks"][0]["totals"]["formations"] == ["3-5-2"]
    assert out["benchmarks"]["unitsByFormation"] == {"3-5-2": {"DEF": {}}}
    # Cached payload untouched.
    assert payload["blocks"][0]["fixtures"][0]["stats"]["formation"] == "5-2-3"
