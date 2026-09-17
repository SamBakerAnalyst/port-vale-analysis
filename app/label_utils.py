from __future__ import annotations

import re

_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"ratio\s*-\s*remove opponents(?:\s+defenders)?", "Opponents removed"),
    (r"ratio\s*-\s*add teammates(?:\s+defenders)?", "Teammates added"),
    (r"total touches fbl", "Touches in left channel"),
    (r"total touches fbr", "Touches in right channel"),
    (r"total touches cb", "Touches centrally"),
    (r"total touches cm", "Touches in midfield"),
    (r"total touches dm", "Touches in defensive midfield"),
    (r"number of aerial duels in packing zone cb", "Aerial duels in central zone"),
    (r"ground duel score", "Ground duels"),
    (r"interception score", "Interceptions"),
    (r"loose ball regain score", "Loose ball regains"),
    (r"defensive header score", "Defensive headers"),
    (r"offensive header score", "Attacking headers"),
    (r"header shot score", "Headers on target"),
    (r"ground duel success rate", "Ground duel win %"),
    (r"aerial duel success rate", "Aerial duel win %"),
    (r"ball wins\*?", "Ball wins"),
    (r"passes\*?", "Passes"),
    (r"^suffered bypassed players$", "Bypassed opponents"),
    (r"^\+\/-\s*suffered bypassed defenders$", "Bypassed defenders"),
    (r"^bypassed opponents$", "Bypassed opponents"),
    (r"^bypassed defenders$", "Bypassed defenders"),
)

_ZONE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bfbl\b", "left channel"),
    (r"\bfbr\b", "right channel"),
    (r"\bcb\b", "central"),
    (r"\bcm\b", "midfield"),
    (r"\bdm\b", "defensive midfield"),
    (r"\bam\b", "attacking midfield"),
    (r"\bwl\b", "left wing"),
    (r"\bwr\b", "right wing"),
)


def humanize_metric_label(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return text

    lowered = text.casefold()
    for pattern, replacement in _PHRASE_REPLACEMENTS:
        if re.search(pattern, lowered):
            return replacement

    text = text.replace("_", " ")
    text = re.sub(r"\s*-\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    for pattern, replacement in _ZONE_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    text = re.sub(r"\bSb\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bRatio\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNumber Of\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bScore\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -")

    if not text:
        return str(label).strip()

    return text[0].upper() + text[1:] if len(text) > 1 else text.upper()


_SHORT_STAT_TO_FULL: tuple[tuple[str, str], ...] = (
    ("aerial duel success rate", "Aerial duel win %"),
    ("ground duel success rate", "Ground duel win %"),
    ("aerial duel win %", "Aerial duel win %"),
    ("ground duel win %", "Ground duel win %"),
    ("aerial duels in central zone", "Number of aerial duels in packing zone CB"),
    ("teammates added", "Ratio — add teammates"),
    ("opponents removed", "Ratio — remove opponents"),
    ("opponents bypassed", "Opponents bypassed"),
    ("defensive headers", "Defensive header score"),
    ("attacking headers", "Offensive header score"),
    ("headers on target", "Header shot score"),
    ("ground duels", "Ground duel score"),
    ("interceptions", "Interception score"),
    ("loose ball regains", "Loose ball regain score"),
    ("touches in left channel", "Total touches FBL"),
    ("touches in right channel", "Total touches FBR"),
    ("touches centrally", "Total touches CB"),
    ("ball wins", "Ball wins"),
    ("passes", "Passes"),
)


def full_stat_label(label: str) -> str:
    """Readable full Impect stat name — never a truncated or stripped short form."""
    text = str(label or "").strip()
    if not text:
        return text
    lowered = text.casefold()
    for short, full in _SHORT_STAT_TO_FULL:
        if lowered == short:
            return full
        prefix = f"{short} — "
        if lowered.startswith(prefix):
            return f"{full} — {text[len(prefix):].strip()}"
        prefix = f"{short} - "
        if lowered.startswith(prefix):
            return f"{full} — {text[len(prefix):].strip()}"
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[0].upper() + text[1:] if len(text) > 1 else text.upper()


def strip_pv_prefix(name: str) -> str:
    return re.sub(r"^\s*pv\b[\s\-:]*", "", str(name or "").strip(), flags=re.IGNORECASE).strip()


def humanize_profile_name(name: str) -> str:
    text = strip_pv_prefix(name)
    text = text.replace("_", " ")
    text = re.sub(r"\s*-\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text).strip()
    if not text:
        return strip_pv_prefix(name) or str(name).strip()
    abbrevs = {"CB", "LB", "RB", "DM", "CM", "AM", "LW", "RW", "CF", "GK", "WB"}
    words = []
    for word in text.split():
        upper = word.upper()
        if upper in abbrevs:
            words.append(upper)
        else:
            words.append(word[:1].upper() + word[1:].lower())
    return " ".join(words)
