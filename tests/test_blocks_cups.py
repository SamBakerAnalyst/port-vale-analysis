"""Blocks Analysis — dedicated Cups tab (non-league fixtures)."""

from __future__ import annotations

from app.blocks_analysis import (
    CUPS_BLOCK_ID,
    _assemble_blocks_payload,
    _build_cups_block,
)


def _cup_match(match_id: int, *, outcome: str = "loss") -> dict:
    return {
        "matchId": match_id,
        "iterationId": 2227,
        "scheduledDate": "2026-08-07T18:45:00Z",
        "competitionLabel": "EFL Cup",
        "competitionShort": "Cup",
        "isHome": True,
        "home": {"squadId": 882, "name": "Port Vale", "score": 0},
        "away": {"squadId": 1, "name": "Wolves", "score": 2},
        "opponent": {"squadId": 1, "name": "Wolverhampton Wanderers", "initials": "WOL"},
        "outcome": outcome,
        "available": True,
    }


def test_build_cups_block_serializes_fixtures():
    block = _build_cups_block([_cup_match(285444)], {})
    assert block["id"] == CUPS_BLOCK_ID
    assert block["kind"] == "cups"
    assert len(block["fixtures"]) == 1
    assert block["fixtures"][0]["competitionLabel"] == "EFL Cup"
    assert block["fixtures"][0]["matchId"] == 285444


def test_assemble_payload_appends_cups_after_nine_league_blocks():
    league = [
        {
            "matchId": 270712,
            "iterationId": 2120,
            "scheduledDate": "2026-08-15T11:30:00Z",
            "isHome": True,
            "home": {"squadId": 882, "name": "Port Vale", "score": 0},
            "away": {"squadId": 2, "name": "Oldham", "score": 1},
            "opponent": {"squadId": 2, "name": "Oldham Athletic"},
            "outcome": "loss",
            "available": True,
        }
    ]
    payload = _assemble_blocks_payload(
        league,
        {},
        cup_matches=[_cup_match(285444)],
        force_refresh=False,
    )
    blocks = payload["blocks"]
    assert len(blocks) == 10
    assert blocks[-1]["id"] == CUPS_BLOCK_ID
    assert payload["cupCount"] == 1
    assert blocks[0]["id"] == 1
