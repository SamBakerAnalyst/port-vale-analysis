# Port Vale product environments

Stop talking in ports. Use the product names.

| Product name | Who uses it | URL | Deploy |
|---|---|---|---|
| **Port Vale Live** | Boss + staff | http://178.128.161.215/ | `bash ~/impect-football-dashboard/deploy-live.sh` |
| **Port Vale Staging** | You / agents only | http://178.128.161.215:8080/ | `bash ~/impect-football-dashboard/deploy-staging.sh` |

## Rules

1. Code only in `~/impect-football-dashboard` (never Desktop / Downloads copies).
2. Build → **Port Vale Staging** first.
3. Promote to **Port Vale Live** only when you explicitly ask.
4. **Iron rule:** nothing on Port Vale Live that is missing from Port Vale Staging.

Ports (`:80` / `:8080`) are implementation detail for engineers — not product names.
