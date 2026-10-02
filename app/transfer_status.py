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
from app.paths import DATA_ROOT, HUB_ROOT
from app.player_identity import identity_keys, name_key, name_keys, same_person

logger = logging.getLogger(__name__)

# Deliberately the same candidate list the report page uses, not a path of our
# own. On the server DATA_ROOT is the mounted volume while the report ships
# inside the image at HUB_ROOT/data, so picking one of the two silently found
# nothing on Staging and every player came back unflagged.
TRANSFER_REPORT_CANDIDATES = REPORT_CANDIDATES

LOAN_SNAPSHOT_NAME = "transfermarkt-loans-2026.json"
LOAN_SNAPSHOT_CANDIDATES = (
    HUB_ROOT / "data" / LOAN_SNAPSHOT_NAME,
    DATA_ROOT / LOAN_SNAPSHOT_NAME,
)

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
_by_surname: dict[str, list[dict[str, Any]]] | None = None
_index_mtime: float | None = None
_meta: dict[str, Any] = {}
_loan_snapshot: dict[str, Any] | None = None
_loan_snapshot_mtime: float | None = None


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


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


def _surname(value: str | None) -> str:
    parts = name_key(value).split()
    return parts[-1] if len(parts) >= 2 else ""


def _index_record(
    index: dict[str, list[dict[str, Any]]],
    by_surname: dict[str, list[dict[str, Any]]],
    name: str,
    record: dict[str, Any],
) -> None:
    stored = {**record, "player": str(name or "").strip()}
    keys = identity_keys(name)
    if not keys:
        return
    bucket = index.setdefault(keys[0], [])
    bucket.append(stored)
    for key in keys[1:]:
        current = index.get(key)
        if current is None:
            index[key] = bucket
        elif current is not bucket and stored not in current:
            current.append(stored)
    last = _surname(name)
    if last:
        by_surname.setdefault(last, []).append(stored)


def _build_index(
    report: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    by_surname: dict[str, list[dict[str, Any]]] = {}
    for league in report.get("leagues") or []:
        league_name = str(league.get("name") or "").strip()
        for team in league.get("teams") or []:
            team_name = str(team.get("name") or "").strip()
            for signing in team.get("signed") or []:
                _index_record(
                    index,
                    by_surname,
                    signing.get("player"),
                    {
                        "club": team_name,
                        "league": league_name,
                        "from": str(signing.get("other") or "").strip(),
                        "fee": str(signing.get("fee") or "").strip(),
                        # 251 of 723 signings this window were loans. Dropping
                        # this field is what put Max Merrick — at Hartlepool on
                        # loan from Chelsea — through the permanent-move path.
                        "loan": str(signing.get("kind") or "").strip().lower() == "loan",
                    },
                )
            for departure in team.get("left") or []:
                # Moves to clubs outside the report (Championship, abroad) never
                # appear as a signing. The selling club still knows they left.
                _index_record(
                    index,
                    by_surname,
                    departure.get("player"),
                    {
                        "club": str(departure.get("other") or "").strip(),
                        "league": league_name,
                        "from": team_name,
                        "fee": str(departure.get("fee") or "").strip(),
                        "loan": str(departure.get("kind") or "").strip().lower() == "loan",
                    },
                )
    return index, by_surname


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
    global _index, _by_surname, _index_mtime, _meta

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
            _index, _by_surname, _index_mtime = {}, {}, mtime
            return _index
        _index, _by_surname = _build_index(report)
        _index_mtime = mtime
        seen_records: set[int] = set()
        for bucket in _index.values():
            for record in bucket:
                seen_records.add(id(record))
        _meta = {
            "updated": str(report.get("updated") or "").strip(),
            "window": str(report.get("window") or "").strip(),
            "season": str(report.get("season") or "").strip(),
            "signings": len(seen_records),
        }
        logger.info("Transfer move index: %d players from %s", len(seen_records), path)
        return _index


def _parent_unknown(value: str | None) -> bool:
    text = str(value or "").strip().casefold()
    return not text or text in _NOT_A_CLUB or text == "loan"


def parent_label(value: str | None) -> str:
    """Parent club for a loan line. Unknown stays unknown — never a guessed club."""
    text = str(value or "").strip()
    if _parent_unknown(text):
        return "unknown"
    return text


def lookup(name: str | None, club: str | None) -> dict[str, Any] | None:
    """Where a player has moved to, or None if no move is on record.

    `club` is the club shown on the row, i.e. the one the player is being
    scouted at. It decides confidence, not whether there is a hit at all.
    """
    status, _matched = _resolve(name, club)
    return _with_display(club, status)


def _records_for_name(name: str | None) -> list[dict[str, Any]]:
    """Transfer rows for this spelling, including Nick / Nicholas.

    Exact and canonical keys win. A surname scan is only the fallback, and it
    still requires the first names to be the same person — a shared surname
    alone is not a join.
    """
    index = _load_index()
    found: list[dict[str, Any]] = []
    seen: set[int] = set()

    def take(records: list[dict[str, Any]] | None) -> None:
        for record in records or []:
            marker = id(record)
            if marker in seen:
                continue
            seen.add(marker)
            found.append(record)

    for key in identity_keys(name):
        take(index.get(key))
    if found:
        return found

    last = _surname(name)
    if not last or _by_surname is None:
        return []
    for record in _by_surname.get(last) or []:
        if same_person(name, record.get("player")):
            take([record])
    return found


def _status_from_records(
    records: list[dict[str, Any]],
    club: str | None,
) -> tuple[dict[str, Any] | None, bool]:
    """A row's status, plus whether a club actually matched."""
    if not records:
        return None, False

    # Order matters. Selling club first, so a player who moved twice is still
    # caught at his middle club.
    for record in records:
        if _clubs_match(record.get("from"), club):
            # Left on loan is not sold. He is still their player and the loan
            # ends, so a scout needs to know he is away — not that he is gone.
            return {
                **record,
                "status": LOAN_OUT if record.get("loan") else GONE,
            }, True

    # Then the destination. If the row already names the club he signed for,
    # he has arrived rather than left.
    for record in records:
        if _clubs_match(record.get("club"), club):
            if record.get("loan"):
                # Max Merrick: Hartlepool on the row, Chelsea's player. Saying
                # nothing here loses the one fact that decides whether he can be
                # signed at all, and who you would be negotiating with.
                return {**record, "status": LOAN_IN}, True
            # A permanent arrival: the row is simply correct. Still a positive
            # identification, which is what clears his namesakes.
            return None, True

    record = records[0]
    if record.get("loan") and _parent_unknown(record.get("from")):
        # A loan whose parent club never arrived. Say so. Do not invent a
        # permanent move to the destination.
        return {**record, "from": "", "status": LOAN_IN}, False
    if str(record.get("from") or "").strip().lower() in _NOT_A_CLUB:
        # Signed as a free agent, so there is no selling club to match the row
        # against. The move is still on record, so say so.
        return {**record, "status": GONE}, False
    return {**record, "status": CHECK}, False


def _resolve(
    name: str | None,
    club: str | None,
    extra_records: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    """A row's status, plus whether a club actually matched.

    That second value is what lets a caller settle namesakes. If some other
    player of the same name matched the record's club, this row is demonstrably
    not the man who moved.

    `extra_records` are moves already tied to this Impect id by another
    spelling. The row's own club still decides the colour.
    """
    records = _merge_records(extra_records or [], _records_for_name(name))
    return _status_from_records(records, club)


def _merge_records(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[int] = set()
    for group in groups:
        for record in group:
            marker = id(record)
            if marker in seen:
                continue
            seen.add(marker)
            merged.append(record)
    return merged


def _as_player_id(row: dict[str, Any]) -> int | None:
    for key in ("player_id", "playerId"):
        raw = row.get(key)
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def present_scout_club(
    row: dict[str, Any],
    *,
    club_key_: str = "club",
) -> dict[str, Any] | None:
    """How a scout table should paint this row.

    Loans always read as the playing club plus `on loan from {parent}`. A row
    keyed by the parent or U21 side is the same sentence — the destination is
    the held club, not `on loan at {destination}`.

    Red is only a permanent move whose data club is not the club he is
    registered at now. The same player in another section, already at that
    club, stays uncoloured.
    """
    move = row.get("transfer") or {}
    if not isinstance(move, dict):
        return None
    status = str(move.get("status") or "")
    data_club = str(row.get(club_key_) or "").strip()
    destination = str(move.get("club") or "").strip()
    parent = parent_label(move.get("from"))
    league = str(move.get("league") or "").strip()
    where = f"{destination}{f' ({league})' if league else ''}"

    if status in LOAN_STATUSES:
        held = destination if status == LOAN_OUT and destination else (data_club or destination)
        parent_text = parent or "unknown"
        return {
            "css": "is-loan",
            "held_club": held or "—",
            "line": f"on loan from {parent_text}",
            "line_class": "club-loan",
            "struck": False,
            "parent": parent_text,
            "title": (
                f"On loan from {parent_text}, playing for {held or 'the current club'}. "
                f"Any deal is with {parent_text}."
            ),
        }

    if status == GONE and destination:
        fee = str(move.get("fee") or "").strip()
        bits = [f"Signed for {where}"]
        origin = str(move.get("from") or "").strip()
        if origin:
            bits.append(f"from {origin}")
        if fee:
            bits.append(fee)
        return {
            "css": "is-moved",
            "held_club": data_club or "—",
            "line": destination,
            "line_class": "club-now",
            "struck": True,
            "title": " · ".join(bits),
        }

    if status == CHECK and destination:
        origin = str(move.get("from") or "").strip()
        from_bit = f" from {origin}" if origin else ""
        return {
            "css": "is-move-check",
            "held_club": data_club or "—",
            "line": f"{destination}?",
            "line_class": "club-now club-now--check",
            "struck": False,
            "title": (
                f"A player of this name signed for {where}{from_bit}"
                " — check it is the same player before ruling him out"
            ),
        }
    return None


def _with_display(club: str | None, status: dict[str, Any] | None) -> dict[str, Any] | None:
    if not status:
        return None
    probe = {"club": club, "transfer": dict(status)}
    display = present_scout_club(probe)
    if display:
        probe["transfer"]["display"] = display
    return probe["transfer"]


def annotate(row: dict[str, Any], *, name_key_: str = "name", club_key_: str = "club") -> dict[str, Any]:
    """Attach a `transfer` block to a player row, in place, when one applies.

    Prefer `annotate_all` where the surrounding squad is available: on its own a
    row cannot tell a namesake from the real thing.
    """
    moved = lookup(row.get(name_key_), row.get(club_key_))
    if moved:
        row["transfer"] = moved
    return row


def annotate_all(
    rows: list[dict[str, Any]],
    *,
    name_key_: str = "name",
    club_key_: str = "club",
    roster: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Annotate a squad, using the squad itself to settle namesakes.

    Two players can share a name exactly. The pool holds two Cameron Humphreys:
    ours at 28, and a 22-year-old at Huddersfield on loan from Ipswich. A name
    is not enough to tell them apart, so both used to be flagged — the young one
    correctly, ours as an amber "check" on a player who is not going anywhere.

    But if one of them positively matches the record's club, the other is
    demonstrably not the man in it. That was true of every shared name in the
    pool: five names, five ambers, all on the wrong player, two of them ours.
    Amber is for genuine doubt, and this is not doubt — it is an answer.

    Only "check" is cleared this way. A confirmed move stays put, because the
    evidence for it never rested on the name alone.
    """
    pool = roster if roster is not None else rows
    by_id: dict[int, list[dict[str, Any]]] = {}

    def absorb(row: dict[str, Any]) -> None:
        player_id = _as_player_id(row)
        if player_id is None:
            return
        found = _records_for_name(row.get(name_key_))
        if not found:
            return
        bucket = by_id.setdefault(player_id, [])
        by_id[player_id] = _merge_records(bucket, found)

    for row in pool:
        absorb(row)
    if roster is not None:
        for row in rows:
            absorb(row)

    identified: set[str] = set()
    for row in pool:
        key = name_key(row.get(name_key_))
        if not key or key in identified:
            continue
        if _resolve(row.get(name_key_), row.get(club_key_))[1]:
            identified.add(key)

    for row in rows:
        player_id = _as_player_id(row)
        extra = by_id.get(player_id) if player_id is not None else None
        status, matched = _resolve(row.get(name_key_), row.get(club_key_), extra)
        if status is None:
            row.pop("transfer", None)
            continue
        if (
            status["status"] == CHECK
            and not matched
            and name_key(row.get(name_key_)) in identified
        ):
            row.pop("transfer", None)
            continue
        attached = _with_display(row.get(club_key_), status)
        if attached:
            row["transfer"] = attached
        else:
            row.pop("transfer", None)
    return rows


def _loan_entries(payload: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    values: list[Any]
    if isinstance(payload, dict):
        values = list(payload.values())
    elif isinstance(payload, list):
        values = payload
    else:
        return rows
    for item in values:
        if not isinstance(item, dict):
            continue
        player = str(item.get("name") or "").strip()
        parent = str(item.get("on_loan_from") or item.get("from") or "").strip()
        if player and parent:
            rows.append({"name": player, "from": parent})
    return rows


def _match_loan_name(player: str, maps: list[list[dict[str, str]]]) -> dict[str, str] | None:
    keys = set(identity_keys(player))
    last = name_key(player).split()[-1] if name_key(player) else ""
    last_hits: list[dict[str, str]] = []
    for entries in maps:
        for entry in entries:
            if set(identity_keys(entry.get("name"))) & keys or same_person(player, entry.get("name")):
                return entry
            entry_last = name_key(entry.get("name")).split()[-1] if name_key(entry.get("name")) else ""
            if last and entry_last == last:
                last_hits.append(entry)
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for hit in last_hits:
        stamp = name_key(hit.get("name"))
        if stamp in seen:
            continue
        seen.add(stamp)
        unique.append(hit)
    return unique[0] if len(unique) == 1 else None


def apply_loan_ins(
    rows: list[dict[str, Any]],
    loans_by_club: dict[str, Any] | None,
    *,
    name_key_: str = "name",
    club_key_: str = "club",
) -> int:
    """Fill loan_in from Transfermarkt when the hand-built report has no move.

    Ramell Carter sat on the Watch list as a Worthing striker. Hull U21 to
    National League never made the BBC/retained-list pages the report is built
    from, so the report had nothing to flag. Transfermarkt's squad badge does.
    A confirmed sale still wins: we do not paint a gone player as a loanee.
    """
    normalized: dict[str, list[dict[str, str]]] = {}
    for club, payload in (loans_by_club or {}).items():
        label = str(club or "").strip()
        entries = _loan_entries(payload)
        if label and entries:
            normalized[label] = entries

    flagged = 0
    protected = {GONE, LOAN_IN, LOAN_OUT}
    for row in rows:
        existing = row.get("transfer") or {}
        if existing.get("status") in protected:
            continue
        club = str(row.get(club_key_) or "").strip()
        player = str(row.get(name_key_) or "").strip()
        if not club or not player:
            continue
        maps = [
            entries
            for key, entries in normalized.items()
            if key == club or _clubs_match(key, club)
        ]
        hit = _match_loan_name(player, maps)
        if not hit:
            continue
        row["transfer"] = {
            "club": club,
            "from": hit["from"],
            "loan": True,
            "status": LOAN_IN,
            "fee": "Loan",
        }
        flagged += 1
    return flagged


def load_loan_snapshot() -> dict[str, Any]:
    """Shipped Transfermarkt loan badges. Built on the Mac; the droplet cannot fetch them."""
    global _loan_snapshot, _loan_snapshot_mtime
    path = next((candidate for candidate in LOAN_SNAPSHOT_CANDIDATES if candidate.is_file()), None)
    if path is None:
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _loan_snapshot is not None and _loan_snapshot_mtime == mtime:
            return _loan_snapshot
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("Could not read Transfermarkt loan snapshot")
            _loan_snapshot, _loan_snapshot_mtime = {}, mtime
            return _loan_snapshot
        clubs = payload.get("clubs") if isinstance(payload, dict) else {}
        _loan_snapshot = clubs if isinstance(clubs, dict) else {}
        _loan_snapshot_mtime = mtime
        return _loan_snapshot


def annotate_transfermarkt_loans(
    rows: list[dict[str, Any]],
    *,
    name_key_: str = "name",
    club_key_: str = "club",
    timeout_s: float = 8.0,
    squad_only: bool = True,
) -> int:
    """Look up Transfermarkt loan badges for the clubs on these rows."""
    from concurrent.futures import ThreadPoolExecutor, wait

    from app.opponent_photos import transfermarkt_loan_ins

    clubs = sorted(
        {
            str(row.get(club_key_) or "").strip()
            for row in rows
            if str(row.get(club_key_) or "").strip()
        }
    )
    if not clubs:
        return 0
    loans_by_club: dict[str, Any] = {}
    workers = min(8, len(clubs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(transfermarkt_loan_ins, club, squad_only=squad_only): club
            for club in clubs
        }
        done, _pending = wait(futures, timeout=timeout_s)
        for fut in done:
            club = futures[fut]
            try:
                loans_by_club[club] = fut.result() or {}
            except Exception:
                logger.exception("Transfermarkt loans failed for %s", club)
    return apply_loan_ins(rows, loans_by_club, name_key_=name_key_, club_key_=club_key_)


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
    global _index, _by_surname, _index_mtime, _meta
    with _lock:
        _index, _by_surname, _index_mtime, _meta = None, None, None, {}
