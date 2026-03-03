from __future__ import annotations

from typing import Dict, Iterable

from .models import MetricDirection, RegressionOutcome, RegressionRule


def evaluate_regression(
    baseline_metrics: Dict[str, float],
    candidate_metrics: Dict[str, float],
    rules: Iterable[RegressionRule],
) -> RegressionOutcome:
    failures = []
    details: Dict[str, Dict[str, float]] = {}

    for rule in rules:
        metric = rule.metric
        baseline = baseline_metrics.get(metric)
        candidate = candidate_metrics.get(metric)

        if baseline is None or candidate is None:
            if rule.required:
                failures.append(
                    f"Missing required metric '{metric}' (baseline={baseline}, candidate={candidate})"
                )
            continue

        if baseline == 0:
            if candidate != 0 and rule.required:
                failures.append(
                    f"Metric '{metric}' baseline is 0 but candidate is {candidate}; cannot compute pct regression"
                )
            continue

        if rule.direction == MetricDirection.LOWER_IS_BETTER:
            regression_pct = ((candidate - baseline) / baseline) * 100.0
        else:
            regression_pct = ((baseline - candidate) / baseline) * 100.0

        details[metric] = {
            "baseline": float(baseline),
            "candidate": float(candidate),
            "regression_pct": float(regression_pct),
            "allowed_pct": float(rule.max_regression_pct),
        }

        if regression_pct > rule.max_regression_pct:
            failures.append(
                f"Metric '{metric}' regressed by {regression_pct:.2f}% (allowed {rule.max_regression_pct:.2f}%)"
            )

    passed = len(failures) == 0
    summary = "Regression checks passed" if passed else "Regression checks failed"
    return RegressionOutcome(
        passed=passed, summary=summary, failures=failures, details=details
    )
