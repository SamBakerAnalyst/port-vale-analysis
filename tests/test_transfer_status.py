"""A player who has already moved should not read as available.

Gbemi Arubi stayed in the Centre-forward pool as a Dundalk player after signing
for Burton Albion. These pin the matching either side of that: confirmed moves
must be caught, and a namesake must not be painted as gone.
"""

from __future__ import annotations

import json

import pytest

from app import transfer_status as ts

# Captured before the autouse fixture redirects it at a temp file.
SHIPPED_CANDIDATES = ts.TRANSFER_REPORT_CANDIDATES

REPORT = {
    "updated": "2026-09-07",
    "window": "Summer 2026 (15 June – 1/3 September)",
    "season": "2026/27",
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
    monkeypatch.setattr(ts, "TRANSFER_REPORT_CANDIDATES", (path,))
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


def test_a_player_already_at_the_club_he_signed_for_is_not_flagged():
    """The row is right, so there is nothing to say.

    Missing this flagged 866 players on Staging. Max Merrick appeared as
    "Hartlepool United -> Hartlepool United (from Chelsea)", which is not a
    warning, it is just where he plays now. At that volume nobody reads the
    colour at all.
    """
    assert ts.lookup("Gbemi Arubi", "Burton Albion") is None
    assert ts.lookup("Harry Wood", "Barnet") is None


def test_a_player_who_moved_twice_is_caught_at_the_middle_club(_report):
    """Selling club is checked before destination, so a stop-off still flags."""
    twice = json.loads(_report.read_text())
    twice["leagues"][1]["teams"][0]["signed"].append(
        {"player": "Rory Feely", "other": "Barnet", "fee": "Undisclosed"}
    )
    twice["leagues"][0]["teams"][0]["signed"].append(
        {"player": "Rory Feely", "other": "Waterford", "fee": "Free"}
    )
    _report.write_text(json.dumps(twice), encoding="utf-8")
    ts.reset_cache()

    # Sitting at Barnet in the pool: he arrived there, then left for Burton.
    moved = ts.lookup("Rory Feely", "Barnet")
    assert moved is not None, "the second move must still register"
    assert moved["status"] == ts.GONE


def test_a_namesake_is_flagged_to_check_not_painted_red():
    """Harry Wood of Shelbourne is in the winger pool; the Harry Wood who signed
    for Barnet came from Hull City. Same name, different player — so ask a human
    rather than telling a scout to drop him."""
    moved = ts.lookup("Harry Wood", "Shelbourne FC")
    assert moved["status"] == ts.CHECK
    assert moved["club"] == "Barnet"


def test_mk_dons_and_milton_keynes_dons_are_one_club():
    """An abbreviation sharing no word with the full name needs spelling out.

    Impect writes "Milton Keynes Dons", the transfer feed writes "MK Dons".
    Substring matching cannot bridge that, and it alone put seven players on
    Staging's amber list who were simply at the club they had just joined.
    """
    assert ts._clubs_match("MK Dons", "Milton Keynes Dons") is True
    assert ts.club_key("MK Dons") == ts.club_key("Milton Keynes Dons")


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


def test_between_windows_the_note_says_what_is_covered():
    from datetime import date

    meta = ts.report_meta(date(2026, 9, 8))

    assert meta["available"] is True
    assert meta["stale"] is False
    assert "League Two" in meta["detail"], "must state the coverage limit"


def test_a_report_built_before_the_open_window_reads_as_stale():
    """The January case. Nothing rebuilds this file on its own, so the page has
    to say so rather than let a clean row imply availability."""
    from datetime import date

    meta = ts.report_meta(date(2027, 1, 12))

    assert meta["stale"] is True
    assert "January" in meta["detail"]
    assert "missing" in meta["detail"]


def test_no_report_says_nobody_will_be_flagged(monkeypatch, tmp_path):
    monkeypatch.setattr(ts, "TRANSFER_REPORT_CANDIDATES", (tmp_path / "gone.json",))
    ts.reset_cache()

    meta = ts.report_meta()

    assert meta["available"] is False
    assert "not be flagged" in meta["detail"]


def test_a_missing_report_is_silent_not_fatal(monkeypatch, tmp_path):
    """No report should mean no flags, never a broken pool."""
    monkeypatch.setattr(ts, "TRANSFER_REPORT_CANDIDATES", (tmp_path / "gone.json",))
    ts.reset_cache()
    assert ts.lookup("Gbemi Arubi", "Dundalk") is None


def test_a_corrupt_report_is_silent_not_fatal(_report):
    _report.write_text("{ not json", encoding="utf-8")
    ts.reset_cache()
    assert ts.lookup("Gbemi Arubi", "Dundalk") is None


def test_we_look_where_the_report_actually_lives():
    """The first cut of this looked only under DATA_ROOT.

    On the server DATA_ROOT is the mounted volume, while the report ships inside
    the image at HUB_ROOT/data. So Staging found no file, flagged nobody, and
    looked identical to a window with no transfers in it. Sharing the report
    page's candidate list means the two cannot drift apart again.
    """
    from app.efl_transfer_report import REPORT_CANDIDATES

    assert SHIPPED_CANDIDATES == REPORT_CANDIDATES
    assert len(REPORT_CANDIDATES) >= 2


def test_a_real_report_is_readable_from_this_checkout(monkeypatch):
    """Guards the wiring end to end, against the file we actually ship.

    A fixture proves the matching works; only the shipped file proves we can
    find it. On Staging the file sat at /app/data while the code looked in
    /data, and every test still passed.
    """
    monkeypatch.setattr(ts, "TRANSFER_REPORT_CANDIDATES", SHIPPED_CANDIDATES)
    ts.reset_cache()

    assert ts._report_path() is not None, "no EFL transfer report in the repo"
    assert len(ts._load_index()) > 100
    assert ts.lookup("Gbemi Arubi", "Dundalk FC")["club"] == "Burton Albion"


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
