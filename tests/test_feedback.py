"""Suggestion tickets — review queue plus a next-open notice for the person who asked."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import feedback as fb
from app.paths import HUB_ROOT


def _ticket(tmp_path, monkeypatch, **overrides):
    monkeypatch.setattr(fb, "FEEDBACK_LOG", tmp_path / "feedback.jsonl")
    row = {
        "id": "20260917T120000-abcd1234",
        "at": "2026-09-17T12:00:00+00:00",
        "message": "Please add a filter on the home page",
        "page": "/ · Port Vale Live",
        "username": "jordan",
        "display_name": "Jordan",
        "status": "open",
        "resolution": "",
        "notify_pending": False,
    }
    row.update(overrides)
    return fb.append_ticket(row)


def test_closing_a_ticket_queues_a_fix_notice(tmp_path, monkeypatch):
    ticket = _ticket(tmp_path, monkeypatch)
    updated = fb.update_ticket(
        ticket["id"],
        actor="Analysis",
        status="closed",
        resolution="Added the league filter on Home.",
    )
    assert updated["status"] == "closed"
    assert updated["notify_pending"] is True
    notices = fb.pending_notifications("sam")
    assert notices == []
    notices = fb.pending_notifications("jordan")
    assert len(notices) == 1
    assert notices[0]["resolution"] == "Added the league filter on Home."
    assert notices[0]["message"] == "Please add a filter on the home page"
    fb.mark_notification_seen(ticket["id"], "JORDAN")
    assert fb.pending_notifications("jordan") == []


def test_close_requires_a_fix_note(tmp_path, monkeypatch):
    ticket = _ticket(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        fb.update_ticket(ticket["id"], actor="Analysis", status="closed", resolution="  ")
    assert exc.value.status_code == 400


def test_edit_keeps_the_ticket_open(tmp_path, monkeypatch):
    ticket = _ticket(tmp_path, monkeypatch)
    updated = fb.update_ticket(
        ticket["id"],
        actor="Analysis",
        message="Please add a filter on the home page (league + date).",
        resolution="Looking at this today.",
    )
    assert updated["status"] == "open"
    assert updated["notify_pending"] is False
    assert "league + date" in updated["message"]


def test_reopen_clears_the_pending_notice(tmp_path, monkeypatch):
    ticket = _ticket(tmp_path, monkeypatch)
    fb.update_ticket(
        ticket["id"],
        actor="Analysis",
        status="closed",
        resolution="Shipped on Staging.",
    )
    updated = fb.update_ticket(ticket["id"], actor="Analysis", status="open")
    assert updated["status"] == "open"
    assert updated["notify_pending"] is False
    assert fb.pending_notifications("jordan") == []


def test_someone_else_cannot_dismiss_a_fix_notice(tmp_path, monkeypatch):
    ticket = _ticket(tmp_path, monkeypatch)
    fb.update_ticket(
        ticket["id"],
        actor="Analysis",
        status="closed",
        resolution="Done.",
    )
    with pytest.raises(HTTPException) as exc:
        fb.mark_notification_seen(ticket["id"], "sam")
    assert exc.value.status_code == 403


def test_screenshot_urls_stay_inside_the_api(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "FEEDBACK_LOG", tmp_path / "feedback.jsonl")
    ticket = fb.append_ticket(
        {
            "id": "shot-1",
            "message": "Broken layout on Compare",
            "screenshots": ["feedback-screenshots/shot-1-1.png", "../secret.png"],
        }
    )
    public = fb.public_ticket(ticket)
    assert public["screenshots"] == ["/api/feedback/screenshots/shot-1-1.png"]
    assert fb.screenshot_api_url("feedback-screenshots/shot-1-1.png") == "/api/feedback/screenshots/shot-1-1.png"


def test_unsigned_tickets_close_without_a_notice(tmp_path, monkeypatch):
    ticket = _ticket(tmp_path, monkeypatch, username=None, display_name=None)
    updated = fb.update_ticket(
        ticket["id"],
        actor="Analysis",
        status="closed",
        resolution="Fixed the overlap on the slide.",
    )
    assert updated["status"] == "closed"
    assert updated["notify_pending"] is False
    assert fb.pending_notifications("") == []


def test_widget_still_submits_and_home_opens_the_inbox():
    js = (HUB_ROOT / "static" / "hub-feedback.js").read_text(encoding="utf-8")
    assert "/api/feedback" in js
    assert "/api/feedback/notifications" in js
    assert "Everyone’s suggestions" in js or "Everyone's suggestions" in js
    assert "Close ticket" in js
    assert "What we changed" in js
