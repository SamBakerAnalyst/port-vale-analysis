"""Shared pre-match squad board: availability and the predicted XI.

Click-to-cycle and drag/swap stay in the browser until Save. The saved board
is the copy every login sees. Reset clears it so the verified default returns.
Staging and Live share the file when SHARED_DATA_ROOT is mounted.
"""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.paths import DATA_ROOT, ensure_data_dirs

_store_lock = threading.Lock()
_STATUSES = {"available", "injured", "suspended", "international", "doubt"}
_MAX_PLAYERS = 80
_MAX_TEXT = 240
_MAX_RETURN = 80
_MAX_SLOTS = 11
_MAX_SHAPE_KEYS = 40


def squad_board_store_path() -> Path:
    ensure_data_dirs()
    shared = Path(os.environ.get("SHARED_DATA_ROOT", "/shared"))
    if shared.is_dir() and os.access(shared, os.W_OK):
        return shared / "pre-match-squad-board.json"
    return DATA_ROOT / "pre-match-squad-board.json"


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "boards": {}}


def _board_key(iteration_id: int, squad_id: int) -> str:
    return f"{int(iteration_id)}:{int(squad_id)}"


def _load_store() -> dict[str, Any]:
    path = squad_board_store_path()
    if not path.exists():
        return _empty_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(payload, dict):
        return _empty_store()
    boards = payload.get("boards")
    if not isinstance(boards, dict):
        boards = {}
    return {"version": 1, "boards": boards}


def _save_store(store: dict[str, Any]) -> None:
    path = squad_board_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "boards": store.get("boards") or {}}
    with _store_lock:
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(path)


def empty_squad_board(iteration_id: int, squad_id: int) -> dict[str, Any]:
    return {
        "iteration_id": int(iteration_id),
        "squad_id": int(squad_id),
        "availability": {},
        "pitch_xi": {},
        "pitch_shape": {},
        "updated_at": None,
        "saved": False,
    }


def _clean_availability(raw: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if len(out) >= _MAX_PLAYERS:
            break
        try:
            player_id = int(key)
        except (TypeError, ValueError):
            continue
        payload = value if isinstance(value, dict) else {"status": value}
        status = str(payload.get("status") or "available").strip().lower()
        if status not in _STATUSES:
            continue
        if status == "available" and not payload.get("reason") and not payload.get("expected_return"):
            continue
        out[str(player_id)] = {
            "status": status,
            "reason": str(payload.get("reason") or "")[:_MAX_TEXT],
            "expected_return": str(payload.get("expected_return") or "")[:_MAX_RETURN],
        }
    return out


def _clean_pitch_xi(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        if len(out) >= _MAX_SLOTS:
            break
        try:
            slot = int(key)
            player_id = int(value)
        except (TypeError, ValueError):
            continue
        if slot < 0 or slot >= _MAX_SLOTS:
            continue
        out[str(slot)] = player_id
    return out


def _clean_shape(raw: Any) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, float]] = {}
    for key, value in raw.items():
        if len(out) >= _MAX_SHAPE_KEYS:
            break
        label = str(key or "").strip()[:80]
        if not label or not isinstance(value, dict):
            continue
        try:
            x = float(value.get("x"))
            y = float(value.get("y"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        out[label] = {
            "x": round(max(0.0, min(100.0, x)), 1),
            "y": round(max(0.0, min(100.0, y)), 1),
        }
    return out


def load_squad_board(iteration_id: int, squad_id: int) -> dict[str, Any]:
    if iteration_id < 1 or squad_id < 1:
        raise ValueError("iteration_id and squad_id are required")
    store = _load_store()
    row = store.get("boards", {}).get(_board_key(iteration_id, squad_id))
    board = empty_squad_board(iteration_id, squad_id)
    if not isinstance(row, dict):
        return board
    board["availability"] = _clean_availability(row.get("availability"))
    board["pitch_xi"] = _clean_pitch_xi(row.get("pitch_xi"))
    board["pitch_shape"] = _clean_shape(row.get("pitch_shape"))
    board["updated_at"] = row.get("updated_at")
    board["saved"] = True
    return board


def save_squad_board(
    iteration_id: int,
    squad_id: int,
    *,
    availability: Any | None = None,
    pitch_xi: Any | None = None,
    pitch_shape: Any | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    if iteration_id < 1 or squad_id < 1:
        raise ValueError("iteration_id and squad_id are required")
    store = _load_store()
    boards = store.setdefault("boards", {})
    key = _board_key(iteration_id, squad_id)
    if reset:
        boards.pop(key, None)
        _save_store(store)
        return empty_squad_board(iteration_id, squad_id)
    boards[key] = {
        "availability": _clean_availability(availability),
        "pitch_xi": _clean_pitch_xi(pitch_xi),
        "pitch_shape": _clean_shape(pitch_shape),
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _save_store(store)
    return load_squad_board(iteration_id, squad_id)
