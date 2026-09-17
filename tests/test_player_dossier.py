from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import player_dossier as dossier


SAMPLE_ROWS = [
    {
        "playerId": 109047,
        "name": "Mo Faal",
        "age": 22,
        "height": "6'5\"",
        "foot": "Right",
        "club": "FC Port Vale",
        "league": "League Two",
        "season": "26/27",
        "minutes": 612,
        "matchCount": 9,
        "position": "CENTER_FORWARD",
        "positionLabel": "Centre-forward",
        "overall": 71.4,
        "iterationId": 99,
        "squadId": 7,
        "bestProfile": "PV Finishing",
        "bestProfileScore": 82,
        "profileScores": {
            "PV Finishing": 82,
            "PV Hold-up": 74,
            "PV Pressing": 0.61,
        },
    },
    {
        "playerId": 109047,
        "name": "Mo Faal",
        "age": 22,
        "height": "6'5\"",
        "foot": "Right",
        "club": "FC Port Vale",
        "league": "League Two",
        "season": "26/27",
        "minutes": 180,
        "matchCount": 4,
        "position": "LEFT_WINGER",
        "positionLabel": "Left winger",
        "overall": 64.0,
        "iterationId": 99,
        "squadId": 7,
        "profileScores": {
            "PV Dribbling": 70,
            "PV Crossing": 58,
        },
    },
]


def test_dossier_builds_from_local_rows_without_impect(monkeypatch):
    monkeypatch.setattr(dossier, "_standouts_player_rows", lambda: SAMPLE_ROWS)
    monkeypatch.setattr(dossier, "_pipeline_row_for_player", lambda _pid: None)
    monkeypatch.setattr(dossier, "_split_player_activity", lambda *_args, **_kw: ([], []))

    payload = dossier.build_player_dossier(109047)

    assert payload["source"] == "database"
    player = payload["player"]
    assert player["name"] == "Mo Faal"
    assert player["club"] == "FC Port Vale"
    assert player["primary_position"] == "CENTER_FORWARD"
    assert player["minutes"] == 612
    assert {row["code"] for row in player["positions"]} == {"CENTER_FORWARD", "LEFT_WINGER"}
    finishing = next(row for row in payload["profiles"] if "Finish" in row["label"] or "Finish" in row["name"])
    assert finishing["pct"] == 82
    pressing = next(row for row in payload["profiles"] if "Press" in row["label"] or "Press" in row["name"])
    assert pressing["pct"] == 61
    assert payload["profiles_by_position"]["LEFT_WINGER"]
    assert payload["games_deferred"] is True


def test_missing_player_is_404(monkeypatch):
    monkeypatch.setattr(dossier, "_standouts_player_rows", lambda: [])
    monkeypatch.setattr(dossier, "_pipeline_row_for_player", lambda _pid: None)
    with pytest.raises(HTTPException) as exc:
        dossier.build_player_dossier(1)
    assert exc.value.status_code == 404
    assert "local player database" in str(exc.value.detail)


def test_page_uses_identity_and_analytics_layout():
    html = (dossier.STANDALONE_DIR / "player-dossier.html").read_text(encoding="utf-8")
    css = (dossier.STANDALONE_DIR.parent / "static" / "player-dossier.css").read_text(encoding="utf-8")
    js = (dossier.STANDALONE_DIR.parent / "static" / "player-dossier.js").read_text(encoding="utf-8")
    assert 'class="pd-shell"' in html
    assert 'class="pd-identity"' in html
    assert 'class="pd-analytics"' in html
    assert 'id="pdProfileBars"' in html
    assert "grid-template-columns: minmax(280px, 340px)" in css
    assert "plotly" not in html.lower()
    assert "Loading player dossier from Impect" not in js
    assert "Loading recent games" not in js
    assert "Loading fixtures" not in js
    assert "renderRadarSvg" in js
    assert "pd-radar-svg" in css
    assert "profilesByPosition" in js
    assert "pdHeroMetrics" not in html
    assert 'id="pdFactorStats"' in html
    assert "loadFactors" in js
    assert "selectProfile" in js
    assert 'id="pdFotmobCard"' in html
    assert "FBRef snapshot" not in html
    assert "renderFotmob" in js
    assert "renderFbref" not in js


def test_fotmob_snapshot_keeps_this_season_and_rejects_old_years():
    from app.player_web_enrichment import _parse_fotmob_season_snapshot

    payload = {
        "id": 1130792,
        "mainLeague": {
            "leagueName": "League Two",
            "season": "2026/2027",
            "stats": [
                {"title": "Matches", "localizedTitleId": "matches_uppercase", "value": 2},
                {"title": "Minutes played", "localizedTitleId": "minutes_played", "value": 105},
                {"title": "Goals", "localizedTitleId": "goals", "value": 0},
                {"title": "Assists", "localizedTitleId": "assists", "value": 0},
            ],
        },
        "primaryTeam": {"teamName": "Port Vale"},
        "meta": {"pageurl": "/players/1130792/mo-faal"},
    }
    snap = _parse_fotmob_season_snapshot(payload)
    assert snap["games"] == 2
    assert snap["minutes"] == 105
    assert snap["goals"] == 0
    assert snap["assists"] == 0
    assert snap["squad"] == "Port Vale"
    stale = dict(payload)
    stale["mainLeague"] = dict(payload["mainLeague"], season="2019/2020")
    assert _parse_fotmob_season_snapshot(stale) is None


class _FakeImpect:
    def _fetch_player_scores(self, iteration_id, squad_id, positions, min_games):
        return (
            [
                {
                    "playerId": 109047,
                    "playerScores": [
                        {"playerScoreId": 1, "value": 2.41},
                        {"playerScoreId": 2, "value": 1.83},
                        {"playerScoreId": 3, "value": 0.4},
                    ],
                }
            ],
            "https://example.test",
        )

    def _fetch_player_profile_definitions(self):
        return {
            "PV Hold-up": {
                "name": "PV Hold-up",
                "factors": [
                    {"name": "hold_up_play", "weight": 0.5},
                    {"name": "link_play", "weight": 0.3},
                    {"name": "aerials", "weight": 0.2},
                ],
            }
        }

    def _fetch_player_score_catalog(self):
        by_id = {
            1: {"id": 1, "name": "hold_up_play", "label": "Hold-up play"},
            2: {"id": 2, "name": "link_play", "label": "Link play"},
            3: {"id": 3, "name": "aerials", "label": "Aerials won"},
        }
        return by_id, {row["name"]: row for row in by_id.values()}

    def _resolve_profile_definition(self, profile_name, definitions):
        return definitions.get(profile_name)

    def _resolve_factor_score_id(self, factor, scores_by_name):
        entry = scores_by_name.get(str(factor.get("name") or "").strip())
        return entry["id"] if entry else None

    def _player_score_value(self, row, score_id):
        for score in row.get("playerScores") or []:
            if score.get("playerScoreId") == score_id:
                return float(score["value"])
        return None

    def _cohort_values_for_key(self, *_args, **_kw):
        return [2.41, 1.1]

    def _factor_standing(self, value, cohort, inverted=False):
        return 80.0


def test_profile_factors_come_from_impect_without_blocking_cache(monkeypatch):
    dossier._FACTORS_CACHE.clear()
    monkeypatch.setattr(dossier, "_standouts_player_rows", lambda: SAMPLE_ROWS)
    monkeypatch.setattr(dossier, "_pipeline_row_for_player", lambda _pid: None)
    monkeypatch.setattr(dossier, "_split_player_activity", lambda *_args, **_kw: ([], []))
    monkeypatch.setattr(dossier, "_impect", lambda: _FakeImpect())

    payload = dossier.build_player_profile_factors(109047, position="CENTER_FORWARD")

    assert payload["source"] == "impect"
    hold = next(row for row in payload["profiles"] if "Hold" in row["name"] or "Hold" in row["label"])
    labels = [row["label"] for row in hold["factors"]]
    assert any("Hold" in label for label in labels)
    assert hold["factors"][0]["weight"] >= hold["factors"][-1]["weight"]
    assert hold["factors"][0]["valueLabel"] == "2.41"
