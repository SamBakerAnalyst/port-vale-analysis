# Deploy to your existing droplet (no App Platform)

**You already pay for the droplet.** This wires `git push` → automatic deploy. No new services.

Live site: **http://178.128.161.215/**

---

## How it works

```
Edit code → git push origin main → GitHub Actions → droplet rebuilds → team sees changes
```

Double-click **`Deploy to Website.command`** or push from Terminal.

---

## One-time setup (~15 minutes)

### Step 1 — Create a deploy key (Mac Terminal)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/portvale_deploy -N "" -C "github-deploy"
cat ~/.ssh/portvale_deploy.pub
```

Copy the **public** key line (starts with `ssh-ed25519`).

### Step 2 — Add the key to your droplet

1. [DigitalOcean](https://cloud.digitalocean.com) → **Droplets** → **PORT-VALE-ANALYSIS**
2. Click **Console** (web terminal)
3. Run:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo 'PASTE_YOUR_PUBLIC_KEY_HERE' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### Step 3 — Add GitHub secrets

1. Open https://github.com/SamBakerAnalyst/port-vale-analysis/settings/secrets/actions
2. **New repository secret** for each:

| Secret name | Value |
|-------------|--------|
| `DEPLOY_HOST` | `178.128.161.215` |
| `DEPLOY_USER` | `root` |
| `DEPLOY_SSH_KEY` | Contents of `~/.ssh/portvale_deploy` (private key, entire file) |

To copy private key:

```bash
cat ~/.ssh/portvale_deploy
```

### Step 4 — Push this repo

```bash
cd ~/impect-football-dashboard
git add .
git commit -m "GitHub Actions deploy to droplet"
git push origin main
```

1. Open https://github.com/SamBakerAnalyst/port-vale-analysis/actions
2. Watch **Deploy to production** — should go green in ~5–10 min
3. Open http://178.128.161.215/ and hard refresh

---

## Day-to-day

```bash
git push origin main
```

Or double-click **`Deploy to Website.command`**.

Wait ~5 minutes. Site updates. **No SSH. No rsync. No DigitalOcean console.**

---

## If deploy fails

1. GitHub → **Actions** → click the failed run → read the log
2. Common fixes:
   - Wrong `DEPLOY_SSH_KEY` → re-paste private key in GitHub secrets
   - Missing `.env` on server → copy from your Mac once via DO Console
   - Build error → check Actions log for Python/Docker errors

### Manual fallback (DO Console)

```bash
cd /opt/port-vale-analysis
bash deploy/update-live.sh
```

---

## Cost

**£0 extra.** Same droplet you already pay for.

---

## App Platform

**Not needed.** Ignore `.do/app.yaml` and `deploy/APP-PLATFORM.md` unless you change your mind later.
