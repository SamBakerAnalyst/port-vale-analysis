"""Player search for manual reports — any player the hub knows, not just one team sheet.

Sources, in priority order (first one wins per player id):

1. Impect standouts index — every player in our six scouted leagues, same ids as ``/player/{id}``.
2. Player Pipelines targets.
3. Players already carried on a filed report (name / club saved on the row).
4. Hub-only player stubs created from Match Scouting for anyone outside the catalog.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from app.player_report_schema import REPORT_POSITIONS
from app.player_reports import all_report_rows, is_stub_player, player_stubs

_POSITION_SHORT = {code: short for code, short, _label in REPORT_POSITIONS}
_POSITION_LABEL = {code: label for code, _short, label in REPORT_POSITIONS}
_POSITION_ALIASES: dict[str, tuple[str, ...]] = {
    "LEFT_WINGBACK_DEFENDER": ("LEFT_WINGBACK_DEFENDER", "LEFT_BACK"),
    "RIGHT_WINGBACK_DEFENDER": ("RIGHT_WINGBACK_DEFENDER", "RIGHT_BACK"),
    "LEFT_WINGER": ("LEFT_WINGER", "LEFT_MIDFIELD"),
    "RIGHT_WINGER": ("RIGHT_WINGER", "RIGHT_MIDFIELD"),
    "CENTER_FORWARD": ("CENTER_FORWARD", "SECOND_STRIKER", "STRIKER"),
}


def fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).casefold().split())


def position_matches(player_position: str, wanted: str) -> bool:
    if not wanted:
        return True
    code = str(player_position or "").strip().upper()
    return code in _POSITION_ALIASES.get(wanted, (wanted,))


def _standouts_rows() -> list[dict[str, Any]]:
    try:
        from app.player_dossier import _standouts_player_rows

        return list(_standouts_player_rows())
    except Exception:
        return []


def _pipeline_rows() -> dict[int, dict[str, Any]]:
    try:
        from app.player_pipelines import pipeline_index_by_player_id

        return dict(pipeline_index_by_player_id())
    except Exception:
        return {}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _entry(pid: int, *, name: Any, club: Any, league: Any, age: Any, position: Any, position_label: Any, source: str) -> dict[str, Any]:
    code = str(position or "").strip().upper()
    try:
        age_value = int(age) if age not in (None, "") else None
    except (TypeError, ValueError):
        age_value = None
    return {
        "player_id": pid,
        "name": str(name or "").strip(),
        "club": str(club or "").strip(),
        "league": str(league or "").strip(),
        "age": age_value,
        "position": code,
        "position_short": _POSITION_SHORT.get(code, ""),
        "position_label": str(position_label or "").strip() or _POSITION_LABEL.get(code, ""),
        "source": source,
        "is_stub": is_stub_player(pid),
    }


def build_catalog() -> dict[int, dict[str, Any]]:
    catalog: dict[int, dict[str, Any]] = {}
    best_minutes: dict[int, float] = {}
    for row in _standouts_rows():
        pid = _int(row.get("playerId") or row.get("player_id"))
        if not pid or not row.get("name"):
            continue
        minutes = float(row.get("minutes") or 0)
        if pid in catalog and minutes <= best_minutes.get(pid, 0):
            continue
        best_minutes[pid] = minutes
        catalog[pid] = _entry(
            pid,
            name=row.get("name"),
            club=row.get("club"),
            league=row.get("league"),
            age=row.get("age"),
            position=row.get("position"),
            position_label=row.get("positionLabel"),
            source="catalog",
        )
    for pid, row in _pipeline_rows().items():
        pid = _int(pid)
        if not pid or pid in catalog or not row.get("name"):
            continue
        catalog[pid] = _entry(
            pid,
            name=row.get("name"),
            club=row.get("club"),
            league=row.get("league"),
            age=row.get("age"),
            position=row.get("position"),
            position_label=row.get("position_label"),
            source="pipeline",
        )
    raw = all_report_rows()
    report_counts: dict[int, int] = {}
    for section in ("general_reports", "detailed_reports"):
        for key, row in raw[section].items():
            pid = _int(str(key).partition(":")[0])
            if not pid or not isinstance(row, dict):
                continue
            report_counts[pid] = report_counts.get(pid, 0) + 1
            if pid in catalog or not row.get("name") or is_stub_player(pid):
                continue
            catalog[pid] = _entry(
                pid,
                name=row.get("name"),
                club=row.get("club"),
                league=row.get("league"),
                age=row.get("age"),
                position=row.get("position"),
                position_label=row.get("position_label"),
                source="reported",
            )
    for pid, row in player_stubs().items():
        catalog[pid] = _entry(
            pid,
            name=row.get("name"),
            club=row.get("club"),
            league=row.get("league"),
            age=row.get("age"),
            position=row.get("position"),
            position_label="",
            source="stub",
        )
    for pid, entry in catalog.items():
        entry["report_count"] = report_counts.get(pid, 0)
    return catalog


def lookup_player(player_id: int) -> dict[str, Any]:
    return build_catalog().get(int(player_id)) or {}


def _score(entry: dict[str, Any], tokens: list[str], query: str) -> int:
    name = fold(entry["name"])
    if not all(token in name for token in tokens):
        return -1
    score = 0
    if name == query:
        score += 100
    elif name.startswith(query):
        score += 60
    parts = name.split()
    score += sum(10 for token in tokens if any(part.startswith(token) for part in parts))
    if entry.get("report_count"):
        score += 5
    return score


def search_players(query: str = "", *, club: str = "", position: str = "", limit: int = 30) -> dict[str, Any]:
    q = fold(query)
    club_key = fold(club)
    wanted = str(position or "").strip().upper()
    if len(q) < 2 and not club_key:
        return {"players": [], "total": 0, "message": "Type at least two letters of the player's name."}
    tokens = q.split()
    scored: list[tuple[int, dict[str, Any]]] = []
    for entry in build_catalog().values():
        if club_key and club_key not in fold(entry["club"]):
            continue
        if not position_matches(entry["position"], wanted):
            continue
        score = _score(entry, tokens, q) if tokens else 0
        if score < 0:
            continue
        scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], item[1]["name"].casefold()))
    rows = [entry for _score_value, entry in scored[: max(1, min(int(limit or 30), 100))]]
    message = ""
    if not rows:
        message = (
            "No player in the hub matches that search. The catalog covers our six scouted leagues, "
            "pipeline targets and anyone already reported — add him as a new player below."
        )
    return {"players": rows, "total": len(scored), "message": message}
