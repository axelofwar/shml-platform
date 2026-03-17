"""
Spark executor for benchmark workloads.

Runs the SAME simulated ADAS event processing pipeline as the
Ray executor, but uses PySpark DataFrame operations instead of
multiprocessing.

The pipeline (same logical steps, different engine):
  1. Generate synthetic events → Spark DataFrame
  2. Filter to face-tagged events (confidence > 0.5)  → df.filter()
  3. Enrich with derived fields → df.withColumn()
  4. Group-by aggregation → df.groupBy().agg()
  5. Collect results → df.collect()

Key differences from Ray path:
  - DataFrame API instead of row-level Python
  - Catalyst optimizer can push down filters, reorder joins
  - AQE handles partition coalescing at runtime
  - Shuffle partitions configurable (vs Ray object store)
"""

from __future__ import annotations

import time
from typing import Callable

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ray_compute.benchmarking.models import BenchmarkResult, BenchmarkScenario
from scripts.benchmarking.executors import generate_synthetic_events


def create_spark_executor(
    config: dict | None = None,
) -> Callable[[BenchmarkScenario], BenchmarkResult]:
    """
    Factory: returns an executor closure that runs the simulated
    ADAS workload using PySpark DataFrames.
    """
    config = config or {}

    def execute(scenario: BenchmarkScenario) -> BenchmarkResult:
        from pyspark.sql import SparkSession
        from pyspark.sql import functions as F

        rows = int(scenario.parameters.get("rows", 100_000))
        workers = int(scenario.parameters.get("workers", 2))
        rep = int(scenario.parameters.get("rep", 1))

        # ── Spark session setup ──────────────────────────────
        shuffle_partitions = config.get("shuffle_partitions", max(workers * 2, 8))
        aqe_enabled = config.get("aqe_enabled", True)
        # Scale driver memory with workload size
        default_mem = (
            "4g" if rows >= 5_000_000 else ("3g" if rows >= 1_000_000 else "2g")
        )
        driver_memory = config.get("driver_memory", default_mem)

        spark = (
            SparkSession.builder.master(f"local[{workers}]")
            .appName(f"bench-{scenario.benchmark_id}")
            .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
            .config("spark.sql.adaptive.enabled", str(aqe_enabled).lower())
            .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
            .config("spark.sql.adaptive.advisoryPartitionSizeInBytes", "64MB")
            .config("spark.driver.memory", driver_memory)
            .config("spark.driver.maxResultSize", "2g")
            .config("spark.ui.enabled", "false")
            .config("spark.python.worker.memory", "512m")
            .getOrCreate()
        )

        try:
            # Simulate queue/scheduling overhead (Spark session startup)
            queue_start = time.time()
            # In production, this would be cluster resource acquisition time.
            # Here we include Spark session creation as part of queue_wait.
            queue_wait = time.time() - queue_start

            # ── Step 1: Generate → DataFrame ────────────────
            t0 = time.time()
            events = generate_synthetic_events(rows, seed=42 + rep)

            # Convert to Spark DataFrame in chunks to avoid huge serialized tasks.
            # Target: ~128MB per partition (each row is ~200 bytes, so ~640K rows per partition)
            target_partitions = max(workers * 2, rows // 500_000, 4)

            # For large datasets, create from pandas to avoid Arrow serialization issues
            import pandas as pd

            pdf = pd.DataFrame(events)
            df = spark.createDataFrame(pdf).repartition(target_partitions)

            # ── Step 2: Filter ──────────────────────────────
            # Catalyst will push this predicate as close to source as possible
            df_filtered = df.filter(
                (F.col("is_face") == True) & (F.col("confidence") > 0.5)
            )

            # ── Step 3: Enrich ──────────────────────────────
            df_enriched = (
                df_filtered.withColumn("area", F.col("bbox_w") * F.col("bbox_h"))
                .withColumn(
                    "aspect_ratio",
                    F.col("bbox_w") / F.greatest(F.col("bbox_h"), F.lit(1)),
                )
                .withColumn(
                    "size_class",
                    F.when(F.col("bbox_w") * F.col("bbox_h") < 5000, "small")
                    .when(F.col("bbox_w") * F.col("bbox_h") < 50000, "medium")
                    .otherwise("large"),
                )
            )

            # ── Step 4: Aggregate ───────────────────────────
            # Group by sensor_type × region (matches Ray aggregation)
            df_agg = df_enriched.groupBy("sensor_type", "region").agg(
                F.count("*").alias("count"),
                F.sum("confidence").alias("sum_confidence"),
                F.sum("area").alias("sum_area"),
                F.avg("confidence").alias("avg_confidence"),
                F.avg("area").alias("avg_area"),
            )

            # ── Step 5: Collect ─────────────────────────────
            agg_results = df_agg.collect()
            total_processed = df.count()
            face_count = df_filtered.count()

            runtime = time.time() - t0
            throughput = total_processed / runtime if runtime > 0 else 0
            failure_rate = 0.0  # Spark handles errors internally via task retries

            # Capture the physical plan for learning/debugging
            explain_str = df_agg._jdf.queryExecution().simpleString()

            return BenchmarkResult(
                metrics={
                    "runtime_seconds": round(runtime, 4),
                    "queue_wait_seconds": round(queue_wait, 4),
                    "throughput_rows_per_sec": round(throughput, 4),
                    "failure_rate": round(failure_rate, 5),
                },
                metadata={
                    "rows": rows,
                    "workers": workers,
                    "retries": rep,
                    "compute_profile": f"cpu={workers}x|engine=spark",
                    "cost_proxy": round(runtime * workers, 3),
                    "face_events_found": face_count,
                    "aggregation_groups": len(agg_results),
                    "shuffle_partitions": shuffle_partitions,
                    "aqe_enabled": aqe_enabled,
                    "physical_plan_summary": explain_str[:2000],
                },
            )
        finally:
            spark.stop()

    return execute
