# mysite/tests/demand/test_outlier_detection.py

"""
# Run all demand tests
pytest mysite/tests/demand/ -v

# Run only import tests
pytest mysite/tests/demand/test_outlier_detection.py -v --tb=short

# Run with coverage
pytest mysite/tests/demand/ --cov=mysite.models.demand --cov=mysite.tasks.demand --cov-report=term-missing
"""

from decimal import Decimal
from django.test import SimpleTestCase
from utils.demand.outlier_detection import detect_candidates


class DetectCandidatesTests(SimpleTestCase):
    def test_flags_single_period_spike(self):
        series = [Decimal(x) for x in [100, 105, 98, 102, 500, 101, 99, 103, 97, 100, 104, 99]]
        result = detect_candidates(series, mad_threshold=Decimal("3.5"), persistence_periods=3, min_history_periods=12)
        self.assertIn(4, result)

    def test_does_not_flag_sustained_increase(self):
        series = [Decimal(x) for x in [100, 105, 98, 102, 400, 410, 405, 103, 97, 100, 104, 99]]
        result = detect_candidates(series, mad_threshold=Decimal("3.5"), persistence_periods=3, min_history_periods=12)
        self.assertNotIn(4, result)
        self.assertNotIn(5, result)

    def test_skips_short_history(self):
        series = [Decimal(x) for x in [100, 500, 100]]
        result = detect_candidates(series, mad_threshold=Decimal("3.5"), persistence_periods=3, min_history_periods=12)
        self.assertEqual(result, [])

    def test_sustained_run_flags_all_points_in_run_not_just_boundary(self):
        series = [Decimal(x) for x in [100, 105, 98, 102, 400, 410, 405, 103, 97, 100, 104, 99]]
        result = detect_candidates(series, mad_threshold=Decimal("3.5"), persistence_periods=3, min_history_periods=12)
        self.assertEqual(result, [])  # indices 4, 5, AND 6 should all be suppressed