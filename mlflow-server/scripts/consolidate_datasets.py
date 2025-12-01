#!/usr/bin/env python3
"""
Consolidate scattered datasets into organized registry.

This script:
1. Identifies duplicate/scattered datasets in experiment 10
2. Creates consolidated runs in a new 'dataset-registry' experiment
3. Organizes datasets with proper tags and metadata
4. Generates cleanup report

Usage:
    python consolidate_datasets.py --dry-run  # Preview changes
    python consolidate_datasets.py --execute  # Apply changes
"""

import mlflow
from mlflow.tracking import MlflowClient
import os
import sys
import hashlib
from pathlib import Path
from collections import defaultdict
import json
import argparse


# Configuration
TRACKING_URI = "http://localhost:5000"
OLD_EXPERIMENT = "dataset-archives"  # Experiment ID 10
NEW_EXPERIMENT = "dataset-registry"
ARTIFACT_ROOT = "/opt/mlflow/artifacts"


def get_file_info(filepath):
    """Get file size and checksum."""
    size = os.path.getsize(filepath)

    # Calculate MD5 for smaller files only
    checksum = None
    if size < 100 * 1024 * 1024:  # Only hash files < 100MB
        md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5.update(chunk)
        checksum = md5.hexdigest()

    return {"size": size, "size_human": format_size(size), "checksum": checksum}


def format_size(bytes_size):
    """Convert bytes to human readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f}{unit}"
        bytes_size /= 1024.0


def analyze_existing_datasets(client):
    """Analyze current dataset artifacts."""
    print("\n" + "=" * 80)
    print("ANALYZING EXISTING DATASETS")
    print("=" * 80)

    try:
        experiment = client.get_experiment_by_name(OLD_EXPERIMENT)
        if not experiment:
            print(f"❌ Experiment '{OLD_EXPERIMENT}' not found")
            return None

        exp_id = experiment.experiment_id
    except Exception as e:
        print(f"❌ Error getting experiment: {e}")
        return None

    # Get all runs
    runs = client.search_runs(experiment_ids=[exp_id])

    datasets = defaultdict(list)
    total_size = 0

    print(f"\nFound {len(runs)} runs in '{OLD_EXPERIMENT}':\n")

    for run in runs:
        run_id = run.info.run_id
        artifact_uri = run.info.artifact_uri

        # Get artifact path - handle mlflow-artifacts:/ URI format
        if artifact_uri.startswith("mlflow-artifacts:/"):
            # mlflow-artifacts:/10/runid/artifacts -> /opt/mlflow/artifacts/10/runid/artifacts
            artifact_path = artifact_uri.replace(
                "mlflow-artifacts:/", ARTIFACT_ROOT + "/"
            )
        else:
            artifact_path = artifact_uri.replace("mlflow-artifacts:/", ARTIFACT_ROOT)

        if os.path.exists(artifact_path):
            for root, dirs, files in os.walk(artifact_path):
                for file in files:
                    filepath = os.path.join(root, file)
                    file_info = get_file_info(filepath)

                    # Categorize datasets
                    filename = file.lower()
                    if "wider" in filename:
                        if "train" in filename:
                            category = "WIDER-train"
                        elif "test" in filename:
                            category = "WIDER-test"
                        elif "val" in filename:
                            category = "WIDER-val"
                        elif "split" in filename:
                            category = "WIDER-split"
                        else:
                            category = "WIDER-other"
                    elif "synthetic" in filename:
                        category = "synthetic-data"
                    elif "downloads" in filename:
                        category = "downloads"
                    else:
                        category = "other"

                    datasets[category].append(
                        {
                            "run_id": run_id,
                            "filename": file,
                            "filepath": filepath,
                            "relative_path": os.path.relpath(filepath, artifact_path),
                            **file_info,
                        }
                    )

                    total_size += file_info["size"]

                    print(
                        f"  Run: {run_id[:8]}... | {file_info['size_human']:>8} | {file}"
                    )

    print(f"\nTotal size: {format_size(total_size)}")
    print(f"\nDataset categories found:")
    for category, files in datasets.items():
        category_size = sum(f["size"] for f in files)
        print(f"  {category}: {len(files)} files, {format_size(category_size)}")

    return datasets, total_size


def plan_consolidation(datasets):
    """Create consolidation plan."""
    print("\n" + "=" * 80)
    print("CONSOLIDATION PLAN")
    print("=" * 80)

    plan = []

    # Group WIDER dataset parts
    wider_train_parts = [
        f for f in datasets.get("WIDER-train", []) if "part" in f["filename"]
    ]
    wider_test_parts = [
        f for f in datasets.get("WIDER-test", []) if "part" in f["filename"]
    ]

    if wider_train_parts:
        plan.append(
            {
                "name": "WIDER-face-train-v1.0",
                "description": "WIDER Face training dataset (consolidated)",
                "files": wider_train_parts,
                "tags": {
                    "artifact_type": "dataset",
                    "dataset_name": "WIDER-face-train",
                    "dataset_version": "1.0",
                    "dataset_type": "face_detection",
                    "split": "train",
                },
            }
        )

    if wider_test_parts:
        plan.append(
            {
                "name": "WIDER-face-test-v1.0",
                "description": "WIDER Face test dataset (consolidated)",
                "files": wider_test_parts,
                "tags": {
                    "artifact_type": "dataset",
                    "dataset_name": "WIDER-face-test",
                    "dataset_version": "1.0",
                    "dataset_type": "face_detection",
                    "split": "test",
                },
            }
        )

    # WIDER val
    wider_val = datasets.get("WIDER-val", [])
    if wider_val:
        plan.append(
            {
                "name": "WIDER-face-val-v1.0",
                "description": "WIDER Face validation dataset",
                "files": wider_val,
                "tags": {
                    "artifact_type": "dataset",
                    "dataset_name": "WIDER-face-val",
                    "dataset_version": "1.0",
                    "dataset_type": "face_detection",
                    "split": "validation",
                },
            }
        )

    # WIDER split metadata
    wider_split = datasets.get("WIDER-split", [])
    if wider_split:
        plan.append(
            {
                "name": "WIDER-face-split-v1.0",
                "description": "WIDER Face dataset split metadata",
                "files": wider_split,
                "tags": {
                    "artifact_type": "dataset",
                    "dataset_name": "WIDER-face-split",
                    "dataset_version": "1.0",
                    "dataset_type": "metadata",
                },
            }
        )

    # Synthetic data
    synthetic = datasets.get("synthetic-data", [])
    if synthetic:
        plan.append(
            {
                "name": "synthetic-data-v1.0",
                "description": "Synthetic training data",
                "files": synthetic,
                "tags": {
                    "artifact_type": "dataset",
                    "dataset_name": "synthetic-data",
                    "dataset_version": "1.0",
                    "dataset_type": "synthetic",
                },
            }
        )

    # Print plan
    print(f"\nWill create {len(plan)} consolidated runs:\n")
    for item in plan:
        total_size = sum(f["size"] for f in item["files"])
        print(f"  ✓ {item['name']}")
        print(f"    Files: {len(item['files'])} ({format_size(total_size)})")
        print(f"    Tags: {item['tags']}")
        print()

    return plan


def execute_consolidation(client, plan, dry_run=True):
    """Execute or simulate consolidation."""
    print("\n" + "=" * 80)
    if dry_run:
        print("DRY RUN - No changes will be made")
    else:
        print("EXECUTING CONSOLIDATION")
    print("=" * 80)

    mlflow.set_tracking_uri(TRACKING_URI)

    # Create/get new experiment
    try:
        experiment_id = client.create_experiment(NEW_EXPERIMENT)
        print(f"\n✓ Created experiment: {NEW_EXPERIMENT}")
    except Exception:
        experiment = client.get_experiment_by_name(NEW_EXPERIMENT)
        experiment_id = experiment.experiment_id
        print(f"\n✓ Using existing experiment: {NEW_EXPERIMENT}")

    mlflow.set_experiment(NEW_EXPERIMENT)

    for item in plan:
        print(f"\n{'[DRY RUN] ' if dry_run else ''}Creating run: {item['name']}")

        if dry_run:
            print(f"  Would create run with:")
            print(f"    Name: {item['name']}")
            print(f"    Description: {item['description']}")
            print(f"    Tags: {json.dumps(item['tags'], indent=6)}")
            print(f"    Files to reference:")
            for f in item["files"]:
                print(f"      - {f['filename']} ({f['size_human']})")
        else:
            try:
                with mlflow.start_run(run_name=item["name"]) as run:
                    # Set tags
                    for key, value in item["tags"].items():
                        mlflow.set_tag(key, value)

                    # Set description
                    mlflow.set_tag("mlflow.note.content", item["description"])

                    # Log file paths as parameters (don't re-upload large files)
                    for idx, f in enumerate(item["files"]):
                        mlflow.log_param(f"file_{idx}_name", f["filename"])
                        mlflow.log_param(f"file_{idx}_path", f["filepath"])
                        mlflow.log_param(f"file_{idx}_size", f["size_human"])
                        if f["checksum"]:
                            mlflow.log_param(f"file_{idx}_md5", f["checksum"])

                    # Log metadata
                    mlflow.log_param("num_files", len(item["files"]))
                    total_size = sum(f["size"] for f in item["files"])
                    mlflow.log_param("total_size", format_size(total_size))

                    # Create metadata file
                    metadata = {
                        "name": item["name"],
                        "description": item["description"],
                        "files": [
                            {
                                "filename": f["filename"],
                                "path": f["filepath"],
                                "size": f["size_human"],
                                "checksum": f.get("checksum"),
                            }
                            for f in item["files"]
                        ],
                        "total_size": format_size(total_size),
                        "num_files": len(item["files"]),
                    }

                    # Save metadata
                    metadata_path = f"/tmp/dataset_metadata_{run.info.run_id}.json"
                    with open(metadata_path, "w") as f:
                        json.dump(metadata, f, indent=2)

                    mlflow.log_artifact(metadata_path, "metadata")
                    os.remove(metadata_path)

                    print(f"  ✓ Created run: {run.info.run_id}")
                    print(
                        f"    View: {TRACKING_URI}/#/experiments/{experiment_id}/runs/{run.info.run_id}"
                    )

            except Exception as e:
                print(f"  ❌ Error: {e}")


def generate_report(datasets, plan, output_file="consolidation_report.txt"):
    """Generate consolidation report."""
    print("\n" + "=" * 80)
    print("GENERATING REPORT")
    print("=" * 80)

    with open(output_file, "w") as f:
        f.write("Dataset Consolidation Report\n")
        f.write("=" * 80 + "\n\n")

        f.write("Current State:\n")
        f.write("-" * 40 + "\n")
        for category, files in datasets.items():
            category_size = sum(file["size"] for file in files)
            f.write(f"{category}:\n")
            f.write(f"  Files: {len(files)}\n")
            f.write(f"  Size: {format_size(category_size)}\n")
            for file in files:
                f.write(f"    - {file['filename']} ({file['size_human']})\n")
            f.write("\n")

        f.write("\nProposed Consolidation:\n")
        f.write("-" * 40 + "\n")
        for item in plan:
            total_size = sum(file["size"] for file in item["files"])
            f.write(f"{item['name']}:\n")
            f.write(f"  Description: {item['description']}\n")
            f.write(f"  Files: {len(item['files'])}\n")
            f.write(f"  Size: {format_size(total_size)}\n")
            f.write(f"  Tags:\n")
            for key, value in item["tags"].items():
                f.write(f"    {key}: {value}\n")
            f.write("\n")

    print(f"✓ Report saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Consolidate MLflow dataset artifacts")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute consolidation (default: dry-run)",
    )
    parser.add_argument(
        "--report",
        type=str,
        default="consolidation_report.txt",
        help="Report output file",
    )
    args = parser.parse_args()

    dry_run = not args.execute

    print("\n" + "=" * 80)
    print("MLflow Dataset Consolidation Tool")
    print("=" * 80)
    print(f"Tracking URI: {TRACKING_URI}")
    print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
    print("=" * 80)

    # Initialize client
    mlflow.set_tracking_uri(TRACKING_URI)
    client = MlflowClient(TRACKING_URI)

    # Analyze
    result = analyze_existing_datasets(client)
    if not result:
        print("\n❌ Analysis failed")
        return 1

    datasets, total_size = result

    # Plan
    plan = plan_consolidation(datasets)
    if not plan:
        print("\n⚠️  No consolidation needed")
        return 0

    # Execute
    execute_consolidation(client, plan, dry_run=dry_run)

    # Report
    generate_report(datasets, plan, args.report)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total datasets analyzed: {sum(len(files) for files in datasets.values())}")
    print(f"Consolidated runs to create: {len(plan)}")
    print(f"Total size: {format_size(total_size)}")

    if dry_run:
        print("\n⚠️  This was a DRY RUN. No changes were made.")
        print("To execute consolidation, run with --execute flag:")
        print(f"  python {sys.argv[0]} --execute")
    else:
        print(f"\n✓ Consolidation complete!")
        print(f"View results: {TRACKING_URI}/#/experiments/11")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
