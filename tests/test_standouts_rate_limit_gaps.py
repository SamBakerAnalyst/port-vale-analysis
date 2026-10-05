"""A rate-limited club must not silently vanish from the season player list.

Oct 2026: Malik Mothersille's player page 404'd because Wycombe's winger rows
hit a 429 during the morning rebuild and the whole club/position was dropped.
"""

from __future__ import annotations

from fastapi import HTTPException

from app import home_dashboard as hd
from app import main as impect


def _rate_limited_once(calls: dict[int, int], flaky: set[int], always: set[int] = frozenset()):
    def fetch(iteration_id, squad_id, positions, min_games):
        calls[squad_id] = calls.get(squad_id, 0) + 1
        if squad_id in always or (squad_id in flaky and calls[squad_id] == 1):
            raise HTTPException(status_code=429, detail="rate limit")
        return [{"playerId": squad_id * 10, "squadId": squad_id}], "url"

    return fetch


def _setup_fetch(monkeypatch, fetch):
    impect._iteration_scores_cache.clear()
    impect._squad_score_failures.clear()
    monkeypatch.setattr(impect, "SQUAD_SCORES_RETRY_PAUSE_SECONDS", 0.0)
    monkeypatch.setattr(impect, "_fetch_squad_ids", lambda iteration_id: [1, 2, 3])
    monkeypatch.setattr(impect, "_fetch_profile_scores", fetch)


def test_a_rate_limited_club_is_retried_not_dropped(monkeypatch):
    calls: dict[int, int] = {}
    _setup_fetch(monkeypatch, _rate_limited_once(calls, flaky={2}))

    rows = impect._fetch_iteration_profile_scores(2117, ["LEFT_WINGER"], 0)

    assert sorted(row["playerId"] for row in rows) == [10, 20, 30]
    assert calls[2] == 2
    assert impect.squad_score_failures_since("LEFT_WINGER", 0) == []


def test_an_incomplete_list_is_flagged_and_not_cached(monkeypatch):
    calls: dict[int, int] = {}
    _setup_fetch(monkeypatch, _rate_limited_once(calls, flaky=set(), always={2}))

    rows = impect._fetch_iteration_profile_scores(2117, ["LEFT_WINGER"], 0)

    assert sorted(row["playerId"] for row in rows) == [10, 30]
    assert impect.squad_score_failures_since("LEFT_WINGER", 0) == [2117]
    assert impect._iteration_scores_cache == {}, "a partial list must not be served for hours"


def _row(iteration: int, player: int, position: str) -> dict:
    return {
        "id": f"{iteration}:{player}",
        "playerId": player,
        "name": f"P{player}",
        "position": position,
        "overall": 50.0,
    }


def _setup_season(monkeypatch, *, fresh, failures, previous, warnings=None):
    monkeypatch.setattr(impect, "ALLOWED_POSITIONS", ["LEFT_WINGER", "GOALKEEPER"])
    monkeypatch.setattr(hd, "_resolve_standouts_season_mode", lambda: ("current", "26/27"))
    monkeypatch.setattr(hd, "_previous_standouts_season_rows", lambda mode: previous)
    monkeypatch.setattr(hd.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        hd,
        "_load_season_position_players",
        lambda position, season_mode: (fresh.get(position, []), (warnings or {}).get(position)),
    )
    monkeypatch.setattr(
        impect,
        "squad_score_failures_since",
        lambda position, since: failures.get(position, []),
    )


def test_season_build_keeps_last_good_rows_for_a_league_that_failed(monkeypatch):
    previous = [
        _row(2117, 106333, "LEFT_WINGER"),  # Malik — League One, failed today
        _row(2120, 555, "LEFT_WINGER"),  # League Two loaded fine; left the list
        _row(2117, 777, "GOALKEEPER"),
    ]
    _setup_season(
        monkeypatch,
        fresh={"LEFT_WINGER": [_row(2117, 1, "LEFT_WINGER")], "GOALKEEPER": [_row(2117, 777, "GOALKEEPER")]},
        failures={"LEFT_WINGER": [2117]},
        previous=previous,
    )

    payload = hd._build_standouts_season_payload()
    ids = sorted(row["id"] for row in payload["players"])

    assert ids == ["2117:1", "2117:106333", "2117:777"]
    assert len(payload["warnings"]) == 1


def test_season_build_keeps_a_whole_position_when_it_fails(monkeypatch):
    previous = [_row(2117, 777, "GOALKEEPER"), _row(2120, 888, "GOALKEEPER")]
    _setup_season(
        monkeypatch,
        fresh={"LEFT_WINGER": [_row(2117, 1, "LEFT_WINGER")]},
        failures={},
        previous=previous,
        warnings={"GOALKEEPER": "Goalkeeper: Impect API rate limit — retries exhausted."},
    )

    payload = hd._build_standouts_season_payload()

    assert sorted(row["id"] for row in payload["players"]) == ["2117:1", "2117:777", "2120:888"]


def test_clean_build_does_not_resurrect_departed_players(monkeypatch):
    _setup_season(
        monkeypatch,
        fresh={"LEFT_WINGER": [_row(2117, 1, "LEFT_WINGER")]},
        failures={},
        previous=[_row(2117, 106333, "LEFT_WINGER")],
    )

    payload = hd._build_standouts_season_payload()

    assert [row["id"] for row in payload["players"]] == ["2117:1"]
    assert payload["warnings"] == []
