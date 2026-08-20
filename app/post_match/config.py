from __future__ import annotations

import os

PORT_VALE_SQUAD_ID = int(os.getenv("PORT_VALE_SQUAD_ID", "882"))

# League Two 26/27 — primary season for post-match reports.
DEFAULT_ITERATION_ID = int(os.getenv("DEFAULT_ITERATION_ID", "2120"))
DEFAULT_SEASON_LABEL = os.getenv("DEFAULT_SEASON_LABEL", "26/27").strip() or "26/27"

# Wolves vs Port Vale — EFL Cup R1, Fri 7 Aug 2026 (19:45 BST).
# Report unlocks once Impect marks the match available after full time.
DEFAULT_MATCH_ID = int(os.getenv("DEFAULT_MATCH_ID", "285444"))

# Competitions merged into the post-match match bar (league + cups).
# Add FA Cup / EFL Trophy iteration ids here when Impect publishes them.
POST_MATCH_COMPETITIONS: list[dict[str, str | int]] = [
    {
        "iterationId": 2120,
        "label": "League Two",
        "shortLabel": "LG2",
        "season": "26/27",
    },
    {
        "iterationId": 2227,
        "label": "EFL Cup",
        "shortLabel": "Cup",
        "season": "26/27",
    },
]
