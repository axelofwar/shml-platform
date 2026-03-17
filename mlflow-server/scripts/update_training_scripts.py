#!/usr/bin/env python3
"""
Update Training Scripts for Remote MLflow Tracking

This script updates your training scripts to use the remote MLflow server
by ensuring they respect the MLFLOW_TRACKING_URI environment variable.
"""

import os
import re
from pathlib import Path

# Configuration
MLFLOW_SERVER_URI = "http://<SERVER_IP>:5000"
SCRIPTS_DIR = Path("/workspace/scripts")
BACKUP_DIR = Path("/workspace/BACKUP_BEFORE_MLFLOW_UPDATE")

# Scripts to update
TRAINING_SCRIPTS = [
    "train/train_local.py",
    "train/train_kaggle.py",
]


def backup_file(filepath):
    """Create backup of file before modification"""
    BACKUP_DIR.mkdir(exist_ok=True)
    backup_path = BACKUP_DIR / filepath.name
    import shutil

    shutil.copy2(filepath, backup_path)
    print(f"  ✓ Backed up to: {backup_path}")


def check_mlflow_imports(content):
    """Check if file uses MLflow"""
    return "import mlflow" in content or "from mlflow" in content


def has_tracking_uri_set(content):
    """Check if tracking URI is already set"""
    patterns = [
        r"mlflow\.set_tracking_uri\(",
        r"MLFLOW_TRACKING_URI",
    ]
    return any(re.search(pattern, content) for pattern in patterns)


def add_tracking_uri_comment(content):
    """Add comment about MLFLOW_TRACKING_URI environment variable"""

    # Find mlflow import location
    import_pattern = r"(import mlflow\n|from mlflow.*\n)"
    match = re.search(import_pattern, content)

    if not match:
        return content

    # Check if comment already exists
    if "MLFLOW_TRACKING_URI" in content:
        return content

    # Add comment after imports
    comment = """
# MLflow Tracking Configuration
# Uses MLFLOW_TRACKING_URI environment variable (set by setup_remote_tracking.sh)
# Default: http://<SERVER_IP>:5000 (remote server)
# To use local: unset MLFLOW_TRACKING_URI or set to 'file:./mlruns'
"""

    insert_pos = match.end()
    return content[:insert_pos] + comment + content[insert_pos:]


def update_script(filepath):
    """Update a single training script"""
    print(f"\nChecking: {filepath}")

    if not filepath.exists():
        print(f"  ⚠️  File not found, skipping")
        return False

    # Read content
    content = filepath.read_text()

    # Check if uses MLflow
    if not check_mlflow_imports(content):
        print(f"  ℹ️  Doesn't use MLflow, skipping")
        return False

    # Check if already configured
    if has_tracking_uri_set(content):
        print(f"  ✓ Already configured for remote tracking")
        return False

    # Backup original
    backup_file(filepath)

    # Add comment about environment variable
    updated_content = add_tracking_uri_comment(content)

    if updated_content != content:
        filepath.write_text(updated_content)
        print(f"  ✓ Updated with remote tracking comment")
        return True
    else:
        print(f"  ℹ️  No changes needed")
        return False


def main():
    print("=" * 60)
    print("Update Training Scripts for Remote MLflow Tracking")
    print("=" * 60)
    print()
    print(f"Remote MLflow Server: {MLFLOW_SERVER_URI}")
    print(f"Scripts directory: {SCRIPTS_DIR}")
    print()

    # Check if scripts directory exists
    if not SCRIPTS_DIR.exists():
        print(f"ERROR: Scripts directory not found: {SCRIPTS_DIR}")
        return

    # Update scripts
    updated_count = 0
    for script_path in TRAINING_SCRIPTS:
        full_path = SCRIPTS_DIR / script_path
        if update_script(full_path):
            updated_count += 1

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Scripts updated: {updated_count}")

    if updated_count > 0:
        print()
        print("✓ Training scripts now use MLFLOW_TRACKING_URI environment variable")
        print()
        print(
            "The environment variable is automatically set by setup_remote_tracking.sh"
        )
        print("All training runs will now go to the remote server by default.")
        print()
        print("To verify:")
        print(f"  echo $MLFLOW_TRACKING_URI")
        print(f"  # Should show: {MLFLOW_SERVER_URI}")
    else:
        print()
        print("ℹ️  No updates needed - scripts already configured or don't use MLflow")

    print()
    print(f"Backups saved to: {BACKUP_DIR}")
    print()


if __name__ == "__main__":
    main()
