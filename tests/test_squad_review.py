import unittest

from app.squad_review import (
    _apply_selections_to_payload,
    _charts_cache_key,
    _charts_payload_from_breakdowns,
    _comparison_cache_key,
    _comparison_export_filename,
    _drilldowns_are_placeholder_standing,
    _filter_charts_to_comparison,
    _limit_drilldown_to_top_weighted,
    _merge_player_drilldowns_into_charts,
    _player_review_scores,
    _values_for_factor_labels,
)
from app.label_utils import full_stat_label, humanize_profile_name
from app.squad_review_pdf import build_squad_review_full_pdf, build_squad_review_pdf


class TestSquadReviewScores(unittest.TestCase):
    def test_slide_uses_exact_impect_profile_not_cohort_rank(self) -> None:
        profile_name = "PV - RIGHT SIDE DUELER"
        row = {
            "profileScores": [
                {"profileName": profile_name, "value": 0.42},
            ]
        }
        # 0.42 is the top of this tiny cohort, so a percentile rank would land near 100.
        league_cohort = {"pv - right side dueler": [0.10, 0.20, 0.42]}

        scores, league, _cross, raw, methods = _player_review_scores(
            row,
            [profile_name],
            league_cohort,
        )

        self.assertEqual(scores[profile_name], 42.0)
        self.assertEqual(raw[profile_name], 0.42)
        self.assertEqual(methods[profile_name], "impect_profile")
        self.assertNotEqual(scores[profile_name], league[profile_name])
        self.assertGreaterEqual(league[profile_name], 80.0)

    def test_minimum_profile_stays_the_impect_score_not_one_percent(self) -> None:
        profile_name = "PV - LEFT SIDE DUELER"
        row = {
            "profileScores": [
                {"profileName": profile_name, "value": 0.10},
            ]
        }
        # Large cohort: the percentile floor is 1%, which is what the slide was showing.
        league_cohort = {
            "pv - left side dueler": [0.10] + [0.10 + i * 0.01 for i in range(1, 80)]
        }

        scores, league, *_ = _player_review_scores(row, [profile_name], league_cohort)

        self.assertEqual(scores[profile_name], 10.0)
        self.assertEqual(league[profile_name], 1.0)


class TestSquadReviewBreakdowns(unittest.TestCase):
    def test_factor_values_align_by_label(self) -> None:
        aligned = _values_for_factor_labels(
            ["Aerial duels won", "Clearances"],
            ["Clearances", "Aerial duels won"],
            [8.0, 12.0],
        )
        self.assertEqual(aligned, [12.0, 8.0])

    def test_missing_factor_stays_blank(self) -> None:
        aligned = _values_for_factor_labels(
            ["Aerial duels won", "Blocks"],
            ["Aerial duels won"],
            [12.0],
        )
        self.assertEqual(aligned, [12.0, None])


class TestSquadReviewChartsPayload(unittest.TestCase):
    def test_breakdowns_become_radar_and_bar_series(self) -> None:
        page = _comparison_page()
        payload = _charts_payload_from_breakdowns(page, page["profileBreakdowns"])
        drilldown = payload["profile_drilldowns"][0]
        self.assertEqual(drilldown["profile"], "PV - AERIAL CB")
        self.assertEqual(drilldown["labels"], ["Aerial duels won"])
        self.assertEqual(drilldown["players"][0]["player"], "Connor Hall")
        self.assertEqual(drilldown["players"][0]["radar_values"], [80.0])
        self.assertEqual(drilldown["players"][1]["bar_raw_values"], [9.0])
        self.assertEqual(payload["players"][1]["player"], "Cameron Humphreys")

    def test_charts_come_from_player_score_drilldowns(self) -> None:
        page = _comparison_page()
        payload = _merge_player_drilldowns_into_charts(
            page,
            [
                {
                    "pv - aerial cb": {
                        "profile": "PV - AERIAL CB",
                        "bar_labels": ["Opponents bypassed"],
                        "bar_weights": [20.0],
                        "bar_raw_values": [19.2],
                        "bar_metric_values": [0.192],
                        "bar_radar_values": [80.0],
                    }
                },
                {
                    "pv - aerial cb": {
                        "profile": "PV - AERIAL CB",
                        "bar_labels": ["Opponents bypassed"],
                        "bar_weights": [20.0],
                        "bar_raw_values": [6.6],
                        "bar_metric_values": [0.066],
                        "bar_radar_values": [40.0],
                    }
                },
            ],
        )
        players = payload["profile_drilldowns"][0]["players"]
        self.assertEqual(payload["source"], "player_scores")
        self.assertEqual(players[0]["bar_raw_values"], [19.2])
        self.assertEqual(players[1]["bar_raw_values"], [6.6])


class TestSquadReviewChartTitles(unittest.TestCase):
    def test_aerial_cb_profile_keeps_full_name(self) -> None:
        self.assertEqual(humanize_profile_name("PV - AERIAL CB"), "Aerial CB")

    def test_top_weighted_factors_are_the_first_three(self) -> None:
        limited = _limit_drilldown_to_top_weighted(
            {
                "profile": "PV - AERIAL CB",
                "bar_labels": ["Aerial duel win %", "Aerial duels", "Teammates added", "Clearances"],
                "bar_weights": [42.0, 28.0, 18.0, 12.0],
                "labels": ["Teammates added", "Clearances", "Aerial duels"],
                "players": [
                    {
                        "player": "Connor Hall",
                        "bar_radar_values": [80.0, 60.0, 40.0, 20.0],
                        "bar_raw_values": [62.0, 10.0, 6.0, 4.0],
                    }
                ],
            }
        )
        self.assertEqual(
            limited["bar_labels"],
            ["Aerial duel win %", "Aerial duels", "Ratio — add teammates"],
        )
        self.assertEqual(limited["labels"], limited["bar_labels"])
        self.assertEqual(limited["players"][0]["radar_values"], [80.0, 60.0, 40.0])

    def test_limiter_keeps_per90_metric_values(self) -> None:
        limited = _limit_drilldown_to_top_weighted(
            {
                "bar_labels": ["Opponents bypassed", "Passes", "Clearances"],
                "bar_weights": [40.0, 30.0, 10.0],
                "players": [
                    {
                        "bar_radar_values": [100.0, 50.0, 10.0],
                        "bar_raw_values": [8.2, 41.0, 1.0],
                        "bar_metric_values": [8.2, 41.05, 1.1],
                    }
                ],
            }
        )
        self.assertEqual(limited["players"][0]["bar_metric_values"], [8.2, 41.05, 1.1])

    def test_aerial_duel_win_rate_is_promoted_to_first(self) -> None:
        limited = _limit_drilldown_to_top_weighted(
            {
                "bar_labels": ["Defensive headers", "Aerial duel win %", "Attacking headers"],
                "bar_weights": [26.7, 26.7, 9.3],
                "players": [
                    {"bar_radar_values": [70.0, 90.0, 40.0], "bar_raw_values": [8.0, 62.0, 3.0]}
                ],
            }
        )
        self.assertEqual(
            limited["bar_labels"],
            ["Aerial duel win %", "Defensive header score", "Offensive header score"],
        )
        self.assertEqual(limited["players"][0]["radar_values"], [90.0, 70.0, 40.0])

    def test_every_profile_uses_the_three_heaviest_factors(self) -> None:
        limited = _limit_drilldown_to_top_weighted(
            {
                "profile": "PV - PROGRESSIVE CB",
                "bar_labels": [
                    "Passes",
                    "Aerial duel win %",
                    "Interceptions",
                    "Clearances",
                ],
                "bar_weights": [8.0, 12.0, 40.0, 30.0],
                "labels": ["Passes", "Clearances", "Interceptions"],
                "players": [
                    {
                        "bar_radar_values": [20.0, 50.0, 80.0, 70.0],
                        "bar_raw_values": [1.0, 2.0, 3.0, 4.0],
                    }
                ],
            }
        )
        self.assertEqual(
            limited["bar_labels"],
            ["Interception score", "Clearances", "Aerial duel win %"],
        )
        self.assertEqual(limited["players"][0]["radar_values"], [80.0, 70.0, 50.0])
        self.assertEqual(len(limited["bar_labels"]), 3)

    def test_full_stat_label_keeps_complete_impect_names(self) -> None:
        self.assertEqual(full_stat_label("Teammates added"), "Ratio — add teammates")
        self.assertEqual(
            full_stat_label("Aerial duels in central zone"),
            "Number of aerial duels in packing zone CB",
        )
        self.assertEqual(full_stat_label("Defensive headers"), "Defensive header score")
        self.assertEqual(full_stat_label("Aerial duel win %"), "Aerial duel win %")

    def test_all_fifty_bars_are_treated_as_placeholder_cache(self) -> None:
        payload = {
            "profile_drilldowns": [
                {
                    "players": [
                        {"bar_radar_values": [50.0, 50.0, 50.0]},
                        {"bar_radar_values": [50.0, 50.0, 50.0]},
                    ]
                }
            ]
        }
        self.assertTrue(_drilldowns_are_placeholder_standing(payload))
        payload["profile_drilldowns"][0]["players"][0]["bar_radar_values"] = [20.0, 80.0, 50.0]
        payload["profile_drilldowns"][0]["players"][1]["bar_radar_values"] = [12.0, 71.0, 44.0]
        self.assertFalse(_drilldowns_are_placeholder_standing(payload))

    def test_third_step_bars_are_treated_as_tiny_cohort_cache(self) -> None:
        payload = {
            "profile_drilldowns": [
                {
                    "players": [
                        {"bar_radar_values": [33.0, 67.0, 33.0]},
                        {"bar_radar_values": [67.0, 67.0, 33.0]},
                        {"bar_radar_values": [33.0, 50.0, 33.0]},
                        {"bar_radar_values": [17.0, 17.0, 1.0]},
                    ]
                }
            ]
        }
        self.assertTrue(_drilldowns_are_placeholder_standing(payload))

    def test_charts_cache_key_is_per_position_not_player_set(self) -> None:
        left = _charts_cache_key("26/27", "CENTRAL_DEFENDER", 0)
        right = _charts_cache_key("26/27", "CENTRAL_DEFENDER", 0, [1, 2, 3])
        self.assertNotIn("1-2-3", left)
        self.assertIn("CENTRAL_DEFENDER", left)
        self.assertNotEqual(left, right)
        self.assertNotEqual(
            _charts_cache_key("26/27", "CENTRAL_DEFENDER", 0),
            _charts_cache_key("26/27", "CENTRAL_DEFENDER", 600),
        )

    def test_charts_filter_keeps_selected_players(self) -> None:
        payload = {
            "profile_drilldowns": [
                {
                    "players": [
                        {"player": "Connor Hall", "bar_raw_values": [8.0]},
                        {"player": "Cameron Humphreys", "bar_raw_values": [6.0]},
                        {"player": "Jordan Gabriel", "bar_raw_values": [1.0]},
                    ]
                }
            ],
            "players": [
                {"player": "Connor Hall"},
                {"player": "Cameron Humphreys"},
                {"player": "Jordan Gabriel"},
            ],
        }
        filtered = _filter_charts_to_comparison(
            payload,
            {
                "players": [
                    {"name": "Connor Hall"},
                    {"name": "Cameron Humphreys"},
                ]
            },
        )
        names = [player["player"] for player in filtered["profile_drilldowns"][0]["players"]]
        self.assertEqual(names, ["Connor Hall", "Cameron Humphreys"])


def _comparison_page() -> dict:
    return {
        "position": "CENTRAL_DEFENDER",
        "positionLabel": "Centre-back",
        "positionShortLabel": "CB",
        "competition": "League Two",
        "season": "26/27",
        "profiles": [{"apiName": "PV - AERIAL CB", "label": "Aerial central"}],
        "players": [
            {
                "id": 1,
                "name": "Connor Hall",
                "minutes": 430,
                "positionLabel": "Centre-back",
                "club": "FC Port Vale",
                "profileScores": {"PV - AERIAL CB": 55.0},
            },
            {
                "id": 2,
                "name": "Cameron Humphreys",
                "minutes": 406,
                "positionLabel": "Centre-back",
                "club": "FC Port Vale",
                "profileScores": {"PV - AERIAL CB": 59.0},
            },
        ],
        "scoring": {"note": "Exact Impect ratings"},
        "profileBreakdowns": [
            {
                "profile": "PV - AERIAL CB",
                "label": "Aerial central",
                "factors": [
                    {
                        "label": "Aerial duels won",
                        "scores": [12.0, 9.0],
                        "standings": [80.0, 40.0],
                    }
                ],
            }
        ],
    }


class TestSquadReviewFullPdf(unittest.TestCase):
    def test_overview_pdf_does_not_need_breakdowns(self) -> None:
        pdf_bytes = build_squad_review_pdf([_comparison_page()])
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_full_pdf_includes_factor_breakdown_pages(self) -> None:
        pdf_bytes = build_squad_review_full_pdf([_comparison_page()])
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertIn(b"/Count 2", pdf_bytes)

    def test_full_export_filename_is_per_position(self) -> None:
        self.assertEqual(
            _comparison_export_filename("Centre-back", full=True),
            "port-vale-centre-back-comparison-full.pdf",
        )


class TestSquadReviewCache(unittest.TestCase):
    def test_cache_key_is_season_and_minutes(self) -> None:
        self.assertEqual(_comparison_cache_key("26/27", 0), "26-27-0")
        self.assertEqual(_comparison_cache_key("26/27", 90), "26-27-90")
        self.assertEqual(_comparison_cache_key("", 0), "auto-0")

    def test_selections_filter_players_without_dropping_roster(self) -> None:
        payload = {
            "comparisons": [
                {
                    "position": "CENTRAL_DEFENDER",
                    "roster": [
                        {"id": 1, "name": "A"},
                        {"id": 2, "name": "B"},
                        {"id": 3, "name": "C"},
                    ],
                    "players": [
                        {"id": 1, "name": "A"},
                        {"id": 2, "name": "B"},
                        {"id": 3, "name": "C"},
                    ],
                }
            ]
        }
        applied = _apply_selections_to_payload(
            payload, {"CENTRAL_DEFENDER": [2, 3]}, 5
        )
        page = applied["comparisons"][0]
        self.assertEqual([player["id"] for player in page["players"]], [2, 3])
        self.assertEqual([player["id"] for player in page["roster"]], [1, 2, 3])
        self.assertEqual(page["selectedPlayerIds"], [2, 3])

    def test_selections_relabel_profiles_from_api_name(self) -> None:
        payload = {
            "comparisons": [
                {
                    "position": "CENTRAL_DEFENDER",
                    "profiles": [{"apiName": "PV - AERIAL CB", "label": "AERIAL central"}],
                    "roster": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
                    "players": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
                }
            ]
        }
        applied = _apply_selections_to_payload(payload, {}, 5)
        self.assertEqual(applied["comparisons"][0]["profiles"][0]["label"], "Aerial CB")


if __name__ == "__main__":
    unittest.main()
