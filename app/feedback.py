"""Hub feedback — staff suggestions logged as tickets analysis can close."""

from __future__ import annotations

import base64
import binascii
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.auth import auth_enabled, current_role, current_user_payload, is_authenticated
from app.paths import DATA_ROOT, ensure_data_dirs

FEEDBACK_LOG = DATA_ROOT / "feedback.jsonl"
FEEDBACK_SCREENSHOTS_DIR = DATA_ROOT / "feedback-screenshots"
MAX_MESSAGE_LEN = 4000
MAX_SCREENSHOTS = 3
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
MANAGER_ROLES = frozenset({"admin", "analysis"})
_SCREENSHOT_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_lock = threading.Lock()

_SCREENSHOT_MEDIA = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class FeedbackRequest(BaseModel):
    message: str = Field(..., min_length=3, max_length=MAX_MESSAGE_LEN)
    page: str = Field(default="", max_length=500)
    screenshots: list[str] = Field(default_factory=list, max_length=MAX_SCREENSHOTS)

    @field_validator("screenshots")
    @classmethod
    def validate_screenshots(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if len(cleaned) > MAX_SCREENSHOTS:
            raise ValueError(f"At most {MAX_SCREENSHOTS} screenshots allowed.")
        return cleaned


class FeedbackUpdateRequest(BaseModel):
    message: str | None = Field(default=None, min_length=3, max_length=MAX_MESSAGE_LEN)
    status: Literal["open", "closed"] | None = None
    resolution: str | None = Field(default=None, max_length=MAX_MESSAGE_LEN)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def can_manage_feedback(request: Request) -> bool:
    if not auth_enabled():
        return True
    return current_role(request) in MANAGER_ROLES


def _require_manager(request: Request) -> dict[str, Any]:
    user = current_user_payload(request)
    if not can_manage_feedback(request):
        raise HTTPException(status_code=403, detail="Only analysis can manage suggestions.")
    return user


def _decode_feedback_image(data_url: str) -> tuple[bytes, str]:
    raw = data_url.strip()
    ext = "png"
    if raw.startswith("data:"):
        header, _, payload = raw.partition(",")
        if not payload:
            raise HTTPException(status_code=400, detail="Invalid screenshot data.")
        lowered = header.lower()
        if "jpeg" in lowered or "jpg" in lowered:
            ext = "jpg"
        elif "webp" in lowered:
            ext = "webp"
        elif "png" in lowered:
            ext = "png"
        else:
            raise HTTPException(
                status_code=400,
                detail="Screenshots must be PNG, JPG, or WebP.",
            )
        raw = payload
    try:
        image_bytes = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid screenshot data.") from exc
    if len(image_bytes) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(status_code=400, detail="Each screenshot must be 5 MB or smaller.")
    return image_bytes, ext


def _save_feedback_screenshots(screenshots: list[str], entry_id: str) -> list[str]:
    if not screenshots:
        return []

    FEEDBACK_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", entry_id) or uuid.uuid4().hex

    for index, screenshot in enumerate(screenshots, start=1):
        image_bytes, ext = _decode_feedback_image(screenshot)
        filename = f"{safe_id}-{index}.{ext}"
        path = FEEDBACK_SCREENSHOTS_DIR / filename
        path.write_bytes(image_bytes)
        saved.append(f"feedback-screenshots/{filename}")

    return saved


def _screenshot_filename(raw: Any) -> str:
    text = str(raw or "").replace("\\", "/").strip()
    if not text or ".." in text:
        return ""
    name = Path(text).name
    return name if name and _SCREENSHOT_NAME.fullmatch(name) else ""


def screenshot_api_url(raw: Any) -> str | None:
    name = _screenshot_filename(raw)
    return f"/api/feedback/screenshots/{name}" if name else None


def _normalize_ticket(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    ticket_id = str(row.get("id") or "").strip()
    if not ticket_id:
        return None
    status = str(row.get("status") or "open").strip().lower()
    if status not in ("open", "closed"):
        status = "open"
    ticket = dict(row)
    ticket["id"] = ticket_id
    ticket["status"] = status
    ticket["message"] = str(ticket.get("message") or "")
    ticket["resolution"] = str(ticket.get("resolution") or "")
    ticket["notify_pending"] = bool(ticket.get("notify_pending"))
    return ticket


def load_tickets() -> list[dict[str, Any]]:
    if not FEEDBACK_LOG.exists():
        return []
    try:
        lines = FEEDBACK_LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    tickets: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ticket = _normalize_ticket(row)
        if ticket:
            tickets.append(ticket)
    return tickets


def save_tickets(tickets: list[dict[str, Any]]) -> None:
    FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = FEEDBACK_LOG.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in tickets:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(FEEDBACK_LOG)


def append_ticket(entry: dict[str, Any]) -> dict[str, Any]:
    ticket = _normalize_ticket(entry)
    if not ticket:
        raise ValueError("Ticket needs an id.")
    with _lock:
        tickets = load_tickets()
        tickets.append(ticket)
        save_tickets(tickets)
    return ticket


def public_ticket(row: dict[str, Any]) -> dict[str, Any]:
    screenshots = [
        url
        for url in (screenshot_api_url(item) for item in (row.get("screenshots") or []))
        if url
    ]
    return {
        "id": row.get("id"),
        "at": row.get("at"),
        "message": row.get("message") or "",
        "page": row.get("page"),
        "screenshots": screenshots,
        "username": row.get("username"),
        "display_name": row.get("display_name"),
        "role": row.get("role"),
        "status": row.get("status") or "open",
        "resolution": row.get("resolution") or "",
        "resolved_at": row.get("resolved_at"),
        "resolved_by": row.get("resolved_by"),
        "updated_at": row.get("updated_at"),
        "updated_by": row.get("updated_by"),
        "notify_pending": bool(row.get("notify_pending")),
    }


def update_ticket(
    ticket_id: str,
    *,
    actor: str,
    message: str | None = None,
    status: str | None = None,
    resolution: str | None = None,
) -> dict[str, Any]:
    wanted = str(ticket_id or "").strip()
    if not wanted:
        raise HTTPException(status_code=404, detail="Suggestion not found.")
    actor_name = str(actor or "Analysis").strip() or "Analysis"
    with _lock:
        tickets = load_tickets()
        ticket = next((row for row in tickets if row.get("id") == wanted), None)
        if not ticket:
            raise HTTPException(status_code=404, detail="Suggestion not found.")

        if message is not None:
            cleaned = message.strip()
            if len(cleaned) < 3:
                raise HTTPException(status_code=400, detail="Please keep a few words on the ticket.")
            ticket["message"] = cleaned

        if resolution is not None:
            ticket["resolution"] = resolution.strip()

        if status == "closed":
            note = str(ticket.get("resolution") or "").strip()
            if len(note) < 3:
                raise HTTPException(
                    status_code=400,
                    detail="Add a short note on what you changed so they see it next time they open the hub.",
                )
            ticket["status"] = "closed"
            ticket["resolution"] = note
            ticket["resolved_at"] = _now()
            ticket["resolved_by"] = actor_name
            if str(ticket.get("username") or "").strip():
                ticket["notify_pending"] = True
                ticket["notify_seen_at"] = None
        elif status == "open":
            ticket["status"] = "open"
            ticket["notify_pending"] = False

        ticket["updated_at"] = _now()
        ticket["updated_by"] = actor_name
        save_tickets(tickets)
        return dict(ticket)


def pending_notifications(username: str) -> list[dict[str, Any]]:
    who = str(username or "").strip().casefold()
    if not who:
        return []
    notices: list[dict[str, Any]] = []
    for row in load_tickets():
        owner = str(row.get("username") or "").strip().casefold()
        if owner != who:
            continue
        if row.get("status") != "closed" or not row.get("notify_pending"):
            continue
        notices.append(
            {
                "id": row.get("id"),
                "title": "Your suggestion is done",
                "message": row.get("message") or "",
                "resolution": row.get("resolution") or "",
                "page": row.get("page"),
                "resolved_by": row.get("resolved_by"),
                "resolved_at": row.get("resolved_at"),
            }
        )
    return notices


def mark_notification_seen(ticket_id: str, username: str) -> dict[str, Any]:
    wanted = str(ticket_id or "").strip()
    who = str(username or "").strip().casefold()
    if not wanted or not who:
        raise HTTPException(status_code=404, detail="Suggestion not found.")
    with _lock:
        tickets = load_tickets()
        ticket = next((row for row in tickets if row.get("id") == wanted), None)
        if not ticket:
            raise HTTPException(status_code=404, detail="Suggestion not found.")
        owner = str(ticket.get("username") or "").strip().casefold()
        if owner != who:
            raise HTTPException(status_code=403, detail="That update is not for this account.")
        ticket["notify_pending"] = False
        ticket["notify_seen_at"] = _now()
        ticket["updated_at"] = _now()
        save_tickets(tickets)
        return dict(ticket)


def _screenshot_path(filename: str) -> Path:
    name = _screenshot_filename(filename)
    if not name:
        raise HTTPException(status_code=404, detail="Screenshot not found.")
    path = (FEEDBACK_SCREENSHOTS_DIR / name).resolve()
    root = FEEDBACK_SCREENSHOTS_DIR.resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found.")
    return path


def register_feedback_routes(app: FastAPI) -> None:
    ensure_data_dirs()
    FEEDBACK_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    @app.get("/api/feedback")
    def list_feedback(request: Request) -> dict[str, Any]:
        manage = can_manage_feedback(request)
        tickets = [public_ticket(row) for row in load_tickets()] if manage else []
        tickets.reverse()
        open_count = sum(1 for row in tickets if row.get("status") == "open")
        return {
            "ok": True,
            "can_manage": manage,
            "open_count": open_count,
            "tickets": tickets,
        }

    @app.get("/api/feedback/notifications")
    def list_feedback_notifications(request: Request) -> dict[str, Any]:
        user = current_user_payload(request)
        notices = pending_notifications(str(user.get("username") or ""))
        return {"ok": True, "notifications": notices}

    @app.get("/api/feedback/screenshots/{filename}")
    def feedback_screenshot(filename: str) -> FileResponse:
        path = _screenshot_path(filename)
        media = _SCREENSHOT_MEDIA.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path, media_type=media)

    @app.post("/api/feedback/{ticket_id}/seen")
    def seen_feedback_notification(request: Request, ticket_id: str) -> dict[str, bool]:
        user = current_user_payload(request)
        mark_notification_seen(ticket_id, str(user.get("username") or ""))
        return {"ok": True}

    @app.patch("/api/feedback/{ticket_id}")
    def patch_feedback(request: Request, ticket_id: str, body: FeedbackUpdateRequest) -> dict[str, Any]:
        user = _require_manager(request)
        actor = str(user.get("display_name") or user.get("username") or "Analysis")
        ticket = update_ticket(
            ticket_id,
            actor=actor,
            message=body.message,
            status=body.status,
            resolution=body.resolution,
        )
        return {"ok": True, "ticket": public_ticket(ticket)}

    @app.post("/api/feedback")
    def submit_feedback(request: Request, body: FeedbackRequest) -> dict[str, bool]:
        message = body.message.strip()
        if len(message) < 3:
            raise HTTPException(status_code=400, detail="Please enter a few words describing the issue or idea.")

        entry_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        screenshot_paths = _save_feedback_screenshots(body.screenshots, entry_id)

        user = current_user_payload(request) if is_authenticated(request) else {}
        entry = {
            "id": entry_id,
            "at": _now(),
            "message": message,
            "page": body.page.strip() or None,
            "screenshots": screenshot_paths or None,
            "username": user.get("username") or None,
            "display_name": user.get("display_name") or None,
            "role": user.get("role") or None,
            "status": "open",
            "resolution": "",
            "notify_pending": False,
            "ip": request.client.host if request.client else None,
            "user_agent": (request.headers.get("user-agent") or "")[:300] or None,
        }
        append_ticket(entry)
        return {"ok": True}
