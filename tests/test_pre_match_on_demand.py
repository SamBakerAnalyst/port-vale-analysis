from __future__ import annotations

import threading
from pathlib import Path

from app import analysis_cache, pre_match
from app.apps_manifest import APPS, LIVE_ESSENTIAL_IDS


def test_opposition_tabs_is_a_reports_tool():
    app = next(row for row in APPS if row["id"] == "opposition-reports")
    assert app["group"] == "reports"
    assert app["title"] == "Opposition Reports"
    assert app["href"] == "/opposition-reports"
    assert app["router"] == "pre_match"
    assert "/api/pre-match" in app["api_prefixes"]
    assert "/pre-match/assets" in app["api_prefixes"]
    assert "opposition-reports" in LIVE_ESSENTIAL_IDS


def test_pre_match_page_has_no_deck_toggle():
    html = Path("standalone/pre-match.page.html").read_text(encoding="utf-8")
    assert "deckModeTwoBtn" not in html
    js = Path("static/pre-match.js").read_text(encoding="utf-8")
    assert "pm-deck-mode" not in js
    assert 'dataset.pmMode === "two_pager"' in js


def test_missing_report_builds_in_background_once(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "_ensure_dir", lambda: tmp_path)
    monkeypatch.setattr(analysis_cache, "CACHE_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(pre_match, "_pre_match_report_from_disk", lambda *a: None)
    monkeypatch.setattr(pre_match, "_background_builds", {})
    release = threading.Event()
    calls: list[int] = []
    written: dict[str, dict] = {}

    def fake_build(body):
        calls.append(int(body.squad_id))
        release.wait(5)
        return {"opponent": {"id": body.squad_id, "name": "Grimsby Town"}}

    monkeypatch.setattr(pre_match, "_build_pre_match_report_uncached", fake_build)
    monkeypatch.setattr(analysis_cache, "read_json", lambda kind, key, **kw: written.get(key))
    monkeypatch.setattr(
        analysis_cache, "write_json", lambda kind, key, data: written.__setitem__(key, data)
    )

    body = pre_match.PreMatchReportRequest(iteration_id=2120, squad_id=953, match_id=270781)
    first = pre_match.build_pre_match_report(body)
    second = pre_match.build_pre_match_report(body)
    assert first["building"] and first["build_status"] == "running"
    assert second["build_status"] == "running"

    release.set()
    for _ in range(50):
        if "report_2120_953_270781" in written:
            break
        threading.Event().wait(0.05)
    assert calls == [953]
    assert written["report_2120_953_270781"]["opponent"]["name"] == "Grimsby Town"
    assert pre_match._background_builds == {}
