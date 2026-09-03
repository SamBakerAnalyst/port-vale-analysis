"""Meeting Front Pages — scout-report title PNGs for video presentations.

Identity card + one profile card per PV profile. Staff pick a player, tweak
copy/stats/cutout, then download a PNG pack for the video meeting.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlparse

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.label_utils import humanize_profile_name, strip_pv_prefix
from app.opponent_photos import (
    WEB_HEADERS,
    _duckduckgo_player_photo_url,
    _normalize_name_key,
    _name_tokens,
    _upgrade_portrait_url,
    _wikipedia_player_photo_url,
)
from app.paths import STANDALONE_DIR
from app.scouting import SCOUTING_DIR, _profiles_for_position

_PHOTO_SEARCH_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_PHOTO_SEARCH_TTL = 30 * 60
_PROXY_ALLOWED_HOST_SUFFIXES = (
    "transfermarkt.technology",
    "transfermarkt.co.uk",
    "tmssl.akamaized.net",
    "wikimedia.org",
    "wikipedia.org",
    "fotmob.com",
    "clubcast.co.uk",
    "portvale.co.uk",
    "gettyimages.com",
    "gettyimages.co.uk",
    "imago-images.com",
    "imago-images.de",
    "premierleague.com",
    "efl.com",
    "skysports.com",
    "bbc.co.uk",
    "bt.com",
    "duckduckgo.com",
    "external-content.duckduckgo.com",
    "bing.com",
    "bing.net",
    "pinimg.com",
    "wp.com",
    "cloudfront.net",
    "googleusercontent.com",
)

# Presentation titles → default clip bullets (editable in the UI).
PROFILE_BULLET_DEFAULTS: dict[str, list[str]] = {
    "WIDE CREATOR": ["CROSSING", "CHANCE CREATED"],
    "CREATOR": ["CROSSING", "CHANCE CREATED"],
    "DEEP CREATOR": ["PROGRESSIVE PASSES", "CHANCE CREATED"],
    "WIDE GOAL THREAT": ["GOALS SCORED", "SHOTS AND CHANCES"],
    "GOAL THREAT": ["GOALS SCORED", "SHOTS AND CHANCES"],
    "THREAT IN BEHIND": ["RUNS IN BEHIND", "GOALS SCORED"],
    "HOLD UP": ["HOLD UP PLAY", "LINK PLAY"],
    "PRESSER": ["PRESSING", "BALL WINS"],
    "WIDE PRESSER": ["PRESSING", "BALL WINS"],
    "BALL CARRIER": ["CARRIES", "PROGRESSIVE ACTIONS"],
    "WIDE BALL CARRIER": ["CARRIES", "PROGRESSIVE ACTIONS"],
    "BALL PLAYING": ["DISTRIBUTION", "SWEEPING"],
    "BOX GOALKEEPER": ["SHOT STOPPING", "COMMAND OF BOX"],
    "SHOT STOPPING": ["SHOT STOPPING", "REFLEXES"],
    "SWEEPER": ["SWEEPING", "DISTRIBUTION"],
    "LINK / DEEP PLAY MAKER": ["PROGRESSIVE PASSES", "TEMPO"],
    "DEFENSIVE": ["DUELS", "DEFENSIVE ACTIONS"],
    "PROGRESSOR": ["CARRIES", "PROGRESSIVE PASSES"],
}

# Pitch dots: x 0–100 (left→right), y 0–100 (attacking end at top).
PITCH_POSITIONS: list[dict[str, Any]] = [
    {"code": "GOALKEEPER", "abbr": "GK", "x": 50, "y": 92},
    {"code": "LEFT_WINGBACK_DEFENDER", "abbr": "LB", "x": 12, "y": 72},
    {"code": "CENTRAL_DEFENDER", "abbr": "CB", "x": 38, "y": 78},
    {"code": "CENTRAL_DEFENDER_R", "abbr": "CB", "x": 62, "y": 78},
    {"code": "RIGHT_WINGBACK_DEFENDER", "abbr": "RB", "x": 88, "y": 72},
    {"code": "DEFENSE_MIDFIELD", "abbr": "DM", "x": 50, "y": 58},
    {"code": "LEFT_WINGBACK_DEFENDER_WB", "abbr": "WB", "x": 12, "y": 48},
    {"code": "CENTRAL_MIDFIELD", "abbr": "CM", "x": 38, "y": 48},
    {"code": "CENTRAL_MIDFIELD_R", "abbr": "CM", "x": 62, "y": 48},
    {"code": "RIGHT_WINGBACK_DEFENDER_WB", "abbr": "WB", "x": 88, "y": 48},
    {"code": "LEFT_MIDFIELD", "abbr": "LM", "x": 18, "y": 36},
    {"code": "ATTACKING_MIDFIELD", "abbr": "AM", "x": 50, "y": 32},
    {"code": "RIGHT_MIDFIELD", "abbr": "RM", "x": 82, "y": 36},
    {"code": "LEFT_WINGER", "abbr": "LW", "x": 18, "y": 18},
    {"code": "RIGHT_WINGER", "abbr": "RW", "x": 82, "y": 18},
    {"code": "CENTER_FORWARD", "abbr": "CF", "x": 50, "y": 10},
]

_WIDE_CODES = {
    "LEFT_WINGBACK_DEFENDER",
    "RIGHT_WINGBACK_DEFENDER",
    "LEFT_BACK",
    "RIGHT_BACK",
    "LEFT_WINGER",
    "RIGHT_WINGER",
    "LEFT_MIDFIELD",
    "RIGHT_MIDFIELD",
}

_POSITION_DISPLAY: dict[str, str] = {
    "GOALKEEPER": "GOALKEEPER",
    "CENTRAL_DEFENDER": "CENTRE BACK",
    "LEFT_WINGBACK_DEFENDER": "LEFT WING BACK",
    "RIGHT_WINGBACK_DEFENDER": "RIGHT WING BACK",
    "LEFT_BACK": "LEFT BACK",
    "RIGHT_BACK": "RIGHT BACK",
    "DEFENSE_MIDFIELD": "DEFENSIVE MIDFIELD",
    "CENTRAL_MIDFIELD": "CENTRAL MIDFIELD",
    "ATTACKING_MIDFIELD": "ATTACKING MIDFIELD",
    "LEFT_MIDFIELD": "LEFT MIDFIELD",
    "RIGHT_MIDFIELD": "RIGHT MIDFIELD",
    "LEFT_WINGER": "LEFT WING",
    "RIGHT_WINGER": "RIGHT WING",
    "CENTER_FORWARD": "CENTRE FORWARD",
    "SECOND_STRIKER": "SECOND STRIKER",
}


def _impect():
    from app import main as impect_main

    return impect_main


def _split_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in str(full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0].upper()
    return parts[0].upper(), " ".join(parts[1:]).upper()


def _birth_year(birthdate: Any) -> str | None:
    text = str(birthdate or "").strip()
    if not text:
        return None
    match = re.match(r"^(\d{4})", text)
    if match:
        return match.group(1)
    match = re.search(r"(\d{4})", text)
    return match.group(1) if match else None


def _age_line(age: Any, birthdate: Any) -> str:
    year = _birth_year(birthdate)
    if age is not None and year:
        return f"{int(age)} Y/O ({year})"
    if age is not None:
        return f"{int(age)} Y/O"
    if year:
        return f"({year})"
    return "—"


def _height_display(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text or text == "—":
        return "—"
    # Prefer feet form without cm suffix: 6'1" or 6'1
    if "'" in text or "ft" in text.casefold():
        feet = text.split("(", 1)[0].strip().rstrip('"')
        feet = re.sub(r"\s*ft\s*", "'", feet, flags=re.I)
        feet = re.sub(r"\s*in\s*", "", feet, flags=re.I).strip()
        # Guard against Impect/TM placeholders like 0'0
        if re.match(r"^0+'0*$", feet.replace(" ", "")):
            return "—"
        return feet
    # Plain cm
    try:
        cm = int(round(float(text)))
    except (TypeError, ValueError):
        return text
    from app.set_piece_pre_match import _height_label_from_cm

    labeled = _height_label_from_cm(cm)
    return labeled if labeled != "—" else "—"


def _club_for_web_lookup(club: str | None) -> str | None:
    """Strip academy / U21 suffixes so Transfermarkt search hits the senior profile."""
    text = str(club or "").strip()
    if not text or text == "—":
        return None
    cleaned = re.sub(
        r"\s*(U\d{2}|Under[-\s]?\d{2}|Youth|Academy|Reserves?|II|B)\s*$",
        "",
        text,
        flags=re.I,
    ).strip(" -–—")
    return cleaned or text


def _tm_position_to_code(raw: Any) -> str | None:
    """Map Transfermarkt position labels onto Impect position codes."""
    text = str(raw or "").casefold()
    if not text:
        return None
    rules: list[tuple[str, str]] = [
        ("goalkeeper", "GOALKEEPER"),
        ("left winger", "LEFT_WINGER"),
        ("right winger", "RIGHT_WINGER"),
        ("left midfield", "LEFT_MIDFIELD"),
        ("right midfield", "RIGHT_MIDFIELD"),
        ("attacking midfield", "ATTACKING_MIDFIELD"),
        ("defensive midfield", "DEFENSE_MIDFIELD"),
        ("central midfield", "CENTRAL_MIDFIELD"),
        ("centre-forward", "CENTER_FORWARD"),
        ("center-forward", "CENTER_FORWARD"),
        ("centre forward", "CENTER_FORWARD"),
        ("center forward", "CENTER_FORWARD"),
        ("second striker", "SECOND_STRIKER"),
        ("left-back", "LEFT_WINGBACK_DEFENDER"),
        ("left back", "LEFT_WINGBACK_DEFENDER"),
        ("right-back", "RIGHT_WINGBACK_DEFENDER"),
        ("right back", "RIGHT_WINGBACK_DEFENDER"),
        ("centre-back", "CENTRAL_DEFENDER"),
        ("center-back", "CENTRAL_DEFENDER"),
        ("centre back", "CENTRAL_DEFENDER"),
        ("center back", "CENTRAL_DEFENDER"),
    ]
    for needle, code in rules:
        if needle in text:
            return code
    if "winger" in text and "left" in text:
        return "LEFT_WINGER"
    if "winger" in text and "right" in text:
        return "RIGHT_WINGER"
    return None


def _ensure_transfermarkt(
    player_name: str,
    club_raw: str | None,
    tm: dict[str, Any] | None,
) -> dict[str, Any]:
    """Always try to fill Transfermarkt bio — U21 club names often miss on first pass."""
    out = dict(tm or {})
    has_height = bool(out.get("height") or out.get("height_cm"))
    complete = has_height and out.get("position") and out.get("photo_url") and out.get("foot")
    if complete:
        return out
    try:
        from app.player_web_enrichment import fetch_transfermarkt_player_profile
    except Exception:
        return out

    attempts = [
        _club_for_web_lookup(club_raw),
        club_raw if club_raw and club_raw != "—" else None,
        None,
    ]
    seen: set[str] = set()
    for club_try in attempts:
        key = _normalize_name_key(club_try or "")
        if key in seen:
            continue
        seen.add(key)
        try:
            fetched = fetch_transfermarkt_player_profile(player_name, club_name=club_try)
        except Exception:
            fetched = None
        if not fetched:
            continue
        for field, value in fetched.items():
            if value is None or value == "":
                continue
            if field in {"height", "height_cm", "photo_url", "position", "foot", "market_value"}:
                out[field] = value
            elif not out.get(field):
                out[field] = value
        if out.get("height") or out.get("height_cm"):
            break
    return out


def _foot_display(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if not text or text in {"—", "-", "N/A"}:
        return "—"
    if "LEFT" in text or text == "L":
        return "LEFT"
    if "RIGHT" in text or text == "R":
        return "RIGHT"
    if "BOTH" in text:
        return "BOTH"
    return text


def _transfer_type(tm: dict[str, Any] | None, club: str | None) -> str:
    if tm and tm.get("on_loan_from"):
        return "LOAN"
    club_u = str(club or "").upper()
    if "PORT VALE" in club_u:
        return "PERMANENT"
    return "—"


def _presentation_title(api_name: str, label: str, primary_position: str | None) -> str:
    """Uppercase meeting title; prefix WIDE for flank roles when profile is generic."""
    base = strip_pv_prefix(api_name) or label or humanize_profile_name(api_name)
    base = re.sub(r"\s*[\(\[].*?[\)\]]\s*", " ", base)
    # Drop side tags Impect appends: " - LEFT", " RIGHT", "/LWB", etc.
    base = re.sub(
        r"[\s\-/]*(?:LEFT|RIGHT|LWB|RWB|LB|RB|LW|RW|LM|RM)\s*$",
        "",
        base,
        flags=re.IGNORECASE,
    )
    base = re.sub(r"\s*[-–—]\s*$", "", base)
    base = re.sub(r"\s+", " ", base).strip().upper()
    if not base:
        return "PROFILE"
    if "WIDE" in base:
        return base
    if primary_position in _WIDE_CODES and base in {
        "CREATOR",
        "GOAL THREAT",
        "PROGRESSOR",
        "PRESSER",
        "BALL CARRIER",
    }:
        return f"WIDE {base}"
    return base


def _bullets_for_title(title: str) -> list[str]:
    upper = title.upper().strip()
    if upper in PROFILE_BULLET_DEFAULTS:
        return list(PROFILE_BULLET_DEFAULTS[upper])
    for key, bullets in PROFILE_BULLET_DEFAULTS.items():
        if key in upper or upper in key:
            return list(bullets)
    return ["KEY STRENGTH", "KEY ACTION"]


def _position_line(positions: list[dict[str, Any]], primary: str | None) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    ordered_codes: list[str] = []
    if primary:
        ordered_codes.append(primary)
    for row in positions or []:
        code = str(row.get("code") or row.get("position") or "").upper()
        if code and code not in ordered_codes:
            ordered_codes.append(code)
    for code in ordered_codes[:3]:
        label = _POSITION_DISPLAY.get(code) or code.replace("_", " ")
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return " / ".join(labels) if labels else "—"


def _highlight_pitch(primary: str | None, positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return pitch dots with green (high mins) / amber (low mins) for played roles."""
    # Build minutes + share lookup for every played code.
    by_code: dict[str, dict[str, Any]] = {}
    if primary:
        by_code[str(primary).upper()] = {"minutes": 0.0, "match_share": 100.0}
    for row in positions or []:
        code = str(row.get("code") or row.get("position") or "").upper()
        if not code:
            continue
        entry = by_code.setdefault(code, {"minutes": 0.0, "match_share": 0.0})
        try:
            entry["minutes"] = max(float(entry["minutes"]), float(row.get("minutes") or 0))
        except (TypeError, ValueError):
            pass
        try:
            entry["match_share"] = max(
                float(entry["match_share"]), float(row.get("match_share") or 0)
            )
        except (TypeError, ValueError):
            pass

    total_minutes = sum(float(v.get("minutes") or 0) for v in by_code.values())
    # Green = main role / lots of minutes; amber = cameo / low share.
    GREEN_SHARE = 25.0  # percent of minutes or match_share

    def role_state(code: str) -> str:
        meta = by_code.get(code) or {}
        minutes = float(meta.get("minutes") or 0)
        share = float(meta.get("match_share") or 0)
        if total_minutes > 0 and minutes > 0:
            pct = 100.0 * minutes / total_minutes
        else:
            pct = share
        # Single known role with no minute breakdown → treat as primary green.
        if code == (str(primary).upper() if primary else None) and len(by_code) == 1:
            return "primary"
        if pct >= GREEN_SHARE or (code == (str(primary).upper() if primary else None) and pct >= 15):
            return "primary"
        if minutes > 0 or share > 0 or code in by_code:
            return "secondary"
        return "idle"

    def matches(dot_code: str, player_code: str) -> bool:
        if dot_code == player_code:
            return True
        aliases = {
            "LEFT_BACK": "LEFT_WINGBACK_DEFENDER",
            "RIGHT_BACK": "RIGHT_WINGBACK_DEFENDER",
            "LEFT_WINGBACK_DEFENDER_WB": "LEFT_WINGBACK_DEFENDER",
            "RIGHT_WINGBACK_DEFENDER_WB": "RIGHT_WINGBACK_DEFENDER",
            "CENTRAL_DEFENDER_R": "CENTRAL_DEFENDER",
            "CENTRAL_MIDFIELD_R": "CENTRAL_MIDFIELD",
        }
        return aliases.get(dot_code) == player_code or aliases.get(player_code) == dot_code

    dots: list[dict[str, Any]] = []
    for dot in PITCH_POSITIONS:
        code = str(dot["code"])
        state = "idle"
        label = None
        # Prefer exact player codes; skip dual-dot aliases unless they map.
        matched_player: str | None = None
        for player_code in by_code:
            if matches(code, player_code):
                matched_player = player_code
                break
        if matched_player:
            state = role_state(matched_player)
            if state == "primary":
                label = str(dot["abbr"])
            elif state == "secondary":
                label = str(dot["abbr"])
        dots.append(
            {
                "code": code,
                "abbr": dot["abbr"],
                "x": dot["x"],
                "y": dot["y"],
                "state": state,
                "label": label,
            }
        )
    return dots


def _pitch_roles_from_dots(dots: list[dict[str, Any]], primary: str | None) -> list[dict[str, Any]]:
    """Compact role list for formation maps (code + highlight state)."""
    abbr_by_code = {str(dot["code"]): str(dot["abbr"]) for dot in PITCH_POSITIONS}
    roles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for dot in dots:
        code = str(dot.get("code") or "").upper()
        state = str(dot.get("state") or "idle")
        if not code or state == "idle" or code in seen:
            continue
        # Skip synthetic dual-dot aliases — keep one CB / CM code.
        if code.endswith("_R") or code.endswith("_WB"):
            base = code.replace("_R", "").replace("_WB", "")
            if base in seen:
                continue
            code = base if base in abbr_by_code else code
        seen.add(code)
        roles.append(
            {
                "code": code,
                "abbr": abbr_by_code.get(code) or str(dot.get("abbr") or code[:2]),
                "state": state,
            }
        )
    if primary:
        code = str(primary).upper()
        if code not in seen:
            roles.insert(
                0,
                {
                    "code": code,
                    "abbr": abbr_by_code.get(code) or code.replace("_", " ")[:3],
                    "state": "primary",
                },
            )
    return roles


def _pitch_roles(primary: str | None, positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _pitch_roles_from_dots(_highlight_pitch(primary, positions), primary)


def _career_stats(dossier: dict[str, Any]) -> dict[str, Any]:
    player = dossier.get("player") or {}
    web = dossier.get("web") or {}
    fbref = web.get("fbref") if isinstance(web.get("fbref"), dict) else {}
    tm = web.get("transfermarkt") if isinstance(web.get("transfermarkt"), dict) else {}
    career = fbref.get("career") if isinstance(fbref.get("career"), dict) else {}
    tm_career = tm.get("career") if isinstance(tm.get("career"), dict) else {}

    def num(*values: Any) -> int | None:
        for value in values:
            if value is None or value == "" or value == "—":
                continue
            try:
                return int(round(float(value)))
            except (TypeError, ValueError):
                continue
        return None

    # Prefer FBref career, then Transfermarkt career, then season / Impect.
    games = num(
        career.get("matches"),
        fbref.get("career_matches"),
        tm_career.get("appearances"),
        tm_career.get("matches"),
        fbref.get("matches"),
        player.get("matches"),
    )
    starts = num(
        career.get("starts"),
        fbref.get("career_starts"),
        tm_career.get("starts"),
        fbref.get("starts"),
    )
    minutes = num(
        career.get("minutes"),
        fbref.get("career_minutes"),
        tm_career.get("minutes"),
        fbref.get("minutes"),
        player.get("minutes"),
    )
    goals = num(
        career.get("goals"),
        fbref.get("career_goals"),
        tm_career.get("goals"),
        fbref.get("goals"),
    )
    assists = num(
        career.get("assists"),
        fbref.get("career_assists"),
        tm_career.get("assists"),
        fbref.get("assists"),
    )

    for row in dossier.get("hero_stats") or []:
        key = str(row.get("key") or "").lower()
        value = row.get("value")
        if key in {"goals", "fbref_goals"} and goals is None:
            goals = num(value)
        if key in {"assists", "fbref_assists"} and assists is None:
            assists = num(value)
        if key in {"matches", "games"} and games is None:
            games = num(value)

    if games is None and minutes is not None and minutes > 0:
        games = max(1, int(round(minutes / 90.0))) if minutes >= 45 else 1
    # Bench cameos: 1 game + sub minutes → 0 starts (editable).
    if starts is None and games is not None and minutes is not None and minutes < (games * 90):
        starts = max(0, min(games, int(minutes // 60))) if minutes >= 60 else 0
        if games == 1 and minutes < 90:
            starts = 0

    has_career = bool(career.get("matches") or fbref.get("career_matches") or tm_career.get("appearances"))
    has_fbref = bool(fbref and (fbref.get("matches") or fbref.get("minutes")))
    has_tm = bool(tm_career)
    if career.get("matches") or fbref.get("career_matches"):
        source = "fbref_career"
        note = "Career totals from FBref (domestic leagues) — edit before export if needed."
    elif has_tm:
        source = "transfermarkt"
        note = "Career totals from Transfermarkt — edit before export if needed."
    elif has_fbref:
        source = "fbref"
        note = "FBref season stats prefilled — edit to career totals before export."
    elif player.get("minutes"):
        source = "impect"
        note = "Season minutes from Impect — edit to full career totals before export."
    else:
        source = None
        note = "Enter career totals before export."

    # When we only have season minutes, still show 0 for blank goal lines so the slide
    # doesn't look half-empty — staff can overwrite in the editor.
    fill_zero = bool(has_career or minutes)
    return {
        "title": "CAREER",
        "games": games,
        "starts": starts,
        "minutes": minutes,
        "goals": goals if goals is not None else (0 if fill_zero else None),
        "assists": assists if assists is not None else (0 if fill_zero else None),
        "source": source,
        "fbrefUrl": fbref.get("profile_url"),
        "note": note,
        "market_value": (tm or {}).get("market_value"),
    }


def _profile_cards(
    dossier: dict[str, Any],
    *,
    primary_position: str | None,
) -> list[dict[str, Any]]:
    scored = {
        str(row.get("name") or ""): row
        for row in (dossier.get("profiles") or [])
        if row.get("name")
    }

    api_names: list[str] = []
    if primary_position:
        try:
            api_names = _profiles_for_position(primary_position)
        except Exception:
            api_names = []
    if not api_names:
        api_names = list(scored.keys())

    # Positional-group set — every profile for this role gets a slide.
    group_names = set(api_names)

    cards: list[dict[str, Any]] = []
    for api_name in api_names:
        score_row = scored.get(api_name) or {}
        label = str(score_row.get("label") or humanize_profile_name(api_name))
        title = _presentation_title(api_name, label, primary_position)
        cards.append(
            {
                "apiName": api_name,
                "label": label,
                "title": title,
                "bullets": _bullets_for_title(title),
                "scorePct": score_row.get("pct"),
                # Auto-load ALL profiles for the positional group.
                "selected": True,
            }
        )

    # Also keep any scored profiles outside the group (unticked by default).
    known = {c["apiName"] for c in cards}
    for api_name, score_row in scored.items():
        if api_name in known:
            continue
        label = str(score_row.get("label") or humanize_profile_name(api_name))
        title = _presentation_title(api_name, label, primary_position)
        cards.append(
            {
                "apiName": api_name,
                "label": label,
                "title": title,
                "bullets": _bullets_for_title(title),
                "scorePct": score_row.get("pct"),
                "selected": False,
            }
        )

    # Last resort: still no cards (unknown position) — seed wide attacker defaults.
    if not cards:
        for title in ("WIDE PRESSER", "WIDE BALL CARRIER", "WIDE CREATOR", "WIDE GOAL THREAT"):
            cards.append(
                {
                    "apiName": title,
                    "label": title,
                    "title": title,
                    "bullets": _bullets_for_title(title),
                    "scorePct": None,
                    "selected": True,
                }
            )

    # If we somehow have a group with zero selected, force the group on.
    if cards and group_names and not any(c["selected"] for c in cards):
        for card in cards:
            if card["apiName"] in group_names:
                card["selected"] = True

    cards.sort(
        key=lambda c: (
            not c["selected"],
            -(c.get("scorePct") if c.get("scorePct") is not None else -1),
            c["title"],
        )
    )
    return cards


def _format_p90_value(value: float) -> str:
    """Impect player-score rates — show clean P90 figures (not % labels)."""
    if value != value:  # NaN
        return "—"
    abs_v = abs(value)
    if abs_v >= 100:
        return str(int(round(value)))
    if abs_v >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    if abs_v >= 1:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    # Sub-1 rates stay as decimals (e.g. 0.46) — never % on this slide.
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _build_p90_stats(
    player_id: int,
    *,
    iteration_id: int | None,
    squad_id: int | None,
    position: str | None,
    profile_api_names: list[str],
    limit: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Best / weakest P90 stats from Impect player-scores for this role."""
    if iteration_id is None or squad_id is None or not position:
        return [], []

    impect = _impect()
    try:
        score_rows, _ = impect._fetch_player_scores(
            int(iteration_id), int(squad_id), [str(position)], 0
        )
    except Exception:
        return [], []

    row = next(
        (r for r in score_rows if int(r.get("playerId") or 0) == int(player_id)),
        None,
    )
    if row is None:
        return [], []

    try:
        scores_by_id, scores_by_name = impect._fetch_player_score_catalog()
        definitions = impect._fetch_player_profile_definitions()
    except Exception:
        return [], []

    # Stats that feed this player's PV profiles — the ones coaches care about.
    wanted: dict[int, dict[str, Any]] = {}
    for api_name in profile_api_names:
        definition = impect._resolve_profile_definition(str(api_name), definitions)
        if not definition:
            continue
        for factor in definition.get("factors") or []:
            if not isinstance(factor, dict):
                continue
            score_id = impect._resolve_factor_score_id(factor, scores_by_name)
            if score_id is None:
                continue
            catalog = scores_by_id.get(int(score_id)) or {}
            from app.profile_resolve import resolve_factor_inverted, resolve_factor_label
            from app.label_utils import humanize_metric_label

            factor_name = str(factor.get("name") or "").strip()
            raw_label = resolve_factor_label(factor, catalog)
            if not raw_label or raw_label.casefold() in {"none", "n/a", "null", "-"}:
                raw_label = factor_name
            if not raw_label:
                continue
            label = (
                humanize_metric_label(raw_label)
                if not factor_name.casefold().startswith("bypassed_")
                else raw_label
            )
            weight = float(factor.get("weight") or 0.0)
            prev = wanted.get(int(score_id))
            if prev is None or weight > float(prev.get("weight") or 0):
                wanted[int(score_id)] = {
                    "scoreId": int(score_id),
                    "label": label,
                    "weight": weight,
                    "inverted": bool(resolve_factor_inverted(factor, catalog)),
                }

    if not wanted:
        return [], []

    stats: list[dict[str, Any]] = []
    for score_id, meta in wanted.items():
        value = impect._player_score_value(row, score_id)
        if value is None:
            continue
        cohort = impect._cohort_values_for_key(
            score_rows, "playerScoreId", score_id, "playerScores"
        )
        standing = impect._factor_standing(
            value, cohort, inverted=bool(meta.get("inverted"))
        )
        # Prefer standing; fall back to weight so we still fill 5 slots.
        rank_key = float(standing) if standing is not None else float(meta.get("weight") or 0)
        stats.append(
            {
                "scoreId": score_id,
                "label": str(meta["label"]).upper(),
                "value": round(float(value), 4),
                "valueLabel": _format_p90_value(float(value)),
                "unit": "P90",
                "standingPct": round(standing) if standing is not None else None,
                "_rank": rank_key,
            }
        )

    stats.sort(key=lambda item: float(item.get("_rank") or 0), reverse=True)
    best = [{k: v for k, v in row.items() if k != "_rank"} for row in stats[:limit]]
    worst = [
        {k: v for k, v in row.items() if k != "_rank"}
        for row in list(reversed(stats[-limit:])) if len(stats) >= 2
    ]
    return best, worst


def _profiles_for_exact_position(
    iteration_id: int,
    squad_id: int,
    player_id: int,
    position: str,
) -> tuple[list[dict[str, Any]], float | None]:
    """PV profile scores for one Impect position (does not fall through to others)."""
    from app.player_dossier import _impect
    from app.label_utils import humanize_profile_name, strip_pv_prefix

    impect = _impect()
    try:
        score_rows, _ = impect._fetch_profile_scores(iteration_id, squad_id, [position], 0)
    except Exception:
        return [], None
    row = next((r for r in score_rows if int(r.get("playerId") or 0) == player_id), None)
    if row is None:
        return [], None
    minutes = impect._play_duration_minutes(row)
    profiles: list[dict[str, Any]] = []
    for score in row.get("profileScores") or []:
        if not isinstance(score, dict):
            continue
        name = str(score.get("profileName") or "").strip()
        if not name or not impect._is_pv_profile(name):
            continue
        value = score.get("value")
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        label = strip_pv_prefix(name)
        label = re.sub(r"\s*[\-\(].*$", "", label).replace("_", " ").strip()
        label = label or humanize_profile_name(name)
        title = _presentation_title(name, label, position)
        profiles.append(
            {
                "apiName": name,
                "label": label,
                "title": title,
                "scorePct": round(numeric * 100),
            }
        )
    profiles.sort(key=lambda item: item["scorePct"], reverse=True)
    return profiles, minutes


def _build_data_summary(
    player_id: int,
    *,
    dossier: dict[str, Any],
    primary: str | None,
    positions: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> dict[str, Any]:
    """Data slide payload — scores by position / season + best & worst."""
    from app.player_dossier import _resolve_catalog_player

    player = dossier.get("player") or {}
    iter_id = player.get("iteration_id")
    squad_id = player.get("squad_id")
    scored = [
        {
            "apiName": str(row.get("name") or ""),
            "label": str(row.get("label") or ""),
            "title": _presentation_title(
                str(row.get("name") or ""),
                str(row.get("label") or ""),
                primary,
            ),
            "scorePct": row.get("pct"),
        }
        for row in (profiles or [])
        if row.get("pct") is not None
    ]
    scored.sort(key=lambda item: float(item.get("scorePct") or 0), reverse=True)

    best = scored[:3]
    worst = list(reversed(scored[-3:])) if len(scored) >= 2 else []

    profile_api_names = [
        str(row.get("apiName") or row.get("name") or "")
        for row in (profiles or [])
        if row.get("apiName") or row.get("name")
    ]
    best_stats, worst_stats = _build_p90_stats(
        int(player_id),
        iteration_id=int(iter_id) if iter_id is not None else None,
        squad_id=int(squad_id) if squad_id is not None else None,
        position=str(primary) if primary else None,
        profile_api_names=profile_api_names,
        limit=5,
    )

    catalog = None
    try:
        catalog = _resolve_catalog_player(int(player_id))
    except Exception:
        catalog = None
    squad_map = (catalog or {}).get("squad_ids_by_iteration") or {}
    # Current season first, then at most two older chartable seasons.
    seasons = list(dossier.get("seasons") or [])
    season_rows: list[dict[str, Any]] = []
    for season_row in seasons:
        if not isinstance(season_row, dict):
            continue
        sid = season_row.get("iteration_id")
        if sid is None:
            continue
        if iter_id is not None and int(sid) == int(iter_id):
            season_rows.insert(0, season_row)
        elif len(season_rows) < 3:
            season_rows.append(season_row)
    season_rows = season_rows[:3]

    by_position: list[dict[str, Any]] = []
    if iter_id is not None and squad_id is not None:
        codes: list[str] = []
        if primary:
            codes.append(str(primary).upper())
        for row in positions or []:
            code = str(row.get("code") or row.get("position") or "").upper()
            if code and code not in codes:
                codes.append(code)
        # Always probe the opposite flank for wingers / wide mids.
        opposite = {
            "LEFT_WINGER": "RIGHT_WINGER",
            "RIGHT_WINGER": "LEFT_WINGER",
            "LEFT_MIDFIELD": "RIGHT_MIDFIELD",
            "RIGHT_MIDFIELD": "LEFT_MIDFIELD",
            "LEFT_WINGBACK_DEFENDER": "RIGHT_WINGBACK_DEFENDER",
            "RIGHT_WINGBACK_DEFENDER": "LEFT_WINGBACK_DEFENDER",
        }
        opp = opposite.get(str(primary or "").upper())
        if opp and opp not in codes:
            codes.append(opp)
        # Keep this light — Impect rate-limits if we hammer every role.
        for code in codes[:4]:
            # Reuse already-fetched primary profiles when possible.
            pos_profiles: list[dict[str, Any]] = []
            pos_minutes: float | None = None
            pos_season_label: str | None = None
            if primary and code == str(primary).upper() and scored:
                pos_profiles = [
                    {
                        "apiName": row["apiName"],
                        "label": row["label"],
                        "title": row["title"],
                        "scorePct": row["scorePct"],
                    }
                    for row in scored
                ]
                pos_minutes = player.get("minutes")
                pos_season_label = str(player.get("season") or "") or None
            else:
                # Probe seasons and keep the sample with the most minutes
                # (e.g. opposite flank may only have volume in a prior year).
                best_hit: tuple[float, list[dict[str, Any]], str | None] | None = None
                for season_row in season_rows:
                    sid = season_row.get("iteration_id")
                    if sid is None:
                        continue
                    if iter_id is not None and int(sid) == int(iter_id):
                        squad_try = int(squad_id)
                    else:
                        squad_raw = squad_map.get(str(sid))
                        if squad_raw is None:
                            continue
                        squad_try = int(squad_raw)
                    try:
                        cand_profiles, cand_minutes = _profiles_for_exact_position(
                            int(sid), squad_try, int(player_id), code
                        )
                    except Exception:
                        cand_profiles, cand_minutes = [], None
                    mins_f = float(cand_minutes or 0)
                    if cand_profiles and mins_f > 0:
                        season_label = str(season_row.get("season") or "") or None
                        if best_hit is None or mins_f > best_hit[0]:
                            best_hit = (mins_f, cand_profiles, season_label)
                if best_hit is not None:
                    pos_minutes = best_hit[0]
                    pos_profiles = best_hit[1]
                    pos_season_label = best_hit[2]
                else:
                    pos_profiles, pos_minutes = [], None
                    pos_season_label = None
            if not pos_profiles:
                continue
            meta = next(
                (
                    r
                    for r in (positions or [])
                    if str(r.get("code") or "").upper() == code
                ),
                {},
            )
            share = meta.get("match_share")
            try:
                share_f = float(share) if share is not None else None
            except (TypeError, ValueError):
                share_f = None
            # Tiny shares look broken on the slide — only show meaningful %.
            if share_f is not None and share_f < 1:
                share_f = None
            mins = pos_minutes
            if mins is None:
                try:
                    mins = float(meta.get("minutes")) if meta.get("minutes") is not None else None
                except (TypeError, ValueError):
                    mins = None
            top = pos_profiles[0] if pos_profiles else None
            by_position.append(
                {
                    "code": code,
                    "label": _POSITION_DISPLAY.get(code) or code.replace("_", " "),
                    "minutes": round(mins) if mins is not None else None,
                    "matchShare": round(share_f, 1) if share_f is not None else None,
                    "season": pos_season_label,
                    "topTitle": (top or {}).get("title"),
                    "topPct": (top or {}).get("scorePct"),
                    "profiles": pos_profiles[:5],
                }
            )

    by_season: list[dict[str, Any]] = []
    for season_row in season_rows:
        sid = season_row.get("iteration_id")
        if sid is None:
            continue
        # Current season: reuse scored profiles — no extra Impect call.
        if iter_id is not None and int(sid) == int(iter_id) and scored:
            season_profiles = [
                {
                    "apiName": row["apiName"],
                    "label": row["label"],
                    "title": row["title"],
                    "scorePct": row["scorePct"],
                }
                for row in scored
            ]
            season_minutes = player.get("minutes")
        else:
            squad_raw = squad_map.get(str(sid))
            if squad_raw is None:
                continue
            try:
                season_profiles, season_minutes = _profiles_for_exact_position(
                    int(sid),
                    int(squad_raw),
                    int(player_id),
                    str(primary or "LEFT_WINGER"),
                )
            except Exception:
                continue
            if not season_profiles:
                continue
        top = season_profiles[0]
        avg = round(sum(float(p["scorePct"]) for p in season_profiles) / len(season_profiles))
        by_season.append(
            {
                "iterationId": int(sid),
                "season": season_row.get("season") or "",
                "label": season_row.get("label") or season_row.get("season") or str(sid),
                "club": season_row.get("club") or "",
                "competition": season_row.get("competition_name") or "",
                "minutes": round(season_minutes) if season_minutes is not None else None,
                "avgPct": avg,
                "topTitle": top.get("title"),
                "topPct": top.get("scorePct"),
                "profiles": season_profiles[:5],
            }
        )

    return {
        "season": player.get("season"),
        "league": player.get("league"),
        "scoredPosition": primary,
        "minutes": player.get("minutes"),
        "note": "Impect P90 player scores · profile ratings 0–100",
        "profiles": scored,
        "best": best,
        "worst": worst,
        "bestStats": best_stats,
        "worstStats": worst_stats,
        "byPosition": by_position,
        "bySeason": by_season,
    }


def build_meeting_front_pack(
    player_id: int,
    *,
    iteration_id: int | None = None,
    position: str | None = None,
) -> dict[str, Any]:
    from app.player_dossier import _profile_rows, build_player_dossier

    dossier = build_player_dossier(player_id, iteration_id=iteration_id, include_games=False)
    player = dossier.get("player") or {}
    first, last = _split_name(str(player.get("name") or ""))
    primary = player.get("primary_position")
    positions = list(player.get("positions") or [])
    web = dossier.get("web") if isinstance(dossier.get("web"), dict) else {}
    tm = web.get("transfermarkt") if isinstance(web.get("transfermarkt"), dict) else {}

    club_raw = str(player.get("club") or "").strip()
    if (not club_raw or club_raw == "—") and tm.get("current_club"):
        club_raw = str(tm.get("current_club") or "").strip()

    # Harden Transfermarkt fill — youth club names often miss on the first dossier pass.
    tm = _ensure_transfermarkt(str(player.get("name") or ""), club_raw, tm)
    if (not club_raw or club_raw == "—") and tm.get("current_club"):
        club_raw = str(tm.get("current_club") or "").strip()
    club = club_raw.upper() if club_raw else "—"

    height = _height_display(player.get("height"))
    if height == "—":
        height = _height_display(tm.get("height") or tm.get("height_cm"))

    foot = _foot_display(player.get("foot"))
    if foot == "—":
        foot = _foot_display(tm.get("foot"))

    # Infer Impect position from Transfermarkt when season shares are empty.
    tm_code = _tm_position_to_code(tm.get("position"))
    if not primary and tm_code:
        primary = tm_code
        if not any(str(row.get("code") or "").upper() == tm_code for row in positions):
            positions = [
                {
                    "code": tm_code,
                    "label": _POSITION_DISPLAY.get(tm_code, tm_code),
                    "minutes": player.get("minutes"),
                    "match_share": 100.0,
                }
            ] + positions

    # Scout override — force the Impect role used for profiles / P90 / pitch.
    position_override = str(position or "").strip().upper() or None
    if position_override and position_override in _POSITION_DISPLAY:
        primary = position_override
        if not any(str(row.get("code") or "").upper() == primary for row in positions):
            positions = [
                {
                    "code": primary,
                    "label": _POSITION_DISPLAY.get(primary, primary),
                    "minutes": player.get("minutes"),
                    "match_share": 100.0,
                }
            ] + list(positions)

    # Re-pull / resolve PV profile scores + the position they were scored in.
    profiles = list(dossier.get("profiles") or [])
    minutes = player.get("minutes")
    squad_id = player.get("squad_id")
    iter_id = player.get("iteration_id")
    if squad_id is not None and iter_id is not None:
        try:
            profiles_fresh, minutes_fresh, scored_position = _profile_rows(
                int(iter_id), int(squad_id), int(player_id), primary
            )
            if profiles_fresh:
                profiles = profiles_fresh
                dossier["profiles"] = profiles
            if minutes_fresh is not None:
                minutes = minutes_fresh
                player["minutes"] = minutes_fresh
            # Honour scout override — don't let Impect fall-through rewrite the role.
            if not position_override:
                if scored_position and not primary:
                    primary = scored_position
                elif scored_position and primary and scored_position != primary and not profiles:
                    primary = scored_position
            if scored_position and not any(
                str(row.get("code") or "").upper() == scored_position for row in positions
            ):
                positions = [
                    {
                        "code": scored_position,
                        "label": _POSITION_DISPLAY.get(scored_position, scored_position),
                        "minutes": minutes,
                        "match_share": 100.0,
                    }
                ] + positions
        except Exception:
            pass

    # Stamp minutes onto the primary role so the pitch can colour green/amber.
    if primary and minutes is not None:
        found = False
        for row in positions:
            if str(row.get("code") or "").upper() == str(primary).upper():
                if row.get("minutes") is None:
                    row["minutes"] = minutes
                if not row.get("match_share"):
                    row["match_share"] = 100.0
                found = True
                break
        if not found:
            positions = [
                {
                    "code": primary,
                    "label": _POSITION_DISPLAY.get(str(primary), str(primary)),
                    "minutes": minutes,
                    "match_share": 100.0,
                }
            ] + positions

    # When scout picks a role, lead the identity line with that display name.
    if position_override and primary:
        position_line = _POSITION_DISPLAY.get(str(primary), str(primary).replace("_", " "))
    else:
        position_line = _position_line(positions, primary)
        if position_line == "—" and tm.get("position"):
            if tm_code and tm_code in _POSITION_DISPLAY:
                position_line = _POSITION_DISPLAY[tm_code]
            else:
                position_line = re.sub(r"^.*?\-\s*", "", str(tm.get("position"))).strip().upper() or "—"
        if position_line == "—" and primary:
            position_line = _POSITION_DISPLAY.get(str(primary), str(primary).replace("_", " "))

    if minutes is not None and player.get("minutes") is None:
        player["minutes"] = minutes
    if minutes is not None and not player.get("matches"):
        try:
            mins = float(minutes)
            player["matches"] = max(1, int(round(mins / 90.0))) if mins >= 45 else 1
        except (TypeError, ValueError):
            pass

    # Prefer Transfermarkt portrait for the default slide photo when available.
    photo_url = player.get("photo_url")
    if tm.get("photo_url"):
        photo_url = _proxy_photo_url(str(tm["photo_url"]))
    elif photo_url and str(photo_url).startswith("http"):
        photo_url = _proxy_photo_url(str(photo_url))

    if tm and isinstance(dossier.get("web"), dict):
        dossier["web"]["transfermarkt"] = tm
    elif tm:
        dossier["web"] = {**(web or {}), "transfermarkt": tm}
    dossier["player"] = player

    available_codes: list[str] = []
    for row in positions or []:
        code = str(row.get("code") or "").upper()
        if code and code in _POSITION_DISPLAY and code not in available_codes:
            available_codes.append(code)
    if primary and str(primary).upper() not in available_codes:
        available_codes.insert(0, str(primary).upper())
    # Always offer the common outfield roles so scouts can force a map.
    for code in (
        "CENTER_FORWARD",
        "SECOND_STRIKER",
        "ATTACKING_MIDFIELD",
        "LEFT_WINGER",
        "RIGHT_WINGER",
        "CENTRAL_MIDFIELD",
        "DEFENSE_MIDFIELD",
        "LEFT_MIDFIELD",
        "RIGHT_MIDFIELD",
        "LEFT_BACK",
        "RIGHT_BACK",
        "CENTRAL_DEFENDER",
        "LEFT_WINGBACK_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
    ):
        if code not in available_codes:
            available_codes.append(code)
    available_positions = [
        {"code": code, "label": _POSITION_DISPLAY.get(code, code.replace("_", " "))}
        for code in available_codes
        if code in _POSITION_DISPLAY
    ]

    available_seasons: list[dict[str, Any]] = []
    seen_iters: set[int] = set()
    for row in dossier.get("seasons") or []:
        if not isinstance(row, dict):
            continue
        sid = row.get("iteration_id")
        if sid is None:
            continue
        try:
            sid_i = int(sid)
        except (TypeError, ValueError):
            continue
        if sid_i in seen_iters:
            continue
        seen_iters.add(sid_i)
        season_label = str(row.get("season") or "").strip()
        competition = str(row.get("competition_name") or "").strip()
        club_name = str(row.get("club") or "").strip()
        bits = [b for b in (competition or None, season_label or None, club_name or None) if b]
        available_seasons.append(
            {
                "iterationId": sid_i,
                "season": season_label,
                "competition": competition,
                "club": club_name,
                "label": str(row.get("label") or " · ".join(bits) or str(sid_i)),
                "chartable": bool(row.get("chartable")),
            }
        )
    # Keep selected season first in the list for the dropdown.
    current_iter = player.get("iteration_id")
    if current_iter is not None:
        try:
            cur_i = int(current_iter)
            available_seasons.sort(
                key=lambda row: (0 if int(row["iterationId"]) == cur_i else 1, -int(row["iterationId"]))
            )
        except (TypeError, ValueError):
            pass

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "player": {
            "id": player_id,
            "name": player.get("name"),
            "firstName": first,
            "lastName": last,
            "ageLine": _age_line(player.get("age"), player.get("birthdate")),
            "height": height,
            "foot": foot,
            "club": club,
            "transferType": _transfer_type(tm or None, club_raw or player.get("club")),
            "positionLine": position_line,
            "primaryPosition": primary,
            "photoUrl": photo_url,
            "season": player.get("season"),
            "league": player.get("league"),
            "iterationId": player.get("iteration_id"),
            "squadId": player.get("squad_id"),
            "marketValue": tm.get("market_value"),
        },
        "availablePositions": available_positions,
        "availableSeasons": available_seasons,
        "careerStats": _career_stats(dossier),
        "pitch": (pitch_dots := _highlight_pitch(primary, positions)),
        "pitchRoles": _pitch_roles_from_dots(pitch_dots, primary),
        "formations": ["4-2-3-1", "4-4-2", "3-5-2", "3-4-3"],
        "profiles": _profile_cards(dossier, primary_position=primary),
        "dataSummary": _build_data_summary(
            player_id,
            dossier=dossier,
            primary=primary,
            positions=positions,
            profiles=profiles,
        ),
        "bulletDefaults": PROFILE_BULLET_DEFAULTS,
        "links": dossier.get("links") or {},
    }


def _proxy_photo_url(url: str) -> str:
    token = str(url or "").strip()
    if not token:
        return ""
    if token.startswith("/"):
        return token
    return f"/api/meeting-front-pages/image-proxy?url={quote(token, safe='')}"


def _host_allowed(host: str) -> bool:
    h = host.lower().strip(".")
    if not h:
        return False
    for suffix in _PROXY_ALLOWED_HOST_SUFFIXES:
        if h == suffix or h.endswith("." + suffix):
            return True
    return False


def _add_photo(
    bucket: list[dict[str, Any]],
    seen: set[str],
    *,
    url: str | None,
    source: str,
    label: str,
    kind: str = "portrait",
) -> None:
    raw = str(url or "").strip()
    if not raw.startswith("http"):
        return
    low = raw.casefold()
    # Hard-skip heavy watermark mills — keep editorial / club / TM / news.
    if any(
        token in low
        for token in (
            "alamy.",
            "shutterstock.",
            "depositphotos.",
            "dreamstime.",
            "123rf.",
            "istockphoto.",
            "adobe.stock",
            "stock.adobe",
        )
    ):
        return
    # Dedupe by path without query noise where possible.
    key = re.sub(r"[?&](w|h|width|height|quality)=\d+", "", low)
    if key in seen:
        return
    seen.add(key)
    bucket.append(
        {
            "id": f"{source}-{len(bucket)+1}",
            "source": source,
            "label": label,
            "kind": kind,
            "url": raw,
            "proxyUrl": _proxy_photo_url(raw),
            "cutoutFriendly": source in {"transfermarkt", "fotmob"} or kind == "portrait",
        }
    )


def _duckduckgo_photo_urls(
    player_name: str,
    club_name: str | None = None,
    *,
    query_extra: str = "football",
    limit: int = 8,
) -> list[str]:
    query = f"{player_name} {club_name or ''} {query_extra}".strip()
    try:
        home = requests.get(
            "https://duckduckgo.com/",
            params={"q": query},
            timeout=20,
            headers=WEB_HEADERS,
        )
        if home.status_code >= 400:
            return []
        match = re.search(r"vqd=([\"']?)([\w.\-]+)\1", home.text)
        if not match:
            match = re.search(r"vqd=([\w.\-]+)", home.text)
        if not match:
            return []
        vqd = match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(1)
        response = requests.get(
            "https://duckduckgo.com/i.js",
            params={
                "l": "uk-en",
                "o": "json",
                "q": query,
                "vqd": vqd,
                "f": ",,,",
                "p": "1",
            },
            timeout=20,
            headers={**WEB_HEADERS, "Referer": "https://duckduckgo.com/"},
        )
        if response.status_code >= 400:
            return []
        results = response.json().get("results") or []
    except (requests.RequestException, ValueError, TypeError):
        return []

    surname = _name_tokens(player_name)[1]
    out: list[str] = []
    for row in results[:24]:
        if not isinstance(row, dict):
            continue
        image = str(row.get("image") or "").strip()
        title = str(row.get("title") or "")
        if not image.startswith("http"):
            continue
        host = (urlparse(image).hostname or "").lower()
        if not _host_allowed(host) and not any(
            token in image.casefold()
            for token in ("transfermarkt", "wikimedia", "wikipedia", "fotmob", "getty", "imago")
        ):
            # Allow other https hosts for variety, but skip obvious junk.
            if any(bad in image.casefold() for bad in (".svg", "logo", "crest", "badge", "icon", "sprite")):
                continue
        if surname and surname not in _normalize_name_key(title) and surname not in _normalize_name_key(image):
            if not any(token in image.casefold() for token in ("transfermarkt", "wikimedia", "fotmob")):
                continue
        if any(bad in image.casefold() for bad in (".svg", "logo", "crest", "badge", "icon")):
            continue
        out.append(image)
        if len(out) >= limit:
            break
    return out


def _wikipedia_photo_variants(player_name: str, club_name: str | None = None) -> list[str]:
    first, surname = _name_tokens(player_name)
    queries = [
        f"{player_name} footballer",
        player_name,
        f"{player_name} {club_name or ''} footballer".strip(),
    ]
    urls: list[str] = []
    seen: set[str] = set()
    for query in queries:
        try:
            response = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrsearch": query,
                    "gsrlimit": 8,
                    "prop": "pageimages|pageterms",
                    "piprop": "thumbnail|original",
                    "pithumbsize": 1000,
                    "wbptterms": "description",
                },
                timeout=20,
                headers=WEB_HEADERS,
            )
            if response.status_code >= 400:
                continue
            pages = ((response.json().get("query") or {}).get("pages") or {})
        except (requests.RequestException, ValueError, TypeError):
            continue

        ranked: list[tuple[int, str, str]] = []
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            title = str(page.get("title") or "")
            title_key = _normalize_name_key(title)
            # Require BOTH name tokens so "Dale Bennett" does not match "Owen Dale".
            if first and first not in title_key:
                continue
            if surname and surname not in title_key:
                continue
            terms = page.get("terms") or {}
            desc = ""
            if isinstance(terms, dict):
                desc_list = terms.get("description") or []
                if isinstance(desc_list, list) and desc_list:
                    desc = str(desc_list[0])
            blob = f"{title} {desc}".casefold()
            score = 0
            if title_key == _normalize_name_key(player_name):
                score += 8
            if "football" in blob or "soccer" in blob:
                score += 3
            if club_name and _normalize_name_key(club_name)[:6] in _normalize_name_key(blob):
                score += 2
            if "disambiguation" in blob or "list of" in blob:
                score -= 8
            original = ((page.get("original") or {}).get("source") or "").strip()
            thumb = ((page.get("thumbnail") or {}).get("source") or "").strip()
            for candidate in (original, thumb):
                if candidate.startswith("http"):
                    ranked.append((score, candidate, title))
        ranked.sort(key=lambda item: item[0], reverse=True)
        for score, candidate, _title in ranked:
            if score < 3:
                continue
            key = candidate.split("?")[0].casefold()
            if key in seen:
                continue
            seen.add(key)
            urls.append(candidate)
    return urls


def _bing_photo_urls(
    player_name: str,
    club_name: str | None = None,
    *,
    query_extra: str = "football",
    limit: int = 10,
    loose: bool = False,
) -> list[str]:
    """Bing image search — reliable from datacenter IPs where DDG/TM are blocked."""
    query = f"{player_name} {club_name or ''} {query_extra}".strip()
    try:
        response = requests.get(
            "https://www.bing.com/images/search",
            params={"q": query, "form": "HDRSC2", "first": "1", "count": "35"},
            timeout=25,
            headers={
                **WEB_HEADERS,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Referer": "https://www.bing.com/",
            },
        )
        if response.status_code >= 400:
            return []
        html = response.text
    except requests.RequestException:
        return []

    urls = re.findall(r"murl&quot;:&quot;(https?://[^&]+)&quot;", html)
    if not urls:
        urls = re.findall(r'"murl":"(https?://[^"]+)"', html)
    if not urls:
        urls = re.findall(r"murl\\\":\\\"(https?://[^\\\"\\]+)", html)
    if not urls:
        # Newer Bing markup
        urls = re.findall(r"murl&quot;:&quot;(https?:\\u002f\\u002f[^&]+)&quot;", html)
        urls = [u.replace("\\u002f", "/") for u in urls]

    first, surname = _name_tokens(player_name)
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        image = html_lib_unescape(raw).replace("\\u002f", "/").replace("\\/", "/")
        if not image.startswith("http"):
            continue
        key = image.split("?")[0].casefold()
        if key in seen:
            continue
        low = image.casefold()
        if any(bad in low for bad in (".svg", "logo", "crest", "badge", "icon", "sprite")):
            continue
        # Drop obvious non-player junk from weak queries.
        if any(bad in low for bad in ("tiger", "cat-", "/cat/", "drawing", "flag-", "map-")):
            continue
        path_key = _normalize_name_key(image)
        if not loose and surname and surname not in path_key and first and first not in path_key:
            # Keep common football media hosts even when CDN paths are opaque.
            if not any(
                host in low
                for host in (
                    "port-vale",
                    "portvale",
                    "transfermarkt",
                    "wikimedia",
                    "wikipedia",
                    "getty",
                    "imago",
                    "pa-images",
                    "paimages",
                    "offside",
                    "actionimages",
                    "reuters",
                    "sky",
                    "bbc",
                    "newcastleunited",
                    "nufc",
                    "premierleague",
                    "efl",
                    "clubcast",
                    "cloudfront",
                    "wp.com",
                    "googleusercontent",
                    "bing.net",
                    "pinimg",
                )
            ):
                continue
        seen.add(key)
        out.append(image)
        if len(out) >= limit:
            break
    return out


def html_lib_unescape(value: str) -> str:
    import html as html_lib

    return html_lib.unescape(value)


def search_meeting_photos(
    player_name: str,
    *,
    club_name: str | None = None,
) -> list[dict[str, Any]]:
    name = str(player_name or "").strip()
    if len(name) < 2:
        return []

    # Always search with a cleaned club (drop U21/Academy) — better TM + Bing hits.
    club_clean = None
    if club_name:
        club_clean = re.sub(
            r"\s*(U\d{2}|Under[-\s]?\d{2}|Youth|Academy|Reserves?|II|B)\s*$",
            "",
            str(club_name),
            flags=re.I,
        ).strip(" -–—") or None

    cache_key = f"{_normalize_name_key(name)}|{_normalize_name_key(club_clean or club_name or '')}"
    cached = _PHOTO_SEARCH_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _PHOTO_SEARCH_TTL and len(cached[1]) >= 4:
        return cached[1]

    photos: list[dict[str, Any]] = []
    seen: set[str] = set()
    club_for_search = club_clean or club_name

    # 1) Transfermarkt portrait (best for presentation — clean studio look)
    try:
        from app.player_web_enrichment import fetch_transfermarkt_player_profile

        tm = fetch_transfermarkt_player_profile(name, club_name=club_for_search)
        if not tm:
            tm = fetch_transfermarkt_player_profile(name, club_name=None)
    except Exception:
        tm = None
    if tm and tm.get("photo_url"):
        base = _upgrade_portrait_url(str(tm["photo_url"]))
        _add_photo(photos, seen, url=base, source="transfermarkt", label="Transfermarkt portrait", kind="portrait")
        for size in ("big", "medium", "header"):
            variant = re.sub(r"/portrait/(?:small|medium|big|header)/", f"/portrait/{size}/", base)
            _add_photo(
                photos,
                seen,
                url=variant,
                source="transfermarkt",
                label=f"Transfermarkt {size}",
                kind="portrait",
            )
        if not club_for_search and tm.get("current_club"):
            club_for_search = str(tm["current_club"])

    # 2) Wikipedia (exact first+surname match)
    for url in _wikipedia_photo_variants(name, club_for_search):
        _add_photo(photos, seen, url=url, source="wikipedia", label="Wikipedia", kind="portrait")

    # 3) Club site / local squad CDN
    try:
        from app.squad_photos import resolve_squad_photo_url

        club_url = resolve_squad_photo_url(name, club_name=club_for_search)
        _add_photo(photos, seen, url=club_url, source="club", label="Club site", kind="portrait")
    except Exception:
        pass

    # 4) Bing — primary volume source on the droplet
    bing_queries: list[tuple[str | None, str, str, str]] = [
        (club_for_search, "football", "portrait", "Bing photo"),
        (club_for_search, "footballer", "portrait", "Bing footballer"),
        (club_for_search, "headshot", "portrait", "Bing headshot"),
        (club_for_search, "portrait", "portrait", "Bing portrait"),
        (club_for_search, "kit", "action", "Bing kit"),
        (club_for_search, "action", "action", "Bing action"),
        (club_for_search, "match", "action", "Bing match"),
        (None, "football", "portrait", "Bing name only"),
        (None, "newcastle", "action", "Bing Newcastle"),
    ]
    for club_q, extra, kind, label in bing_queries:
        for url in _bing_photo_urls(name, club_q, query_extra=extra, limit=8, loose=False):
            _add_photo(photos, seen, url=url, source="bing", label=label, kind=kind)
        if len(photos) >= 24:
            break

    # If still thin, loosen Bing filters (opaque CDN paths).
    if len(photos) < 8:
        for club_q, extra, kind, label in (
            (club_for_search, "football", "portrait", "Bing photo"),
            (None, "football action", "action", "Bing action"),
            (None, "winger", "action", "Bing winger"),
        ):
            for url in _bing_photo_urls(name, club_q, query_extra=extra, limit=12, loose=True):
                _add_photo(photos, seen, url=url, source="bing", label=label, kind=kind)

    # 5) DuckDuckGo (works on local Mac; often 403 from datacenter)
    for extra, kind, label in (
        ("football headshot", "portrait", "Web headshot"),
        ("football kit", "action", "Web kit photo"),
        ("football action", "action", "Web action"),
    ):
        for url in _duckduckgo_photo_urls(name, club_for_search, query_extra=extra, limit=6):
            _add_photo(photos, seen, url=url, source="web", label=label, kind=kind)

    if not photos:
        one = _duckduckgo_player_photo_url(name, club_for_search)
        _add_photo(photos, seen, url=one, source="web", label="Web search", kind="portrait")
    if not photos:
        wiki_one = _wikipedia_player_photo_url(name, None)
        _add_photo(photos, seen, url=wiki_one, source="wikipedia", label="Wikipedia", kind="portrait")

    # Only cache healthy galleries — don't lock in a 1-photo miss for 30 minutes.
    if len(photos) >= 3:
        _PHOTO_SEARCH_CACHE[cache_key] = (now, photos)
    return photos


def register_meeting_front_pages_routes(app: FastAPI) -> None:
    @app.get("/meeting-front-pages", response_class=HTMLResponse)
    def meeting_front_pages_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "meeting-front-pages.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Meeting Front Pages page missing.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/meeting-front-pages/pack")
    def meeting_front_pages_pack(
        player_id: int = Query(..., alias="playerId"),
        iteration_id: int | None = Query(None, alias="iterationId"),
        position: str | None = Query(None, description="Impect position code override"),
    ) -> JSONResponse:
        try:
            payload = build_meeting_front_pack(
                player_id, iteration_id=iteration_id, position=position
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not build pack: {exc}") from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/meeting-front-pages/players")
    def meeting_front_pages_players(q: str = Query(..., min_length=2)) -> JSONResponse:
        """Player typeahead — soft-fails so the UI never sticks on 'Search failed'."""
        query = str(q or "").strip()
        if len(query) < 2:
            return JSONResponse(
                {"players": [], "player_count": 0, "message": None},
                headers={"Cache-Control": "no-store"},
            )
        try:
            import app.main as main

            payload = main.list_players(main.PlayerCatalogRequest(search=query))
            return JSONResponse(payload, headers={"Cache-Control": "no-store"})
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Impect search unavailable"
            return JSONResponse(
                {
                    "players": [],
                    "player_count": 0,
                    "message": f"{detail}. Try again in a moment.",
                },
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            return JSONResponse(
                {
                    "players": [],
                    "player_count": 0,
                    "message": "Player search is temporarily unavailable. Try again.",
                },
                headers={"Cache-Control": "no-store"},
            )

    @app.get("/api/meeting-front-pages/photos")
    def meeting_front_pages_photos(
        name: str = Query(...),
        club: str | None = Query(None),
        refresh: int = Query(0),
    ) -> JSONResponse:
        if refresh:
            # Bust in-memory cache so "Find web photos" always re-searches.
            prefix = f"{_normalize_name_key(name)}|"
            for key in list(_PHOTO_SEARCH_CACHE.keys()):
                if key.startswith(prefix):
                    _PHOTO_SEARCH_CACHE.pop(key, None)
        photos = search_meeting_photos(name, club_name=club)
        return JSONResponse(
            {"player": name, "club": club, "count": len(photos), "photos": photos},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/meeting-front-pages/image-proxy")
    def meeting_front_pages_image_proxy(url: str = Query(...)) -> Response:
        token = str(url or "").strip()
        if not token.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Invalid image URL.")
        host = (urlparse(token).hostname or "").lower()
        if not host:
            raise HTTPException(status_code=400, detail="Invalid image host.")
        # Meeting tool pulls editorial/club CDNs — allow broad https hosts,
        # but still block obvious non-image / local schemes already handled above.

        headers = {
            **WEB_HEADERS,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://www.google.com/",
        }
        if "transfermarkt" in token.casefold():
            headers["Referer"] = "https://www.transfermarkt.co.uk/"
        try:
            upstream = requests.get(token, timeout=25, headers=headers, stream=True)
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail="Could not fetch image.") from exc
        if upstream.status_code >= 400:
            raise HTTPException(status_code=502, detail="Image unavailable.")

        # Cap downloads so a huge asset cannot blow memory.
        chunks: list[bytes] = []
        total = 0
        for chunk in upstream.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > 8 * 1024 * 1024:
                raise HTTPException(status_code=502, detail="Image too large.")
            chunks.append(chunk)
        content = b"".join(chunks)
        if not content:
            raise HTTPException(status_code=502, detail="Image unavailable.")

        content_type = upstream.headers.get("Content-Type") or "image/jpeg"
        if "image" not in content_type and "octet-stream" not in content_type:
            # Some CDNs omit content-type; sniff magic bytes.
            if content[:3] == b"\xff\xd8\xff":
                content_type = "image/jpeg"
            elif content[:8] == b"\x89PNG\r\n\x1a\n":
                content_type = "image/png"
            elif content[:4] == b"RIFF":
                content_type = "image/webp"
            else:
                raise HTTPException(status_code=502, detail="Upstream was not an image.")

        return Response(
            content=content,
            media_type=content_type.split(";")[0].strip(),
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/api/meeting-front-pages/meta")
    def meeting_front_pages_meta() -> dict[str, Any]:
        return {
            "title": "Meeting Front Pages",
            "badgeUrl": "/standalone/port-vale-badge.png",
            "slideSize": {"width": 1920, "height": 1080},
            "bulletDefaults": PROFILE_BULLET_DEFAULTS,
            "standaloneDir": str(STANDALONE_DIR),
        }
