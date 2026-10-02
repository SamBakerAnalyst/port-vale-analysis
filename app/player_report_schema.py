"""Scout prompts and field catalogs for Scouting (Port Vale report format).

Physical attributes and position profiles follow the club scouting PDF:
general first look + detailed prompts per role.
"""

from __future__ import annotations

import re
from typing import Any

from app.label_utils import humanize_profile_name, strip_pv_prefix


REPORT_POSITIONS: tuple[tuple[str, str, str], ...] = (
    ("GOALKEEPER", "GK", "Goalkeeper"),
    ("LEFT_WINGBACK_DEFENDER", "LB", "Left back"),
    ("CENTRAL_DEFENDER", "CB", "Centre-back"),
    ("RIGHT_WINGBACK_DEFENDER", "RB", "Right back"),
    ("DEFENSE_MIDFIELD", "DM", "Defensive midfield"),
    ("CENTRAL_MIDFIELD", "CM", "Central midfield"),
    ("ATTACKING_MIDFIELD", "AM", "Attacking midfield"),
    ("LEFT_WINGER", "LW", "Left winger"),
    ("RIGHT_WINGER", "RW", "Right winger"),
    ("CENTER_FORWARD", "ST", "Striker"),
)

POSITION_IDS = {code for code, _short, _label in REPORT_POSITIONS}

# Field kinds drive the scout UI: text, rating (0-10), foot (L/R), weak_foot enum.
PHYSICAL_FIELD_DEFS: tuple[dict[str, Any], ...] = (
    {
        "id": "work_rate",
        "label": "Work rate",
        "kind": "rating",
        "prompt": "0–10 work rate in this game.",
        "detailed_prompt": "0–10 work rate — pressing, recovery, and how hard they worked for the team.",
        "positions": "outfield",
    },
    {
        "id": "size",
        "label": "Size",
        "kind": "text",
        "prompt": "Frame, height, strength.",
        "detailed_prompt": "How big vs the opponent? Who wins aerials and hold-up?",
        "positions": "all",
    },
    {
        "id": "mobility",
        "label": "Mobility",
        "kind": "rating",
        "prompt": "0–10 mobility — pace, agility, recovery.",
        "detailed_prompt": "0–10 mobility — pace over 10 yards, recovery runs, change of direction.",
        "positions": "all",
    },
    {
        "id": "strong_foot",
        "label": "Strong foot",
        "kind": "foot",
        "prompt": "Preferred / strong foot.",
        "detailed_prompt": "Strong foot — left or right. What actions did they play with it?",
        "positions": "all",
    },
    {
        "id": "weak_foot",
        "label": "Weak foot",
        "kind": "weak_foot",
        "prompt": "Poor · Mid · Strong · Very strong",
        "detailed_prompt": "Weak foot — poor, mid, strong, or very strong. Could they use it under pressure?",
        "positions": "all",
    },
    {
        "id": "general_fitness",
        "label": "General fitness",
        "kind": "rating",
        "prompt": "0–10 general fitness — lasted the game?",
        "detailed_prompt": "0–10 general fitness — stamina, repeated sprints, drop-off after 70.",
        "positions": "outfield",
    },
)

PHYSICAL_FIELDS: tuple[tuple[str, str, str, str], ...] = tuple(
    (row["id"], row["label"], row["prompt"], row["detailed_prompt"])
    for row in PHYSICAL_FIELD_DEFS
)

WEAK_FOOT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("poor", "Poor"),
    ("mid", "Mid"),
    ("strong", "Strong"),
    ("very_strong", "Very strong"),
)

STRONG_FOOT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("left", "Left"),
    ("right", "Right"),
)

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

# PDF position profiles — names match the club scouting template.
POSITION_PROFILES: dict[str, tuple[str, ...]] = {
    "GOALKEEPER": (
        "SHOT STOPPER",
        "LONG KICKING",
        "SHORT KICKING",
        "BOX GOALKEEPER",
        "SWEEPER KEEPER",
    ),
    "LEFT_WINGBACK_DEFENDER": (
        "DEEP CREATOR",
        "DEFENSIVE",
        "OFFENSIVE",
    ),
    "RIGHT_WINGBACK_DEFENDER": (
        "DEEP CREATOR",
        "DEFENSIVE",
        "OFFENSIVE",
    ),
    "CENTRAL_DEFENDER": (
        "CENTRAL DUELER",
        "AERIAL",
        "BALL PROGRESSOR",
        "RIGHT SIDE DUELER",
        "LEFT SIDE DUELER",
    ),
    "DEFENSE_MIDFIELD": (
        "BALL WINNER",
        "BALL PROGRESSOR",
        "CREATOR",
    ),
    "CENTRAL_MIDFIELD": (
        "BALL WINNER",
        "BALL PROGRESSOR",
        "CREATOR",
        "RUNNING THREAT",
        "GOAL THREAT",
    ),
    "ATTACKING_MIDFIELD": (
        "BALL WINNER",
        "CREATOR",
        "RUNNING THREAT",
        "GOAL THREAT",
    ),
    "LEFT_WINGER": (
        "BALL CARRIER",
        "CREATOR",
        "GOAL THREAT",
        "PRESSER",
    ),
    "RIGHT_WINGER": (
        "BALL CARRIER",
        "CREATOR",
        "GOAL THREAT",
        "PRESSER",
    ),
    "CENTER_FORWARD": (
        "GOAL THREAT",
        "TARGET MAN",
        "THREAT IN BEHIND",
        "PRESSER",
        "LINK / CREATOR",
    ),
}

PROFILE_LABELS: dict[str, str] = {
    "shot-stopper": "Shot stopper",
    "long-kicking": "Long kicking",
    "short-kicking": "Short kicking",
    "box-goalkeeper": "Box goalkeeper",
    "sweeper-keeper": "Sweeper keeper",
    "deep-creator": "Deep creator",
    "defensive": "Defensive",
    "offensive": "Offensive",
    "central-dueler": "Central dueler",
    "aerial": "Aerial",
    "ball-progressor": "Ball progressor",
    "right-side-dueler": "Right side dueler (if back 3)",
    "left-side-dueler": "Left side dueler (if back 3)",
    "ball-winner": "Ball winner",
    "creator": "Creator",
    "running-threat": "Running threat",
    "goal-threat": "Goal threat",
    "ball-carrier": "Ball carrier",
    "presser": "Presser",
    "target-man": "Target man",
    "threat-in-behind": "Threat in behind",
    "link-creator": "Link / creator",
}

# Detailed prompts from the PDF; general prompts are short first-look versions.
PROFILE_PROMPTS: dict[str, dict[str, str]] = {
    "shot-stopper": {
        "general": "Shot stopping — first look.",
        "detailed": "Best saves? Weakness?",
    },
    "long-kicking": {
        "general": "Long kicking — first look.",
        "detailed": "Accurate? Distance?",
    },
    "short-kicking": {
        "general": "Short kicking — first look.",
        "detailed": "Join the backline?",
    },
    "box-goalkeeper": {
        "general": "Box goalkeeper — first look.",
        "detailed": "Catch or punch?",
    },
    "sweeper-keeper": {
        "general": "Sweeper keeper — first look.",
        "detailed": "How aggressive?",
    },
    "deep-creator": {
        "general": "Deep creator — first look.",
        "detailed": "Does he create and how?",
    },
    "defensive": {
        "general": "Defensive — first look.",
        "detailed": "Back post? Aerial? Dueler? High or low?",
    },
    "offensive": {
        "general": "Offensive — first look.",
        "detailed": "What types of chances? Ball carrier?",
    },
    "central-dueler": {
        "general": "Central dueler — first look.",
        "detailed": "Front foot or sweeper?",
    },
    "aerial": {
        "general": "Aerial — first look.",
        "detailed": "How aggressive? Types of headers?",
    },
    "ball-progressor": {
        "general": "Ball progressor — first look.",
        "detailed": "Short or long? Create? Sideways or forwards? Where from?",
    },
    "right-side-dueler": {
        "general": "Right side dueler (if back 3) — first look.",
        "detailed": "How does he duel on the right side of a back three?",
    },
    "left-side-dueler": {
        "general": "Left side dueler (if back 3) — first look.",
        "detailed": "How does he duel on the left side of a back three?",
    },
    "ball-winner": {
        "general": "Ball winner — first look.",
        "detailed": "High or low? Aggressive? Offensive interventions?",
    },
    "creator": {
        "general": "Creator — first look.",
        "detailed": "Does he break lines? Types of chances? Crosses?",
    },
    "running-threat": {
        "general": "Running threat — first look.",
        "detailed": "Into channels? Does he break lines?",
    },
    "goal-threat": {
        "general": "Goal threat — first look.",
        "detailed": "Types of shots / chances? How can we get him to score?",
    },
    "ball-carrier": {
        "general": "Ball carrier — first look.",
        "detailed": "Does he beat them?",
    },
    "presser": {
        "general": "Presser — first look.",
        "detailed": "Types of pressing? Does he work back? Regains? 2nd balls?",
    },
    "target-man": {
        "general": "Target man — first look.",
        "detailed": "Big? Feet or head? Aggressive?",
    },
    "threat-in-behind": {
        "general": "Threat in behind — first look.",
        "detailed": "Types of runs? Channels or in behind?",
    },
    "link-creator": {
        "general": "Link / creator — first look.",
        "detailed": "What sort of chances does he create?",
    },
}

GENERIC_PROMPTS = {
    "general": "What did you see in this part of his game?",
    "detailed": "Break this profile down. Be specific — actions, not just a score.",
}

_WEAK_FOOT_IDS = {key for key, _label in WEAK_FOOT_OPTIONS}
_STRONG_FOOT_IDS = {key for key, _label in STRONG_FOOT_OPTIONS}
_RATING_IDS = {row["id"] for row in PHYSICAL_FIELD_DEFS if row["kind"] == "rating"}
_ALL_PHYSICAL_IDS = {row["id"] for row in PHYSICAL_FIELD_DEFS}


def profile_id(name: str) -> str:
    token = strip_pv_prefix(name).casefold()
    token = re.sub(r"[^a-z0-9]+", "-", token).strip("-")
    return token or "profile"


def profile_label(name: str) -> str:
    pid = profile_id(name)
    if pid in PROFILE_LABELS:
        return PROFILE_LABELS[pid]
    return humanize_profile_name(name)


def prompts_for(name: str) -> dict[str, str]:
    return dict(PROFILE_PROMPTS.get(profile_id(name)) or GENERIC_PROMPTS)


def _is_goalkeeper(position: str) -> bool:
    return clean_position(position) == "GOALKEEPER"


def physical_field_defs_for_position(position: str = "") -> list[dict[str, Any]]:
    gk = _is_goalkeeper(position)
    out: list[dict[str, Any]] = []
    for row in PHYSICAL_FIELD_DEFS:
        scope = row["positions"]
        if scope == "all":
            out.append(dict(row))
        elif scope == "outfield" and not gk:
            out.append(dict(row))
        elif scope == "gk" and gk:
            out.append(dict(row))
    # When no position picked yet, show the full outfield set so scouts see every prompt.
    if not clean_position(position):
        return [dict(row) for row in PHYSICAL_FIELD_DEFS]
    return out


def empty_physical() -> dict[str, str]:
    return {key: "" for key in _ALL_PHYSICAL_IDS}


def empty_psychology() -> dict[str, str]:
    out = {key: "" for key, _label, _prompt in PSYCHOLOGY_FIELDS}
    out["notes"] = ""
    return out


def _clean_rating(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        rating = float(value)
    except (TypeError, ValueError):
        text = str(value or "").strip()
        return text[:2000] if text else ""
    if rating < 0 or rating > 10:
        return ""
    if rating == int(rating):
        return str(int(rating))
    return str(round(rating, 1))


def _clean_weak_foot(value: Any) -> str:
    token = str(value or "").strip().casefold().replace(" ", "_").replace("-", "_")
    aliases = {
        "verystrong": "very_strong",
        "v_strong": "very_strong",
        "medium": "mid",
        "avg": "mid",
        "average": "mid",
    }
    token = aliases.get(token, token)
    return token if token in _WEAK_FOOT_IDS else (str(value or "").strip()[:2000] if value else "")


def _clean_strong_foot(value: Any) -> str:
    token = str(value or "").strip().casefold()
    if token in _STRONG_FOOT_IDS:
        return token
    if token in {"l", "lf", "left foot", "left-footed"}:
        return "left"
    if token in {"r", "rf", "right foot", "right-footed"}:
        return "right"
    # Legacy free-text "foot" answers — keep as note text if not L/R.
    text = str(value or "").strip()
    return text[:2000] if text else ""


def clean_physical(row: Any) -> dict[str, str]:
    source = row if isinstance(row, dict) else {}
    out = empty_physical()

    # Migrate older keys from the previous form.
    if "strong_foot" not in source and source.get("foot"):
        source = {**source, "strong_foot": source.get("foot")}
    if "general_fitness" not in source and source.get("physical_ability"):
        source = {**source, "general_fitness": source.get("physical_ability")}

    for key in _ALL_PHYSICAL_IDS:
        raw = source.get(key)
        if key in _RATING_IDS:
            out[key] = _clean_rating(raw)
        elif key == "weak_foot":
            out[key] = _clean_weak_foot(raw)
        elif key == "strong_foot":
            out[key] = _clean_strong_foot(raw)
        else:
            out[key] = str(raw or "").strip()[:2000]
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
    wanted = clean_position(position) or clean_position(player_position)
    # Always use the PDF template for the selected role — scout notes attach to
    # those headings. Live Impect profile scores are optional extras only when
    # the player's listed position matches the role being reported.
    fallback: list[dict[str, Any]] = []
    for name in POSITION_PROFILES.get(wanted or "", ()):
        fallback.append(
            {
                "id": profile_id(name),
                "key": name,
                "label": profile_label(name),
                "score": None,
                "general_prompt": prompts_for(name)["general"],
                "detailed_prompt": prompts_for(name)["detailed"],
            }
        )
    if not fallback:
        return fallback

    same_role = bool(wanted) and clean_position(player_position) == wanted
    if same_role and player_profiles:
        by_id = {row["id"]: row for row in fallback}
        for row in player_profiles:
            if not isinstance(row, dict):
                continue
            raw = str(row.get("key") or row.get("label") or "").strip()
            if not raw:
                continue
            pid = profile_id(raw)
            if pid in by_id and row.get("score") is not None:
                by_id[pid]["score"] = row.get("score")
    return fallback


def option_fields() -> dict[str, Any]:
    physical_rows = [
        {
            "id": row["id"],
            "label": row["label"],
            "kind": row["kind"],
            "prompt": row["prompt"],
            "detailed_prompt": row["detailed_prompt"],
            "positions": row["positions"],
        }
        for row in PHYSICAL_FIELD_DEFS
    ]
    return {
        "positions": [
            {"id": code, "short": short, "label": label}
            for code, short, label in REPORT_POSITIONS
        ],
        "physical": physical_rows,
        "physical_by_position": {
            code: physical_field_defs_for_position(code)
            for code, _short, _label in REPORT_POSITIONS
        },
        "weak_foot_options": [
            {"id": key, "label": label} for key, label in WEAK_FOOT_OPTIONS
        ],
        "strong_foot_options": [
            {"id": key, "label": label} for key, label in STRONG_FOOT_OPTIONS
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
        "profiles_by_position": {
            code: profile_entries_for_position(code)
            for code, _short, _label in REPORT_POSITIONS
        },
    }
