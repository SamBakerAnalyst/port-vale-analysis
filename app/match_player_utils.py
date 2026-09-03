"""Shared player display helpers used across match prep tools."""

from __future__ import annotations

from typing import Any

from app.pre_match import _position_label
from app.scouting import _format_height as format_player_height

POSITION_ABBR: dict[str, str] = {
    "GOALKEEPER": "GK",
    "CENTRAL_DEFENDER": "CH",
    "LEFT_WINGBACK_DEFENDER": "LB",
    "RIGHT_WINGBACK_DEFENDER": "RB",
    "DEFENSE_MIDFIELD": "DM",
    "CENTRAL_MIDFIELD": "CM",
    "ATTACKING_MIDFIELD": "AM",
    "LEFT_WINGER": "LW",
    "RIGHT_WINGER": "RW",
    "CENTER_FORWARD": "CF",
    "SECOND_STRIKER": "SS",
}


def _position_abbr(position: str | None) -> str:
    code = str(position or "").upper()
    if not code:
        return "—"
    return POSITION_ABBR.get(code, _position_label(position)[:3].upper())


def _height_short(player: dict[str, Any]) -> str:
    for key in ("heightCm", "height", "bodyHeight"):
        raw = player.get(key)
        if raw is None or raw == "":
            continue
        try:
            cm = int(float(raw))
        except (TypeError, ValueError):
            continue
        if cm <= 0:
            continue
        feet = int(cm // 30.48)
        inches = int(round((cm / 2.54) % 12))
        return f"{feet}'{inches}\""
    formatted = format_player_height(player)
    if formatted and "(" in formatted:
        return formatted.split("(", 1)[0].strip()
    return formatted or "—"
