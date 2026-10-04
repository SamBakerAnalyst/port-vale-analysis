"""Colchester squad corrections, shared XI board, and 19 Sep line-up phases."""

from __future__ import annotations

from pathlib import Path

from app.pre_match import (
    FORMATION_TEMPLATES,
    _normalize_formation_key,
    _relayout_existing_phase,
    build_verified_last_game_phases,
    repair_last_game_detail,
)
from app.pre_match_board import load_squad_board, save_squad_board, squad_board_store_path
from app.pre_match_squad_overrides import (
    apply_club_squad_overrides,
    availability_defaults_for_rows,
)

_MESSY_COLCHESTER = [
    {"id": 1, "name": "Tom Smith", "shirt_number": 1, "position_code": "CENTRAL_MIDFIELD", "minutes": 10},
    {"id": 2, "name": "Kien Connolly", "shirt_number": 39, "position_code": "CENTRAL_MIDFIELD", "minutes": 5},
    {"id": 3, "name": "Samuel Kuffour", "shirt_number": 44, "position_code": "CENTRAL_DEFENDER", "minutes": 20},
    {"id": 4, "name": "Samuel Kuffour Jr", "shirt_number": 28, "position_code": "CENTRAL_MIDFIELD", "minutes": 40},
    {"id": 5, "name": "Jack Tucker", "shirt_number": 8, "position_code": "CENTRAL_MIDFIELD", "minutes": 800},
    {"id": 6, "name": "Frankie Terry", "shirt_number": 4, "position_code": "CENTRAL_DEFENDER", "minutes": 100},
    {"id": 7, "name": "Jake Leake", "shirt_number": 16, "position_code": "CENTRAL_DEFENDER", "minutes": 50},
    {"id": 8, "name": "Paul Digby", "shirt_number": 8, "position_code": "CENTRAL_MIDFIELD", "minutes": 200},
    {"id": 9, "name": "Jay Williams", "shirt_number": 28, "position_code": "DEFENSE_MIDFIELD", "minutes": 700},
    {"id": 10, "name": "Jaden Williams", "shirt_number": 28, "position_code": "LEFT_WINGER", "minutes": 100},
    {"id": 11, "name": "Kylian Kouassi", "shirt_number": 9, "position_code": "CENTER_FORWARD", "minutes": 400},
    {"id": 12, "name": "Leon Chiwome", "shirt_number": 19, "position_code": "CENTER_FORWARD", "minutes": 80},
    {"id": 13, "name": "Teddy Bishop", "shirt_number": 18, "position_code": "CENTRAL_MIDFIELD", "minutes": 300},
    {"id": 14, "name": "Milton Oni", "shirt_number": 21, "position_code": "CENTRAL_MIDFIELD", "minutes": 40},
    {"id": 15, "name": "Jack Payne", "shirt_number": 16, "position_code": "ATTACKING_MIDFIELD", "minutes": 600},
    {"id": 16, "name": "Sean Raggett", "shirt_number": 28, "position_code": "CENTRAL_DEFENDER", "minutes": 700},
    {"id": 17, "name": "Thimothee Lo-Tutala", "shirt_number": 22, "position_code": "GOALKEEPER", "minutes": 900},
    {"id": 18, "name": "Ellis Iandolo", "shirt_number": 3, "position_code": "LEFT_WINGBACK_DEFENDER", "minutes": 800},
    {"id": 19, "name": "Rob Hunt", "shirt_number": 2, "position_code": "RIGHT_WINGBACK_DEFENDER", "minutes": 800},
    {"id": 20, "name": "Moses Sesay", "shirt_number": 12, "position_code": "CENTRAL_MIDFIELD", "minutes": 500},
    {"id": 21, "name": "Harry Anderson", "shirt_number": 7, "position_code": "LEFT_WINGER", "minutes": 600},
    {"id": 22, "name": "Oscar Thorn", "shirt_number": 27, "position_code": "RIGHT_WINGER", "minutes": 400},
    {"id": 23, "name": "Kane Vincent-Young", "shirt_number": 30, "position_code": "RIGHT_WINGBACK_DEFENDER", "minutes": 100},
]


def _rows():
    return apply_club_squad_overrides("Colchester United", _MESSY_COLCHESTER)


def _by_name(rows, name):
    return next(row for row in rows if row["name"] == name)


def test_colchester_squad_corrections():
    rows = _rows()
    names = {row["name"] for row in rows}
    assert "Samuel Kuffour" not in names
    smith = _by_name(rows, "Tom Smith")
    assert smith["position_code"] == "GOALKEEPER"
    assert smith["band"] == "gk"
    assert _by_name(rows, "Kien Connolly")["position_code"] == "CENTER_FORWARD"
    assert _by_name(rows, "Jack Tucker")["shirt_number"] == 5
    assert _by_name(rows, "Jack Tucker")["band"] == "def"
    assert _by_name(rows, "Samuel Kuffour Jr")["shirt_number"] == 44
    assert _by_name(rows, "Samuel Kuffour Jr")["band"] == "def"
    shirts = {
        "Jake Leake": 21,
        "Frankie Terry": 24,
        "Kylian Kouassi": 14,
        "Jaden Williams": 17,
        "Leon Chiwome": 11,
        "Paul Digby": 6,
        "Teddy Bishop": 8,
        "Milton Oni": 42,
        "Jay Williams": 26,
        "Jack Payne": 10,
        "Sean Raggett": 20,
        "Ben Perry": 4,
        "Ronnie Harvey": 47,
        "Adrian Akande": 23,
        "Kaion Lisbie": 34,
    }
    for name, shirt in shirts.items():
        assert _by_name(rows, name)["shirt_number"] == shirt
    assert _by_name(rows, "Max Jolliffe")["shirt_number"] is None
    assert _by_name(rows, "Max Jolliffe")["band"] == "mid"


def test_availability_defaults_include_doubt_and_reasons():
    rows = _rows()
    defaults = availability_defaults_for_rows("Colchester United", rows)
    by_id = {row["name"]: defaults[str(row["id"])] for row in rows if str(row["id"]) in defaults}
    assert by_id["Jaden Williams"]["status"] == "suspended"
    assert "3-match ban" in by_id["Jaden Williams"]["reason"]
    assert "20 Oct" in by_id["Jaden Williams"]["expected_return"]
    assert by_id["Teddy Bishop"]["status"] == "injured"
    assert by_id["Jake Leake"]["status"] == "injured"
    assert by_id["Jay Williams"]["status"] == "international"
    assert "St Kitts" in by_id["Jay Williams"]["reason"]
    assert by_id["Kane Vincent-Young"]["status"] == "doubt"
    assert by_id["Max Jolliffe"]["status"] == "injured"


def test_formation_templates_keep_outfield_outside_the_box():
    assert _normalize_formation_key("3-5-2") == "3-5-2"
    assert _normalize_formation_key("5-4-1") == "5-4-1"
    assert _normalize_formation_key("5-2-2-1") == "5-2-2-1"
    for key in ("4-2-3-1", "5-4-1", "4-4-2", "3-5-2", "5-2-2-1", "4-3-3", "5-3-2"):
        slots = FORMATION_TEMPLATES[key]
        assert len(slots) == 11
        for position, x_pct, y_pct, _side in slots:
            if position == "GOALKEEPER":
                assert y_pct >= 88
                continue
            assert 18 <= y_pct <= 80, (key, position, y_pct)
            assert 12 <= x_pct <= 88, (key, position, x_pct)


def test_cheltenham_19_sep_phases():
    rows = _rows()
    phases = build_verified_last_game_phases(
        "Colchester United",
        "Cheltenham Town",
        "2026-09-19T15:00:00",
        rows,
    )
    assert phases is not None
    assert len(phases) == 4
    start, sub_on, red, late = phases

    def placed(phase):
        return {
            player["name"]: (
                player["shirt_number"],
                player["x_pct"],
                player["y_pct"],
                player.get("highlight"),
            )
            for player in phase["pitch_players"]
        }

    kickoff = placed(start)
    assert kickoff["Jay Williams"][:3] == (26, 36.0, 55.0)
    assert kickoff["Jack Tucker"][0] == 5
    assert kickoff["Kylian Kouassi"][2] == 18.0
    assert kickoff["Thimothee Lo-Tutala"][2] == 91.0
    assert "Jaden Williams" not in kickoff

    at_69 = placed(sub_on)
    assert "Oscar Thorn" not in at_69
    assert at_69["Jaden Williams"] == (17, 82.0, 38.0, "sub")
    assert at_69["Jay Williams"][:3] == (26, 36.0, 55.0)
    assert sub_on["on_names"] == ["Williams 17"]
    assert sub_on["off_names"] == ["Thorn 27"]
    assert sub_on["sent_off"] == []

    at_83 = placed(red)
    assert "Jaden Williams" not in at_83
    assert len(at_83) == 10
    assert at_83["Harry Anderson"][:3] == (7, 28.0, 38.0)
    assert at_83["Jack Payne"][:3] == (10, 72.0, 38.0)
    assert at_83["Jay Williams"][:3] == (26, 36.0, 55.0)
    assert at_83["Moses Sesay"][:3] == (12, 64.0, 55.0)
    assert at_83["Ellis Iandolo"][1] == 16.0
    assert red["sent_off"][0]["shirt_number"] == 17
    assert red["sent_off"][0]["minute"] == "83'"
    assert all(player.get("ghost") is not True for player in red["pitch_players"])

    at_89 = placed(late)
    assert "Harry Anderson" not in at_89
    assert at_89["Leon Chiwome"] == (11, 28.0, 38.0, "sub")
    assert at_89["Jack Payne"][:3] == (10, 72.0, 38.0)
    assert late["sent_off"][0]["name"] == "Jaden Williams"
    for phase in phases:
        for player in phase["pitch_players"]:
            y_pct = float(player["y_pct"])
            if "GOAL" in str(player.get("position") or "").upper() or player.get("band") == "gk":
                assert y_pct >= 88
            else:
                assert 18 <= y_pct <= 80
                assert 12 <= float(player["x_pct"]) <= 88


def test_repair_replaces_only_the_verified_match():
    rows = _rows()
    detail = {
        "opponent": "Cheltenham Town",
        "date": "2026-09-19",
        "phases": [{"kind": "start", "pitch_players": [{"name": "Wrong", "shirt_number": 28, "y_pct": 8}]}],
    }
    repaired = repair_last_game_detail(detail, "Colchester United", rows)
    assert repaired["phases"][0]["label"] == "Starting XI"
    assert any(player["name"] == "Jay Williams" for player in repaired["phases"][0]["pitch_players"])

    other = {
        "opponent": "Newport County",
        "date": "2026-09-05",
        "formation": "4-2-3-1",
        "phases": [
            {
                "kind": "change",
                "minute_labels": ["82'"],
                "formation": "4-2-3-1",
                "pitch_players": [
                    {
                        "player_id": 10,
                        "name": "Jaden Williams",
                        "shirt_number": 28,
                        "position": "RIGHT_WINGER",
                        "y_pct": 12,
                        "x_pct": 90,
                        "highlight": "red",
                        "ghost": True,
                    },
                    {
                        "player_id": 9,
                        "name": "Jay Williams",
                        "shirt_number": 28,
                        "position": "DEFENSE_MIDFIELD",
                        "y_pct": 55,
                        "x_pct": 36,
                    },
                ],
            }
        ],
    }
    kept = repair_last_game_detail(other, "Colchester United", rows)
    live = kept["phases"][0]["pitch_players"]
    assert all(player.get("name") != "Jaden Williams" for player in live)
    assert kept["phases"][0]["sent_off"][0]["shirt_number"] == 17
    jay = next(player for player in live if player["name"] == "Jay Williams")
    assert jay["shirt_number"] == 26


def test_cached_full_xi_inside_the_box_is_reslotted():
    strikers = [
        {
            "player_id": index,
            "name": f"Player {index}",
            "position": "CENTER_FORWARD" if index < 2 else "CENTRAL_DEFENDER" if index < 6 else "CENTRAL_MIDFIELD" if index < 10 else "GOALKEEPER",
            "x_pct": 10 + index * 7,
            "y_pct": 8 if index < 2 else 94 if index == 10 else 50,
            "starts": 1,
        }
        for index in range(11)
    ]
    phase = {"formation": "4-4-2", "pitch_players": strikers}
    laid = _relayout_existing_phase(phase, "Someone Else")
    outfield = [
        player
        for player in laid["pitch_players"]
        if "GOAL" not in str(player.get("position") or "").upper()
    ]
    assert outfield
    assert all(18 <= float(player["y_pct"]) <= 80 for player in outfield)


def test_squad_board_round_trip_and_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_DATA_ROOT", str(tmp_path / "missing"))
    monkeypatch.setattr("app.pre_match_board.DATA_ROOT", tmp_path)
    monkeypatch.setattr(
        "app.pre_match_board.squad_board_store_path",
        lambda: tmp_path / "pre-match-squad-board.json",
    )
    empty = load_squad_board(2120, 2157)
    assert empty["saved"] is False
    saved = save_squad_board(
        2120,
        2157,
        availability={
            "17": {"status": "suspended", "reason": "Red card", "expected_return": "20 Oct"},
            "6": {"status": "available", "reason": "", "expected_return": ""},
            "nope": {"status": "injured"},
        },
        pitch_xi={"5": -44, "12": "not-a-player"},
        pitch_shape={"slot:0": {"x": 18.2, "y": 34.4}, "bad": {"x": "no"}},
    )
    assert saved["saved"] is True
    assert saved["availability"]["17"]["status"] == "suspended"
    assert "6" not in saved["availability"]
    assert saved["pitch_xi"] == {"5": -44}
    assert saved["pitch_shape"]["slot:0"] == {"x": 18.2, "y": 34.4}
    loaded = load_squad_board(2120, 2157)
    assert loaded["pitch_xi"]["5"] == -44
    reset = save_squad_board(2120, 2157, reset=True)
    assert reset["saved"] is False
    assert load_squad_board(2120, 2157)["saved"] is False
    assert squad_board_store_path().name == "pre-match-squad-board.json"


def test_pre_match_page_wires_save_doubt_and_sent_off_strip():
    js = Path("static/pre-match.js").read_text(encoding="utf-8")
    assert 'const AVAILABILITY_CYCLE = ["available", "injured", "suspended", "international", "doubt"]' in js
    assert 'data-pitch-save' in js
    assert "persistSquadBoard" in js
    assert "sentOffStripHtml" in js
    load_availability = js.split("function loadAvailability()", 1)[1][:200]
    assert "localStorage" not in load_availability
    assert "ensureSquadBoard" in load_availability
    css = Path("static/pre-match.css").read_text(encoding="utf-8")
    assert ".last-game-sentoff" in css
    assert ".squad-roster__player--doubt" in css
