"""Verified opposition squad corrections for the pre-match squad list.

Impect match positions and shirt numbers drift (a goalkeeper filed as a
midfielder, a stale squad number, the same player twice). Club-specific
overrides are applied after the generated roster is built, and again when a
cached report is rehydrated, so the squad list is fixed at the source rather
than only in the browser.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

# Colchester United, checked 25 Sep 2026 (cu-fc.com, Colchester Gazette, FotMob).
# The Port Vale fixture that had been dated 3 Oct was postponed with no new date.
# These notes are player availability, not a kickoff.

_COLCHESTER = "colchester united"

_POSITION_LABELS = {
    "GOALKEEPER": "Goalkeeper",
    "CENTRAL_DEFENDER": "Centre-Back",
    "LEFT_WINGBACK_DEFENDER": "Left-Back",
    "RIGHT_WINGBACK_DEFENDER": "Right-Back",
    "DEFENSE_MIDFIELD": "Defensive Midfield",
    "CENTRAL_MIDFIELD": "Central Midfield",
    "ATTACKING_MIDFIELD": "Attacking Midfield",
    "LEFT_WINGER": "Left Winger",
    "RIGHT_WINGER": "Right Winger",
    "CENTER_FORWARD": "Centre-Forward",
}


def _band(position: str) -> str:
    code = str(position or "").upper()
    if code == "GOALKEEPER":
        return "gk"
    if code in {"CENTER_FORWARD", "LEFT_WINGER", "RIGHT_WINGER", "SECOND_STRIKER"}:
        return "attack"
    if "DEFENDER" in code or code.endswith("BACK"):
        return "def"
    return "mid"


def normalize_person_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace(".", " ").replace("-", " ").replace("'", "")
    text = re.sub(r"\b(junior|jnr)\b", "jr", text, flags=re.IGNORECASE)
    text = re.sub(r"[^a-zA-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def normalize_club_name(name: str) -> str:
    return normalize_person_name(name)


def synthetic_player_id(club_name: str, player_name: str) -> int:
    """Stable negative id so added players can be dragged onto the pitch."""
    raw = f"{normalize_club_name(club_name)}|{normalize_person_name(player_name)}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return -int(digest[:7], 16)


# players: normalized name → shirt / position / whether to add if the feed omitted them.
_CLUBS: dict[str, dict[str, Any]] = {
    _COLCHESTER: {
        "players": {
            "thimothee lo tutala": {"shirt": 22, "position": "GOALKEEPER"},
            "tom smith": {"shirt": 1, "position": "GOALKEEPER"},
            "ellis iandolo": {"shirt": 3, "position": "LEFT_WINGBACK_DEFENDER"},
            "sean raggett": {"shirt": 20, "position": "CENTRAL_DEFENDER"},
            "jack tucker": {"shirt": 5, "position": "CENTRAL_DEFENDER", "captain": True},
            "rob hunt": {"shirt": 2, "position": "RIGHT_WINGBACK_DEFENDER"},
            "frankie terry": {"shirt": 24, "position": "CENTRAL_DEFENDER"},
            "samuel kuffour jr": {"shirt": 44, "position": "CENTRAL_DEFENDER"},
            "kane vincent young": {"shirt": 30, "position": "RIGHT_WINGBACK_DEFENDER"},
            "jake leake": {"shirt": 21, "position": "CENTRAL_DEFENDER"},
            "jay williams": {"shirt": 26, "position": "DEFENSE_MIDFIELD"},
            "moses sesay": {"shirt": 12, "position": "CENTRAL_MIDFIELD"},
            "paul digby": {"shirt": 6, "position": "DEFENSE_MIDFIELD"},
            "jack payne": {"shirt": 10, "position": "ATTACKING_MIDFIELD"},
            "teddy bishop": {"shirt": 8, "position": "CENTRAL_MIDFIELD"},
            "milton oni": {"shirt": 42, "position": "CENTRAL_MIDFIELD"},
            "ben perry": {"shirt": 4, "position": "CENTRAL_MIDFIELD", "add": True, "display": "Ben Perry"},
            "ronnie harvey": {"shirt": 47, "position": "CENTRAL_MIDFIELD", "add": True, "display": "Ronnie Harvey"},
            "max jolliffe": {"shirt": None, "position": "CENTRAL_MIDFIELD", "add": True, "display": "Max Jolliffe"},
            "harry anderson": {"shirt": 7, "position": "LEFT_WINGER"},
            "oscar thorn": {"shirt": 27, "position": "RIGHT_WINGER"},
            "kylian kouassi": {"shirt": 14, "position": "CENTER_FORWARD"},
            "jaden williams": {"shirt": 17, "position": "CENTER_FORWARD"},
            "leon chiwome": {"shirt": 11, "position": "CENTER_FORWARD"},
            "kien connolly": {"shirt": 39, "position": "CENTER_FORWARD"},
            "adrian akande": {"shirt": 23, "position": "CENTER_FORWARD", "add": True, "display": "Adrian Akande"},
            "kaion lisbie": {"shirt": 34, "position": "CENTER_FORWARD", "add": True, "display": "Kaion Lisbie"},
        },
        # Bare "Samuel Kuffour" is the same player as Samuel Kuffour Jr.
        "drop_exact": ("samuel kuffour",),
        "predicted_xi": {
            "formation": "4-2-3-1",
            "captain": "jack tucker",
            "names": (
                "thimothee lo tutala",
                "ellis iandolo",
                "sean raggett",
                "jack tucker",
                "rob hunt",
                "jay williams",
                "moses sesay",
                "harry anderson",
                "jack payne",
                "oscar thorn",
                "kylian kouassi",
            ),
            # Used when the named starter is injured, suspended, or on international duty.
            "suggestions": (
                {"out": "jay williams", "in": "paul digby"},
            ),
        },
        "availability": (
            {
                "name": "jaden williams",
                "status": "suspended",
                "reason": "Red card 19 Sep, 3-match ban",
                "expected_return": "Back ~20 Oct",
            },
            {
                "name": "teddy bishop",
                "status": "injured",
                "reason": "Hamstring",
                "expected_return": "Back ~early Nov",
            },
            {
                "name": "jake leake",
                "status": "injured",
                "reason": "Dislocated shoulder",
                "expected_return": "Return TBC",
            },
            {
                "name": "jay williams",
                "status": "international",
                "reason": "St Kitts & Nevis",
                "expected_return": "29 Sep and 2 Oct",
            },
            {
                "name": "kane vincent young",
                "status": "doubt",
                "reason": "Hamstring / possible Grenada call-up",
                "expected_return": "",
            },
            {
                "name": "max jolliffe",
                "status": "injured",
                "reason": "Injured",
                "expected_return": "Return TBC",
            },
        ),
        # 19 Sep 2026, Colchester 1-1 Cheltenham (cu-fc.com, ESPN, Flashscore).
        # Jaden Williams replaced Thorn at 69' and was sent off at 83'.
        # Chiwome replaced Anderson at 89'. Impect's phase cap was hiding the 69' sub
        # and a stale shirt showed Jay Williams as 28.
        "matches": (
            {
                "opponent": "cheltenham",
                "date_prefix": "2026-09-19",
                "formation": "4-2-3-1",
                "starters": (
                    "thimothee lo tutala",
                    "ellis iandolo",
                    "sean raggett",
                    "jack tucker",
                    "rob hunt",
                    "jay williams",
                    "moses sesay",
                    "harry anderson",
                    "jack payne",
                    "oscar thorn",
                    "kylian kouassi",
                ),
                "events": (
                    {
                        "type": "SUB_ON",
                        "minute": 69,
                        "player": "jaden williams",
                        "replaces": "oscar thorn",
                        "to_position": "RIGHT_WINGER",
                        "to_side": "RIGHT",
                    },
                    {"type": "RED_CARD", "minute": 83, "player": "jaden williams"},
                    {
                        "type": "SUB_ON",
                        "minute": 89,
                        "player": "leon chiwome",
                        "replaces": "harry anderson",
                        "to_position": "LEFT_WINGER",
                        "to_side": "LEFT",
                    },
                ),
            },
        ),
    },
}


def club_spec(club_name: str) -> dict[str, Any] | None:
    return _CLUBS.get(normalize_club_name(club_name))


def _names_match(player_name: str, key: str) -> bool:
    left = normalize_person_name(player_name)
    right = key
    if left == right:
        return True
    left_parts = left.split()
    right_parts = right.split()
    if not left_parts or not right_parts or left_parts[-1] != right_parts[-1]:
        return False
    if ("jr" in left_parts) != ("jr" in right_parts):
        return False
    if len(left_parts) == 1 or len(right_parts) == 1:
        return "jr" not in right_parts
    if left_parts[0] == right_parts[0]:
        return True
    # "J. Williams" — only when the initial is unambiguous. Jay and Jaden share J.
    if len(left_parts[0]) == 1 and right_parts[0].startswith(left_parts[0]):
        return False
    return False


def _find_row_indexes(rows: list[dict[str, Any]], key: str) -> list[int]:
    return [index for index, row in enumerate(rows) if _names_match(str(row.get("name") or ""), key)]


def _apply_player_meta(row: dict[str, Any], meta: dict[str, Any]) -> None:
    position = str(meta.get("position") or "")
    if position:
        row["position_code"] = position
        row["position"] = _POSITION_LABELS.get(position, position.replace("_", " ").title())
        row["band"] = _band(position)
    shirt = meta.get("shirt")
    if shirt is not None:
        row["shirt_number"] = int(shirt)
    if meta.get("captain"):
        row["captain"] = True


def _synthetic_row(club_name: str, key: str, meta: dict[str, Any]) -> dict[str, Any]:
    position = str(meta.get("position") or "CENTRAL_MIDFIELD")
    display = str(meta.get("display") or key.title())
    shirt = meta.get("shirt")
    return {
        "id": synthetic_player_id(club_name, display),
        "name": display,
        "age": None,
        "foot": "—",
        "position": _POSITION_LABELS.get(position, position.replace("_", " ").title()),
        "position_code": position,
        "band": _band(position),
        "appearances": 0,
        "starts": 0,
        "minutes": 0,
        "goals": 0,
        "assists": 0,
        "shirt_number": int(shirt) if shirt is not None else None,
        "current": True,
        "captain": bool(meta.get("captain")),
        "source": "squad-correction",
    }


def apply_club_squad_overrides(
    club_name: str,
    squad_rows: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    spec = club_spec(club_name)
    rows = [dict(row) for row in (squad_rows or []) if isinstance(row, dict)]
    if spec is None:
        return rows

    drop_indexes: set[int] = set()
    for key, meta in spec["players"].items():
        matches = _find_row_indexes(rows, key)
        if not matches:
            if meta.get("add"):
                rows.append(_synthetic_row(club_name, key, meta))
            continue
        primary = max(
            matches,
            key=lambda index: (
                int((rows[index].get("minutes") or 0)),
                "jr" in normalize_person_name(str(rows[index].get("name") or "")),
            ),
        )
        _apply_player_meta(rows[primary], meta)
        for index in matches:
            if index != primary:
                drop_indexes.add(index)

    kept = [row for index, row in enumerate(rows) if index not in drop_indexes]
    drop_exact = {normalize_person_name(name) for name in spec.get("drop_exact") or ()}
    if drop_exact:
        has_jr = any(
            "kuffour" in normalize_person_name(str(row.get("name") or ""))
            and "jr" in normalize_person_name(str(row.get("name") or "")).split()
            for row in kept
        )
        if has_jr:
            kept = [
                row
                for row in kept
                if normalize_person_name(str(row.get("name") or "")) not in drop_exact
            ]
    return kept


def corrected_shirt_number(
    club_name: str,
    player_name: str,
    current: Any = None,
) -> Any:
    spec = club_spec(club_name)
    if spec is None:
        return current
    for key, meta in spec["players"].items():
        if not _names_match(player_name, key):
            continue
        shirt = meta.get("shirt")
        if shirt is not None:
            return int(shirt)
        return current
    return current


def _row_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    matches = _find_row_indexes(rows, key)
    if not matches:
        return None
    return rows[matches[0]]


def predicted_xi_spec(club_name: str) -> dict[str, Any] | None:
    spec = club_spec(club_name)
    if not spec:
        return None
    predicted = spec.get("predicted_xi")
    return dict(predicted) if isinstance(predicted, dict) else None


def availability_defaults_for_rows(
    club_name: str,
    squad_rows: list[dict[str, Any]] | None,
) -> dict[str, dict[str, str]]:
    spec = club_spec(club_name)
    if spec is None:
        return {}
    rows = list(squad_rows or [])
    out: dict[str, dict[str, str]] = {}
    for item in spec.get("availability") or ():
        row = _row_by_key(rows, str(item["name"]))
        if row is None or row.get("id") is None:
            continue
        out[str(int(row["id"]))] = {
            "status": str(item.get("status") or "available"),
            "reason": str(item.get("reason") or ""),
            "expected_return": str(item.get("expected_return") or ""),
        }
    return out


def xi_suggestions_for_rows(
    club_name: str,
    squad_rows: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    spec = predicted_xi_spec(club_name) or {}
    rows = list(squad_rows or [])
    suggestions = []
    for item in spec.get("suggestions") or ():
        outgoing = _row_by_key(rows, str(item.get("out") or ""))
        incoming = _row_by_key(rows, str(item.get("in") or ""))
        if not outgoing or not incoming:
            continue
        suggestions.append(
            {
                "out_id": int(outgoing["id"]),
                "out_name": outgoing.get("name"),
                "in_id": int(incoming["id"]),
                "in_name": incoming.get("name"),
            }
        )
    return suggestions


def verified_match_script(
    club_name: str,
    opponent_name: str,
    match_date: Any,
) -> dict[str, Any] | None:
    spec = club_spec(club_name)
    if spec is None:
        return None
    opponent = normalize_club_name(str(opponent_name or ""))
    date_text = str(match_date or "")
    for script in spec.get("matches") or ():
        if str(script.get("opponent") or "") not in opponent:
            continue
        prefix = str(script.get("date_prefix") or "")
        if prefix and not date_text.startswith(prefix):
            continue
        return script
    return None
