/**
 * Hub app registry FALLBACK (offline / API failure).
 *
 * Source of truth: app/apps_manifest.py via GET /api/apps.
 * Hub prefers /api/apps on boot; this file keeps the left rail alive if the API fails.
 * When adding a tool: update apps_manifest.py (+ register_apps.py), then regenerate
 * this file OR keep titles in sync manually — never only edit one side.
 */
window.IMPECT_APP_GROUPS = [
  {
    "id": "analysis",
    "title": "Analysis",
    "subtitle": "Pre-match prep, handouts, and post-match review",
    "icon": "📊",
    "accent": "#34d399"
  },
  {
    "id": "recruitment",
    "title": "Recruitment",
    "subtitle": "Search, compare, and plan the squad",
    "icon": "🔍",
    "accent": "#3d8bfd"
  },
  {
    "id": "scouts",
    "title": "Scouts",
    "subtitle": "Fixtures, coverage, calendars, travel map, and scout reports",
    "icon": "🗓️",
    "accent": "#f97316"
  },
  {
    "id": "strategy",
    "title": "Strategy",
    "subtitle": "Squad reviews, benchmarks, and league context",
    "icon": "📈",
    "accent": "#f5c518"
  }
];

window.IMPECT_APPS = [
  {
    "id": "pre-match-handout",
    "group": "analysis",
    "title": "Pre-Match Handout",
    "description": "A4 keynote handout for the dressing room — predicted XI, previous lineups, form, rankings, and player profiles. PDF export.",
    "href": "/pre-match-handout",
    "icon": "📄",
    "accent": "#f97316",
    "tags": [
      "Opponent",
      "A4",
      "Export"
    ]
  },
  {
    "id": "pre-match",
    "group": "analysis",
    "title": "Pre-Match Report",
    "description": "Automated opponent prep — squad overview, form, team metrics, and more.",
    "href": "/pre-match",
    "icon": "📋",
    "accent": "#fbbf24",
    "tags": [
      "Opponent",
      "Prep"
    ]
  },
  {
    "id": "set-piece-pre-match",
    "group": "analysis",
    "title": "Set Piece Pre-Match",
    "description": "Dedicated set-play prep — squad heights, first-contact maps, corner/FK KPIs, and aerial threats.",
    "href": "/set-piece-pre-match",
    "icon": "🚩",
    "accent": "#14b8a6",
    "tags": [
      "Opponent",
      "Set pieces"
    ]
  },
  {
    "id": "player-cards",
    "group": "analysis",
    "title": "Player Cards",
    "description": "Blank opponent squad cards for performance analysis — club site headshots, Impect height and foot, 26/27 fixtures.",
    "href": "/player-cards",
    "icon": "🪪",
    "accent": "#e52320",
    "tags": [
      "Opponent",
      "Squad",
      "Cards"
    ]
  },
  {
    "id": "xg-chance-analysis",
    "group": "analysis",
    "title": "xG Chance Analysis",
    "description": "Break down shot quality by chance rating, game state, half, and manpower. See which players take high vs low xG shots — season or single match.",
    "href": "/xg-chance-analysis",
    "icon": "🎯",
    "accent": "#38bdf8",
    "tags": [
      "xG",
      "Shots",
      "Game state"
    ]
  },
  {
    "id": "post-match",
    "group": "analysis",
    "title": "Post-Match Report",
    "description": "Live post-match data slides — xG race, momentum, zones, player bars, and PDF export.",
    "href": "/post-match",
    "icon": "📊",
    "accent": "#34d399",
    "tags": [
      "Match day",
      "Export"
    ]
  },
  {
    "id": "blocks-analysis",
    "group": "analysis",
    "title": "Blocks Analysis",
    "description": "Nine blocks of five league games — result colours, editable Silver targets, live block KPIs, and PNG export.",
    "href": "/blocks-analysis",
    "icon": "🧱",
    "accent": "#f5c518",
    "tags": [
      "League Two",
      "Blocks",
      "Live"
    ]
  },
  {
    "id": "schedule",
    "group": "analysis",
    "title": "Schedule",
    "description": "First-team calendar — Port Vale fixtures from FotMob, training vs regen days, report times, and custom events.",
    "href": "/schedule",
    "icon": "📆",
    "accent": "#22c55e",
    "tags": [
      "Training",
      "Fixtures",
      "Calendar"
    ]
  },
  {
    "id": "player-comparison",
    "group": "recruitment",
    "title": "Player Comparison Tool",
    "description": "Search players, add them to a comparison, and build radar and pizza charts side by side.",
    "href": "/studio",
    "icon": "⚽",
    "accent": "#56d4ff",
    "tags": [
      "Charts",
      "Profiles"
    ]
  },
  {
    "id": "who-to-scout",
    "group": "recruitment",
    "title": "Who To Scout",
    "description": "Top profile scorers by league and position — adjust profile weights, filter by age, height, club and minutes.",
    "href": "/who-to-scout",
    "icon": "🎯",
    "accent": "#34d399",
    "tags": [
      "Scouting",
      "Profiles",
      "Leagues"
    ]
  },
  {
    "id": "player-search",
    "group": "recruitment",
    "title": "Player Search Dashboard",
    "description": "Profile-weighted scouting lists by position and league. Rank, filter, export Excel or PDF.",
    "href": "/scouting",
    "icon": "🔍",
    "accent": "#3d8bfd",
    "tags": [
      "Scouting",
      "Search"
    ]
  },
  {
    "id": "squad-balance",
    "group": "recruitment",
    "title": "Squad Balance",
    "description": "Recruitment squad builder — search players per position, paste headshots, squad-average profile scores.",
    "href": "/squad-balance",
    "icon": "⚖️",
    "accent": "#f5c518",
    "tags": [
      "Squad",
      "Balance"
    ]
  },
  {
    "id": "squad-planner",
    "group": "recruitment",
    "title": "Squad Planner",
    "description": "Plan current and shadow squads by formation. Search players, tag with age labels, and track potential signings.",
    "href": "/squad-planner",
    "icon": "📋",
    "accent": "#3d8bfd",
    "tags": [
      "Squad",
      "Planning"
    ]
  },
  {
    "id": "fixture-planner",
    "group": "scouts",
    "title": "Fixture Planner",
    "description": "Upcoming fixtures only — assign scouts Live or Video across the leagues. Feeds Scout Summary.",
    "href": "/fixture-planner",
    "icon": "📅",
    "accent": "#34d399",
    "tags": [
      "Fixtures",
      "Upcoming"
    ]
  },
  {
    "id": "played-fixtures",
    "group": "scouts",
    "title": "Played Fixtures",
    "description": "Games that have taken place — keep LIVE ownership, pick up VIDEO coverage, players and reports.",
    "href": "/played-fixtures",
    "icon": "🎬",
    "accent": "#fbbf24",
    "tags": [
      "Fixtures",
      "Played",
      "Video"
    ]
  },
  {
    "id": "scouting-address",
    "group": "scouts",
    "title": "Scouting Address Tool",
    "description": "UK stadium map for EFL, National League, NL North/South, Scottish Prem/Champ and more.",
    "href": "/scouting-address",
    "icon": "🗺️",
    "accent": "#38bdf8",
    "tags": [
      "Scouts",
      "Map",
      "Travel"
    ]
  },
  {
    "id": "scout-summary-report",
    "group": "scouts",
    "title": "Generate Scout Summary",
    "description": "Pick a date range, preview KPIs, league charts, player reports and team coverage, then export the PDF.",
    "href": "/scout-summary-report",
    "icon": "📄",
    "accent": "#38bdf8",
    "tags": [
      "Scouts",
      "Reports",
      "PDF"
    ]
  },
  {
    "id": "scout-summary",
    "group": "scouts",
    "title": "Scout Summary",
    "description": "Who has covered what — pulls from Fixture Planner and Played Fixtures (live vs video, by scout and league).",
    "href": "/scout-summary",
    "icon": "📊",
    "accent": "#a78bfa",
    "tags": [
      "Scouts",
      "Coverage"
    ]
  },
  {
    "id": "scouts-calendar",
    "group": "scouts",
    "title": "Scouts Calendar",
    "description": "Live calendar of assigned fixtures. Scouts see upcoming live games — auto-refreshes every 30 seconds.",
    "href": "/scouts-calendar",
    "icon": "🗓️",
    "accent": "#f97316",
    "tags": [
      "Scouts",
      "Live"
    ]
  },
  {
    "id": "squad-comparison",
    "group": "strategy",
    "title": "Squad Comparison",
    "description": "Internal squad reviews — compare Port Vale players by PV profile percentiles. Live-updates through the season.",
    "href": "/squad-review",
    "icon": "👥",
    "accent": "#f5c518",
    "tags": [
      "Squad",
      "Internal"
    ]
  },
  {
    "id": "availability-tracker",
    "group": "strategy",
    "title": "Squad Availability",
    "description": "Training and match availability tracker — log injuries, training attendance, and auto-fill minutes from Impect.",
    "href": "/availability-tracker",
    "icon": "🏥",
    "accent": "#ef4444",
    "tags": [
      "Squad",
      "Injuries",
      "Training"
    ]
  },
  {
    "id": "club-strategy",
    "group": "strategy",
    "title": "Club Strategy",
    "description": "League Two benchmarks — standings, shooting, xG/xPoints, and first-goal analysis with live season tracking.",
    "href": "/club-strategy",
    "icon": "🎯",
    "accent": "#f5c518",
    "tags": [
      "League Two",
      "FGS",
      "xG"
    ]
  },
  {
    "id": "league-two-strategy",
    "group": "strategy",
    "title": "League Two Strategy Report",
    "description": "Season strategy slides — promotion point benchmarks, league context, and targets (21/22–25/26).",
    "href": "/strategy",
    "icon": "📈",
    "accent": "#f5c518",
    "tags": [
      "League Two",
      "Strategy"
    ]
  },
  {
    "id": "players-strategy",
    "group": "strategy",
    "title": "Players Strategy Report",
    "description": "Dressing-room presentation — punchy promotion standards. Build here, then Present or Export PDF.",
    "href": "/players-strategy",
    "icon": "🗣️",
    "accent": "#f5c518",
    "tags": [
      "League Two",
      "Players",
      "Presentation"
    ]
  },
  {
    "id": "league-two-progress",
    "group": "strategy",
    "title": "Season Progress Report",
    "description": "Live promotion pace for every key metric, goals by time, and season targets versus auto / play-off / champions.",
    "href": "/strategy-tracker",
    "icon": "📉",
    "accent": "#fbbf24",
    "tags": [
      "League Two",
      "Progress",
      "Pace"
    ]
  }
];
