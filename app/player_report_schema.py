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

PHYSICAL_FIELDS: tuple[tuple[str, str, str, str], ...] = (
    (
        "size",
        "Size",
        "Frame, height, strength in duels and hold-up.",
        "How big vs the opponent? Who wins aerials and hold-up, and how — first contact, second ball, pin?",
    ),
    (
        "mobility",
        "Mobility",
        "Pace over 10 yards, recovery runs, agility, change of direction.",
        "Pace over 10 yards, recovery, agility. Did they last, or drop off late? Turn and recover vs a runner?",
    ),
    (
        "foot",
        "Foot",
        "Preferred foot — range of pass, cross, shot.",
        "Preferred foot in this game — range of pass, cross, shot. What actions did they actually play with it?",
    ),
    (
        "weak_foot",
        "Weak foot",
        "Can they use it under pressure, or is it a liability?",
        "Can they use the weak foot under pressure? Did they hide it, or was it a real option to progress or finish?",
    ),
    (
        "physical_ability",
        "Physical ability",
        "Stamina, repeated sprints, how they lasted the game.",
        "Stamina, repeated sprints, duels won and lost. How they lasted — and what dropped off after 70?",
    ),
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

POSITION_PROFILES: dict[str, tuple[str, ...]] = {
    "GOALKEEPER": ("SHOT STOPPING", "BOX GOALKEEPER", "SWEEPER", "BALL PLAYING"),
    "CENTRAL_DEFENDER": ("DEFENSIVE", "DEFENDER", "PROGRESSOR", "BALL PLAYING"),
    "LEFT_WINGBACK_DEFENDER": (
        "DEFENDER",
        "OFFENSIVE",
        "DEEP CREATOR",
        "WIDE PRESSER",
        "WIDE BALL CARRIER",
        "WIDE CREATOR",
    ),
    "RIGHT_WINGBACK_DEFENDER": (
        "DEFENDER",
        "OFFENSIVE",
        "DEEP CREATOR",
        "WIDE PRESSER",
        "WIDE BALL CARRIER",
        "WIDE CREATOR",
    ),
    "DEFENSE_MIDFIELD": ("DEFENSIVE", "PROGRESSOR", "DEEP CREATOR", "PRESSER", "BALL CARRIER"),
    "CENTRAL_MIDFIELD": (
        "DEFENSIVE",
        "PROGRESSOR",
        "DEEP CREATOR",
        "PRESSER",
        "BALL CARRIER",
        "CREATOR",
    ),
    "ATTACKING_MIDFIELD": ("CREATOR", "GOAL THREAT", "PRESSER", "BALL CARRIER", "THREAT IN BEHIND"),
    "LEFT_WINGER": (
        "WIDE CREATOR",
        "WIDE GOAL THREAT",
        "WIDE PRESSER",
        "WIDE BALL CARRIER",
        "THREAT IN BEHIND",
    ),
    "RIGHT_WINGER": (
        "WIDE CREATOR",
        "WIDE GOAL THREAT",
        "WIDE PRESSER",
        "WIDE BALL CARRIER",
        "THREAT IN BEHIND",
    ),
    "CENTER_FORWARD": ("GOAL THREAT", "HOLD UP", "PRESSER", "THREAT IN BEHIND", "BALL CARRIER"),
}

PROFILE_PROMPTS: dict[str, dict[str, str]] = {
    "defender": {
        "general": "1v1s, positioning, and how they dealt with their man.",
        "detailed": "How do they defend 1v1 and in the box? What sort of headers do they win — attacking, defensive, flick-ons? Timing of tackles and recovery runs?",
    },
    "defensive": {
        "general": "How they protected the box and won the ball.",
        "detailed": "When do they step in vs sit off? What sort of headers do they win? Are they aggressive or calculated in duels?",
    },
    "offensive": {
        "general": "Overlaps, underlaps, end product from wide areas.",
        "detailed": "How do they progress the ball from that side — carry, combination, or cross? What type of crosses / cut-backs? End product vs just occupancy?",
    },
    "deep-creator": {
        "general": "Progressive passing and how they found teammates.",
        "detailed": "How do they progress the ball — line-break, switch, or set? What type of chances did they create, and from where? What happens when they are pressed?",
    },
    "creator": {
        "general": "Chance created, final ball, combinations.",
        "detailed": "How do they progress the ball into the box? Slip, cross, carry? Who did they find, and was it repeatable?",
    },
    "wide-creator": {
        "general": "Crossing, cut-backs, and chance created from the touchline.",
        "detailed": "How do they progress the ball from wide — early cross, drive inside, or combination? Quality of the delivery and who they aimed for.",
    },
    "progressor": {
        "general": "Carries and forward passing through the lines.",
        "detailed": "How do they progress the ball — carry through contact, or pass? Which line did they break, and what was the next action after?",
    },
    "ball-carrier": {
        "general": "Carries into space and through contact.",
        "detailed": "Do they carry into space or through contact? What is the end product after the carry? Where do they lose it?",
    },
    "wide-ball-carrier": {
        "general": "Drives from wide, 1v1s, and carrying inside.",
        "detailed": "How do they beat their full-back? Carry inside or stay wide? What happens after the take-on?",
    },
    "ball-playing": {
        "general": "Distribution under pressure, range, and composure.",
        "detailed": "How do they progress the ball from the back? Long vs short, weak-side switches, mistakes when pressed?",
    },
    "presser": {
        "general": "Pressing triggers, work rate, and ball wins.",
        "detailed": "When do they jump? Do they recover if they miss? Is the press coordinated or a solo hunt?",
    },
    "wide-presser": {
        "general": "Pressing from wide, tracking, and ball wins.",
        "detailed": "Do they lock the full-back in? Recovery if they dive in? How do they defend the counter after a high press?",
    },
    "goal-threat": {
        "general": "Movement for shots, finishing, box presence.",
        "detailed": "What type of chances — poacher, strike from range, header? Movement in the box and finishing technique. Missed looks?",
    },
    "wide-goal-threat": {
        "general": "Arrivals in the box and finishing from wide.",
        "detailed": "How do they get shots away from wide or the back post? Timing of arrivals vs staying outside.",
    },
    "threat-in-behind": {
        "general": "Runs in behind, timing, and finishing those looks.",
        "detailed": "When do they go? Do they hold the line or go early? Quality of the finish after the run.",
    },
    "hold-up": {
        "general": "Back to goal, pinning, and link play.",
        "detailed": "Who do they link with? Can they pin a centre-half and play around the corner? What sort of headers do they win?",
    },
    "shot-stopping": {
        "general": "Shot stopping, positioning, and handling.",
        "detailed": "What type of saves — reflex, 1v1, or claims? Handling under pressure and decision to come?",
    },
    "box-goalkeeper": {
        "general": "Command of the box, claims, and punching.",
        "detailed": "Do they claim or punch? Starting position on crosses. Communication with the back line?",
    },
    "sweeper": {
        "general": "Sweeps behind the line and starting position.",
        "detailed": "When do they leave the line? Speed off the line vs staying. Distribution after the sweep?",
    },
    "link-deep-play-maker": {
        "general": "Tempo, receiving on the half-turn, progressive passing.",
        "detailed": "How do they progress the ball from deep? Who do they find, and do they slow or speed the game?",
    },
}

GENERIC_PROMPTS = {
    "general": "What did you see in this part of his game?",
    "detailed": "Break this profile down. Why did it look good or poor? Specific actions — how they progress the ball, what headers they win, 1v1s — not just a score.",
}


def profile_id(name: str) -> str:
    token = strip_pv_prefix(name).casefold()
    token = re.sub(r"[^a-z0-9]+", "-", token).strip("-")
    return token or "profile"


def prompts_for(name: str) -> dict[str, str]:
    return dict(PROFILE_PROMPTS.get(profile_id(name)) or GENERIC_PROMPTS)


def empty_physical() -> dict[str, str]:
    return {key: "" for key, *_rest in PHYSICAL_FIELDS}


def empty_psychology() -> dict[str, str]:
    out = {key: "" for key, _label, _prompt in PSYCHOLOGY_FIELDS}
    out["notes"] = ""
    return out


def clean_physical(row: Any) -> dict[str, str]:
    source = row if isinstance(row, dict) else {}
    out = empty_physical()
    for key, *_rest in PHYSICAL_FIELDS:
        out[key] = str(source.get(key) or "").strip()[:2000]
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
    live: list[dict[str, Any]] = []
    same_role = bool(wanted) and clean_position(player_position) == wanted
    if same_role:
        for row in player_profiles or []:
            if not isinstance(row, dict):
                continue
            raw = str(row.get("key") or row.get("label") or "").strip()
            if not raw:
                continue
            live.append(
                {
                    "id": profile_id(raw),
                    "key": raw,
                    "label": humanize_profile_name(str(row.get("label") or raw)),
                    "score": row.get("score"),
                    "general_prompt": prompts_for(raw)["general"],
                    "detailed_prompt": prompts_for(raw)["detailed"],
                }
            )
    if live:
        return live
    fallback: list[dict[str, Any]] = []
    for name in POSITION_PROFILES.get(wanted or "", ()):
        fallback.append(
            {
                "id": profile_id(name),
                "key": name,
                "label": humanize_profile_name(name),
                "score": None,
                "general_prompt": prompts_for(name)["general"],
                "detailed_prompt": prompts_for(name)["detailed"],
            }
        )
    return fallback


def option_fields() -> dict[str, Any]:
    return {
        "positions": [
            {"id": code, "short": short, "label": label}
            for code, short, label in REPORT_POSITIONS
        ],
        "physical": [
            {
                "id": key,
                "label": label,
                "prompt": prompt,
                "detailed_prompt": detailed,
            }
            for key, label, prompt, detailed in PHYSICAL_FIELDS
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
