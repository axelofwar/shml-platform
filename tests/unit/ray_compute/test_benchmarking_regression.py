from ray_compute.benchmarking import MetricDirection, RegressionRule
from ray_compute.benchmarking.regression import evaluate_regression


def test_regression_passes_within_thresholds():
    baseline = {
        "runtime_seconds": 100.0,
        "throughput_rows_per_sec": 1000.0,
    }
    candidate = {
        "runtime_seconds": 106.0,
        "throughput_rows_per_sec": 960.0,
    }

    rules = [
        RegressionRule(
            metric="runtime_seconds",
            direction=MetricDirection.LOWER_IS_BETTER,
            max_regression_pct=10.0,
        ),
        RegressionRule(
            metric="throughput_rows_per_sec",
            direction=MetricDirection.HIGHER_IS_BETTER,
            max_regression_pct=5.0,
        ),
    ]

    outcome = evaluate_regression(baseline, candidate, rules)
    assert outcome.passed is True
    assert not outcome.failures


def test_regression_fails_when_metric_regresses_too_far():
    baseline = {"runtime_seconds": 100.0}
    candidate = {"runtime_seconds": 130.0}

    rules = [
        RegressionRule(
            metric="runtime_seconds",
            direction=MetricDirection.LOWER_IS_BETTER,
            max_regression_pct=10.0,
        )
    ]

    outcome = evaluate_regression(baseline, candidate, rules)
    assert outcome.passed is False
    assert any("runtime_seconds" in failure for failure in outcome.failures)
