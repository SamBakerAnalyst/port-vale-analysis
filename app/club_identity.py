"""One club id for every spelling of the same club.

Loans Watch, Who To Scout and the Watch list join stats to a loan on this id.
The id is the club's tokens after house-style noise is removed. Matching is
equality of that id. A shorter name is not treated as the same club just
because it is a prefix or a substring — Dundee and Dundee United stay apart,
while a trailing place tag (Y Glasgow / Y) or a legal suffix (FC) does not
create a second club.
"""

from __future__ import annotations

import re
import unicodedata

# Words that never identify a club. "United" and "City" are not in here:
# stripping them would merge two clubs that share a town.
_LEGAL_NOISE = frozenset({"fc", "afc", "cf", "sc", "football", "club", "the"})

# A feed sometimes writes the town before or after the club. It is only noise
# when the rest of the name still identifies the club.
_PLACE_TAGS = frozenset(
    {
        "glasgow",
        "edinburgh",
        "london",
        "birmingham",
        "nottingham",
    }
)

# Tokens that are a different club when they are the only thing left
# (Manchester United must not collapse to "united").
_DISTINGUISHERS = frozenset(
    {
        "united",
        "city",
        "wednesday",
        "athletic",
        "athletico",
        "wanderers",
        "rovers",
        "albion",
        "town",
        "county",
        "forest",
        "hotspur",
        "argyle",
        "villa",
        "palace",
        "orient",
        "stanley",
        "alexandra",
        "vale",
    }
)

# Abbreviations that share no token with the full name. This is the existing
# transfer-feed pair, not a per-player exception.
_ABBREVIATIONS = {
    "mk dons": "milton keynes dons",
    "mk": "milton keynes dons",
}

_YOUTH = re.compile(r"^u\d{2}s?$")


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def club_tokens(value: str | None) -> list[str]:
    text = _strip_accents(str(value or "")).lower().replace("&", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [word for word in text.split() if word and word not in _LEGAL_NOISE]
    folded: list[str] = []
    for token in tokens:
        folded.append("st" if token == "saint" else token)
    while folded and _YOUTH.match(folded[-1]):
        folded.pop()
    return folded


def _fold_plural(tokens: list[str]) -> list[str]:
    """Bohemian and Bohemians. A short word is left alone."""
    if not tokens:
        return tokens
    last = tokens[-1]
    if len(last) >= 6 and last.endswith("s") and not last.endswith("ss"):
        return [*tokens[:-1], last[:-1]]
    return tokens


def _drop_place_tag(tokens: list[str]) -> list[str]:
    """Y Glasgow and Glasgow Y are Y. United stays, so the town is not enough."""
    if len(tokens) < 2:
        return tokens

    def _remainder_identifies(rest: list[str]) -> bool:
        return any(token not in _PLACE_TAGS and token not in _DISTINGUISHERS for token in rest)

    if tokens[0] in _PLACE_TAGS and _remainder_identifies(tokens[1:]):
        return _drop_place_tag(tokens[1:])
    if tokens[-1] in _PLACE_TAGS and _remainder_identifies(tokens[:-1]):
        return _drop_place_tag(tokens[:-1])
    return tokens


def canonical_club_id(value: str | None) -> str:
    """Stable id. Empty when the name has no identifying tokens."""
    tokens = _drop_place_tag(club_tokens(value))
    key = " ".join(tokens)
    key = _ABBREVIATIONS.get(key, key)
    tokens = _fold_plural(key.split()) if key else []
    return " ".join(tokens)


def same_club(left: str | None, right: str | None) -> bool:
    """True only when both names reduce to the same id."""
    a = canonical_club_id(left)
    b = canonical_club_id(right)
    return bool(a) and a == b
