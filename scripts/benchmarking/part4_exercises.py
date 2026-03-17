#!/usr/bin/env python3
"""
Part 4 Exercises: Feature Platform Design & SLOs

Programmatic answers to the 4 exercises from Part 4, using real benchmark
data from EB-01/02 to ground the calculations.

Exercises:
    1. Design a feature view (entity, schema, schedule, freshness SLO)
    2. Calculate error budget (freshness SLO math)
    3. Identify training/serving skew (3 divergence scenarios)
    4. Design monitoring dashboard (Grafana panels + alert thresholds)
"""
from __future__ import annotations

import json
import math
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def exercise_1_feature_view_design():
    """
    Exercise 1: Design a feature view for a real model.
    Define: entity, join keys, schema, schedule, freshness SLO.
    """
    print("=" * 70)
    print("EXERCISE 1: Feature View Design")
    print("=" * 70)

    design = {
        "name": "user_activity_features_v1",
        "entity": {
            "name": "user",
            "join_keys": ["user_id"],
            "description": "Individual user, keyed by platform user ID",
        },
        "schema": [
            {
                "name": "total_events_7d",
                "type": "BIGINT",
                "description": "Total events in rolling 7-day window",
            },
            {
                "name": "unique_event_types",
                "type": "INT",
                "description": "Distinct event types in window",
            },
            {
                "name": "total_spend_7d",
                "type": "DOUBLE",
                "description": "Total spend in rolling 7-day window",
            },
            {
                "name": "avg_spend_per_event",
                "type": "DOUBLE",
                "description": "Average spend per event",
            },
            {
                "name": "last_activity_date",
                "type": "DATE",
                "description": "Most recent event date",
            },
            {
                "name": "purchase_ratio",
                "type": "DOUBLE",
                "description": "Fraction of events that are purchases",
            },
        ],
        "source": "raw_events (Iceberg table: local.features.raw_events)",
        "schedule": "@hourly",
        "freshness_slo": "60 minutes (99th percentile)",
        "owner": "platform-team",
        "compute_engine": "Spark (batch path, EB-02 validated)",
    }

    # Freshness budget breakdown using real EB-02 benchmarks
    # Our actual Spark runtimes from EB-02:
    spark_runtimes = {
        "S_100k": 6.70,  # seconds
        "M_1M": 46.61,  # seconds
        "L_5M": 244.39,  # seconds
    }

    # Projected production workload: ~1M users, feature recompute = M-size
    compute_time_s = spark_runtimes["M_1M"]
    serving_lag_s = 30  # Iceberg commit + cache invalidation
    total_freshness_s = compute_time_s + serving_lag_s
    freshness_budget_s = 60 * 60  # 60 min SLO

    slack_s = freshness_budget_s - total_freshness_s
    slack_pct = (slack_s / freshness_budget_s) * 100

    print(f"\n  Feature View: {design['name']}")
    print(
        f"  Entity: {design['entity']['name']} (join keys: {design['entity']['join_keys']})"
    )
    print(f"  Schedule: {design['schedule']}")
    print(f"  Freshness SLO: {design['freshness_slo']}")
    print(f"\n  Schema:")
    for col in design["schema"]:
        print(f"    {col['name']:25s} {col['type']:8s}  {col['description']}")

    print(f"\n  Freshness Budget Breakdown (using EB-02 actual data):")
    print(f"    Compute time (M workload, 1M rows): {compute_time_s:.1f}s")
    print(f"    Serving lag (commit + cache):        {serving_lag_s}s")
    print(
        f"    Total freshness:                     {total_freshness_s:.1f}s ({total_freshness_s/60:.1f} min)"
    )
    print(f"    SLO budget:                          {freshness_budget_s}s (60 min)")
    print(f"    Slack:                               {slack_s:.1f}s ({slack_pct:.1f}%)")
    print(f"    Verdict: ✅ Comfortable — using only {100-slack_pct:.1f}% of budget")

    print(f"\n  Growth ceiling:")
    max_compute = freshness_budget_s - serving_lag_s
    throughput = 1_000_000 / compute_time_s
    max_rows = throughput * max_compute
    print(f"    At current throughput ({throughput:.0f} rows/s):")
    print(f"    Max rows before budget breach: {max_rows:,.0f} (~{max_rows/1e6:.1f}M)")
    print(
        f"    That's {max_rows/1e6:.0f}× current workload size before needing optimization"
    )

    return design


def exercise_2_error_budget():
    """
    Exercise 2: Calculate error budget.
    SLO: 60-minute freshness, 99% of the time, hourly runs.
    How many late runs per month? With L=615s runtime, what's the slack?
    """
    print("\n" + "=" * 70)
    print("EXERCISE 2: Error Budget Calculation")
    print("=" * 70)

    slo_freshness_min = 60
    slo_pct = 99.0  # 99% of windows must be fresh
    schedule_interval_min = 60  # hourly
    hours_per_month = 24 * 30  # 720
    windows_per_month = hours_per_month  # 720 hourly windows

    # Error budget = (100% - 99%) × 720 = 7.2 windows can be late
    error_budget_windows = (1 - slo_pct / 100) * windows_per_month
    error_budget_int = math.floor(
        error_budget_windows
    )  # can't have fractional failures

    # L-size benchmark runtime
    l_runtime_s = 244.39  # actual from EB-02 Spark L
    serving_lag_s = 30
    total_freshness_s = l_runtime_s + serving_lag_s
    slack_s = (slo_freshness_min * 60) - total_freshness_s
    slack_pct = (slack_s / (slo_freshness_min * 60)) * 100

    # What if runtime doubles (data growth)?
    doubled_runtime_s = l_runtime_s * 2
    doubled_freshness_s = doubled_runtime_s + serving_lag_s
    doubled_slack_s = (slo_freshness_min * 60) - doubled_freshness_s

    # What runtime would consume 80% of budget? (danger zone threshold)
    danger_threshold_s = (slo_freshness_min * 60) * 0.80 - serving_lag_s

    print(f"\n  Parameters:")
    print(f"    Freshness SLO:      {slo_freshness_min} minutes")
    print(f"    Compliance target:  {slo_pct}%")
    print(f"    Schedule:           hourly ({windows_per_month} windows/month)")
    print(f"    L-size runtime:     {l_runtime_s}s (from EB-02 Spark)")

    print(f"\n  Error Budget:")
    print(
        f"    Allowed failures:   {slo_pct}% of {windows_per_month} = {error_budget_windows:.1f} windows"
    )
    print(f"    Practical budget:   {error_budget_int} late runs per month")
    print(f"    That's ~{error_budget_int / 4:.1f} late runs per week")

    print(f"\n  Freshness Analysis (L workload):")
    print(f"    Compute:            {l_runtime_s:.1f}s ({l_runtime_s/60:.1f} min)")
    print(f"    Serving lag:        {serving_lag_s}s")
    print(
        f"    Total:              {total_freshness_s:.1f}s ({total_freshness_s/60:.1f} min)"
    )
    print(
        f"    SLO budget:         {slo_freshness_min * 60}s ({slo_freshness_min} min)"
    )
    print(f"    Slack:              {slack_s:.1f}s ({slack_pct:.1f}%)")

    print(f"\n  Growth Scenarios:")
    print(
        f"    If runtime doubles: {doubled_freshness_s:.1f}s → slack = {doubled_slack_s:.1f}s {'✅' if doubled_slack_s > 0 else '❌ BREACH'}"
    )
    print(
        f"    Danger zone (>80%): runtime > {danger_threshold_s:.0f}s ({danger_threshold_s/60:.1f} min)"
    )
    print(
        f"    Current utilization: {(total_freshness_s / (slo_freshness_min * 60)) * 100:.1f}%"
    )

    return {
        "error_budget_windows": error_budget_int,
        "slack_seconds": round(slack_s, 1),
        "slack_pct": round(slack_pct, 1),
        "danger_threshold_s": round(danger_threshold_s, 0),
        "budget_utilization_pct": round(
            (total_freshness_s / (slo_freshness_min * 60)) * 100, 1
        ),
    }


def exercise_3_training_serving_skew():
    """
    Exercise 3: Identify training/serving skew.
    Scenario: Daily batch job (Spark) computes features → offline store
              Streaming job updates cache → online store
    List 3 ways values diverge. How does a feature platform prevent each?
    """
    print("\n" + "=" * 70)
    print("EXERCISE 3: Training/Serving Skew Analysis")
    print("=" * 70)

    skew_scenarios = [
        {
            "name": "Logic Divergence",
            "description": "Batch SQL and streaming code implement the same feature with slightly different logic",
            "example": (
                "Batch: SUM(amount) WHERE status != 'refunded'\n"
                "Stream: SUM(amount) (forgets to exclude refunds)"
            ),
            "impact": "Model trains on refund-excluded spend, serves refund-included spend → systematic positive bias in predictions",
            "platform_fix": (
                "Single feature definition (FeatureView) with one transform function.\n"
                "Platform materializes the SAME output to both offline (Iceberg) and online (Redis).\n"
                "There is no separate streaming code path — the batch output IS the online value."
            ),
        },
        {
            "name": "Temporal Divergence",
            "description": "Batch runs on yesterday's data; streaming cache has real-time data. Time windows don't align.",
            "example": (
                "Batch: total_spend_7d computed at midnight → covers days [-8, -1]\n"
                "Cache: total_spend_7d updated continuously → covers days [-7, 0]\n"
                "On Feb 26 at 3pm: batch sees Feb 17-24, cache sees Feb 19-26"
            ),
            "impact": "Training data has stale windows; serving data has fresh windows → model performance on training data doesn't match production",
            "platform_fix": (
                "Feature platform enforces point-in-time correctness.\n"
                "Training reads use Iceberg time travel: FOR SYSTEM_TIME AS OF label_timestamp.\n"
                "This guarantees training features match exactly what was available at prediction time.\n"
                "No temporal leakage possible."
            ),
        },
        {
            "name": "Schema/Type Divergence",
            "description": "Batch output evolves (new column, type change) but cache schema isn't updated.",
            "example": (
                "Batch: total_spend DOUBLE → total_spend_cents BIGINT (precision fix)\n"
                "Cache: Still serves total_spend as DOUBLE\n"
                "Values differ by factor of 100"
            ),
            "impact": "Features have completely wrong magnitude → model predictions catastrophically wrong",
            "platform_fix": (
                "Iceberg schema evolution propagates schema ID to all consumers.\n"
                "Platform validates that the online store schema matches the offline table schema.\n"
                "Schema migration is atomic — both offline and online update together.\n"
                "Rollback is safe via Iceberg time travel if the migration breaks."
            ),
        },
    ]

    for i, scenario in enumerate(skew_scenarios, 1):
        print(f"\n  Skew Scenario {i}: {scenario['name']}")
        print(f"  {'─' * 60}")
        print(f"  Description: {scenario['description']}")
        print(f"\n  Example:")
        for line in scenario["example"].split("\n"):
            print(f"    {line}")
        print(f"\n  Impact: {scenario['impact']}")
        print(f"\n  Platform Fix:")
        for line in scenario["platform_fix"].split("\n"):
            print(f"    {line}")

    print(f"\n  ── Root Cause Pattern ──")
    print(f"  All 3 scenarios share one root cause: separate code paths for")
    print(f"  training and serving. A feature platform eliminates this by")
    print(f"  making the FeatureView the SINGLE source of truth — one")
    print(f"  definition, one compute, dual writes (offline + online).")

    return skew_scenarios


def exercise_4_monitoring_dashboard():
    """
    Exercise 4: Design the monitoring dashboard.
    Grafana panels, alert thresholds, escalation path.
    """
    print("\n" + "=" * 70)
    print("EXERCISE 4: Monitoring Dashboard Design")
    print("=" * 70)

    panels = [
        {
            "name": "Feature Freshness (minutes)",
            "metric": "feature_freshness_seconds / 60",
            "visualization": "Time series with SLO line",
            "alert_threshold": "> 60 min (SLO breach) → P1",
            "warn_threshold": "> 48 min (80% budget consumed) → P3",
            "source": "Prometheus gauge, pushed after each compute",
        },
        {
            "name": "Feature Completeness (%)",
            "metric": "feature_completeness_ratio × 100",
            "visualization": "Gauge with green/amber/red zones",
            "alert_threshold": "< 99.5% → P2 (entities missing features)",
            "warn_threshold": "< 99.8% → P4 (early warning)",
            "source": "Prometheus gauge, pushed after quality check",
        },
        {
            "name": "Compute Duration Trend",
            "metric": "feature_compute_duration_seconds",
            "visualization": "Time series with linear regression trendline",
            "alert_threshold": "> 2400s (40 min, 67% of budget) → P3",
            "warn_threshold": "Trend slope > 5s/day (runtime growing) → P4",
            "source": "Prometheus histogram, captures p50/p95/p99",
        },
        {
            "name": "Error Budget Burn Rate",
            "metric": "slo_violations_this_month / error_budget_total",
            "visualization": "Single stat with color coding",
            "alert_threshold": "> 80% → P2 (freeze risky changes)",
            "warn_threshold": "> 50% → P3 (review upcoming deployments)",
            "source": "Prometheus counter, incremented on SLO breach",
        },
        {
            "name": "Data Quality: Null Rate",
            "metric": "null_values / total_values per feature column",
            "visualization": "Heatmap (columns × time)",
            "alert_threshold": "Any column > 5% nulls → P3",
            "warn_threshold": "New column appears with > 0% nulls → P4",
            "source": "Custom quality check in feature transform",
        },
        {
            "name": "Throughput (rows/sec)",
            "metric": "total_rows_processed / compute_duration_seconds",
            "visualization": "Time series with baseline band",
            "alert_threshold": "< 50% of baseline → P3 (performance regression)",
            "warn_threshold": "< 80% of baseline → P4 (investigate)",
            "source": "MLflow metric, logged per benchmark run",
        },
    ]

    escalation = {
        "P1": {
            "response_time": "< 15 minutes",
            "action": "Page on-call. Feature freshness SLO breached. Check Spark job status, restart if stuck. Rollback last deployment if it caused the breach.",
            "notify": "On-call engineer + team lead",
        },
        "P2": {
            "response_time": "< 1 hour",
            "action": "Investigate completeness drop or budget burn. Check for upstream data source issues. Freeze non-critical deployments if budget > 80%.",
            "notify": "On-call engineer",
        },
        "P3": {
            "response_time": "< 4 hours (business hours)",
            "action": "Review compute duration trend. If growing, either optimize query (EB-04 techniques) or request more resources. Run compaction if small file issue.",
            "notify": "Feature owner via Slack",
        },
        "P4": {
            "response_time": "Next business day",
            "action": "Track in sprint backlog. Early warning — monitor trend. No immediate action unless combined with other signals.",
            "notify": "Feature owner via ticket",
        },
    }

    print(f"\n  Dashboard Panels ({len(panels)} total):")
    for i, panel in enumerate(panels, 1):
        print(f"\n  Panel {i}: {panel['name']}")
        print(f"    Metric:    {panel['metric']}")
        print(f"    Viz:       {panel['visualization']}")
        print(f"    Alert:     {panel['alert_threshold']}")
        print(f"    Warning:   {panel['warn_threshold']}")

    print(f"\n  Escalation Path:")
    for level, details in escalation.items():
        print(f"\n  {level}:")
        print(f"    Response:  {details['response_time']}")
        print(f"    Action:    {details['action']}")
        print(f"    Notify:    {details['notify']}")

    print(f"\n  ── Key Design Principles ──")
    print(
        f"  1. SLO-driven alerts: Only page when an SLO is at risk, not on every anomaly"
    )
    print(
        f"  2. Budget awareness: Track burn rate to decide when to innovate vs stabilize"
    )
    print(f"  3. Trend-based warnings: Catch runtime growth before it becomes a breach")
    print(
        f"  4. Layered escalation: P1 pages immediately, P4 is a ticket for next sprint"
    )

    return {"panels": panels, "escalation": escalation}


def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  Part 4 Exercises: Feature Platform Design & SLOs               ║")
    print("║  Answers Grounded in EB-01/02/03 Actual Data                    ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    all_results = {}
    all_results["exercise_1"] = exercise_1_feature_view_design()
    all_results["exercise_2"] = exercise_2_error_budget()
    all_results["exercise_3"] = exercise_3_training_serving_skew()
    all_results["exercise_4"] = exercise_4_monitoring_dashboard()

    print("\n" + "=" * 70)
    print("ALL PART 4 EXERCISES COMPLETE")
    print("=" * 70)

    # Save results
    output_file = PROJECT_ROOT / "runs" / "part4_exercise_results.json"

    def make_serializable(obj):
        if isinstance(obj, (int, float, str, bool, type(None))):
            return obj
        if isinstance(obj, dict):
            return {k: make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [make_serializable(v) for v in obj]
        return str(obj)

    output_file.write_text(
        json.dumps(make_serializable(all_results), indent=2, sort_keys=True)
    )
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
