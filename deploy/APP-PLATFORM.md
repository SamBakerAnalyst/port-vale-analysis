# Deploy on DigitalOcean App Platform

**Goal:** `git push` → website updates. No SSH. No rsync. No droplet console.

Live URL will be something like `https://port-vale-analysis-xxxxx.ondigitalocean.app`  
Then add `https://analysis.port-vale.co.uk` when IT sets DNS.

---

## How it works

```
Edit code → git push origin main → App Platform rebuilds → team sees changes
```

Agents and you only need to **push to GitHub**. DigitalOcean deploys automatically.

---

## One-time setup (~30 minutes)

### Step 1 — Push this repo to GitHub

From your Mac Terminal:

```bash
cd ~/impect-football-dashboard
git add .
git commit -m "App Platform setup"
git push origin main
```

Repo: https://github.com/SamBakerAnalyst/port-vale-analysis

### Step 2 — Create the App Platform app

1. Log in to [DigitalOcean](https://cloud.digitalocean.com)
2. **Create** → **Apps** → **Create App**
3. Choose **GitHub** → authorize → select **port-vale-analysis** → branch **main**
4. DigitalOcean should detect **`.do/app.yaml`** — confirm settings:
   - Region: **London**
   - Plan: **Professional M** (4 GB RAM)
   - Dockerfile build
5. **Environment variables** — add secrets (copy from your server `.env` or local `.env`):

| Variable | Required |
|----------|----------|
| `IMPECT_USERNAME` | Yes |
| `IMPECT_PASSWORD` | Yes |
| `TEAM_PASSWORD` | Yes (staff login) |
| `HUB_AUTH_SECRET` | Yes (random 32+ char string) |
| `TEAM_USERNAME` | `PortVale` (already in app.yaml) |
| SMTP vars | Only if you use fixture emails |

6. Click **Create Resources** / **Deploy**
7. Wait ~5–10 minutes for first build

### Step 3 — Test the new URL

App Platform gives you a URL like:

`https://port-vale-analysis-xxxxx.ondigitalocean.app`

- Open it → should redirect to `/login`
- Sign in: **PortVale** / your team password
- Click through Analysis, Recruitment, Scouts, Strategy tools

### Step 4 — Custom domain (when IT is ready)

1. App Platform → your app → **Settings** → **Domains**
2. Add `analysis.port-vale.co.uk`
3. IT points DNS **A record** or **CNAME** as shown in the DO dashboard
4. HTTPS is automatic (no Caddy needed)

### Step 5 — Turn off the old droplet

Once the App Platform URL works for your team:

1. Update bookmarks from `http://178.128.161.215/` to the new URL
2. **Destroy** the old droplet (saves ~£25/mo duplicate cost)

---

## Day-to-day workflow (you + agents)

```bash
cd ~/impect-football-dashboard
# ... make changes ...
git add .
git commit -m "Describe the fix"
git push origin main
```

Wait 3–8 minutes. Hard refresh the live site (`Cmd+Shift+R`).

**Or double-click:** `Deploy to Website.command` (commits + pushes for you).

---

## Important: saved data on deploy

App Platform **does not have persistent disks** like your droplet did.

| Data | What happens |
|------|----------------|
| Impect API caches | Rebuild automatically (first load slower after deploy) |
| Scout assignments, feedback logs, uploaded photos | **Reset on each deploy** until we add DO Spaces storage |

**For now:** avoid deploying during active scout assignment weeks, or we add Spaces storage next (keeps assignments across deploys).

---

## Cost

| | |
|---|---|
| App Platform Professional M (4 GB) | ~£48/mo |
| Old droplet (delete after migration) | save ~£25/mo |
| Custom domain | £0 |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Build fails | App Platform → **Activity** → view build log |
| App unhealthy | Check `IMPECT_USERNAME` / `IMPECT_PASSWORD` secrets |
| Login 404 | Old deploy — push latest `main` again |
| Tool slow after deploy | Normal — Impect caches rebuilding |

---

## What we removed

- SSH / rsync / `deploy-live.sh` for daily use
- Caddy container (App Platform handles HTTPS)
- "Restart server" / port 8000 (not relevant on App Platform)

Old droplet scripts remain in `deploy/` for reference during migration only.
