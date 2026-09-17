"""FotMob live overlay for pre-match two-pager fields Impect often lags.

Canonical from FotMob: next game, last starting XI, recent results, goals/assists.
Impect still owns style scores, xG, possession, average positions, and other KPIs.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

_UK_TZ = ZoneInfo("Europe/London")

from app.handout_badges import fotmob_crest_url_for_club, fotmob_team_id_for_club
from app.opponent_photos import opponent_photo_api_url

PORT_VALE_FOTMOB_ID = 9799
FOTMOB_TEAM_TTL_SECONDS = 10 * 60
TWO_MATCH_LIMIT = 2

_team_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_team_cache_lock = threading.Lock()

_CLUB_STOP = {
    "fc",
    "afc",
    "the",
    "club",
    "town",
    "city",
    "united",
    "utd",
    "athletic",
    "rovers",
    "wanderers",
    "county",
    "albion",
    "hotspur",
    "argyle",
}


def _norm_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _club_tokens(name: str | None) -> set[str]:
    text = re.sub(r"[^a-z0-9\s]+", " ", str(name or "").casefold())
    return {token for token in text.split() if token and token not in _CLUB_STOP}


def club_names_match(left: str | None, right: str | None) -> bool:
    if _norm_key(left) and _norm_key(left) == _norm_key(right):
        return True
    a = _club_tokens(left)
    b = _club_tokens(right)
    if not a or not b:
        return False
    return a == b or a.issubset(b) or b.issubset(a)


def _surname(name: str) -> str:
    parts = str(name or "").strip().split()
    return parts[-1] if parts else str(name or "")


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _format_kickoff(scheduled: str | None) -> tuple[str | None, str | None]:
    dt = _parse_dt(scheduled)
    if dt is None:
        return (str(scheduled)[:10] if scheduled else None), None
    local = dt.astimezone(_UK_TZ)
    return local.strftime("%A %d %B %Y"), local.strftime("%H:%M")


def _kickoff_label(scheduled: str | None, is_home: bool) -> str:
    prefix = "H" if is_home else "A"
    dt = _parse_dt(scheduled)
    if dt is None:
        return prefix
    local = dt.astimezone(_UK_TZ)
    short = f"{local.strftime('%a')} {local.day} {local.strftime('%b')}"
    return f"{prefix} {short} · {local.strftime('%H:%M')}"


def _date_token(value: Any) -> str:
    dt = _parse_dt(value)
    if dt is not None:
        return dt.date().isoformat()
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def _pct(value: Any, *, invert: bool = False) -> float:
    try:
        raw = float(value)
    except (TypeError, ValueError):
        raw = 0.5
    if invert:
        raw = 1.0 - raw
    return round(max(6.0, min(94.0, raw * 100.0)), 1)


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _fotmob_match_id_from_url(url: Any) -> int | None:
    text = str(url or "")
    match = re.search(r"#(\d+)\s*$", text)
    if not match:
        match = re.search(r"/(\d+)\s*$", text)
    if not match:
        return None
    return _int_or_none(match.group(1))


def fetch_fotmob_team_payload(team_id: int | str | None) -> dict[str, Any] | None:
    token = _int_or_none(team_id)
    if not token:
        return None
    now = time.time()
    with _team_cache_lock:
        cached = _team_cache.get(token)
        if cached and now - cached[0] < FOTMOB_TEAM_TTL_SECONDS:
            return dict(cached[1])
    try:
        from app.fixture_planner import _http

        response = _http.get(
            "https://www.fotmob.com/api/data/teams",
            params={"id": token},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        if not response.ok:
            return None
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, dict) or not payload:
        return None
    with _team_cache_lock:
        _team_cache[token] = (now, payload)
    return payload


def fetch_club_payload(club_name: str | None) -> dict[str, Any] | None:
    team_id = fotmob_team_id_for_club(club_name)
    return fetch_fotmob_team_payload(team_id)


def _band_from_starter(starter: dict[str, Any]) -> str:
    usual = _int_or_none(starter.get("usualPlayingPositionId"))
    if usual == 0:
        return "gk"
    if usual == 1:
        return "def"
    if usual == 3:
        return "attack"
    if usual == 2:
        return "mid"
    position_id = _int_or_none(starter.get("positionId")) or 0
    if position_id in {0, 10, 11}:
        return "gk"
    if 30 <= position_id < 50:
        return "def"
    if position_id >= 80:
        return "attack"
    return "mid"


def _layout_pct(starter: dict[str, Any]) -> tuple[float, float]:
    """Map FotMob verticalLayout onto our pitch (attack top, GK bottom).

    FotMob vertical x is mirrored vs left/right, y=0 is own goal.
    """
    layout = starter.get("verticalLayout") or {}
    x_pct = _pct(layout.get("x"), invert=True)
    y_pct = _pct(layout.get("y"), invert=True)
    return x_pct, y_pct


def parse_last_xi(
    payload: dict[str, Any],
    *,
    club_name: str | None,
    season: str | None,
    squad_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    lineup = (payload.get("overview") or {}).get("lastLineupStats") or {}
    formation = str(lineup.get("formation") or "").strip() or None
    starters = [row for row in (lineup.get("starters") or []) if isinstance(row, dict)]
    if not starters:
        return [], formation
    players: list[dict[str, Any]] = []
    for starter in starters[:11]:
        name = str(starter.get("name") or "").strip()
        if not name:
            continue
        x_pct, y_pct = _layout_pct(starter)
        band = _band_from_starter(starter)
        shirt = _int_or_none(starter.get("shirtNumber"))
        impect = _match_squad_player(name, squad_rows)
        player_id = (impect or {}).get("id") or starter.get("id")
        players.append(
            {
                "player_id": player_id,
                "fotmob_player_id": starter.get("id"),
                "name": name,
                "short_name": _surname(name),
                "shirt_number": shirt if shirt is not None else (impect or {}).get("shirt_number"),
                "position": band,
                "band": band,
                "x_pct": x_pct,
                "y_pct": y_pct,
                "starts": 1,
                "minutes": 90,
                "source": "fotmob",
                "position_locked": True,
                "photo_url": opponent_photo_api_url(
                    name,
                    club_name=club_name,
                    season=season,
                    shirt_number=shirt,
                )
                if club_name
                else None,
            }
        )
    return players, formation


def _match_squad_player(
    name: str,
    squad_rows: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    key = _norm_key(name)
    surname = _norm_key(_surname(name))
    if not key:
        return None
    rows = [row for row in (squad_rows or []) if isinstance(row, dict)]
    for row in rows:
        if _norm_key(row.get("name") or row.get("player_name")) == key:
            return row
    surname_hits = [
        row
        for row in rows
        if _norm_key(_surname(str(row.get("name") or row.get("player_name") or "")))
        == surname
    ]
    if len(surname_hits) == 1:
        return surname_hits[0]
    return None


def _side_is_ours(side: dict[str, Any] | None, team_id: int | None) -> bool:
    side = side or {}
    if side.get("isOurTeam") is True:
        return True
    if team_id is None:
        return False
    return _int_or_none(side.get("id")) == int(team_id)


def parse_recent_results(
    payload: dict[str, Any],
    *,
    limit: int = TWO_MATCH_LIMIT,
) -> list[dict[str, Any]]:
    details = payload.get("details") or {}
    team_id = _int_or_none(details.get("id"))
    rows: list[dict[str, Any]] = []
    for item in (payload.get("overview") or {}).get("teamForm") or []:
        if not isinstance(item, dict):
            continue
        tooltip = item.get("tooltipText") if isinstance(item.get("tooltipText"), dict) else {}
        home = item.get("home") if isinstance(item.get("home"), dict) else {}
        away = item.get("away") if isinstance(item.get("away"), dict) else {}
        is_home = _side_is_ours(home, team_id)
        if not is_home and not _side_is_ours(away, team_id):
            continue
        home_score = _int_or_none(tooltip.get("homeScore"))
        away_score = _int_or_none(tooltip.get("awayScore"))
        if home_score is None or away_score is None:
            continue
        goals_for = home_score if is_home else away_score
        goals_against = away_score if is_home else home_score
        if goals_for > goals_against:
            result = "W"
        elif goals_for < goals_against:
            result = "L"
        else:
            result = "D"
        opponent = away if is_home else home
        opponent_name = str(
            opponent.get("name")
            or tooltip.get("awayTeam" if is_home else "homeTeam")
            or "Opponent"
        )
        kickoff = (
            (item.get("date") or {}).get("utcTime")
            if isinstance(item.get("date"), dict)
            else tooltip.get("utcTime")
        )
        rows.append(
            {
                "id": _fotmob_match_id_from_url(item.get("linkToMatch")),
                "fotmob_match_id": _fotmob_match_id_from_url(item.get("linkToMatch")),
                "date": kickoff,
                "opponent": opponent_name,
                "opponent_badge_url": fotmob_crest_url_for_club(opponent_name)
                or item.get("imageUrl"),
                "venue": "H" if is_home else "A",
                "result": result,
                "score": f"{goals_for}-{goals_against}",
                "goals_for": goals_for,
                "goals_against": goals_against,
                "competition": str(item.get("tournamentName") or "").strip() or None,
                "source": "fotmob",
            }
        )
    rows.sort(key=lambda row: str(row.get("date") or ""))
    return rows[-limit:]


def parse_top_players(
    payload: dict[str, Any],
    key: str,
    *,
    club_name: str | None,
    season: str | None,
    squad_rows: list[dict[str, Any]] | None = None,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    bucket = ((payload.get("overview") or {}).get("topPlayers") or {}).get(key) or {}
    players: list[dict[str, Any]] = []
    for row in bucket.get("players") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        value = row.get("value")
        if value is None:
            value = (row.get("stat") or {}).get("value")
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number <= 0:
            continue
        impect = _match_squad_player(name, squad_rows)
        shirt = (impect or {}).get("shirt_number")
        label = str(int(round(number))) if abs(number - round(number)) < 0.05 else f"{number:.1f}".rstrip("0").rstrip(".")
        players.append(
            {
                "player_id": (impect or {}).get("id") or row.get("id"),
                "fotmob_player_id": row.get("id"),
                "name": name,
                "short_name": _surname(name),
                "shirt_number": shirt,
                "photo_url": opponent_photo_api_url(
                    name,
                    club_name=club_name,
                    season=season,
                    shirt_number=shirt,
                )
                if club_name
                else None,
                "value": round(number, 2),
                "value_label": label,
                "source": "fotmob",
            }
        )
        if len(players) >= top_n:
            break
    return players


def parse_next_match(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw = (payload.get("overview") or {}).get("nextMatch")
    if not isinstance(raw, dict) or not raw:
        return None
    details = payload.get("details") or {}
    team_id = _int_or_none(details.get("id"))
    home = raw.get("home") if isinstance(raw.get("home"), dict) else {}
    away = raw.get("away") if isinstance(raw.get("away"), dict) else {}
    is_home = _side_is_ours(home, team_id)
    opponent = away if is_home else home
    status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
    if status.get("finished"):
        return None
    opponent_name = str(opponent.get("name") or "").strip()
    if not opponent_name:
        return None
    return {
        "id": raw.get("id"),
        "date": status.get("utcTime"),
        "opponent": opponent_name,
        "opponent_fotmob_id": opponent.get("id"),
        "is_home": is_home,
        "competition": str((raw.get("tournament") or {}).get("name") or "").strip() or None,
        "source": "fotmob",
    }


def _same_game(impect: dict[str, Any], fotmob: dict[str, Any]) -> bool:
    if not club_names_match(impect.get("opponent"), fotmob.get("opponent")):
        return False
    left = _date_token(impect.get("date") or impect.get("scheduled_date"))
    right = _date_token(fotmob.get("date"))
    return bool(left) and left == right


def overlay_two_match(
    two_match: dict[str, Any] | None,
    payload: dict[str, Any],
    *,
    club_name: str | None,
    season: str | None,
    squad_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    two = dict(two_match or {})
    fotmob_matches = parse_recent_results(payload)
    last_xi, last_formation = parse_last_xi(
        payload,
        club_name=club_name,
        season=season,
        squad_rows=squad_rows,
    )
    impect_matches = [dict(row) for row in two.get("matches") or [] if isinstance(row, dict)]
    merged: list[dict[str, Any]] = []
    for index, fotmob in enumerate(fotmob_matches):
        impect = next((row for row in impect_matches if _same_game(row, fotmob)), None)
        row = dict(fotmob)
        if impect:
            row["match_id"] = impect.get("match_id")
            row["opponent_id"] = impect.get("opponent_id")
            row["opponent_badge_url"] = (
                impect.get("opponent_badge_url")
                or row.get("opponent_badge_url")
            )
            if impect.get("xg_for") is not None:
                row["xg_for"] = impect.get("xg_for")
            if impect.get("xg_against") is not None:
                row["xg_against"] = impect.get("xg_against")
            if impect.get("possession_pct") is not None:
                row["possession_pct"] = impect.get("possession_pct")
            row["formation"] = impect.get("formation") or row.get("formation")
            row["pitch_players"] = impect.get("pitch_players") or []
            row["players"] = impect.get("players") or []
            row["impect_match"] = True
        else:
            row["pitch_players"] = []
            row["players"] = []
        is_last = index == len(fotmob_matches) - 1
        if is_last and last_xi:
            row["pitch_players"] = last_xi
            row["formation"] = last_formation or row.get("formation")
            row["source"] = "fotmob"
        merged.append(row)

    if merged:
        two["matches"] = merged
        two["match_count"] = len(merged)
        last = merged[-1]
        two["last_formation"] = last.get("formation") or last_formation
        two["last_xi"] = last_xi or last.get("pitch_players") or two.get("last_xi") or []
    elif last_xi:
        two["last_xi"] = last_xi
        two["last_formation"] = last_formation or two.get("last_formation")

    goals = parse_top_players(
        payload,
        "byGoals",
        club_name=club_name,
        season=season,
        squad_rows=squad_rows,
    )
    assists = parse_top_players(
        payload,
        "byAssists",
        club_name=club_name,
        season=season,
        squad_rows=squad_rows,
    )
    boards = [dict(board) for board in two.get("stat_leaders") or []]
    by_key = {str(board.get("key") or ""): board for board in boards}

    def _board(key: str, label: str, players: list[dict[str, Any]]) -> dict[str, Any]:
        existing = by_key.get(key) or {"key": key, "label": label, "per90": False}
        existing["players"] = players
        existing["scope_label"] = "Season total"
        existing["source"] = "fotmob"
        return existing

    if goals:
        by_key["goals"] = _board("goals", "Most goals", goals)
    if assists:
        by_key["assists"] = _board("assists", "Most assists", assists)
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("goals", "assists"):
        if key in by_key:
            ordered.append(by_key[key])
            seen.add(key)
    for board in boards:
        key = str(board.get("key") or "")
        if key and key not in seen:
            ordered.append(by_key.get(key) or board)
            seen.add(key)
    if ordered:
        two["stat_leaders"] = ordered
    two["live_source"] = {
        "last_xi": "fotmob" if last_xi else "impect",
        "results": "fotmob" if merged else "impect",
        "goals_assists": "fotmob" if goals or assists else "impect",
    }
    return two


def overlay_form(
    form: list[dict[str, Any]] | None,
    payload: dict[str, Any],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    current = [dict(row) for row in form or [] if isinstance(row, dict)]
    fotmob = parse_recent_results(payload, limit=limit)
    if not fotmob:
        return current

    def _key(row: dict[str, Any]) -> tuple[str, str]:
        return (_date_token(row.get("date")), _norm_key(row.get("opponent")))

    have = {_key(row) for row in current}
    extra: list[dict[str, Any]] = []
    for row in fotmob:
        token = _key(row)
        if token in have or not token[0]:
            continue
        extra.append(
            {
                "match_id": row.get("fotmob_match_id") or row.get("id"),
                "date": row.get("date"),
                "venue": row.get("venue"),
                "opponent": row.get("opponent"),
                "opponent_image_url": row.get("opponent_badge_url"),
                "score": row.get("score"),
                "goals_for": row.get("goals_for"),
                "goals_against": row.get("goals_against"),
                "result": row.get("result"),
                "source": "fotmob",
            }
        )
        have.add(token)
    if not extra:
        return current
    merged = current + extra
    merged.sort(key=lambda row: str(row.get("date") or ""))
    return merged[-limit:]


def overlay_fixture_kickoff(
    fixture: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    current = dict(fixture or {})
    nxt = parse_next_match(payload)
    if not nxt:
        return current
    raw_opp = current.get("opponent")
    opponent = (
        str(raw_opp.get("name") or "")
        if isinstance(raw_opp, dict)
        else str(raw_opp or "")
    )
    # Only stamp the forthcoming Vale fixture — don't rewrite a backdata report.
    selected_dt = _parse_dt(current.get("scheduled_date"))
    next_dt = _parse_dt(nxt.get("date"))
    same_kickoff = (
        selected_dt is None
        or next_dt is None
        or abs((selected_dt - next_dt).total_seconds()) <= 3 * 24 * 3600
    )
    if club_names_match(nxt.get("opponent"), "Port Vale") and same_kickoff:
        current["scheduled_date"] = nxt.get("date") or current.get("scheduled_date")
        current["is_home"] = not bool(nxt.get("is_home"))
        current["venue"] = "Home" if current["is_home"] else "Away"
        date_label, time_label = _format_kickoff(current.get("scheduled_date"))
        current["date_label"] = date_label or current.get("date_label")
        current["time_label"] = time_label or current.get("time_label")
        pv_name = (current.get("port_vale") or {}).get("name") or "Port Vale"
        opp_name = opponent or "Opponent"
        current["fixture_line"] = (
            f"{pv_name} vs {opp_name}" if current["is_home"] else f"{opp_name} vs {pv_name}"
        )
        current["source"] = "fotmob"
        return current
    if opponent and club_names_match(nxt.get("opponent"), opponent):
        current["scheduled_date"] = nxt.get("date") or current.get("scheduled_date")
        current["is_home"] = bool(nxt.get("is_home"))
        current["source"] = "fotmob"
    return current


def apply_fotmob_live_overlay(report: dict[str, Any] | None) -> dict[str, Any]:
    """Refresh next game / XI / results / G/A from FotMob; leave Impect fields intact."""
    hydrated = dict(report or {})
    club_name = str((hydrated.get("opponent") or {}).get("name") or "")
    if not club_name:
        return hydrated
    try:
        payload = fetch_club_payload(club_name)
    except Exception:
        payload = None
    if not payload:
        return hydrated
    season = str(hydrated.get("season") or "") or None
    squad_rows = list(hydrated.get("squad") or [])
    try:
        hydrated["two_match"] = overlay_two_match(
            hydrated.get("two_match"),
            payload,
            club_name=club_name,
            season=season,
            squad_rows=squad_rows,
        )
    except Exception:
        pass
    try:
        hydrated["form"] = overlay_form(hydrated.get("form"), payload)
    except Exception:
        pass
    try:
        hydrated["fixture"] = overlay_fixture_kickoff(hydrated.get("fixture"), payload)
    except Exception:
        pass
    return hydrated


def overlay_fotmob_vale_fixtures(
    fixtures: list[dict[str, Any]] | None,
    iteration_id: int,
) -> list[dict[str, Any]]:
    """Mark finished games from FotMob and ensure Vale's next opponent is present."""
    rows = [dict(row) for row in fixtures or []]
    try:
        payload = fetch_fotmob_team_payload(PORT_VALE_FOTMOB_ID)
    except Exception:
        payload = None
    if not payload:
        return rows

    completed = parse_recent_results(payload, limit=12)
    nxt = parse_next_match(payload)

    for row in rows:
        opponent_name = str((row.get("opponent") or {}).get("name") or "")
        fotmob = next(
            (
                item
                for item in completed
                if club_names_match(item.get("opponent"), opponent_name)
                and (
                    not _date_token(row.get("scheduled_date"))
                    or _date_token(row.get("scheduled_date")) == _date_token(item.get("date"))
                )
            ),
            None,
        )
        if fotmob is None:
            continue
        if not row.get("played"):
            row["played"] = True
            row["kickoff_label"] = str(fotmob.get("score") or row.get("kickoff_label") or "")
        row["scheduled_date"] = fotmob.get("date") or row.get("scheduled_date")

    if nxt:
        opponent_name = str(nxt.get("opponent") or "")
        existing = next(
            (
                row
                for row in rows
                if club_names_match((row.get("opponent") or {}).get("name"), opponent_name)
                and not row.get("played")
            ),
            None,
        )
        if existing is not None:
            existing["scheduled_date"] = nxt.get("date") or existing.get("scheduled_date")
            existing["is_home"] = bool(nxt.get("is_home"))
            existing["source"] = "fotmob"
            existing["kickoff_label"] = _kickoff_label(
                existing.get("scheduled_date"), bool(existing.get("is_home"))
            )
        else:
            try:
                from app.pre_match import _enrich_team_crest, _squads_map

                squads = _squads_map(int(iteration_id))
                match = next(
                    (
                        item
                        for item in squads.values()
                        if club_names_match(item.get("name"), opponent_name)
                    ),
                    None,
                )
                if match is not None:
                    opponent = _enrich_team_crest(
                        {
                            "id": int(match.get("id") or 0),
                            "name": str(match.get("name") or opponent_name),
                            "image_url": match.get("imageUrl"),
                        },
                        int(iteration_id),
                    )
                    rows.append(
                        {
                            "match_id": None,
                            "match_day": None,
                            "scheduled_date": nxt.get("date"),
                            "kickoff_label": _kickoff_label(
                                nxt.get("date"), bool(nxt.get("is_home"))
                            ),
                            "is_home": bool(nxt.get("is_home")),
                            "played": False,
                            "source": "fotmob",
                            "opponent": opponent,
                        }
                    )
            except Exception:
                pass
    return rows


def pick_fotmob_next_fixture(fixtures: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    try:
        payload = fetch_fotmob_team_payload(PORT_VALE_FOTMOB_ID)
    except Exception:
        payload = None
    nxt = parse_next_match(payload or {})
    if not nxt:
        return None
    for row in fixtures or []:
        opponent_name = str((row.get("opponent") or {}).get("name") or "")
        if club_names_match(opponent_name, nxt.get("opponent")) and not row.get("played"):
            return row
    return None
