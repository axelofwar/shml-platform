#!/usr/bin/env python3
"""
Replay Week 1 baseline runs to the remote MLflow server.

Problem: Week 1 baselines were stored locally at file:///...
because the OAuth path wasn't working. This script reads the
local file-backed runs and re-creates them on the remote
MLflow server so all future comparisons are apples-to-apples.

Usage:
    # Source OAuth first
    source scripts/auth/export_mlflow_oauth_env.sh
    source ~/.config/shml/mlflow_oauth.env

    # Then replay
    python scripts/benchmarking/replay_baselines_to_remote.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import mlflow

LOCAL_STORE = PROJECT_ROOT / "runs" / "week1_mlflow"
LOCAL_EXPERIMENT_ID = "336449102121561788"
REMOTE_EXPERIMENT = "platform-benchmarking"


def _read_local_run(run_dir: Path) -> dict:
    """Read a local file-backed MLflow run into a dict."""
    import yaml

    meta = yaml.safe_load((run_dir / "meta.yaml").read_text())

    params = {}
    params_dir = run_dir / "params"
    if params_dir.is_dir():
        for pfile in params_dir.iterdir():
            params[pfile.name] = pfile.read_text().strip()

    metrics = {}
    metrics_dir = run_dir / "metrics"
    if metrics_dir.is_dir():
        for mfile in metrics_dir.iterdir():
            lines = mfile.read_text().strip().split("\n")
            last = lines[-1].split()
            metrics[mfile.name] = float(last[1]) if len(last) >= 2 else 0.0

    tags = {}
    tags_dir = run_dir / "tags"
    if tags_dir.is_dir():
        for tfile in tags_dir.iterdir():
            if not tfile.name.startswith("mlflow."):
                tags[tfile.name] = tfile.read_text().strip()

    # Read benchmark metadata artifact if present
    metadata = {}
    meta_artifact = run_dir / "artifacts" / "benchmark" / "benchmark_metadata.json"
    if meta_artifact.exists():
        metadata = json.loads(meta_artifact.read_text())

    return {
        "run_id": meta.get("run_id"),
        "run_name": meta.get("run_name"),
        "params": params,
        "metrics": metrics,
        "tags": tags,
        "metadata": metadata,
    }


def replay_to_remote() -> dict[str, str]:
    """
    Replay all local Week 1 runs to the remote MLflow server.

    Returns:
        Mapping of local_run_id -> remote_run_id
    """
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not tracking_uri or "shml-platform" not in tracking_uri:
        print("ERROR: MLFLOW_TRACKING_URI not set or not pointing to remote server.")
        print("Run: source scripts/auth/export_mlflow_oauth_env.sh")
        print("     source ~/.config/shml/mlflow_oauth.env")
        sys.exit(1)

    mlflow.set_tracking_uri(tracking_uri)

    # Get or create experiment
    exp = mlflow.get_experiment_by_name(REMOTE_EXPERIMENT)
    if exp is not None:
        experiment_id = exp.experiment_id
    else:
        experiment_id = mlflow.create_experiment(name=REMOTE_EXPERIMENT)

    print(f"Remote MLflow: {tracking_uri}")
    print(f"Experiment: {REMOTE_EXPERIMENT} (id={experiment_id})")
    print()

    # Read all local runs
    local_exp_dir = LOCAL_STORE / LOCAL_EXPERIMENT_ID
    if not local_exp_dir.is_dir():
        print(f"ERROR: Local experiment dir not found: {local_exp_dir}")
        sys.exit(1)

    run_dirs = sorted(
        [
            d
            for d in local_exp_dir.iterdir()
            if d.is_dir() and (d / "meta.yaml").exists()
        ]
    )

    print(f"Found {len(run_dirs)} local runs to replay")
    print("=" * 60)

    id_map: dict[str, str] = {}

    for run_dir in run_dirs:
        local_data = _read_local_run(run_dir)
        local_id = local_data["run_id"]
        run_name = local_data["run_name"]
        print(f"\nReplaying: {run_name}")
        print(f"  Local ID:  {local_id}")

        # Add replay provenance tags
        replay_tags = {
            **local_data["tags"],
            "replay.source": "local-file-store",
            "replay.original_run_id": local_id,
            "replay.reason": "week1-oauth-path-fix",
        }

        with mlflow.start_run(
            experiment_id=experiment_id,
            run_name=run_name,
            tags=replay_tags,
        ) as run:
            remote_id = run.info.run_id

            # Log params
            if local_data["params"]:
                mlflow.log_params(local_data["params"])

            # Log metrics
            if local_data["metrics"]:
                mlflow.log_metrics(local_data["metrics"])

            # Log metadata artifact
            if local_data["metadata"]:
                with tempfile.TemporaryDirectory(prefix="replay-") as tmp:
                    meta_file = Path(tmp) / "benchmark_metadata.json"
                    meta_file.write_text(
                        json.dumps(local_data["metadata"], indent=2, sort_keys=True),
                        encoding="utf-8",
                    )
                    mlflow.log_artifact(str(meta_file), artifact_path="benchmark")

            id_map[local_id] = remote_id
            print(f"  Remote ID: {remote_id}  ✓")

    print()
    print("=" * 60)
    print(f"Replayed {len(id_map)} runs successfully")

    # Save the ID mapping for reference
    mapping_file = PROJECT_ROOT / "runs" / "week1_local_to_remote_id_map.json"
    mapping_file.write_text(json.dumps(id_map, indent=2, sort_keys=True))
    print(f"ID mapping saved to: {mapping_file}")

    return id_map


if __name__ == "__main__":
    replay_to_remote()
