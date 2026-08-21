# Product roadmap — Port Vale Analysis Hub → sellable platform

**North star right now:** the tools that are live must be rock-solid. Looking silly in front of the boss (or a buyer) because something is broken is worse than having fewer tools.

Order matters. Do not unlock new live tools, chase SaaS, or expand the surface area until the live set is quiet.

## Where to build

| Where | When |
|--------|------|
| **Local Mac** (`~/impect-football-dashboard` only) | Day-to-day code. Default. |
| **Port Vale Staging** http://178.128.161.215:8080/ | Break / fix / polish safely. Staff stay off this. |
| **Port Vale Live** http://178.128.161.215/ | Boss + team. Promote only when you explicitly ask. |

Flow: build locally → verify on **Port Vale Staging** → promote to **Port Vale Live** only after `deploy/smoke-live.sh` PASS.

**Iron rule:** nothing on Port Vale Live that is missing from Port Vale Staging. If that happens, Staging is stale — run `deploy-staging.sh` first. Never “fix forward” by shipping only to Live.

Naming: [`docs/ENVIRONMENTS.md`](ENVIRONMENTS.md).

## Live product surface (sell this)

These are the only tools staff should treat as “ready.” Everything else is Coming soon until it is proven.

| Group | Live tools |
|--------|------------|
| Analysis | Pre-Match Report, Set Piece Pre-Match, Player Cards, xG Chance Analysis, Blocks Analysis |
| Recruitment | Who To Scout, Player Pipelines |
| Scouts | Fixture Planner, Played Fixtures, Scouting Address Tool, Scout Summary, Scouts Calendar |
| Strategy | Squad Availability, Season Progress Report |

Plus hub home (fixtures, schedule widgets, League Two season).

Source of truth for what is open on live: `LIVE_ESSENTIAL_IDS` in `app/apps_manifest.py`.

## Phase A — Stop the bleeding (done)

1. Staging on the same droplet (`deploy-staging.sh`) — $0 extra
2. Live only via `deploy-live.sh` when asked; smoke must PASS
3. Suggest / feedback on tools (`POST /api/feedback`)
4. Sidebar hygiene — retired tools stay out of `app/apps_manifest.py`
5. Live essentials vs Coming soon rail (open tools first; clear Soon badge)

## Phase B — Reliability of what is live (current priority)

**Goal:** weeks go by without emergency fixes; boss can open any live tool without you hovering.

### B1 — Harden the 14 + hub home

For each live tool, treat “done” as:

- Opens every time after login (no blank / stuck Loading)
- Correct season / competition (**League Two 26/27**) and club data — first league game played; do not stick on 25/26
- No console/server 500s on the happy path staff actually use
- Deploy does not regress it (`smoke-live.sh` still PASS; add tool-specific checks when a bug bites twice)

Priority order (highest embarrassment risk first):

1. Hub home (widgets, fixtures, schedule)
2. Fixture Planner + Played Fixtures
3. Pre-Match Report + Set Piece Pre-Match
4. Scout Summary + Scouts Calendar + Scouting Address Tool
5. Player Cards, xG Chance Analysis, Blocks Analysis
6. Who To Scout + Player Pipelines
7. Squad Availability + Season Progress Report

### B2 — Polish for selling

Once B1 is quiet on a tool:

- Clear empty / error states (“what do I click?”)
- Consistent labels and dates staff already understand
- Coaching PDFs via WYSIWYG screenshot path when a report must leave the building (not html2canvas as the primary WhatsApp/boss path)
- Short “how this tool is used” note only where people still get lost

**Sellable pitch = this live set working every Monday.** Not “we have 30 half-built tools.”

### B3 — Ops that protect you

- Never build day-to-day on live; use staging
- Do not promote a WIP tool just because it is “almost done”
- Admin inbox UI for suggestions (read/triage without SSH) — after B1 is under control
- Kill dead / duplicate entries that confuse the story; keep Analysis → Recruitment → Scouts → Strategy clear

## Phase B-spare — Other tools (nights / weekends only)

Improve on staging. **Do not put on live** until you would bet your job they will not break the hub or look unfinished.

Examples (Coming soon today): Post-Match, Match Story, Ball Progression, Crosses, Shots & xG, Duels & Pressing, Schedule, Player Comparison, Player Search, Squad Balance / Planner, Generate Scout Summary, Squad Comparison, Club Strategy, strategy decks, match dashboards WIP.

Promote rule for spare-time tools:

1. Works on staging for real staff workflows
2. Smoke / page checks green
3. You explicitly ask to unlock it in `LIVE_ESSENTIAL_IDS` and run `deploy-live.sh`
4. If it wobbles in the first week, pull it back to Coming soon immediately

## Phase C — Second club (first real sell)

Only after Phase B is quiet for a stretch (live set boring in a good way).

- Club config profile (name, Impect/FotMob IDs, competition, badge, branding)
- Strip Port Vale literals from core paths
- Second login / role allowlists
- Sell as **managed hub**, not self-serve SaaS

## Phase D — Real SaaS (later)

Multi-tenant isolation, billing, onboarding — only after Phase C is quiet for weeks.

## Explicitly not now

- App Platform / new paid host stack
- Day-to-day coding against the live droplet
- Unlocking Coming soon tools “because they’re useful” before they are boringly reliable
- Shared threaded staff comments (inbox first)
- Expanding the live sidebar while Phase B still has flaky essentials
