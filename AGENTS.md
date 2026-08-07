# Port Vale Analysis Hub

## Live website

**URL:** http://178.128.161.215/  
**Hosting:** Existing DigitalOcean droplet (no App Platform)

## ONE deploy path

```bash
bash ~/impect-football-dashboard/deploy-live.sh
```

Or double-click **`Deploy to Website.command`**.

That pushes GitHub **and** updates the droplet immediately. Details: `deploy/HOW-WE-DEPLOY.md`.

**Never** mark complete after only local changes.

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

### Adding a new tool

1. Add the app to `app/apps_manifest.py`
2. Wire its registrar in `app/register_apps.py` (`_ROUTER_REGISTRARS`)
3. Auth + sidebar + smoke pick it up automatically
4. Commit, run `deploy-live.sh`, confirm smoke PASS

Startup **fails** if a manifest `router` is missing from the registry — fix before shipping.

## Definition of done

1. Edit in `~/impect-football-dashboard`
2. **Commit** changes
3. Run **`bash ~/impect-football-dashboard/deploy-live.sh`**
4. **`deploy/smoke-live.sh` must PASS** (full sidebar titles from `/api/apps` + key routes)
5. Verify at http://178.128.161.215/ (hard refresh)

Never mark done if a sidebar title is missing from smoke / `/api/apps`.
Never mark done after local-only changes.
