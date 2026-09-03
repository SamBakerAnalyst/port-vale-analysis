# Port Vale Analysis Hub

## Products

| Product | URL | Purpose |
|---|---|---|
| **Port Vale Live** | http://178.128.161.215/ | Staff / boss. Promote only when asked. |
| **Port Vale Staging** | http://178.128.161.215:8080/ | Safe break/fix. Does not touch Live. |

Hosting: existing DigitalOcean droplet (no App Platform).

Naming source of truth: [`docs/ENVIRONMENTS.md`](docs/ENVIRONMENTS.md).  
Product roadmap: [`docs/PRODUCT-ROADMAP.md`](docs/PRODUCT-ROADMAP.md).

## Where to build

- **Local Mac** (`~/impect-football-dashboard`) — write code here. Default.
- **Port Vale Staging** — **always** after local work: `bash ~/impect-football-dashboard/deploy-staging.sh` then open the Staging URL. Does not touch Live. Do not wait to be asked.
- **Port Vale Live** — only when the user explicitly asks: `bash ~/impect-football-dashboard/deploy-live.sh`

Never mark complete after only local changes. Never debug by shipping half-fixes straight to Live while staff are on it.

## ONE Live deploy path

```bash
bash ~/impect-football-dashboard/deploy-live.sh
```

Or double-click **`Deploy to Website.command`**.

That pushes GitHub **and** updates Port Vale Live immediately. Details: `deploy/HOW-WE-DEPLOY.md`.

Staging:

```bash
bash ~/impect-football-dashboard/deploy-staging.sh
```

## Repo path (mandatory)

- Edit and deploy **only** from `~/impect-football-dashboard`.
- **Refuse** Desktop / Downloads copies (`~/Desktop/impect-football-dashboard`, etc.) — they drift from Live and wipe tools after deploy.
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
4. Verify on **Port Vale Staging**, then (when asked) commit + `deploy-live.sh` + smoke PASS

Startup **fails** if a manifest `router` is missing from the registry — fix before shipping.

## Suggest / feedback

Every tool page loads `/static/hub-feedback.js` (floating Suggest). Posts to `POST /api/feedback` with page URL + username. Hub home also has Suggestion / bug.

## Definition of done (Live)

1. Edit in `~/impect-football-dashboard`
2. **Always** run **`bash ~/impect-football-dashboard/deploy-staging.sh`** (do not wait to be asked)
3. **Commit** changes when asked
4. Run **`bash ~/impect-football-dashboard/deploy-live.sh`** only when asked to promote
5. **`deploy/smoke-live.sh` must PASS**
6. Verify at **Port Vale Live** (hard refresh)

Never mark done if a sidebar title is missing from smoke / `/api/apps`.  
Never mark done after local-only changes.  
Never treat a Staging deploy as “done for staff.”
