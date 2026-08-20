# Port Vale Analysis Hub

## Live website

**URL:** http://178.128.161.215/  
**Staging (verify):** http://178.128.161.215:8080/  
**Hosting:** Existing DigitalOcean droplet (no App Platform)

Product roadmap: [`docs/PRODUCT-ROADMAP.md`](docs/PRODUCT-ROADMAP.md).

## Where to build

- **Local Mac** (`~/impect-football-dashboard`) — write code here. Default.
- **Staging** — `bash ~/impect-football-dashboard/deploy-staging.sh` then check `:8080`. Does not touch live staff traffic.
- **Live** — only when the user explicitly asks: `bash ~/impect-football-dashboard/deploy-live.sh`

Never mark complete after only local changes. Never debug by shipping half-fixes straight to live while staff are on it.

## ONE live deploy path

```bash
bash ~/impect-football-dashboard/deploy-live.sh
```

Or double-click **`Deploy to Website.command`**.

That pushes GitHub **and** updates the droplet immediately. Details: `deploy/HOW-WE-DEPLOY.md`.

Staging:

```bash
bash ~/impect-football-dashboard/deploy-staging.sh
```

## Repo path (mandatory)

- Edit and deploy **only** from `~/impect-football-dashboard`.
- **Refuse** Desktop / Downloads copies (`~/Desktop/impect-football-dashboard`, etc.) — they drift from live and wipe tools after deploy.
- Never rsync-only or silent partial copies from Desktop.

## App registry (source of truth)

All hub tools live in **`app/apps_manifest.py`** (`id`, `group`, `title`, `href`, `roles`, `api_prefixes`, `router`).

That drives:

- Left rail via **`GET /api/apps`** (hub loads this on boot; `standalone/apps.js` is fallback only)
- Route registration via **`app/register_apps.py`** (`register_all_app_routes`)
- Analysis auth allowlists in **`app/auth.py`** (derived from manifest roles/prefixes)
- Smoke sidebar titles in **`deploy/smoke-live.sh`** (reads `/api/apps`)

Retired tools must be removed from the manifest (and kept in hub `RETIRED_APP_IDS` if needed) so they cannot reappear after refresh.

### Adding a new tool

1. Add the app to `app/apps_manifest.py`
2. Wire its registrar in `app/register_apps.py` (`_ROUTER_REGISTRARS`)
3. Auth + sidebar + smoke pick it up automatically
4. Verify on staging, then (when asked) commit + `deploy-live.sh` + smoke PASS

Startup **fails** if a manifest `router` is missing from the registry — fix before shipping.

## Suggest / feedback

Every tool page loads `/static/hub-feedback.js` (floating Suggest). Posts to `POST /api/feedback` with page URL + username. Hub home also has Suggestion / bug.

## Definition of done (live)

1. Edit in `~/impect-football-dashboard`
2. **Commit** changes
3. Prefer staging verify first
4. Run **`bash ~/impect-football-dashboard/deploy-live.sh`** only when asked to promote
5. **`deploy/smoke-live.sh` must PASS**
6. Verify at http://178.128.161.215/ (hard refresh)

Never mark done if a sidebar title is missing from smoke / `/api/apps`.
Never mark done after local-only changes.
