"""26/27 Port Vale first-team groups and public availability facts.

The Squad Availability matrix groups players as Goalkeepers / Defenders /
Midfielders / Attackers. For 26/27 those groups follow the first-team page on
port-vale.co.uk, not Impect primary positions (Impect sends wingers and
attacking midfielders to Attackers, which mis-files several Vale players).

Snapshot taken from https://www.port-vale.co.uk/squad/70 on 22 Sep 2026.
Keaton Moseley is not on that first-team page, so he is not added here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from app.squad_photos import _normalize_name_key

SQUAD_GROUP_REVISION = "2026-09-22-club-groups"

# Display-name variants already stored on the board → club-site squad key.
ROSTER_NAME_ALIASES: dict[str, str] = {
    "rhysanthonywalters": "rhyswalters",
    "matthewcraig": "mattycraig",
}

# International window the club cited for the Northampton (26 Sep) and
# Colchester (3 Oct) postponements. Starts after Walsall (19 Sep), which
# Waine played and Walters / Simpson were unused for.
INT_WINDOW_SINCE = "2026-09-21"
INT_WINDOW_UNTIL = "2026-10-04"

# Club-site order. highlight "loan_in" matches the existing roster flag.
CLUB_FIRST_TEAM_26_27: tuple[dict[str, Any], ...] = (
    {"name": "Jackson Smith", "position_group": "GK", "highlight": None},
    {"name": "Marko Maroši", "position_group": "GK", "highlight": None},
    {"name": "Kyle John", "position_group": "DEF", "highlight": None},
    {"name": "Jaheim Headley", "position_group": "DEF", "highlight": None},
    {"name": "Jasper Moon", "position_group": "DEF", "highlight": None},
    {"name": "Connor Hall", "position_group": "DEF", "highlight": None},
    {"name": "Jordan Gabriel", "position_group": "DEF", "highlight": None},
    {"name": "Aaron McGowan", "position_group": "DEF", "highlight": None},
    {"name": "Liam Gordon", "position_group": "DEF", "highlight": None},
    {"name": "Lewis Montsma", "position_group": "DEF", "highlight": None},
    {"name": "Cameron Humphreys", "position_group": "DEF", "highlight": None},
    {"name": "Joe Williams", "position_group": "DEF", "highlight": None},
    {"name": "George Byers", "position_group": "MID", "highlight": None},
    {"name": "Ben Garrity", "position_group": "MID", "highlight": None},
    {"name": "Kyle Dempsey", "position_group": "MID", "highlight": None},
    {"name": "Onel Hernández", "position_group": "MID", "highlight": None},
    {"name": "Ryan Croasdale", "position_group": "MID", "highlight": None},
    {"name": "Jack Shorrock", "position_group": "MID", "highlight": None},
    {"name": "Maleace Asamoah", "position_group": "MID", "highlight": "loan_in"},
    {"name": "George Hall", "position_group": "MID", "highlight": None},
    {"name": "Matty Craig", "position_group": "MID", "highlight": None},
    {"name": "Rhys Walters", "position_group": "MID", "highlight": None},
    {"name": "Charlie Bussell", "position_group": "MID", "highlight": None},
    {"name": "Mo Faal", "position_group": "ATT", "highlight": "loan_in"},
    {"name": "Oliver Lynch", "position_group": "ATT", "highlight": "loan_in"},
    {"name": "Tyreece Simpson", "position_group": "ATT", "highlight": None},
    {"name": "Ben Waine", "position_group": "ATT", "highlight": None},
    {"name": "Keyrol Figueroa", "position_group": "ATT", "highlight": "loan_in"},
    {"name": "Max Watters", "position_group": "ATT", "highlight": None},
)

PUBLIC_STANDING_FACTS: tuple[dict[str, Any], ...] = (
    {
        "id": "shorrock-loan-sligo-2026",
        "names": ["Jack Shorrock"],
        "status": "LOAN",
        "since": "2026-07-28",
        "return_date": None,
        "ended_at": None,
        "notes": "Season-long loan to Sligo Rovers (from 28 Jul 2026).",
    },
    {
        "id": "faal-long-term-2026",
        "names": ["Mo Faal"],
        "status": "INJ",
        "since": "2026-08-23",
        "return_date": "2026-12-31",
        "ended_at": None,
        "notes": "Long-term. Brady indicated a return toward the end of 2026 (loan from Wrexham).",
    },
    {
        "id": "waine-nz-int-2026-09",
        "names": ["Ben Waine"],
        "status": "INT",
        "since": INT_WINDOW_SINCE,
        "return_date": INT_WINDOW_UNTIL,
        "ended_at": INT_WINDOW_UNTIL,
        "notes": (
            "New Zealand All Whites. Club cited this window for the "
            "Northampton (26 Sep) and Colchester (3 Oct) postponements."
        ),
    },
    {
        "id": "simpson-skn-int-2026-09",
        "names": ["Tyreece Simpson"],
        "status": "INT",
        "since": INT_WINDOW_SINCE,
        "return_date": INT_WINDOW_UNTIL,
        "ended_at": INT_WINDOW_UNTIL,
        "notes": "Fitness rebuilding. Saint Kitts & Nevis international duty this break.",
    },
    {
        "id": "gordon-guyana-int-2026-09",
        "names": ["Liam Gordon"],
        "status": "INT",
        "since": INT_WINDOW_SINCE,
        "return_date": INT_WINDOW_UNTIL,
        "ended_at": INT_WINDOW_UNTIL,
        "notes": "Guyana international duty this break.",
    },
    {
        "id": "figueroa-honduras-int-2026-09",
        "names": ["Keyrol Figueroa"],
        "status": "INT",
        "since": INT_WINDOW_SINCE,
        "return_date": INT_WINDOW_UNTIL,
        "ended_at": INT_WINDOW_UNTIL,
        "notes": "Honduras international duty this break (loan from Liverpool, 1 Sep 2026).",
    },
    {
        "id": "smith-walsall-concussion-2026-09-19",
        "names": ["Jackson Smith"],
        "status": "INJ",
        "since": "2026-09-19",
        "return_date": "2026-09-20",
        "ended_at": "2026-09-19",
        "notes": "Concussion protocol — missed Walsall (19 Sep).",
    },
)

# Unused-bench games. A one-time clear so these cells are not left as INT or INJ.
# Played minutes still win over this manual N in the matrix.
PUBLIC_MATCH_FACTS: tuple[dict[str, Any], ...] = (
    {
        "id": "walters-salford-unused-2026-09-05",
        "names": ["Rhys Walters", "Rhys Anthony Walters"],
        "date": "2026-09-05",
        "opponent_contains": "salford",
        "status": "N",
    },
    {
        "id": "walters-exeter-unused-2026-09-12",
        "names": ["Rhys Walters", "Rhys Anthony Walters"],
        "date": "2026-09-12",
        "opponent_contains": "exeter",
        "status": "N",
    },
)


def canonical_roster_key(name: str) -> str:
    key = _normalize_name_key(name)
    return ROSTER_NAME_ALIASES.get(key, key)


def position_group_for_name(name: str) -> str | None:
    target = canonical_roster_key(name)
    for row in CLUB_FIRST_TEAM_26_27:
        if canonical_roster_key(str(row["name"])) == target:
            return str(row["position_group"])
    return None


def injury_badge(injury: dict[str, Any] | None, *, today: date) -> dict[str, Any] | None:
    """Current spell for the name badge. A spell that has already ended stays on cells only."""
    if not isinstance(injury, dict):
        return None
    status = str(injury.get("status") or "").upper()
    if not status or status == "AVAIL":
        return None
    ended = _parse_iso_date(injury.get("ended_at"))
    if ended is not None and ended < today:
        return None
    return injury


def reconcile_26_27_roster(store: dict[str, Any], roster: list[dict[str, Any]]) -> bool:
    """Apply club-site groups once, then any public standing spells not yet recorded.

    Group correction is one-shot so a later Sync squad from port-vale.co.uk can
    move players if the club page changes. Standing facts are also one-shot per
    id, so staff edits after that are kept.
    """
    changed = False
    revisions = store.setdefault("squad_group_revision", {})
    if not isinstance(revisions, dict):
        revisions = {}
        store["squad_group_revision"] = revisions
    if revisions.get("26/27") != SQUAD_GROUP_REVISION:
        if _apply_club_groups(roster):
            changed = True
        revisions["26/27"] = SQUAD_GROUP_REVISION
        changed = True
    if _apply_standing_facts(store, roster):
        changed = True
    return changed


def apply_public_match_facts(
    store: dict[str, Any],
    roster: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
) -> bool:
    """Pin unused-bench matches to N when a saved INT/INJ would mis-state them."""
    changed = False
    applied = _applied_facts(store)
    stored_sessions = _stored_sessions(store)
    for fact in PUBLIC_MATCH_FACTS:
        fact_id = str(fact["id"])
        if fact_id in applied:
            continue
        player = _find_roster_player(roster, list(fact["names"]))
        if player is None:
            continue
        matched = [
            session
            for session in sessions
            if _session_matches_fact(session, fact)
        ]
        if not matched:
            continue
        player_id = str(player["id"])
        status = str(fact["status"])
        for session in matched:
            stored = _stored_session_for(stored_sessions, session)
            if stored is None:
                stored = {
                    "id": str(session.get("id") or f"s-{uuid.uuid4().hex[:10]}"),
                    "type": "match",
                    "date": str(session.get("date") or "")[:10],
                    "label": session.get("label") or session.get("date"),
                    "match_id": session.get("match_id"),
                    "match_category": session.get("match_category") or "league",
                    "opponent": session.get("opponent") or "",
                    "venue": session.get("venue") or "",
                    "entries": {},
                }
                stored_sessions.append(stored)
                changed = True
            entries = stored.setdefault("entries", {})
            if not isinstance(entries, dict):
                entries = {}
                stored["entries"] = entries
            current = str((entries.get(player_id) or {}).get("status") or "").upper()
            if current != status:
                entries[player_id] = {"status": status}
                changed = True
            session_entries = session.setdefault("entries", {})
            if not isinstance(session_entries, dict):
                session_entries = {}
                session["entries"] = session_entries
            session_entries[player_id] = {"status": status}
        applied[fact_id] = _now_iso()
        changed = True
    return changed


def _apply_club_groups(roster: list[dict[str, Any]]) -> bool:
    changed = False
    for index, row in enumerate(CLUB_FIRST_TEAM_26_27):
        name = str(row["name"])
        position_group = str(row["position_group"])
        highlight = row.get("highlight")
        existing = _find_roster_player(roster, [name])
        if existing is None:
            roster.append(
                {
                    "id": f"p-{uuid.uuid4().hex[:10]}",
                    "name": name,
                    "position_group": position_group,
                    "sort_order": index,
                    "impect_id": None,
                    "highlight": highlight,
                    "active": True,
                }
            )
            changed = True
            continue
        if existing.get("position_group") != position_group:
            existing["position_group"] = position_group
            changed = True
        if existing.get("sort_order") != index:
            existing["sort_order"] = index
            changed = True
        if existing.get("active", True) is False:
            existing["active"] = True
            changed = True
        if highlight and not existing.get("highlight"):
            existing["highlight"] = highlight
            changed = True
    return changed


def _apply_standing_facts(store: dict[str, Any], roster: list[dict[str, Any]]) -> bool:
    changed = False
    applied = _applied_facts(store)
    injuries = _injury_bucket(store)
    history = _history_bucket(store)
    for fact in PUBLIC_STANDING_FACTS:
        fact_id = str(fact["id"])
        if fact_id in applied:
            continue
        player = _find_roster_player(roster, list(fact["names"]))
        if player is None:
            continue
        player_id = str(player["id"])
        since = str(fact["since"])[:10]
        ended_at = fact.get("ended_at")
        ended_at = str(ended_at)[:10] if ended_at else None
        notes = str(fact.get("notes") or "")
        status = str(fact["status"])
        records = history.setdefault(player_id, [])
        if not isinstance(records, list):
            records = []
            history[player_id] = records
        _close_open_record(records, since)
        injuries[player_id] = {
            "status": status,
            "return_date": fact.get("return_date"),
            "notes": notes,
            "since": since,
            "ended_at": ended_at,
            "away_from_club": False,
        }
        records.append(
            {
                "id": f"ih-{uuid.uuid4().hex[:10]}",
                "status": status,
                "since": since,
                "return_date": fact.get("return_date"),
                "ended_at": ended_at,
                "notes": notes,
                "away_from_club": False,
                "recorded_at": _now_iso(),
            }
        )
        applied[fact_id] = _now_iso()
        changed = True
    return changed


def _find_roster_player(roster: list[dict[str, Any]], names: list[str]) -> dict[str, Any] | None:
    targets = {canonical_roster_key(name) for name in names}
    raw_targets = {_normalize_name_key(name) for name in names}
    matches: list[dict[str, Any]] = []
    for player in roster:
        if not isinstance(player, dict):
            continue
        player_name = str(player.get("name") or "")
        if canonical_roster_key(player_name) in targets or _normalize_name_key(player_name) in raw_targets:
            matches.append(player)
    if not matches:
        return None
    active = [player for player in matches if player.get("active", True) is not False]
    return active[0] if active else matches[0]


def _applied_facts(store: dict[str, Any]) -> dict[str, Any]:
    applied = store.setdefault("public_status_facts", {})
    if not isinstance(applied, dict):
        applied = {}
        store["public_status_facts"] = applied
    return applied


def _injury_bucket(store: dict[str, Any]) -> dict[str, Any]:
    root = store.setdefault("injuries", {})
    if not isinstance(root, dict):
        root = {}
        store["injuries"] = root
    bucket = root.setdefault("26/27", {})
    if not isinstance(bucket, dict):
        bucket = {}
        root["26/27"] = bucket
    return bucket


def _history_bucket(store: dict[str, Any]) -> dict[str, Any]:
    root = store.setdefault("injury_history", {})
    if not isinstance(root, dict):
        root = {}
        store["injury_history"] = root
    bucket = root.setdefault("26/27", {})
    if not isinstance(bucket, dict):
        bucket = {}
        root["26/27"] = bucket
    return bucket


def _stored_sessions(store: dict[str, Any]) -> list[dict[str, Any]]:
    root = store.setdefault("sessions", {})
    if not isinstance(root, dict):
        root = {}
        store["sessions"] = root
    bucket = root.get("26/27")
    if not isinstance(bucket, list):
        bucket = []
        root["26/27"] = bucket
    return bucket


def _session_matches_fact(session: dict[str, Any], fact: dict[str, Any]) -> bool:
    if str(session.get("type") or "match") != "match":
        return False
    if str(session.get("date") or "")[:10] != str(fact["date"]):
        return False
    blob = f"{session.get('opponent') or ''} {session.get('label') or ''}".casefold()
    return str(fact["opponent_contains"]).casefold() in blob


def _stored_session_for(
    stored_sessions: list[dict[str, Any]],
    session: dict[str, Any],
) -> dict[str, Any] | None:
    match_id = session.get("match_id")
    session_date = str(session.get("date") or "")[:10]
    label = str(session.get("label") or "").casefold()
    opponent = str(session.get("opponent") or "").casefold()
    for row in stored_sessions:
        if not isinstance(row, dict):
            continue
        if match_id is not None and row.get("match_id") is not None and int(row["match_id"]) == int(match_id):
            return row
        if str(row.get("date") or "")[:10] != session_date:
            continue
        row_blob = f"{row.get('opponent') or ''} {row.get('label') or ''}".casefold()
        if opponent and opponent in row_blob:
            return row
        if label and label in row_blob:
            return row
    return None


def _close_open_record(records: list[dict[str, Any]], ended_at: str) -> None:
    for record in reversed(records):
        if isinstance(record, dict) and not record.get("ended_at"):
            record["ended_at"] = ended_at[:10]
            return


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
