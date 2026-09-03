# How we deploy

Product names (not ports): see [`docs/ENVIRONMENTS.md`](../docs/ENVIRONMENTS.md).

| Product | URL |
|---|---|
| **Port Vale Live** | http://178.128.161.215/ |
| **Port Vale Staging** | http://178.128.161.215:8080/ |

## Port Vale Live (staff)

**Double-click** `Deploy to Website.command`  
or in Terminal:

```bash
bash ~/impect-football-dashboard/deploy-live.sh
```

That script always:
1. Pushes `main` to GitHub (source of truth)
2. Syncs this Mac → the droplet
3. Rebuilds/restarts the Live hub
4. Runs `deploy/smoke-live.sh`

## Port Vale Staging (does not touch Live)

```bash
bash ~/impect-football-dashboard/deploy-staging.sh
```

Rebuilds the Staging Docker project. Staff on Port Vale Live stay uninterrupted.

## Putting Live on HTTPS (not done yet)

Live currently serves plain HTTP on the bare IP (`deploy/Caddyfile.ip`, `auto_https off`).
That is fine inside the building but not for links we send to phones — the Goal
Involvement coach scoring links carry a signed token in the URL.

`deploy/Caddyfile.tls` + `deploy/docker-compose.tls.yml` are ready for the switch.
They serve `SITE_DOMAIN` over HTTPS **and** keep the bare IP on `:80`, so nobody's
bookmark breaks. Caddy gets and renews the certificate itself; the `caddy-data`
volume keeps it across restarts, which matters because Let's Encrypt rate limits.

Order of work:

1. **DNS** — an `A` record for `analysis.port-vale.co.uk` → `178.128.161.215`.
   Club IT owns the `port-vale.co.uk` zone. If it sits behind Cloudflare it must be
   "DNS only" (grey cloud), or Caddy cannot complete the ACME challenge.
2. Confirm it resolves: `dig +short analysis.port-vale.co.uk`
3. Open the port on the droplet: `ufw allow 443/tcp`
4. Put `SITE_DOMAIN` and `CADDY_EMAIL` in the server `.env`
5. **Validate before reloading Live**, on the droplet:
   ```bash
   docker run --rm -e SITE_DOMAIN -e CADDY_EMAIL \
     -v "$PWD/deploy/Caddyfile.tls:/etc/caddy/Caddyfile:ro" \
     caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
   ```
6. Bring it up with `-f deploy/docker-compose.tls.yml`, then check both
   `https://analysis.port-vale.co.uk` and `http://178.128.161.215` still answer.

Do this at a quiet time — it replaces the Caddy container that fronts Live.

## Do not

- Run random deploy scripts from `~` (home folder) — you must be in the project, or use the full path above
- Use DigitalOcean Console `update-live.sh` unless Mac deploy is broken (it pulls GitHub only)
- Rely on rsync-only without a git push — the next GitHub deploy will overwrite you
- Debug by shipping half-fixes straight to Port Vale Live while staff are using it — use Port Vale Staging first
- Put something on Live that is missing from Staging

## Why we kept rolling back

Fixes were rsynced to Live but **not pushed to GitHub**. Later a GitHub-based update put the **old** committed code back on the server.

## Check it worked

Open **Port Vale Live** → hard refresh (**Cmd+Shift+R**) → yellow stamp reads **Port Vale Live**.  
Open **Port Vale Staging** → blue stamp reads **Port Vale Staging**.  
Run `bash deploy/smoke-live.sh`.

## Release notes (homepage)

Before a **big** Staging → Live promote, add a short entry at the top of
[`standalone/app-changelog.json`](../standalone/app-changelog.json):

```json
{
  "date": "YYYY-MM-DD",
  "title": "Short title",
  "detail": "What staff will notice.",
  "tag": "New"
}
```

Tags that work well: `New`, `Fix`, `Hub`, `Scouts`, `Recruitment`, `Strategy`.  
Staff see these under **Release notes** on the Home dashboard after login.

If Live goes down or a bad ship goes out, reset the joke counter by editing
`last_broke` in [`standalone/hub-uptime-joke.json`](../standalone/hub-uptime-joke.json).
