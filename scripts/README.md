# Scripts Directory

Organized utility scripts for the SHML Platform.

## Directory Structure

```
scripts/
├── deploy/         # ★ Deploy orchestration libraries (sourced by start_all_safe.sh)
│   ├── lib.sh          Core env, colors, logging, timeouts, Tailscale helpers
│   ├── networks.sh     Network constants + ensure_networks()
│   ├── docker.sh       dc_pull/up/stop/down/restart, retry backoff
│   ├── health.sh       wait_for_health/http/middleware (strict/warn)
│   ├── gpu.sh          MPS daemon, VRAM verification
│   ├── backup.sh       Backup discovery, DB restore, pre-restart snapshots
│   ├── stop_all.sh     Stop all services (real target, root wrapper delegates here)
│   ├── stop_dev.sh     Stop dev stack
│   ├── start_all_dev.sh  Start dev/optional stack
│   ├── check_platform_status.sh  Quick health overview
│   └── run_tests.sh    Run test suite
├── auth/           # Authentication & user management
├── backup/         # Backup & restore operations
├── gpu/            # GPU management & monitoring
├── monitoring/     # Metrics, dashboards, resources
├── network/        # Tailscale, funnel, remote access
├── self-healing/   # Native watchdog + autonomous remediation
├── security/       # Security checks and publication boundary tooling
├── setup/          # One-time setup scripts
├── training/       # Training orchestration & outputs
└── webhook/        # Webhook deployment
```

> **Note:** The Platform SDK (FusionAuth admin) has been merged into `libs/client/shml/admin/`.
> Use `from shml.admin import PlatformSDK` instead.

## Deploy Libraries (`deploy/`)

The `deploy/` subdirectory holds the **modular orchestration library** for `start_all_safe.sh`.
Each file is independently sourceable with idempotency guards (`_SHML_*_LOADED`).

```bash
# Source any module individually (e.g. in a one-off script)
source scripts/deploy/lib.sh
source scripts/deploy/docker.sh
dc_up deploy/compose/docker-compose.infra.yml infra 120

# Or use the Taskfile entrypoint for all operations
task restart:inference
```

Root-level scripts (`stop_all.sh`, `check_platform_status.sh`, etc.) are thin wrappers
that `exec` into the real implementations in `scripts/deploy/`. This keeps the repo root clean
while maintaining backwards compatibility for scripts referencing the old paths.

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

### Self-Healing (`self-healing/` + `monitoring/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `watchdog.sh` | Native GPU-aware self-healing watchdog orchestrated via agent-service | `./self-healing/watchdog.sh` |
| `watchdog_admin.py` | Watchdog operations dashboard/API | `python ./self-healing/watchdog_admin.py` |
| `autonomous_service_guard.sh` | 5-minute resource-aware remediation + config drift restarts | `./monitoring/autonomous_service_guard.sh remediate` |
| `install_guard_timer.sh` | Install user-level systemd timer for always-on autonomous guard remediation | `./monitoring/install_guard_timer.sh` |

Environment tuning for `autonomous_service_guard.sh`:
- `MIN_MEM_MB` (default: `2048`)
- `MIN_BUILD_MEM_MB` (default: `3072`)
- `TRAINING_GPU` (default: `0`)
- `TRAINING_SENSITIVE_SERVICES` (default: `ray-head,ray-compute-api,mlflow-server,postgres,redis,inference-gateway`)
- `CONFIG_WATCH_MAP` (default includes infra + MLflow compose mappings)

### Setup (`setup/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `setup_google_idp.sh` | Configure Google OAuth | `./setup_google_idp.sh` |
| `migrate_sfml_to_shml.sh` | Migration script | `./migrate_sfml_to_shml.sh` |
| `init_mlflow.py` | Initialize MLflow | `python init_mlflow.py` |

### Security (`security/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `validate_security.sh` | Runtime hardening validation checks | `./validate_security.sh` |
| `export_public_mirror.sh` | Build sanitized public mirror using allowlist/denylist policy | `bash scripts/security/export_public_mirror.sh --output .public-mirror` |
| `sync_infisical_to_gitlab_vars.sh` | Path A: sync selected Infisical secrets to GitLab masked/protected CI variables | `bash scripts/security/sync_infisical_to_gitlab_vars.sh` |
| `render_infisical_secret_files.sh` | Path A: render selected Infisical secrets into local `secrets/*.txt` files | `bash scripts/security/render_infisical_secret_files.sh` |

### Training (`training/`)

| Script | Purpose | Usage |
|--------|---------|-------|
| `training_orchestrator.py` | Training job management | `python training_orchestrator.py` |
| `check_training_outputs.sh` | Check training results | `./check_training_outputs.sh` |
| `run_phase10_safe.sh` | Sync phase10 + `gpu_yield` into `ray-head` before execution (persistent fix for missing module) | `./run_phase10_safe.sh --dry-run` |

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
