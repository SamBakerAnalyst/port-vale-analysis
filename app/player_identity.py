"""One identity for a player across Impect, Transfermarkt, and the transfer report.

Scout tables say "Nicholas". The loan report says "Nick". Those are the same
person when the surname matches and the first name is a known short form, or
the shorter form is a real prefix of the longer one ("Nick" / "Nicholas").
Callers still decide colour from the row's data club. This module only answers
whether two spellings are one player.
"""

from __future__ import annotations

import re
import unicodedata

# Short forms that are not prefixes of each other (Tom / Tommy, Joe / Josef).
# A lookup must not grow a per-player exception list on top of this.
FIRST_NAME_CANON = {
    "alexander": "alexander",
    "alex": "alexander",
    "andrew": "andrew",
    "andy": "andrew",
    "benjamin": "benjamin",
    "ben": "benjamin",
    "christopher": "christopher",
    "chris": "christopher",
    "daniel": "daniel",
    "dan": "daniel",
    "danny": "daniel",
    "james": "james",
    "jamie": "james",
    "jim": "james",
    "jimmy": "james",
    "joseph": "joseph",
    "joe": "joseph",
    "josef": "joseph",
    "jonathan": "jonathan",
    "jon": "jonathan",
    "johnny": "jonathan",
    "matthew": "matthew",
    "matt": "matthew",
    "matty": "matthew",
    "mattie": "matthew",
    "michael": "michael",
    "mike": "michael",
    "mick": "michael",
    "nicholas": "nicholas",
    "nick": "nicholas",
    "nicky": "nicholas",
    "oliver": "oliver",
    "olly": "oliver",
    "ollie": "oliver",
    "oli": "oliver",
    "ismael": "ismael",
    "ismeal": "ismael",
    "ruari": "ruari",
    "ruiri": "ruari",
    "shumaira": "shumaira",
    "shim": "shumaira",
    "richard": "richard",
    "rich": "richard",
    "rick": "richard",
    "ricky": "richard",
    "robert": "robert",
    "rob": "robert",
    "bobby": "robert",
    "samuel": "samuel",
    "sam": "samuel",
    "thomas": "thomas",
    "tom": "thomas",
    "tommy": "thomas",
    "timothy": "timothy",
    "tim": "timothy",
    "william": "william",
    "will": "william",
    "billy": "william",
    "joshua": "joshua",
    "josh": "joshua",
}


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def name_key(value: str | None) -> str:
    """A name reduced to something two sources can agree on."""
    text = _strip_accents(str(value or "")).lower()
    text = re.sub(r"[^a-z\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def name_keys(value: str | None) -> list[str]:
    """Ar'Jany and Arjany have to hit the same index row."""
    key = name_key(value)
    if not key:
        return []
    compact = key.replace(" ", "").replace("-", "")
    if compact == key:
        return [key]
    return [key, compact]


def canonical_name_key(value: str | None) -> str:
    """First name folded to one spelling, surname left as written."""
    key = name_key(value)
    parts = key.split()
    if len(parts) < 2:
        return key
    first = FIRST_NAME_CANON.get(parts[0], parts[0])
    return " ".join((first, *parts[1:]))


def identity_keys(value: str | None) -> list[str]:
    """Every key two spellings of one player should share."""
    keys = name_keys(value)
    canon = canonical_name_key(value)
    if canon and canon not in keys:
        keys.append(canon)
    if canon:
        compact = canon.replace(" ", "").replace("-", "")
        if compact not in keys:
            keys.append(compact)
    return keys


def _first_and_rest(value: str | None) -> tuple[str, str]:
    parts = name_key(value).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def same_person(left: str | None, right: str | None) -> bool:
    """True when two display names are one player, not merely the same surname."""
    left_keys = set(name_keys(left))
    right_keys = set(name_keys(right))
    if left_keys and left_keys & right_keys:
        return True
    canon_left, canon_right = canonical_name_key(left), canonical_name_key(right)
    if canon_left and canon_left == canon_right:
        return True
    left_first, left_rest = _first_and_rest(left)
    right_first, right_rest = _first_and_rest(right)
    if not left_rest or left_rest != right_rest or not left_first or not right_first:
        return False
    if FIRST_NAME_CANON.get(left_first, left_first) == FIRST_NAME_CANON.get(right_first, right_first):
        return True
    short, long = (left_first, right_first) if len(left_first) <= len(right_first) else (right_first, left_first)
    # "Nick" is a prefix of "Nicholas". A 3-letter gate also matches Dan/Danilo.
    return len(short) >= 4 and long.startswith(short)
