"""Scout prompts and field catalogs for Player Reports."""

from __future__ import annotations

import re
from typing import Any

from app.label_utils import humanize_profile_name, strip_pv_prefix

REPORT_POSITIONS: tuple[tuple[str, str, str], ...] = (
    ("GOALKEEPER", "GK", "Goalkeeper"),
    ("LEFT_WINGBACK_DEFENDER", "LB", "Left back / wing-back"),
    ("CENTRAL_DEFENDER", "CB", "Centre-back"),
    ("RIGHT_WINGBACK_DEFENDER", "RB", "Right back / wing-back"),
    ("DEFENSE_MIDFIELD", "DM", "Defensive midfield"),
    ("CENTRAL_MIDFIELD", "CM", "Central midfield"),
    ("ATTACKING_MIDFIELD", "AM", "Attacking midfield"),
    ("LEFT_WINGER", "LW", "Left winger"),
    ("RIGHT_WINGER", "RW", "Right winger"),
    ("CENTER_FORWARD", "ST", "Centre-forward"),
)

POSITION_IDS = {code for code, _short, _label in REPORT_POSITIONS}

STRONG_FOOT_CHOICES: tuple[tuple[str, str], ...] = (
    ("left", "Left"),
    ("right", "Right"),
    ("both", "Both"),
)

WEAK_FOOT_CHOICES: tuple[tuple[str, str], ...] = (
    ("poor", "Poor"),
    ("mid", "Mid"),
    ("strong", "Strong"),
    ("very_strong", "Very strong"),
)

# (id, label, kind, prompt). kind: "scale" = 0-10, "choice", or "text".
PHYSICAL_FIELDS: tuple[tuple[str, str, str, str], ...] = (
    ("work_rate", "Work rate", "scale", "0–10 · off the ball, tracking, repeat efforts."),
    ("size", "Size", "text", "Height / frame — does it win him duels?"),
    ("mobility", "Mobility", "scale", "0–10 · pace, agility, recovery."),
    ("foot", "Strong foot", "choice", ""),
    ("weak_foot", "Weak foot", "choice", ""),
    ("fitness", "General fitness", "scale", "0–10 · how he lasted the game."),
)

PHYSICAL_CHOICES: dict[str, tuple[tuple[str, str], ...]] = {
    "foot": STRONG_FOOT_CHOICES,
    "weak_foot": WEAK_FOOT_CHOICES,
}

# Older reports stored free text under these keys; keep them so nothing is lost.
LEGACY_PHYSICAL_KEYS: tuple[str, ...] = ("physical_ability",)

GK_PHYSICAL = ("size", "mobility", "foot", "weak_foot")
OUTFIELD_PHYSICAL = ("work_rate", "size", "mobility", "foot", "weak_foot", "fitness")

# Port Vale scouting report format, one per position group:
# (group id, title, positions, physical field ids, ((profile, detailed question), ...)).
REPORT_GROUPS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[tuple[str, str], ...]], ...] = (
    (
        "GK",
        "Goalkeeper",
        ("GOALKEEPER",),
        GK_PHYSICAL,
        (
            ("Shot stopper", "Best saves? Weakness?"),
            ("Long kicking", "Accurate? Distance?"),
            ("Short kicking", "Does he join the back line?"),
            ("Box goalkeeper", "Catch or punch?"),
            ("Sweeper keeper", "How aggressive?"),
        ),
    ),
    (
        "FB",
        "Full back",
        ("LEFT_WINGBACK_DEFENDER", "RIGHT_WINGBACK_DEFENDER"),
        OUTFIELD_PHYSICAL,
        (
            ("Deep creator", "Does he create, and how?"),
            ("Defensive", "Back post? Aerial? Dueler? High or low?"),
            ("Offensive", "What types of chances? Ball carrier?"),
        ),
    ),
    (
        "CB",
        "Centre back",
        ("CENTRAL_DEFENDER",),
        OUTFIELD_PHYSICAL,
        (
            ("Central dueler", "Front foot or sweeper?"),
            ("Aerial", "How aggressive? Types of headers?"),
            ("Ball progressor", "Short or long? Does he create?"),
            ("Right side dueler (if back 3)", "How does he defend the right channel and step out?"),
            ("Left side dueler (if back 3)", "How does he defend the left channel and step out?"),
        ),
    ),
    (
        "DM",
        "Defensive midfield",
        ("DEFENSE_MIDFIELD",),
        OUTFIELD_PHYSICAL,
        (
            ("Ball winner", "High or low? Aggressive?"),
            ("Ball progressor", "Sideways or forwards? Where from?"),
            ("Creator", "Does he break lines?"),
        ),
    ),
    (
        "CM",
        "Central midfield",
        ("CENTRAL_MIDFIELD",),
        OUTFIELD_PHYSICAL,
        (
            ("Ball winner", "High or low?"),
            ("Ball progressor", "From the back line, or higher?"),
            ("Creator", "High or low? Types of crosses?"),
            ("Running threat", "Into the channels?"),
            ("Goal threat", "Types of shots he gets?"),
        ),
    ),
    (
        "AM",
        "Attacking midfield",
        ("ATTACKING_MIDFIELD",),
        OUTFIELD_PHYSICAL,
        (
            ("Ball winner", "Offensive interventions?"),
            ("Creator", "Types of chances?"),
            ("Running threat", "Does he break lines?"),
            ("Goal threat", "Types of chances?"),
        ),
    ),
    (
        "W",
        "Winger",
        ("LEFT_WINGER", "RIGHT_WINGER"),
        OUTFIELD_PHYSICAL,
        (
            ("Ball carrier", "Does he beat them?"),
            ("Creator", "Types of chances? Crosses?"),
            ("Goal threat", "How can we get him to score?"),
            ("Presser", "Types of pressing? Does he work back?"),
        ),
    ),
    (
        "ST",
        "Striker",
        ("CENTER_FORWARD",),
        OUTFIELD_PHYSICAL,
        (
            ("Goal threat", "What types of chances does he score from?"),
            ("Target man", "Big? Feet or head? Aggressive?"),
            ("Threat in behind", "Types of runs? Channels or in behind?"),
            ("Presser", "Regains? Second balls?"),
            ("Link / creator", "What sort of chances does he create?"),
        ),
    ),
)

GROUP_BY_POSITION: dict[str, str] = {
    position: group_id
    for group_id, _title, positions, _physical, _profiles in REPORT_GROUPS
    for position in positions
}

PVFC_LEVELS: tuple[tuple[str, str, str], ...] = (
    ("A", "Starter", "Would go straight into the XI"),
    ("B", "Challenger", "Pushes a starter / rotation now"),
    ("C", "Emerging talent", "Project — not ready, but we like the tools"),
    ("D", "Not to standard", "Below Port Vale level"),
)

NEXT_ACTIONS: tuple[tuple[str, str], ...] = (
    ("not_to_standard", "Not to standard"),
    ("low_priority", "Low priority"),
    ("high_priority", "High priority"),
    ("sign", "Sign"),
)

PSYCHOLOGY_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("work_hard", "Worked hard", "Did he work for the team off the ball?"),
    ("leader", "Leader", "Did he organise, demand, or take responsibility?"),
    ("booked", "Booked", "Yellow / red, or lucky not to be?"),
    ("frustrated", "Frustrated", "Body language when it went against him."),
    ("spoke_to_coach", "Spoke to the coach", "Sideline chat, instructions, argument?"),
)

YES_MIXED_NO: tuple[tuple[str, str], ...] = (
    ("yes", "Yes"),
    ("mixed", "Mixed"),
    ("no", "No"),
)

PIPELINE_STAGES: tuple[tuple[str, str], ...] = (
    ("watched", "Watched"),
    ("scout_identified", "Scout identified"),
    ("video_scouted", "Video scouted"),
    ("live_scouted", "Live scouted"),
    ("not_the_right_fit", "Not the right fit"),
)

GENERAL_PROFILE_PROMPT = "What did you see from him in this role?"


def profile_id(name: str) -> str:
    token = strip_pv_prefix(name).casefold()
    token = re.sub(r"[^a-z0-9]+", "-", token).strip("-")
    return token or "profile"


def _group_row(position: str) -> tuple | None:
    group_id = GROUP_BY_POSITION.get(clean_position(position))
    for row in REPORT_GROUPS:
        if row[0] == group_id:
            return row
    return None


def report_group_for_position(position: str) -> dict[str, Any]:
    row = _group_row(position)
    if row is None:
        return {"id": "", "title": "", "physical": [], "profiles": []}
    group_id, title, _positions, physical, profiles = row
    return {
        "id": group_id,
        "title": title,
        "physical": list(physical),
        "profiles": [
            {
                "id": profile_id(label),
                "key": label,
                "label": label,
                "score": None,
                "general_prompt": GENERAL_PROFILE_PROMPT,
                "detailed_prompt": question,
            }
            for label, question in profiles
        ],
    }


def empty_physical() -> dict[str, str]:
    return {key: "" for key, *_rest in PHYSICAL_FIELDS}


def empty_psychology() -> dict[str, str]:
    out = {key: "" for key, _label, _prompt in PSYCHOLOGY_FIELDS}
    out["notes"] = ""
    return out


def clean_physical(row: Any) -> dict[str, str]:
    source = row if isinstance(row, dict) else {}
    out = empty_physical()
    for key in (*out.keys(), *LEGACY_PHYSICAL_KEYS):
        value = str(source.get(key) or "").strip()[:2000]
        if value or key in out:
            out[key] = value
    return out


def clean_profiles(row: Any) -> dict[str, str]:
    source = row if isinstance(row, dict) else {}
    out: dict[str, str] = {}
    for key, value in source.items():
        pid = profile_id(str(key))
        text = str(value or "").strip()[:4000]
        if pid:
            out[pid] = text
    return out


def clean_psychology(row: Any) -> dict[str, str]:
    source = row if isinstance(row, dict) else {}
    allowed = {"", "yes", "no", "mixed"}
    out = empty_psychology()
    for key, _label, _prompt in PSYCHOLOGY_FIELDS:
        token = str(source.get(key) or "").strip().casefold()
        out[key] = token if token in allowed else ""
    out["notes"] = str(source.get("notes") or "").strip()[:4000]
    return out


def clean_match_rating(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        rating = float(value)
    except (TypeError, ValueError):
        return None
    if rating < 0 or rating > 10:
        return None
    return round(rating, 1)


def clean_pvfc_level(value: Any) -> str:
    token = str(value or "").strip().upper()
    return token if token in {key for key, _title, _hint in PVFC_LEVELS} else ""


def clean_next_action(value: Any) -> str:
    token = str(value or "").strip().casefold().replace(" ", "_")
    return token if token in {key for key, _label in NEXT_ACTIONS} else ""


def clean_position(value: Any) -> str:
    token = str(value or "").strip()
    return token if token in POSITION_IDS else ""


def clean_pipeline_stage(value: Any) -> str:
    token = str(value or "").strip()
    return token if token in {key for key, _label in PIPELINE_STAGES} else ""


def profile_entries_for_position(
    position: str,
    *,
    player_profiles: list[dict[str, Any]] | None = None,
    player_position: str = "",
) -> list[dict[str, Any]]:
    """Port Vale report profiles for the role (the club format, not Impect data profiles)."""
    wanted = clean_position(position) or clean_position(player_position)
    return report_group_for_position(wanted)["profiles"]


def option_fields() -> dict[str, Any]:
    return {
        "positions": [
            {
                "id": code,
                "short": short,
                "label": label,
                "group": GROUP_BY_POSITION.get(code, ""),
            }
            for code, short, label in REPORT_POSITIONS
        ],
        "physical": [
            {
                "id": key,
                "label": label,
                "kind": kind,
                "prompt": prompt,
                "detailed_prompt": prompt,
                "choices": [
                    {"id": cid, "label": clabel}
                    for cid, clabel in PHYSICAL_CHOICES.get(key, ())
                ],
            }
            for key, label, kind, prompt in PHYSICAL_FIELDS
        ],
        "psychology": [
            {"id": key, "label": label, "prompt": prompt}
            for key, label, prompt in PSYCHOLOGY_FIELDS
        ],
        "yes_mixed_no": [{"id": key, "label": label} for key, label in YES_MIXED_NO],
        "pvfc_levels": [
            {"id": key, "label": label, "hint": hint}
            for key, label, hint in PVFC_LEVELS
        ],
        "next_actions": [{"id": key, "label": label} for key, label in NEXT_ACTIONS],
        "pipeline_stages": [
            {"id": key, "label": label} for key, label in PIPELINE_STAGES
        ],
        "report_groups": {
            code: report_group_for_position(code)
            for code, _short, _label in REPORT_POSITIONS
        },
        "profiles_by_position": {
            code: profile_entries_for_position(code)
            for code, _short, _label in REPORT_POSITIONS
        },
    }
