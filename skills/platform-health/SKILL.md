---
name: platform-health
description: Audit SHML platform health - containers, GPU utilization, critical services, disk, and network. Remediate unhealthy services with safe restarts. Use when checking platform status, debugging service issues, or running pre-deployment checks.
---

# SHML Platform Health Audit

## Overview

Comprehensive health check for the SHML platform stack. Covers Docker containers, GPU status, critical service endpoints, disk usage, and network connectivity between services.

## When to Use

- Pre-deployment verification
- Periodic health monitoring (via heartbeat or cron)
- Debugging service degradation
- After infrastructure changes (compose up/down, GPU driver updates)

## Workflow

### 1) Container Health

```bash
# All containers with health status
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | sort

# Unhealthy containers
docker ps --filter "health=unhealthy" --format '{{.Names}} {{.Status}}'

# Restarting containers (crash loop)
docker ps --filter "status=restarting" --format '{{.Names}} {{.Status}}'

# Recently exited (unexpected crashes)
docker ps -a --filter "status=exited" --format '{{.Names}} {{.Status}}' | head -10
```

### 2) GPU Health

```bash
# GPU utilization and memory
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader

# GPU processes (which containers use which GPU)
nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader
```

### 3) Critical Service Endpoints

Test internal health endpoints for critical services:

```bash
# Inference models
docker exec inference-gateway curl -sf http://localhost:8000/health
docker exec nemotron-coding curl -sf http://localhost:8000/health
docker exec qwen3-vl-api curl -sf http://localhost:8000/health

# Agent service
docker exec shml-agent-service curl -sf http://localhost:8000/health

# Infrastructure
docker exec shml-postgres pg_isready -U postgres
docker exec shml-redis redis-cli ping
```

### 4) Disk & Memory

```bash
# Disk usage (look for >85% as warning)
df -h / /home 2>/dev/null | tail -n +2

# Docker disk usage
docker system df

# System memory
free -h
```

### 5) Network Connectivity

```bash
# Verify key internal DNS resolves (from within Docker network)
docker exec inference-gateway getent hosts shml-postgres nemotron-coding qwen3-vl-api shml-redis
```

## Remediation

When a service is unhealthy:

1. **Check logs first**: `docker logs --tail 50 <container>`
2. **Soft restart**: `docker restart <container>` (preserves volumes)
3. **Hard recreate**: `docker compose up -d --force-recreate <service>` (only if restart fails)
4. **Verify after**: Re-run health endpoint check

### Safety Rules

- Never `docker rm -f` a database container
- Always check `docker logs` before restarting
- Prefer `restart` over `recreate`
- For GPU services, check `nvidia-smi` before and after restart

## Output Format

Report as structured table:

```
| Category      | Check           | Status | Details              |
|---------------|-----------------|--------|----------------------|
| Containers    | All healthy     | ✅/❌  | N healthy, M issues  |
| GPU-0 (3090)  | Memory/Util     | ✅/⚠️  | X/24GB, Y% util      |
| GPU-1 (2070)  | Memory/Util     | ✅/⚠️  | X/8GB, Y% util       |
| Postgres      | Connectivity    | ✅/❌  | Ready/Error          |
| Redis         | Connectivity    | ✅/❌  | PONG/Error           |
| Inference     | Gateway health  | ✅/❌  | Healthy/Error        |
| Disk          | Usage           | ✅/⚠️  | X% used              |
```

## Cron Integration

To schedule periodic health checks:

```
Schedule: every 4 hours
Payload: "Run platform-health skill audit. Report only issues."
Session: isolated
Delivery: announce
```
