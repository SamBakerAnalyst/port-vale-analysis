import json

from app.club_strategy import build_club_strategy_report
from app.strategy_tracker import (
    REPORT_DISK_NAMES,
    TRACKER_CACHE_VERSION,
    _newest_cached_tracker,
    _pick_from_disk_reports,
    _read_report_cheap,
)


def test_report_disk_names_prefer_current_v4():
    assert REPORT_DISK_NAMES[0] == "report-v4"


def test_read_report_cheap_finds_v4(tmp_path, monkeypatch):
    monkeypatch.setattr("app.club_strategy.DISK_CACHE_DIR", tmp_path)
    payload = {
        "cached_at_epoch": 1,
        "competition": "League Two",
        "season": "2026-2027",
        "standings": [{"club": "Port Vale", "focus": True, "played": 4}],
    }
    (tmp_path / "report-v4-4242.json").write_text(json.dumps(payload), encoding="utf-8")

    report = _read_report_cheap(4242)
    assert report is not None
    assert report["season"] == "2026-2027"
    assert "cached_at_epoch" not in report


def test_pick_from_disk_reports_uses_v4(tmp_path, monkeypatch):
    monkeypatch.setattr("app.club_strategy.DISK_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.strategy_tracker.CLUB_STRATEGY_CACHE_DIR", tmp_path)
    payload = {
        "cached_at_epoch": 1,
        "competition": "League Two",
        "season": "2026-2027",
        "standings": [{"club": "Port Vale", "focus": True, "squad_id": 8, "played": 4}],
    }
    (tmp_path / "report-v4-4242.json").write_text(json.dumps(payload), encoding="utf-8")

    picked = _pick_from_disk_reports("League Two")
    assert picked is not None
    assert picked[0] == 4242
    assert picked[1] == "League Two"


def test_newest_cached_tracker_serves_stale(tmp_path, monkeypatch):
    monkeypatch.setattr("app.strategy_tracker.TRACKER_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.strategy_tracker._cache", {})
    payload = {
        "cached_at_epoch": 1,
        "competition": "League Two",
        "season": "2026-2027",
        "generated_at": "2026-09-04T05:00:00+00:00",
        "iteration_id": 77,
    }
    (tmp_path / f"tracker-v{TRACKER_CACHE_VERSION}-77.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    cached = _newest_cached_tracker("League Two")
    assert cached is not None
    assert cached["iteration_id"] == 77
    assert cached["season"] == "2026-2027"


def test_club_strategy_click_path_serves_stale_disk(tmp_path, monkeypatch):
    monkeypatch.setattr("app.club_strategy.DISK_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.club_strategy._report_cache", {})
    payload = {
        "cached_at_epoch": 1,
        "competition": "League Two",
        "season": "2026-2027",
        "iteration_id": 88,
        "standings": [{"club": "Port Vale", "focus": True, "played": 3}],
        "averages": {},
        "generated_at": "2026-09-04T05:00:00+00:00",
    }
    (tmp_path / "report-v4-88.json").write_text(json.dumps(payload), encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise AssertionError("click path must not call Impect")

    monkeypatch.setattr("app.club_strategy._resolve_iteration", boom)
    monkeypatch.setattr("app.club_strategy._build_standings", boom)

    report = build_club_strategy_report(88, force_refresh=False)
    assert report["season"] == "2026-2027"
    assert report["iteration_id"] == 88
    assert "cached_at_epoch" not in report
