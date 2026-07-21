from __future__ import annotations

from app.main import (
    _enrich_player_label,
    _merge_player_options,
    _player_key,
    _resolve_player_catalog_option,
)


def test_player_key_includes_id() -> None:
    assert _player_key("Cameron Humphreys", 12345) == "cameron humphreys|12345"
    assert _player_key("Cameron Humphreys") == "cameron humphreys"


def test_merge_splits_homonyms_by_player_id() -> None:
    players_by_iteration = {
        1: [
            {
                "commonname": "Cameron Humphreys",
                "id": 100,
                "currentSquadId": 50,
                "birthdate": "1998-01-01",
            },
            {
                "commonname": "Cameron Humphreys",
                "id": 200,
                "currentSquadId": 99,
                "birthdate": "2002-06-15",
            },
        ],
        2: [
            {
                "commonname": "Cameron Humphreys",
                "id": 100,
                "currentSquadId": 50,
            },
            {
                "commonname": "Cameron Humphreys",
                "id": 201,
                "currentSquadId": 77,
            },
        ],
    }

    merged = _merge_player_options([1, 2], players_by_iteration)
    keys = {item["key"] for item in merged}

    assert len(merged) == 3
    assert "cameron humphreys|100" in keys
    assert "cameron humphreys|200" in keys
    assert "cameron humphreys|201" in keys

    primary = next(item for item in merged if item["key"] == "cameron humphreys|100")
    assert primary["ids_by_iteration"] == {"1": 100, "2": 100}
    assert primary["squad_ids_by_iteration"] == {"1": 50, "2": 50}


def test_enrich_player_label_uses_league_and_club() -> None:
    player = {
        "name": "Cameron Humphreys",
        "age": 26,
        "ids_by_iteration": {"1": 100},
        "squad_ids_by_iteration": {"1": 50},
        "seasons": [
            {
                "iteration_id": 1,
                "competition_name": "League One",
                "chartable": True,
            }
        ],
    }
    iteration_meta = {1: {"competition_name": "League One"}}
    squad_names = {1: {50: "AFC Wimbledon"}}

    labeled = _enrich_player_label(player, iteration_meta, squad_names)

    assert labeled["label"] == "Cameron Humphreys (26) — League One · AFC Wimbledon"
    assert labeled["club"] == "AFC Wimbledon"
    assert labeled["league"] == "League One"


def test_resolve_legacy_name_only_key() -> None:
    options_by_key = {
        "cameron humphreys|100": {
            "key": "cameron humphreys|100",
            "name": "Cameron Humphreys",
            "label": "Cameron Humphreys (26) — League One · AFC Wimbledon",
        },
        "cameron humphreys|200": {
            "key": "cameron humphreys|200",
            "name": "Cameron Humphreys",
            "label": "Cameron Humphreys (22) — League Two · Tranmere Rovers",
        },
    }

    option, warning = _resolve_player_catalog_option("cameron humphreys", options_by_key)
    assert option is None
    assert warning is not None
    assert "Ambiguous" in warning

    option, warning = _resolve_player_catalog_option(
        "cameron humphreys|100",
        options_by_key,
    )
    assert option is not None
    assert warning is None
    assert option["key"] == "cameron humphreys|100"
