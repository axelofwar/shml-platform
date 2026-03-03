# Scripts Directory

Organized utility scripts for the SHML Platform.

## Directory Structure

```
scripts/
├── auth/           # Authentication & user management
├── backup/         # Backup & restore operations
├── gpu/            # GPU management & monitoring
├── monitoring/     # Metrics, dashboards, resources
├── network/        # Tailscale, funnel, remote access
├── openclaw/       # OpenClaw governance and control utilities
├── setup/          # One-time setup scripts
├── training/       # Training orchestration & outputs
└── webhook/        # Webhook deployment
```

> **Note:** The Platform SDK (FusionAuth admin) has been merged into `libs/client/shml/admin/`.
> Use `from shml.admin import PlatformSDK` instead.

## Quick Reference

### Auth (`auth/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `auth-test.sh` | Test authentication flows | `./auth-test.sh oauth2 [email]` |
| `user-management.sh` | FusionAuth user operations | `./user-management.sh verify <email>` |
| `add-elevated-developer-role.sh` | Add developer role | `./add-elevated-developer-role.sh` |
| `create-elevated-developer-key.sh` | Create API keys | `./create-elevated-developer-key.sh` |
| `apply-session-config.sh` | Apply session settings | `./apply-session-config.sh` |
| `export_mlflow_oauth_env.sh` | Generate short-lived OAuth env exports for Traefik-protected MLflow (`MLFLOW_TRACKING_URI` + `MLFLOW_TRACKING_TOKEN`) | `./export_mlflow_oauth_env.sh` |

### Backup (`backup/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `backup.sh` | Unified backup/restore | `./backup.sh db backup` |

**Subcommands:**
- `db backup|restore|list` - Database operations
- `platform backup|restore|list` - Full platform backup
- `cron setup|remove` - Automated daily backups

### GPU (`gpu/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `gpu-manager.sh` | GPU allocation management | `./gpu-manager.sh status` |
| `setup-gpu-sharing.sh` | Configure GPU sharing | `./setup-gpu-sharing.sh` |
| `verify_gpu_monitoring.sh` | Check GPU metrics | `./verify_gpu_monitoring.sh` |

### Monitoring (`monitoring/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `container-metrics.sh` | Container Prometheus metrics | `./container-metrics.sh all` |
| `metrics_exporter.sh` | Export platform metrics | `./metrics_exporter.sh` |
| `monitor_resources.sh` | Real-time resource monitoring | `./monitor_resources.sh` |
| `detect_resources.sh` | Detect system resources | `./detect_resources.sh` |
| `autonomous_service_guard.sh` | Resource-aware health check + self-remediation | `./autonomous_service_guard.sh remediate` |
| `resource_manager.py` | Python resource management | `python resource_manager.py` |

### Network (`network/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `manage_funnel.sh` | Tailscale Funnel management | `./manage_funnel.sh start` |
| `recover-tailscale.sh` | Tailscale recovery | `./recover-tailscale.sh` |

### OpenClaw (`openclaw/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `openclaw_governor.sh` | Budget/cancel/override governance for OpenClaw | `./openclaw/openclaw_governor.sh status` |
| `openclaw_autonomous_manager.sh` | 5-minute health remediation + model routing (local Nemotron first, Copilot fallback) | `./openclaw/openclaw_autonomous_manager.sh` |
| `install_autonomous_manager_timer.sh` | Install user-level systemd timer for always-on autonomous manager | `./openclaw/install_autonomous_manager_timer.sh` |

Environment tuning for `openclaw_autonomous_manager.sh`:
- `CONSECUTIVE_DEGRADE_THRESHOLD` (default: `2`)
- `MAX_NEMOTRON_HEALTH_LATENCY_MS` (default: `2500`)
- `NEMOTRON_HEALTH_TIMEOUT_SECONDS` (default: `8`)

### Setup (`setup/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `setup_google_idp.sh` | Configure Google OAuth | `./setup_google_idp.sh` |
| `migrate_sfml_to_shml.sh` | Migration script | `./migrate_sfml_to_shml.sh` |
| `init_mlflow.py` | Initialize MLflow | `python init_mlflow.py` |

### Training (`training/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `training_orchestrator.py` | Training job management | `python training_orchestrator.py` |
| `check_training_outputs.sh` | Check training results | `./check_training_outputs.sh` |

### Webhook (`webhook/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `deploy.sh` | Deploy webhook service | `./deploy.sh` |

## Consolidated Scripts

The following scripts were consolidated in v0.2.0:

| New Script | Replaces | Location |
|------------|----------|----------|
| `backup.sh` | 5 scripts | `backup/` |
| `user-management.sh` | 3 scripts | `auth/` |
| `container-metrics.sh` | 3 scripts | `monitoring/` |
| `auth-test.sh` | 3 scripts | `auth/` |
| `platform_sdk` | 19 files | `libs/client/shml/admin/` |

Original scripts archived in `archived/v0.2.0-pre-unified-cleanup/scripts/`.

## Running Scripts

All scripts should be run from the repository root:

```bash
# From repo root
./scripts/auth/auth-test.sh --help
./scripts/backup/backup.sh db backup
./scripts/gpu/gpu-manager.sh status

# Or cd into scripts first
cd scripts
./auth/auth-test.sh --help
```

## Adding New Scripts

1. Place in appropriate subdirectory
2. Follow naming convention: `lowercase-with-dashes.sh`
3. Add help text with `--help` flag
4. Make executable: `chmod +x script.sh`
5. Update this README

---

**Last Updated:** 2025-12-11
**Scripts Count:** 18 shell/python scripts
