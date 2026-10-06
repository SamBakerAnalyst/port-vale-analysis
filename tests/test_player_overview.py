from __future__ import annotations

from app import player_overview as overview


def _report(**overrides):
    row = {
        "source": "library",
        "fixture": "Port Vale vs Bradford",
        "date": "2026-09-12",
        "scout": "Martin",
        "position": "CF",
        "viewing": "live",
        "match_rating": 7.0,
        "pvfc_level": "B",
        "next_action": "high_priority",
        "current_ability": None,
        "potential_ability": None,
        "text": "Strong in the air. Holds the ball up well under pressure.",
        "next_steps": "",
        "href": "/reports-library",
    }
    row.update(overrides)
    return row


def test_no_reports_returns_empty_summary(monkeypatch):
    monkeypatch.setattr(overview, "collect_player_reports", lambda pid, name: [])
    data = overview.build_reports_summary(1, "Player")
    assert data["count"] == 0
    assert data["summary"] is None


def test_reports_build_consensus_summary(monkeypatch):
    rows = [
        _report(),
        _report(date="2026-08-30", scout="Dave", match_rating=8.0, pvfc_level="B"),
        _report(date="2026-08-01", scout="Dave", match_rating=6.0, pvfc_level="C", next_action="low_priority"),
    ]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(overview, "collect_player_reports", lambda pid, name: rows)
    data = overview.build_reports_summary(1, "Player")
    stats = data["stats"]
    assert data["count"] == 3
    assert stats["pvfc_level"] == "B"
    assert stats["avg_match_rating"] == 7.0
    assert stats["scouts"] == ["Dave", "Martin"]
    assert stats["next_action"] == "high_priority"
    assert data["summary"]["engine"] == "built-in"
    assert "3 reports from 2 scouts" in data["summary"]["headline"]
