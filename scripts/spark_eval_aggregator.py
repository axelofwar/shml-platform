"""Spark-based evaluation aggregation for face detection models.

Applies Part 2 learnings: use Spark for SQL-expressible bulk ETL
(per-class mAP aggregation across thousands of images).

Reads per-image evaluation results and computes per-class/per-scale
breakdowns, writing results to the feature store via pgvector/Iceberg.

Usage:
    python -m scripts.spark_eval_aggregator --run-id <mlflow_run_id>
    python -m scripts.spark_eval_aggregator --results-dir /path/to/eval/results
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("spark-eval-aggregator")

# Add libs to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "libs"))


def aggregate_eval_results(results_dir: str, run_id: str | None = None) -> dict:
    """Aggregate per-image evaluation results using Spark.

    Parameters
    ----------
    results_dir : str
        Directory containing per-image JSON result files.
    run_id : str, optional
        MLflow run ID for lineage tracking.

    Returns
    -------
    dict
        Aggregated metrics (per-class, per-scale, overall).
    """
    from shml_spark import create_spark_session
    from pyspark.sql import functions as F

    spark = create_spark_session(
        "eval-aggregation",
        local_mode=True,
        extra_config={
            # Optimized for aggregation workload (from EB-04 learnings)
            "spark.sql.shuffle.partitions": "8",  # Small dataset, avoid 200-partition overhead
            "spark.sql.adaptive.advisoryPartitionSizeInBytes": "64MB",
        },
    )

    try:
        # Read all per-image results as a DataFrame
        results_path = Path(results_dir)
        if not results_path.exists():
            logger.error("Results directory not found: %s", results_dir)
            return {}

        # Load JSON results into Spark DataFrame
        json_files = list(results_path.glob("*.json"))
        if not json_files:
            logger.warning("No JSON result files found in %s", results_dir)
            return {}

        logger.info("Loading %d evaluation result files", len(json_files))
        df = spark.read.json(str(results_path / "*.json"))

        # Cache for multiple aggregations
        df.cache()
        total_images = df.count()
        logger.info("Loaded %d evaluation records", total_images)

        # --- Overall metrics ---
        overall = df.agg(
            F.avg("mAP50").alias("avg_mAP50"),
            F.avg("mAP50_95").alias("avg_mAP50_95"),
            F.avg("recall").alias("avg_recall"),
            F.avg("precision").alias("avg_precision"),
            F.stddev("mAP50").alias("std_mAP50"),
            F.count("*").alias("total_images"),
            F.sum(F.when(F.col("mAP50") < 0.5, 1).otherwise(0)).alias("failure_count"),
        ).collect()[0]

        # --- Per-scale breakdown (face size buckets) ---
        per_scale = {}
        if "face_size_bucket" in df.columns:
            scale_df = (
                df.groupBy("face_size_bucket")
                .agg(
                    F.avg("mAP50").alias("avg_mAP50"),
                    F.avg("recall").alias("avg_recall"),
                    F.count("*").alias("count"),
                )
                .collect()
            )
            per_scale = {
                row["face_size_bucket"]: {
                    "avg_mAP50": round(row["avg_mAP50"], 4),
                    "avg_recall": round(row["avg_recall"], 4),
                    "count": row["count"],
                }
                for row in scale_df
            }

        # --- Per-class breakdown ---
        per_class = {}
        if "class_name" in df.columns:
            class_df = (
                df.groupBy("class_name")
                .agg(
                    F.avg("mAP50").alias("avg_mAP50"),
                    F.avg("precision").alias("avg_precision"),
                    F.avg("recall").alias("avg_recall"),
                    F.count("*").alias("count"),
                )
                .collect()
            )
            per_class = {
                row["class_name"]: {
                    "avg_mAP50": round(row["avg_mAP50"], 4),
                    "avg_precision": round(row["avg_precision"], 4),
                    "avg_recall": round(row["avg_recall"], 4),
                    "count": row["count"],
                }
                for row in class_df
            }

        # --- Failure analysis (images with mAP50 < 0.5) ---
        failure_rate = overall["failure_count"] / max(total_images, 1)

        result = {
            "run_id": run_id,
            "total_images": total_images,
            "overall": {
                "avg_mAP50": round(overall["avg_mAP50"] or 0, 4),
                "avg_mAP50_95": round(overall["avg_mAP50_95"] or 0, 4),
                "avg_recall": round(overall["avg_recall"] or 0, 4),
                "avg_precision": round(overall["avg_precision"] or 0, 4),
                "std_mAP50": round(overall["std_mAP50"] or 0, 4),
                "failure_rate": round(failure_rate, 4),
            },
            "per_scale": per_scale,
            "per_class": per_class,
        }

        logger.info(
            "Aggregation complete: %d images, mAP50=%.4f, recall=%.4f, failure_rate=%.4f",
            total_images,
            result["overall"]["avg_mAP50"],
            result["overall"]["avg_recall"],
            result["overall"]["failure_rate"],
        )

        return result

    finally:
        spark.stop()


def materialize_to_feature_store(aggregated: dict) -> None:
    """Write aggregated results to the feature store.

    Parameters
    ----------
    aggregated : dict
        Output from ``aggregate_eval_results()``.
    """
    from shml_features import FeatureClient

    run_id = aggregated.get("run_id")
    if not run_id:
        logger.warning(
            "No run_id in aggregated results, skipping feature store materialization"
        )
        return

    with FeatureClient() as client:
        client.materialize_eval_features(run_id)
        client.materialize_training_lineage(run_id)
        logger.info("Materialized features for run %s", run_id[:8])


def main():
    parser = argparse.ArgumentParser(description="Spark-based evaluation aggregation")
    parser.add_argument(
        "--results-dir", required=True, help="Directory with per-image JSON results"
    )
    parser.add_argument("--run-id", help="MLflow run ID for lineage tracking")
    parser.add_argument("--output", help="Output JSON path (default: stdout)")
    parser.add_argument(
        "--materialize", action="store_true", help="Write results to feature store"
    )
    args = parser.parse_args()

    result = aggregate_eval_results(args.results_dir, run_id=args.run_id)

    if not result:
        logger.error("No results to aggregate")
        sys.exit(1)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        logger.info("Results written to %s", args.output)
    else:
        print(json.dumps(result, indent=2))

    if args.materialize:
        materialize_to_feature_store(result)


if __name__ == "__main__":
    main()
