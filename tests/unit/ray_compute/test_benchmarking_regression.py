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


def test_missing_required_metric_causes_failure():
    """Missing required metric adds failure and sets passed=False."""
    baseline = {}
    candidate = {}

    rules = [
        RegressionRule(
            metric="accuracy",
            direction=MetricDirection.HIGHER_IS_BETTER,
            max_regression_pct=5.0,
            required=True,
        )
    ]

    outcome = evaluate_regression(baseline, candidate, rules)
    assert outcome.passed is False
    assert any("accuracy" in f for f in outcome.failures)
    assert any("Missing required metric" in f for f in outcome.failures)


def test_missing_optional_metric_skipped():
    """Missing non-required metric is silently skipped; passes if no other failures."""
    baseline = {}
    candidate = {}

    rules = [
        RegressionRule(
            metric="optional_score",
            direction=MetricDirection.HIGHER_IS_BETTER,
            max_regression_pct=5.0,
            required=False,
        )
    ]

    outcome = evaluate_regression(baseline, candidate, rules)
    assert outcome.passed is True
    assert outcome.failures == []


def test_zero_baseline_with_nonzero_candidate_required():
    """Zero baseline + nonzero candidate for required metric adds failure."""
    baseline = {"loss": 0.0}
    candidate = {"loss": 0.05}

    rules = [
        RegressionRule(
            metric="loss",
            direction=MetricDirection.LOWER_IS_BETTER,
            max_regression_pct=10.0,
            required=True,
        )
    ]

    outcome = evaluate_regression(baseline, candidate, rules)
    assert outcome.passed is False
    assert any("baseline is 0" in f for f in outcome.failures)


def test_zero_baseline_with_zero_candidate():
    """Zero baseline AND zero candidate is silently skipped (no pct possible)."""
    baseline = {"loss": 0.0}
    candidate = {"loss": 0.0}

    rules = [
        RegressionRule(
            metric="loss",
            direction=MetricDirection.LOWER_IS_BETTER,
            max_regression_pct=10.0,
            required=True,
        )
    ]

    outcome = evaluate_regression(baseline, candidate, rules)
    assert outcome.passed is True
    assert outcome.failures == []


def test_higher_is_better_regression_detected():
    """Lower candidate relative to baseline triggers HIGHER_IS_BETTER failure."""
    baseline = {"f1": 0.90}
    candidate = {"f1": 0.70}

    rules = [
        RegressionRule(
            metric="f1",
            direction=MetricDirection.HIGHER_IS_BETTER,
            max_regression_pct=5.0,
        )
    ]

    outcome = evaluate_regression(baseline, candidate, rules)
    assert outcome.passed is False
    assert "f1" in outcome.details
    assert outcome.details["f1"]["regression_pct"] > 5.0
