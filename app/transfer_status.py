"""Has this player already moved club?

Who To Scout shows the club a player turned out for in the season data, which is
not the same as the club he is at today. Gbemi Arubi sat in the Centre-forward
pool as a Dundalk player long after signing for Burton Albion, and he is not
alone: 314 of the 723 signings in the Summer 2026 window came from clubs we
scout, so that many pool rows name a club the player has left.

The signings come from the EFL transfer report this repo already builds, so
there is no new feed to maintain. That also fixes the coverage, and it is worth
being blunt about it: the report tracks moves *into* League One, League Two, the
National League and the Scottish Premiership. A player joining a Championship
club, going abroad, or moving between Irish Prem clubs will not show up. So
"gone" means confirmed gone, while no flag means only "no move recorded" — not
"still available". Anything that dresses this up as full transfer coverage will
get a scout on a plane to watch someone else's player.

Matching is on name first. Only two names in 723 appear twice in the report, and
both are the same player on a loan return rather than two people, so collisions
inside the feed are not the risk. The risk is a namesake in a pool, which is why
a name-only hit reports as "check" rather than "gone" — a scout can settle it in
seconds, and a wrong red is worse than an amber.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from app.efl_transfer_report import REPORT_CANDIDATES

logger = logging.getLogger(__name__)

# Deliberately the same candidate list the report page uses, not a path of our
# own. On the server DATA_ROOT is the mounted volume while the report ships
# inside the image at HUB_ROOT/data, so picking one of the two silently found
# nothing on Staging and every player came back unflagged.
TRANSFER_REPORT_CANDIDATES = REPORT_CANDIDATES

# Sold or signed permanently, and no longer at the club on the row.
GONE = "gone"
# Away on loan. Not the same thing as sold: he is still their player and he
# comes back, so this must not read as gone.
LOAN_OUT = "loan_out"
# At the club on the row, but on loan from somewhere else. The row is correct;
# what matters is that any deal is with the parent club, not this one.
LOAN_IN = "loan_in"
# Name matched, selling club did not — most often a namesake or a club written a
# different way in the two sources.
CHECK = "check"

# A loan is a different fact about a player, not a weaker version of a transfer,
# and the pools have shown loans in blue for far longer than this code has
# existed. Painting one red would be a straight regression.
LOAN_STATUSES = frozenset({LOAN_OUT, LOAN_IN})

# Words that carry no identity, so "Dundalk" and "Dundalk FC" are one club.
# "United", "City", "Town" and the rest stay: Galway and Galway United are
# different clubs, and dropping them would merge them.
_GENERIC_CLUB_WORDS = frozenset({"fc", "afc", "football", "club", "the"})

# Two sources, two house styles. Substring matching absorbs most of it —
# "Dundalk" against "Dundalk FC", "Bohemian" against "Bohemians" — but an
# abbreviation that shares no word with the full name has to be spelled out.
# Impect says "Milton Keynes Dons" where the transfer feed says "MK Dons", and
# that alone accounted for seven of eighteen amber rows on Staging: players
# already at the club they had signed for.
_CLUB_ALIASES = {
    "mk dons": "milton keynes dons",
    "mk": "milton keynes dons",
}

# A seller that is not a club, so there is nothing to match a pool row against.
_NOT_A_CLUB = frozenset(
    {"", "unattached", "free agent", "free", "n/a", "na", "unknown", "?", "trial"}
)

# Transfer windows, as dates rather than a feeling. Ends are the deadline day
# itself; a few days either way does not change what we tell a scout.
_WINDOWS: tuple[tuple[str, tuple[int, int], tuple[int, int]], ...] = (
    ("January", (1, 1), (2, 3)),
    ("summer", (6, 14), (9, 2)),
)

_lock = threading.Lock()
_index: dict[str, list[dict[str, Any]]] | None = None
_index_mtime: float | None = None
_meta: dict[str, Any] = {}


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def name_key(value: str | None) -> str:
    """A name reduced to something two sources can agree on."""
    text = _strip_accents(str(value or "")).lower()
    text = re.sub(r"[^a-z\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def club_key(value: str | None) -> str:
    """A club reduced to its identifying words."""
    text = _strip_accents(str(value or "")).lower()
    text = re.sub(r"[^a-z\s]", " ", text)
    words = [w for w in text.split() if w and w not in _GENERIC_CLUB_WORDS]
    key = " ".join(words)
    return _CLUB_ALIASES.get(key, key)


def _clubs_match(seller: str | None, pool_club: str | None) -> bool:
    """Do these two spellings mean the same club?

    Substring either way, because the two sources abbreviate differently:
    "Dundalk" against "Dundalk FC", "Bohemian" against "Bohemians". It stays
    tight enough to keep Derry City and Cork City apart, since neither reduces
    to a bare "city".
    """
    left, right = club_key(seller), club_key(pool_club)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _build_index(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for league in report.get("leagues") or []:
        league_name = str(league.get("name") or "").strip()
        for team in league.get("teams") or []:
            team_name = str(team.get("name") or "").strip()
            for signing in team.get("signed") or []:
                key = name_key(signing.get("player"))
                if not key:
                    continue
                index.setdefault(key, []).append(
                    {
                        "club": team_name,
                        "league": league_name,
                        "from": str(signing.get("other") or "").strip(),
                        "fee": str(signing.get("fee") or "").strip(),
                        # 251 of 723 signings this window were loans. Dropping
                        # this field is what put Max Merrick — at Hartlepool on
                        # loan from Chelsea — through the permanent-move path.
                        "loan": str(signing.get("kind") or "").strip().lower() == "loan",
                    }
                )
    return index


def _report_path() -> Path | None:
    for path in TRANSFER_REPORT_CANDIDATES:
        if path.is_file():
            return path
    return None


def _load_index() -> dict[str, list[dict[str, Any]]]:
    """The signings, reread only when the report file changes on disk.

    Deliberately not tied to the standouts cache: that one takes four minutes to
    rebuild, and a transfer correction should not have to wait for it.
    """
    global _index, _index_mtime, _meta

    path = _report_path()
    if path is None:
        # Warned, not silent. An unflagged pool looks exactly like a pool with
        # no transfers in it, which is how this went unnoticed on Staging.
        logger.warning(
            "No transfer report found in %s — no players will be flagged as moved",
            ", ".join(str(p) for p in TRANSFER_REPORT_CANDIDATES),
        )
        return {}

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}

    with _lock:
        if _index is not None and _index_mtime == mtime:
            return _index
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("Could not read the transfer report — no move flags")
            _index, _index_mtime = {}, mtime
            return _index
        _index = _build_index(report)
        _index_mtime = mtime
        _meta = {
            "updated": str(report.get("updated") or "").strip(),
            "window": str(report.get("window") or "").strip(),
            "season": str(report.get("season") or "").strip(),
            "signings": len(_index),
        }
        logger.info("Transfer move index: %d players from %s", len(_index), path)
        return _index


def lookup(name: str | None, club: str | None) -> dict[str, Any] | None:
    """Where a player has moved to, or None if no move is on record.

    `club` is the club shown on the row, i.e. the one the player is being
    scouted at. It decides confidence, not whether there is a hit at all.
    """
    key = name_key(name)
    if not key:
        return None
    matches = _load_index().get(key)
    if not matches:
        return None

    # Order matters. Selling club first, so a player who moved twice is still
    # caught at his middle club.
    for record in matches:
        if _clubs_match(record.get("from"), club):
            # Left on loan is not sold. He is still their player and the loan
            # ends, so a scout needs to know he is away — not that he is gone.
            return {
                **record,
                "status": LOAN_OUT if record.get("loan") else GONE,
            }

    # Then the destination. If the row already names the club he signed for,
    # he has arrived rather than left.
    for record in matches:
        if _clubs_match(record.get("club"), club):
            if record.get("loan"):
                # Max Merrick: Hartlepool on the row, Chelsea's player. Saying
                # nothing here loses the one fact that decides whether he can be
                # signed at all, and who you would be negotiating with.
                return {**record, "status": LOAN_IN}
            # A permanent arrival: the row is simply correct.
            return None

    record = matches[0]
    if str(record.get("from") or "").strip().lower() in _NOT_A_CLUB:
        # Signed as a free agent, so there is no selling club to match the row
        # against. The move is still on record, so say so.
        return {**record, "status": GONE}
    return {**record, "status": CHECK}


def annotate(row: dict[str, Any], *, name_key_: str = "name", club_key_: str = "club") -> dict[str, Any]:
    """Attach a `transfer` block to a player row, in place, when one applies."""
    moved = lookup(row.get(name_key_), row.get(club_key_))
    if moved:
        row["transfer"] = moved
    return row


def _open_window(today: date) -> tuple[str, date] | None:
    """The window open on this date, and the day it opened."""
    for label, start, end in _WINDOWS:
        opened = date(today.year, *start)
        if opened <= today <= date(today.year, *end):
            return label, opened
    return None


def _pretty(day: date) -> str:
    return f"{day.day} {day:%B}"


def report_meta(today: date | None = None) -> dict[str, Any]:
    """What the flags rest on, in words a page can print.

    The report is built by hand: someone saves BBC and retained-list pages into
    data/efl-transfer-sources and runs the build script. Nothing fetches them, so
    the file cannot notice a new window opening on its own. Saying when it was
    last updated is the difference between a scout reading a clean row as "no
    move recorded" and reading it as "still available".
    """
    _load_index()
    meta = dict(_meta)
    if not meta:
        return {
            "available": False,
            "detail": "No transfer check — players will not be flagged as moved.",
        }

    today = today or date.today()
    try:
        updated = date.fromisoformat(meta["updated"])
    except (KeyError, ValueError):
        return {**meta, "available": True, "stale": False, "detail": ""}

    window = _open_window(today)
    if window and updated < window[1]:
        label, opened = window
        return {
            **meta,
            "available": True,
            "stale": True,
            "detail": (
                f"Transfer check last updated {_pretty(updated)}, before the {label} "
                f"window opened on {_pretty(opened)} — moves since then are missing."
            ),
        }
    return {
        **meta,
        "available": True,
        "stale": False,
        "detail": (
            f"Transfer check current to {_pretty(updated)} "
            f"({meta.get('signings') or 0} signings). Covers moves into League One, "
            "League Two, the National League and the Scottish Premiership only."
        ),
    }


def reset_cache() -> None:
    """Drop the cached index. For tests, and after rebuilding the report."""
    global _index, _index_mtime, _meta
    with _lock:
        _index, _index_mtime, _meta = None, None, {}
