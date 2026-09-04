"""Register all hub tool FastAPI routes from the apps manifest.

Call register_all_app_routes(app) once from main.py (after main has finished
loading). Startup fails if a manifest tool points at a router that was not
registered.

Registrars are imported lazily to avoid circular imports with app.main.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, Request

from app.apps_manifest import APPS, manifest_payload
from app.auth import current_role, is_authenticated, auth_enabled


def _load_router_registrars() -> dict[str, Callable[[FastAPI], None]]:
    from app.availability_tracker import register_availability_tracker_routes
    from app.blocks_analysis import register_blocks_analysis_routes
    from app.club_strategy import register_club_strategy_routes
    from app.fixture_planner import register_fixture_planner_routes
    from app.hub_origin import register_hub_origin_routes
    from app.match_dashboards import register_match_dashboards_routes
    from app.match_day_countdown import register_match_day_countdown_routes
    from app.meeting_front_pages import register_meeting_front_pages_routes
    from app.player_cards import register_player_cards_routes
    from app.player_pipelines import register_player_pipelines_routes
    from app.presentations import register_presentations_routes
    from app.post_match.routes import register_post_match_routes
    from app.pre_match import register_pre_match_routes
    from app.schedule import register_schedule_routes
    from app.scouting import register_scouting_routes
    from app.scouting_address import register_scouting_address_routes
    from app.scoutable_teams import register_scoutable_teams_routes
    from app.set_piece_pre_match import register_set_piece_pre_match_routes
    from app.squad_balance import register_squad_balance_routes
    from app.squad_planner import register_squad_planner_routes
    from app.squad_review import register_squad_review_routes
    from app.strategy_tracker import register_strategy_tracker_routes
    from app.who_to_scout import register_who_to_scout_routes
    from app.win_drivers import register_win_drivers_routes
    from app.goal_involvement import register_goal_involvement_routes
    from app.xg_chance_analysis import register_xg_chance_analysis_routes
    from app.window_review import register_window_review_routes
    from app.efl_transfer_report import register_efl_transfer_report_routes

    return {
        "match_dashboards": register_match_dashboards_routes,
        "match_day_countdown": register_match_day_countdown_routes,
        "post_match": register_post_match_routes,
        "pre_match": register_pre_match_routes,
        "set_piece_pre_match": register_set_piece_pre_match_routes,
        "player_cards": register_player_cards_routes,
        "xg_chance_analysis": register_xg_chance_analysis_routes,
        "goal_involvement": register_goal_involvement_routes,
        "hub_origin": register_hub_origin_routes,
        "window_review": register_window_review_routes,
        "efl_transfer_report": register_efl_transfer_report_routes,
        "blocks_analysis": register_blocks_analysis_routes,
        "schedule": register_schedule_routes,
        "scouting": register_scouting_routes,
        "scoutable_teams": register_scoutable_teams_routes,
        "squad_review": register_squad_review_routes,
        "squad_planner": register_squad_planner_routes,
        "squad_balance": register_squad_balance_routes,
        "fixture_planner": register_fixture_planner_routes,
        "club_strategy": register_club_strategy_routes,
        "win_drivers": register_win_drivers_routes,
        "availability_tracker": register_availability_tracker_routes,
        "scouting_address": register_scouting_address_routes,
        "who_to_scout": register_who_to_scout_routes,
        "player_pipelines": register_player_pipelines_routes,
        "presentations": register_presentations_routes,
        "strategy_tracker": register_strategy_tracker_routes,
        "meeting_front_pages": register_meeting_front_pages_routes,
        # Covered by routes defined in main.py (studio) — no-op registrar.
        "main_studio": lambda _app: None,
    }


def _load_always_register() -> tuple[Callable[[FastAPI], None], ...]:
    from app.board_briefing import register_board_briefing_routes
    from app.feedback import register_feedback_routes
    from app.handout_badges import register_team_badge_routes
    from app.home_dashboard import register_home_dashboard_routes
    from app.hub_snapshots import register_hub_snapshots_routes
    from app.player_dossier import register_player_dossier_routes
    from app.wysiwyg_export import register_wysiwyg_export_routes

    return (
        register_home_dashboard_routes,
        register_player_dossier_routes,
        register_team_badge_routes,
        register_feedback_routes,
        register_wysiwyg_export_routes,
        register_hub_snapshots_routes,
        # Retired from sidebar — keep URL alive for old bookmarks.
        register_board_briefing_routes,
    )


def register_all_app_routes(app: FastAPI) -> None:
    registrars = _load_router_registrars()
    registered: set[str] = set()

    for router_id, registrar in registrars.items():
        registrar(app)
        registered.add(router_id)

    for registrar in _load_always_register():
        registrar(app)

    missing: list[str] = []
    for app_row in APPS:
        router_id = str(app_row.get("router") or "")
        if not router_id:
            missing.append(f"{app_row['id']} (no router key)")
            continue
        if router_id not in registered:
            missing.append(f"{app_row['id']} → router '{router_id}' not registered")
        if router_id not in registrars:
            missing.append(f"{app_row['id']} → unknown router '{router_id}'")

    if missing:
        detail = "; ".join(missing)
        raise RuntimeError(
            "Apps manifest / route registry mismatch — fix before serving traffic: "
            + detail
        )

    @app.get("/api/apps")
    def list_apps(request: Request) -> dict[str, Any]:
        if auth_enabled() and not is_authenticated(request):
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Not authenticated")
        role = current_role(request) if auth_enabled() else "admin"
        return manifest_payload(role=role)
