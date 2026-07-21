# Deploy Port Vale Analysis Hub online

Get the hub live at **https://analysis.port-vale.co.uk** (or your chosen subdomain).

Estimated time: **~2 hours** (mostly waiting on DNS + club IT).

---

## What you need

| Item | Who |
|---|---|
| **DigitalOcean account** (or similar VPS) | You |
| **DNS A record** → server IP | Club IT |
| **Impect API credentials** | You (already have) |
| **Private GitHub repo** (recommended) | You |

**Cost:** ~£20/month (4 GB droplet, London).

---

## Step 1 — Push code to GitHub

On your Mac:

```bash
cd ~/impect-football-dashboard
git init   # if not already
git add .
git commit -m "Port Vale analysis hub — production ready"
gh repo create port-vale-analysis --private --source=. --push
```

Or create a private repo on GitHub and push manually.

---

## Step 2 — Create the server

1. Go to [DigitalOcean](https://cloud.digitalocean.com) → **Create Droplet**
2. **Region:** London
3. **Image:** Ubuntu 24.04
4. **Size:** Basic → 4 GB RAM / 2 vCPU (~$24/mo)
5. **Authentication:** SSH key (add your Mac’s public key)
6. **Hostname:** `port-vale-analysis`
7. Create

Note the **IP address** (e.g. `164.92.xxx.xxx`).

---

## Step 3 — DNS (club IT)

Ask IT to add:

| Type | Name | Value |
|---|---|---|
| **A** | `analysis` | `YOUR_DROPLET_IP` |

Result: `analysis.port-vale.co.uk` → your server.

DNS can take 5–60 minutes to propagate.

---

## Step 4 — Server setup (one time)

SSH in:

```bash
ssh root@YOUR_DROPLET_IP
```

Clone and bootstrap:

```bash
git clone https://github.com/YOUR_ORG/port-vale-analysis.git /opt/port-vale-analysis
cd /opt/port-vale-analysis
bash deploy/setup-server.sh
```

---

## Step 5 — Configure environment

On the server:

```bash
cd /opt/port-vale-analysis
cp .env.production.example .env
nano .env
```

Fill in:

- `SITE_DOMAIN=analysis.port-vale.co.uk`
- `IMPECT_USERNAME` / `IMPECT_PASSWORD`
- SMTP settings if you use fixture emails

**Optional basic auth** (recommended until M365 login):

```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'ChooseATeamPassword'
```

Add to `.env`:

```
BASIC_AUTH_USER=portvale
BASIC_AUTH_HASH=<paste hash from above>
```

---

## Step 6 — Deploy

```bash
cd /opt/port-vale-analysis
bash deploy/deploy.sh
```

Caddy automatically gets an HTTPS certificate from Let’s Encrypt.

Open **https://analysis.port-vale.co.uk** — you should see the hub.

---

## Step 7 — Migrate your local data (optional)

From your Mac, copy fixture assignments, availability data, etc.:

```bash
cd ~/impect-football-dashboard
bash deploy/migrate-local-data.sh root@YOUR_DROPLET_IP
```

---

## Step 8 — Share with the team

Send colleagues:

> **Port Vale Analysis Hub**  
> https://analysis.port-vale.co.uk  
> Sign in with the team username/password (if basic auth enabled).  
> Use Chrome. Sign in with Microsoft coming soon.

---

## Updating after changes

On the server:

```bash
cd /opt/port-vale-analysis
git pull
bash deploy/deploy.sh
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| **502 / site not loading** | `docker compose -f docker-compose.prod.yml logs hub` |
| **Certificate error** | DNS not propagated yet — wait or check A record |
| **Impect errors** | Check `.env` credentials on server |
| **Empty fixture data** | Run `migrate-local-data.sh` from your Mac |

---

## Next: Microsoft 365 login (Phase 3)

Basic auth works for launch. Phase 3 replaces it with **Sign in with Microsoft** so staff use their `@port-vale.co.uk` accounts.
