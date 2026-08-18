#!/usr/bin/env python3
"""One-time Microsoft Graph mail setup for the live Fixture Planner.

Creates a refresh token so the hub can send assignment emails over HTTPS
(from sam.baker@port-vale.co.uk) without SMTP.

Prerequisites (once, in Azure Portal):
  1. App registrations → New registration → "Port Vale Fixture Planner Mail"
  2. Supported account types: single tenant (Port Vale only)
  3. API permissions → Microsoft Graph → Delegated → Mail.Send → Grant admin consent if prompted
  4. Authentication → Advanced settings → Allow public client flows: Yes
  5. Copy the Application (client) ID

Then run:
  MS_GRAPH_CLIENT_ID=your-client-id python scripts/setup-graph-mail-token.py

Sign in as sam.baker@port-vale.co.uk when prompted, then paste the printed
.env lines onto the live server at /opt/port-vale-analysis/.env and restart the hub.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

TENANT = os.getenv("MS_GRAPH_TENANT_ID", "dfcffac1-cb4c-4a43-9ad5-aaf3672ee5d8")
CLIENT_ID = os.getenv("MS_GRAPH_CLIENT_ID", "").strip()
SCOPE = "https://graph.microsoft.com/Mail.Send offline_access openid profile"


def post_form(url: str, data: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read().decode("utf-8"))


def main() -> int:
    if not CLIENT_ID:
        print("Set MS_GRAPH_CLIENT_ID to your Azure app client ID first.", file=sys.stderr)
        return 1

    device = post_form(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/devicecode",
        {"client_id": CLIENT_ID, "scope": SCOPE},
    )
    print("\n=== Sign in once as sam.baker@port-vale.co.uk ===")
    print(device.get("message", ""))
    print()

    interval = max(2, int(device.get("interval") or 5))
    device_code = str(device.get("device_code") or "")
    deadline = time.time() + int(device.get("expires_in") or 900)

    while time.time() < deadline:
        time.sleep(interval)
        try:
            token = post_form(
                f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": CLIENT_ID,
                    "device_code": device_code,
                },
            )
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            error = str(payload.get("error") or "")
            if error in {"authorization_pending", "slow_down"}:
                continue
            print(f"Auth failed: {payload}", file=sys.stderr)
            return 1

        refresh = str(token.get("refresh_token") or "").strip()
        if not refresh:
            print(f"No refresh token in response: {token}", file=sys.stderr)
            return 1

        print("\n=== Add these lines to /opt/port-vale-analysis/.env on the live server ===\n")
        print(f"FIXTURE_EMAIL_TRANSPORT=graph_delegated")
        print(f"MS_GRAPH_TENANT_ID={TENANT}")
        print(f"MS_GRAPH_CLIENT_ID={CLIENT_ID}")
        print(f"MS_GRAPH_REFRESH_TOKEN={refresh}")
        print(f"FIXTURE_EMAIL_FROM=sam.baker@port-vale.co.uk")
        print(f"FIXTURE_EMAIL_FROM_NAME=Sam Baker · Port Vale Recruitment")
        print("\nThen restart the hub:")
        print("  cd /opt/port-vale-analysis && bash deploy/deploy-ip.sh")
        return 0

    print("Device login timed out.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
