# Port Vale product environments

Stop talking in ports. Use the product names.

| Product name | Who uses it | URL | Deploy |
|---|---|---|---|
| **Port Vale Live** | Boss + staff | http://178.128.161.215/ | `bash ~/impect-football-dashboard/deploy-live.sh` |
| **Port Vale Staging** | You / agents only | http://178.128.161.215:8080/ | `bash ~/impect-football-dashboard/deploy-staging.sh` |
| **LMS Sports AI Consultancy** | Demos / blank build | https://lmsc.sportsanalysis.ai/ | `bash ~/impect-football-dashboard/deploy-lms-demo.sh` |

## Rules

1. Code only in `~/impect-football-dashboard` (never Desktop / Downloads copies).
2. Build → **Port Vale Staging** first.
3. Promote to **Port Vale Live** only when you explicitly ask.
4. **Iron rule:** nothing on Port Vale Live that is missing from Port Vale Staging.
5. **LMS Sports AI Consultancy** is a blank duplicate of the same hub (separate login, empty data, no Port Vale branding). It does not touch Live or Staging. This is the demo product to show and build into. Never put LMS on `pvfc.sportsanalysis.ai` or the staff IP. LMS Docker service must not be named `hub`.

Ports (`:80` / `:8080` / `:8090`) are implementation detail for engineers — not product names.
