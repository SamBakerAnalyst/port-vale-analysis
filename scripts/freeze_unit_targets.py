"""Re-pin the Blocks wall targets (4-4-2 / 3-5-2 / 3-4-3) to the current League Two top-7.

Usage (from ~/impect-football-dashboard, with .env loaded):
    set -a; source .env; set +a
    PYTHONPATH=. .venv/bin/python scripts/freeze_unit_targets.py

Then deploy — app/blocks_fixed_unit_targets.json ships with the code.
"""

from __future__ import annotations

import json

from app.blocks_analysis import FIXED_UNIT_TARGETS_PATH, freeze_fixed_unit_targets


def main() -> None:
    payload = freeze_fixed_unit_targets()
    print(f"Wrote {FIXED_UNIT_TARGETS_PATH} (frozen {payload['frozenAt']})")
    print(json.dumps(payload["shapes"], indent=2))


if __name__ == "__main__":
    main()
