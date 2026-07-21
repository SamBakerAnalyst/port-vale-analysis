from __future__ import annotations

from typing import Any

SHOT_XG_TOLERANCE = 0.01

SHOT_BASED_METRIC_IDS = frozenset({
    "shotBasedXg",
    "shotBasedXgAgainst",
})

POST_SHOT_METRIC_IDS = frozenset({
    "postShotXg",
    "postShotXgAgainst",
})


def _close(a: float | None, b: float | None, *, tol: float = SHOT_XG_TOLERANCE) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= tol


def validate_shots_payload(payload: dict[str, Any], *, context: str) -> None:
    """Ensure every shot-based xG surface on a shots slide shows the same values."""
    summary = payload.get("summary") or {}
    team_metrics = payload.get("teamMetrics") or []
    phases = payload.get("phases") or []
    shot_points = payload.get("shotPoints") or []

    canonical_shot_xg = round(float(payload.get("totalShotXg") or summary.get("totalXg") or 0), 4)
    points_sum = round(sum(float(point.get("xg") or 0) for point in shot_points), 4)
    if not _close(canonical_shot_xg, points_sum):
        raise ValueError(
            f"{context}: shot xG mismatch — canonical total {canonical_shot_xg} "
            f"vs shot map sum {points_sum}"
        )

    summary_xg = round(float(summary.get("totalXg") or 0), 4)
    if not _close(canonical_shot_xg, summary_xg):
        raise ValueError(
            f"{context}: shot xG mismatch — canonical {canonical_shot_xg} "
            f"vs summary {summary_xg}"
        )

    shot_metric = next(
        (row for row in team_metrics if row.get("id") in SHOT_BASED_METRIC_IDS),
        None,
    )
    if shot_metric is None:
        return

    metric_match = round(float(shot_metric.get("matchValue") or 0), 4)
    if not _close(canonical_shot_xg, metric_match):
        raise ValueError(
            f"{context}: shot xG mismatch — canonical {canonical_shot_xg} "
            f"vs team metric {metric_match}"
        )

    summary_display = summary.get("totalXgDisplay")
    metric_display = shot_metric.get("matchDisplay")
    if summary_display != metric_display:
        raise ValueError(
            f"{context}: shot xG display mismatch — summary {summary_display!r} "
            f"vs team metric {metric_display!r}"
        )

    summary_avg = summary.get("avgXg")
    metric_avg = shot_metric.get("avgValue")
    if summary_avg is not None and metric_avg is not None and not _close(summary_avg, metric_avg):
        raise ValueError(
            f"{context}: shot xG average mismatch — summary {summary_avg} "
            f"vs team metric {metric_avg}"
        )

    summary_avg_display = summary.get("avgXgDisplay")
    metric_avg_display = shot_metric.get("avgDisplay")
    if (
        summary_avg_display is not None
        and metric_avg_display is not None
        and summary_avg_display != metric_avg_display
    ):
        raise ValueError(
            f"{context}: shot xG average display mismatch — summary {summary_avg_display!r} "
            f"vs team metric {metric_avg_display!r}"
        )

    phase_total = next((row for row in phases if row.get("isTotal")), None)
    if phase_total is not None:
        phase_xg = round(float(phase_total.get("xg") or 0), 4)
        if not _close(canonical_shot_xg, phase_xg):
            raise ValueError(
                f"{context}: shot xG mismatch — canonical {canonical_shot_xg} "
                f"vs phase total {phase_xg}"
            )
        phase_display = phase_total.get("xgDisplay")
        if phase_display != summary_display:
            raise ValueError(
                f"{context}: shot xG display mismatch — summary {summary_display!r} "
                f"vs phase total {phase_display!r}"
            )
        if (
            summary_avg_display is not None
            and phase_total.get("avgXgDisplay") is not None
            and phase_total.get("avgXgDisplay") != summary_avg_display
        ):
            raise ValueError(
                f"{context}: shot xG average display mismatch — summary {summary_avg_display!r} "
                f"vs phase total {phase_total.get('avgXgDisplay')!r}"
            )


def _race_total_for_squad(xg_race: dict[str, Any], squad_id: int) -> float:
    for key in ("home", "away"):
        side = xg_race.get(key) or {}
        if int(side.get("squadId") or 0) == squad_id:
            return round(float(side.get("totalXg") or 0), 4)
    return 0.0


def validate_report_shot_xg(report: dict[str, Any]) -> None:
    """Cross-slide check: shots slides must agree with the xG race chart."""
    xg_race = report.get("xgRace") or {}
    focus_id = int(report.get("focusSquadId") or 0)
    opponent_id = int(report.get("opponentSquadId") or 0)

    checks = (
        ("shots", focus_id, "In-possession shots"),
        ("shotsAgainst", opponent_id, "Shots against"),
    )
    for slide_key, squad_id, label in checks:
        if not squad_id:
            continue
        payload = report.get(slide_key) or {}
        if not payload.get("summary"):
            continue
        validate_shots_payload(payload, context=label)
        slide_xg = round(float(payload["summary"].get("totalXg") or 0), 4)
        race_xg = _race_total_for_squad(xg_race, squad_id)
        if not _close(slide_xg, race_xg):
            raise ValueError(
                f"{label}: shot xG mismatch — slide summary {slide_xg} vs xG race {race_xg}"
            )
