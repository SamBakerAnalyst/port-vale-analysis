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
