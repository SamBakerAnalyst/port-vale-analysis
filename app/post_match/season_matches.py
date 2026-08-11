from __future__ import annotations

from typing import Any

from app.post_match.config import PORT_VALE_SQUAD_ID
from app.post_match.impect_client import extract_rows, impect_get, v5_path
from app.post_match.report import _squad_details
from app.post_match.squad_badges import enrich_squad


def _match_day_index(match_row: dict[str, Any]) -> int | None:
    match_day = match_row.get("matchDay")
    if isinstance(match_day, dict):
        index = match_day.get("index")
        return int(index) if index is not None else None
    if match_day is not None:
        return int(match_day)
    return None


def _focus_match_outcome(
    focus_squad_id: int,
    home_id: int,
    away_id: int,
    goals: dict[str, Any],
) -> str | None:
    home_ft = (goals.get("home") or {}).get("fullTime")
    away_ft = (goals.get("away") or {}).get("fullTime")
    if home_ft is None or away_ft is None:
        return None
    if focus_squad_id == home_id:
        focus_goals, opp_goals = int(home_ft), int(away_ft)
    elif focus_squad_id == away_id:
        focus_goals, opp_goals = int(away_ft), int(home_ft)
    else:
        return None
    if focus_goals > opp_goals:
        return "win"
    if focus_goals < opp_goals:
        return "loss"
    return "draw"


def _score_label(
    focus_squad_id: int,
    home_id: int,
    away_id: int,
    goals: dict[str, Any],
) -> str | None:
    home_ft = (goals.get("home") or {}).get("fullTime")
    away_ft = (goals.get("away") or {}).get("fullTime")
    if home_ft is None or away_ft is None:
        return None
    if focus_squad_id == home_id:
        return f"H {int(home_ft)}:{int(away_ft)}"
    if focus_squad_id == away_id:
        return f"A {int(away_ft)}:{int(home_ft)}"
    return f"{int(home_ft)}:{int(away_ft)}"


def build_season_matches(
    iteration_id: int,
    focus_squad_id: int,
    *,
    include_upcoming: bool = True,
    competition_label: str | None = None,
    competition_short: str | None = None,
    season_label: str | None = None,
) -> list[dict[str, Any]]:
    raw = impect_get(v5_path(f"/iterations/{iteration_id}/matches"))
    rows = extract_rows(raw["data"])
    squads = _squad_details(iteration_id)

    matches: list[dict[str, Any]] = []
    for row in rows:
        available = row.get("available") is not False
        if not available and not include_upcoming:
            continue
        match_id = int(row.get("id") or 0)
        if not match_id:
            continue
        home_id = int(row.get("homeSquadId") or 0)
        away_id = int(row.get("awaySquadId") or 0)
        if focus_squad_id not in (home_id, away_id):
            continue

        is_home = focus_squad_id == home_id
        opponent_id = away_id if is_home else home_id
        opponent = squads.get(opponent_id, {})
        home = squads.get(home_id, {})
        away = squads.get(away_id, {})
        goals = row.get("goals") or {}

        matches.append(
            {
                "matchId": match_id,
                "iterationId": int(iteration_id),
                "scheduledDate": row.get("scheduledDate"),
                "matchDay": _match_day_index(row),
                "result": row.get("result"),
                "available": available,
                "competitionLabel": competition_label,
                "competitionShort": competition_short,
                "seasonLabel": season_label,
                "isHome": is_home,
                "home": enrich_squad(
                    {
                        "squadId": home_id,
                        "name": home.get("name") or f"Squad {home_id}",
                        "imageUrl": home.get("imageUrl"),
                        "score": (goals.get("home") or {}).get("fullTime"),
                    },
                    home_id,
                    iteration_id,
                ),
                "away": enrich_squad(
                    {
                        "squadId": away_id,
                        "name": away.get("name") or f"Squad {away_id}",
                        "imageUrl": away.get("imageUrl"),
                        "score": (goals.get("away") or {}).get("fullTime"),
                    },
                    away_id,
                    iteration_id,
                ),
                "opponent": enrich_squad(
                    {
                        "squadId": opponent_id,
                        "name": opponent.get("name") or f"Squad {opponent_id}",
                        "imageUrl": opponent.get("imageUrl"),
                    },
                    opponent_id,
                    iteration_id,
                ),
                "outcome": _focus_match_outcome(focus_squad_id, home_id, away_id, goals),
                "scoreLabel": _score_label(focus_squad_id, home_id, away_id, goals),
            }
        )

    matches.sort(key=lambda item: item.get("scheduledDate") or "")
    return matches


def build_combined_season_matches(
    focus_squad_id: int = PORT_VALE_SQUAD_ID,
    *,
    competitions: list[dict[str, Any]] | None = None,
    include_upcoming: bool = True,
) -> dict[str, Any]:
    if competitions is not None:
        comps = competitions
    else:
        try:
            from app.post_match.config import POST_MATCH_COMPETITIONS as comps
        except ImportError:
            comps = []
    matches: list[dict[str, Any]] = []
    errors: list[str] = []
    loaded: list[dict[str, Any]] = []

    for comp in comps:
        iteration_id = int(comp.get("iterationId") or 0)
        if not iteration_id:
            continue
        label = str(comp.get("label") or f"Iteration {iteration_id}")
        short = str(comp.get("shortLabel") or label)
        season = str(comp.get("season") or "")
        try:
            batch = build_season_matches(
                iteration_id,
                focus_squad_id,
                include_upcoming=include_upcoming,
                competition_label=label,
                competition_short=short,
                season_label=season or None,
            )
            matches.extend(batch)
            loaded.append(
                {
                    "iterationId": iteration_id,
                    "label": label,
                    "shortLabel": short,
                    "season": season,
                    "matchCount": len(batch),
                }
            )
        except Exception as exc:  # noqa: BLE001 — keep other comps if one fails
            errors.append(f"{label}: {exc}")

    matches.sort(key=lambda item: item.get("scheduledDate") or "")

    # Prefer latest available report; otherwise next upcoming kick-off.
    default_match_id = None
    for match in reversed(matches):
        if match.get("available"):
            default_match_id = match["matchId"]
            break
    if default_match_id is None and matches:
        default_match_id = matches[0]["matchId"]

    return {
        "focusSquadId": focus_squad_id,
        "competitions": loaded,
        "matches": matches,
        "defaultMatchId": default_match_id,
        "errors": errors,
    }
