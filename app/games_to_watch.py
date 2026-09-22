"""Games to Watch — rank played and upcoming fixtures for video scouting.

Two looks: High scores (profile quality) and Young players (U27s playing).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.fixture_planner import (
    DEFAULT_SEASON,
    FIXTURE_LEAGUE_BY_UI,
    FIXTURE_STAFF,
    FIXTURE_STAFF_TEAMS,
    FixtureAssignmentUpdate,
    WATCH_TYPES,
    build_fixture_planner_payload,
    get_fixture_assignments,
    upsert_fixture_assignment,
    _fixture_is_played,
    _normalize_team_name,
)
from app.home_dashboard import STANDOUTS_LEAGUES
from app.paths import GAMES_TO_WATCH_DATA_DIR, STANDALONE_DIR, ensure_data_dirs
from app import transfer_status
from app.analysis_cache import read_json, write_json
from app.who_to_scout import _load_standouts_raw_payload, build_club_team_sheet

logger = logging.getLogger(__name__)

GAMES_CACHE_TTL_SECONDS = 5 * 60
GAMES_CACHE_STALE_SECONDS = 6 * 3600
_games_payload_mem: dict[str, tuple[float, dict[str, Any]]] = {}
_games_payload_lock = threading.Lock()
_games_refreshing: set[str] = set()
_watched_lock = threading.Lock()

U27_MAX_AGE = 26
LIKELY_SQUAD_SIZE = 14
HEADLINE_COUNT = 3
LOOKAHEAD_DAYS = 45
# Fixtures marked watched within this window leave the "Haven't watched recently" section.
RECENT_WATCHED_DAYS = 21
WATCHED_PATH = GAMES_TO_WATCH_DATA_DIR / "watched.json"

SCORING_NOTE = (
    "High scores ranks games by profile quality. Young players ranks games by U27s "
    "(26 and under) actually playing. Both is the midpoint of those two lists."
)
SCORING_NOTES = {
    "scores": (
        "Ranking by profile quality in each league. Age is secondary. "
        "Young = U27 (26 and under). All leagues only keeps the best few "
        "games in each league at the top."
    ),
    "young": (
        "Ranking by U27s actually playing (26 and under). Best in each league, "
        "not just academy sides. All leagues only keeps the best few games "
        "in each league at the top."
    ),
    "both": (
        "Ranking games that have both strong profile scores and U27s playing. "
        "Young = U27 (26 and under). All leagues only keeps the best few "
        "games in each league at the top."
    ),
}

# Impect profiles are percentiles vs peers in that competition. PL2 / U21 cups
# have smaller, same-age pools, so a 70 there is not a 70 in League One.
ACADEMY_LEAGUES = frozenset(
    {
        "PL2",
        "Premier League Cup",
        "Professional Development League",
    }
)
ACADEMY_SCORE_FACTOR = 0.78
ACADEMY_LIST_FACTOR = 0.82
ACADEMY_PRIOR = 46.0
ACADEMY_SHRINK_K = 12
ACADEMY_SHRINK_BELOW = 20

# All-leagues mix: a 144-game Irish season cannot park 40 games in Must watch.
# Keep the best few in each league at full strength, then step the rest down.
# Irish / Scottish keep fewer slots — Vale sign from EFL first.
MIX_KEEP_DEFAULT = 6
MIX_KEEP_BY_LEAGUE = {
    "Irish Prem": 4,
    "Scottish Prem": 4,
}
MIX_STEP = 12


class AssignBody(BaseModel):
    fixture_id: str
    staff: list[str] | str = ""
    watch_type: str = "VIDEO"
    season: str = ""
    league: str = ""
    home: str = ""
    away: str = ""
    date: str = ""
    kickoff_utc: str | None = None
    watched_players: list[dict[str, Any]] = Field(default_factory=list)


class MarkWatchedBody(BaseModel):
    fixture_id: str
    home: str = ""
    away: str = ""
    league: str = ""
    date: str = ""
    season: str = ""
    clear: bool = False


def _empty_watched_store() -> dict[str, Any]:
    return {"version": 1, "updated_at": None, "watched": {}}


def _load_watched_store() -> dict[str, Any]:
    ensure_data_dirs()
    with _watched_lock:
        if not WATCHED_PATH.exists():
            return _empty_watched_store()
        try:
            payload = json.loads(WATCHED_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_watched_store()
        if not isinstance(payload, dict):
            return _empty_watched_store()
        watched = payload.get("watched")
        if not isinstance(watched, dict):
            payload["watched"] = {}
        return payload


def _save_watched_store(payload: dict[str, Any]) -> None:
    ensure_data_dirs()
    GAMES_TO_WATCH_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload["version"] = 1
    payload["updated_at"] = datetime.now(UTC).isoformat()
    temp_path = WATCHED_PATH.with_suffix(".json.tmp")
    with _watched_lock:
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(WATCHED_PATH)


def get_watched_marks() -> dict[str, Any]:
    """Return fixture_id → {last_watched_at, ...} marks for Games to Watch recency."""
    store = _load_watched_store()
    watched: dict[str, Any] = {}
    for fixture_id, row in dict(store.get("watched") or {}).items():
        if not isinstance(row, dict):
            continue
        stamp = str(row.get("last_watched_at") or "").strip()
        if not stamp:
            continue
        watched[str(fixture_id)] = {
            "fixture_id": str(fixture_id),
            "last_watched_at": stamp,
            "home": str(row.get("home") or ""),
            "away": str(row.get("away") or ""),
            "league": str(row.get("league") or ""),
            "date": str(row.get("date") or "")[:10],
            "season": str(row.get("season") or ""),
        }
    return {
        "watched": watched,
        "updated_at": store.get("updated_at"),
        "recent_days": RECENT_WATCHED_DAYS,
    }


def mark_fixture_watched(body: MarkWatchedBody) -> dict[str, Any]:
    """Persist last_watched_at for a fixture (or clear it)."""
    fixture_id = str(body.fixture_id or "").strip()
    if not fixture_id:
        raise HTTPException(status_code=400, detail="fixture_id is required")
    store = _load_watched_store()
    watched = dict(store.get("watched") or {})
    if body.clear:
        watched.pop(fixture_id, None)
        store["watched"] = watched
        _save_watched_store(store)
        return {
            "ok": True,
            "fixture_id": fixture_id,
            "last_watched_at": None,
            "recent_days": RECENT_WATCHED_DAYS,
        }
    now = datetime.now(UTC).isoformat()
    watched[fixture_id] = {
        "fixture_id": fixture_id,
        "last_watched_at": now,
        "home": str(body.home or "").strip(),
        "away": str(body.away or "").strip(),
        "league": str(body.league or "").strip(),
        "date": str(body.date or "").strip()[:10],
        "season": str(body.season or "").strip() or DEFAULT_SEASON,
    }
    store["watched"] = watched
    _save_watched_store(store)
    return {
        "ok": True,
        "fixture_id": fixture_id,
        "last_watched_at": now,
        "recent_days": RECENT_WATCHED_DAYS,
        "mark": watched[fixture_id],
    }


def _attach_watched_marks(rows: list[dict[str, Any]]) -> None:
    marks = get_watched_marks().get("watched") or {}
    for row in rows:
        fixture_id = str(row.get("fixture_id") or "")
        mark = marks.get(fixture_id) if fixture_id else None
        row["last_watched_at"] = (
            str(mark.get("last_watched_at") or "") if isinstance(mark, dict) else None
        ) or None


def _club_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").casefold())


_FC_TOKEN = re.compile(r"\bfc\b", re.I)
_FOOTBALL_CLUB = re.compile(r"\bfootball club\b", re.I)


def _name_variants(name: str) -> list[str]:
    """FotMob 'Bohemian FC' and Impect 'Bohemian Football Club' must hit the same keys."""
    raw = str(name or "").strip()
    out: list[str] = []
    for variant in (
        raw,
        _FC_TOKEN.sub("Football Club", raw) if raw else "",
        _FOOTBALL_CLUB.sub("FC", raw) if raw else "",
        _normalize_team_name(raw),
    ):
        token = str(variant or "").strip()
        if token and token not in out:
            out.append(token)
    return out


def _core_club_key(name: str) -> str:
    key = _club_key(name)
    for prefix in ("afc", "fc", "cf", "sc"):
        if key.startswith(prefix) and len(key) > len(prefix) + 2:
            key = key[len(prefix) :]
            break
    for suffix in ("afc", "fc", "cf"):
        if key.endswith(suffix) and len(key) > len(suffix) + 2:
            key = key[: -len(suffix)]
            break
    return key


def _flex_club_keys(key: str) -> list[str]:
    """Bohemian ↔ Bohemians, plus the compact key itself."""
    keys: list[str] = []
    if key and key not in keys:
        keys.append(key)
    if len(key) < 6:
        return keys
    if key.endswith("s"):
        stem = key[:-1]
        if stem and stem not in keys:
            keys.append(stem)
    else:
        plural = key + "s"
        if plural not in keys:
            keys.append(plural)
    return keys


def _club_lookup_keys(name: str) -> list[str]:
    keys: list[str] = []
    for variant in _name_variants(name):
        for key in (_club_key(variant), _core_club_key(variant)):
            for token in _flex_club_keys(key):
                if token and token not in keys:
                    keys.append(token)
    return keys


def adjust_profile_for_league(
    overall: float,
    *,
    league: str,
    club_n: int = 0,
) -> float:
    """Map academy percentiles onto a senior-comparable scale.

    A thin U21 pool makes average lads look like 70s. Shrink harder when the
    club has few scored players.
    """
    score = float(overall)
    if str(league or "").strip() not in ACADEMY_LEAGUES:
        return score
    mapped = score * ACADEMY_SCORE_FACTOR
    if club_n and club_n < ACADEMY_SHRINK_BELOW:
        weight = club_n / (club_n + ACADEMY_SHRINK_K)
        mapped = weight * mapped + (1.0 - weight) * ACADEMY_PRIOR
    return mapped


def _mid_percentile(value: float, values: list[float]) -> float:
    if not values:
        return 50.0
    less = sum(1 for item in values if item < value)
    equal = sum(1 for item in values if item == value)
    return (less + 0.5 * equal) / len(values) * 100.0


def display_watch_pct(
    raw: float | None,
    *,
    league: str,
    league_raws: list[float],
) -> int | None:
    """Turn a raw profile blend into a within-league 1–99 so EFL can reach Must watch."""
    if raw is None:
        return None
    pool = list(league_raws) or [float(raw)]
    pct = _mid_percentile(float(raw), pool)
    if str(league or "").strip() in ACADEMY_LEAGUES:
        pct *= ACADEMY_LIST_FACTOR
    return int(round(max(1.0, min(99.0, pct))))


def _apply_league_relative_field(
    rows: list[dict[str, Any]],
    *,
    source: str,
    dest: str,
    stash: str | None = None,
) -> None:
    by_league: dict[str, list[float]] = {}
    for row in rows:
        raw = row.get(source)
        if stash:
            row[stash] = raw
        if raw is None:
            continue
        by_league.setdefault(str(row.get("league") or ""), []).append(float(raw))
    for row in rows:
        raw = row.get(stash) if stash else row.get(source)
        row[dest] = display_watch_pct(
            raw,
            league=str(row.get("league") or ""),
            league_raws=by_league.get(str(row.get("league") or ""), []),
        )


def apply_league_relative_watch(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best game in League One and best game in Irish Prem both land near the top.

    score_pct = high-profile look. young_pct = U27s-playing look.
    watch_pct stays as the blended rank for older callers.
    """
    _apply_league_relative_field(
        rows, source="watch_pct", dest="watch_pct", stash="watch_raw"
    )
    _apply_league_relative_field(rows, source="quality_pct", dest="score_pct")
    _apply_league_relative_field(rows, source="youth_pct", dest="young_pct")
    for row in rows:
        row["both_pct"] = _both_look_pct(row.get("score_pct"), row.get("young_pct"))
    apply_all_leagues_depth(rows)
    return rows


def _mix_keep_for(league: str) -> int:
    return MIX_KEEP_BY_LEAGUE.get(str(league or "").strip(), MIX_KEEP_DEFAULT)


def _apply_depth_mix(rows: list[dict[str, Any]], source: str, dest: str) -> None:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get(source) is None:
            row[dest] = None
            continue
        groups.setdefault(str(row.get("league") or ""), []).append(row)
    for league, group in groups.items():
        group.sort(
            key=lambda row: (int(row[source]), str(row.get("date") or "")),
            reverse=True,
        )
        keep = _mix_keep_for(league)
        for index, row in enumerate(group):
            extra = max(0, index + 1 - keep)
            row[dest] = max(1, min(99, int(row[source]) - MIX_STEP * extra))


def apply_all_leagues_depth(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stop a long season (Irish Prem) flooding All leagues with Must watch."""
    _apply_depth_mix(rows, "score_pct", "score_mix_pct")
    _apply_depth_mix(rows, "young_pct", "young_mix_pct")
    _apply_depth_mix(rows, "watch_pct", "watch_mix_pct")
    _apply_depth_mix(rows, "both_pct", "both_mix_pct")
    return rows


def _both_look_pct(score_pct: Any, young_pct: Any) -> int | None:
    """Midpoint of the two looks — high scores alone or youth alone cannot win Both."""
    have_score = score_pct is not None
    have_young = young_pct is not None
    if not have_score and not have_young:
        return None
    if not have_score:
        return int(young_pct)
    if not have_young:
        return int(score_pct)
    return int(round((int(score_pct) + int(young_pct)) / 2))


def youth_weight(age: int | None) -> float:
    """How much a player's age counts toward 'should we watch this game'.

    U21 = full weight. U27 still high. 30+ barely registers, so a card full of
    older players cannot rank near the top even if a couple of scores look fine.
    """
    if age is None:
        return 0.45
    if age <= 20:
        return 1.0
    if age <= 23:
        return 0.90
    if age <= 26:
        return 0.78
    if age <= 29:
        return 0.32
    return 0.08


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _player_id(row: dict[str, Any]) -> int:
    return int(row.get("playerId") or row.get("player_id") or 0)


def _normalize_player(row: dict[str, Any]) -> dict[str, Any] | None:
    player_id = _player_id(row)
    overall = row.get("overall")
    if overall is None:
        return None
    try:
        overall_n = round(float(overall), 1)
    except (TypeError, ValueError):
        return None
    age = _as_int(row.get("age"))
    minutes = max(0.0, _as_float(row.get("minutes")))
    name = str(row.get("name") or "").strip()
    if not name:
        return None
    scores = row.get("profileScores") or row.get("profile_scores") or {}
    if not isinstance(scores, dict):
        scores = {}
    best_name = str(row.get("bestProfile") or row.get("top_profile") or "").strip()
    best_score = row.get("bestProfileScore")
    if best_score is None:
        best_score = row.get("top_profile_score")
    return {
        "player_id": player_id or None,
        "name": name,
        "age": age,
        "minutes": int(round(minutes)),
        "overall": overall_n,
        "club": str(row.get("club") or "").strip(),
        "league": str(row.get("league") or "").strip(),
        "position": str(row.get("position") or "").strip(),
        "position_label": str(
            row.get("positionLabel") or row.get("position_label") or ""
        ).strip(),
        "profile_scores": scores,
        "best_profile": best_name,
        "best_profile_score": (
            round(float(best_score), 1) if best_score is not None else None
        ),
        "u27": age is not None and age <= U27_MAX_AGE,
        "watch_value": round(overall_n * youth_weight(age), 1),
        "dossier_href": f"/player/{player_id}" if player_id else "",
    }


def _dedupe_players(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per player — keep the stronger / more-minutes copy."""
    best: dict[str, dict[str, Any]] = {}
    for raw in rows:
        player = _normalize_player(raw)
        if not player:
            continue
        key = str(player.get("player_id") or player["name"].casefold())
        current = best.get(key)
        if current is None:
            best[key] = player
            continue
        current_rank = (
            float(current.get("minutes") or 0),
            float(current.get("overall") or 0),
        )
        next_rank = (
            float(player.get("minutes") or 0),
            float(player.get("overall") or 0),
        )
        if next_rank > current_rank:
            best[key] = player
    return list(best.values())


def _left_listed_club(row: dict[str, Any]) -> bool:
    status = str((row.get("transfer") or {}).get("status") or "")
    return status in {transfer_status.GONE, transfer_status.LOAN_OUT}


def _annotate_side_players(rows: list[dict[str, Any]], club_name: str) -> list[dict[str, Any]]:
    """Flag loans and departures against the club on this team sheet."""
    listed = str(club_name or "").strip()
    for row in rows:
        if listed and not str(row.get("club") or "").strip():
            row["club"] = listed
    transfer_status.annotate_all(rows)
    if not listed:
        return rows
    retry = [row for row in rows if not row.get("transfer")]
    if not retry:
        return rows
    saved = [(row, str(row.get("club") or "")) for row in retry]
    for row, _ in saved:
        row["club"] = listed
    transfer_status.annotate_all(retry)
    for row, previous in saved:
        if not row.get("transfer") and previous:
            row["club"] = previous
    return _sort_sheet_players(rows)


def likely_players(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Players most likely to be on the video — regulars first, then high scores."""
    scored = [row for row in players if row.get("overall") is not None]
    scored.sort(
        key=lambda row: (
            -float(row.get("minutes") or 0),
            -float(row.get("overall") or 0),
            str(row.get("name") or ""),
        )
    )
    with_minutes = [row for row in scored if float(row.get("minutes") or 0) > 0]
    pool = with_minutes if len(with_minutes) >= 8 else scored
    return pool[:LIKELY_SQUAD_SIZE]


def score_side(
    players: list[dict[str, Any]],
    *,
    league: str = "",
) -> dict[str, Any] | None:
    watchable = [row for row in players if not _left_listed_club(row)]
    likely = likely_players(watchable)
    if not likely:
        return None
    club_n = sum(1 for row in players if row.get("overall") is not None)
    total_w = 0.0
    watch_acc = 0.0
    quality_acc = 0.0
    u27_w = 0.0
    u27_n = 0
    for row in likely:
        weight = max(float(row.get("minutes") or 0), 1.0)
        overall = adjust_profile_for_league(
            float(row.get("overall") or 0),
            league=league,
            club_n=club_n,
        )
        age = _as_int(row.get("age"))
        watch_acc += overall * youth_weight(age) * weight
        quality_acc += overall * weight
        total_w += weight
        if age is not None and age <= U27_MAX_AGE:
            u27_w += weight
            u27_n += 1
    if total_w <= 0:
        return None
    return {
        "watch_pct": watch_acc / total_w,
        "quality_pct": quality_acc / total_w,
        "u27_share": u27_w / total_w,
        "u27_count": u27_n,
        "player_count": len(likely),
        "players": likely,
    }


def combine_side_scores(
    home: dict[str, Any] | None,
    away: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Equal weight per team so a bigger squad list cannot swamp the other side."""
    sides = [side for side in (home, away) if side]
    if not sides:
        return None
    age_weighted = sum(float(side["watch_pct"]) for side in sides) / len(sides)
    quality = sum(float(side["quality_pct"]) for side in sides) / len(sides)
    u27_share = sum(float(side["u27_share"]) for side in sides) / len(sides)
    u27_count = sum(int(side["u27_count"]) for side in sides)
    player_count = sum(int(side["player_count"]) for side in sides)
    likely: list[dict[str, Any]] = []
    for side in sides:
        likely.extend(side.get("players") or [])
    young_heads = [row for row in likely if row.get("u27")]
    young_heads.sort(
        key=lambda row: (
            -float(row.get("watch_value") or 0),
            -float(row.get("overall") or 0),
        )
    )
    score_heads = sorted(
        likely,
        key=lambda row: (
            -float(row.get("overall") or 0),
            -float(row.get("minutes") or 0),
        ),
    )
    # Profile quality is the main rank (75%). Age-discounted scores are the
    # rest so veterans cannot hide behind a high number. Raw U27 share is
    # shown, not added — that is what used to put PL2 on top of Ireland.
    watch = 0.75 * quality + 0.25 * age_weighted
    return {
        "watch_pct": int(round(max(0.0, min(100.0, watch)))),
        "quality_pct": int(round(max(0.0, min(100.0, quality)))),
        "youth_pct": int(round(max(0.0, min(100.0, u27_share * 100)))),
        "u27_count": u27_count,
        "player_count": player_count,
        "headlines": _slim_headlines(young_heads),
        "score_headlines": _slim_headlines(score_heads),
        "incomplete": len(sides) == 1,
    }


def _slim_headlines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": row["name"],
            "age": row.get("age"),
            "overall": row.get("overall"),
            "club": row.get("club") or "",
            "minutes": row.get("minutes") or 0,
        }
        for row in rows[:HEADLINE_COUNT]
    ]


def score_fixture_players(
    home_players: list[dict[str, Any]],
    away_players: list[dict[str, Any]],
    *,
    league: str = "",
) -> dict[str, Any] | None:
    return combine_side_scores(
        score_side(home_players, league=league),
        score_side(away_players, league=league),
    )


def _index_players_by_club(players: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    lists: dict[str, list[dict[str, Any]]] = {}
    for raw in players:
        club = str(raw.get("club") or "").strip()
        if not club:
            continue
        keys = _club_lookup_keys(club)
        if not keys:
            continue
        primary = keys[0]
        bucket = lists.get(primary)
        if bucket is None:
            bucket = []
            lists[primary] = bucket
        bucket.append(raw)
        for key in keys:
            buckets[key] = bucket
    return {key: _dedupe_players(rows) for key, rows in buckets.items()}


def players_for_club(
    club: str, index: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    for key in _club_lookup_keys(club):
        rows = index.get(key)
        if rows:
            return rows
    return []


def _side_name(side: Any) -> str:
    if isinstance(side, dict):
        return str(side.get("name") or "").strip()
    return str(side or "").strip()


def _side_image(side: Any) -> str | None:
    if isinstance(side, dict):
        url = side.get("image_url") or side.get("imageUrl")
        return str(url) if url else None
    return None


def _league_color(league: str) -> str:
    row = FIXTURE_LEAGUE_BY_UI.get(league) or {}
    return str(row.get("color") or "#3d8bfd")


def _score_label(fixture: dict[str, Any]) -> str:
    raw = fixture.get("score")
    if raw is None:
        return ""
    token = str(raw).strip()
    return token


def _watchable_fixtures(season: str) -> list[dict[str, Any]]:
    """This season's played tape, plus upcoming within LOOKAHEAD_DAYS.

    Irish Prem is a calendar-year league (Feb–Nov). A 30-day lookbehind
    hid most of that tape even when the UI said All dates / This season.
    """
    payload = build_fixture_planner_payload(season=season)
    today = datetime.now(UTC).date()
    end = (today + timedelta(days=LOOKAHEAD_DAYS)).isoformat()
    out: list[dict[str, Any]] = []
    for row in payload.get("fixtures") or []:
        if not isinstance(row, dict):
            continue
        if row.get("postponed") or str(row.get("status") or "").lower() == "postponed":
            continue
        date_key = str(row.get("date") or "")[:10]
        if row.get("manual"):
            out.append(row)
            continue
        if not date_key:
            continue
        if _fixture_is_played(row) or date_key <= end:
            out.append(row)
    out.sort(
        key=lambda row: (
            str(row.get("date") or ""),
            str(row.get("kickoff_utc") or ""),
            str(row.get("league") or ""),
        )
    )
    return out


def _assignment_summary(
    fixture_id: str, assignments: dict[str, Any]
) -> dict[str, Any] | None:
    row = assignments.get(fixture_id)
    if not isinstance(row, dict):
        return None
    staff = [str(name).strip() for name in (row.get("staff") or []) if str(name).strip()]
    watch_type = str(row.get("watch_type") or "").strip().upper()
    if not staff and not watch_type:
        return None
    return {
        "staff": staff,
        "watch_type": watch_type,
        "watched_players": list(row.get("watched_players") or []),
    }


def _load_player_index() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    raw = _load_standouts_raw_payload(period="season")
    meta = {
        "building": bool(raw.get("building")),
        "generated_at": raw.get("generated_at"),
        "season_label": raw.get("season_label") or raw.get("period_label") or "",
        "player_count": len(raw.get("players") or []),
        "leagues": list(raw.get("leagues") or STANDOUTS_LEAGUES),
    }
    if raw.get("building") and not raw.get("players"):
        return {}, meta
    return _index_players_by_club(list(raw.get("players") or [])), meta


def _rank_row(
    fixture: dict[str, Any],
    *,
    index: dict[str, list[dict[str, Any]]],
    assignments: dict[str, Any],
) -> dict[str, Any]:
    fixture_id = str(fixture.get("fixture_id") or "")
    home_name = _side_name(fixture.get("home"))
    away_name = _side_name(fixture.get("away"))
    home_players = _annotate_side_players(list(players_for_club(home_name, index)), home_name)
    away_players = _annotate_side_players(list(players_for_club(away_name, index)), away_name)
    league = str(fixture.get("league") or "").strip()
    ranked = score_fixture_players(home_players, away_players, league=league)
    assignment = _assignment_summary(fixture_id, assignments)
    return {
        "fixture_id": fixture_id,
        "season": str(fixture.get("season") or DEFAULT_SEASON),
        "date": str(fixture.get("date") or "")[:10],
        "kickoff_utc": fixture.get("kickoff_utc") or fixture.get("scheduled_date"),
        "league": league,
        "league_color": _league_color(league),
        "home": {"name": home_name, "image_url": _side_image(fixture.get("home"))},
        "away": {"name": away_name, "image_url": _side_image(fixture.get("away"))},
        "watch_pct": None if ranked is None else ranked["watch_pct"],
        "quality_pct": None if ranked is None else ranked["quality_pct"],
        "youth_pct": None if ranked is None else ranked["youth_pct"],
        "u27_count": 0 if ranked is None else ranked["u27_count"],
        "player_count": 0 if ranked is None else ranked["player_count"],
        "headlines": [] if ranked is None else ranked["headlines"],
        "score_headlines": [] if ranked is None else ranked["score_headlines"],
        "has_profiles": ranked is not None,
        "incomplete": bool(ranked and ranked.get("incomplete")),
        "played": _fixture_is_played(fixture),
        "score": _score_label(fixture) or None,
        "assignment": assignment,
    }


def build_games_to_watch_payload(*, season: str = DEFAULT_SEASON) -> dict[str, Any]:
    index, profiles_meta = _load_player_index()
    fixtures = _watchable_fixtures(season)
    assignments = get_fixture_assignments().get("assignments") or {}
    rows = [
        _rank_row(fixture, index=index, assignments=assignments) for fixture in fixtures
    ]
    apply_league_relative_watch(rows)
    rows.sort(
        key=lambda row: (
            0 if row.get("has_profiles") else 1,
            -(row.get("score_pct") if row.get("score_pct") is not None else -1),
            str(row.get("date") or ""),
        )
    )
    _attach_watched_marks(rows)
    leagues: list[str] = []
    for row in rows:
        league = str(row.get("league") or "").strip()
        if league and league not in leagues:
            leagues.append(league)
    for name in STANDOUTS_LEAGUES:
        if name not in leagues:
            leagues.append(name)
    return {
        "season": season,
        "building": bool(profiles_meta.get("building")),
        "generated_at": datetime.now(UTC).isoformat(),
        "profiles_generated_at": profiles_meta.get("generated_at"),
        "season_label": profiles_meta.get("season_label") or "",
        "scoring": {
            "method": "look_lenses",
            "academy_leagues": sorted(ACADEMY_LEAGUES),
            "academy_score_factor": ACADEMY_SCORE_FACTOR,
            "academy_list_factor": ACADEMY_LIST_FACTOR,
            "u27_max_age": U27_MAX_AGE,
            "likely_squad": LIKELY_SQUAD_SIZE,
            "mix_keep_default": MIX_KEEP_DEFAULT,
            "mix_keep_by_league": dict(MIX_KEEP_BY_LEAGUE),
            "mix_step": MIX_STEP,
            "note": SCORING_NOTE,
            "notes": dict(SCORING_NOTES),
        },
        "staff": list(FIXTURE_STAFF),
        "staff_teams": [
            {
                "id": team["id"],
                "label": team["label"],
                "members": list(team["members"]),
            }
            for team in FIXTURE_STAFF_TEAMS
        ],
        "watch_types": list(WATCH_TYPES),
        "recent_watched_days": RECENT_WATCHED_DAYS,
        "leagues": [
            {"id": name, "color": _league_color(name)} for name in leagues if name
        ],
        "games": rows,
        "game_count": len(rows),
        "must_watch": sum(
            1 for row in rows if (row.get("watch_pct") or 0) >= 70
        ),
        "played_count": sum(1 for row in rows if row.get("played")),
        "upcoming_count": sum(1 for row in rows if not row.get("played")),
    }


def _store_games_payload(season: str, payload: dict[str, Any]) -> dict[str, Any]:
    _games_payload_mem[season] = (time.time(), payload)
    try:
        write_json("games-to-watch", season, payload)
    except Exception:
        logger.exception("Could not write games-to-watch cache for %s", season)
    return payload


def _empty_building_payload(season: str) -> dict[str, Any]:
    return {
        "season": season,
        "building": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "profiles_generated_at": None,
        "season_label": "",
        "scoring": {"note": SCORING_NOTE, "notes": dict(SCORING_NOTES)},
        "staff": list(FIXTURE_STAFF),
        "staff_teams": [
            {
                "id": team["id"],
                "label": team["label"],
                "members": list(team["members"]),
            }
            for team in FIXTURE_STAFF_TEAMS
        ],
        "watch_types": list(WATCH_TYPES),
        "recent_watched_days": RECENT_WATCHED_DAYS,
        "leagues": [
            {"id": name, "color": _league_color(name)}
            for name in STANDOUTS_LEAGUES
            if name
        ],
        "games": [],
        "game_count": 0,
        "must_watch": 0,
        "played_count": 0,
        "upcoming_count": 0,
    }


def _refresh_games_payload(season: str) -> None:
    with _games_payload_lock:
        if season in _games_refreshing:
            return
        _games_refreshing.add(season)

    def _run() -> None:
        try:
            _store_games_payload(season, build_games_to_watch_payload(season=season))
        except Exception:
            logger.exception("Background games-to-watch refresh failed for %s", season)
        finally:
            _games_refreshing.discard(season)

    threading.Thread(target=_run, name=f"games-to-watch-{season}", daemon=True).start()


def cached_games_to_watch_payload(*, season: str = DEFAULT_SEASON) -> dict[str, Any]:
    """Serve a warm list immediately so Player Reports does not die on first open."""
    now = time.time()
    cached = _games_payload_mem.get(season)
    if cached and now - cached[0] < GAMES_CACHE_TTL_SECONDS:
        return _with_fresh_watched_marks(cached[1])
    disk = read_json("games-to-watch", season, ttl=GAMES_CACHE_STALE_SECONDS)
    if disk:
        _games_payload_mem[season] = (now, disk)
        if cached and now - cached[0] >= GAMES_CACHE_TTL_SECONDS:
            _refresh_games_payload(season)
        return _with_fresh_watched_marks(disk)
    _refresh_games_payload(season)
    return _with_fresh_watched_marks(_empty_building_payload(season))


def _with_fresh_watched_marks(payload: dict[str, Any]) -> dict[str, Any]:
    """Re-attach last_watched_at on every read so Mark watched is not stuck behind cache."""
    out = dict(payload)
    games = [dict(row) for row in list(payload.get("games") or [])]
    _attach_watched_marks(games)
    out["games"] = games
    out["recent_watched_days"] = RECENT_WATCHED_DAYS
    return out


def warm_games_to_watch_cache(*, season: str = DEFAULT_SEASON) -> None:
    _refresh_games_payload(season)


def _enrich_club_queries(club: str) -> list[str]:
    """Try Impect-style 'Football Club' names before FotMob 'FC' (which 404s)."""
    variants = _name_variants(club)
    expanded = [name for name in variants if "football club" in name.casefold()]
    rest = [name for name in variants if name not in expanded]
    return expanded + rest


def _sort_sheet_players(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(
        key=lambda row: (
            1 if _left_listed_club(row) else 0,
            0 if row.get("u27") else 1,
            -float(row.get("overall") or 0),
            str(row.get("name") or ""),
        )
    )
    return rows


def _profile_lookup(index: dict[str, list[dict[str, Any]]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for rows in index.values():
        for row in rows:
            try:
                player_id = int(row.get("player_id"))
            except (TypeError, ValueError):
                continue
            out[player_id] = row
    return out


def _squad_id(side: Any) -> int:
    if isinstance(side, dict):
        try:
            return int(side.get("id") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _human_position(code: str) -> str:
    text = str(code or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:].lower() if text else ""


def players_from_match_squad(
    squad: dict[str, Any],
    *,
    club: str,
    names: dict[int, str],
    profiles: dict[int, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Kick-off XI plus anyone who came on. Never the unused bench or another club."""
    from app.pre_match import (
        _clean_formation_label,
        _coords_from_starting_position,
        _parse_game_clock,
        _shirt_map_from_squad_block,
    )

    shirts = _shirt_map_from_squad_block(squad)
    profiles = profiles or {}
    formation = _clean_formation_label(squad.get("startingFormation"))
    players: list[dict[str, Any]] = []
    seen: set[int] = set()

    def _row(player_id: int, position: str, *, started: bool, minute: int | None, side: Any = None) -> dict[str, Any]:
        profile = dict(profiles.get(player_id) or {})
        name = str(names.get(player_id) or profile.get("name") or f"Player {player_id}").strip()
        x_pct, y_pct = _coords_from_starting_position(position, side)
        age = profile.get("age")
        merged = {
            **profile,
            "player_id": player_id,
            "name": name,
            "club": club,
            "position": position,
            "position_label": _human_position(position) or profile.get("position_label") or "",
            "formation_slot": position,
            "shirt_number": shirts.get(player_id) or profile.get("shirt_number"),
            "started": started,
            "subbed_on": not started,
            "match_minute": minute,
            "x_pct": x_pct,
            "y_pct": y_pct,
            "u27": age is not None and int(age) <= U27_MAX_AGE,
        }
        return merged

    for row in squad.get("startingPositions") or []:
        if not isinstance(row, dict):
            continue
        player_id = int(row.get("playerId") or 0)
        if not player_id or player_id in seen:
            continue
        seen.add(player_id)
        players.append(
            _row(
                player_id,
                str(row.get("position") or ""),
                started=True,
                minute=None,
                side=row.get("positionSide"),
            )
        )

    for row in squad.get("substitutions") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("substitutionType") or "").upper() != "SUB_ON":
            continue
        player_id = int(row.get("playerId") or 0)
        if not player_id or player_id in seen:
            continue
        seen.add(player_id)
        minute, _sort, _label = _parse_game_clock(row.get("gameTime"))
        players.append(
            _row(
                player_id,
                str(row.get("toPosition") or row.get("position") or ""),
                started=False,
                minute=minute or None,
                side=row.get("positionSide"),
            )
        )
    return players, formation


def _lineup_from_match(
    fixture: dict[str, Any],
    side_key: str,
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str | None, str]:
    if not _fixture_is_played(fixture):
        return [], None, "upcoming"
    match_id = fixture.get("match_id")
    iteration_id = fixture.get("iteration_id")
    side = fixture.get(side_key) or {}
    squad_id = _squad_id(side)
    club = _side_name(side)
    if not match_id or not squad_id:
        return [], None, "missing"
    try:
        from app.fixture_planner import _player_names_for_iteration
        from app.pre_match import _fetch_match_detail, _match_squad_block

        detail = _fetch_match_detail(int(match_id))
        squad = _match_squad_block(detail, squad_id)
        if not squad:
            return [], None, "missing"
        names = _player_names_for_iteration(int(iteration_id)) if iteration_id else {}
        players, formation = players_from_match_squad(
            squad,
            club=club,
            names=names,
            profiles=_profile_lookup(index),
        )
        if not players:
            return [], formation, "missing"
        transfer_status.annotate_all(players)
        return players, formation, "match"
    except Exception:
        logger.exception("Could not load match XI for %s %s", club, match_id)
        return [], None, "missing"


def _sheet_players(
    club: str,
    index: dict[str, list[dict[str, Any]]],
    *,
    enrich: bool,
) -> list[dict[str, Any]]:
    rows = list(players_for_club(club, index))
    if rows or not enrich or not club:
        return _sort_sheet_players(rows)
    for query in _enrich_club_queries(club):
        try:
            sheet = build_club_team_sheet(query)
        except HTTPException:
            continue
        except Exception:  # noqa: BLE001
            continue
        enriched = _dedupe_players(list(sheet.get("players") or []))
        if not enriched:
            continue
        for row in enriched:
            if not row.get("club"):
                row["club"] = str(sheet.get("club") or club)
        return _sort_sheet_players(enriched)
    return []


def build_fixture_sheet(*, season: str, fixture_id: str) -> dict[str, Any]:
    token = str(fixture_id or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="fixture_id is required")
    fixture = None
    for row in _watchable_fixtures(season):
        if str(row.get("fixture_id") or "") == token:
            fixture = row
            break
    if fixture is None:
        payload = build_fixture_planner_payload(season=season)
        for row in payload.get("fixtures") or []:
            if str(row.get("fixture_id") or "") == token:
                fixture = row
                break
    if fixture is None:
        raise HTTPException(status_code=404, detail="Fixture not found")

    index, _meta = _load_player_index()
    home_players, home_formation, home_lineup = _lineup_from_match(fixture, "home", index)
    away_players, away_formation, away_lineup = _lineup_from_match(fixture, "away", index)
    league = str(fixture.get("league") or "").strip()
    ranked = score_fixture_players(home_players, away_players, league=league)
    assignments = get_fixture_assignments().get("assignments") or {}
    list_rows = [
        _rank_row(row, index=index, assignments=assignments)
        for row in _watchable_fixtures(season)
    ]
    apply_league_relative_watch(list_rows)
    league_raws = [
        float(row["watch_raw"])
        for row in list_rows
        if row.get("watch_raw") is not None
        and str(row.get("league") or "") == league
    ]
    quality_raws = [
        float(row["quality_pct"])
        for row in list_rows
        if row.get("quality_pct") is not None
        and str(row.get("league") or "") == league
    ]
    youth_raws = [
        float(row["youth_pct"])
        for row in list_rows
        if row.get("youth_pct") is not None
        and str(row.get("league") or "") == league
    ]
    summary = _rank_row(fixture, index=index, assignments=assignments)
    listed = next(
        (
            row
            for row in list_rows
            if str(row.get("fixture_id") or "") == token
        ),
        None,
    )
    if listed:
        summary["score_mix_pct"] = listed.get("score_mix_pct")
        summary["young_mix_pct"] = listed.get("young_mix_pct")
        summary["both_mix_pct"] = listed.get("both_mix_pct")
        summary["watch_mix_pct"] = listed.get("watch_mix_pct")
    if ranked:
        score_pct = display_watch_pct(
            ranked["quality_pct"],
            league=league,
            league_raws=quality_raws,
        )
        young_pct = display_watch_pct(
            ranked["youth_pct"],
            league=league,
            league_raws=youth_raws,
        )
        summary.update(
            {
                "watch_pct": display_watch_pct(
                    ranked["watch_pct"],
                    league=league,
                    league_raws=league_raws,
                ),
                "score_pct": score_pct,
                "young_pct": young_pct,
                "both_pct": _both_look_pct(score_pct, young_pct),
                "watch_raw": ranked["watch_pct"],
                "quality_pct": ranked["quality_pct"],
                "youth_pct": ranked["youth_pct"],
                "u27_count": ranked["u27_count"],
                "player_count": ranked["player_count"],
                "headlines": ranked["headlines"],
                "score_headlines": ranked["score_headlines"],
                "has_profiles": True,
                "incomplete": ranked.get("incomplete"),
            }
        )
    return {
        **summary,
        "home": {
            **summary["home"],
            "players": home_players,
            "formation": home_formation,
            "lineup_status": home_lineup,
        },
        "away": {
            **summary["away"],
            "players": away_players,
            "formation": away_formation,
            "lineup_status": away_lineup,
        },
        "staff": list(FIXTURE_STAFF),
        "staff_teams": [
            {
                "id": team["id"],
                "label": team["label"],
                "members": list(team["members"]),
            }
            for team in FIXTURE_STAFF_TEAMS
        ],
        "watch_types": list(WATCH_TYPES),
        "scoring": {"note": SCORING_NOTE, "notes": dict(SCORING_NOTES)},
        "recent_watched_days": RECENT_WATCHED_DAYS,
        "last_watched_at": (
            (get_watched_marks().get("watched") or {})
            .get(token, {})
            .get("last_watched_at")
        ),
    }


def assign_game(body: AssignBody) -> dict[str, Any]:
    watch_type = str(body.watch_type or "VIDEO").strip().upper() or "VIDEO"
    saved = upsert_fixture_assignment(
        FixtureAssignmentUpdate(
            fixture_id=body.fixture_id,
            staff=body.staff,
            watch_type=watch_type,
            season=body.season or DEFAULT_SEASON,
            league=body.league,
            home=body.home,
            away=body.away,
            date=body.date,
            kickoff_utc=body.kickoff_utc,
            watched_players=body.watched_players,
        )
    )
    assignment = (saved.get("assignments") or {}).get(body.fixture_id) or {}
    return {
        "ok": True,
        "fixture_id": body.fixture_id,
        "assignment": assignment,
        "email": saved.get("email"),
    }


def register_games_to_watch_routes(app: FastAPI) -> None:
    page_path = STANDALONE_DIR / "games-to-watch.html"

    @app.get("/games-to-watch", response_class=HTMLResponse)
    def games_to_watch_page() -> HTMLResponse:
        if not page_path.is_file():
            raise RuntimeError(f"Missing page: {page_path}")
        return HTMLResponse(page_path.read_text(encoding="utf-8"))

    @app.get("/api/games-to-watch")
    def games_to_watch_list_route(
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return cached_games_to_watch_payload(season=season)

    @app.get("/api/games-to-watch/fixture")
    def games_to_watch_fixture_route(
        fixture_id: str = Query(...),
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return build_fixture_sheet(season=season, fixture_id=fixture_id)

    @app.post("/api/games-to-watch/assign")
    def games_to_watch_assign_route(body: AssignBody) -> dict[str, Any]:
        return assign_game(body)

    @app.get("/api/games-to-watch/watched")
    def games_to_watch_watched_route() -> dict[str, Any]:
        return get_watched_marks()

    @app.post("/api/games-to-watch/watched")
    def games_to_watch_mark_watched_route(body: MarkWatchedBody) -> dict[str, Any]:
        return mark_fixture_watched(body)

    @app.on_event("startup")
    def _warm_games_to_watch() -> None:
        warm_games_to_watch_cache()
