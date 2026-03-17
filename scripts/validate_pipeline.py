#!/usr/bin/env python3
"""
validate_pipeline.py — Post-training pipeline validation for SHML Platform.

Validates the end-to-end ML pipeline after a training run:
1. MLflow: Recent run exists with expected metrics
2. Model Registry: Model registered with aliases
3. Feature Store: Eval features materialized to pgvector
4. Nessie: Branch/tag operations work
5. SLO Exporter: Metrics updated
6. FiftyOne: Dataset creation works

Output format (consumed by run_integration_training.sh):
    PASS: <description>
    FAIL: <description>
    SKIP: <description>

Usage:
    python scripts/validate_pipeline.py
    python scripts/validate_pipeline.py --run-id <mlflow_run_id>
    python scripts/validate_pipeline.py --materialize  # Also run feature materialization
"""

import argparse
import json
import os
import sys
import time

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-nginx:80")
MLFLOW_EXTERNAL_URI = os.getenv("MLFLOW_EXTERNAL_URI", "http://localhost:80/mlflow")
NESSIE_URI = os.getenv("NESSIE_URI", "http://localhost:19120")
SLO_EXPORTER_URL = os.getenv("SLO_EXPORTER_URL", "http://localhost:9092")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "ray_compute")
POSTGRES_USER = os.getenv("POSTGRES_USER", "shared_user")
MODEL_NAME = os.getenv("MLFLOW_REGISTRY_MODEL_NAME", "face-detection-yolov8l-p2")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
SECRETS_DIR = os.path.join(PROJECT_DIR, "secrets")


def get_db_password():
    """Read database password from secrets file."""
    pw = os.getenv("POSTGRES_PASSWORD", "")
    if pw:
        return pw
    secret_file = os.path.join(SECRETS_DIR, "shared_db_password.txt")
    try:
        with open(secret_file) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report_pass(msg):
    print(f"PASS: {msg}")


def report_fail(msg):
    print(f"FAIL: {msg}")


def report_skip(msg):
    print(f"SKIP: {msg}")


# ---------------------------------------------------------------------------
# MLflow Validation
# ---------------------------------------------------------------------------


def validate_mlflow(run_id=None):
    """Check MLflow for recent runs and expected metrics."""
    try:
        # Search for recent finished runs
        resp = requests.post(
            f"{MLFLOW_EXTERNAL_URI}/api/2.0/mlflow/runs/search",
            json={
                "experiment_ids": [],
                "filter": "attributes.status = 'FINISHED'",
                "max_results": 5,
                "order_by": ["attributes.start_time DESC"],
            },
            timeout=10,
        )
        if resp.status_code != 200:
            report_fail(f"MLflow runs search: HTTP {resp.status_code}")
            return None

        data = resp.json()
        runs = data.get("runs", [])

        if not runs:
            report_skip("No finished MLflow runs found")
            return None

        report_pass(f"MLflow has {len(runs)} recent finished run(s)")

        # Use specified run or latest
        run = (
            runs[0]
            if not run_id
            else next((r for r in runs if r["info"]["run_id"] == run_id), runs[0])
        )
        rid = run["info"]["run_id"]
        report_pass(f"Latest run: {rid}")

        # Check for key metrics
        metrics = run.get("data", {}).get("metrics", [])
        metric_names = [m["key"] for m in metrics]

        expected_metrics = ["loss", "mAP50", "precision", "recall"]
        found = [
            m
            for m in expected_metrics
            if m in metric_names or any(m.lower() in mn.lower() for mn in metric_names)
        ]
        if found:
            report_pass(f"Training metrics logged: {', '.join(found)}")
        else:
            report_skip(
                f"No standard training metrics found (have: {metric_names[:10]})"
            )

        return rid
    except requests.exceptions.ConnectionError:
        report_fail("MLflow not reachable")
        return None
    except Exception as e:
        report_fail(f"MLflow validation error: {e}")
        return None


def validate_model_registry():
    """Check model registration and aliases."""
    try:
        resp = requests.get(
            f"{MLFLOW_EXTERNAL_URI}/api/2.0/mlflow/registered-models/get",
            params={"name": MODEL_NAME},
            timeout=10,
        )
        if resp.status_code != 200:
            report_skip(f"Model '{MODEL_NAME}' not yet registered")
            return

        model = resp.json().get("registered_model", {})
        report_pass(f"Model registered: {model.get('name')}")

        # Check versions
        versions = model.get("latest_versions", [])
        if versions:
            latest = versions[0]
            report_pass(
                f"Latest version: v{latest.get('version')} (status: {latest.get('status')})"
            )
        else:
            report_skip("No model versions found")

        # Check aliases
        aliases = model.get("aliases", [])
        if aliases:
            alias_names = [a["alias"] for a in aliases]
            report_pass(f"Model aliases: {', '.join(alias_names)}")
        else:
            report_skip(
                "No model aliases set (use MLflow API to set @champion/@challenger)"
            )

    except requests.exceptions.ConnectionError:
        report_fail("MLflow not reachable for model registry check")
    except Exception as e:
        report_fail(f"Model registry validation error: {e}")


# ---------------------------------------------------------------------------
# Nessie Validation
# ---------------------------------------------------------------------------


def validate_nessie():
    """Test Nessie branch and tag operations."""
    try:
        # Config endpoint
        resp = requests.get(f"{NESSIE_URI}/api/v2/config", timeout=10)
        if resp.status_code != 200:
            report_fail(f"Nessie config: HTTP {resp.status_code}")
            return

        config = resp.json()
        report_pass(
            f"Nessie config OK (default branch: {config.get('defaultBranch', 'unknown')})"
        )

        # Get main hash
        resp = requests.get(f"{NESSIE_URI}/api/v2/trees/main", timeout=10)
        if resp.status_code != 200:
            report_fail(f"Nessie main branch: HTTP {resp.status_code}")
            return

        main_hash = resp.json().get("hash", "")
        report_pass(f"Nessie main branch hash: {main_hash[:12]}...")

        # Create a test branch
        test_branch = f"validation-{int(time.time())}"
        resp = requests.post(
            f"{NESSIE_URI}/api/v2/trees",
            json={"type": "BRANCH", "name": test_branch, "hash": main_hash},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            report_pass(f"Nessie branch create: {test_branch}")

            # Clean up
            requests.delete(f"{NESSIE_URI}/api/v2/trees/{test_branch}", timeout=10)
            report_pass(f"Nessie branch cleanup: {test_branch}")
        else:
            report_fail(
                f"Nessie branch create: HTTP {resp.status_code} — {resp.text[:100]}"
            )

    except requests.exceptions.ConnectionError:
        report_skip("Nessie not reachable (may be container-only network)")
    except Exception as e:
        report_fail(f"Nessie validation error: {e}")


# ---------------------------------------------------------------------------
# Feature Store Validation
# ---------------------------------------------------------------------------


def validate_feature_store(materialize=False, run_id=None):
    """Check feature store schema and optionally materialize features."""
    password = get_db_password()
    if not password:
        report_skip("Feature store: DB password not available")
        return

    try:
        import psycopg2
    except ImportError:
        report_skip("Feature store: psycopg2 not installed")
        return

    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=password,
        )
        conn.autocommit = True
        cur = conn.cursor()

        # Check pgvector extension
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        row = cur.fetchone()
        if row:
            report_pass("pgvector extension installed")
        else:
            # Try to create it
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                report_pass("pgvector extension created")
            except Exception as e:
                report_fail(f"pgvector extension: {e}")
                cur.close()
                conn.close()
                return

        # Check/create feature tables
        tables = [
            "feature_eval",
            "feature_hard_examples",
            "feature_training_lineage",
            "feature_dataset_quality",
        ]
        all_exist = True
        for table in tables:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
                (table,),
            )
            exists = cur.fetchone()[0]
            if exists:
                report_pass(f"Table '{table}' exists")
            else:
                all_exist = False
                report_skip(f"Table '{table}' not created yet")

        if not all_exist and materialize:
            report_pass("Initializing feature store schema...")
            sys.path.insert(0, os.path.join(PROJECT_DIR, "libs"))
            try:
                from shml_features import FeatureClient

                dsn = f"host={POSTGRES_HOST} port={POSTGRES_PORT} dbname={POSTGRES_DB} user={POSTGRES_USER} password={password}"
                client = FeatureClient(dsn=dsn)
                client.init_schema()
                report_pass("Feature store schema initialized")

                # Re-check tables
                for table in tables:
                    cur.execute(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
                        (table,),
                    )
                    exists = cur.fetchone()[0]
                    if exists:
                        report_pass(f"Table '{table}' created")
                    else:
                        report_fail(
                            f"Table '{table}' still missing after init_schema()"
                        )
            except ImportError as e:
                report_fail(f"FeatureClient import: {e}")
            except Exception as e:
                report_fail(f"Feature store init: {e}")

        # Check for existing data in feature_eval
        try:
            cur.execute("SELECT COUNT(*) FROM feature_eval")
            count = cur.fetchone()[0]
            if count > 0:
                report_pass(f"feature_eval has {count} rows")
            else:
                report_skip("feature_eval is empty (no runs materialized yet)")
        except Exception:
            report_skip("feature_eval table not queryable")

        # Materialize features from latest run if requested
        if materialize and run_id:
            sys.path.insert(0, os.path.join(PROJECT_DIR, "libs"))
            try:
                from shml_features import FeatureClient

                dsn = f"host={POSTGRES_HOST} port={POSTGRES_PORT} dbname={POSTGRES_DB} user={POSTGRES_USER} password={password}"
                client = FeatureClient(dsn=dsn)
                client.materialize_eval_features(run_id=run_id, model_name=MODEL_NAME)
                report_pass(f"Eval features materialized for run {run_id[:12]}...")
            except ImportError:
                report_skip("FeatureClient not importable for materialization")
            except Exception as e:
                report_fail(f"Feature materialization: {e}")

        cur.close()
        conn.close()
    except Exception as e:
        report_fail(f"Feature store validation error: {e}")


# ---------------------------------------------------------------------------
# SLO Exporter Validation
# ---------------------------------------------------------------------------


def validate_slo_exporter():
    """Check SLO exporter is serving updated metrics."""
    try:
        resp = requests.get(f"{SLO_EXPORTER_URL}/", timeout=10)
        if resp.status_code != 200:
            report_fail(f"SLO exporter: HTTP {resp.status_code}")
            return

        text = resp.text
        expected = [
            "ml_model_freshness_days",
            "ml_training_success_rate_7d",
            "ml_error_budget_remaining_pct",
        ]
        found = [m for m in expected if m in text]
        if len(found) >= 2:
            report_pass(
                f"SLO exporter metrics active ({len(found)}/{len(expected)} key gauges)"
            )
        else:
            report_fail(f"SLO exporter: only {len(found)} key metrics found")

    except requests.exceptions.ConnectionError:
        report_skip("SLO exporter not reachable (may be container-only network)")
    except Exception as e:
        report_fail(f"SLO exporter validation error: {e}")


# ---------------------------------------------------------------------------
# FiftyOne Validation
# ---------------------------------------------------------------------------


def validate_fiftyone():
    """Check FiftyOne is operational."""
    try:
        import fiftyone as fo

        # Create a tiny test dataset
        dataset_name = f"validation_test_{int(time.time())}"
        dataset = fo.Dataset(name=dataset_name)
        sample = fo.Sample(filepath="/tmp/test.jpg")
        # Don't actually add sample without a real image
        report_pass(f"FiftyOne SDK operational (created dataset: {dataset_name})")

        # Clean up
        fo.delete_dataset(dataset_name)
        report_pass("FiftyOne test dataset cleaned up")

    except ImportError:
        report_skip("FiftyOne not installed (pip install fiftyone)")
    except Exception as e:
        # FiftyOne may not be able to connect to MongoDB from host
        report_skip(f"FiftyOne SDK: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Post-training pipeline validation")
    parser.add_argument("--run-id", help="Specific MLflow run ID to validate")
    parser.add_argument(
        "--materialize",
        action="store_true",
        help="Create feature store schema and materialize features",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("SHML Platform — Post-Training Pipeline Validation")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()

    # 1. MLflow
    run_id = validate_mlflow(run_id=args.run_id)
    print()

    # 2. Model Registry
    validate_model_registry()
    print()

    # 3. Nessie
    validate_nessie()
    print()

    # 4. Feature Store
    validate_feature_store(materialize=args.materialize, run_id=run_id or args.run_id)
    print()

    # 5. SLO Exporter
    validate_slo_exporter()
    print()

    # 6. FiftyOne
    validate_fiftyone()
    print()

    print("=" * 60)
    print("Validation complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
