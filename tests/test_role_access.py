"""Role boundaries for personal staff logins.

The scouts role exists so each scout signs in as themselves (real names on Watch
list and pipeline notes) without handing over Strategy or the Presentations decks.
These tests pin that boundary — widening it should be a deliberate edit here.
"""

from __future__ import annotations

import pytest

from app.apps_manifest import APPS, RECRUITMENT_GROUPS, role_path_prefixes
from app.auth import ROLE_GROUPS, ROLE_HOME_TABS, _path_allowed_for_role


def _app(app_id: str) -> dict:
    return next(app for app in APPS if app["id"] == app_id)


def _titles_for_role(role: str) -> set[str]:
    return {app["title"] for app in APPS if role in tuple(app.get("roles") or ())}


def test_scouts_role_is_registered_with_recruitment_and_scouts_groups():
    assert ROLE_GROUPS["scouts"] == ("recruitment", "scouts")
    assert ROLE_HOME_TABS["scouts"] == ("home", "recruitment")


def test_every_role_has_home_tabs_and_groups():
    assert set(ROLE_GROUPS) == set(ROLE_HOME_TABS)
    for role, tabs in ROLE_HOME_TABS.items():
        assert "home" in tabs, f"{role} cannot open the hub landing tab"


@pytest.mark.parametrize(
    "app_id",
    [
        "who-to-scout",
        "watch-list",
        "player-pipelines",
        "scoutable-teams",
        "squad-planner",
        "squad-balance",
        "player-comparison",
        "fixture-planner",
        "played-fixtures",
        "scouting-address",
        "scout-summary",
        "scouts-calendar",
    ],
)
def test_scouts_can_open_the_scouting_workflow(app_id):
    assert "scouts" in _app(app_id)["roles"], f"{app_id} locked out for scouts"


@pytest.mark.parametrize(
    "app_id",
    ["club-strategy", "win-drivers", "availability-tracker", "presentations"],
)
def test_scouts_cannot_open_strategy_or_presentations(app_id):
    assert "scouts" not in _app(app_id)["roles"], f"{app_id} leaked to scouts"


def test_scouts_and_analysis_roles_do_not_overlap():
    assert not _titles_for_role("scouts") & _titles_for_role("analysis")


def test_no_app_grants_a_bare_api_wildcard_to_a_non_admin_role():
    """A bare "/api/" prefix on a shared app hands over the whole API."""
    for app in APPS:
        roles = {r for r in (app.get("roles") or ()) if r != "admin"}
        if not roles:
            continue
        prefixes = {str(p).rstrip("/") for p in (app.get("api_prefixes") or ())}
        assert "/api" not in prefixes, (
            f"{app['id']} exposes all of /api to {sorted(roles)}"
        )


def test_recruitment_support_paths_reach_scouts_but_not_analysis():
    """Watch list rows link to the dossier and read the daily snapshot."""
    for path in (
        "/player/12345",
        "/api/player/12345/notes",
        "/api/hub-snapshots/status",
        "/api/home/recruitment",
    ):
        assert _path_allowed_for_role(path, "scouts"), f"scouts blocked from {path}"
        assert not _path_allowed_for_role(path, "analysis"), f"{path} leaked to analysis"


def test_scouts_are_blocked_from_analysis_and_strategy_endpoints():
    for path in ("/api/post-match", "/post-match", "/api/club-strategy", "/club-strategy"):
        assert not _path_allowed_for_role(path, "scouts"), f"{path} leaked to scouts"


def test_analysis_role_keeps_its_existing_tools():
    for path in ("/pre-match", "/api/pre-match", "/api/schedule", "/blocks-analysis"):
        assert _path_allowed_for_role(path, "analysis"), f"analysis lost {path}"


def test_scouts_reach_their_own_tool_pages_and_apis():
    for path in (
        "/watch-list",
        "/api/watch-list",
        "/player-pipelines",
        "/api/player-pipelines/targets",
        "/who-to-scout",
        "/scoutable-teams",
        "/fixture-planner",
    ):
        assert _path_allowed_for_role(path, "scouts"), f"scouts blocked from {path}"


def test_admin_bypasses_the_allowlist_entirely():
    for path in ("/club-strategy", "/api/anything-at-all", "/presentations"):
        assert _path_allowed_for_role(path, "admin")


def test_shared_paths_and_hub_shell_open_for_every_role():
    for role in ROLE_GROUPS:
        for path in ("/", "/hub", "/api/apps", "/api/auth/me", "/static/styles.css"):
            assert _path_allowed_for_role(path, role), f"{role} blocked from {path}"


def test_raw_standalone_html_stays_blocked_for_non_admin_roles():
    for role in ("scouts", "analysis"):
        assert not _path_allowed_for_role("/standalone/club-strategy.html", role)
        assert _path_allowed_for_role("/standalone/watch-list.js", role)


def test_role_prefixes_never_contain_a_bare_slash():
    for role in ROLE_GROUPS:
        assert "/" not in role_path_prefixes(role)


def test_recruitment_groups_match_the_manifest_groups():
    assert RECRUITMENT_GROUPS == {"recruitment", "scouts"}


def test_logout_is_reachable_by_every_role():
    """Personal logins are useless without a way back out."""
    from app.auth import _is_public_path

    for role in ROLE_GROUPS:
        assert _path_allowed_for_role("/api/auth/logout", role)
    # The login page itself must stay reachable without a session.
    assert _is_public_path("/login")


def test_user_payload_reports_whether_login_is_enabled():
    """The Sign out button hides itself on a no-password local server."""
    from app.auth import current_user_payload

    class Req:
        session = {
            "authenticated": True,
            "username": "SamBaker",
            "display_name": "Sam Baker",
            "role": "admin",
        }

    payload = current_user_payload(Req())
    assert payload["auth_enabled"] is True
    assert payload["display_name"] == "Sam Baker"
