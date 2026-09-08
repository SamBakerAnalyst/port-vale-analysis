"""A player who has already moved should not read as available.

Gbemi Arubi stayed in the Centre-forward pool as a Dundalk player after signing
for Burton Albion. These pin the matching either side of that: confirmed moves
must be caught, and a namesake must not be painted as gone.
"""

from __future__ import annotations

import json

import pytest

from app import transfer_status as ts

REPORT = {
    "leagues": [
        {
            "name": "League One",
            "teams": [
                {
                    "name": "Burton Albion",
                    "signed": [
                        {"player": "Gbemi Arubi", "other": "Dundalk", "fee": "Undisclosed"}
                    ],
                },
                {
                    "name": "Wigan Athletic",
                    "signed": [
                        {"player": "Seamus O'Ceallaigh", "other": "Bohemians", "fee": "Free"},
                        {"player": "Andy Yiadom", "other": "unattached", "fee": "Free"},
                    ],
                },
            ],
        },
        {
            "name": "League Two",
            "teams": [
                {
                    "name": "Barnet",
                    "signed": [{"player": "Harry Wood", "other": "Hull City", "fee": "Loan"}],
                }
            ],
        },
    ]
}


@pytest.fixture(autouse=True)
def _report(tmp_path, monkeypatch):
    path = tmp_path / "efl-transfer-report-2026.json"
    path.write_text(json.dumps(REPORT), encoding="utf-8")
    monkeypatch.setattr(ts, "TRANSFER_REPORT_PATH", path)
    ts.reset_cache()
    yield path
    ts.reset_cache()


def test_the_player_who_started_this():
    moved = ts.lookup("Gbemi Arubi", "Dundalk FC")
    assert moved["status"] == ts.GONE
    assert moved["club"] == "Burton Albion"
    assert moved["league"] == "League One"
    assert moved["from"] == "Dundalk"


def test_a_club_written_two_ways_still_matches():
    """The pool says "Dundalk FC", the report says "Dundalk"."""
    assert ts.lookup("Gbemi Arubi", "Dundalk")["status"] == ts.GONE
    assert ts.lookup("Gbemi Arubi", "Dundalk Football Club")["status"] == ts.GONE


def test_bohemian_and_bohemians_are_the_same_club():
    """Impect writes "Bohemian Football Club"; the transfer feed writes
    "Bohemians". Requiring an exact string here would miss the move."""
    moved = ts.lookup("Seamus O'Ceallaigh", "Bohemian Football Club")
    assert moved["status"] == ts.GONE
    assert moved["club"] == "Wigan Athletic"


def test_an_accent_does_not_hide_a_move():
    assert ts.lookup("Séamus O'Ceallaigh", "Bohemians") is not None


def test_a_namesake_is_flagged_to_check_not_painted_red():
    """Harry Wood of Shelbourne is in the winger pool; the Harry Wood who signed
    for Barnet came from Hull City. Same name, different player — so ask a human
    rather than telling a scout to drop him."""
    moved = ts.lookup("Harry Wood", "Shelbourne FC")
    assert moved["status"] == ts.CHECK
    assert moved["club"] == "Barnet"


def test_derry_city_and_cork_city_are_not_confused():
    """Both reduce to something containing "city"; they must not match."""
    assert ts._clubs_match("Derry City", "Cork City") is False
    assert ts._clubs_match("Derry City", "Derry City FC") is True


def test_galway_and_galway_united_stay_distinct_words():
    """Stripping "United" as noise would merge two different clubs."""
    assert ts.club_key("Galway United") == "galway united"


def test_a_free_agent_signing_still_counts_as_gone():
    """No selling club to check against, but the move is on record."""
    moved = ts.lookup("Andy Yiadom", "Reading")
    assert moved["status"] == ts.GONE
    assert moved["club"] == "Wigan Athletic"


def test_a_player_with_no_move_gets_nothing():
    assert ts.lookup("Eoin Kenny", "Dundalk FC") is None


def test_a_blank_name_is_not_a_lookup():
    assert ts.lookup("", "Dundalk") is None
    assert ts.lookup(None, None) is None


def test_annotate_leaves_untouched_players_alone():
    row = {"name": "Eoin Kenny", "club": "Dundalk FC"}
    assert "transfer" not in ts.annotate(row)

    moved = ts.annotate({"name": "Gbemi Arubi", "club": "Dundalk FC"})
    assert moved["transfer"]["club"] == "Burton Albion"


def test_a_missing_report_is_silent_not_fatal(monkeypatch, tmp_path):
    """No report should mean no flags, never a broken pool."""
    monkeypatch.setattr(ts, "TRANSFER_REPORT_PATH", tmp_path / "gone.json")
    ts.reset_cache()
    assert ts.lookup("Gbemi Arubi", "Dundalk") is None


def test_a_corrupt_report_is_silent_not_fatal(_report):
    _report.write_text("{ not json", encoding="utf-8")
    ts.reset_cache()
    assert ts.lookup("Gbemi Arubi", "Dundalk") is None


def test_who_to_scout_rows_carry_the_flag():
    """Wiring check: annotated at serve time, not baked into the cache.

    The standouts rebuild takes four minutes. Attaching this to the cached
    payload would mean a transfer correction waited on that.
    """
    import app.main  # noqa: F401 - resolve the router imports
    from app.who_to_scout import _who_to_scout_player

    row = _who_to_scout_player(
        {"name": "Gbemi Arubi", "club": "Dundalk FC", "overall": 71.8, "minutes": 1799}
    )
    assert row["transfer"]["club"] == "Burton Albion"
    assert row["transfer"]["status"] == ts.GONE

    clean = _who_to_scout_player({"name": "Eoin Kenny", "club": "Dundalk FC"})
    assert "transfer" not in clean


def test_the_index_reloads_when_the_report_changes(_report):
    assert ts.lookup("Gbemi Arubi", "Dundalk")["club"] == "Burton Albion"

    amended = json.loads(_report.read_text())
    amended["leagues"][0]["teams"][0]["name"] = "Burton Albion Reserves"
    import os
    import time

    _report.write_text(json.dumps(amended), encoding="utf-8")
    os.utime(_report, (time.time() + 5, time.time() + 5))

    # A transfer correction must not have to wait on the four-minute
    # standouts rebuild.
    assert ts.lookup("Gbemi Arubi", "Dundalk")["club"] == "Burton Albion Reserves"
