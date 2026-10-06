#!/usr/bin/env python3
"""Build data/player-careers.json — every club/season each player has minutes for.

Run from the repo root after build_shadow_teams.py has refreshed the raw cache:

    .venv/bin/python scripts/build_player_careers.py

Reads only data/cache/impect-shadow-teams/raw (no Impect calls). The raw folder is
~1 GB and never leaves this Mac; this compact index is what ships to the servers.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "cache" / "impect-shadow-teams" / "raw"
OUT_PATH = ROOT / "data" / "player-careers.json"
KPI_FILE = re.compile(r"^iterations_(\d+)_squads_(\d+)_player_kpis\.json$")
SQUADS_FILE = re.compile(r"^iterations_(\d+)_squads\.json$")


def _rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("data", payload)
    return payload if isinstance(payload, list) else []


def main() -> None:
    meta = {int(row["id"]): row for row in _rows(RAW_DIR / "iterations.json")}
    clubs: dict[str, str] = {}
    seconds: dict[int, dict[tuple[int, int], float]] = defaultdict(lambda: defaultdict(float))

    for path in RAW_DIR.iterdir():
        squads = SQUADS_FILE.match(path.name)
        if squads:
            iteration_id = int(squads.group(1))
            for row in _rows(path):
                if row.get("id") is not None and row.get("name"):
                    clubs[f"{iteration_id}-{int(row['id'])}"] = str(row["name"])
            continue
        kpis = KPI_FILE.match(path.name)
        if not kpis:
            continue
        key = (int(kpis.group(1)), int(kpis.group(2)))
        for row in _rows(path):
            if row.get("playerId") is not None:
                seconds[int(row["playerId"])][key] += float(row.get("playDuration") or 0)

    used_iterations: set[int] = set()
    players: dict[str, list[list[int]]] = {}
    for player_id, spells in seconds.items():
        entries = [
            [iteration_id, squad_id, round(total / 60)]
            for (iteration_id, squad_id), total in spells.items()
            if total >= 60
        ]
        if not entries:
            continue
        entries.sort(key=lambda item: (str(meta.get(item[0], {}).get("season", "")), item[2]), reverse=True)
        used_iterations.update(item[0] for item in entries)
        players[str(player_id)] = entries

    seasons = {
        str(iteration_id): [
            str(meta.get(iteration_id, {}).get("season", "")),
            str((meta.get(iteration_id, {}).get("competition") or {}).get("name", "")),
        ]
        for iteration_id in sorted(used_iterations)
    }
    clubs = {key: name for key, name in clubs.items() if int(key.split("-")[0]) in used_iterations}
    OUT_PATH.write_text(
        json.dumps(
            {
                "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "seasons": seasons,
                "clubs": clubs,
                "players": players,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"{OUT_PATH.name}: {len(players)} players, {len(seasons)} league seasons, {OUT_PATH.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
