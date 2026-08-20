# How we deploy

**Live site:** http://178.128.161.215/  
**Staging (verify only):** http://178.128.161.215:8080/

## Live (staff)

**Double-click** `Deploy to Website.command`  
or in Terminal:

```bash
bash ~/impect-football-dashboard/deploy-live.sh
```

That script always:
1. Pushes `main` to GitHub (source of truth)
2. Syncs this Mac → the droplet
3. Rebuilds/restarts the hub
4. Runs `deploy/smoke-live.sh`

## Staging (does not touch live)

```bash
bash ~/impect-football-dashboard/deploy-staging.sh
```

Rebuilds a separate Docker project on port **8080**. Staff on `:80` stay uninterrupted.

## Do not

- Run random deploy scripts from `~` (home folder) — you must be in the project, or use the full path above
- Use DigitalOcean Console `update-live.sh` unless Mac deploy is broken (it pulls GitHub only)
- Rely on rsync-only without a git push — the next GitHub deploy will overwrite you
- Debug by shipping half-fixes straight to live while staff are using it — use staging first

## Why we kept rolling back

Fixes were rsynced live but **not pushed to GitHub**. Later a GitHub-based update put the **old** committed code back on the server.

## Check it worked

Open http://178.128.161.215/ → hard refresh (**Cmd+Shift+R**) → yellow build stamp updates. Run `bash deploy/smoke-live.sh`.
