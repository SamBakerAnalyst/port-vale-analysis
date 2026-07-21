# Port Vale Analysis Hub

Internal football analysis platform for Port Vale FC — pre-match prep, scouting, squad planning, fixture management, post-match reports, and strategy tools. All served from a single FastAPI backend with a hub landing page at `/`.

## Quick start (local development)

```bash
cd impect-football-dashboard

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your Impect username/password

./start.sh
# Or background: ./restart.sh
```

Open **http://127.0.0.1:8000** in Chrome.

## Project structure

```
impect-football-dashboard/
├── app/                        # FastAPI backend
│   ├── main.py                 # App entry + route registration
│   ├── post_match/             # Post-match report (slides, xG race, PDF export)
│   ├── pre_match.py            # Pre-match report
│   ├── scouting.py             # Player search + hub routes
│   └── …                       # Other tool modules
├── standalone/                 # Hub HTML + tool pages (apps.js registry)
├── static/                     # JS/CSS assets served at /static
├── templates/                  # Player comparison studio
├── strategy-reports/           # League Two strategy slides
├── data/cache/                 # Shared team data (fixtures, availability, etc.)
├── Dockerfile
└── docker-compose.yml
```

## Tools (17 live + 1 coming soon)

Registered in `standalone/apps.js`:

| Department | Tools |
|---|---|
| **Analysis** | Pre-Match Handout, Pre-Match Report, xG Chance Analysis, Post-Match Report |
| **Recruitment** | Player Comparison, Player Search, Squad Balance, Squad Planner |
| **Scouts** | Fixture Planner, Scouting Address, Scout Summary, Scout Calendar |
| **Strategy** | Squad Comparison, Squad Availability, Club Strategy, League Two Strategy |

All tools run on **one server** (port 8000). Post-match is at `/post-match` with APIs under `/api/post-match/…`.

## Environment variables

See `.env.example`. Key variables:

| Variable | Purpose |
|---|---|
| `IMPECT_USERNAME` / `IMPECT_PASSWORD` | Impect API credentials (required) |
| `DATA_ROOT` | Persistent data directory (default: `./data`) |
| `HOST` / `PORT` | Server bind address (`0.0.0.0` for team/LAN access) |

## Docker

```bash
cp .env.example .env   # add credentials
docker compose up --build
```

Hub (including post-match): http://localhost:8000

## Deploying for the team

**Full step-by-step guide:** [DEPLOY.md](DEPLOY.md)

1. Push to private GitHub
2. Create DigitalOcean droplet (London, 4 GB ~£20/mo)
3. Club IT: DNS `analysis.port-vale.co.uk` → server IP
4. On server: `bash deploy/setup-server.sh` then `bash deploy/deploy.sh`
5. Share **https://analysis.port-vale.co.uk** with the team

Production uses Docker + Caddy (automatic HTTPS). Optional basic auth until M365 login.

## Migrating existing local data

```bash
mkdir -p data/cache
cp -R ~/.cache/impect-fixture-planner data/cache/ 2>/dev/null || true
cp -R ~/.cache/impect-availability data/cache/ 2>/dev/null || true
cp -R ~/.cache/impect-scouting data/cache/ 2>/dev/null || true
cp -R ~/.cache/impect-club-strategy data/cache/ 2>/dev/null || true
```

## Adding a new tool

1. Add HTML page in `standalone/`
2. Register in `standalone/apps.js`
3. Add FastAPI routes in `app/` and register in `app/main.py`

## Tests

```bash
source .venv/bin/activate
pip install pytest
python -m pytest tests/ -q
```
