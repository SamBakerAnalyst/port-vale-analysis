#!/usr/bin/env python3
"""Snapshot Transfermarkt on-loan badges for clubs we scout.

The droplet is blocked by Transfermarkt, so live lookups from Staging/Live
come back empty. This file is built on the Mac and shipped in the image,
same pattern as the EFL transfer report.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.efl_transfer_report import load_report  # noqa: E402
from app.opponent_photos import transfermarkt_loan_ins  # noqa: E402

OUT = ROOT / "data" / "transfermarkt-loans-2026.json"

# Impect spellings that are not the report's club name.
EXTRA_CLUBS = (
    "FC Worthing",
    "Worthing FC",
    "Shelbourne FC",
    "Dundalk FC",
    "Shamrock Rovers",
    "St Patrick's Athletic",
    "St. Patrick's Athletic",
    "Bohemian Football Club",
    "Bohemians",
    "Derry City",
    "Sligo Rovers",
    "FC Waterford",
    "Waterford FC",
    "Galway United",
    "FC Galway United",
    "Cork City",
    "Drogheda United",
)


def club_names() -> list[str]:
    names: set[str] = set()
    report = load_report()
    for league in report.get("leagues") or []:
        for team in league.get("teams") or []:
            name = str(team.get("name") or "").strip()
            if name:
                names.add(name)
    names.update(EXTRA_CLUBS)
    return sorted(names)


def fetch_one(club: str) -> tuple[str, list[dict[str, str]]]:
    try:
        raw = transfermarkt_loan_ins(club, squad_only=True) or {}
    except Exception as exc:  # noqa: BLE001 — one club must not kill the snapshot
        print(f"  fail {club}: {exc}", file=sys.stderr)
        return club, []
    rows = [
        {"name": str(row.get("name") or "").strip(), "from": str(row.get("on_loan_from") or "").strip()}
        for row in raw.values()
        if str(row.get("name") or "").strip() and str(row.get("on_loan_from") or "").strip()
    ]
    return club, rows


def main() -> None:
    clubs = club_names()
    print(f"Fetching squad loan badges for {len(clubs)} clubs…")
    payload: dict[str, list[dict[str, str]]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_one, club): club for club in clubs}
        for fut in as_completed(futures):
            club, rows = fut.result()
            payload[club] = rows
            print(f"  {club}: {len(rows)}")
    out = {
        "updated": date.today().isoformat(),
        "clubs": payload,
        "club_count": len(payload),
        "loan_count": sum(len(rows) for rows in payload.values()),
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({out['loan_count']} loans across {out['club_count']} clubs)")


if __name__ == "__main__":
    main()
