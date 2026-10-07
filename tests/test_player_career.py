"""Player career — FotMob seasons linked to the Impect seasons we hold."""

from __future__ import annotations

from app import player_career as career


FOTMOB = {
    "careerHistory": {
        "careerItems": {
            "senior": {
                "seasonEntries": [
                    {
                        "seasonName": "2025/2026", "team": "Bolton Wanderers", "teamId": 8559,
                        "appearances": "38", "goals": "2", "assists": "0", "rating": {"rating": "6.86"},
                        "transferType": None,
                        "tournamentStats": [
                            {"isFriendly": False, "leagueName": "EFL Trophy", "appearances": "3"},
                            {"isFriendly": False, "leagueName": "League One", "appearances": "35"},
                        ],
                    },
                    {
                        "seasonName": "2024/2025", "team": "Hull City", "teamId": 8667, "appearances": "22",
                        "tournamentStats": [{"isFriendly": False, "leagueName": "Championship", "appearances": "20"}],
                    },
                    {
                        "seasonName": "2024/2025", "team": "Wycombe Wanderers", "teamId": 8676, "appearances": "16",
                        "transferType": {"localizationKey": "on_loan"},
                        "tournamentStats": [{"isFriendly": False, "leagueName": "League One", "appearances": "16"}],
                    },
                ]
            },
            "youth": {
                "seasonEntries": [
                    {
                        "seasonName": "2021/2022", "team": "Chelsea U23", "teamId": 357211, "appearances": "20",
                        "tournamentStats": [{"isFriendly": False, "leagueName": "Premier League 2", "appearances": "20"}],
                    },
                ]
            },
        }
    }
}

IMPECT = [
    {"season": "25/26", "competition_name": "League One", "club": "Bolton Wanderers",
     "impect_iteration_id": 1500, "impect_squad_id": 10, "minutes": 2213},
    {"season": "24/25", "competition_name": "League One", "club": "Wycombe Wanderers",
     "impect_iteration_id": 1021, "impect_squad_id": 11, "minutes": 1295},
    {"season": "21/22", "competition_name": "Premier League 2", "club": "FC Chelsea U21",
     "impect_iteration_id": 429, "impect_squad_id": 13, "minutes": 1563},
    {"season": "20/21", "competition_name": "League Two", "club": "Walsall",
     "impect_iteration_id": 300, "impect_squad_id": 14, "minutes": 182},
]


def test_fotmob_seasons_parse_with_the_league_not_the_cup():
    rows = career.parse_fotmob_career(FOTMOB)
    bolton = rows[0]
    assert (bolton["season"], bolton["club"], bolton["league"], bolton["apps"]) == ("25/26", "Bolton Wanderers", "League One", 38)
    assert bolton["logo"].endswith("/8559_small.png")
    assert next(row for row in rows if row["club"] == "Wycombe Wanderers")["on_loan"] is True


def test_impect_seasons_link_to_the_right_club_and_youth_side():
    rows = career.link_impect_seasons(career.parse_fotmob_career(FOTMOB), IMPECT)
    linked = {(row["season"], row["club"]): row["impect"] for row in rows}
    assert linked[("25/26", "Bolton Wanderers")]["iteration_id"] == 1500
    assert linked[("24/25", "Wycombe Wanderers")]["squad_id"] == 11
    assert linked[("24/25", "Hull City")] is None
    assert linked[("21/22", "Chelsea U23")]["iteration_id"] == 429


def test_impect_seasons_fotmob_misses_are_kept():
    rows = career.link_impect_seasons(career.parse_fotmob_career(FOTMOB), IMPECT)
    walsall = next(row for row in rows if row["club"] == "Walsall")
    assert walsall["source"] == "impect" and walsall["impect"]["iteration_id"] == 300
    assert [row["season"] for row in rows] == sorted((row["season"] for row in rows), reverse=True)


def test_season_profiles_are_fetched_once_and_kept_on_disk(tmp_path, monkeypatch):
    from app import player_dossier as dossier

    calls = []

    def fake_live(player_id, iteration_id, squad_id):
        calls.append((player_id, iteration_id, squad_id))
        profiles = [{"name": "PV - Creator", "label": "Creator", "score": 0.6, "pct": 60}]
        return {
            "positions": [{"code": "DEFENSE_MIDFIELD", "label": "Defensive midfield", "abbrev": "DM", "minutes": 900}],
            "by_position": {"DEFENSE_MIDFIELD": profiles},
            "complete": True,
        }

    monkeypatch.setattr(dossier, "SEASON_PROFILES_PATH", tmp_path / "season-profiles.json")
    monkeypatch.setattr(dossier, "_SEASON_PROFILES_CACHE", {})
    monkeypatch.setattr(dossier, "_season_disk_loaded", False)
    monkeypatch.setattr(dossier, "_live_season_profiles", fake_live)
    monkeypatch.setattr(dossier, "_cached_rows_for_player", lambda pid: [])

    first = dossier.build_season_profiles(7, 1465, 930)
    again = dossier.build_season_profiles(7, 1465, 930, "DEFENSE_MIDFIELD")
    assert first["position"] == again["position"] == "DEFENSE_MIDFIELD"
    assert calls == [(7, 1465, 930)]

    monkeypatch.setattr(dossier, "_SEASON_PROFILES_CACHE", {})
    monkeypatch.setattr(dossier, "_season_disk_loaded", False)
    assert dossier.build_season_profiles(7, 1465, 930)["profiles"][0]["label"] == "Creator"
    assert calls == [(7, 1465, 930)]
