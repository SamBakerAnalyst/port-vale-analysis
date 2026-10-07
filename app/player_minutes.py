"""Minutes at the club a player is at now, shared by every scout page.

Loans Watch, Who To Scout and the Watch list used to add up different sets of
rows for the same loanee: every club he had ever appeared for, or only the
position the profile score was built on. This module is the one filter.

`aggregate_player_minutes` keeps rows whose canonical club id is the club being
asked about and whose season window is that competition's window. A parent-club
row (transfer status loan_out) and a previous club's calendar season are not
part of the total. The listed position and its minutes come from those rows
only, so profile minutes cannot exceed the total.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.club_identity import canonical_club_id, same_club
from app.season_defaults import CURRENT_SEASON
from app import transfer_status

LOAN_OUT = "loan_out"

_SPLIT_SEASON = re.compile(r"^(?:20)?(\d{2})\s*[/\-]\s*(?:20)?(\d{2})$")
_CALENDAR_SEASON = re.compile(r"^(20\d{2})$")


def season_window_id(value: str | None) -> str | None:
    """'26/27' and '2026/27' are one window. A calendar '2026' is a different one."""
    text = re.sub(r"\s+", "", str(value or "")).strip()
    if not text:
        return None
    split = _SPLIT_SEASON.match(text)
    if split:
        return f"split:{int(split.group(1)):02d}"
    calendar = _CALENDAR_SEASON.match(text)
    if calendar:
        return f"calendar:{calendar.group(1)}"
    return None


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return number


def _player_id(row: dict[str, Any]) -> int | None:
    return _as_int(row.get("playerId") if "playerId" in row else row.get("player_id"))


def _edit_distance(left: str, right: str) -> int:
    if abs(len(left) - len(right)) > 2:
        return 99
    previous = list(range(len(right) + 1))
    for i, ch in enumerate(left, start=1):
        current = [i]
        for j, other in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (ch != other),
                )
            )
        previous = current
    return previous[-1]


def _first_and_rest(value: str | None) -> tuple[str, str]:
    parts = transfer_status.name_key(value).split()
    if len(parts) < 2:
        return "", ""
    return parts[0], " ".join(parts[1:])


# Short forms that are not a prefix of the long form ("Nick" / "Nicholas",
# "Ollie" / "Oliver"). This is spelling, not a list of players.
_FIRST_NAME_FORMS = {
    "nick": "nicholas",
    "nicholas": "nicholas",
    "nicky": "nicholas",
    "ollie": "oliver",
    "oliver": "oliver",
    "olly": "oliver",
    "oli": "oliver",
    "ruiri": "ruari",
    "ruari": "ruari",
}


def _first_form(token: str) -> str:
    return _FIRST_NAME_FORMS.get(token, token)


def same_player_name(left: str | None, right: str | None) -> bool:
    """Nick / Nicholas, Ollie / Oliver, Ruiri / Ruari. Not two different surnames.

    A shared surname is not enough. The first names have to be the same word,
    a known short form, a real prefix (at least four letters), or one letter apart.
    """
    left_keys = set(transfer_status.name_keys(left))
    right_keys = set(transfer_status.name_keys(right))
    if left_keys and left_keys & right_keys:
        return True
    left_first, left_rest = _first_and_rest(left)
    right_first, right_rest = _first_and_rest(right)
    if not left_rest or left_rest != right_rest or not left_first or not right_first:
        return False
    if _first_form(left_first) == _first_form(right_first):
        return True
    short, long = (
        (left_first, right_first)
        if len(left_first) <= len(right_first)
        else (right_first, left_first)
    )
    if len(short) >= 4 and long.startswith(short):
        return True
    return len(left_first) >= 4 and len(right_first) >= 4 and _edit_distance(left_first, right_first) <= 1


def _is_loan_out(row: dict[str, Any]) -> bool:
    transfer = row.get("transfer") if isinstance(row.get("transfer"), dict) else {}
    return str(transfer.get("status") or "") == LOAN_OUT


def _position_code(row: dict[str, Any]) -> str:
    return str(row.get("position") or row.get("positionLabel") or "").strip()


def _position_label(row: dict[str, Any], code: str) -> str:
    label = str(row.get("positionLabel") or row.get("position_label") or "").strip()
    return label or code


def _competition_key(row: dict[str, Any]) -> str:
    for key in ("competitionId", "iterationId", "iteration_id"):
        raw = row.get(key)
        if raw not in (None, ""):
            return str(raw)
    ident = str(row.get("id") or "")
    if ":" in ident:
        return ident.split(":", 1)[0]
    return ""


def choose_season_window(rows: list[dict[str, Any]], club_id: str) -> str | None:
    """The window to add up. Never a mix of calendar-year and split-season rows."""
    found: list[str] = []
    for row in rows:
        if not same_club(str(row.get("club") or ""), club_id):
            continue
        if _is_loan_out(row):
            continue
        window = season_window_id(str(row.get("season") or ""))
        if window:
            found.append(window)
    if not found:
        return None
    preferred = season_window_id(CURRENT_SEASON)
    if preferred and preferred in found:
        return preferred
    unique = set(found)
    if len(unique) == 1:
        return next(iter(unique))
    # Two families at one club and neither is the current split season: do not add them.
    return preferred if preferred in unique else None


def _count_across_competitions(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> int | None:
    """Real appearances. Max inside one competition, then add competitions (league + cups)."""
    buckets: dict[str, int] = {}
    loose: list[int] = []
    for row in rows:
        number = None
        for key in keys:
            number = _as_int(row.get(key))
            if number is not None and number >= 0:
                break
        if number is None:
            continue
        competition = _competition_key(row)
        if competition:
            buckets[competition] = max(buckets.get(competition, 0), number)
        else:
            loose.append(number)
    if buckets:
        return sum(buckets.values())
    if not loose:
        return None
    # No competition id: the same total is often repeated on every position row.
    return max(loose)


def aggregate_player_minutes(
    rows: list[dict[str, Any]],
    club_id: str | None,
    season_window: str | None = None,
    *,
    position: str | None = None,
) -> dict[str, Any]:
    """Minutes for one player at one club in one season window.

    `total` is every position at that club (league and cups). `profile_minutes`
    is the listed position: the caller's position, or the position with the
    most minutes when the caller does not name one. Both are None when this
    club has no rows in the window — a parent club's minutes are not borrowed.
    """
    wanted = canonical_club_id(club_id)
    window = season_window_id(season_window) if season_window else None
    if window is None and wanted:
        window = choose_season_window(rows, wanted)

    parent_minutes = 0
    parent_seen = False
    at_club: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        minutes = _as_int(row.get("minutes"))
        if _is_loan_out(row):
            parent_seen = True
            if minutes:
                parent_minutes += minutes
            continue
        if wanted and not same_club(str(row.get("club") or ""), wanted):
            continue
        at_club.append(row)

    dated = [row for row in at_club if season_window_id(str(row.get("season") or ""))]
    if dated:
        if window is None and wanted:
            window = choose_season_window(at_club, wanted)
        # Two season families (a calendar year and a split season) are never added together.
        if window is None:
            filtered = []
        else:
            filtered = [
                row
                for row in at_club
                if season_window_id(str(row.get("season") or "")) == window
            ]
    else:
        filtered = at_club

    by_code: dict[str, int] = {}
    labels: dict[str, str] = {}
    for row in filtered:
        minutes = _as_int(row.get("minutes"))
        if minutes is None:
            continue
        code = _position_code(row) or "UNKNOWN"
        by_code[code] = by_code.get(code, 0) + max(0, minutes)
        if code not in labels:
            labels[code] = _position_label(row, code)

    by_position = [
        {"position": code, "label": labels.get(code) or code, "minutes": mins}
        for code, mins in by_code.items()
        if mins > 0
    ]
    by_position.sort(key=lambda item: (-int(item["minutes"]), str(item["position"])))

    if not by_position:
        return {
            "total": None,
            "profile_minutes": None,
            "position": "",
            "position_label": "",
            "by_position": [],
            "appearances": None,
            "starts": None,
            "appearances_estimated": False,
            "starts_estimated": False,
            "parent_minutes": parent_minutes if parent_seen else None,
            "season_window": window,
            "club_id": wanted,
            "rows": [],
        }

    total = sum(int(item["minutes"]) for item in by_position)
    wanted_position = str(position or "").strip()
    if wanted_position:
        listed = next((item for item in by_position if item["position"] == wanted_position), None)
        if listed is None:
            profile_minutes = 0
            listed_code = wanted_position
            listed_label = wanted_position
        else:
            profile_minutes = int(listed["minutes"])
            listed_code = str(listed["position"])
            listed_label = str(listed["label"])
    else:
        listed = by_position[0]
        profile_minutes = int(listed["minutes"])
        listed_code = str(listed["position"])
        listed_label = str(listed["label"])

    appearances = _count_across_competitions(
        filtered,
        ("matchCount", "matches", "numberOfMatches", "games", "appearances", "matchAppearances"),
    )
    starts = _count_across_competitions(
        filtered,
        ("starts", "gamesStarted", "numberOfStarts", "startingAppearances", "matchesStarted"),
    )
    appearances_estimated = False
    starts_estimated = False
    if appearances is None and total > 0:
        appearances = max(1, int(round(total / 90.0)))
        appearances_estimated = True
    if starts is None and appearances is not None and total > 0:
        from app.loans_watch import infer_starts

        starts, starts_estimated = infer_starts(total, appearances, None)

    return {
        "total": total,
        "profile_minutes": profile_minutes,
        "position": listed_code,
        "position_label": listed_label,
        "by_position": by_position,
        "appearances": appearances,
        "starts": starts,
        "appearances_estimated": appearances_estimated,
        "starts_estimated": bool(starts_estimated),
        "parent_minutes": parent_minutes if parent_seen else None,
        "season_window": window,
        "club_id": wanted,
        "rows": filtered,
    }


def target_is_loanee(row: dict[str, Any]) -> bool:
    """True when this watch-list row is a current loan, in either direction."""
    status = str((row.get("transfer") or {}).get("status") or "")
    if status in {transfer_status.LOAN_IN, transfer_status.LOAN_OUT}:
        return True
    found = transfer_status.lookup(row.get("name"), row.get("club"))
    return bool(found and str(found.get("status") or "") in transfer_status.LOAN_STATUSES)


def apply_scoped_minutes(
    row: dict[str, Any],
    stat_rows: list[dict[str, Any]],
    *,
    feed_loaded: bool = True,
) -> bool:
    """Replace frozen watch-list minutes with the shared club/season total.

    An empty feed (the cache failed to load) leaves the row alone. A loaded
    feed with no rows at this club clears the frozen number and flags it.
    """
    if not feed_loaded or row.get("manual") or not row.get("player_id"):
        return False
    try:
        player_id = int(row.get("player_id") or 0)
    except (TypeError, ValueError):
        return False
    if player_id <= 0:
        return False
    name = str(row.get("name") or "")
    own: list[dict[str, Any]] = []
    for stat in stat_rows:
        if not isinstance(stat, dict):
            continue
        raw_id = stat.get("playerId") if stat.get("playerId") not in (None, "") else stat.get("player_id")
        try:
            stat_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if stat_id != player_id:
            continue
        if not same_player_name(name, str(stat.get("name") or "")):
            continue
        own.append(stat)
    position = str(row.get("position") or "").strip() or None
    summary = aggregate_player_minutes(own, str(row.get("club") or ""), position=position)
    row["minutes_by_position"] = summary["by_position"]
    row["stats_updated_at"] = datetime.now(UTC).isoformat()
    if summary["total"] is None:
        row["minutes"] = None
        row["total_minutes"] = None
        row["stats_club_missing"] = True
    else:
        row["minutes"] = summary["profile_minutes"]
        row["total_minutes"] = summary["total"]
        row["stats_club_missing"] = False
    return True


def attach_scoped_totals(rows: list[dict[str, Any]]) -> None:
    """Stamp each Who To Scout row with the shared club/season total.

    The row's own `minutes` stays the minutes in that position. `total_minutes`
    is the same number Loans Watch uses for this player at this club.
    """
    groups: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _player_id(row)
        if key is None:
            key = ("name", transfer_status.name_key(str(row.get("name") or "")))
        groups.setdefault(key, []).append(row)

    for group in groups.values():
        buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in group:
            if _is_loan_out(row):
                row["total_minutes"] = None
                row["position_minutes"] = None
                continue
            window = season_window_id(str(row.get("season") or "")) or ""
            buckets.setdefault((canonical_club_id(str(row.get("club") or "")), window), []).append(row)
        for (club_id, window), bucket in buckets.items():
            summary = aggregate_player_minutes(group, club_id, window or None)
            lookup = {str(item["position"]): int(item["minutes"]) for item in summary["by_position"]}
            for row in bucket:
                row["total_minutes"] = summary["total"]
                code = _position_code(row)
                row["position_minutes"] = lookup.get(code)
