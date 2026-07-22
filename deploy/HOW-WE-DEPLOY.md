# How we deploy (ONE path)

**Live site:** http://178.128.161.215/

## Do this

**Double-click** `Deploy to Website.command`  
or in Terminal:

```bash
bash ~/impect-football-dashboard/deploy-live.sh
```

That script always:
1. Pushes `main` to GitHub (source of truth)
2. Syncs this Mac → the droplet
3. Rebuilds/restarts the hub

## Do not

- Run random deploy scripts from `~` (home folder) — you must be in the project, or use the full path above
- Use DigitalOcean Console `update-live.sh` unless Mac deploy is broken (it pulls GitHub only)
- Rely on rsync-only without a git push — the next GitHub deploy will overwrite you

## Why we kept rolling back

Fixes were rsynced live but **not pushed to GitHub**. Later a GitHub-based update put the **old** committed code back on the server.

## Check it worked

Open http://178.128.161.215/scouting-address → hard refresh (**Cmd+Shift+R**) → footer should say **Build: webpage-v12** (or newer).
