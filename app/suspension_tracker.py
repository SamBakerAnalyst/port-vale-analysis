"""Suspension Tracker — FotMob yellow/red cards + EFL offence codes."""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.paths import STANDALONE_DIR, SUSPENSION_TRACKER_DATA_DIR, ensure_data_dirs
from app.season_defaults import CURRENT_SEASON

FOTMOB_TEAM_ID = 9799
LEAGUE_TWO_ID = 109
EFL_CUP_ID = 133
CACHE_TTL_SECONDS = 15 * 60
FIXTURES_CACHE_TTL_SECONDS = 5 * 60

DATA_DIR = SUSPENSION_TRACKER_DATA_DIR
DATA_PATH = DATA_DIR / "offences.json"
_store_lock = threading.Lock()
_fixtures_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_cards_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

# Competition buckets mirror Sam Baker Discipline sheet columns.
COMP_BUCKETS: tuple[dict[str, Any], ...] = (
    {
        "id": "league_two",
        "label": "League Two",
        "short": "L2",
        "rules": (
            "5 cautions → ban (cut-off game 19) · 10 cautions → ban (cut-off game 37) · "
            "15 & 20 cautions → last game of the regular season"
        ),
        "thresholds": (
            {"cards": 5, "label": "1-match ban (by game 19)"},
            {"cards": 10, "label": "2-match ban (by game 37)"},
            {"cards": 15, "label": "Ban step (season end cut-off)"},
            {"cards": 20, "label": "Ban step (season end cut-off)"},
        ),
    },
    {
        "id": "efl_trophy",
        "label": "EFL Trophy",
        "short": "Trophy",
        "rules": "2 cautions → 1 game · 4 cautions → 2 games · Quarter-final cut-off",
        "thresholds": (
            {"cards": 2, "label": "1-match ban"},
            {"cards": 4, "label": "2-match ban"},
        ),
    },
    {
        "id": "efl_cup",
        "label": "EFL Cup",
        "short": "League Cup",
        "rules": "2 cautions → 1 game · 4 cautions → 1 game · Quarter-final cut-off",
        "thresholds": (
            {"cards": 2, "label": "1-match ban"},
            {"cards": 4, "label": "1-match ban"},
        ),
    },
    {
        "id": "fa_cup",
        "label": "FA Cup",
        "short": "FA Cup",
        "rules": "2 cautions → 1 game · 4 cautions → 1 game · Quarter-final cut-off",
        "thresholds": (
            {"cards": 2, "label": "1-match ban"},
            {"cards": 4, "label": "1-match ban"},
        ),
    },
    {
        "id": "other",
        "label": "Other",
        "short": "Other",
        "rules": "Friendlies / other comps — tracked for completeness",
        "thresholds": (),
    },
)
_BUCKET_BY_ID = {row["id"]: row for row in COMP_BUCKETS}

STAFF_RULES = (
    "Across all competitions — 3 cautions = 1 match ban · 6 = 2 match ban · "
    "9 = 3 match ban · 12 = Regulatory Commission"
)

# EFL charge codes from staff reference sheet (yellow C*, red S*).
C1_SUBTYPES: tuple[tuple[str, str], ...] = (
    ("AA", "Adopting an aggressive attitude"),
    ("DI", "Simulation"),
    ("DP", "Dangerous Play"),
    ("FT", "Foul Tackle"),
    ("GC", "Goal Celebration"),
    ("HB", "Handball"),
    ("RP", "Reckless Play"),
    ("SP", "Pushing or Pulling an opponent"),
    ("TR", "Tripping"),
    ("UB", "Unspecified Behaviour"),
)

S2_SUBTYPES: tuple[tuple[str, str], ...] = (
    ("HEAD", "Head to Head"),
    ("ELBOW", "Elbowing"),
    ("KICK", "Kicking"),
    ("STAMP", "Stamping"),
    ("STRIKE", "Striking"),
    ("BITE", "Biting"),
    ("OTHER", "Other Unspecified Behaviour"),
)

YELLOW_OFFENCE_OPTIONS: list[dict[str, str]] = [
    *[
        {
            "value": f"C1-{code}",
            "label": f"C1 · {code} — {label}",
            "group": "C1 Unsporting Behaviour",
        }
        for code, label in C1_SUBTYPES
    ],
    {"value": "C2", "label": "C2 — Dissent", "group": "Caution"},
    {
        "value": "C2-SINBIN",
        "label": "C2 — Dissent (sin bin)",
        "group": "Caution",
    },
    {
        "value": "C3",
        "label": "C3 — Persistently infringing the Laws of the Game",
        "group": "Caution",
    },
    {
        "value": "C4",
        "label": "C4 — Delays the restart of play",
        "group": "Caution",
    },
    {
        "value": "C5",
        "label": "C5 — Fails to respect the required distance at a restart",
        "group": "Caution",
    },
    {
        "value": "C6",
        "label": "C6 — Enters or re-enters the field without permission",
        "group": "Caution",
    },
    {
        "value": "C7",
        "label": "C7 — Deliberately leaves the field without permission",
        "group": "Caution",
    },
]

RED_OFFENCE_OPTIONS: list[dict[str, str]] = [
    {"value": "S1", "label": "S1 — Serious Foul Play", "group": "Sending-off"},
    *[
        {
            "value": f"S2-{code}",
            "label": f"S2 · {label} — Violent Conduct",
            "group": "S2 Violent Conduct",
        }
        for code, label in S2_SUBTYPES
    ],
    {"value": "S3", "label": "S3 — Spitting", "group": "Sending-off"},
    {
        "value": "S4",
        "label": "S4 — Denies a goal / OGSO by deliberate handball",
        "group": "Sending-off",
    },
    {
        "value": "S5",
        "label": "S5 — Denies an OGSO by a free-kick / penalty offence",
        "group": "Sending-off",
    },
    {
        "value": "S6",
        "label": "S6 — Offensive, insulting or abusive language",
        "group": "Sending-off",
    },
    {
        "value": "S7",
        "label": "S7 — Second yellow card in the same match",
        "group": "Sending-off",
    },
]

_OFFENCE_LABELS = {
    row["value"]: row["label"]
    for row in (*YELLOW_OFFENCE_OPTIONS, *RED_OFFENCE_OPTIONS)
}

THRESHOLDS = COMP_BUCKETS[0]["thresholds"]


class OffenceUpdate(BaseModel):
    offence_code: str | None = Field(default=None, max_length=32)


class StaffNoteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    date: str = Field(..., min_length=8, max_length=12)
    offence_code: str = Field(default="C1", max_length=32)
    notes: str = Field(default="", max_length=500)


def _season_date_bounds(season: str) -> tuple[str, str]:
    start_year = int(str(season).split("/")[0])
    if start_year < 100:
        start_year += 2000
    return f"{start_year}-07-01", f"{start_year + 1}-06-30"


def _validate_season(season: str | None) -> str:
    raw = (season or CURRENT_SEASON).strip()
    if "/" not in raw:
        raise HTTPException(status_code=400, detail="Season must look like 26/27")
    return raw


def _fotmob_http_get(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.fixture_planner import _http

    response = _http.get(
        url,
        params=params or {},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=25,
    )
    if not response.ok:
        raise HTTPException(
            status_code=502, detail=f"FotMob request failed ({response.status_code})"
        )
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _ensure_store() -> None:
    ensure_data_dirs()
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_store() -> dict[str, Any]:
    _ensure_store()
    with _store_lock:
        if not DATA_PATH.exists():
            return {"offences": {}, "staff": []}
        try:
            payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"offences": {}, "staff": []}
    if not isinstance(payload, dict):
        return {"offences": {}, "staff": []}
    payload.setdefault("offences", {})
    payload.setdefault("staff", [])
    return payload


def _load_offences() -> dict[str, str]:
    raw = _load_store().get("offences") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        code = str(value or "").strip()
        if key and code and code in _OFFENCE_LABELS:
            out[str(key)] = code
    return out


def _save_store(store: dict[str, Any]) -> None:
    _ensure_store()
    with _store_lock:
        temp_path = DATA_PATH.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(store, indent=2), encoding="utf-8")
        temp_path.replace(DATA_PATH)


def _save_offences(offences: dict[str, str]) -> None:
    store = _load_store()
    store["offences"] = offences
    _save_store(store)


def _bucket_for_league(league_id: int, competition: str) -> str:
    name = competition.casefold()
    if league_id == LEAGUE_TWO_ID or "league two" in name:
        return "league_two"
    if "trophy" in name:
        return "efl_trophy"
    if league_id == EFL_CUP_ID or "league cup" in name or "efl cup" in name or "carabao" in name:
        return "efl_cup"
    if "fa cup" in name or "emirates fa" in name:
        return "fa_cup"
    return "other"


def _fixtures_for_season(season: str) -> list[dict[str, Any]]:
    season = _validate_season(season)
    cached = _fixtures_cache.get(season)
    now = time.time()
    if cached and now - cached[0] < FIXTURES_CACHE_TTL_SECONDS:
        return cached[1]

    payload = _fotmob_http_get(
        "https://www.fotmob.com/api/data/teams",
        params={"id": FOTMOB_TEAM_ID},
    )
    raw = (
        ((payload.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures")
        or []
    )
    start, end = _season_date_bounds(season)
    rows: list[dict[str, Any]] = []
    for match in raw:
        if not isinstance(match, dict):
            continue
        status = match.get("status") or {}
        kickoff = str(status.get("utcTime") or "")
        match_date = kickoff[:10]
        if not match_date or match_date < start or match_date > end:
            continue
        home = match.get("home") or {}
        away = match.get("away") or {}
        tournament = match.get("tournament") or {}
        try:
            home_id = int(home.get("id") or 0)
            away_id = int(away.get("id") or 0)
            match_id = int(match["id"])
            league_id = int(tournament.get("leagueId") or 0)
        except (TypeError, ValueError, KeyError):
            continue
        if FOTMOB_TEAM_ID not in (home_id, away_id):
            continue
        is_home = home_id == FOTMOB_TEAM_ID
        opponent = away if is_home else home
        competition = str(tournament.get("name") or "").strip() or "Competition"
        rows.append(
            {
                "match_id": match_id,
                "date": match_date,
                "kickoff_utc": kickoff or None,
                "finished": bool(status.get("finished")),
                "opponent": str(opponent.get("name") or "TBC").strip() or "TBC",
                "is_home": is_home,
                "venue": "H" if is_home else "A",
                "competition": competition,
                "league_id": league_id,
                "bucket": _bucket_for_league(league_id, competition),
            }
        )
    rows.sort(key=lambda row: (str(row.get("date") or ""), int(row.get("match_id") or 0)))
    _fixtures_cache[season] = (now, rows)
    return rows


def _normalize_card_kind(raw: Any) -> str | None:
    text = str(raw or "").strip().casefold()
    if not text:
        return None
    if "yellow" in text and "red" in text:
        return "SecondYellow"
    if text in {"yellow", "yc"} or text.startswith("yellow"):
        return "Yellow"
    if text in {"red", "rc"} or text.startswith("red"):
        return "Red"
    return None


def _cards_for_match(match: dict[str, Any]) -> list[dict[str, Any]]:
    match_id = int(match["match_id"])
    try:
        payload = _fotmob_http_get(
            "https://www.fotmob.com/api/data/matchDetails",
            params={"matchId": match_id},
        )
    except HTTPException:
        return []

    events = (
        (((payload.get("content") or {}).get("matchFacts") or {}).get("events") or {}).get(
            "events"
        )
        or []
    )
    is_home = bool(match.get("is_home"))
    out: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "Card":
            continue
        if bool(event.get("isHome")) != is_home:
            continue
        kind = _normalize_card_kind(event.get("card"))
        if not kind:
            continue
        player = event.get("player") if isinstance(event.get("player"), dict) else {}
        player_name = (
            str(player.get("name") or event.get("nameStr") or event.get("fullName") or "")
            .strip()
        )
        if not player_name:
            continue
        try:
            event_id = int(event.get("eventId") or 0)
            player_id = int(player.get("id") or event.get("playerId") or 0) or None
            minute = int(event.get("time") or 0)
        except (TypeError, ValueError):
            event_id = 0
            player_id = None
            minute = 0
        card_id = f"{match_id}-{event_id or minute}-{player_id or player_name}"
        out.append(
            {
                "id": card_id,
                "match_id": match_id,
                "event_id": event_id or None,
                "date": match.get("date"),
                "opponent": match.get("opponent"),
                "venue": match.get("venue"),
                "competition": match.get("competition"),
                "league_id": match.get("league_id"),
                "bucket": match.get("bucket"),
                "player": player_name,
                "player_id": player_id,
                "minute": minute,
                "card": kind,
                "fotmob_reason": event.get("cardReason") or event.get("cardDescription"),
            }
        )
    return out


def _fetch_season_cards(season: str, *, refresh: bool = False) -> list[dict[str, Any]]:
    season = _validate_season(season)
    if refresh:
        _fixtures_cache.pop(season, None)
        _cards_cache.pop(season, None)

    cached = _cards_cache.get(season)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    fixtures = _fixtures_for_season(season)
    finished = [row for row in fixtures if row.get("finished")]
    cards: list[dict[str, Any]] = []
    if finished:
        with ThreadPoolExecutor(max_workers=min(8, len(finished))) as pool:
            futures = {pool.submit(_cards_for_match, match): match for match in finished}
            for future in as_completed(futures):
                try:
                    cards.extend(future.result())
                except Exception:
                    continue

    cards.sort(
        key=lambda row: (
            str(row.get("date") or ""),
            int(row.get("match_id") or 0),
            int(row.get("minute") or 0),
            str(row.get("player") or ""),
        )
    )
    _cards_cache[season] = (now, cards)
    return cards


def _risk_for_yellows(
    yellows: int, *, thresholds: tuple[dict[str, Any], ...] | list[dict[str, Any]]
) -> tuple[str, str]:
    """Return (status, risk label) using competition-specific caution thresholds."""
    levels = sorted(
        int(row.get("cards") or 0)
        for row in thresholds
        if int(row.get("cards") or 0) > 0
    )
    if not levels:
        if yellows <= 0:
            return "OK", "Clear"
        return "Watch", f"{yellows} caution(s)"
    hit = [level for level in levels if yellows >= level]
    if hit:
        top = hit[-1]
        label = next(
            (
                str(row.get("label") or "")
                for row in thresholds
                if int(row.get("cards") or 0) == top
            ),
            f"{top}+ cautions",
        )
        status = "Banned" if top == levels[-1] and yellows >= levels[-1] else "Watch"
        # Treat reaching the first ban step as Watch unless clearly past last listed.
        if yellows >= levels[-1] and len(levels) >= 3:
            status = "Banned"
        return status, label
    next_level = levels[0]
    if yellows == next_level - 1 and next_level > 1:
        return "Watch", f"One away from {next_level}"
    return "OK", "Clear"


def _player_rows(
    cards: list[dict[str, Any]],
    *,
    thresholds: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_player: dict[str, dict[str, Any]] = {}
    for card in cards:
        name = str(card.get("player") or "").strip()
        if not name:
            continue
        row = by_player.setdefault(
            name,
            {
                "player": name,
                "player_id": card.get("player_id"),
                "yellows": 0,
                "reds": 0,
                "last_card": "—",
                "last_date": "",
                "cards": [],
            },
        )
        if card.get("player_id") and not row.get("player_id"):
            row["player_id"] = card.get("player_id")
        kind = card.get("card")
        if kind == "Yellow":
            row["yellows"] += 1
        elif kind in {"Red", "SecondYellow"}:
            row["reds"] += 1
        date = str(card.get("date") or "")
        stamp = f"{date} {int(card.get('minute') or 0):03d}"
        if stamp >= str(row.get("last_date") or ""):
            row["last_date"] = stamp
            venue = card.get("venue") or ""
            opp = card.get("opponent") or ""
            minute = card.get("minute")
            code = card.get("offence_code")
            code_bit = f" · {code}" if code else ""
            row["last_card"] = f"{kind} {minute}' v {opp} ({venue}){code_bit}"
        row["cards"].append(card)

    players: list[dict[str, Any]] = []
    for row in by_player.values():
        status, risk = _risk_for_yellows(int(row["yellows"]), thresholds=thresholds)
        if int(row["reds"]) > 0 and status == "OK":
            status, risk = "Watch", "Red card on record this competition"
        players.append(
            {
                "player": row["player"],
                "player_id": row.get("player_id"),
                "yellows": row["yellows"],
                "reds": row["reds"],
                "last_card": row["last_card"],
                "risk": risk,
                "status": status,
            }
        )
    players.sort(key=lambda row: (-int(row["yellows"]), -int(row["reds"]), row["player"]))
    return players


def _decorate_cards(
    cards: list[dict[str, Any]], offences: dict[str, str]
) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for card in cards:
        row = dict(card)
        code = offences.get(str(card.get("id") or ""))
        row["offence_code"] = code
        row["offence_label"] = _OFFENCE_LABELS.get(code) if code else None
        decorated.append(row)
    return decorated


def _bucket_payload(
    *,
    meta: dict[str, Any],
    cards: list[dict[str, Any]],
) -> dict[str, Any]:
    thresholds = tuple(meta.get("thresholds") or ())
    players = _player_rows(cards, thresholds=thresholds)
    yellows = sum(1 for card in cards if card.get("card") == "Yellow")
    reds = sum(1 for card in cards if card.get("card") in {"Red", "SecondYellow"})
    coded = sum(1 for card in cards if card.get("offence_code"))
    return {
        "id": meta["id"],
        "label": meta["label"],
        "short": meta.get("short") or meta["label"],
        "rules": meta.get("rules") or "",
        "thresholds": list(thresholds),
        "cards": cards,
        "players": players,
        "summary": {
            "yellows": yellows,
            "reds": reds,
            "players_booked": len(players),
            "coded": coded,
            "uncoded": max(0, len(cards) - coded),
            "watch": sum(1 for row in players if row["status"] == "Watch"),
            "banned": sum(1 for row in players if row["status"] == "Banned"),
        },
    }


def build_suspension_payload(season: str | None = None, *, refresh: bool = False) -> dict[str, Any]:
    season = _validate_season(season)
    store = _load_store()
    offences = _load_offences()
    cards = _decorate_cards(_fetch_season_cards(season, refresh=refresh), offences)
    fixtures = _fixtures_for_season(season)
    buckets: dict[str, Any] = {}
    for meta in COMP_BUCKETS:
        bucket_cards = [card for card in cards if card.get("bucket") == meta["id"]]
        buckets[meta["id"]] = _bucket_payload(meta=meta, cards=bucket_cards)
    return {
        "season": season,
        "source": "fotmob",
        "team_id": FOTMOB_TEAM_ID,
        "bucket_order": [row["id"] for row in COMP_BUCKETS],
        "thresholds": list(COMP_BUCKETS[0]["thresholds"]),
        "staff_rules": STAFF_RULES,
        "staff": list(store.get("staff") or []),
        "offence_codes": {
            "yellow": YELLOW_OFFENCE_OPTIONS,
            "red": RED_OFFENCE_OPTIONS,
        },
        "fixtures_played": sum(1 for row in fixtures if row.get("finished")),
        "fixtures_total": len(fixtures),
        "buckets": buckets,
        "note": (
            "Replaces the Discipline sheet. Yellows/reds pull from FotMob per competition. "
            "Set C1–C7 / S1–S7 on each card. League starts & minutes are on Squad Availability."
        ),
    }


def set_card_offence(card_id: str, offence_code: str | None) -> dict[str, Any]:
    card_key = str(card_id or "").strip()
    if not card_key:
        raise HTTPException(status_code=400, detail="Missing card id")
    code = (offence_code or "").strip() or None
    if code and code not in _OFFENCE_LABELS:
        raise HTTPException(status_code=400, detail=f"Unknown offence code: {code}")
    offences = _load_offences()
    if code:
        offences[card_key] = code
    else:
        offences.pop(card_key, None)
    _save_offences(offences)
    return {
        "id": card_key,
        "offence_code": code,
        "offence_label": _OFFENCE_LABELS.get(code) if code else None,
    }


def add_staff_note(body: StaffNoteCreate) -> dict[str, Any]:
    store = _load_store()
    staff = list(store.get("staff") or [])
    staff.append(
        {
            "id": f"st-{uuid.uuid4().hex[:8]}",
            "name": body.name.strip(),
            "date": body.date[:10],
            "offence_code": body.offence_code.strip() or "C1",
            "notes": body.notes.strip(),
        }
    )
    store["staff"] = staff
    _save_store(store)
    return build_suspension_payload()


def delete_staff_note(note_id: str) -> dict[str, Any]:
    store = _load_store()
    before = list(store.get("staff") or [])
    after = [row for row in before if str(row.get("id")) != note_id]
    if len(after) == len(before):
        raise HTTPException(status_code=404, detail="Staff note not found")
    store["staff"] = after
    _save_store(store)
    return build_suspension_payload()


def register_suspension_tracker_routes(app: FastAPI) -> None:
    page_path = STANDALONE_DIR / "suspension-tracker.html"

    @app.get("/suspension-tracker", response_class=HTMLResponse)
    def suspension_tracker_page() -> HTMLResponse:
        if not page_path.is_file():
            raise HTTPException(status_code=404, detail="Suspension Tracker UI not found.")
        return HTMLResponse(page_path.read_text(encoding="utf-8"))

    @app.get("/api/suspension-tracker")
    def suspension_tracker_get(
        season: str = Query(CURRENT_SEASON),
        refresh: bool = Query(False),
    ) -> dict[str, Any]:
        return build_suspension_payload(season, refresh=refresh)

    @app.put("/api/suspension-tracker/card/{card_id:path}")
    def suspension_tracker_set_offence(
        card_id: str, body: OffenceUpdate
    ) -> dict[str, Any]:
        return set_card_offence(card_id, body.offence_code)

    @app.post("/api/suspension-tracker/staff")
    def suspension_tracker_add_staff(body: StaffNoteCreate) -> dict[str, Any]:
        return add_staff_note(body)

    @app.delete("/api/suspension-tracker/staff/{note_id}")
    def suspension_tracker_delete_staff(note_id: str) -> dict[str, Any]:
        return delete_staff_note(note_id)
