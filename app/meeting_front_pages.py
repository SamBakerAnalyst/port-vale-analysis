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
    {"code": "ATTACKING_MIDFIELD", "abbr": "AM", "x": 50, "y": 32},
    {"code": "LEFT_WINGER", "abbr": "LW", "x": 18, "y": 22},
    {"code": "RIGHT_WINGER", "abbr": "RW", "x": 82, "y": 22},
    {"code": "CENTER_FORWARD", "abbr": "CF", "x": 50, "y": 12},
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
    if "'" in text:
        feet = text.split("(", 1)[0].strip().rstrip('"')
        return feet
    return text


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
    """Return pitch dots with highlight state for the player's roles."""
    codes: list[str] = []
    if primary:
        codes.append(str(primary).upper())
    for row in positions or []:
        code = str(row.get("code") or row.get("position") or "").upper()
        if code and code not in codes:
            codes.append(code)

    primary_code = codes[0] if codes else None
    secondary = set(codes[1:])

    def matches(dot_code: str, player_code: str) -> bool:
        if dot_code == player_code:
            return True
        # Map LB/RB aliases and dual CB/CM dots.
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
        state = "idle"
        label = None
        code = str(dot["code"])
        if primary_code and matches(code, primary_code):
            state = "primary"
            label = str(dot["abbr"])
        elif any(matches(code, sec) for sec in secondary):
            state = "secondary"
        dots.append(
            {
                "abbr": dot["abbr"],
                "x": dot["x"],
                "y": dot["y"],
                "state": state,
                "label": label if state == "primary" else None,
            }
        )
    return dots


def _career_stats(dossier: dict[str, Any]) -> dict[str, Any]:
    player = dossier.get("player") or {}
    web = dossier.get("web") or {}
    fbref = web.get("fbref") if isinstance(web.get("fbref"), dict) else {}
    tm = web.get("transfermarkt") if isinstance(web.get("transfermarkt"), dict) else {}
    career = fbref.get("career") if isinstance(fbref.get("career"), dict) else {}

    def num(*values: Any) -> int | None:
        for value in values:
            if value is None or value == "" or value == "—":
                continue
            try:
                return int(round(float(value)))
            except (TypeError, ValueError):
                continue
        return None

    # Prefer FBref career totals (domestic leagues), then season row, then Impect.
    games = num(
        career.get("matches"),
        fbref.get("career_matches"),
        fbref.get("matches"),
        player.get("matches"),
    )
    starts = num(career.get("starts"), fbref.get("career_starts"), fbref.get("starts"))
    minutes = num(
        career.get("minutes"),
        fbref.get("career_minutes"),
        fbref.get("minutes"),
        player.get("minutes"),
    )
    goals = num(career.get("goals"), fbref.get("career_goals"), fbref.get("goals"))
    assists = num(career.get("assists"), fbref.get("career_assists"), fbref.get("assists"))

    # Fall back to hero_stats when FBref is thin.
    for row in dossier.get("hero_stats") or []:
        key = str(row.get("key") or "").lower()
        value = row.get("value")
        if key == "goals" and goals is None:
            goals = num(value)
        if key == "assists" and assists is None:
            assists = num(value)

    has_career = bool(career.get("matches") or fbref.get("career_matches"))
    has_fbref = bool(fbref)
    return {
        "games": games,
        "starts": starts,
        "minutes": minutes,
        "goals": goals,
        "assists": assists,
        "source": "fbref_career" if has_career else ("fbref" if has_fbref else ("impect" if player.get("minutes") else None)),
        "fbrefUrl": fbref.get("profile_url"),
        "note": (
            "Career totals from FBref (domestic leagues) — edit before export if needed."
            if has_career
            else (
                "FBref season stats prefilled — edit to career totals before export."
                if has_fbref
                else (
                    "Season minutes from Impect — edit to career totals before export."
                    if player.get("minutes")
                    else "Enter career totals before export."
                )
            )
        ),
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

    cards: list[dict[str, Any]] = []
    for api_name in api_names:
        score_row = scored.get(api_name) or {}
        label = str(score_row.get("label") or humanize_profile_name(api_name))
        title = _presentation_title(api_name, label, primary_position)
        # Prefill selection: scored ≥40%, or top 2 by score for a usable video pack.
        cards.append(
            {
                "apiName": api_name,
                "label": label,
                "title": title,
                "bullets": _bullets_for_title(title),
                "scorePct": score_row.get("pct"),
                "selected": bool(score_row) and (score_row.get("pct") or 0) >= 40,
            }
        )

    # Always include scored profiles even if not in position list.
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
                "selected": (score_row.get("pct") or 0) >= 40,
            }
        )

    # Prefer a ready video pack: keep ≥40% fits, else top 3 by score.
    if cards and sum(1 for c in cards if c["selected"]) < 2:
        ranked = sorted(
            cards,
            key=lambda c: (c.get("scorePct") is not None, c.get("scorePct") or -1),
            reverse=True,
        )
        for card in ranked[:3]:
            card["selected"] = True

    # If nothing selected, select top 2 by score.
    if cards and not any(c["selected"] for c in cards):
        ranked = sorted(
            cards,
            key=lambda c: (c.get("scorePct") is not None, c.get("scorePct") or -1),
            reverse=True,
        )
        for card in ranked[:2]:
            card["selected"] = True

    cards.sort(
        key=lambda c: (
            not c["selected"],
            -(c.get("scorePct") if c.get("scorePct") is not None else -1),
            c["title"],
        )
    )
    return cards


def build_meeting_front_pack(player_id: int, *, iteration_id: int | None = None) -> dict[str, Any]:
    from app.player_dossier import build_player_dossier

    dossier = build_player_dossier(player_id, iteration_id=iteration_id, include_games=False)
    player = dossier.get("player") or {}
    first, last = _split_name(str(player.get("name") or ""))
    primary = player.get("primary_position")
    positions = player.get("positions") or []
    web = dossier.get("web") if isinstance(dossier.get("web"), dict) else {}
    tm = web.get("transfermarkt") if isinstance(web.get("transfermarkt"), dict) else {}

    height = _height_display(player.get("height"))
    if height == "—" and tm.get("height"):
        height = _height_display(tm.get("height"))

    club_raw = str(player.get("club") or "").strip()
    if (not club_raw or club_raw == "—") and tm.get("current_club"):
        club_raw = str(tm.get("current_club") or "").strip()
    club = club_raw.upper() if club_raw else "—"

    foot = _foot_display(player.get("foot"))
    if foot == "—" and tm.get("foot"):
        foot = _foot_display(tm.get("foot"))

    # Prefer Transfermarkt portrait for the default slide photo when available.
    photo_url = player.get("photo_url")
    if tm.get("photo_url"):
        photo_url = _proxy_photo_url(str(tm["photo_url"]))
    elif photo_url and str(photo_url).startswith("http"):
        photo_url = _proxy_photo_url(str(photo_url))

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
            "positionLine": _position_line(positions, primary),
            "primaryPosition": primary,
            "photoUrl": photo_url,
            "season": player.get("season"),
            "league": player.get("league"),
        },
        "careerStats": _career_stats(dossier),
        "pitch": _highlight_pitch(primary, positions),
        "profiles": _profile_cards(dossier, primary_position=primary),
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
    # Dedupe by path without query noise where possible.
    key = re.sub(r"[?&](w|h|width|height|quality)=\d+", "", raw.casefold())
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
) -> list[str]:
    """Bing image search — reliable from datacenter IPs where DDG/TM are blocked."""
    query = f"{player_name} {club_name or ''} {query_extra}".strip()
    try:
        response = requests.get(
            "https://www.bing.com/images/search",
            params={"q": query, "form": "HDRSC2", "first": "1"},
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
        if any(bad in low for bad in (".svg", "logo", "crest", "badge", "icon", "sprite", "watermark")):
            continue
        # Soft name filter on URL path — keep variety but drop obvious mismatches later in UI.
        path_key = _normalize_name_key(image)
        if surname and surname not in path_key and first and first not in path_key:
            # Still keep club / editorial hosts; staff pick the right one.
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
                    "shutterstock",
                    "alamy",
                    "clubcast",
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

    cache_key = f"{_normalize_name_key(name)}|{_normalize_name_key(club_name or '')}"
    cached = _PHOTO_SEARCH_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _PHOTO_SEARCH_TTL:
        return cached[1]

    photos: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1) Transfermarkt portrait (best for presentation — clean studio look)
    try:
        from app.player_web_enrichment import fetch_transfermarkt_player_profile

        tm = fetch_transfermarkt_player_profile(name, club_name=club_name)
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
        if not club_name and tm.get("current_club"):
            club_name = str(tm["current_club"])

    # 2) Wikipedia (exact first+surname match)
    for url in _wikipedia_photo_variants(name, club_name):
        _add_photo(photos, seen, url=url, source="wikipedia", label="Wikipedia", kind="portrait")

    # 3) Club site / local squad CDN
    try:
        from app.squad_photos import resolve_squad_photo_url

        club_url = resolve_squad_photo_url(name, club_name=club_name)
        _add_photo(photos, seen, url=club_url, source="club", label="Club site", kind="portrait")
    except Exception:
        pass

    # 4) Bing image search — works from the droplet when TM/DDG are blocked
    for extra, kind, label in (
        ("football", "portrait", "Bing photo"),
        ("football headshot", "portrait", "Bing headshot"),
        ("football portrait", "portrait", "Bing portrait"),
        ("kit", "action", "Bing kit"),
        ("action", "action", "Bing action"),
    ):
        for url in _bing_photo_urls(name, club_name, query_extra=extra, limit=5):
            _add_photo(photos, seen, url=url, source="bing", label=label, kind=kind)

    # 5) DuckDuckGo (works on local Mac; often 403 from datacenter)
    for extra, kind, label in (
        ("football headshot", "portrait", "Web headshot"),
        ("football kit", "action", "Web kit photo"),
    ):
        for url in _duckduckgo_photo_urls(name, club_name, query_extra=extra, limit=3):
            _add_photo(photos, seen, url=url, source="web", label=label, kind=kind)

    if not photos:
        one = _duckduckgo_player_photo_url(name, club_name)
        _add_photo(photos, seen, url=one, source="web", label="Web search", kind="portrait")
    if not photos:
        wiki_one = _wikipedia_player_photo_url(name, None)
        # Only accept if first+surname both present in URL path or we already filtered hard above.
        _add_photo(photos, seen, url=wiki_one, source="wikipedia", label="Wikipedia", kind="portrait")

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
    ) -> JSONResponse:
        try:
            payload = build_meeting_front_pack(player_id, iteration_id=iteration_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not build pack: {exc}") from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/meeting-front-pages/photos")
    def meeting_front_pages_photos(
        name: str = Query(...),
        club: str | None = Query(None),
    ) -> JSONResponse:
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
