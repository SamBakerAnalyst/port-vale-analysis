#!/usr/bin/env python3
"""Fold Transfermarkt squad loans into the Transfer Centre report.

Watch list / Who To Scout flags read this file. Academy loans (Ramell Carter
at Worthing) were missing from the BBC/retained-list scrape, so they never
flagged. This writes them in as `kind: loan` on the matching club.
"""

from __future__ import annotations

import html
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.transfer_status import _clubs_match, name_keys  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "build_efl_transfer_report", ROOT / "scripts" / "build_efl_transfer_report.py"
)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MOD)
same_player = _MOD.same_player

REPORT = ROOT / "data" / "efl-transfer-report-2026.json"
LOANS = ROOT / "data" / "transfermarkt-loans-2026.json"
CORE_LEAGUES = frozenset({"league-one", "league-two", "national-league", "scottish-prem"})


def _slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return text or "club"


def _row(player: str, parent: str) -> dict[str, str]:
    return {
        "player": html.unescape(player).strip(),
        "other": html.unescape(parent).strip(),
        "kind": "loan",
        "fee": "Loan",
    }


def _already_has(team: dict, player: str) -> bool:
    if not str(player or "").strip():
        return True
    for bucket in ("signed", "left"):
        for row in team.get(bucket) or []:
            existing = str(row.get("player") or "")
            if set(name_keys(player)) & set(name_keys(existing)):
                return True
            if same_player(player, existing):
                return True
    return False


def _find_core_team(report: dict, club: str) -> dict | None:
    for league in report.get("leagues") or []:
        if str(league.get("id") or "") not in CORE_LEAGUES:
            continue
        for team in league.get("teams") or []:
            if _clubs_match(team.get("name"), club):
                return team
    return None


def _loan_count(report: dict) -> int:
    return sum(
        1
        for league in report.get("leagues") or []
        for team in league.get("teams") or []
        for signing in team.get("signed") or []
        if str(signing.get("kind") or "").lower() == "loan"
    )


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    snapshot = json.loads(LOANS.read_text(encoding="utf-8"))
    clubs = snapshot.get("clubs") or {}
    before = _loan_count(report)

    unmatched: dict[str, list[dict[str, str]]] = {}

    for club, rows in clubs.items():
        team = _find_core_team(report, club)
        if team is None:
            unmatched[club] = list(rows or [])
            continue
        signed = list(team.get("signed") or [])
        team["signed"] = signed
        for raw in rows or []:
            name = html.unescape(str(raw.get("name") or "")).strip()
            parent = html.unescape(str(raw.get("from") or "")).strip()
            if not name or not parent:
                continue
            if _already_has(team, name):
                continue
            signed.append(_row(name, parent))
        team["signed_count"] = len(signed)

    extra_rows: dict[str, list[dict[str, str]]] = {}
    for club, rows in unmatched.items():
        keep = []
        for raw in rows:
            name = html.unescape(str(raw.get("name") or "")).strip()
            parent = html.unescape(str(raw.get("from") or "")).strip()
            if name and parent:
                keep.append({"name": name, "from": parent})
        if not keep:
            continue
        existing = next((key for key in extra_rows if _clubs_match(key, club)), None)
        extra_rows.setdefault(existing or club, []).extend(keep)

    report["leagues"] = [
        league
        for league in report.get("leagues") or []
        if str(league.get("id") or "") != "irish-prem"
    ]

    extra_teams = []
    for club, rows in sorted(extra_rows.items()):
        unique: list[dict[str, str]] = []
        seen_team = {"signed": unique, "left": []}
        for raw in rows:
            if _already_has(seen_team, raw["name"]):
                continue
            unique.append(_row(raw["name"], raw["from"]))
        if not unique:
            continue
        extra_teams.append(
            {
                "id": _slug(club),
                "name": club.replace("Football Club", "FC").strip(),
                "signed": unique,
                "released": [],
                "left": [],
                "signed_count": len(unique),
                "released_count": 0,
                "left_count": 0,
            }
        )
    if extra_teams:
        report["leagues"].append(
            {
                "id": "irish-prem",
                "name": "Irish Prem",
                "teams": extra_teams,
            }
        )
        print("Irish Prem clubs added:", [team["name"] for team in extra_teams])

    sources = list(report.get("sources") or [])
    note = "Transfermarkt current-squad on-loan badges (academy loans the BBC scrape missed)"
    if note not in sources:
        sources.append(note)
    report["sources"] = sources
    report["updated"] = date.today().isoformat()

    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Loan signings: {before} -> {_loan_count(report)} in {REPORT}")


if __name__ == "__main__":
    main()
