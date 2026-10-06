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
        "text": "Strong in the air and a good size. Good first touch and carried the ball well.",
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
    summary = data["summary"]
    assert "Watched 3 times by 2 scouts" in summary["headline"]
    assert "centre-forward" in summary["headline"]
    assert any(item.startswith("Crosses & aerial play") or item.startswith("Technique") or "Physique" in item for item in summary["strengths"])
    assert summary["recommendation"].startswith("High priority")


def test_clean_text_strips_migration_headers():
    text = (
        "Original scout (Gemini): Tom Fry — created Oct 30 - 2:19pm 2025\n"
        "Match (Gemini): A vs B · Position in match: LW · Context: vs B on 18/10/2025\n"
        "Scout comments: •\tGood first touch and carried the ball well.\n"
        "Gemini verdict: No (from Tom Fry)."
    )
    sentences = overview._clean_report_text(text)
    assert sentences == ["Good first touch and carried the ball well"]
    assert overview._date_from_text(text) == "2025-10-18"
