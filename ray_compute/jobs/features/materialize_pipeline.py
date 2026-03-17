#!/usr/bin/env python3
"""
Phase 9: Feature Materialization Pipeline
==========================================

Materializes training features into the Feature Store (pgvector):
1. Eval metrics from MLflow → feature_eval table
2. Training lineage → feature_training_lineage table
3. CLIP embeddings from FiftyOne → feature_hard_examples table
4. Dataset quality metrics → feature_dataset_quality table

This pipeline bridges:
- MLflow (experiment tracking) → Feature Store (queryable metrics)
- FiftyOne Brain (embeddings) → Feature Store (similarity search)
- COCO dataset stats → Feature Store (data quality monitoring)

Usage:
    python materialize_pipeline.py --run-id <mlflow_run_id>
    python materialize_pipeline.py --run-id <run_id> --data-dir /data/face_detection
    python materialize_pipeline.py --init-schema  # Just create tables
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# SDK/libs path setup
_script_dir = os.path.dirname(os.path.abspath(__file__))
for p in [
    os.path.join(_script_dir, "..", "libs"),
    os.path.join(_script_dir, "..", "..", "..", "libs"),
    os.path.join(_script_dir, "..", "..", "libs"),
]:
    p = os.path.abspath(p)
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

FEATURE_CLIENT_AVAILABLE = False
try:
    from shml_features import FeatureClient

    FEATURE_CLIENT_AVAILABLE = True
except ImportError:
    pass

MLFLOW_AVAILABLE = False
try:
    import mlflow

    MLFLOW_AVAILABLE = True
except ImportError:
    pass


def get_db_password() -> str:
    """Read database password from secrets or environment."""
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if password:
        return password
    for sp in [
        "/run/secrets/shared_db_password",
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "secrets",
            "shared_db_password.txt",
        ),
        os.path.join(
            os.path.dirname(__file__), "..", "..", "secrets", "shared_db_password.txt"
        ),
    ]:
        try:
            with open(sp) as f:
                return f.read().strip()
        except FileNotFoundError:
            continue
    return ""


def create_feature_client() -> FeatureClient | None:
    """Create a FeatureClient with proper configuration."""
    if not FEATURE_CLIENT_AVAILABLE:
        print("⚠️  FeatureClient not available")
        return None

    password = get_db_password()
    if not password:
        print("⚠️  DB password not available")
        return None

    return FeatureClient(
        postgres_host=os.environ.get("POSTGRES_HOST", "postgres"),
        postgres_port=int(os.environ.get("POSTGRES_PORT", "5432")),
        postgres_db=os.environ.get("POSTGRES_DB", "inference"),
        postgres_user=os.environ.get("POSTGRES_USER", "inference"),
        postgres_password=password,
    )


def materialize_eval_features(client: FeatureClient, run_id: str) -> bool:
    """Materialize evaluation metrics from MLflow to feature_eval.

    Pulls the latest metrics from an MLflow run and stores them in
    the feature store for querying by downstream services (SLO exporter,
    Grafana dashboards, model comparison tools).
    """
    print("\n━━━ Eval Feature Materialization ━━━")

    try:
        ok = client.materialize_eval_features(run_id=run_id)
        if ok:
            print(f"  ✓ Eval features materialized for run {run_id[:12]}")
        else:
            print(f"  ⚠️  Eval materialization returned False")
        return ok
    except Exception as e:
        print(f"  ⚠️  Eval materialization failed: {e}")
        return False


def materialize_training_lineage(client: FeatureClient, run_id: str) -> bool:
    """Materialize training lineage for audit trail.

    Records: parent run, dataset version, hyperparameters, git commit,
    hardware, training duration — enabling full reproducibility.
    """
    print("\n━━━ Training Lineage Materialization ━━━")

    try:
        ok = client.materialize_training_lineage(run_id=run_id)
        if ok:
            print(f"  ✓ Training lineage materialized for run {run_id[:12]}")
        else:
            print(f"  ⚠️  Lineage materialization returned False")
        return ok
    except Exception as e:
        print(f"  ⚠️  Lineage materialization failed: {e}")
        return False


def materialize_dataset_quality(
    client: FeatureClient,
    data_dir: Path,
    run_id: str = "",
) -> bool:
    """Materialize dataset quality metrics to feature_dataset_quality.

    This fills the previously-empty feature_dataset_quality table with
    actual metrics from the merged face detection dataset.
    """
    print("\n━━━ Dataset Quality Materialization ━━━")

    info_path = data_dir / "dataset_info.json"
    if not info_path.exists():
        print(f"  ⚠️  Dataset info not found: {info_path}")
        return False

    try:
        with open(info_path) as f:
            info = json.load(f)

        stats = info.get("stats", {})
        sources = info.get("sources", [])

        conn = client._get_conn()
        with conn.cursor() as cur:
            for split, split_stats in stats.items():
                cur.execute(
                    """
                    INSERT INTO feature_dataset_quality
                        (dataset_name, split, total_images, total_annotations,
                         faces_per_image_mean, size_distribution, sources,
                         run_id, extra, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (dataset_name, split) DO UPDATE SET
                        total_images = EXCLUDED.total_images,
                        total_annotations = EXCLUDED.total_annotations,
                        faces_per_image_mean = EXCLUDED.faces_per_image_mean,
                        size_distribution = EXCLUDED.size_distribution,
                        run_id = EXCLUDED.run_id,
                        extra = EXCLUDED.extra,
                        created_at = NOW()
                """,
                    (
                        "face_detection_merged",
                        split,
                        split_stats.get("total_images", 0),
                        split_stats.get("total_annotations", 0),
                        split_stats.get("faces_per_image_mean", 0),
                        json.dumps(split_stats.get("face_size_distribution", {})),
                        json.dumps(sources),
                        run_id,
                        json.dumps(
                            {
                                "min_area": split_stats.get("min_area"),
                                "max_area": split_stats.get("max_area"),
                                "mean_area": split_stats.get("mean_area"),
                                "faces_per_image_median": split_stats.get(
                                    "faces_per_image_median"
                                ),
                            }
                        ),
                    ),
                )

            conn.commit()
            print(f"  ✓ Dataset quality metrics materialized for {len(stats)} splits")
            return True
    except Exception as e:
        print(f"  ⚠️  Dataset quality materialization failed: {e}")
        return False


def ensure_dataset_quality_table(client: FeatureClient) -> None:
    """Create feature_dataset_quality table if it doesn't exist.

    This was defined in FeatureClient.init_schema() but was never
    populated. Add missing columns needed for the pipeline.
    """
    conn = client._get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS feature_dataset_quality (
                id SERIAL PRIMARY KEY,
                dataset_name TEXT NOT NULL,
                split TEXT NOT NULL,
                total_images INT DEFAULT 0,
                total_annotations INT DEFAULT 0,
                faces_per_image_mean FLOAT DEFAULT 0,
                size_distribution JSONB DEFAULT '{}',
                sources JSONB DEFAULT '[]',
                run_id TEXT,
                extra JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (dataset_name, split)
            );
        """
        )
        conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Feature Materialization Pipeline")
    parser.add_argument(
        "--run-id", type=str, default="", help="MLflow run ID to materialize"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="/data/face_detection",
        help="Dataset directory for quality metrics",
    )
    parser.add_argument(
        "--init-schema", action="store_true", help="Initialize schema and exit"
    )
    parser.add_argument(
        "--skip-eval", action="store_true", help="Skip eval feature materialization"
    )
    parser.add_argument(
        "--skip-lineage",
        action="store_true",
        help="Skip training lineage materialization",
    )
    parser.add_argument(
        "--skip-quality",
        action="store_true",
        help="Skip dataset quality materialization",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Phase 9: Feature Materialization Pipeline")
    print("=" * 70)

    # Create client
    client = create_feature_client()
    if client is None:
        print("❌ Could not create FeatureClient")
        sys.exit(1)

    # Initialize schema
    print("\n━━━ Schema Initialization ━━━")
    try:
        client.init_schema()
        ensure_dataset_quality_table(client)
        print("  ✓ Feature store schema ready")
    except Exception as e:
        print(f"  ⚠️  Schema init failed: {e}")

    if args.init_schema:
        print("\n✅ Schema initialized")
        client.close()
        return

    results = {}

    # 1. Eval features
    if not args.skip_eval and args.run_id:
        results["eval"] = materialize_eval_features(client, args.run_id)

    # 2. Training lineage
    if not args.skip_lineage and args.run_id:
        results["lineage"] = materialize_training_lineage(client, args.run_id)

    # 3. Dataset quality
    if not args.skip_quality:
        data_dir = Path(args.data_dir)
        results["quality"] = materialize_dataset_quality(
            client, data_dir, run_id=args.run_id
        )

    # Summary
    print("\n" + "=" * 70)
    print("MATERIALIZATION SUMMARY")
    print("=" * 70)
    for key, success in results.items():
        print(f"  {key:20s}: {'✅' if success else '⚠️'}")
    print("=" * 70)

    client.close()
    print("\n✅ Materialization pipeline complete")


if __name__ == "__main__":
    main()
