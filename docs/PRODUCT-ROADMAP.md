# Product roadmap — Port Vale Analysis Hub → sellable platform

Order matters. Do not skip ahead to SaaS before reliability and a second club work.

## Where to build

| Where | When |
|--------|------|
| **Local Mac** (`~/impect-football-dashboard` only) | Day-to-day code. Default. |
| **Staging** `http://178.128.161.215:8080/` | Real-server check (auth, Docker, Impect `.env`). Safe for staff. |
| **Live** `http://178.128.161.215/` | Staff / boss / customer. Promote only when you explicitly ask. |

Build locally → verify on staging → promote to live after smoke PASS.

## Phase A — Stop the bleeding (current)

1. Staging on the same droplet ($0 extra) — `deploy-staging.sh`
2. Deploy rules — live only via `deploy-live.sh` when asked; smoke must PASS
3. Suggest / comment button on every tool (private inbox via `POST /api/feedback`)
4. Sidebar hygiene — retired tools stay out of `app/apps_manifest.py`

## Phase B — Clean the product

- Kill dead / duplicate tools; clear Analysis → Recruitment → Scouts → Strategy story
- Reliability pass on home, fixture planner, post-match, pre-match, blocks
- Coaching PDFs via WYSIWYG screenshot path (not html2canvas as primary)
- Admin inbox UI for suggestions (read/triage without SSH)

## Phase C — Second club (first real sell)

- Club config profile (name, Impect/FotMob IDs, competition, badge, branding)
- Strip Port Vale literals from core paths
- Second login / role allowlists
- Sell as **managed hub**, not self-serve SaaS

## Phase D — Real SaaS (later)

- Multi-tenant isolation, billing, onboarding — only after Phase C is quiet for weeks

## Explicitly not now

- App Platform / new paid host stack
- Building day-to-day on the live droplet
- Shared threaded staff comments (inbox first)
