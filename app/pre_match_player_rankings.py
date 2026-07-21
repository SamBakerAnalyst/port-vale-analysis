"""Pre-match player ranking boards (in / out of possession)."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from app.opponent_photos import opponent_photo_api_url
from app.pre_match_goals import (
    _classify_goal_type,
    _classify_phase,
    _fetch_events,
    _fetch_set_piece_categories,
    _find_assist,
    _shot_goals,
)

RANKING_MATCH_LIMIT = 46
RANKING_TOP_N = 5
MIN_MINUTES_FOR_PER90 = 450.0

# Impect player-kpi ids.
KPI_GOALS = 28
KPI_ASSISTS = 77
KPI_PXT_ATTACK = 1633
KPI_PXT_PASS = 1404
KPI_PXT_DRIBBLE = 1405
KPI_PXT_SETPIECE = 1406
KPI_PXT_SHOT = 1408
KPI_PXT_BALL_WIN = 1409  # regain / ball win threat
KPI_PXT_REC = 1412
KPI_BYPASSED_OPPONENTS = 1399  # ball progression volume
KPI_BYPASSED_DEFENDERS = 1400
KPI_PRESSES = 1536
KPI_PRESSES_BUILD_UP = 1537
KPI_PRESSES_BETWEEN_THE_LINES = 1538
KPI_PRESSES_COUNTER = 1539
KPI_BALL_WIN_VS_DEFENDERS = 25
KPI_OFFENSIVE_INTERVENTIONS = 24  # BALL_WIN_REMOVED_OPPONENTS (Impect OI)
KPI_OI_BY_DUEL = 865
KPI_OI_BY_LOOSE = 866
KPI_OI_BY_INTERCEPTION = 867
KPI_OI_BY_HEADER = 868
KPI_OI_BY_BLOCK = 869
KPI_WON_GROUND = 94
KPI_LOST_GROUND = 95
KPI_WON_AERIAL = 96
KPI_LOST_AERIAL = 97

SUM_KPI_IDS = frozenset(
    {
        KPI_GOALS,
        KPI_ASSISTS,
        KPI_PXT_ATTACK,
        KPI_PXT_PASS,
        KPI_PXT_DRIBBLE,
        KPI_PXT_SETPIECE,
        KPI_PXT_SHOT,
        KPI_PXT_BALL_WIN,
        KPI_PXT_REC,
        KPI_BYPASSED_OPPONENTS,
        KPI_BYPASSED_DEFENDERS,
        KPI_PRESSES,
        KPI_PRESSES_BUILD_UP,
        KPI_PRESSES_BETWEEN_THE_LINES,
        KPI_PRESSES_COUNTER,
        KPI_BALL_WIN_VS_DEFENDERS,
        KPI_OFFENSIVE_INTERVENTIONS,
        KPI_OI_BY_DUEL,
        KPI_OI_BY_LOOSE,
        KPI_OI_BY_INTERCEPTION,
        KPI_OI_BY_HEADER,
        KPI_OI_BY_BLOCK,
        KPI_WON_GROUND,
        KPI_LOST_GROUND,
        KPI_WON_AERIAL,
        KPI_LOST_AERIAL,
    }
)


def _impect():
    from app import main as impect_main

    return impect_main


def _blank_player(player_id: int) -> dict[str, Any]:
    return {
        "id": player_id,
        "minutes": 0.0,
        "kpis": defaultdict(float),
        "position_minutes": defaultdict(float),
        "goals_possession": 0,
        "goals_transition": 0,
        "goals_set_play": 0,
        "goals_total": 0,
        "assists_events": 0,
        "assists_possession": 0,
        "assists_transition": 0,
        "assists_set_play": 0,
        "threat_left": 0,
        "threat_centre": 0,
        "threat_right": 0,
    }


def _per90(value: float, minutes: float) -> float:
    if minutes <= 0:
        return 0.0
    return float(value) * 90.0 / float(minutes)


def _is_goalkeeper(row: dict[str, Any], position_hints: dict[int, str] | None = None) -> bool:
    pos_minutes = row.get("position_minutes") or {}
    if pos_minutes:
        primary = max(pos_minutes.items(), key=lambda item: item[1])[0]
        if "GOAL" in str(primary).upper():
            return True
    hint = (position_hints or {}).get(int(row.get("id") or 0), "")
    return "GOAL" in str(hint).upper()


def _accumulate_player_kpis(
    match_id: int,
    squad_id: int,
    totals: dict[int, dict[str, Any]],
) -> None:
    from app.pre_match import _fetch_match_detail, _match_play_minutes, _match_squad_block, _unwrap_match_player_payload

    impect = _impect()
    detail = _fetch_match_detail(match_id)
    squad_block = _match_squad_block(detail, squad_id) or {}
    for row in squad_block.get("players") or []:
        if not isinstance(row, dict):
            continue
        player_id = int(row.get("id") or 0)
        if not player_id:
            continue
        bucket = totals.setdefault(player_id, _blank_player(player_id))
        shirt = row.get("shirtNumber")
        if shirt is not None:
            try:
                bucket["shirt_number"] = int(shirt)
            except (TypeError, ValueError):
                pass

    payload = _unwrap_match_player_payload(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/matches/{match_id}/player-kpis"
        )["data"]
    )
    for side in ("squadHome", "squadAway"):
        squad = payload.get(side) or {}
        if int(squad.get("id") or -1) != squad_id:
            continue
        per_match_best: dict[int, dict[str, Any]] = {}
        for row in squad.get("players") or []:
            player_id = row.get("id")
            if player_id is None:
                continue
            player_id = int(player_id)
            minutes = _match_play_minutes(row)
            position = str(row.get("position") or "")
            bucket = totals.setdefault(player_id, _blank_player(player_id))
            if position and minutes > 0:
                bucket["position_minutes"][position] += float(minutes)
            existing = per_match_best.get(player_id)
            if existing is None or minutes > existing["minutes"]:
                per_match_best[player_id] = {
                    "minutes": minutes,
                    "kpis": row.get("kpis") or [],
                }
        for player_id, match_row in per_match_best.items():
            bucket = totals.setdefault(player_id, _blank_player(player_id))
            bucket["minutes"] += float(match_row["minutes"] or 0.0)
            for kpi in match_row["kpis"]:
                try:
                    kpi_id = int(kpi.get("kpiId") or -1)
                except (TypeError, ValueError):
                    continue
                if kpi_id not in SUM_KPI_IDS:
                    continue
                bucket["kpis"][kpi_id] += float(kpi.get("value") or 0.0)


def _threat_channel(coords: tuple[float, float] | None) -> str | None:
    """Map pitch width (y) into left / centre / right attacking channels."""
    if not coords:
        return None
    _x, y = coords
    # Impect pitch width is ~0–68; keep edges as channels, middle as centre.
    if y < 22.5:
        return "left"
    if y > 45.5:
        return "right"
    return "centre"


def _add_threat_location(bucket: dict[str, Any], coords: tuple[float, float] | None) -> None:
    channel = _threat_channel(coords)
    if not channel:
        return
    bucket[f"threat_{channel}"] = int(bucket.get(f"threat_{channel}") or 0) + 1


def _accumulate_goal_phases(
    match_id: int,
    squad_id: int,
    totals: dict[int, dict[str, Any]],
) -> None:
    from app.pre_match_goals import _coords

    events = _fetch_events(match_id)
    set_cats = _fetch_set_piece_categories(match_id)
    for goal in _shot_goals(events):
        try:
            scorer_squad = int(goal.get("squadId") or 0)
            player = goal.get("player") if isinstance(goal.get("player"), dict) else {}
            player_id = int(player.get("id") or goal.get("playerId") or 0)
        except (TypeError, ValueError):
            continue
        if scorer_squad != squad_id or not player_id:
            continue
        assist = _find_assist(events, goal)
        label = _classify_goal_type(goal, assist, set_cats)
        phase = _classify_phase(goal, label)
        bucket = totals.setdefault(player_id, _blank_player(player_id))
        bucket["goals_total"] += 1
        if phase == "possession":
            bucket["goals_possession"] += 1
        elif phase == "transition":
            bucket["goals_transition"] += 1
        else:
            bucket["goals_set_play"] += 1

        # Shot location contributes to where this player generates threat.
        _add_threat_location(bucket, _coords(goal.get("start") or goal.get("end")))

        if assist:
            try:
                assister = assist.get("player") if isinstance(assist.get("player"), dict) else {}
                assist_id = int(assister.get("id") or assist.get("playerId") or 0)
            except (TypeError, ValueError):
                assist_id = 0
            if assist_id and int(assist.get("squadId") or 0) == squad_id:
                ab = totals.setdefault(assist_id, _blank_player(assist_id))
                ab["assists_events"] += 1
                if phase == "possession":
                    ab["assists_possession"] += 1
                elif phase == "transition":
                    ab["assists_transition"] += 1
                else:
                    ab["assists_set_play"] += 1
                _add_threat_location(ab, _coords(assist.get("start")))


def _process_match_rankings(match_id: int, squad_id: int) -> dict[int, dict[str, Any]]:
    totals: dict[int, dict[str, Any]] = {}
    _accumulate_player_kpis(match_id, squad_id, totals)
    _accumulate_goal_phases(match_id, squad_id, totals)
    return totals


def _merge_player_totals(
    dst: dict[int, dict[str, Any]],
    src: dict[int, dict[str, Any]],
) -> None:
    for player_id, row in src.items():
        bucket = dst.setdefault(player_id, _blank_player(player_id))
        bucket["minutes"] += float(row.get("minutes") or 0.0)
        if row.get("shirt_number") is not None:
            bucket["shirt_number"] = row["shirt_number"]
        for key in (
            "goals_possession",
            "goals_transition",
            "goals_set_play",
            "goals_total",
            "assists_events",
            "assists_possession",
            "assists_transition",
            "assists_set_play",
            "threat_left",
            "threat_centre",
            "threat_right",
        ):
            bucket[key] += int(row.get(key) or 0)
        for kpi_id, value in (row.get("kpis") or {}).items():
            bucket["kpis"][int(kpi_id)] += float(value or 0.0)
        for position, minutes in (row.get("position_minutes") or {}).items():
            bucket["position_minutes"][str(position)] += float(minutes or 0.0)


def _fmt_rate(value: float, digits: int = 1) -> str:
    rounded = round(float(value), digits)
    if digits == 0:
        return str(int(rounded))
    text = f"{rounded:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def _fmt_pct(value: float) -> str:
    return f"{round(float(value)):.0f}%"


def _phase_parts(
    *,
    possession: int,
    transition: int,
    set_play: int,
    total: int,
) -> list[dict[str, Any]]:
    """Build Poss/Trn/Set chips that always reconcile with the displayed total."""
    poss = max(0, int(possession or 0))
    trans = max(0, int(transition or 0))
    set_play_n = max(0, int(set_play or 0))
    total_n = max(0, int(total or 0))
    phase_sum = poss + trans + set_play_n
    other = max(0, total_n - phase_sum)
    if phase_sum == 0 and other:
        return [{"key": "other", "label": "Other", "value": other}]
    parts = [
        {"key": "possession", "label": "Poss", "value": poss},
        {"key": "transition", "label": "Trn", "value": trans},
        {"key": "set_play", "label": "Set", "value": set_play_n},
    ]
    if other:
        parts.append({"key": "other", "label": "Other", "value": other})
    return parts


def _share_parts(
    parts: list[tuple[str, str, float]],
    *,
    total: float,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Top contributors as % of decomposed parts (always sums to ~100 with Other)."""
    ranked = sorted(
        ((key, label, max(0.0, float(value or 0.0))) for key, label, value in parts),
        key=lambda item: (-item[2], item[0]),
    )
    part_sum = sum(value for _, _, value in ranked)
    share_base = part_sum if part_sum > 0.0001 else max(0.0, float(total or 0.0))
    if share_base <= 0:
        return []
    chosen = ranked[:top_n]
    shown = sum(value for _, _, value in chosen)
    other = max(0.0, share_base - shown)
    out: list[dict[str, Any]] = []
    for key, label, value in chosen:
        pct = int(round(100.0 * value / share_base))
        out.append({"key": key, "label": label, "value": pct, "value_label": f"{pct}%"})
    if other > 0.0001:
        pct = int(round(100.0 * other / share_base))
        out.append({"key": "other", "label": "Other", "value": pct, "value_label": f"{pct}%"})
    pct_sum = sum(int(part["value"]) for part in out)
    if out and pct_sum != 100:
        out[-1]["value"] = int(out[-1]["value"]) + (100 - pct_sum)
        out[-1]["value_label"] = f"{out[-1]['value']}%"
    return [part for part in out if int(part["value"]) > 0 or len(out) == 1]


def _rank_rows(
    players: list[dict[str, Any]],
    *,
    value_key: str,
    top_n: int = RANKING_TOP_N,
    min_value: float = 0.0,
    format_value=None,
    breakdown_builder=None,
) -> list[dict[str, Any]]:
    ranked = sorted(
        players,
        key=lambda row: (-float(row.get(value_key) or 0.0), str(row.get("name") or "")),
    )
    out: list[dict[str, Any]] = []
    for row in ranked:
        value = float(row.get(value_key) or 0.0)
        if value <= min_value:
            continue
        item = {
            "id": row["id"],
            "name": row["name"],
            "shirt_number": row.get("shirt_number"),
            "photo_url": row.get("photo_url"),
            "value": round(value, 4),
            "value_label": (format_value or (lambda v: _fmt_rate(v, 1)))(value),
            "minutes": int(round(float(row.get("minutes") or 0.0))),
        }
        if breakdown_builder:
            item["breakdown"] = breakdown_builder(row)
        out.append(item)
        if len(out) >= top_n:
            break
    return out


def _board(
    key: str,
    label: str,
    subtitle: str,
    players: list[dict[str, Any]],
    *,
    value_key: str,
    format_value=None,
    min_value: float = 0.0,
    breakdown_builder=None,
) -> dict[str, Any]:
    rows = _rank_rows(
        players,
        value_key=value_key,
        format_value=format_value,
        min_value=min_value,
        breakdown_builder=breakdown_builder,
    )
    return {
        "key": key,
        "label": label,
        "subtitle": subtitle,
        "players": rows,
    }


def build_player_rankings(
    iteration_id: int,
    squad_id: int,
    *,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
    match_limit: int = RANKING_MATCH_LIMIT,
    player_names: dict[int, str] | None = None,
    player_positions: dict[int, str] | None = None,
    club_name: str | None = None,
    season: str | None = None,
) -> dict[str, Any]:
    from app.pre_match import _recent_completed_matches

    names = player_names or {}
    position_hints = player_positions or {}
    matches = _recent_completed_matches(
        iteration_id,
        squad_id,
        limit=match_limit,
        before=before,
        exclude_match_id=exclude_match_id,
    )
    merged: dict[int, dict[str, Any]] = {}
    match_count = 0

    if matches:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(_process_match_rankings, int(match["id"]), squad_id)
                for match in matches
            ]
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception:  # noqa: BLE001
                    continue
                match_count += 1
                _merge_player_totals(merged, result)

    players: list[dict[str, Any]] = []
    for player_id, row in merged.items():
        if _is_goalkeeper(row, position_hints):
            continue
        minutes = float(row.get("minutes") or 0.0)
        if minutes < MIN_MINUTES_FOR_PER90:
            continue
        kpis = row["kpis"]
        won_ground = float(kpis.get(KPI_WON_GROUND, 0))
        lost_ground = float(kpis.get(KPI_LOST_GROUND, 0))
        won_aerial = float(kpis.get(KPI_WON_AERIAL, 0))
        lost_aerial = float(kpis.get(KPI_LOST_AERIAL, 0))
        won = won_ground + won_aerial
        lost = lost_ground + lost_aerial
        duel_total = won + lost
        ground_total = won_ground + lost_ground
        aerial_total = won_aerial + lost_aerial
        goals_kpi = int(round(kpis.get(KPI_GOALS, 0)))
        goals_events = int(row.get("goals_total") or 0)
        goals_poss = int(row.get("goals_possession") or 0)
        goals_trans = int(row.get("goals_transition") or 0)
        goals_set = int(row.get("goals_set_play") or 0)
        goals_phase_sum = goals_poss + goals_trans + goals_set
        goals_total = max(goals_kpi, goals_events, goals_phase_sum)

        assists_kpi = int(round(kpis.get(KPI_ASSISTS, 0)))
        assists_events = int(row.get("assists_events") or 0)
        assists_poss = int(row.get("assists_possession") or 0)
        assists_trans = int(row.get("assists_transition") or 0)
        assists_set = int(row.get("assists_set_play") or 0)
        assists_phase_sum = assists_poss + assists_trans + assists_set
        assists = max(assists_kpi, assists_events, assists_phase_sum)
        name = names.get(player_id) or f"Player {player_id}"
        players.append(
            {
                "id": player_id,
                "name": name,
                "shirt_number": row.get("shirt_number"),
                "photo_url": opponent_photo_api_url(
                    name,
                    club_name=club_name,
                    season=season,
                ),
                "minutes": minutes,
                "goals": float(goals_total),
                "goals_possession": float(goals_poss),
                "goals_transition": float(goals_trans),
                "goals_set_play": float(goals_set),
                "assists": float(assists),
                "assists_possession": float(assists_poss),
                "assists_transition": float(assists_trans),
                "assists_set_play": float(assists_set),
                "threat_left": int(row.get("threat_left") or 0),
                "threat_centre": int(row.get("threat_centre") or 0),
                "threat_right": int(row.get("threat_right") or 0),
                "pxt": _per90(float(kpis.get(KPI_PXT_ATTACK, 0)), minutes),
                "pxt_pass": _per90(float(kpis.get(KPI_PXT_PASS, 0)), minutes),
                "pxt_dribble": _per90(float(kpis.get(KPI_PXT_DRIBBLE, 0)), minutes),
                "pxt_regain": _per90(float(kpis.get(KPI_PXT_BALL_WIN, 0)), minutes),
                "pxt_shot": _per90(float(kpis.get(KPI_PXT_SHOT, 0)), minutes),
                "pxt_set": _per90(float(kpis.get(KPI_PXT_SETPIECE, 0)), minutes),
                "pxt_rec": _per90(float(kpis.get(KPI_PXT_REC, 0)), minutes),
                "ball_progression": _per90(float(kpis.get(KPI_BYPASSED_OPPONENTS, 0)), minutes),
                "bypassed_defenders": _per90(float(kpis.get(KPI_BYPASSED_DEFENDERS, 0)), minutes),
                "presses": _per90(float(kpis.get(KPI_PRESSES, 0)), minutes),
                "presses_build_up": _per90(float(kpis.get(KPI_PRESSES_BUILD_UP, 0)), minutes),
                "presses_btl": _per90(float(kpis.get(KPI_PRESSES_BETWEEN_THE_LINES, 0)), minutes),
                "presses_counter": _per90(float(kpis.get(KPI_PRESSES_COUNTER, 0)), minutes),
                "regains_vs_defenders": _per90(float(kpis.get(KPI_BALL_WIN_VS_DEFENDERS, 0)), minutes),
                "offensive_interventions": _per90(
                    float(kpis.get(KPI_OFFENSIVE_INTERVENTIONS, 0)), minutes
                ),
                "oi_duel": _per90(float(kpis.get(KPI_OI_BY_DUEL, 0)), minutes),
                "oi_loose": _per90(float(kpis.get(KPI_OI_BY_LOOSE, 0)), minutes),
                "oi_intercept": _per90(float(kpis.get(KPI_OI_BY_INTERCEPTION, 0)), minutes),
                "oi_header": _per90(float(kpis.get(KPI_OI_BY_HEADER, 0)), minutes),
                "oi_block": _per90(float(kpis.get(KPI_OI_BY_BLOCK, 0)), minutes),
                "duel_rate": (100.0 * won / duel_total) if duel_total >= 8 else -1.0,
                "ground_duel_rate": (
                    (100.0 * won_ground / ground_total) if ground_total >= 1 else 0.0
                ),
                "aerial_duel_rate": (
                    (100.0 * won_aerial / aerial_total) if aerial_total >= 1 else 0.0
                ),
                "duels": int(round(duel_total)),
            }
        )

    def goal_breakdown(row: dict[str, Any]) -> list[dict[str, Any]]:
        return _phase_parts(
            possession=int(row.get("goals_possession") or 0),
            transition=int(row.get("goals_transition") or 0),
            set_play=int(row.get("goals_set_play") or 0),
            total=int(round(float(row.get("goals") or 0))),
        )

    def assist_breakdown(row: dict[str, Any]) -> list[dict[str, Any]]:
        return _phase_parts(
            possession=int(row.get("assists_possession") or 0),
            transition=int(row.get("assists_transition") or 0),
            set_play=int(row.get("assists_set_play") or 0),
            total=int(round(float(row.get("assists") or 0))),
        )

    def threat_breakdown(row: dict[str, Any]) -> list[dict[str, Any]]:
        # Impect has no separate PXT_CROSS — crosses sit inside Pass.
        return _share_parts(
            [
                ("pass", "Pass", float(row.get("pxt_pass") or 0.0)),
                ("dribble", "Drib", float(row.get("pxt_dribble") or 0.0)),
                ("regain", "Regain", float(row.get("pxt_regain") or 0.0)),
                ("shot", "Shot", float(row.get("pxt_shot") or 0.0)),
                ("set", "Set", float(row.get("pxt_set") or 0.0)),
                ("rec", "Rec", float(row.get("pxt_rec") or 0.0)),
            ],
            total=float(row.get("pxt") or 0.0),
        )

    def oi_breakdown(row: dict[str, Any]) -> list[dict[str, Any]]:
        return _share_parts(
            [
                ("duel", "Duel", float(row.get("oi_duel") or 0.0)),
                ("intercept", "Int", float(row.get("oi_intercept") or 0.0)),
                ("loose", "Loose", float(row.get("oi_loose") or 0.0)),
                ("header", "Head", float(row.get("oi_header") or 0.0)),
                ("block", "Block", float(row.get("oi_block") or 0.0)),
            ],
            total=float(row.get("offensive_interventions") or 0.0),
        )

    def press_breakdown(row: dict[str, Any]) -> list[dict[str, Any]]:
        # Build-up / between lines / counter-press are only part of all presses.
        return _share_parts(
            [
                ("build", "Build", float(row.get("presses_build_up") or 0.0)),
                ("btl", "BTL", float(row.get("presses_btl") or 0.0)),
                ("counter", "Counter", float(row.get("presses_counter") or 0.0)),
            ],
            total=float(row.get("presses") or 0.0),
            top_n=3,
        )

    def duel_breakdown(row: dict[str, Any]) -> list[dict[str, Any]]:
        ground = float(row.get("ground_duel_rate") or 0.0)
        aerial = float(row.get("aerial_duel_rate") or 0.0)
        return [
            {
                "key": "ground",
                "label": "Ground",
                "value": round(ground, 1),
                "value_label": f"{round(ground):.0f}%",
            },
            {
                "key": "aerial",
                "label": "Aerial",
                "value": round(aerial, 1),
                "value_label": f"{round(aerial):.0f}%",
            },
        ]

    rate1 = lambda v: _fmt_rate(v, 1)
    rate2 = lambda v: _fmt_rate(v, 2)
    total_int = lambda v: str(int(round(float(v))))

    in_possession = [
        _board(
            "goals",
            "Top goal scorers",
            "Season totals · phase split",
            players,
            value_key="goals",
            format_value=total_int,
            min_value=0.5,
            breakdown_builder=goal_breakdown,
        ),
        _board(
            "assists",
            "Most assists",
            "Season totals · phase split",
            players,
            value_key="assists",
            format_value=total_int,
            min_value=0.5,
            breakdown_builder=assist_breakdown,
        ),
        _board(
            "pxt",
            "Most expected threat",
            "PXT / 90 · share by action type",
            players,
            value_key="pxt",
            format_value=rate2,
            min_value=0.01,
            breakdown_builder=threat_breakdown,
        ),
        _board(
            "ball_progression",
            "Best ball progression",
            "Bypassed opponents / 90",
            players,
            value_key="ball_progression",
            format_value=rate1,
            min_value=0.1,
        ),
        _board(
            "bypassed_defenders",
            "Most defenders bypassed",
            "Line-breaking / 90",
            players,
            value_key="bypassed_defenders",
            format_value=rate1,
            min_value=0.1,
        ),
    ]

    out_of_possession = [
        _board(
            "regains_vs_defenders",
            "Most regains vs defenders",
            "Ball wins off defenders / 90",
            players,
            value_key="regains_vs_defenders",
            format_value=rate1,
            min_value=0.1,
        ),
        _board(
            "offensive_interventions",
            "Most offensive interventions",
            "Opponents removed / 90 · share by win type",
            players,
            value_key="offensive_interventions",
            format_value=rate1,
            min_value=0.1,
            breakdown_builder=oi_breakdown,
        ),
        _board(
            "presses",
            "Most presses",
            "Presses / 90 · share by press type",
            players,
            value_key="presses",
            format_value=rate1,
            min_value=0.1,
            breakdown_builder=press_breakdown,
        ),
        _board(
            "duel_rate",
            "Best duel rate",
            "Min. 8 duels · ground & aerial win %",
            players,
            value_key="duel_rate",
            format_value=_fmt_pct,
            min_value=0.1,
            breakdown_builder=duel_breakdown,
        ),
    ]

    return {
        "matches": match_count,
        "per_90": True,
        "min_minutes": int(MIN_MINUTES_FOR_PER90),
        "splits_version": 5,
        "in_possession": in_possession,
        "out_of_possession": out_of_possession,
    }
