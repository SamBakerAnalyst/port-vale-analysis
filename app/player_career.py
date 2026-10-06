"""Player career — FotMob club history by season, linked to the Impect seasons we hold."""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from typing import Any

FOTMOB_SEARCH_URL = "https://www.fotmob.com/api/data/search/suggest"
FOTMOB_PLAYER_URL = "https://www.fotmob.com/api/data/playerData"
FOTMOB_LOGO_URL = "https://images.fotmob.com/image_resources/logo/teamlogo/{team_id}_small.png"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TTL = 12 * 60 * 60
_MISS_TTL = 60 * 60

_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()

_CUP_RE = re.compile(r"\b(cup|trophy|shield|play-?offs?|friendl|super ?cup|qualif)", re.I)
_YOUTH_RE = re.compile(r"\b(u ?\d{2}|under[- ]?\d{2}|youth|academy|reserves?|ii|b)$", re.I)
_CLUB_NOISE = {"fc", "afc", "cf", "sc", "the"}


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.casefold()).split())


def _club_parts(name: Any) -> tuple[str, bool]:
    """('manchester united', True) for 'FC Manchester United U21'."""
    text = _fold(name)
    youth = False
    while True:
        stripped = _YOUTH_RE.sub("", text).strip()
        if stripped == text:
            break
        youth, text = True, stripped
    words = [word for word in text.split() if word not in _CLUB_NOISE]
    return " ".join(words), youth


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def short_season(name: Any) -> str:
    """'2025/2026' → '25/26'. Calendar-year seasons ('2022') stay as they are."""
    text = str(name or "").strip()
    match = re.fullmatch(r"(\d{4})\s*[/-]\s*(\d{2,4})", text)
    if match:
        return f"{match.group(1)[-2:]}/{match.group(2)[-2:]}"
    return text


def _season_sort_key(season: str) -> int:
    match = re.match(r"(\d{2,4})", season or "")
    if not match:
        return 0
    year = int(match.group(1))
    return year + 2000 if year < 100 else year


def _get_json(url: str, params: dict[str, Any]) -> Any:
    from app.fixture_planner import _http

    response = _http.get(url, params=params, headers=_HEADERS, timeout=15)
    response.raise_for_status()
    return response.json()


def find_fotmob_player_id(name: str, clubs: list[str]) -> int | None:
    target = _fold(name)
    if not target:
        return None
    try:
        payload = _get_json(FOTMOB_SEARCH_URL, {"term": name, "lang": "en"})
    except Exception:
        return None
    club_bases = {_club_parts(club)[0] for club in clubs if club}
    surname = target.split()[-1]
    first = target.split()[0]
    best: tuple[int, int] | None = None
    for group in payload if isinstance(payload, list) else []:
        for row in (group or {}).get("suggestions") or []:
            if not isinstance(row, dict) or row.get("type") != "player" or row.get("isCoach"):
                continue
            pid = _int(row.get("id"))
            key = _fold(row.get("name"))
            if not pid or not key:
                continue
            if key == target:
                score = 10
            elif key.split()[-1] == surname and key.split()[0][:1] == first[:1]:
                score = 6
            else:
                continue
            if _club_parts(row.get("teamName"))[0] in club_bases:
                score += 5
            if best is None or score > best[0]:
                best = (score, pid)
    if best is None or best[0] < 10:
        return None
    return best[1]


def _main_tournament(entry: dict[str, Any]) -> dict[str, Any]:
    stats = [row for row in entry.get("tournamentStats") or [] if isinstance(row, dict) and not row.get("isFriendly")]
    leagues = [row for row in stats if not _CUP_RE.search(str(row.get("leagueName") or ""))]
    pool = leagues or stats
    if not pool:
        return {}
    return max(pool, key=lambda row: _int(row.get("appearances")) or 0)


def parse_fotmob_career(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = ((payload.get("careerHistory") or {}).get("careerItems") or {}) if isinstance(payload, dict) else {}
    rows: list[dict[str, Any]] = []
    for group in ("senior", "youth"):
        for entry in (items.get(group) or {}).get("seasonEntries") or []:
            if not isinstance(entry, dict) or not entry.get("team"):
                continue
            main = _main_tournament(entry)
            if not main and not _int(entry.get("appearances")):
                continue
            transfer = str(((entry.get("transferType") or {}).get("localizationKey")) or "")
            team_id = _int(entry.get("teamId"))
            rows.append(
                {
                    "season": short_season(entry.get("seasonName")),
                    "club": str(entry.get("team")).strip(),
                    "league": str(main.get("leagueName") or "").strip(),
                    "apps": _int(entry.get("appearances")),
                    "goals": _int(entry.get("goals")),
                    "assists": _int(entry.get("assists")),
                    "rating": _float((entry.get("rating") or {}).get("rating")),
                    "on_loan": transfer == "on_loan",
                    "youth": group == "youth",
                    "logo": FOTMOB_LOGO_URL.format(team_id=team_id) if team_id else "",
                }
            )
    rows.sort(key=lambda row: (_season_sort_key(row["season"]), not row["youth"], row["apps"] or 0), reverse=True)
    return rows


def _impect_link(season: dict[str, Any]) -> dict[str, Any] | None:
    iteration_id = _int(season.get("impect_iteration_id"))
    squad_id = _int(season.get("impect_squad_id"))
    if not iteration_id or not squad_id:
        return None
    return {
        "iteration_id": iteration_id,
        "squad_id": squad_id,
        "competition": season.get("competition_name") or "",
        "minutes": season.get("minutes"),
    }


def _match_score(row: dict[str, Any], season: dict[str, Any]) -> int:
    if row["season"] != str(season.get("season") or "").strip():
        return 0
    base, youth = _club_parts(row["club"])
    other_base, other_youth = _club_parts(season.get("club"))
    if youth != other_youth or not base or not other_base:
        return 0
    score = 0
    if base == other_base:
        score += 3
    elif set(base.split()) & set(other_base.split()):
        score += 1
    if row["league"] and _fold(row["league"]) == _fold(season.get("competition_name")):
        score += 1
    return score


def link_impect_seasons(rows: list[dict[str, Any]], impect_seasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach each Impect season to its FotMob row; keep Impect seasons FotMob does not list."""
    linked = [dict(row, source="fotmob", impect=None) for row in rows]
    candidates = [season for season in impect_seasons if _impect_link(season)]
    used: set[int] = set()
    for row in linked:
        best: tuple[int, int] | None = None
        for idx, season in enumerate(candidates):
            if idx in used:
                continue
            score = _match_score(row, season)
            if score >= 2 and (best is None or score > best[0]):
                best = (score, idx)
        if best is not None:
            used.add(best[1])
            row["impect"] = _impect_link(candidates[best[1]])
    for idx, season in enumerate(candidates):
        if idx in used:
            continue
        linked.append(
            {
                "season": str(season.get("season") or ""),
                "club": str(season.get("club") or ""),
                "league": str(season.get("competition_name") or ""),
                "apps": None,
                "goals": None,
                "assists": None,
                "rating": None,
                "on_loan": False,
                "youth": _club_parts(season.get("club"))[1],
                "logo": "",
                "source": "impect",
                "impect": _impect_link(season),
            }
        )
    linked.sort(key=lambda row: (_season_sort_key(row["season"]), not row["youth"], row["apps"] or 0), reverse=True)
    return linked


def build_player_career(
    player_id: int,
    name: str,
    impect_seasons: list[dict[str, Any]],
    *,
    current_club: str = "",
    refresh: bool = False,
) -> dict[str, Any]:
    now = time.time()
    with _lock:
        hit = _cache.get(int(player_id))
    if hit and not refresh:
        ttl = _TTL if hit[1].get("fotmob_id") else _MISS_TTL
        if now - hit[0] < ttl:
            fotmob_rows = hit[1].get("fotmob_rows") or []
            return {**hit[1], "seasons": link_impect_seasons(fotmob_rows, impect_seasons)}

    clubs = [str(season.get("club") or "") for season in impect_seasons] + [current_club]
    fotmob_id = find_fotmob_player_id(name, clubs)
    fotmob_rows: list[dict[str, Any]] = []
    profile_url = ""
    if fotmob_id:
        try:
            payload = _get_json(FOTMOB_PLAYER_URL, {"id": fotmob_id})
            fotmob_rows = parse_fotmob_career(payload if isinstance(payload, dict) else {})
            page = str(((payload or {}).get("meta") or {}).get("pageurl") or "")
            profile_url = f"https://www.fotmob.com{page}" if page.startswith("/") else ""
        except Exception:
            fotmob_rows = []
    result = {
        "player_id": int(player_id),
        "fotmob_id": fotmob_id if fotmob_rows else None,
        "fotmob_url": profile_url,
        "fotmob_rows": fotmob_rows,
    }
    with _lock:
        _cache[int(player_id)] = (now, result)
    return {**result, "seasons": link_impect_seasons(fotmob_rows, impect_seasons)}
