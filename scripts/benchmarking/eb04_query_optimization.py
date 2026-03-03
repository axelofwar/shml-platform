#!/usr/bin/env python3
"""
EB-04: Query Optimization Case Study

Demonstrates 3 controlled optimizations on Iceberg tables with before/after
explain plans, runtime measurements, and shuffle metrics.

Optimizations:
    1. Partition pruning — full scan vs filtered scan
    2. Join strategy — SortMergeJoin vs BroadcastHashJoin
    3. AQE partition coalescing — fixed 200 partitions vs adaptive

Usage:
    source scripts/auth/export_mlflow_oauth_env.sh
    source ~/.config/shml/mlflow_oauth.env
    python scripts/benchmarking/eb04_query_optimization.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ICEBERG_PACKAGE = "org.apache.iceberg:iceberg-spark-runtime-4.0_2.13:1.10.1"
WAREHOUSE_DIR = str(PROJECT_ROOT / "runs" / "eb04_warehouse")


def get_spark(app_name: str, aqe: bool = True, shuffle_partitions: int = 8):
    """Create SparkSession with Iceberg catalog."""
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.master("local[4]")
        .appName(app_name)
        .config("spark.jars.packages", ICEBERG_PACKAGE)
        .config("spark.sql.catalog.local", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.local.type", "hadoop")
        .config("spark.sql.catalog.local.warehouse", WAREHOUSE_DIR)
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config("spark.sql.adaptive.enabled", str(aqe).lower())
        .config("spark.sql.adaptive.coalescePartitions.enabled", str(aqe).lower())
        .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
        .config("spark.driver.memory", "2g")
        .config("spark.ui.enabled", "false")
    )
    return builder.getOrCreate()


def capture_plan(df) -> dict:
    """Capture explain plan details and metrics from a DataFrame."""
    plan_str = df._jdf.queryExecution().toString()
    simple_plan = df._jdf.queryExecution().simpleString()

    # Count exchanges (shuffles)
    exchange_count = simple_plan.count("Exchange")
    has_broadcast = (
        "BroadcastHashJoin" in simple_plan or "BroadcastExchange" in simple_plan
    )
    has_sort_merge = "SortMergeJoin" in simple_plan
    has_partition_filter = "PartitionFilters" in plan_str or "filters=" in simple_plan
    has_aqe = "AdaptiveSparkPlan" in simple_plan
    has_coalesce = (
        "CoalescedShuffleRead" in simple_plan or "coalesced" in simple_plan.lower()
    )

    return {
        "exchange_count": exchange_count,
        "broadcast_join": has_broadcast,
        "sort_merge_join": has_sort_merge,
        "partition_pruning": has_partition_filter,
        "aqe_active": has_aqe,
        "coalesced_partitions": has_coalesce,
        "plan_snippet": simple_plan[:3000],
    }


def timed_collect(df, label: str) -> tuple:
    """Collect a DataFrame and measure time. Returns (results, elapsed_s, plan_info)."""
    plan_info = capture_plan(df)
    t0 = time.time()
    results = df.collect()
    elapsed = time.time() - t0
    print(
        f"    [{label}] {len(results)} rows, {elapsed:.3f}s, "
        f"exchanges={plan_info['exchange_count']}, "
        f"broadcast={plan_info['broadcast_join']}, "
        f"smj={plan_info['sort_merge_join']}"
    )
    return results, elapsed, plan_info


def setup_data(spark):
    """Create fact and dimension tables with enough data for meaningful comparison."""
    import random
    from pyspark.sql import Row

    print("Setting up test data...")

    rng = random.Random(42)
    regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1", "sa-east-1"]
    event_types = ["purchase", "view", "click", "refund", "signup"]
    base_date = date(2026, 1, 1)

    # Fact table: 50K rows across 60 days
    print("  Generating 50,000 fact rows across 60 days...")
    fact_rows = []
    for i in range(50_000):
        day_offset = i % 60
        fact_rows.append(
            Row(
                event_id=i,
                user_id=f"user_{i % 2000:05d}",
                event_type=rng.choice(event_types),
                region=rng.choice(regions),
                event_count=rng.randint(1, 100),
                total_spend=round(rng.uniform(1.0, 500.0), 2),
                event_date=base_date + timedelta(days=day_offset),
                processed_at=datetime(2026, 2, 26, 10, 0, 0),
            )
        )

    spark.sql("DROP TABLE IF EXISTS local.optim.events")
    spark.sql(
        """
        CREATE TABLE local.optim.events (
            event_id    BIGINT,
            user_id     STRING,
            event_type  STRING,
            region      STRING,
            event_count INT,
            total_spend DOUBLE,
            event_date  DATE,
            processed_at TIMESTAMP
        )
        USING iceberg
        PARTITIONED BY (days(event_date))
    """
    )

    import pandas as pd

    df_fact = spark.createDataFrame(pd.DataFrame([r.asDict() for r in fact_rows]))
    df_fact.writeTo("local.optim.events").append()

    fact_count = spark.sql("SELECT count(*) FROM local.optim.events").collect()[0][0]
    fact_files = spark.sql("SELECT count(*) FROM local.optim.events.files").collect()[
        0
    ][0]
    print(f"  Fact table: {fact_count} rows, {fact_files} files")

    # Dimension table: 5 regions (small, should be broadcast)
    spark.sql("DROP TABLE IF EXISTS local.optim.dim_regions")
    spark.sql(
        """
        CREATE TABLE local.optim.dim_regions (
            region_code STRING,
            region_name STRING,
            timezone    STRING,
            cost_zone   INT
        ) USING iceberg
    """
    )

    dim_rows = [
        Row(
            region_code="us-east-1",
            region_name="US East (Virginia)",
            timezone="EST",
            cost_zone=1,
        ),
        Row(
            region_code="us-west-2",
            region_name="US West (Oregon)",
            timezone="PST",
            cost_zone=2,
        ),
        Row(
            region_code="eu-west-1",
            region_name="EU West (Ireland)",
            timezone="GMT",
            cost_zone=3,
        ),
        Row(
            region_code="ap-south-1",
            region_name="Asia Pacific (Mumbai)",
            timezone="IST",
            cost_zone=4,
        ),
        Row(
            region_code="sa-east-1",
            region_name="South America (São Paulo)",
            timezone="BRT",
            cost_zone=5,
        ),
    ]
    spark.createDataFrame(dim_rows).writeTo("local.optim.dim_regions").append()
    print(f"  Dim table: {len(dim_rows)} rows")

    # Medium dimension table: 2000 users (larger, near broadcast threshold for testing)
    spark.sql("DROP TABLE IF EXISTS local.optim.dim_users")
    spark.sql(
        """
        CREATE TABLE local.optim.dim_users (
            user_id     STRING,
            user_name   STRING,
            signup_date DATE,
            tier        STRING,
            credit_score INT
        ) USING iceberg
    """
    )

    tiers = ["free", "basic", "premium", "enterprise"]
    user_rows = [
        Row(
            user_id=f"user_{i:05d}",
            user_name=f"User {i}",
            signup_date=base_date - timedelta(days=rng.randint(0, 365)),
            tier=rng.choice(tiers),
            credit_score=rng.randint(300, 850),
        )
        for i in range(2000)
    ]
    spark.createDataFrame(pd.DataFrame([r.asDict() for r in user_rows])).writeTo(
        "local.optim.dim_users"
    ).append()
    print(f"  User dim table: {len(user_rows)} rows")

    return fact_count


def optimization_1_partition_pruning(reps: int = 3):
    """
    Optimization 1: Partition Pruning
    Before: Full table scan (no date filter)
    After: Date-filtered scan (partition pruning)
    """
    print("\n" + "=" * 70)
    print("OPTIMIZATION 1: Partition Pruning")
    print("=" * 70)

    spark = get_spark("opt1-partition-pruning")
    results = {}

    try:
        # ── BASELINE: No partition filter ──
        print("\n  BASELINE: Full table scan (no date filter)")
        baseline_times = []
        for rep in range(reps):
            df_baseline = spark.sql(
                """
                SELECT region, event_type,
                       SUM(event_count) as total_events,
                       SUM(total_spend) as total_spend,
                       COUNT(*) as row_count
                FROM local.optim.events
                GROUP BY region, event_type
                ORDER BY total_spend DESC
            """
            )
            _, elapsed, plan = timed_collect(df_baseline, f"baseline-{rep+1}")
            baseline_times.append(elapsed)
            if rep == 0:
                results["baseline_plan"] = plan

        print(f"\n  Baseline explain plan:")
        spark.sql(
            """
            SELECT region, SUM(event_count), SUM(total_spend)
            FROM local.optim.events GROUP BY region
        """
        ).explain(True)

        # ── OPTIMIZED: With partition filter ──
        print("\n  OPTIMIZED: Date-filtered scan (7-day window)")
        opt_times = []
        for rep in range(reps):
            df_opt = spark.sql(
                """
                SELECT region, event_type,
                       SUM(event_count) as total_events,
                       SUM(total_spend) as total_spend,
                       COUNT(*) as row_count
                FROM local.optim.events
                WHERE event_date >= DATE '2026-02-01'
                  AND event_date <= DATE '2026-02-07'
                GROUP BY region, event_type
                ORDER BY total_spend DESC
            """
            )
            _, elapsed, plan = timed_collect(df_opt, f"optimized-{rep+1}")
            opt_times.append(elapsed)
            if rep == 0:
                results["optimized_plan"] = plan

        print(f"\n  Optimized explain plan:")
        spark.sql(
            """
            SELECT region, SUM(event_count), SUM(total_spend)
            FROM local.optim.events
            WHERE event_date >= DATE '2026-02-01' AND event_date <= DATE '2026-02-07'
            GROUP BY region
        """
        ).explain(True)

        avg_base = sum(baseline_times) / len(baseline_times)
        avg_opt = sum(opt_times) / len(opt_times)
        speedup = avg_base / max(avg_opt, 0.001)

        results["baseline_avg_s"] = round(avg_base, 4)
        results["optimized_avg_s"] = round(avg_opt, 4)
        results["speedup"] = round(speedup, 2)
        results["data_reduction"] = "60 → 7 days (88% fewer partitions scanned)"
        results["success"] = True

        print(f"\n  ── Results ──")
        print(f"  Baseline (full scan):  {avg_base:.4f}s avg")
        print(f"  Optimized (pruned):    {avg_opt:.4f}s avg")
        print(f"  Speedup:               {speedup:.2f}×")
        print(f"  Partitions scanned:    60 → 7 (88% reduction)")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback

        traceback.print_exc()
        results["success"] = False
        results["error"] = str(e)
    finally:
        spark.stop()

    return results


def optimization_2_join_strategy(reps: int = 3):
    """
    Optimization 2: Join Strategy
    Before: Force SortMergeJoin on small dim table
    After: BroadcastHashJoin (default — show why it's better)
    """
    print("\n" + "=" * 70)
    print("OPTIMIZATION 2: Join Strategy (SMJ → BHJ)")
    print("=" * 70)

    results = {}

    try:
        # ── BASELINE: Force SortMergeJoin ──
        print("\n  BASELINE: Forced SortMergeJoin (broadcast disabled)")
        spark_smj = get_spark("opt2-smj")
        # Disable broadcast to force SortMergeJoin
        spark_smj.conf.set("spark.sql.autoBroadcastJoinThreshold", "-1")

        smj_times = []
        for rep in range(reps):
            df_smj = spark_smj.sql(
                """
                SELECT e.event_type, d.region_name, d.cost_zone,
                       SUM(e.event_count) as total_events,
                       SUM(e.total_spend) as total_spend
                FROM local.optim.events e
                JOIN local.optim.dim_regions d ON e.region = d.region_code
                WHERE e.event_date >= DATE '2026-02-01'
                GROUP BY e.event_type, d.region_name, d.cost_zone
                ORDER BY total_spend DESC
            """
            )
            _, elapsed, plan = timed_collect(df_smj, f"smj-{rep+1}")
            smj_times.append(elapsed)
            if rep == 0:
                results["smj_plan"] = plan

        print(f"\n  SortMergeJoin explain plan:")
        spark_smj.conf.set("spark.sql.autoBroadcastJoinThreshold", "-1")
        spark_smj.sql(
            """
            SELECT e.event_type, d.region_name,
                   SUM(e.event_count), SUM(e.total_spend)
            FROM local.optim.events e
            JOIN local.optim.dim_regions d ON e.region = d.region_code
            WHERE e.event_date >= DATE '2026-02-01'
            GROUP BY e.event_type, d.region_name
        """
        ).explain(True)
        spark_smj.stop()

        # ── OPTIMIZED: BroadcastHashJoin (default) ──
        print("\n  OPTIMIZED: BroadcastHashJoin (default threshold)")
        spark_bhj = get_spark("opt2-bhj")

        bhj_times = []
        for rep in range(reps):
            df_bhj = spark_bhj.sql(
                """
                SELECT e.event_type, d.region_name, d.cost_zone,
                       SUM(e.event_count) as total_events,
                       SUM(e.total_spend) as total_spend
                FROM local.optim.events e
                JOIN local.optim.dim_regions d ON e.region = d.region_code
                WHERE e.event_date >= DATE '2026-02-01'
                GROUP BY e.event_type, d.region_name, d.cost_zone
                ORDER BY total_spend DESC
            """
            )
            _, elapsed, plan = timed_collect(df_bhj, f"bhj-{rep+1}")
            bhj_times.append(elapsed)
            if rep == 0:
                results["bhj_plan"] = plan

        print(f"\n  BroadcastHashJoin explain plan:")
        spark_bhj.sql(
            """
            SELECT e.event_type, d.region_name,
                   SUM(e.event_count), SUM(e.total_spend)
            FROM local.optim.events e
            JOIN local.optim.dim_regions d ON e.region = d.region_code
            WHERE e.event_date >= DATE '2026-02-01'
            GROUP BY e.event_type, d.region_name
        """
        ).explain(True)
        spark_bhj.stop()

        avg_smj = sum(smj_times) / len(smj_times)
        avg_bhj = sum(bhj_times) / len(bhj_times)
        speedup = avg_smj / max(avg_bhj, 0.001)

        # Exchange difference: SMJ has extra exchanges for both-side shuffle
        smj_exchanges = results.get("smj_plan", {}).get("exchange_count", 0)
        bhj_exchanges = results.get("bhj_plan", {}).get("exchange_count", 0)

        results["smj_avg_s"] = round(avg_smj, 4)
        results["bhj_avg_s"] = round(avg_bhj, 4)
        results["speedup"] = round(speedup, 2)
        results["smj_exchanges"] = smj_exchanges
        results["bhj_exchanges"] = bhj_exchanges
        results["success"] = True

        print(f"\n  ── Results ──")
        print(f"  SortMergeJoin:       {avg_smj:.4f}s avg, {smj_exchanges} exchanges")
        print(f"  BroadcastHashJoin:   {avg_bhj:.4f}s avg, {bhj_exchanges} exchanges")
        print(f"  Speedup:             {speedup:.2f}×")
        print(
            f"  Shuffle eliminated:  {smj_exchanges - bhj_exchanges} exchange(s) removed"
        )

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback

        traceback.print_exc()
        results["success"] = False
        results["error"] = str(e)

    return results


def optimization_3_aqe_coalescing(reps: int = 3):
    """
    Optimization 3: AQE Partition Coalescing
    Before: Fixed 200 shuffle partitions, AQE off
    After: AQE auto-coalesces small partitions
    """
    print("\n" + "=" * 70)
    print("OPTIMIZATION 3: AQE Partition Coalescing")
    print("=" * 70)

    results = {}

    try:
        # ── BASELINE: Fixed 200 partitions, AQE off ──
        print("\n  BASELINE: 200 fixed shuffle partitions, AQE disabled")
        spark_fixed = get_spark("opt3-fixed", aqe=False, shuffle_partitions=200)

        fixed_times = []
        for rep in range(reps):
            df_fixed = spark_fixed.sql(
                """
                SELECT u.tier, e.event_type, e.region,
                       COUNT(*) as event_count,
                       SUM(e.total_spend) as total_spend,
                       AVG(u.credit_score) as avg_credit_score
                FROM local.optim.events e
                JOIN local.optim.dim_users u ON e.user_id = u.user_id
                WHERE e.event_date >= DATE '2026-02-01'
                GROUP BY u.tier, e.event_type, e.region
                ORDER BY total_spend DESC
            """
            )
            _, elapsed, plan = timed_collect(df_fixed, f"fixed-{rep+1}")
            fixed_times.append(elapsed)
            if rep == 0:
                results["fixed_plan"] = plan

        # Count actual tasks via RDD
        df_check = spark_fixed.sql(
            """
            SELECT u.tier, e.event_type, e.region, SUM(e.total_spend)
            FROM local.optim.events e
            JOIN local.optim.dim_users u ON e.user_id = u.user_id
            WHERE e.event_date >= DATE '2026-02-01'
            GROUP BY u.tier, e.event_type, e.region
        """
        )
        fixed_partitions = df_check.rdd.getNumPartitions()
        print(f"  Fixed partition count: {fixed_partitions}")
        results["fixed_partition_count"] = fixed_partitions

        print(f"\n  Fixed-200 explain plan:")
        df_check.explain(True)
        spark_fixed.stop()

        # ── OPTIMIZED: AQE with auto-coalescing ──
        print("\n  OPTIMIZED: AQE enabled with auto-coalescing")
        spark_aqe = get_spark("opt3-aqe", aqe=True, shuffle_partitions=200)

        aqe_times = []
        for rep in range(reps):
            df_aqe = spark_aqe.sql(
                """
                SELECT u.tier, e.event_type, e.region,
                       COUNT(*) as event_count,
                       SUM(e.total_spend) as total_spend,
                       AVG(u.credit_score) as avg_credit_score
                FROM local.optim.events e
                JOIN local.optim.dim_users u ON e.user_id = u.user_id
                WHERE e.event_date >= DATE '2026-02-01'
                GROUP BY u.tier, e.event_type, e.region
                ORDER BY total_spend DESC
            """
            )
            _, elapsed, plan = timed_collect(df_aqe, f"aqe-{rep+1}")
            aqe_times.append(elapsed)
            if rep == 0:
                results["aqe_plan"] = plan

        df_check_aqe = spark_aqe.sql(
            """
            SELECT u.tier, e.event_type, e.region, SUM(e.total_spend)
            FROM local.optim.events e
            JOIN local.optim.dim_users u ON e.user_id = u.user_id
            WHERE e.event_date >= DATE '2026-02-01'
            GROUP BY u.tier, e.event_type, e.region
        """
        )
        # Force materialization to see AQE post-optimization partitions
        _ = df_check_aqe.collect()
        aqe_partitions = df_check_aqe.rdd.getNumPartitions()
        print(f"  AQE partition count: {aqe_partitions}")
        results["aqe_partition_count"] = aqe_partitions

        print(f"\n  AQE explain plan:")
        df_check_aqe.explain(True)
        spark_aqe.stop()

        avg_fixed = sum(fixed_times) / len(fixed_times)
        avg_aqe = sum(aqe_times) / len(aqe_times)
        speedup = avg_fixed / max(avg_aqe, 0.001)

        results["fixed_avg_s"] = round(avg_fixed, 4)
        results["aqe_avg_s"] = round(avg_aqe, 4)
        results["speedup"] = round(speedup, 2)
        results["success"] = True

        print(f"\n  ── Results ──")
        print(
            f"  Fixed 200 partitions: {avg_fixed:.4f}s avg, {fixed_partitions} output partitions"
        )
        print(
            f"  AQE coalescing:       {avg_aqe:.4f}s avg, {aqe_partitions} output partitions"
        )
        print(f"  Speedup:              {speedup:.2f}×")
        print(f"  Partition reduction:  {fixed_partitions} → {aqe_partitions}")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback

        traceback.print_exc()
        results["success"] = False
        results["error"] = str(e)

    return results


def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  EB-04: Query Optimization Case Study                           ║")
    print("║  3 Controlled Experiments — Before/After with Explain Plans      ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    # Clean warehouse
    if os.path.exists(WAREHOUSE_DIR):
        shutil.rmtree(WAREHOUSE_DIR)
    os.makedirs(WAREHOUSE_DIR, exist_ok=True)

    # Setup shared data
    spark_setup = get_spark("eb04-setup")
    setup_data(spark_setup)
    spark_setup.stop()

    all_results = {}

    # Run all 3 optimizations
    all_results["opt1_partition_pruning"] = optimization_1_partition_pruning()
    all_results["opt2_join_strategy"] = optimization_2_join_strategy()
    all_results["opt3_aqe_coalescing"] = optimization_3_aqe_coalescing()

    # Summary
    print("\n" + "=" * 70)
    print("CASE STUDY SUMMARY")
    print("=" * 70)

    for name, result in all_results.items():
        status = "✓" if result.get("success") else "✗"
        speedup = result.get("speedup", "?")
        print(f"  {status} {name}: {speedup}× speedup")

    # Save results
    output_file = PROJECT_ROOT / "runs" / "eb04_optimization_results.json"

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
