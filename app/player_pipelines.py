"""Shared recruitment player pipelines (kanban)."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.auth import current_user_payload
from app.paths import DATA_ROOT, STANDALONE_DIR, ensure_data_dirs

PIPELINES_PATH = DATA_ROOT / "player-pipelines.json"
_lock = threading.Lock()

STAGES: tuple[dict[str, str], ...] = (
    {
        "id": "data_identified",
        "title": "Data identified",
        "hint": "On the list from data — not videoed yet",
    },
    {
        "id": "video_scouted",
        "title": "Video scouted",
        "hint": "Watched on video",
    },
    {
        "id": "live_scouted",
        "title": "Live scouted",
        "hint": "Seen in person",
    },
    {
        "id": "gone_elsewhere",
        "title": "Gone / turned us down",
        "hint": "Went elsewhere or said no",
    },
)
STAGE_IDS = tuple(row["id"] for row in STAGES)

POSITIONS: tuple[tuple[str, str], ...] = (
    ("GOALKEEPER", "GK"),
    ("RIGHT_WINGBACK_DEFENDER", "RB"),
    ("LEFT_WINGBACK_DEFENDER", "LB"),
    ("CENTRAL_DEFENDER", "CB"),
    ("DEFENSE_MIDFIELD", "DM"),
    ("CENTRAL_MIDFIELD", "CM"),
    ("ATTACKING_MIDFIELD", "AM"),
    ("LEFT_WINGER", "LW"),
    ("RIGHT_WINGER", "RW"),
    ("CENTER_FORWARD", "ST"),
)
POSITION_LABELS = {code: short for code, short in POSITIONS}

DEFAULT_TAGS: tuple[str, ...] = (
    "Agent contacted",
    "Watching",
    "Priority",
    "Loan",
    "Offer made",
    "Medical",
    "Contract talks",
    "Turned us down",
    "Signed elsewhere",
)


class AddTargetBody(BaseModel):
    player_id: int
    name: str = ""
    club: str = ""
    league: str = ""
    position: str = ""
    position_label: str = ""
    age: int | None = None
    photo_url: str = ""
    stage: str = "data_identified"
    tags: list[str] = Field(default_factory=list)


class MoveTargetBody(BaseModel):
    stage: str
    before_id: str | None = None


class PatchTargetBody(BaseModel):
    tags: list[str] | None = None
    position: str | None = None
    position_label: str | None = None


class NoteBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _staff(request: Request) -> str:
    payload = current_user_payload(request)
    return str(payload.get("display_name") or payload.get("username") or "Staff").strip() or "Staff"


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "targets": []}


def _load() -> dict[str, Any]:
    ensure_data_dirs()
    if not PIPELINES_PATH.exists():
        return _empty_store()
    try:
        payload = json.loads(PIPELINES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(payload, dict):
        return _empty_store()
    targets = payload.get("targets")
    if not isinstance(targets, list):
        targets = []
    return {"version": 1, "targets": targets}


def _save(store: dict[str, Any]) -> None:
    ensure_data_dirs()
    payload = {"version": 1, "targets": store.get("targets") or []}
    with _lock:
        temp_path = PIPELINES_PATH.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(PIPELINES_PATH)


def _clean_tags(raw: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in raw or []:
        label = " ".join(str(item or "").split())[:40]
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out[:20]


def _clean_stage(value: str | None) -> str:
    stage = str(value or "").strip()
    return stage if stage in STAGE_IDS else "data_identified"


def _public_target(row: dict[str, Any]) -> dict[str, Any]:
    notes = row.get("notes") if isinstance(row.get("notes"), list) else []
    return {
        "id": row.get("id"),
        "player_id": row.get("player_id"),
        "name": row.get("name") or "Unknown",
        "club": row.get("club") or "",
        "league": row.get("league") or "",
        "position": row.get("position") or "",
        "position_label": row.get("position_label")
        or POSITION_LABELS.get(str(row.get("position") or ""), ""),
        "age": row.get("age"),
        "photo_url": row.get("photo_url") or "",
        "stage": _clean_stage(row.get("stage")),
        "tags": _clean_tags(row.get("tags")),
        "added_by": row.get("added_by") or "",
        "added_at": row.get("added_at") or "",
        "moved_by": row.get("moved_by") or "",
        "moved_at": row.get("moved_at") or "",
        "sort": int(row.get("sort") or 0),
        "notes": [
            {
                "id": note.get("id"),
                "text": note.get("text") or "",
                "author": note.get("author") or "",
                "created_at": note.get("created_at") or "",
            }
            for note in notes
            if isinstance(note, dict)
        ],
        "dossier_href": f"/player/{row.get('player_id')}" if row.get("player_id") else "",
    }


def _board_payload() -> dict[str, Any]:
    store = _load()
    targets = [_public_target(row) for row in store["targets"] if isinstance(row, dict)]
    targets.sort(key=lambda row: (STAGE_IDS.index(row["stage"]), row["sort"], row["name"].lower()))
    return {
        "stages": list(STAGES),
        "positions": [{"id": code, "label": short} for code, short in POSITIONS],
        "default_tags": list(DEFAULT_TAGS),
        "targets": targets,
    }


def _next_sort(targets: list[dict[str, Any]], stage: str) -> int:
    values = [int(row.get("sort") or 0) for row in targets if row.get("stage") == stage]
    return (max(values) + 1) if values else 0


def _find_by_player(targets: list[dict[str, Any]], player_id: int) -> dict[str, Any] | None:
    for row in targets:
        if int(row.get("player_id") or 0) == player_id:
            return row
    return None


def _find_by_id(targets: list[dict[str, Any]], target_id: str) -> dict[str, Any] | None:
    for row in targets:
        if str(row.get("id") or "") == target_id:
            return row
    return None


def _reorder(targets: list[dict[str, Any]], stage: str, moved_id: str, before_id: str | None) -> None:
    column = [row for row in targets if row.get("stage") == stage]
    moved = next((row for row in column if str(row.get("id")) == moved_id), None)
    if moved is None:
        return
    rest = [row for row in column if str(row.get("id")) != moved_id]
    insert_at = len(rest)
    if before_id:
        for idx, row in enumerate(rest):
            if str(row.get("id")) == before_id:
                insert_at = idx
                break
    rest.insert(insert_at, moved)
    for idx, row in enumerate(rest):
        row["sort"] = idx


def register_player_pipelines_routes(app: FastAPI) -> None:
    @app.get("/player-pipelines", response_class=HTMLResponse)
    def player_pipelines_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "player-pipelines.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Player pipelines UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/player-pipelines")
    def player_pipelines_board() -> dict[str, Any]:
        return _board_payload()

    @app.get("/api/player-pipelines/status")
    def player_pipelines_status(player_id: int) -> dict[str, Any]:
        store = _load()
        row = _find_by_player(store["targets"], player_id)
        if row is None:
            return {"in_pipeline": False, "target": None}
        return {"in_pipeline": True, "target": _public_target(row)}

    @app.post("/api/player-pipelines/targets")
    def player_pipelines_add(request: Request, body: AddTargetBody) -> dict[str, Any]:
        store = _load()
        existing = _find_by_player(store["targets"], body.player_id)
        if existing is not None:
            return {"created": False, "target": _public_target(existing)}

        staff = _staff(request)
        stage = _clean_stage(body.stage)
        name = " ".join((body.name or "").split()) or f"Player {body.player_id}"
        position = str(body.position or "").strip()
        position_label = str(body.position_label or "").strip() or POSITION_LABELS.get(position, "")
        photo = str(body.photo_url or "").strip()
        if not photo and name:
            from urllib.parse import quote

            photo = f"/api/player-photo?name={quote(name)}"
        row = {
            "id": str(uuid.uuid4()),
            "player_id": int(body.player_id),
            "name": name,
            "club": " ".join((body.club or "").split()),
            "league": " ".join((body.league or "").split()),
            "position": position,
            "position_label": position_label,
            "age": body.age,
            "photo_url": photo,
            "stage": stage,
            "tags": _clean_tags(body.tags),
            "added_by": staff,
            "added_at": _now(),
            "moved_by": staff,
            "moved_at": _now(),
            "sort": _next_sort(store["targets"], stage),
            "notes": [],
        }
        store["targets"].append(row)
        _save(store)
        return {"created": True, "target": _public_target(row)}

    @app.patch("/api/player-pipelines/targets/{target_id}")
    def player_pipelines_patch(
        request: Request, target_id: str, body: PatchTargetBody
    ) -> dict[str, Any]:
        store = _load()
        row = _find_by_id(store["targets"], target_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Target not found.")
        if body.tags is not None:
            row["tags"] = _clean_tags(body.tags)
        if body.position is not None:
            row["position"] = str(body.position).strip()
            row["position_label"] = (
                str(body.position_label or "").strip()
                or POSITION_LABELS.get(row["position"], "")
            )
        elif body.position_label is not None:
            row["position_label"] = str(body.position_label).strip()
        _save(store)
        return {"target": _public_target(row)}

    @app.post("/api/player-pipelines/targets/{target_id}/move")
    def player_pipelines_move(
        request: Request, target_id: str, body: MoveTargetBody
    ) -> dict[str, Any]:
        store = _load()
        row = _find_by_id(store["targets"], target_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Target not found.")
        stage = _clean_stage(body.stage)
        row["stage"] = stage
        row["moved_by"] = _staff(request)
        row["moved_at"] = _now()
        _reorder(store["targets"], stage, target_id, body.before_id)
        _save(store)
        return {"target": _public_target(row)}

    @app.delete("/api/player-pipelines/targets/{target_id}")
    def player_pipelines_delete(target_id: str) -> dict[str, bool]:
        store = _load()
        before = len(store["targets"])
        store["targets"] = [
            row for row in store["targets"] if str(row.get("id") or "") != target_id
        ]
        if len(store["targets"]) == before:
            raise HTTPException(status_code=404, detail="Target not found.")
        _save(store)
        return {"ok": True}

    @app.post("/api/player-pipelines/targets/{target_id}/notes")
    def player_pipelines_add_note(
        request: Request, target_id: str, body: NoteBody
    ) -> dict[str, Any]:
        store = _load()
        row = _find_by_id(store["targets"], target_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Target not found.")
        text = " ".join(body.text.split())
        if not text:
            raise HTTPException(status_code=400, detail="Note cannot be empty.")
        notes = row.get("notes") if isinstance(row.get("notes"), list) else []
        note = {
            "id": str(uuid.uuid4()),
            "text": text,
            "author": _staff(request),
            "created_at": _now(),
        }
        notes.append(note)
        row["notes"] = notes
        _save(store)
        return {"target": _public_target(row), "note": note}
