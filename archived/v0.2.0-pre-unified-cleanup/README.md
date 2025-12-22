# Archived Code - v0.2.0 Pre-Unified Cleanup

**Date Archived:** December 11, 2025
**Archived By:** Code cleanup audit

## Reason for Archival

This folder contains code that was deprecated during the modularization and unification of the SHML platform. These files have been superseded by newer, more comprehensive implementations.

## Contents

### ray_compute/jobs/
| File | Reason | Superseded By |
|------|--------|---------------|
| `sota_training_job.py` | Pre-modularization training script (1089 lines). All features integrated into unified training script. | `face_detection_training.py` (4397 lines) |

### ray_compute/pipelines/
| File | Reason |
|------|--------|
| `auto_retraining_pipeline.py` | Uses deprecated `ray_compute.jobs.training` API that no longer exists |
| `yolo_training.py` | Uses deprecated `ray_compute.jobs.training` API |
| `yolo_inference.py` | Uses deprecated `ray_compute.jobs.inference` API |
| `dataset_curation.py` | Uses deprecated `ray_compute.pipelines.curation` API |

### ray_compute/examples/
| File | Reason |
|------|--------|
| `test_full_training.py` | Example code using old APIs |
| `training_script.py` | Support file for examples |
| `test_simple_gpu.py` | Broken test (missing import) |

### Config Backups
| File | Reason |
|------|--------|
| `container-metrics.json.bak` | Grafana dashboard backup - original retained in active dir |

## What Was Deleted (Not Archived)

These files were completely removed as they were redundant:

| File | Reason |
|------|--------|
| `ray_compute/jobs/submit_evaluation_job.py` | Thin wrapper with redundant functionality |
| `ray_compute/jobs/utils/training_metrics.py` | Duplicate of `ray_compute/jobs/training_metrics.py` |
| `ray_compute/jobs/=0.19.0` | Artifact file from pip install |
| `wget-log`, `setup.log`, `startup.log` | Log files at project root |
| `docs/remote/` | Empty directory |

## Files Reorganized (Not Deleted)

| Original Location | New Location | Reason |
|------------------|--------------|--------|
| `yolov8l.pt` (87MB) | `data/models/yolov8l.pt` | Model files belong in data directory |
| `test-agent.html` | `tests/html/test-agent.html` | Test files belong in tests directory |

## Security Fixes Applied

| File | Fix |
|------|-----|
| `scripts/training_orchestrator.py` | Removed hardcoded credentials (client_secret, password). Now requires env vars. |

## Script Consolidations (14 → 4 scripts)

The following scripts were consolidated into unified tools with subcommands:

### scripts/backup.sh (NEW - replaces 5 scripts)
| Archived Script | New Command |
|-----------------|-------------|
| `backup_databases.sh` | `./scripts/backup.sh db backup` |
| `restore_databases.sh` | `./scripts/backup.sh db restore <ts>` |
| `backup_platform.sh` | `./scripts/backup.sh platform backup` |
| `restore_platform.sh` | `./scripts/backup.sh platform restore <ts>` |
| `setup_daily_backup.sh` | `./scripts/backup.sh cron setup` |

### scripts/user-management.sh (NEW - replaces 3 scripts)
| Archived Script | New Command |
|-----------------|-------------|
| `verify_user_email.sh` | `./scripts/user-management.sh verify <email>` |
| `verify_all_registrations.sh` | `./scripts/user-management.sh verify-all` |
| `user_verification_report.sh` | `./scripts/user-management.sh report` |

### scripts/container-metrics.sh (NEW - replaces 3 scripts)
| Archived Script | New Command |
|-----------------|-------------|
| `generate_container_mapping.sh` | `./scripts/container-metrics.sh mapping` |
| `generate_container_name_metrics.sh` | `./scripts/container-metrics.sh metrics` |
| `update_container_dashboard.sh` | `./scripts/container-metrics.sh dashboard` |

### scripts/auth-test.sh (NEW - replaces 3 scripts)
| Archived Script | New Command |
|-----------------|-------------|
| `test-oauth2-roles.sh` | `./scripts/auth-test.sh oauth2` |
| `test-role-auth.sh` | `./scripts/auth-test.sh roles` |
| `debug_auth_flow.sh` | `./scripts/auth-test.sh debug` |

## Current Active Files

After cleanup, these are the active production files in `ray_compute/jobs/`:

| File | Purpose | Lines |
|------|---------|-------|
| `face_detection_training.py` | **Primary training script** - All SOTA techniques, curriculum learning, failure analysis | 4397 |
| `submit_face_detection_job.py` | Job submission wrapper for Ray | 775 |
| `evaluate_face_detection.py` | Comprehensive WIDER Face evaluation with MLflow | 851 |
| `evaluate_wider_face.py` | Model comparison (curriculum vs baseline) | 733 |
| `simple_eval.py` | Lightweight quick evaluation | 209 |
| `training_metrics.py` | Prometheus metrics for training | 534 |
| `test_cuda.py` | CUDA availability check | 22 |
| `test_threshold_comparison.py` | Hyperparameter tuning utility | 109 |
| `validate_yolov8l_face.py` | Baseline model validation | 129 |

## Restoration

If you need to restore any of these files:

```bash
# Restore a specific script
cp archived/v0.2.0-pre-unified-cleanup/scripts/backup_databases.sh scripts/

# Restore a ray_compute file
cp archived/v0.2.0-pre-unified-cleanup/ray_compute/jobs/sota_training_job.py ray_compute/jobs/

# Restore entire pipelines folder
cp -r archived/v0.2.0-pre-unified-cleanup/ray_compute/pipelines ray_compute/
```

## Related Documentation

- See `CHANGELOG.md` for cleanup entry
- See `docs/PLATFORM_IMPROVEMENTS_PROJECT_BOARD.md` for current status
