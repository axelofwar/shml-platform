#!/usr/bin/env python3
"""Scheduled Feature Materialization Job.

Ray job that:
1. Reads the feature registry for active views
2. For each view due for refresh, runs the materialization pipeline
3. Records run start/completion in the registry
4. Updates the SLO exporter with per-view freshness

Usage (via Ray job submission):
    python scheduled_materialize.py
    python scheduled_materialize.py --view eval_metrics
    python scheduled_materialize.py --force  # Ignore schedule, run all
    python scheduled_materialize.py --dry-run

Can also be submitted via the Ray Compute API:
    POST /api/v1/jobs
    {"name": "feature-materialize", "entrypoint": "python scheduled_materialize.py"}
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

# Path setup for libs
_script_dir = os.path.dirname(os.path.abspath(__file__))
for p in [
    os.path.join(_script_dir, "..", "libs"),
    os.path.join(_script_dir, "..", "..", "libs"),
    os.path.join(_script_dir, "..", "..", "..", "libs"),
]:
    p = os.path.abspath(p)
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

# Add features module to path
for p in [
    os.path.join(_script_dir, ".."),
    os.path.join(_script_dir, "..", ".."),
]:
    p = os.path.abspath(p)
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("feature-materialize")

# ---------------------------------------------------------------------------
# Schedule parsing
# ---------------------------------------------------------------------------

SCHEDULE_INTERVALS = {
    "@hourly": 60,  # minutes
    "@daily": 1440,  # 24 hours
    "@weekly": 10080,  # 7 days
}


def is_due_for_refresh(
    schedule: str,
    last_materialized: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Check if a feature view is due for materialization based on schedule."""
    if now is None:
        now = datetime.now(timezone.utc)
    if last_materialized is None:
        return True  # Never materialized

    interval_minutes = SCHEDULE_INTERVALS.get(schedule)
    if interval_minutes is None:
        # Try parsing cron-like, default to hourly
        logger.warning("Unknown schedule '%s', defaulting to hourly", schedule)
        interval_minutes = 60

    if last_materialized.tzinfo is None:
        last_materialized = last_materialized.replace(tzinfo=timezone.utc)

    elapsed = (now - last_materialized).total_seconds() / 60.0
    return elapsed >= interval_minutes


# ---------------------------------------------------------------------------
# Materialization logic
# ---------------------------------------------------------------------------


def materialize_view(view_name: str, source_table: str, pg_config: dict) -> dict:
    """Run materialization for a single feature view.

    For the existing feature tables, "materialization" means:
    - eval_metrics: pull latest MLflow runs → upsert into feature_eval
    - training_lineage: pull latest runs → upsert into feature_training_lineage
    - dataset_quality: scan dataset dirs → upsert into feature_dataset_quality
    - hard_examples: pull FiftyOne brain results → upsert into feature_hard_examples

    Returns a dict with {rows_written, duration_seconds, error?}.
    """
    start = time.monotonic()
    result = {
        "view": view_name,
        "rows_written": 0,
        "duration_seconds": 0,
        "error": None,
    }

    try:
        if view_name == "eval_metrics":
            result["rows_written"] = _materialize_eval_metrics(pg_config)
        elif view_name == "training_lineage":
            result["rows_written"] = _materialize_training_lineage(pg_config)
        elif view_name == "dataset_quality":
            result["rows_written"] = _materialize_dataset_quality(pg_config)
        elif view_name == "hard_examples":
            # Hard examples only change after eval runs with CLIP, skip if no new data
            result["rows_written"] = 0
            logger.info(
                "hard_examples: skipped (CLIP embeddings only update after eval runs)"
            )
        else:
            logger.warning("No materialization logic for view '%s'", view_name)
    except Exception as e:
        result["error"] = str(e)
        logger.error("Materialization failed for %s: %s", view_name, e)

    result["duration_seconds"] = round(time.monotonic() - start, 2)
    return result


def _materialize_eval_metrics(pg_config: dict) -> int:
    """Pull recent MLflow runs and upsert eval features."""
    try:
        from shml_features import FeatureClient
    except ImportError:
        logger.warning("FeatureClient not available, skipping eval_metrics")
        return 0

    import requests

    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow-nginx:80")
    url = f"{mlflow_uri}/api/2.0/mlflow/runs/search"

    # Find recent finished runs with eval metrics
    payload = {
        "max_results": 50,
        "order_by": ["attributes.end_time DESC"],
        "filter": "attributes.status = 'FINISHED'",
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        runs = resp.json().get("runs", [])
    except Exception as e:
        logger.error("Failed to query MLflow: %s", e)
        return 0

    client = FeatureClient(
        postgres_host=pg_config["host"],
        postgres_port=pg_config["port"],
        postgres_db=pg_config["dbname"],
        postgres_user=pg_config["user"],
        postgres_password=pg_config["password"],
    )

    rows = 0
    for run in runs:
        run_id = run.get("info", {}).get("run_id")
        if not run_id:
            continue
        # Only materialize runs that have eval metrics
        metrics = {m["key"]: m["value"] for m in run.get("data", {}).get("metrics", [])}
        has_eval = any(
            k in metrics for k in ["mAP50", "final_mAP50", "precision", "recall"]
        )
        if has_eval:
            try:
                if client.materialize_eval_features(run_id):
                    rows += 1
            except Exception as e:
                logger.warning("Failed to materialize run %s: %s", run_id[:8], e)

    client.close()
    return rows


def _materialize_training_lineage(pg_config: dict) -> int:
    """Pull recent MLflow runs and upsert training lineage."""
    try:
        from shml_features import FeatureClient
    except ImportError:
        logger.warning("FeatureClient not available, skipping training_lineage")
        return 0

    import requests

    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow-nginx:80")
    url = f"{mlflow_uri}/api/2.0/mlflow/runs/search"

    payload = {
        "max_results": 50,
        "order_by": ["attributes.end_time DESC"],
        "filter": "attributes.status = 'FINISHED'",
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        runs = resp.json().get("runs", [])
    except Exception as e:
        logger.error("Failed to query MLflow: %s", e)
        return 0

    client = FeatureClient(
        postgres_host=pg_config["host"],
        postgres_port=pg_config["port"],
        postgres_db=pg_config["dbname"],
        postgres_user=pg_config["user"],
        postgres_password=pg_config["password"],
    )

    rows = 0
    for run in runs:
        run_id = run.get("info", {}).get("run_id")
        if not run_id:
            continue
        try:
            if client.materialize_training_lineage(run_id):
                rows += 1
        except Exception as e:
            logger.warning("Failed to materialize lineage for %s: %s", run_id[:8], e)

    client.close()
    return rows


def _materialize_dataset_quality(pg_config: dict) -> int:
    """Scan known dataset directories and update quality metrics."""
    import psycopg2

    data_dirs = [
        "/data/face_detection",
        "/opt/ray/data",
    ]

    conn = psycopg2.connect(**pg_config)
    rows = 0

    for data_dir in data_dirs:
        if not os.path.isdir(data_dir):
            continue
        for split in ["train", "val", "test"]:
            split_dir = os.path.join(data_dir, split, "images")
            labels_dir = os.path.join(data_dir, split, "labels")
            if not os.path.isdir(split_dir):
                continue

            images = [
                f
                for f in os.listdir(split_dir)
                if f.endswith((".jpg", ".png", ".jpeg"))
            ]
            total_images = len(images)

            # Count annotations
            total_annots = 0
            missing_annots = 0
            if os.path.isdir(labels_dir):
                for img in images:
                    label_file = os.path.join(
                        labels_dir, os.path.splitext(img)[0] + ".txt"
                    )
                    if os.path.exists(label_file):
                        with open(label_file) as f:
                            total_annots += len(f.readlines())
                    else:
                        missing_annots += 1

            missing_rate = missing_annots / total_images if total_images > 0 else 0
            dataset_name = os.path.basename(data_dir)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO feature_dataset_quality
                        (dataset_name, split, total_images, missing_annot_rate, extra, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (dataset_name, split) DO UPDATE SET
                        total_images = EXCLUDED.total_images,
                        missing_annot_rate = EXCLUDED.missing_annot_rate,
                        extra = EXCLUDED.extra,
                        updated_at = NOW()
                """,
                    (
                        dataset_name,
                        split,
                        total_images,
                        missing_rate,
                        json.dumps({"total_annotations": total_annots}),
                    ),
                )
                rows += 1

    conn.commit()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Scheduled feature materialization")
    parser.add_argument("--view", type=str, help="Only materialize this specific view")
    parser.add_argument(
        "--force", action="store_true", help="Ignore schedule, run all views"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would run without executing"
    )
    args = parser.parse_args()

    # Build pg config
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password:
        for sp in [
            "/run/secrets/shared_db_password",
            os.path.join(_script_dir, "..", "..", "secrets", "shared_db_password.txt"),
            os.path.join(_script_dir, "..", "secrets", "shared_db_password.txt"),
        ]:
            try:
                with open(sp) as f:
                    password = f.read().strip()
                    break
            except FileNotFoundError:
                continue

    pg_config = {
        "host": os.environ.get("POSTGRES_HOST", "postgres"),
        "port": int(os.environ.get("POSTGRES_PORT", "5432")),
        "dbname": os.environ.get("POSTGRES_FEATURES_DB", "inference"),
        "user": os.environ.get("POSTGRES_USER", "inference"),
        "password": password,
    }

    # Import registry
    try:
        sys.path.insert(0, os.path.join(_script_dir, ".."))
        from ray_compute.features.registry import (
            FeatureRegistry,
            MaterializationRun,
            MaterializationStatus,
        )
        from ray_compute.features.definitions import register_builtin_views
    except ImportError:
        # Fallback: try relative
        try:
            from features.registry import (
                FeatureRegistry,
                MaterializationRun,
                MaterializationStatus,
            )
            from features.definitions import register_builtin_views
        except ImportError as e:
            logger.error("Cannot import feature registry: %s", e)
            sys.exit(1)

    registry = FeatureRegistry(pg_config)
    registry.init_schema()
    register_builtin_views(registry)

    views = registry.list_views(status="active")
    logger.info("Found %d active feature views", len(views))

    if args.view:
        views = [v for v in views if v.name == args.view]
        if not views:
            logger.error("Feature view '%s' not found or not active", args.view)
            sys.exit(1)

    total_start = time.monotonic()
    results = []

    for view in views:
        due = args.force or is_due_for_refresh(
            view.schedule,
            view.last_materialized_at,
        )

        if not due:
            logger.info(
                "⏭  %s: not due (last=%s, schedule=%s)",
                view.name,
                (
                    view.last_materialized_at.isoformat()
                    if view.last_materialized_at
                    else "never"
                ),
                view.schedule,
            )
            continue

        if args.dry_run:
            logger.info(
                "🔍 [DRY RUN] Would materialize: %s (table=%s)",
                view.name,
                view.source_table,
            )
            continue

        # Record run start
        run = MaterializationRun(
            feature_view_name=view.name,
            status=MaterializationStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        registry.record_run_start(run)

        logger.info("▶  Materializing: %s (table=%s)", view.name, view.source_table)
        result = materialize_view(view.name, view.source_table, pg_config)
        results.append(result)

        # Record completion
        if result["error"]:
            registry.record_run_complete(
                run.run_id,
                MaterializationStatus.FAILED,
                rows_written=result["rows_written"],
                error_message=result["error"],
            )
            logger.error("✗  %s: FAILED (%s)", view.name, result["error"])
        else:
            registry.record_run_complete(
                run.run_id,
                MaterializationStatus.SUCCEEDED,
                rows_written=result["rows_written"],
            )
            logger.info(
                "✓  %s: %d rows in %.1fs",
                view.name,
                result["rows_written"],
                result["duration_seconds"],
            )

    total_elapsed = time.monotonic() - total_start

    # Summary
    if results:
        succeeded = sum(1 for r in results if not r["error"])
        failed = sum(1 for r in results if r["error"])
        total_rows = sum(r["rows_written"] for r in results)
        logger.info(
            "\n═══ Materialization Summary ═══\n"
            "  Views processed: %d (%d succeeded, %d failed)\n"
            "  Total rows written: %d\n"
            "  Total time: %.1fs\n",
            len(results),
            succeeded,
            failed,
            total_rows,
            total_elapsed,
        )
    elif not args.dry_run:
        logger.info("No views due for materialization")

    registry.close()


if __name__ == "__main__":
    main()
