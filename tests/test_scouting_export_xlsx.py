from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.scouting_export_xlsx import build_scouting_all_positions_xlsx, build_scouting_export_xlsx


class ScoutingExportXlsxTests(unittest.TestCase):
    def test_build_scouting_export_xlsx_includes_profile_columns(self) -> None:
        body = SimpleNamespace(
            position_label="Left back",
            generated_at="12 Jun 2026",
            leagues=["League Two"],
            min_minutes=450,
            scoring_note="League-relative percentiles.",
            profiles=[
                SimpleNamespace(api_name="PV - Defensive (LB/LWB)", apiName="PV - Defensive (LB/LWB)", label="Defensive", weight=20),
                SimpleNamespace(api_name="PV - Offensive (LB/LWB)", apiName="PV - Offensive (LB/LWB)", label="Offensive", weight=0),
            ],
            players=[
                SimpleNamespace(
                    rank=1,
                    name="Test Player",
                    age=24,
                    minutes=1200,
                    height="180",
                    foot="L",
                    league="League Two",
                    club="Test FC",
                    overall=88.5,
                    profile_scores={"PV - Defensive (LB/LWB)": 90.0, "PV - Offensive (LB/LWB)": 87.0},
                    profileScores={"PV - Defensive (LB/LWB)": 90.0, "PV - Offensive (LB/LWB)": 87.0},
                )
            ],
        )

        xlsx_bytes = build_scouting_export_xlsx(body)
        self.assertTrue(xlsx_bytes.startswith(b"PK"))

    def test_build_scouting_all_positions_xlsx_creates_workbook(self) -> None:
        xlsx_bytes = build_scouting_all_positions_xlsx(
            sheets=[
                {
                    "positionLabel": "Left back",
                    "profiles": [
                        {"apiName": "PV - Defensive (LB/LWB)", "label": "Defensive"},
                        {"apiName": "PV - Offensive (LB/LWB)", "label": "Offensive"},
                    ],
                    "players": [
                        {
                            "name": "A",
                            "age": 22,
                            "minutes": 900,
                            "height": "180",
                            "foot": "R",
                            "league": "League Two",
                            "club": "Club A",
                            "profileScores": {
                                "PV - Defensive (LB/LWB)": 80.0,
                                "PV - Offensive (LB/LWB)": 70.0,
                            },
                        }
                    ],
                }
            ],
            generated_at="12 Jun 2026",
            leagues=["League Two"],
            min_minutes=450,
            season_mode_label="Current season",
            scoring_note="League-relative percentiles.",
        )
        self.assertTrue(xlsx_bytes.startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
