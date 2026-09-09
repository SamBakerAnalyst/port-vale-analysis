"""Pre-Match two-pager notes + shape overrides.

Staff type these on Staging, then expect them on Live. Browser localStorage is
per-origin (port 8080 vs 80), so the source of truth is a JSON file. On the
droplet both environments mount SHARED_DATA_ROOT so the same notes appear in
both products.
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
_NOTE_FIELDS = ("hurt_us", "hurt_them", "player_comments")
_MAX_NOTE_CHARS = 8000
_MAX_SHAPE_KEYS = 40


def two_pager_store_path() -> Path:
    """Prefer the shared droplet folder so Staging and Live read the same notes."""
    ensure_data_dirs()
    shared = Path(os.environ.get("SHARED_DATA_ROOT", "/shared"))
    if shared.is_dir() and os.access(shared, os.W_OK):
        return shared / "pre-match-two-pager.json"
    return DATA_ROOT / "pre-match-two-pager.json"


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "boards": {}}


def _board_key(iteration_id: int, squad_id: int) -> str:
    return f"{int(iteration_id)}:{int(squad_id)}"


def _empty_notes() -> dict[str, str]:
    return {field: "" for field in _NOTE_FIELDS}


def _clean_notes(raw: Any) -> dict[str, str]:
    payload = raw if isinstance(raw, dict) else {}
    out = _empty_notes()
    for field in _NOTE_FIELDS:
        value = payload.get(field)
        if field == "hurt_us" and not value:
            value = payload.get("strengths")
        if field == "hurt_them" and not value:
            value = payload.get("weaknesses")
        if field == "player_comments" and not value:
            value = payload.get("player_notes")
        out[field] = str(value or "")[:_MAX_NOTE_CHARS]
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
        out[label] = {"x": round(max(0.0, min(100.0, x)), 1), "y": round(max(0.0, min(100.0, y)), 1)}
    return out


def _load_store() -> dict[str, Any]:
    path = two_pager_store_path()
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


def _save_store(store: dict[str, Any]) -> Path:
    path = two_pager_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "boards": store.get("boards") or {}}
    with _store_lock:
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(path)
    return path


def empty_two_pager_board(iteration_id: int, squad_id: int) -> dict[str, Any]:
    return {
        "iteration_id": int(iteration_id),
        "squad_id": int(squad_id),
        "notes": _empty_notes(),
        "xi_shape": {},
        "avg_shape": {},
        "updated_at": None,
    }


def load_two_pager_board(iteration_id: int, squad_id: int) -> dict[str, Any]:
    if iteration_id < 1 or squad_id < 1:
        raise ValueError("iteration_id and squad_id are required")
    store = _load_store()
    row = store.get("boards", {}).get(_board_key(iteration_id, squad_id))
    if not isinstance(row, dict):
        return empty_two_pager_board(iteration_id, squad_id)
    board = empty_two_pager_board(iteration_id, squad_id)
    board["notes"] = _clean_notes(row.get("notes"))
    board["xi_shape"] = _clean_shape(row.get("xi_shape"))
    board["avg_shape"] = _clean_shape(row.get("avg_shape"))
    board["updated_at"] = row.get("updated_at")
    return board


def save_two_pager_board(
    iteration_id: int,
    squad_id: int,
    *,
    notes: Any | None = None,
    xi_shape: Any | None = None,
    avg_shape: Any | None = None,
) -> dict[str, Any]:
    if iteration_id < 1 or squad_id < 1:
        raise ValueError("iteration_id and squad_id are required")
    store = _load_store()
    boards = store.setdefault("boards", {})
    key = _board_key(iteration_id, squad_id)
    existing = boards.get(key) if isinstance(boards.get(key), dict) else {}
    row = {
        "notes": _clean_notes(notes if notes is not None else existing.get("notes")),
        "xi_shape": _clean_shape(xi_shape if xi_shape is not None else existing.get("xi_shape")),
        "avg_shape": _clean_shape(avg_shape if avg_shape is not None else existing.get("avg_shape")),
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    boards[key] = row
    _save_store(store)
    return load_two_pager_board(iteration_id, squad_id)
