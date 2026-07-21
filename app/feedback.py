"""Hub feedback — suggestions and bug reports appended to a JSONL log."""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.paths import DATA_ROOT, ensure_data_dirs

FEEDBACK_LOG = DATA_ROOT / "feedback.jsonl"
FEEDBACK_SCREENSHOTS_DIR = DATA_ROOT / "feedback-screenshots"
MAX_MESSAGE_LEN = 4000
MAX_SCREENSHOTS = 3
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024


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


def register_feedback_routes(app: FastAPI) -> None:
    ensure_data_dirs()
    FEEDBACK_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    @app.post("/api/feedback")
    def submit_feedback(request: Request, body: FeedbackRequest) -> dict[str, bool]:
        message = body.message.strip()
        if len(message) < 3:
            raise HTTPException(status_code=400, detail="Please enter a few words describing the issue or idea.")

        entry_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        screenshot_paths = _save_feedback_screenshots(body.screenshots, entry_id)

        entry = {
            "id": entry_id,
            "at": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "page": body.page.strip() or None,
            "screenshots": screenshot_paths or None,
            "ip": request.client.host if request.client else None,
            "user_agent": (request.headers.get("user-agent") or "")[:300] or None,
        }

        FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return {"ok": True}
