"""
tests/test_bench_budgets.py

Guards for tests/_bench.py -- the host-tolerant wall-clock budget helper.

These lock the helper's contract so a future edit cannot silently turn the
perf benchmarks back into flaky one-shot assertions (or into vacuous ones):
budgets scale with the measured host factor, measure() keeps the fastest
attempt, and a pathologically slow host SKIPS timing checks loudly instead of
failing them (correctness assertions are untouched elsewhere).
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import _bench
import time
import unittest


class TestBenchBudgets(unittest.TestCase):

    def setUp(self):
        # Freeze the host factor for deterministic assertions; restore after.
        self._saved = _bench._factor_cache

    def tearDown(self):
        _bench._factor_cache = self._saved

    def test_budget_scales_with_host_factor(self):
        _bench._factor_cache = 2.0
        self.assertAlmostEqual(_bench.budget(2.5), 5.0 * _bench.ENV_FACTOR)
        _bench._factor_cache = 1.0
        self.assertAlmostEqual(_bench.budget(0.4), 0.4 * _bench.ENV_FACTOR)

    def test_host_factor_floor_is_one(self):
        # A host FASTER than the reference box must not shrink budgets.
        _bench._factor_cache = None
        self.assertGreaterEqual(_bench.host_factor(), 1.0)
        self.assertGreaterEqual(_bench.budget(1.0), 1.0)

    def test_measure_keeps_fastest_attempt(self):
        if _bench.STRICT:
            self.skipTest("strict mode forces single-shot measurement")
        calls = []

        def _flaky():
            calls.append(1)
            time.sleep(0.03 if len(calls) == 1 else 0.001)
            return len(calls)

        elapsed, result = _bench.measure(_flaky, attempts=3)
        self.assertIn(result, (2, 3))  # a fast run's result kept, never run 1
        self.assertLess(elapsed, 0.02)  # the 30ms stall was discarded

    def test_assert_time_fails_on_normal_host(self):
        _bench._factor_cache = 1.0
        tc = unittest.TestCase()
        self.assertTrue(_bench.assert_time(tc, 0.05, 0.10, "well within budget"))
        with self.assertRaises(AssertionError):
            _bench.assert_time(tc, 10.0, 0.10, "hopelessly over budget")

    def test_assert_time_and_rate_skip_on_pathological_host(self):
        if _bench.STRICT:
            self.skipTest("strict mode never skips")
        _bench._factor_cache = _bench.SKIP_FACTOR
        tc = unittest.TestCase()
        self.assertTrue(_bench.assert_time(tc, 10.0, 0.10, "over budget but host is hopeless"))
        self.assertTrue(_bench.assert_rate(tc, 0.1, 20.0, "slow host throughput"))


if __name__ == "__main__":
    unittest.main()
