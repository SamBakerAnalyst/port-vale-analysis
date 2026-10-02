from datetime import UTC, datetime, timedelta

from app import home_dashboard as hd
from app.fixture_planner import _fotmob_fixture_status


def _row(days: int, fid: str, status: str, opponent: str) -> dict:
    kickoff = (datetime.now(UTC) + timedelta(days=days)).replace(microsecond=0)
    iso = kickoff.isoformat().replace("+00:00", "Z")
    return {
        "league": "League Two",
        "date": iso[:10],
        "kickoff_utc": iso,
        "home": {"name": "Port Vale", "fotmob_id": hd.PORT_VALE_FOTMOB_ID, "score": 0},
        "away": {"name": opponent, "fotmob_id": "1", "score": 0},
        "status": status,
        "score": None,
        "home_score": 0,
        "away_score": 0,
        "source_ids": {"fotmob": fid},
    }


def test_fotmob_status_maps_postponed():
    assert _fotmob_fixture_status({"finished": True}) == "completed"
    assert _fotmob_fixture_status({"cancelled": True, "reason": {"short": "PP"}}) == "postponed"
    assert _fotmob_fixture_status({}) == "scheduled"


def test_next_match_skips_postponed_and_stale(monkeypatch, tmp_path):
    rows = [
        _row(-6, "1", "postponed", "Northampton Town"),
        _row(-3, "2", "scheduled", "Stale FC"),
        _row(1, "3", "scheduled", "Colchester United"),
    ]
    monkeypatch.setattr(hd, "is_demo", lambda: False)
    monkeypatch.setattr(hd, "PV_FOTMOB_LEAGUE_SEASONS", [])
    monkeypatch.setattr(hd, "_fetch_team_fixtures_fotmob", lambda: rows)
    monkeypatch.setattr("app.analysis_cache.write_json", lambda *a, **k: None)
    monkeypatch.setattr("app.analysis_cache.read_json", lambda *a, **k: None)
    hd._fixtures_cache.clear()

    payload = hd.build_port_vale_fixtures(force_refresh=True)

    assert payload["next"]["opponent"]["name"] == "Colchester United"
    postponed = [m for m in payload["matches"] if m["postponed"]]
    assert [m["opponent"]["name"] for m in postponed] == ["Northampton Town"]
