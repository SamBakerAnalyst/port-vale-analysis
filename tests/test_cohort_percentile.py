import unittest

from app.main import _cohort_percentile, _factor_standing, _impect_score_0_100


class TestCohortPercentile(unittest.TestCase):
    def test_empty_cohort_returns_none(self) -> None:
        self.assertIsNone(_cohort_percentile(0.5, []))

    def test_minimum_value_is_never_zero(self) -> None:
        cohort = [0.1, 0.2, 0.3, 0.4, 0.5]
        self.assertEqual(_cohort_percentile(0.1, cohort), 10.0)

    def test_maximum_value_is_never_above_100(self) -> None:
        cohort = [0.1, 0.2, 0.3, 0.4, 0.5]
        self.assertEqual(_cohort_percentile(0.5, cohort), 90.0)

    def test_old_formula_would_have_returned_zero_for_minimum(self) -> None:
        cohort = list(range(100))
        result = _cohort_percentile(0, cohort)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result, 1.0)

    def test_tied_values_use_mid_rank(self) -> None:
        cohort = [0.2, 0.2, 0.2, 0.8]
        self.assertEqual(_cohort_percentile(0.2, cohort), 37.5)


class TestImpectScore(unittest.TestCase):
    def test_none_and_junk_are_blank(self) -> None:
        self.assertIsNone(_impect_score_0_100(None))
        self.assertIsNone(_impect_score_0_100("bad"))

    def test_zero_to_one_is_scaled_to_impect_display_units(self) -> None:
        self.assertEqual(_impect_score_0_100(0.0), 0.0)
        self.assertEqual(_impect_score_0_100(0.42), 42.0)
        self.assertEqual(_impect_score_0_100(1.0), 100.0)
        self.assertEqual(_impect_score_0_100("0.5"), 50.0)

    def test_already_display_scale_is_left_alone(self) -> None:
        self.assertEqual(_impect_score_0_100(49.0), 49.0)
        self.assertEqual(_impect_score_0_100(97.5), 97.5)


class TestFactorStanding(unittest.TestCase):
    def test_display_score_is_not_the_radar_value(self) -> None:
        # Typical LB dribble score: 0.05 displays as 5, but ranks above a 0.026 median.
        cohort = [0.00, 0.01, 0.02, 0.026, 0.03, 0.05, 0.08, 0.12]
        self.assertEqual(_impect_score_0_100(0.05), 5.0)
        standing = _factor_standing(0.05, cohort)
        self.assertIsNotNone(standing)
        self.assertGreater(standing, 50)
        self.assertGreater(standing, _impect_score_0_100(0.05))

    def test_inverted_flips_high_is_bad(self) -> None:
        cohort = [1.0, 2.0, 3.0, 8.0]
        high_is_good = _factor_standing(8.0, cohort, inverted=False)
        high_is_bad = _factor_standing(8.0, cohort, inverted=True)
        self.assertGreater(high_is_good, 50)
        self.assertLess(high_is_bad, 50)

    def test_empty_cohort_is_blank(self) -> None:
        self.assertIsNone(_factor_standing(0.05, []))


if __name__ == "__main__":
    unittest.main()
