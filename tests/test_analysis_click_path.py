"""Analysis click-path serves stale disk and never calls Impect."""

from __future__ import annotations

import json
import time

import app.analysis_cache as analysis_cache
from app.analysis_cache import write_json
from app.blocks_analysis import MATCH_STATS_CACHE_VERSION, build_blocks_analysis_payload
from app.home_dashboard import build_port_vale_fixtures
from app.player_cards import build_player_cards_squad
from app.pre_match import (
    PreMatchReportRequest,
    build_pre_match_fixtures,
    build_pre_match_report,
    pre_match_meta,
)
from app.set_piece_pre_match import (
    SetPiecePreMatchRequest,
    build_set_piece_pre_match_report,
    fixtures_from_cached_reports,
    meta_from_cached_reports,
)
from app.xg_chance_analysis import (
    build_xg_chance_fixtures,
    build_xg_chance_report,
    xg_chance_meta,
)


def _boom(*_args, **_kwargs):
    raise AssertionError("click path must not call Impect")


def test_read_json_allow_stale_serves_expired_file(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    write_json("pre-match", "report_old", {"opponent": {"name": "Bradford"}})
    path = tmp_path / "pre-match" / "report_old.json"
    old = time.time() - 30 * 24 * 3600
    path.touch()
    # rewrite then age the file
    write_json("pre-match", "report_old", {"opponent": {"name": "Bradford"}})
    import os

    os.utime(path, (old, old))
    assert analysis_cache.read_json("pre-match", "report_old", ttl=60) is None
    stale = analysis_cache.read_json(
        "pre-match", "report_old", ttl=60, allow_stale=True
    )
    assert stale["opponent"]["name"] == "Bradford"


def test_pre_match_click_serves_stale_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    write_json(
        "pre-match",
        "report_11_22_33",
        {"opponent": {"name": "Bradford"}, "season": "26/27"},
    )
    monkeypatch.setattr("app.pre_match._build_pre_match_report_uncached", _boom)
    report = build_pre_match_report(
        PreMatchReportRequest(iteration_id=11, squad_id=22, match_id=33, refresh=False)
    )
    assert report["opponent"]["name"] == "Bradford"
    assert report["cache"]["hit"] is True


def test_pre_match_click_miss_builds_once_then_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.set_piece_pre_match.SET_PIECE_CACHE_DIR", tmp_path / "sp")

    def _built(body):
        return {"opponent": {"id": int(body.squad_id), "name": "Built"}, "iteration_id": int(body.iteration_id)}

    monkeypatch.setattr("app.pre_match._build_pre_match_report_uncached", _built)
    monkeypatch.setattr(
        "app.pre_match._build_pre_match_fixtures_uncached",
        lambda *_args, **_kwargs: [{"match_id": 3, "opponent": {"id": 2, "name": "Built"}}],
    )
    report = build_pre_match_report(
        PreMatchReportRequest(iteration_id=1, squad_id=2, match_id=3, refresh=False)
    )
    assert report["opponent"]["name"] == "Built"
    assert report["cache"]["hit"] is False
    monkeypatch.setattr("app.pre_match._build_pre_match_report_uncached", _boom)
    cached = build_pre_match_report(
        PreMatchReportRequest(iteration_id=1, squad_id=2, match_id=3, refresh=False)
    )
    assert cached["cache"]["hit"] is True
    assert build_pre_match_fixtures(99, refresh=False)[0]["opponent"]["name"] == "Built"


def test_pre_match_recovers_old_reports_into_bar(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.set_piece_pre_match.SET_PIECE_CACHE_DIR", tmp_path / "sp")
    write_json(
        "pre-match",
        "report_2120_55_99",
        {
            "iteration_id": 2120,
            "season": "26/27",
            "opponent": {"id": 55, "name": "Bradford"},
            "fixture": {
                "match_id": 99,
                "match_day": 4,
                "kickoff_label": "Sat 3pm",
                "is_home": True,
            },
        },
    )
    monkeypatch.setattr("app.pre_match._pre_match_meta_uncached", _boom)
    monkeypatch.setattr("app.pre_match._build_pre_match_fixtures_uncached", _boom)
    monkeypatch.setattr("app.pre_match._build_pre_match_report_uncached", _boom)
    meta = pre_match_meta(refresh=False)
    assert meta.get("building") is not True
    assert meta["default_iteration_id"] == 2120
    assert any(item["id"] == 2120 for item in meta["iterations"])
    fixtures = build_pre_match_fixtures(2120, refresh=False)
    assert fixtures[0]["opponent"]["name"] == "Bradford"
    report = build_pre_match_report(
        PreMatchReportRequest(iteration_id=2120, squad_id=55, match_id=88, refresh=False)
    )
    assert report["opponent"]["name"] == "Bradford"
    assert report["cache"]["hit"] is True


def test_pre_match_meta_empty_cache_builds_once(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.set_piece_pre_match.SET_PIECE_CACHE_DIR", tmp_path / "sp")
    monkeypatch.setattr(
        "app.pre_match._pre_match_meta_uncached",
        lambda *_args, **_kwargs: {
            "competition": "League Two",
            "default_iteration_id": 2120,
            "iterations": [{"id": 2120, "season": "26/27", "label": "26/27"}],
        },
    )
    meta = pre_match_meta(refresh=False)
    assert meta.get("building") is not True
    assert meta["default_iteration_id"] == 2120
    monkeypatch.setattr("app.pre_match._pre_match_meta_uncached", _boom)
    again = pre_match_meta(refresh=False)
    assert again["default_iteration_id"] == 2120


def test_xg_click_serves_stale_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    write_json(
        "xg-report",
        "report_default_match_auto",
        {"shots": [{"id": 1}], "shotCount": 1},
    )
    monkeypatch.setattr("app.xg_chance_analysis._build_xg_chance_report_uncached", _boom)
    report = build_xg_chance_report(scope="match", refresh=False)
    assert report["shotCount"] == 1
    assert report["cache"]["hit"] is True


def test_player_cards_click_serves_stale_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.player_cards._squad_cache", {})
    from app.opponent_photos import _normalize_name_key

    disk_key = (
        f"v2feet_26/27_League Two_{_normalize_name_key('Port Vale')}___"
    )
    write_json(
        "player-cards",
        disk_key,
        {"club": "Port Vale", "players": [{"name": "Ben Heneghan"}], "player_count": 1},
    )
    monkeypatch.setattr("app.player_cards._find_club_row", _boom)
    payload = build_player_cards_squad(
        club_name="Port Vale", season="26/27", league="League Two", refresh=False
    )
    assert payload["player_count"] == 1
    assert payload["players"][0]["name"] == "Ben Heneghan"


def test_blocks_click_assembles_played_games_from_local_disks(tmp_path, monkeypatch):
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
        json.dumps(
            {
                "matches": [
                    {
                        "matchId": 101,
                        "outcome": "win",
                        "available": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "match-kpis.json").write_text(
        json.dumps(
            {
                "101": {
                    "v": MATCH_STATS_CACHE_VERSION,
                    "fingerprint": "x",
                    "fetchedAt": 1,
                    "stats": {"units": {"ATT": {"shots": 8}}, "players": []},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.blocks_analysis.build_season_matches", _boom)
    monkeypatch.setattr("app.blocks_analysis.build_block_benchmarks", _boom)
    payload = build_blocks_analysis_payload(force_refresh=False)
    assert payload.get("building") is not True
    assert payload["playedCount"] == 1
    assert payload["blocks"]


def test_blocks_click_serves_stale_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.blocks_analysis._payload_cache", {})
    write_json(
        "blocks",
        "default",
        {
            "season": "26/27",
            "blocks": [{"id": 1}],
            "currentBlockId": 1,
            "matchCount": 4,
        },
    )
    monkeypatch.setattr("app.blocks_analysis.build_season_matches", _boom)
    payload = build_blocks_analysis_payload(force_refresh=False)
    assert payload["matchCount"] == 4
    assert payload["blocks"][0]["id"] == 1


def test_countdown_fixtures_click_serves_stale_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.home_dashboard._fixtures_cache", {})
    write_json(
        "countdown-fixtures",
        "port-vale",
        {"next": {"opponent": {"name": "Bromley"}}, "upcoming": [1], "building": False},
    )
    monkeypatch.setattr("app.home_dashboard._fetch_team_fixtures_fotmob", _boom)
    payload = build_port_vale_fixtures(force_refresh=False)
    assert payload["next"]["opponent"]["name"] == "Bromley"


def test_xg_meta_never_blanks_season_bar(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.xg_chance_analysis._xg_chance_seasons", _boom)
    meta = xg_chance_meta(refresh=False)
    assert meta.get("building") is not True
    assert meta["seasons"]
    assert meta["defaultSeason"]


def test_xg_recovers_old_report_and_fixtures(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    write_json(
        "xg-report",
        "report_other_key",
        {
            "season": "26/27",
            "scope": "match",
            "shots": [{"id": 7}],
            "shotCount": 1,
            "matches": [
                {
                    "matchId": 404,
                    "matchDay": 5,
                    "opponent": {"name": "Grimsby"},
                    "isHome": True,
                }
            ],
        },
    )
    monkeypatch.setattr("app.xg_chance_analysis._build_xg_chance_report_uncached", _boom)
    report = build_xg_chance_report(season="26/27", scope="match", refresh=False)
    assert report["shotCount"] == 1
    assert report["cache"]["hit"] is True
    fixtures = build_xg_chance_fixtures("26/27", refresh=False)
    assert fixtures[0]["opponent"]["name"] == "Grimsby"


def test_player_cards_recovers_nearby_disk_key(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.player_cards._squad_cache", {})
    write_json(
        "player-cards",
        "old_key_port_vale",
        {"club": "Port Vale", "season": "26/27", "players": [{"name": "Ben Heneghan"}], "player_count": 1},
    )
    monkeypatch.setattr("app.player_cards._find_club_row", _boom)
    payload = build_player_cards_squad(
        club_name="Port Vale", season="26/27", league="League Two", refresh=False
    )
    assert payload["player_count"] == 1


def test_set_piece_recovers_old_reports_into_bar(tmp_path, monkeypatch):
    monkeypatch.setattr("app.set_piece_pre_match.SET_PIECE_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.set_piece_pre_match._REPORT_MEM_CACHE", {})
    (tmp_path / "report_2120_77_latest_0.json").write_text(
        json.dumps(
            {
                "iteration_id": 2120,
                "season": "26/27",
                "opponent": {"id": 77, "name": "Bromley"},
                "fixture": {
                    "match_id": 501,
                    "match_day": 6,
                    "kickoff_label": "Tue 7:45",
                    "is_home": False,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.set_piece_pre_match._impect", _boom)
    monkeypatch.setattr("app.set_piece_pre_match.build_pre_match_fixtures", _boom)
    meta = meta_from_cached_reports("League Two")
    assert meta["default_iteration_id"] == 2120
    fixtures = fixtures_from_cached_reports(2120)
    assert fixtures[0]["opponent"]["name"] == "Bromley"
    report = build_set_piece_pre_match_report(
        SetPiecePreMatchRequest(iteration_id=999, squad_id=77, refresh=False)
    )
    assert report["opponent"]["name"] == "Bromley"


def test_set_piece_click_serves_stale_disk(tmp_path, monkeypatch):
    monkeypatch.setattr("app.set_piece_pre_match.SET_PIECE_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.set_piece_pre_match._REPORT_MEM_CACHE", {})
    (tmp_path / "report_8_9_latest_0.json").write_text(
        json.dumps({"opponent": {"name": "Bromley", "id": 9}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.set_piece_pre_match._impect", _boom)
    monkeypatch.setattr("app.set_piece_pre_match.build_pre_match_fixtures", _boom)
    report = build_set_piece_pre_match_report(
        SetPiecePreMatchRequest(iteration_id=8, squad_id=9, refresh=False)
    )
    assert report["opponent"]["name"] == "Bromley"
    assert report["cache"]["hit"] is True
