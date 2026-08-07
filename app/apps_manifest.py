"""Single source of truth for hub tools (sidebar + auth + smoke).

Every staff tool must appear here. Agents: add the tool to APPS (and register
its FastAPI routes in register_apps.py) before deploying.
"""

from __future__ import annotations

from typing import Any

APP_GROUPS: list[dict[str, Any]] = [
    {
        "id": "analysis",
        "title": "Analysis",
        "subtitle": "Pre-match prep, handouts, and post-match review",
        "icon": "📊",
        "accent": "#34d399",
    },
    {
        "id": "recruitment",
        "title": "Recruitment",
        "subtitle": "Search, compare, and plan the squad",
        "icon": "🔍",
        "accent": "#3d8bfd",
    },
    {
        "id": "scouts",
        "title": "Scouts",
        "subtitle": "Fixtures, coverage, calendars, travel map, and scout reports",
        "icon": "🗓️",
        "accent": "#f97316",
    },
    {
        "id": "strategy",
        "title": "Strategy",
        "subtitle": "Squad reviews, benchmarks, and league context",
        "icon": "📈",
        "accent": "#f5c518",
    },
]

# roles: which login roles may open the tool. "admin" always sees everything.
# api_prefixes: path prefixes the role may hit (page + /api/...).
APPS: list[dict[str, Any]] = [
    {
        "id": "pre-match-handout",
        "group": "analysis",
        "title": "Pre-Match Handout",
        "description": (
            "A4 keynote handout for the dressing room — predicted XI, previous "
            "lineups, form, rankings, and player profiles. PDF export."
        ),
        "href": "/pre-match-handout",
        "icon": "📄",
        "accent": "#f97316",
        "tags": ["Opponent", "A4", "Export"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/pre-match-handout", "/api/pre-match-handout"),
        "router": "pre_match_handout",
    },
    {
        "id": "pre-match",
        "group": "analysis",
        "title": "Pre-Match Report",
        "description": (
            "Automated opponent prep — squad overview, form, team metrics, and more."
        ),
        "href": "/pre-match",
        "icon": "📋",
        "accent": "#fbbf24",
        "tags": ["Opponent", "Prep"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/pre-match", "/api/pre-match"),
        "router": "pre_match",
    },
    {
        "id": "set-piece-pre-match",
        "group": "analysis",
        "title": "Set Piece Pre-Match",
        "description": (
            "Dedicated set-play prep — squad heights, first-contact maps, "
            "corner/FK KPIs, and aerial threats."
        ),
        "href": "/set-piece-pre-match",
        "icon": "🚩",
        "accent": "#14b8a6",
        "tags": ["Opponent", "Set pieces"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/set-piece-pre-match", "/api/set-piece-pre-match"),
        "router": "set_piece_pre_match",
    },
    {
        "id": "player-cards",
        "group": "analysis",
        "title": "Player Cards",
        "description": (
            "Blank opponent squad cards for performance analysis — club site "
            "headshots, Impect height and foot, 26/27 fixtures."
        ),
        "href": "/player-cards",
        "icon": "🪪",
        "accent": "#e52320",
        "tags": ["Opponent", "Squad", "Cards"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/player-cards", "/api/player-cards"),
        "router": "player_cards",
    },
    {
        "id": "xg-chance-analysis",
        "group": "analysis",
        "title": "xG Chance Analysis",
        "description": (
            "Break down shot quality by chance rating, game state, half, and "
            "manpower. See which players take high vs low xG shots — season or "
            "single match."
        ),
        "href": "/xg-chance-analysis",
        "icon": "🎯",
        "accent": "#38bdf8",
        "tags": ["xG", "Shots", "Game state"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/xg-chance-analysis", "/api/xg-chance-analysis"),
        "router": "xg_chance_analysis",
    },
    {
        "id": "post-match",
        "group": "analysis",
        "title": "Post-Match Report",
        "description": (
            "Live post-match data slides — xG race, momentum, zones, player "
            "bars, and PDF export."
        ),
        "href": "/post-match",
        "icon": "📊",
        "accent": "#34d399",
        "tags": ["Match day", "Export"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/post-match", "/api/post-match"),
        "router": "post_match",
    },
    {
        "id": "schedule",
        "group": "analysis",
        "title": "Schedule",
        "description": (
            "First-team calendar — Port Vale fixtures from FotMob, training vs "
            "regen days, report times, and custom events."
        ),
        "href": "/schedule",
        "icon": "📆",
        "accent": "#22c55e",
        "tags": ["Training", "Fixtures", "Calendar"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/schedule", "/api/schedule"),
        "router": "schedule",
    },
    {
        "id": "player-comparison",
        "group": "recruitment",
        "title": "Player Comparison Tool",
        "description": (
            "Search players, add them to a comparison, and build radar and "
            "pizza charts side by side."
        ),
        "href": "/studio",
        "icon": "⚽",
        "accent": "#56d4ff",
        "tags": ["Charts", "Profiles"],
        "roles": ("admin",),
        "api_prefixes": ("/studio", "/api/"),
        "router": "main_studio",
    },
    {
        "id": "who-to-scout",
        "group": "recruitment",
        "title": "Who To Scout",
        "description": (
            "Top profile scorers by league and position — adjust profile "
            "weights, filter by age, height, club and minutes."
        ),
        "href": "/who-to-scout",
        "icon": "🎯",
        "accent": "#34d399",
        "tags": ["Scouting", "Profiles", "Leagues"],
        "roles": ("admin",),
        "api_prefixes": ("/who-to-scout", "/api/who-to-scout"),
        "router": "who_to_scout",
    },
    {
        "id": "player-search",
        "group": "recruitment",
        "title": "Player Search Dashboard",
        "description": (
            "Profile-weighted scouting lists by position and league. Rank, "
            "filter, export Excel or PDF."
        ),
        "href": "/scouting",
        "icon": "🔍",
        "accent": "#3d8bfd",
        "tags": ["Scouting", "Search"],
        "roles": ("admin",),
        "api_prefixes": ("/scouting", "/api/scouting"),
        "router": "scouting",
    },
    {
        "id": "squad-balance",
        "group": "recruitment",
        "title": "Squad Balance",
        "description": (
            "Recruitment squad builder — search players per position, paste "
            "headshots, squad-average profile scores."
        ),
        "href": "/squad-balance",
        "icon": "⚖️",
        "accent": "#f5c518",
        "tags": ["Squad", "Balance"],
        "roles": ("admin",),
        "api_prefixes": ("/squad-balance", "/api/squad-balance"),
        "router": "squad_balance",
    },
    {
        "id": "squad-planner",
        "group": "recruitment",
        "title": "Squad Planner",
        "description": (
            "Plan current and shadow squads by formation. Search players, tag "
            "with age labels, and track potential signings."
        ),
        "href": "/squad-planner",
        "icon": "📋",
        "accent": "#3d8bfd",
        "tags": ["Squad", "Planning"],
        "roles": ("admin",),
        "api_prefixes": ("/squad-planner", "/api/squad-planner"),
        "router": "squad_planner",
    },
    {
        "id": "fixture-planner",
        "group": "scouts",
        "title": "Fixture Planner",
        "description": (
            "Upcoming fixtures only — assign scouts Live or Video across the "
            "leagues. Feeds Scout Summary."
        ),
        "href": "/fixture-planner",
        "icon": "📅",
        "accent": "#34d399",
        "tags": ["Fixtures", "Upcoming"],
        "roles": ("admin",),
        "api_prefixes": ("/fixture-planner", "/api/fixture-planner"),
        "router": "fixture_planner",
    },
    {
        "id": "played-fixtures",
        "group": "scouts",
        "title": "Played Fixtures",
        "description": (
            "Games that have taken place — keep LIVE ownership, pick up VIDEO "
            "coverage, players and reports."
        ),
        "href": "/played-fixtures",
        "icon": "🎬",
        "accent": "#fbbf24",
        "tags": ["Fixtures", "Played", "Video"],
        "roles": ("admin",),
        "api_prefixes": ("/played-fixtures", "/api/fixture-planner"),
        "router": "fixture_planner",
    },
    {
        "id": "scouting-address",
        "group": "scouts",
        "title": "Scouting Address Tool",
        "description": (
            "UK stadium map for EFL, National League, NL North/South, Scottish "
            "Prem/Champ and more."
        ),
        "href": "/scouting-address",
        "icon": "🗺️",
        "accent": "#38bdf8",
        "tags": ["Scouts", "Map", "Travel"],
        "roles": ("admin",),
        "api_prefixes": ("/scouting-address", "/api/scouting-address"),
        "router": "scouting_address",
    },
    {
        "id": "scout-summary-report",
        "group": "scouts",
        "title": "Generate Scout Summary",
        "description": (
            "Pick a date range, preview KPIs, league charts, player reports "
            "and team coverage, then export the PDF."
        ),
        "href": "/scout-summary-report",
        "icon": "📄",
        "accent": "#38bdf8",
        "tags": ["Scouts", "Reports", "PDF"],
        "roles": ("admin",),
        "api_prefixes": ("/scout-summary-report", "/api/fixture-planner"),
        "router": "fixture_planner",
    },
    {
        "id": "scout-summary",
        "group": "scouts",
        "title": "Scout Summary",
        "description": (
            "Who has covered what — pulls from Fixture Planner and Played "
            "Fixtures (live vs video, by scout and league)."
        ),
        "href": "/scout-summary",
        "icon": "📊",
        "accent": "#a78bfa",
        "tags": ["Scouts", "Coverage"],
        "roles": ("admin",),
        "api_prefixes": ("/scout-summary", "/api/fixture-planner"),
        "router": "fixture_planner",
    },
    {
        "id": "scouts-calendar",
        "group": "scouts",
        "title": "Scouts Calendar",
        "description": (
            "Live calendar of assigned fixtures. Scouts see upcoming live "
            "games — auto-refreshes every 30 seconds."
        ),
        "href": "/scouts-calendar",
        "icon": "🗓️",
        "accent": "#f97316",
        "tags": ["Scouts", "Live"],
        "roles": ("admin",),
        "api_prefixes": ("/scouts-calendar", "/api/fixture-planner"),
        "router": "fixture_planner",
    },
    {
        "id": "squad-comparison",
        "group": "strategy",
        "title": "Squad Comparison",
        "description": (
            "Internal squad reviews — compare Port Vale players by PV profile "
            "percentiles. Live-updates through the season."
        ),
        "href": "/squad-review",
        "icon": "👥",
        "accent": "#f5c518",
        "tags": ["Squad", "Internal"],
        "roles": ("admin",),
        "api_prefixes": ("/squad-review", "/api/squad-review"),
        "router": "squad_review",
    },
    {
        "id": "availability-tracker",
        "group": "strategy",
        "title": "Squad Availability",
        "description": (
            "Training and match availability tracker — log injuries, training "
            "attendance, and auto-fill minutes from Impect."
        ),
        "href": "/availability-tracker",
        "icon": "🏥",
        "accent": "#ef4444",
        "tags": ["Squad", "Injuries", "Training"],
        "roles": ("admin",),
        "api_prefixes": ("/availability-tracker", "/api/availability"),
        "router": "availability_tracker",
    },
    {
        "id": "club-strategy",
        "group": "strategy",
        "title": "Club Strategy",
        "description": (
            "League Two benchmarks — standings, shooting, xG/xPoints, and "
            "first-goal analysis with live season tracking."
        ),
        "href": "/club-strategy",
        "icon": "🎯",
        "accent": "#f5c518",
        "tags": ["League Two", "FGS", "xG"],
        "roles": ("admin",),
        "api_prefixes": ("/club-strategy", "/api/club-strategy"),
        "router": "club_strategy",
    },
    {
        "id": "league-two-strategy",
        "group": "strategy",
        "title": "League Two Strategy Report",
        "description": (
            "Season strategy slides — promotion point benchmarks, league "
            "context, and targets (21/22–25/26)."
        ),
        "href": "/strategy",
        "icon": "📈",
        "accent": "#f5c518",
        "tags": ["League Two", "Strategy"],
        "roles": ("admin",),
        "api_prefixes": ("/strategy", "/strategy/assets"),
        "router": "scouting",
    },
    {
        "id": "players-strategy",
        "group": "strategy",
        "title": "Players Strategy Report",
        "description": (
            "Dressing-room presentation — punchy promotion standards. Build "
            "here, then Present or Export PDF."
        ),
        "href": "/players-strategy",
        "icon": "🗣️",
        "accent": "#f5c518",
        "tags": ["League Two", "Players", "Presentation"],
        "roles": ("admin",),
        "api_prefixes": ("/players-strategy",),
        "router": "scouting",
    },
    {
        "id": "league-two-progress",
        "group": "strategy",
        "title": "League Two Progress Report",
        "description": (
            "Track live promotion progress, point pace, and season targets "
            "against benchmarks."
        ),
        "href": "/strategy-tracker",
        "icon": "📉",
        "accent": "#fbbf24",
        "tags": ["League Two", "Progress"],
        "roles": ("admin",),
        "api_prefixes": ("/strategy-tracker", "/api/strategy-tracker"),
        "router": "strategy_tracker",
    },
]


def apps_for_role(role: str) -> list[dict[str, Any]]:
    role_key = (role or "analysis").strip().lower()
    if role_key == "admin":
        return list(APPS)
    return [app for app in APPS if role_key in tuple(app.get("roles") or ())]


def public_app_payload(app: dict[str, Any]) -> dict[str, Any]:
    """Sidebar-safe fields (no internal router keys required by the client)."""
    return {
        "id": app["id"],
        "group": app["group"],
        "title": app["title"],
        "description": app.get("description") or "",
        "href": app["href"],
        "icon": app.get("icon") or "◆",
        "accent": app.get("accent") or "#3d8bfd",
        "tags": list(app.get("tags") or []),
    }


def analysis_path_prefixes() -> tuple[str, ...]:
    prefixes: list[str] = []
    for app in APPS:
        roles = tuple(app.get("roles") or ())
        if "analysis" not in roles:
            continue
        for prefix in app.get("api_prefixes") or ():
            prefixes.append(str(prefix))
    # Shared assets + feedback always allowed for signed-in analysis users.
    prefixes.extend(("/api/feedback", "/api/apps", "/static/", "/standalone/"))
    # Dedupe, longest-first so more specific prefixes win in mental model
    # (middleware uses startswith either way).
    uniq = sorted(set(prefixes), key=lambda p: (-len(p), p))
    return tuple(uniq)


def required_sidebar_titles() -> list[str]:
    return [str(app["title"]) for app in APPS]


def manifest_payload(*, role: str = "admin") -> dict[str, Any]:
    apps = [public_app_payload(app) for app in apps_for_role(role)]
    groups_used = {app["group"] for app in apps}
    groups = [g for g in APP_GROUPS if g["id"] in groups_used]
    return {
        "groups": groups,
        "apps": apps,
        "titles": [app["title"] for app in apps],
    }
