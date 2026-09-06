/**
 * Hub app registry FALLBACK (offline / API failure).
 * Source of truth: app/apps_manifest.py via GET /api/apps.
 */
window.IMPECT_APP_GROUPS = [
  {
    "id": "analysis",
    "title": "Analysis",
    "subtitle": "Pre-match prep and post-match review",
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
  },
  {
    "id": "presentations",
    "title": "Presentations",
    "subtitle": "Personal decks — off the daily rail",
    "icon": "🎬",
    "accent": "#a78bfa"
  }
];

window.IMPECT_APPS = [
  {
    "id": "pre-match",
    "group": "analysis",
    "title": "Pre-Match Report",
    "description": "Opponent prep — full slide deck plus editable Two pager handout.",
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
    "id": "post-match",
    "group": "analysis",
    "title": "Post-Match Report",
    "description": "Full post-match slide deck — shots, progression, crosses, duels, set plays, xG race and PDF export.",
    "href": "/post-match",
    "icon": "📊",
    "accent": "#34d399",
    "tags": [
      "Match day"
    ],
    "comingSoon": true,
    "note": "Coming soon"
  },
  {
    "id": "match-day-countdown",
    "group": "analysis",
    "title": "Match Day Countdown",
    "description": "Dead-simple dressing-room clock — next opponent badges, countdown to kick-off, and the next match-day timing (analysis, warm-up, etc.).",
    "href": "/match-day-countdown",
    "icon": "⏰",
    "accent": "#f5c518",
    "tags": [
      "Match day",
      "Clock"
    ]
  },
  {
    "id": "match-story",
    "group": "analysis",
    "title": "Match Story",
    "description": "15-minute blocks, presses, duels and the xG race. For / against and combine games.",
    "href": "/match-dashboards?view=story",
    "icon": "⏱️",
    "accent": "#34d399",
    "tags": [
      "Match",
      "Momentum"
    ],
    "comingSoon": true,
    "note": "Coming soon"
  },
  {
    "id": "ball-progression",
    "group": "analysis",
    "title": "Ball Progression",
    "description": "Team packing KPIs and player progression. For / against and combine games.",
    "href": "/match-dashboards?view=progression",
    "icon": "⏩",
    "accent": "#22c55e",
    "tags": [
      "In possession"
    ],
    "comingSoon": true,
    "note": "Coming soon"
  },
  {
    "id": "crosses-dashboard",
    "group": "analysis",
    "title": "Crosses",
    "description": "Cross origins, flank packing and threat. For / against and combine games.",
    "href": "/match-dashboards?view=crosses",
    "icon": "➕",
    "accent": "#14b8a6",
    "tags": [
      "In possession"
    ],
    "comingSoon": true,
    "note": "Coming soon"
  },
  {
    "id": "shots-xg",
    "group": "analysis",
    "title": "Shots & xG",
    "description": "Shot map coloured by chance rating, plus game state, half/manpower and player xG tags. For / against and combine games.",
    "href": "/match-dashboards?view=shots",
    "icon": "🎯",
    "accent": "#38bdf8",
    "tags": [
      "xG",
      "Shots",
      "Game state"
    ],
    "comingSoon": true,
    "note": "Coming soon"
  },
  {
    "id": "duels-pressing",
    "group": "analysis",
    "title": "Duels & Pressing",
    "description": "Team duels, press height and player duel rows. For / against and combine games.",
    "href": "/match-dashboards?view=duels",
    "icon": "🛡️",
    "accent": "#f97316",
    "tags": [
      "Out of possession"
    ],
    "comingSoon": true,
    "note": "Coming soon"
  },
  {
    "id": "xg-chance-analysis",
    "group": "analysis",
    "title": "xG Chance Analysis",
    "description": "Break down shot quality by chance rating, game state, half, and manpower. Season or single match.",
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
    "id": "goal-involvement",
    "group": "analysis",
    "title": "Goal Involvement",
    "description": "Coaches split 10 points on every goal we score or concede. Averages, disagreement flags, and player season totals.",
    "href": "/goal-involvement",
    "icon": "🔟",
    "accent": "#eab308",
    "tags": [
      "Goals",
      "Coaches",
      "Match day"
    ],
    "comingSoon": true,
    "note": "Coming soon"
  },
  {
    "id": "blocks-analysis",
    "group": "analysis",
    "title": "Blocks Analysis",
    "description": "Nine blocks of five league games — result colours, editable Silver targets, live block KPIs, and a 2-page A4 match report PDF.",
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
    ],
    "comingSoon": true,
    "note": "Coming soon"
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
    ],
    "comingSoon": true,
    "note": "Coming soon"
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
    ],
    "comingSoon": true,
    "note": "Coming soon"
  },
  {
    "id": "watch-list",
    "group": "recruitment",
    "title": "Watch list",
    "description": "Players spotted on Who To Scout / Stand outs — review here, then promote into Player Pipelines when scouts should progress them.",
    "href": "/watch-list",
    "icon": "👀",
    "accent": "#38bdf8",
    "tags": [
      "Watch list",
      "Scouting",
      "Targets"
    ]
  },
  {
    "id": "player-pipelines",
    "group": "recruitment",
    "title": "Player Pipelines",
    "description": "Shared recruitment progression board — promote from the Watch list, then drag between Data identified, Video scouted, Live scouted, Gone / turned us down, and Not the right fit. Notes and tags are visible to the whole team.",
    "href": "/player-pipelines",
    "icon": "📌",
    "accent": "#a78bfa",
    "tags": [
      "Pipelines",
      "Scouting",
      "Targets",
      "Notes"
    ]
  },
  {
    "id": "scoutable-teams",
    "group": "recruitment",
    "title": "Scoutable Teams",
    "description": "Monday-style league boards — open any club, see player data scores, and move prospects straight onto Player Pipelines.",
    "href": "/scoutable-teams",
    "icon": "🏟️",
    "accent": "#34d399",
    "tags": [
      "Scouting",
      "Clubs",
      "Pipelines"
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
    ],
    "comingSoon": true,
    "note": "Coming soon"
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
    "description": "UK stadium map for EFL, National League, NL North/South, Scottish Prem/Champ and more, plus a Germany tab for Bundesliga / 2. Bundesliga.",
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
    ],
    "comingSoon": true,
    "note": "Coming soon"
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
    "id": "meeting-front-pages",
    "group": "scouts",
    "title": "Meeting Front Pages",
    "description": "Scout video title cards — identity page plus one PNG per PV profile (Wide Creator, Goal Threat, etc.). Download a pack.",
    "href": "/meeting-front-pages",
    "icon": "🎬",
    "accent": "#f97316",
    "tags": [
      "Scouts",
      "Video",
      "PNG"
    ],
    "comingSoon": true,
    "note": "Coming soon"
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
    ],
    "comingSoon": true,
    "note": "Coming soon"
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
    "id": "league-two-progress",
    "group": "strategy",
    "title": "Season Progress Report",
    "description": "Live promotion pace, Impect style stats, and a Present / PDF board pack versus auto / play-off / champions.",
    "href": "/strategy-tracker",
    "icon": "📉",
    "accent": "#f5c518",
    "tags": [
      "League Two",
      "Progress",
      "Pace"
    ]
  },
  {
    "id": "win-drivers",
    "group": "strategy",
    "title": "What Wins Games",
    "description": "The 15 Impect stats most linked to winning in League Two history — why each matters, live table, Port Vale highlighted.",
    "href": "/win-drivers",
    "icon": "🏆",
    "accent": "#f5c518",
    "tags": [
      "League Two",
      "Impect",
      "Table"
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
    "id": "presentations",
    "group": "presentations",
    "title": "Presentations",
    "description": "Personal decks — strategy reports, origin story, window review. Off the daily rail; admin only.",
    "href": "/presentations",
    "icon": "🎬",
    "accent": "#a78bfa",
    "tags": [
      "Personal",
      "Decks"
    ]
  },
  {
    "id": "league-two-strategy",
    "group": "presentations",
    "title": "League Two Strategy Report",
    "description": "Season strategy slides — promotion point benchmarks, league context, and targets (21/22–25/26).",
    "href": "/strategy",
    "icon": "📈",
    "accent": "#a78bfa",
    "tags": [
      "League Two",
      "Strategy"
    ],
    "comingSoon": true,
    "note": "Coming soon",
    "sidebar": false
  },
  {
    "id": "players-strategy",
    "group": "presentations",
    "title": "Players Strategy Report",
    "description": "Dressing-room presentation — punchy promotion standards. Build here, then Present or Export PDF.",
    "href": "/players-strategy",
    "icon": "🗣️",
    "accent": "#a78bfa",
    "tags": [
      "League Two",
      "Players",
      "Presentation"
    ],
    "comingSoon": true,
    "note": "Coming soon",
    "sidebar": false
  },
  {
    "id": "players-strategy-staff",
    "group": "presentations",
    "title": "Staff Strategy Report",
    "description": "Staff edition of Project Promotion — same benchmarks, fuller detail.",
    "href": "/players-strategy-staff",
    "icon": "📋",
    "accent": "#a78bfa",
    "tags": [
      "League Two",
      "Staff",
      "Presentation"
    ],
    "comingSoon": true,
    "note": "Coming soon",
    "sidebar": false
  },
  {
    "id": "players-strategy-values",
    "group": "presentations",
    "title": "Values Report",
    "description": "Our values and non-negotiables — culture first, before the numbers.",
    "href": "/players-strategy-values",
    "icon": "🧭",
    "accent": "#a78bfa",
    "tags": [
      "League Two",
      "Values",
      "Presentation"
    ],
    "comingSoon": true,
    "note": "Coming soon",
    "sidebar": false
  },
  {
    "id": "hub-origin",
    "group": "presentations",
    "title": "Hub Origin Story",
    "description": "Why we built the Analysis Hub, how Player Comparison on leave started it, and what’s live — Present deck for staff briefings.",
    "href": "/hub-origin",
    "icon": "✦",
    "accent": "#a78bfa",
    "tags": [
      "Story",
      "Presentation"
    ],
    "comingSoon": true,
    "note": "Coming soon",
    "sidebar": false
  },
  {
    "id": "window-review",
    "group": "presentations",
    "title": "Summer Window Review",
    "description": "End of 26/27 summer window — ins and outs, average age change, and squad depth in primary positions. Present or PDF.",
    "href": "/window-review",
    "icon": "🔁",
    "accent": "#a78bfa",
    "tags": [
      "Squad",
      "Transfers",
      "Presentation"
    ],
    "comingSoon": true,
    "note": "Coming soon",
    "sidebar": false
  },
  {
    "id": "efl-transfer-report",
    "group": "presentations",
    "title": "EFL Transfer Report",
    "description": "Summer 2026 window — every League One, League Two, National League and Scottish Prem club: who they signed and who they released. Present or PDF.",
    "href": "/efl-transfer-report",
    "icon": "🔁",
    "accent": "#a78bfa",
    "tags": ["Transfers", "EFL", "Presentation"],
    "sidebar": false
  }
];
