from __future__ import annotations

import re
from typing import Any

from app.label_utils import humanize_metric_label, strip_pv_prefix

PROFILE_DEFINITION_ALIASES: dict[str, str] = {
    "pv box gk": "PV - Box Goalkeeper",
    "pv shot stopper": "PV - Shot Stopping Goal Keeper",
    "pv shot stopping gk": "PV - Shot Stopping Goal Keeper",
    "pv ball playing gk": "PV - Ball Playing Goal Keeper",
    "pv sweeper keeper": "PV - SWEEPER KEEPER",
    "pv sweeper gk": "PV - SWEEPER KEEPER",
}

_PROFILE_TOKEN_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bgk\b", "goalkeeper"),
    (r"\bstopper\b", "stopping"),
    (r"\bst\b", ""),
    (r"\bcm\b", ""),
    (r"\bcb\b", ""),
    (r"\blwb\b", ""),
    (r"\brwb\b", ""),
    (r"\brw\b", ""),
    (r"\blb\b", ""),
    (r"\brb\b", ""),
    (r"\bwr\b", ""),
    (r"\bwl\b", ""),
    (r"\bwinger\b", ""),
)

_STOP_WORDS = {"the", "a", "per", "game", "and", "or", "to", "in", "of", "by", "from", "-"}

FACTOR_SCORE_ALIASES: dict[str, str] = {
    "defensive_touches_in_packing_zone_fbl": "total_touches_in_packing_zone_fbl",
    "defensive_touches_in_packing_zone_fbr": "total_touches_in_packing_zone_fbr",
    "defensive_touches_in_packing_zone_cb": "total_touches_in_packing_zone_cb",
    "defensive_touches_in_packing_zone_cm": "total_touches_in_packing_zone_cm",
    "defensive_touches_in_packing_zone_dm": "total_touches_in_packing_zone_dm",
    "ball_win_removed_opponents_in_packing_zone_fbl": "ratio_removed_opponents",
    "ball_win_removed_opponents_in_packing_zone_fbr": "ratio_removed_opponents",
    "ball_win_removed_opponents_in_packing_zone_cb": "ratio_removed_opponents",
    "ball_win_removed_opponents_in_packing_zone_cm": "ratio_removed_opponents",
    "ball_win_removed_opponents_in_packing_zone_dm": "ratio_removed_opponents",
    "ball_win_removed_opponents_in_packing_zone_am": "ratio_removed_opponents",
    "ball_win_removed_opponents_in_packing_zone_wl": "ratio_removed_opponents",
    "ball_win_removed_opponents_in_packing_zone_wr": "ratio_removed_opponents",
    "ball_win_removed_opponents_in_packing_zone_ib": "ratio_removed_opponents",
    "ball_win_removed_opponents_in_packing_zone_ibwl": "ratio_removed_opponents",
    "ball_win_removed_opponents_in_packing_zone_ibwr": "ratio_removed_opponents",
    "ball_win_added_teammates_in_packing_zone_fbl": "ratio_added_teammates",
    "ball_win_added_teammates_in_packing_zone_fbr": "ratio_added_teammates",
    "ball_win_added_teammates_in_packing_zone_cb": "ratio_added_teammates",
    "ball_win_added_teammates_in_packing_zone_cm": "ratio_added_teammates",
    "ball_win_added_teammates_in_packing_zone_dm": "ratio_added_teammates",
    "ball_win_added_teammates": "ratio_added_teammates",
    "ball_win_added_teammates_defenders": "ratio_added_teammates_defenders",
    "ball_win_removed_opponents": "ratio_removed_opponents",
    "ball_win_removed_opponents_defenders": "ratio_removed_opponents_defenders",
    "ball_win_number_by_action_duel": "ground_duel_score",
    "ball_win_number_by_action_interception": "interception_score",
    "ball_win_number_by_action_loose_ball_regain": "loose_ball_regain_score",
    "catch_high_ball": "gk_caught_high_balls_percent",
    "save_high_ball": "gk_caught_and_punched_high_balls_percent",
    "bypassed_defenders": "deviation_bypassed_defenders",
    "bypassed_opponents": "suffered_bypassed_opponents",
    "bypassed_defenders_receiving": "deviation_bypassed_defenders",
    "bypassed_opponents_receiving": "suffered_bypassed_opponents",
    "bypassed_defenders_receiving_to_packing_zone_ib": "deviation_bypassed_defenders",
    "bypassed_opponents_receiving_to_packing_zone_ib": "suffered_bypassed_opponents",
    "bypassed_defenders_receiving_to_packing_zone_ibwl": "deviation_bypassed_defenders",
    "bypassed_opponents_receiving_to_packing_zone_ibwl": "suffered_bypassed_opponents",
    "bypassed_defenders_receiving_to_packing_zone_ibwr": "deviation_bypassed_defenders",
    "bypassed_opponents_receiving_to_packing_zone_ibwr": "suffered_bypassed_opponents",
    "bypassed_defenders_to_packing_zone_am": "deviation_bypassed_defenders",
    "bypassed_defenders_to_packing_zone_cm": "deviation_bypassed_defenders",
    "bypassed_defenders_to_packing_zone_ib": "deviation_bypassed_defenders",
    "bypassed_defenders_to_packing_zone_ibwl": "deviation_bypassed_defenders",
    "bypassed_defenders_to_packing_zone_ibwr": "deviation_bypassed_defenders",
    "bypassed_defenders_from_packing_zone_wl": "deviation_bypassed_defenders",
    "bypassed_defenders_from_packing_zone_am": "deviation_bypassed_defenders",
    "bypassed_defenders_from_packing_zone_ibwr": "deviation_bypassed_defenders",
    "bypassed_opponents_from_packing_zone_cb": "suffered_bypassed_opponents",
    "bypassed_opponents_from_packing_zone_cm": "suffered_bypassed_opponents",
    "bypassed_opponents_from_packing_zone_dm": "suffered_bypassed_opponents",
    "bypassed_opponents_from_packing_zone_am": "suffered_bypassed_opponents",
    "bypassed_opponents_from_packing_zone_fbl": "suffered_bypassed_opponents",
    "bypassed_opponents_from_packing_zone_fbr": "suffered_bypassed_opponents",
    "bypassed_opponents_from_packing_zone_ibwr": "suffered_bypassed_opponents",
    "bypassed_opponents_to_packing_zone_ib": "suffered_bypassed_opponents",
    "bypassed_opponents_to_packing_zone_ibwl": "suffered_bypassed_opponents",
    "bypassed_opponents_to_packing_zone_ibwr": "suffered_bypassed_opponents",
    "bypassed_opponents_receiving_to_packing_zone_cm": "suffered_bypassed_opponents",
    "ball_loss_removed_teammates": "ratio_added_opponents",
    "ball_loss_removed_teammates_defenders": "ratio_reverse_play_added_opponents",
    "critical_ball_loss_number": "unsuccessful_passes_clean",
    "conceded_goals": "gk_conceded_goals",
    "number_of_presses": "interventions_score_packing",
    "number_of_presses_build_up": "defensive_positional_play_score_packing",
    "number_of_presses_counter_press": "pxt_ball_win_delta_attack",
    "number_of_presses_between_the_lines": "availability_btl_score",
    "distance_to_goal_covered_dribble": "dribble_score",
    "offensive_touches_by_action_availability_in_the_back": "availability_out_wide_score",
    "offensive_touches_in_packing_zone_am": "total_touches_in_packing_zone_am",
    "offensive_touches_in_packing_zone_wl": "total_touches_in_packing_zone_wl",
    "offensive_touches_in_packing_zone_wr": "total_touches_in_packing_zone_wr",
    "offensive_touches_in_packing_zone_ibwl": "total_touches_in_packing_zone_ibwl",
    "offensive_touches_in_packing_zone_ibwr": "total_touches_in_packing_zone_ibwr",
    "successful_passes_by_action_low_pass": "low_pass_score",
    "successful_passes_by_action_high_cross": "high_cross_score",
    "successful_passes_by_action_low_cross": "low_cross_score",
    "successful_passes_by_action_header": "offensive_header_score",
    "successful_passes_by_action_short_aerial_pass": "short_aerial_pass_score",
    "goals": "ratio_minutes_per_goal",
    "assists": "ratio_minutes_per_assist",
    "shot_xg": "ratio_minutes_per_shot_xg",
    "postshot_xg": "ratio_postshot_xg_shot_xg",
    "goals_by_action_mid_range_shot": "mid_range_shot_score",
    "gk_minutes_per_postshot_xg": "ratio_minutes_per_shot_xg",
    "pxt_shot_at_pxt_phase_attack": "offensive_impect_score_pxt",
    "pxt_dribble_at_pxt_phase_attack": "offensive_impect_score_pxt",
    "pxt_ball_win": "pxt_ball_win_delta_attack",
    "def_pxt_foul_at_pxt_phase_defend": "def_pxt",
    "reverse_play_added_opponents": "ratio_added_teammates",
    "neutral_launch": "gk_successful_launches_percent",
}

# Profile factors reference KPIs that are not in the player-scores catalog. Proxies above
# use the closest available score; overrides adjust percentile direction where needed.
FACTOR_INVERT_OVERRIDES: dict[str, bool] = {
    "conceded_goals": False,
}

FACTOR_LABEL_OVERRIDES: dict[str, str] = {
    "prevented_goals_percent_shot_xg": "Prevented Goals % (shot xG)",
    "prevented_goals_percent_post_shot_xg": "Prevented Goals % (post-shot xG)",
    "prevented_goals_total_shot_xg": "Prevented Goals total (shot xG)",
    "prevented_goals_total_post_shot_xg": "Prevented Goals total (post-shot xG)",
    "gk_prevented_goals_percent_shot_xg": "Prevented Goals % (shot xG)",
    "gk_prevented_goals_percent_post_shot_xg": "Prevented Goals % (post-shot xG)",
    "gk_prevented_goals_total_shot_xg": "Prevented Goals total (shot xG)",
    "gk_prevented_goals_total_post_shot_xg": "Prevented Goals total (post-shot xG)",
    "conceded_goals": "Conceded goals",
    "ball_loss_removed_teammates": "Ball loss removed teammates",
    "ball_loss_removed_teammates_defenders": "Ball loss removed teammates (defenders)",
    "critical_ball_loss_number": "Critical ball losses",
    "number_of_presses": "Number of presses",
    "number_of_presses_build_up": "Presses during opponent build-up",
    "number_of_presses_counter_press": "Counter-presses",
    "number_of_presses_between_the_lines": "Presses between the lines",
    "distance_to_goal_covered_dribble": "Distance covered by dribbles",
    "offensive_touches_by_action_availability_in_the_back": "Availability at the back",
}


def normalize_factor_key(name: str) -> str:
    return str(name or "").strip().casefold().replace(" ", "_")


def profile_match_tokens(name: str) -> frozenset[str]:
    text = strip_pv_prefix(name).casefold()
    text = re.sub(r"[\(\)/]", " ", text)
    for pattern, replacement in _PROFILE_TOKEN_REPLACEMENTS:
        text = re.sub(pattern, f" {replacement} ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return frozenset(token for token in text.split() if token and token not in _STOP_WORDS)


def resolve_profile_definition(
    profile_name: str,
    definitions: dict[str, dict[str, Any]],
    *,
    is_pv_profile: Any,
) -> dict[str, Any] | None:
    normalized = str(profile_name or "").strip()
    if not normalized:
        return None

    if normalized in definitions:
        return definitions[normalized]

    lowered = normalized.casefold()
    if lowered in PROFILE_DEFINITION_ALIASES:
        alias_target = PROFILE_DEFINITION_ALIASES[lowered]
        if alias_target in definitions:
            return definitions[alias_target]

    for name, definition in definitions.items():
        if name.casefold() == lowered:
            return definition

    target_tokens = profile_match_tokens(normalized)
    if not target_tokens:
        return None

    best_name: str | None = None
    best_score = 0.0
    for name, definition in definitions.items():
        if not is_pv_profile(name):
            continue
        definition_tokens = profile_match_tokens(name)
        if not definition_tokens:
            continue
        overlap = len(target_tokens & definition_tokens)
        if overlap == 0:
            continue
        score = overlap / max(len(target_tokens), len(definition_tokens))
        if target_tokens.issubset(definition_tokens) or definition_tokens.issubset(target_tokens):
            score += 0.25
        if score > best_score:
            best_score = score
            best_name = name

    if best_name and best_score >= 0.6:
        return definitions[best_name]
    return None


def factor_catalog_candidates(
    factor_name: str,
    factor: dict[str, Any] | None = None,
) -> list[str]:
    key = normalize_factor_key(factor_name)
    candidates: list[str] = []

    def add(value: str) -> None:
        cleaned = str(value or "").strip().casefold()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    if factor is not None:
        offensive_proxy = offensive_bypass_score_name(factor)
        if offensive_proxy:
            add(offensive_proxy)

    add(key)
    add(FACTOR_SCORE_ALIASES.get(key, ""))

    if key == "conceded_goals":
        add("gk_conceded_goals")
        add("goals_conceded")
        add("gk_goals_conceded")

    for prefix in ("offensive_touches_in_packing_zone_", "defensive_touches_in_packing_zone_"):
        if key.startswith(prefix):
            add(f"total_touches_in_packing_zone_{key[len(prefix):]}")

    action_match = re.match(r"successful_passes_by_action_(.+)", key)
    if action_match:
        action = action_match.group(1)
        add(f"{action}_score")
        add(f"{action}_pass_score")

    if not key.endswith("_score"):
        add(f"{key}_score")

    return candidates


def is_offensive_bypass_factor(factor: dict[str, Any]) -> bool:
    factor_key = normalize_factor_key(str(factor.get("name", "")))
    return factor_key.startswith("bypassed_") and not bool(factor.get("inverted", False))


def offensive_bypass_score_name(factor: dict[str, Any]) -> str | None:
    """Ball-progressor style bypass KPIs: bypassing others, not being bypassed."""
    if not is_offensive_bypass_factor(factor):
        return None
    factor_key = normalize_factor_key(str(factor.get("name", "")))
    if "opponents" in factor_key:
        return "progression_score_packing"
    if "defenders" in factor_key:
        return "ratio_removed_opponents_defenders"
    return None


def resolve_factor_inverted(
    factor: dict[str, Any],
    catalog_entry: dict[str, Any],
) -> bool:
    factor_key = normalize_factor_key(str(factor.get("name", "")))
    if factor_key in FACTOR_INVERT_OVERRIDES:
        return FACTOR_INVERT_OVERRIDES[factor_key]
    if is_offensive_bypass_factor(factor):
        return False
    if "inverted" in factor:
        return bool(factor.get("inverted"))
    return bool(catalog_entry.get("inverted", False))


def humanize_factor_label(factor_name: str, *, offensive: bool = False) -> str:
    factor_key = normalize_factor_key(factor_name)
    if factor_key in FACTOR_LABEL_OVERRIDES:
        return FACTOR_LABEL_OVERRIDES[factor_key]

    text = factor_key
    text = re.sub(r"^bypassed_opponents", "bypassed opponents", text)
    text = re.sub(r"^bypassed_defenders", "bypassed defenders", text)
    text = text.replace("_from_packing_zone_", " from ")
    text = text.replace("_to_packing_zone_", " to ")
    text = text.replace("_receiving_to_packing_zone_", " receiving to ")
    text = text.replace("_receiving", " receiving")
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()

    from app.label_utils import _ZONE_REPLACEMENTS

    for pattern, replacement in _ZONE_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -")

    if not text:
        return humanize_metric_label(factor_name)

    if offensive:
        if text.startswith("bypassed opponents "):
            zone = text[len("bypassed opponents ") :].strip()
            return f"Opponents bypassed — {zone}" if zone else "Opponents bypassed"
        if text.startswith("bypassed defenders "):
            zone = text[len("bypassed defenders ") :].strip()
            return f"Defenders bypassed — {zone}" if zone else "Defenders bypassed"
        if text == "bypassed opponents":
            return "Opponents bypassed"
        if text == "bypassed defenders":
            return "Defenders bypassed"

    if text.startswith("bypassed opponents "):
        zone = text[len("bypassed opponents ") :].strip()
        return f"Opponents bypassed you — {zone}" if zone else "Opponents bypassed you"
    if text.startswith("bypassed defenders "):
        zone = text[len("bypassed defenders ") :].strip()
        return f"Defenders bypassed you — {zone}" if zone else "Defenders bypassed you"
    if text == "bypassed opponents":
        return "Opponents bypassed you"
    if text == "bypassed defenders":
        return "Defenders bypassed you"
    return humanize_metric_label(text)


def resolve_factor_label(
    factor: dict[str, Any],
    catalog_entry: dict[str, Any],
) -> str:
    factor_key = normalize_factor_key(str(factor.get("name", "")))
    if factor_key in FACTOR_LABEL_OVERRIDES:
        return FACTOR_LABEL_OVERRIDES[factor_key]
    if factor_key.startswith("bypassed_"):
        return humanize_factor_label(
            str(factor.get("name", "")),
            offensive=is_offensive_bypass_factor(factor),
        )
    raw_label = str(catalog_entry.get("label") or factor.get("name", "")).strip()
    return raw_label


def resolve_factor_score_id(
    factor: dict[str, Any],
    scores_by_name: dict[str, dict[str, Any]],
) -> int | None:
    factor_name = str(factor.get("name", "")).strip()
    if not factor_name:
        return None

    for candidate in factor_catalog_candidates(factor_name, factor):
        match = scores_by_name.get(candidate)
        if match:
            return int(match["id"])
    return None
