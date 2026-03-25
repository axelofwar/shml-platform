---
title: "Service Management"
domain: infrastructure
applies-to: "**/*.yml,**/*.sh,**/docker-compose*,Taskfile.yml"
---

# 🚨 CRITICAL: ALWAYS USE start_all_safe.sh FOR SERVICE MANAGEMENT

## ✅ MANDATORY: Use start_all_safe.sh for ALL service restarts

**ALWAYS use the start_all_safe.sh script:**
```bash
# Restart specific service stack
./start_all_safe.sh restart ray       # Restart Ray services only
./start_all_safe.sh restart mlflow    # Restart MLflow services only
./start_all_safe.sh restart infra     # Restart infrastructure only
./start_all_safe.sh restart inference # Restart inference services only

# Start specific service stack
./start_all_safe.sh start ray
./start_all_safe.sh start mlflow

# Stop specific service stack
./start_all_safe.sh stop ray
./start_all_safe.sh stop mlflow

# Check platform status
./start_all_safe.sh status
```

**WHY use start_all_safe.sh:**
- ✅ Handles database migrations automatically
- ✅ Ensures proper startup order (dependencies)
- ✅ Cleans up orphaned containers
- ✅ Validates service health before proceeding
- ✅ Prevents race conditions and corruption
- ✅ Provides clear status feedback

## ❌ NEVER use these commands directly:
```bash
# ❌ WRONG - skips migrations, wrong order, orphaned containers
docker-compose -f ray_compute/docker-compose.yml restart ray-compute-ui
docker compose up -d --build ray-compute-ui
docker-compose down

# ❌ WRONG - kills ALL services including active jobs
./stop_all.sh  # Only use if explicitly requested by user
```

**CRITICAL:** Restarting services without start_all_safe.sh kills:
- Active Ray training jobs (hours of GPU compute lost)
- MLflow logging connections (corrupts experiment tracking)
- Loaded inference models (RTX 2070/3090 VRAM states)
- WebSocket sessions and active workflows
- Database migrations are skipped (data corruption risk)

## ✅ Preferred: use `task` for day-to-day operations

```bash
# Install Task once: brew install go-task
task                           # Show platform status
task start                     # Start all services
task start:inference           # Start inference stack only
task restart:ray               # Restart Ray compute stack
task restart:mlflow            # Restart MLflow stack
task restart:infra             # Restart Traefik/OAuth/FusionAuth
task restart:inference         # Restart inference services
task stop                      # Stop all services
task status                    # Detailed health status
task gpu                       # GPU VRAM + utilization
task logs -- <service>         # Follow service logs
task systemd:install           # Install systemd unit files
```

## Read-only operations (always safe)

```bash
./start_all_safe.sh status
./check_platform_status.sh
docker logs mlflow-server -f
docker logs ray-compute-api -f
docker logs oauth2-proxy -f
```

## Deploy Library Pattern

Orchestration logic is in 6 modular, guard-gated bash libraries in `scripts/deploy/`:

| Library | Functions |
|---------|-----------|
| `lib.sh` | `load_shml_env`, log helpers, `can_run_privileged`, Tailscale helpers |
| `networks.sh` | `ensure_networks()`, `PLATFORM_NETWORK`, `CORE_NETWORK` |
| `docker.sh` | `dc_pull/up/stop/down/restart`, `cleanup_compose_conflicts` |
| `health.sh` | `wait_for_health`, `wait_for_http`, `wait_for_middleware` |
| `gpu.sh` | `check_mps_status`, `stop_mps_daemon`, `verify_gpu_access` |
| `backup.sh` | `find_best_backup`, `restore_database_from_backup`, `create_pre_restart_backup` |

Each module uses an idempotency guard (`[[ -n "${_SHML_LIB_LOADED:-}" ]] && return 0`) so sourcing from multiple entry-points is safe.

## GPU Resource Management

```bash
# Before training on RTX 3090:
curl -X POST http://localhost/api/image/yield-to-training

# Z-Image auto-unloads after 5min idle
# Z-Image auto-reloads on next request
```

## Service Startup Order (critical pattern)

**Problem:** Race conditions, orphaned containers
**Solution:** Use phased startup with cleanup

```bash
docker-compose down --remove-orphans
# Phase 1: Infrastructure (databases)
# Phase 2: Core services
# Phase 3: API services
# Phase 4: Monitoring
```

## ⚠️ WARNING: Restarting services interrupts

- Active Ray training jobs (hours of GPU time lost)
- MLflow logging connections
- Inference model loading states
- WebSocket connections

**start_all_safe.sh / task ensures:**
- Database migrations run before services start
- Proper dependency ordering (postgres → app → ui)
- Orphaned containers are cleaned up
- Health checks validate services before proceeding
