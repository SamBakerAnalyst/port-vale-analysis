"""Finished games must not stay cached as upcoming after Impect has the score."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import app.analysis_cache as analysis_cache
from app.analysis_cache import (
    analysis_results_incomplete,
    goals_full_time,
    kickoff_should_have_result,
    write_json,
)
from app.blocks_analysis import MATCH_STATS_CACHE_VERSION, build_blocks_analysis_payload
from app.post_match.season_matches import build_season_matches
from app.pre_match import build_pre_match_fixtures


def test_kickoff_should_have_result_waits_for_full_time():
    kickoff = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
    assert kickoff_should_have_result(kickoff, now=kickoff + timedelta(hours=1)) is False
    assert kickoff_should_have_result(kickoff, now=kickoff + timedelta(hours=3)) is True
    assert kickoff_should_have_result(None) is False


def test_goals_full_time_reads_result_string_when_goals_missing():
    assert goals_full_time({"result": "1:0 (0:0)"}) == (1, 0)
    assert goals_full_time({"result": "3-1"}) == (3, 1)
    assert goals_full_time(
        {"goals": {"home": {"fullTime": 2}, "away": {"fullTime": 2}}}
    ) == (2, 2)
    assert goals_full_time({}) is None


def test_season_matches_use_result_string(monkeypatch):
    monkeypatch.setattr(
        "app.post_match.season_matches.impect_get",
        lambda *_a, **_k: {
            "data": [
                {
                    "id": 270770,
                    "available": True,
                    "scheduledDate": "2026-09-12T14:00:00Z",
                    "homeSquadId": 882,
                    "awaySquadId": 881,
                    "result": "1:0 (0:0)",
                    "goals": {"home": {}, "away": {}},
                }
            ]
        },
    )
    monkeypatch.setattr(
        "app.post_match.season_matches._squad_details",
        lambda *_a, **_k: {
            882: {"name": "Port Vale"},
            881: {"name": "Exeter City"},
        },
    )
    monkeypatch.setattr(
        "app.post_match.season_matches.enrich_squad",
        lambda row, *_a, **_k: row,
    )
    matches = build_season_matches(2120, 882)
    assert matches[0]["outcome"] == "win"
    assert matches[0]["scoreLabel"] == "H 1:0"


def test_past_unplayed_blocks_refetch_from_impect(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.blocks_analysis._payload_cache", {})
    monkeypatch.setattr("app.blocks_analysis.DATA_DIR", tmp_path)
    monkeypatch.setattr(
        "app.blocks_analysis.SEASON_MATCHES_PATH", tmp_path / "season-matches.json"
    )
    monkeypatch.setattr(
        "app.blocks_analysis.KPI_CACHE_PATH", tmp_path / "match-kpis.json"
    )
    monkeypatch.setattr("app.blocks_analysis.TARGETS_PATH", tmp_path / "targets.json")
    (tmp_path / "season-matches.json").write_text(
        __import__("json").dumps(
            {
                "matches": [
                    {
                        "matchId": 270770,
                        "scheduledDate": "2026-09-12T14:00:00Z",
                        "outcome": None,
                        "available": True,
                        "opponent": {"name": "Exeter City"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    write_json(
        "blocks",
        "default",
        {
            "playedCount": 5,
            "blocks": [
                {
                    "id": 1,
                    "fixtures": [
                        {
                            "played": True,
                            "opponentName": "Salford City",
                            "stats": {"xg": 1.0, "units": {"ATT": {"shots": 6}}},
                        }
                    ],
                }
            ],
        },
    )

    def _fresh(*_a, **_k):
        return [
            {
                "matchId": 270770,
                "scheduledDate": "2026-09-12T14:00:00Z",
                "outcome": "win",
                "available": True,
                "isHome": True,
                "scoreLabel": "H 1:0",
                "home": {"squadId": 882, "name": "Port Vale", "score": 1},
                "away": {"squadId": 881, "name": "Exeter City", "score": 0},
                "opponent": {"name": "Exeter City", "initials": "EXE"},
            }
        ]

    monkeypatch.setattr("app.blocks_analysis.build_season_matches", _fresh)
    monkeypatch.setattr(
        "app.blocks_analysis._load_match_kpis",
        lambda *_a, **_k: {
            270770: {"xg": 1.1, "units": {"ATT": {"shots": 9}}, "players": []}
        },
    )
    payload = build_blocks_analysis_payload(force_refresh=False)
    assert payload["playedCount"] == 1
    fixture = payload["blocks"][0]["fixtures"][0]
    assert fixture["opponentName"] == "Exeter City"
    assert fixture["played"] is True
    assert fixture["scoreLabel"] == "H 1:0"


def test_past_unplayed_pre_match_refetch_from_impect(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    write_json(
        "pre-match-fixtures",
        "fixtures_2120",
        {
            "fixtures": [
                {
                    "match_id": 270770,
                    "match_day": 5,
                    "played": False,
                    "scheduled_date": "2026-09-12T14:00:00Z",
                    "kickoff_label": "H Sat 12 Sep · 15:00",
                    "opponent": {"id": 881, "name": "Exeter City"},
                }
            ]
        },
    )

    def _fresh(_iteration_id):
        return [
            {
                "match_id": 270770,
                "match_day": 5,
                "played": True,
                "scheduled_date": "2026-09-12T14:00:00Z",
                "kickoff_label": "1-0",
                "opponent": {"id": 881, "name": "Exeter City"},
            }
        ]

    monkeypatch.setattr("app.pre_match._build_pre_match_fixtures_uncached", _fresh)
    monkeypatch.setattr("app.pre_match._hydrate_fixture_row", lambda row, _iid: row)
    fixtures = build_pre_match_fixtures(2120, refresh=False)
    assert fixtures[0]["played"] is True
    assert fixtures[0]["kickoff_label"] == "1-0"


def test_analysis_results_incomplete_when_exeter_cached_unplayed(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        "app.blocks_analysis.SEASON_MATCHES_PATH", tmp_path / "season-matches.json"
    )
    (tmp_path / "season-matches.json").write_text(
        __import__("json").dumps(
            {
                "matches": [
                    {
                        "matchId": 270770,
                        "scheduledDate": "2026-09-12T14:00:00Z",
                        "outcome": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert analysis_results_incomplete() is True
