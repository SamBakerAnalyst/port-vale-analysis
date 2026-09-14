"""Last starting XI must sit in the labelled shape, not three flat lines."""

from __future__ import annotations

from app.pre_match import _beautify_pitch_layout, _slot_pitch_to_formation


def _player(player_id: int, name: str, position: str, band: str, x: float, y: float) -> dict:
    return {
        "player_id": player_id,
        "name": name,
        "short_name": name,
        "position": position,
        "band": band,
        "x_pct": x,
        "y_pct": y,
        "starts": 1,
        "minutes": 90,
    }


# Walsall vs Exeter 5 Sep — Impect 4-2-3-1, stacked as a 4-3-3 before slotting.
WALSALL_EXETER = [
    _player(79613, "Ward", "GOALKEEPER", "gk", 50, 94),
    _player(120967, "Hancock", "LEFT_WINGBACK_DEFENDER", "def", 12, 74),
    _player(38517, "Leak", "CENTRAL_DEFENDER", "def", 28, 74),
    _player(97789, "Connolly", "CENTRAL_DEFENDER", "def", 72, 74),
    _player(128007, "Ahui", "RIGHT_WINGBACK_DEFENDER", "def", 88, 74),
    _player(240197, "Moore", "DEFENSE_MIDFIELD", "mid", 28, 48),
    _player(118548, "Crew", "DEFENSE_MIDFIELD", "mid", 72, 48),
    _player(3858, "Evans", "ATTACKING_MIDFIELD", "mid", 50, 48),
    _player(108602, "Smith", "LEFT_WINGER", "attack", 12, 18),
    _player(31564, "Pressley", "CENTER_FORWARD", "attack", 50, 18),
    _player(105153, "Clarke", "RIGHT_WINGER", "attack", 88, 18),
]


def test_4231_puts_the_ten_in_the_hole():
    slotted = _slot_pitch_to_formation(WALSALL_EXETER, "4-2-3-1")
    by_name = {row["short_name"]: row for row in slotted}
    evans_y = float(by_name["Evans"]["y_pct"])
    pivot_y = min(float(by_name["Moore"]["y_pct"]), float(by_name["Crew"]["y_pct"]))
    pressley_y = float(by_name["Pressley"]["y_pct"])
    assert evans_y < pivot_y - 8
    assert evans_y > pressley_y + 8
    assert by_name["Evans"]["formation_slot"] == "ATTACKING_MIDFIELD"


def test_beautify_does_not_drop_the_ten_onto_the_pivots():
    rows = _beautify_pitch_layout(
        [
            {**_player(1, "Evans", "ATTACKING_MIDFIELD", "mid", 50, 28), "formation_slot": "ATTACKING_MIDFIELD"},
            {**_player(2, "Moore", "DEFENSE_MIDFIELD", "mid", 34, 50), "formation_slot": "DEFENSE_MIDFIELD"},
            {**_player(3, "Crew", "DEFENSE_MIDFIELD", "mid", 66, 50), "formation_slot": "DEFENSE_MIDFIELD"},
        ]
    )
    by_name = {row["short_name"]: row for row in rows}
    assert float(by_name["Evans"]["y_pct"]) <= 38
    assert float(by_name["Evans"]["y_pct"]) < float(by_name["Moore"]["y_pct"]) - 8
