import unittest

from app.main import _cohort_percentile


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


if __name__ == "__main__":
    unittest.main()
