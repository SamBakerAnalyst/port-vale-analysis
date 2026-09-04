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
        "subtitle": "Pre-match prep and post-match review",
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
    {
        "id": "presentations",
        "title": "Presentations",
        "subtitle": "Personal decks — off the daily rail",
        "icon": "🎬",
        "accent": "#a78bfa",
    },
]

# roles: which login roles may open the tool. "admin" always sees everything.
# api_prefixes: path prefixes the role may hit (page + /api/...).
APPS: list[dict[str, Any]] = [
    {
        "id": "pre-match",
        "group": "analysis",
        "title": "Pre-Match Report",
        "description": (
            "Opponent prep — full slide deck plus editable Two pager handout."
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
        "id": "post-match",
        "group": "analysis",
        "title": "Post-Match Report",
        "description": (
            "Full post-match slide deck — shots, progression, crosses, duels, "
            "set plays, xG race and PDF export."
        ),
        "href": "/post-match",
        "icon": "📊",
        "accent": "#34d399",
        "tags": ["Match day"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/post-match", "/api/post-match"),
        "router": "post_match",
    },
    {
        "id": "match-day-countdown",
        "group": "analysis",
        "title": "Match Day Countdown",
        "description": (
            "Dead-simple dressing-room clock — next opponent badges, countdown "
            "to kick-off, and the next match-day timing (analysis, warm-up, etc.)."
        ),
        "href": "/match-day-countdown",
        "icon": "⏰",
        "accent": "#f5c518",
        "tags": ["Match day", "Clock"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/match-day-countdown", "/api/match-day-countdown"),
        "router": "match_day_countdown",
    },
    {
        "id": "match-story",
        "group": "analysis",
        "title": "Match Story",
        "description": "15-minute blocks, presses, duels and the xG race. For / against and combine games.",
        "href": "/match-dashboards?view=story",
        "icon": "⏱️",
        "accent": "#34d399",
        "tags": ["Match", "Momentum"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/match-dashboards", "/api/match-dashboards"),
        "router": "match_dashboards",
    },
    {
        "id": "ball-progression",
        "group": "analysis",
        "title": "Ball Progression",
        "description": "Team packing KPIs and player progression. For / against and combine games.",
        "href": "/match-dashboards?view=progression",
        "icon": "⏩",
        "accent": "#22c55e",
        "tags": ["In possession"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/match-dashboards", "/api/match-dashboards"),
        "router": "match_dashboards",
    },
    {
        "id": "crosses-dashboard",
        "group": "analysis",
        "title": "Crosses",
        "description": "Cross origins, flank packing and threat. For / against and combine games.",
        "href": "/match-dashboards?view=crosses",
        "icon": "➕",
        "accent": "#14b8a6",
        "tags": ["In possession"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/match-dashboards", "/api/match-dashboards"),
        "router": "match_dashboards",
    },
    {
        "id": "shots-xg",
        "group": "analysis",
        "title": "Shots & xG",
        "description": (
            "Shot map coloured by chance rating, plus game state, half/manpower "
            "and player xG tags. For / against and combine games."
        ),
        "href": "/match-dashboards?view=shots",
        "icon": "🎯",
        "accent": "#38bdf8",
        "tags": ["xG", "Shots", "Game state"],
        "roles": ("analysis", "admin"),
        "api_prefixes": (
            "/match-dashboards",
            "/api/match-dashboards",
            "/xg-chance-analysis",
            "/api/xg-chance-analysis",
        ),
        "router": "match_dashboards",
    },
    {
        "id": "duels-pressing",
        "group": "analysis",
        "title": "Duels & Pressing",
        "description": "Team duels, press height and player duel rows. For / against and combine games.",
        "href": "/match-dashboards?view=duels",
        "icon": "🛡️",
        "accent": "#f97316",
        "tags": ["Out of possession"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/match-dashboards", "/api/match-dashboards"),
        "router": "match_dashboards",
    },
    {
        "id": "xg-chance-analysis",
        "group": "analysis",
        "title": "xG Chance Analysis",
        "description": (
            "Break down shot quality by chance rating, game state, half, and "
            "manpower. Season or single match."
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
        "id": "goal-involvement",
        "group": "analysis",
        "title": "Goal Involvement",
        "description": (
            "Coaches split 10 points on every goal we score or concede. "
            "Averages, disagreement flags, and player season totals."
        ),
        "href": "/goal-involvement",
        "icon": "🔟",
        "accent": "#eab308",
        "tags": ["Goals", "Coaches", "Match day"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/goal-involvement", "/api/goal-involvement"),
        "router": "goal_involvement",
    },
    {
        "id": "blocks-analysis",
        "group": "analysis",
        "title": "Blocks Analysis",
        "description": (
            "Nine blocks of five league games — result colours, editable Silver "
            "targets, live block KPIs, and a 2-page A4 match report PDF."
        ),
        "href": "/blocks-analysis",
        "icon": "🧱",
        "accent": "#f5c518",
        "tags": ["League Two", "Blocks", "Live"],
        "roles": ("analysis", "admin"),
        "api_prefixes": ("/blocks-analysis", "/api/blocks-analysis"),
        "router": "blocks_analysis",
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
        "roles": ("scouts", "admin"),
        # Studio endpoints listed one by one. A bare "/api/" here would hand every
        # non-admin role the whole API.
        "api_prefixes": (
            "/studio",
            "/api/charts",
            "/api/export-pdf",
            "/api/export-pptx",
            "/api/iterations",
            "/api/player-history",
            "/api/player-positions",
            "/api/players",
            "/api/player-photo/upload",
            "/api/squad-balance/meta",
        ),
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
        "roles": ("scouts", "admin",),
        "api_prefixes": (
            "/who-to-scout",
            "/api/who-to-scout",
            "/api/player-pipelines",
            "/api/watch-list",
        ),
        "router": "who_to_scout",
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
        "roles": ("scouts", "admin",),
        "api_prefixes": ("/squad-balance", "/api/squad-balance"),
        "router": "squad_balance",
    },
    {
        "id": "watch-list",
        "group": "recruitment",
        "title": "Watch list",
        "description": (
            "Players spotted on Who To Scout / Stand outs — review here, then promote "
            "into Player Pipelines when scouts should progress them."
        ),
        "href": "/watch-list",
        "icon": "👀",
        "accent": "#38bdf8",
        "tags": ["Watch list", "Scouting", "Targets"],
        "roles": ("scouts", "admin",),
        "api_prefixes": ("/watch-list", "/api/watch-list", "/api/player-pipelines"),
        "router": "player_pipelines",
    },
    {
        "id": "player-pipelines",
        "group": "recruitment",
        "title": "Player Pipelines",
        "description": (
            "Shared recruitment progression board — promote from the Watch list, then drag "
            "between Data identified, Video scouted, Live scouted, Gone / turned us down, "
            "and Not the right fit. Notes and tags are visible to the whole team."
        ),
        "href": "/player-pipelines",
        "icon": "📌",
        "accent": "#a78bfa",
        "tags": ["Pipelines", "Scouting", "Targets", "Notes"],
        "roles": ("scouts", "admin",),
        "api_prefixes": ("/player-pipelines", "/api/player-pipelines"),
        "router": "player_pipelines",
    },
    {
        "id": "scoutable-teams",
        "group": "recruitment",
        "title": "Scoutable Teams",
        "description": (
            "Monday-style league boards — open any club, see player data scores, "
            "and move prospects straight onto Player Pipelines."
        ),
        "href": "/scoutable-teams",
        "icon": "🏟️",
        "accent": "#34d399",
        "tags": ["Scouting", "Clubs", "Pipelines"],
        "roles": ("scouts", "admin",),
        "api_prefixes": ("/scoutable-teams", "/api/scoutable-teams"),
        "router": "scoutable_teams",
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
        "roles": ("scouts", "admin",),
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
        "roles": ("scouts", "admin",),
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
        "roles": ("scouts", "admin",),
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
        "roles": ("scouts", "admin",),
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
        "roles": ("scouts", "admin",),
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
        "roles": ("scouts", "admin",),
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
        "roles": ("scouts", "admin",),
        "api_prefixes": ("/scouts-calendar", "/api/fixture-planner"),
        "router": "fixture_planner",
    },
    {
        "id": "meeting-front-pages",
        "group": "scouts",
        "title": "Meeting Front Pages",
        "description": (
            "Scout video title cards — identity page plus one PNG per PV "
            "profile (Wide Creator, Goal Threat, etc.). Download a pack."
        ),
        "href": "/meeting-front-pages",
        "icon": "🎬",
        "accent": "#f97316",
        "tags": ["Scouts", "Video", "PNG"],
        "roles": ("scouts", "admin",),
        "api_prefixes": (
            "/meeting-front-pages",
            "/api/meeting-front-pages",
            "/api/players",
            "/api/player",
            "/api/player-photo",
            "/api/pre-match/player-photo",
            "/api/wysiwyg-export-pdf",
            "/api/wysiwyg-export-png-zip",
        ),
        "router": "meeting_front_pages",
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
        "id": "league-two-progress",
        "group": "strategy",
        "title": "Season Progress Report",
        "description": (
            "Live promotion pace, Impect style stats, and a Present / PDF board pack "
            "versus auto / play-off / champions."
        ),
        "href": "/strategy-tracker",
        "icon": "📉",
        "accent": "#f5c518",
        "tags": ["League Two", "Progress", "Pace"],
        "roles": ("admin",),
        "api_prefixes": ("/strategy-tracker", "/api/strategy-tracker"),
        "router": "strategy_tracker",
    },
    {
        "id": "win-drivers",
        "group": "strategy",
        "title": "What Wins Games",
        "description": (
            "The 15 Impect stats most linked to winning in League Two history — "
            "why each matters, live table, Port Vale highlighted."
        ),
        "href": "/win-drivers",
        "icon": "🏆",
        "accent": "#f5c518",
        "tags": ["League Two", "Impect", "Table"],
        "roles": ("admin",),
        "api_prefixes": ("/win-drivers", "/api/win-drivers"),
        "router": "win_drivers",
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
        "id": "presentations",
        "group": "presentations",
        "title": "Presentations",
        "description": (
            "Personal decks — strategy reports, origin story, window review. "
            "Off the daily rail; admin only."
        ),
        "href": "/presentations",
        "icon": "🎬",
        "accent": "#a78bfa",
        "tags": ["Personal", "Decks"],
        "roles": ("admin",),
        "api_prefixes": ("/presentations",),
        "router": "presentations",
    },
    {
        "id": "league-two-strategy",
        "group": "presentations",
        "title": "League Two Strategy Report",
        "description": (
            "Season strategy slides — promotion point benchmarks, league "
            "context, and targets (21/22–25/26)."
        ),
        "href": "/strategy",
        "icon": "📈",
        "accent": "#a78bfa",
        "tags": ["League Two", "Strategy"],
        "roles": ("admin",),
        "api_prefixes": ("/strategy", "/strategy/assets"),
        "router": "scouting",
        "sidebar": False,
    },
    {
        "id": "players-strategy",
        "group": "presentations",
        "title": "Players Strategy Report",
        "description": (
            "Dressing-room presentation — punchy promotion standards. Build "
            "here, then Present or Export PDF."
        ),
        "href": "/players-strategy",
        "icon": "🗣️",
        "accent": "#a78bfa",
        "tags": ["League Two", "Players", "Presentation"],
        "roles": ("admin",),
        "api_prefixes": ("/players-strategy",),
        "router": "scouting",
        "sidebar": False,
    },
    {
        "id": "players-strategy-staff",
        "group": "presentations",
        "title": "Staff Strategy Report",
        "description": (
            "Staff edition of Project Promotion — same benchmarks, fuller detail."
        ),
        "href": "/players-strategy-staff",
        "icon": "📋",
        "accent": "#a78bfa",
        "tags": ["League Two", "Staff", "Presentation"],
        "roles": ("admin",),
        "api_prefixes": ("/players-strategy-staff",),
        "router": "scouting",
        "sidebar": False,
    },
    {
        "id": "players-strategy-values",
        "group": "presentations",
        "title": "Values Report",
        "description": (
            "Our values and non-negotiables — culture first, before the numbers."
        ),
        "href": "/players-strategy-values",
        "icon": "🧭",
        "accent": "#a78bfa",
        "tags": ["League Two", "Values", "Presentation"],
        "roles": ("admin",),
        "api_prefixes": ("/players-strategy-values",),
        "router": "scouting",
        "sidebar": False,
    },
    {
        "id": "hub-origin",
        "group": "presentations",
        "title": "Hub Origin Story",
        "description": (
            "Why we built the Analysis Hub, how Player Comparison on leave started it, "
            "and what’s live — Present deck for staff briefings."
        ),
        "href": "/hub-origin",
        "icon": "✦",
        "accent": "#a78bfa",
        "tags": ["Story", "Presentation"],
        "roles": ("admin",),
        "api_prefixes": ("/hub-origin",),
        "router": "hub_origin",
        "sidebar": False,
    },
    {
        "id": "window-review",
        "group": "presentations",
        "title": "Summer Window Review",
        "description": (
            "End of 26/27 summer window — ins and outs, average age change, "
            "and squad depth in primary positions. Present or PDF."
        ),
        "href": "/window-review",
        "icon": "🔁",
        "accent": "#a78bfa",
        "tags": ["Squad", "Transfers", "Presentation"],
        "roles": ("admin",),
        "api_prefixes": ("/window-review", "/api/wysiwyg-export-pdf"),
        "router": "window_review",
        "sidebar": False,
    },
    {
        "id": "efl-transfer-report",
        "group": "presentations",
        "title": "EFL Transfer Report",
        "description": (
            "Summer 2026 window — every League One, League Two, National League "
            "and Scottish Prem club: who they signed and who they released. Present or PDF."
        ),
        "href": "/efl-transfer-report",
        "icon": "🔁",
        "accent": "#a78bfa",
        "tags": ["Transfers", "EFL", "Presentation"],
        "roles": ("admin",),
        "api_prefixes": ("/efl-transfer-report", "/api/efl-transfer-report", "/api/wysiwyg-export-pdf"),
        "router": "efl_transfer_report",
        "sidebar": False,
    },
]


# Live staff sidebar this week — everything else is comingSoon on live.
# Staging (HUB_ENV=staging) reveals all tools so you can break/fix safely.
LIVE_ESSENTIAL_IDS = frozenset(
    {
        # Analysis
        "pre-match",
        "set-piece-pre-match",
        "player-cards",
        "match-day-countdown",
        "xg-chance-analysis",
        "blocks-analysis",
        # Recruitment
        "who-to-scout",
        "watch-list",
        # Live once scouts have personal logins, so the shared board and its
        # notes carry real names rather than one team account.
        "player-pipelines",
        "scoutable-teams",
        # Scouts
        "fixture-planner",
        "played-fixtures",
        "scouting-address",
        "scout-summary",
        "scouts-calendar",
        # Strategy
        "availability-tracker",
        "league-two-progress",
        "win-drivers",
        "club-strategy",
        # Presentations (one rail link; decks live on the gallery page)
        "presentations",
    }
)


def _is_staging_env() -> bool:
    import os

    return os.getenv("HUB_ENV", "").strip().lower() == "staging"


def is_app_live(app_id: str) -> bool:
    """True when staff can actually open this tool from the rail right now."""
    return _is_staging_env() or str(app_id) in LIVE_ESSENTIAL_IDS


def presentation_decks() -> list[dict[str, Any]]:
    """Personal Present / PDF decks — listed on /presentations, not the daily rail."""
    return [
        app
        for app in APPS
        if app.get("group") == "presentations" and app["id"] != "presentations"
    ]


def apps_for_role(role: str, *, include_hidden: bool = False) -> list[dict[str, Any]]:
    role_key = (role or "analysis").strip().lower()
    if role_key == "admin":
        apps = list(APPS)
    else:
        apps = [app for app in APPS if role_key in tuple(app.get("roles") or ())]
    if include_hidden:
        return apps
    return [app for app in apps if app.get("sidebar") is not False]


def public_app_payload(app: dict[str, Any], *, reveal_all: bool = False) -> dict[str, Any]:
    """Sidebar-safe fields (no internal router keys required by the client)."""
    coming_soon = bool(app.get("comingSoon"))
    if not reveal_all and app["id"] not in LIVE_ESSENTIAL_IDS:
        coming_soon = True
    payload = {
        "id": app["id"],
        "group": app["group"],
        "title": app["title"],
        "description": app.get("description") or "",
        "href": app["href"],
        "icon": app.get("icon") or "◆",
        "accent": app.get("accent") or "#3d8bfd",
        "tags": list(app.get("tags") or []),
    }
    if coming_soon:
        payload["comingSoon"] = True
        payload["note"] = str(app.get("note") or "Coming soon")
    return payload


# Shared assets + feedback + WYSIWYG always allowed for any signed-in account.
SHARED_PATH_PREFIXES: tuple[str, ...] = (
    "/api/feedback",
    "/api/apps",
    "/api/player-photo",
    "/api/wysiwyg-export-pdf",
    "/api/wysiwyg-export-png-zip",
    "/static/",
    "/standalone/",
)

# Recruitment/scouting accounts also need the hub home widgets they can see, the
# player dossier behind Watch list rows, and the daily snapshot scores come from.
RECRUITMENT_SUPPORT_PREFIXES: tuple[str, ...] = (
    "/api/home/",
    "/api/hub-snapshots/",
    "/api/players",
    "/api/player/",
    "/player/",
    "/api/team-badge",
)
RECRUITMENT_GROUPS = frozenset({"recruitment", "scouts"})


def role_path_prefixes(role: str) -> tuple[str, ...]:
    """Paths a non-admin account may hit. Derived from APPS — no parallel list."""
    role_key = str(role or "").strip().lower()
    prefixes: list[str] = []
    needs_recruitment_support = False
    for app in APPS:
        if role_key not in tuple(app.get("roles") or ()):
            continue
        for prefix in app.get("api_prefixes") or ():
            prefixes.append(str(prefix))
        if app.get("group") in RECRUITMENT_GROUPS:
            needs_recruitment_support = True
    prefixes.extend(SHARED_PATH_PREFIXES)
    if needs_recruitment_support:
        prefixes.extend(RECRUITMENT_SUPPORT_PREFIXES)
    # Dedupe, longest-first so more specific prefixes win in mental model
    # (middleware uses startswith either way).
    uniq = sorted(set(prefixes), key=lambda p: (-len(p), p))
    return tuple(uniq)


def analysis_path_prefixes() -> tuple[str, ...]:
    return role_path_prefixes("analysis")


def required_sidebar_titles() -> list[str]:
    return [str(app["title"]) for app in APPS if app.get("sidebar") is not False]


def essential_sidebar_titles() -> list[str]:
    return [
        str(app["title"])
        for app in APPS
        if app["id"] in LIVE_ESSENTIAL_IDS and app.get("sidebar") is not False
    ]


def manifest_payload(*, role: str = "admin") -> dict[str, Any]:
    reveal_all = _is_staging_env()
    apps = [public_app_payload(app, reveal_all=reveal_all) for app in apps_for_role(role)]
    groups_used = {app["group"] for app in apps}
    groups = [g for g in APP_GROUPS if g["id"] in groups_used]
    product = "Port Vale Staging" if reveal_all else "Port Vale Live"
    return {
        "groups": groups,
        "apps": apps,
        "titles": [app["title"] for app in apps if not app.get("comingSoon")],
        "all_titles": [app["title"] for app in apps],
        "staging": reveal_all,
        "product": product,
        "product_id": "staging" if reveal_all else "live",
    }
