# CLAUDE.md — SHML Platform Project Context

<!-- GENERATED FILE — edit sources in .agent/rules/, run scripts/generate-ide-configs.sh to update -->
**Version:** 0.1.0 | **Generated:** 2026-03-22

This file is automatically loaded by Claude Code at session start.

---

## Quick Command Reference

```bash
# Platform management
task status              # Check all services
task restart:ray         # Restart Ray stack
task restart:mlflow      # Restart MLflow stack
task restart:inference   # Restart inference stack
task gpu                 # GPU VRAM status

# Generate IDE configs (after editing .agent/rules/)
scripts/generate-ide-configs.sh --target all
```

## Agent Context

- **Rules:** `.agent/rules/` — 6 focused rule files (service-management, documentation, security, platform, api, code)
- **Skills:** `.claude/skills/` — 13 skills with SKILL.md (same canonical files as agent-service)
- **Commands:** `.claude/commands/` — slash commands (/project:review, /project:audit, etc.)
- **Agents:** `.claude/agents/` — specialized subagents (code-reviewer, security-auditor, training-monitor)

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

---


# 🔒 Security Standards

## ⚠️ CRITICAL: Pre-Commit Hooks (MANDATORY)

This project uses pre-commit hooks with GitGuardian to prevent secret leaks.

```bash
# Install hooks (required for all developers)
pip install pre-commit ggshield
pre-commit install
pre-commit install --hook-type pre-push

# Authenticate ggshield (one-time setup)
ggshield auth login
```

**What gets scanned:**
- Every commit is scanned for secrets before it's created
- Every push is scanned before reaching GitHub
- GitGuardian CI also scans all PRs

**If a secret is detected:**
1. The commit/push will be BLOCKED
2. You'll see which file/line contains the secret
3. Remove the secret and try again
4. Use environment variables or Docker secrets instead

## Secrets Management

**Git-Ignored Files (NEVER commit these):**
- `REMOTE_ACCESS_COMPLETE.sh` — Contains ALL credentials, IPs, passwords
- `mlflow-server/secrets/` — Database passwords
- `ray_compute/.env` — OAuth secrets, API keys
- `*/data/` — Persistent data volumes
- `*/logs/` — Service logs
- `*/backups/` — Database backups
- `*-env.backup` — Environment backups

**Safe to Commit:**
- `.env.example` — Templates with placeholders
- Documentation files
- Source code without secrets
- Configuration templates

## How to Handle Secrets in Code

**❌ NEVER do this:**
```python
# Hardcoded secrets — WILL BE BLOCKED by pre-commit
API_KEY = "sk-1234567890abcdef"
PASSWORD = "AiSolutions2350!"
SECRET_KEY = os.getenv("SECRET_KEY", "default_secret")  # Bad default!
```

**✅ ALWAYS do this:**
```python
# Load from environment — no fallback for secrets
API_KEY = os.environ["API_KEY"]  # Fails loudly if not set
PASSWORD = os.getenv("PASSWORD")
if not PASSWORD:
    raise ValueError("PASSWORD environment variable required")

# Or use Docker secrets
def load_secret(name: str) -> str:
    secret_path = f"/run/secrets/{name}"
    if os.path.exists(secret_path):
        with open(secret_path) as f:
            return f.read().strip()
    value = os.environ.get(name.upper())
    if not value:
        raise ValueError(f"Secret {name} not found in /run/secrets/ or environment")
    return value
```

## Placeholder Patterns

**Never in committed files:**
```
❌ PASSWORD=AiSolutions2350!
❌ TAILSCALE_IP=100.x.x.x
❌ DB_HOST=192.168.1.100
❌ client_secret=JsDs6mClPCWKqEq...
```

**Always use:**
```
✅ PASSWORD=${DB_PASSWORD}
✅ TAILSCALE_IP=${TAILSCALE_IP}
✅ DB_HOST=<your-server-ip>
✅ client_secret=<from-authentik-dashboard>
```

## Security Scanning Tools

| Tool | When | What |
|------|------|------|
| **ggshield** | Pre-commit, pre-push | Blocks secrets before commit |
| **Gitleaks** | Pre-commit, CI | Additional secret patterns |
| **GitGuardian** | GitHub CI | Scans all PRs and pushes |
| **Trivy** | CI | Container vulnerabilities |
| **pip-audit** | CI | Python dependency CVEs |

## OWASP Top 10 Checklist

When writing code, verify:
- [ ] No hardcoded credentials or secrets
- [ ] Input validation at all system boundaries (user input, external APIs)
- [ ] No SQL injection (use parameterized queries)
- [ ] No XSS (escape output; use framework escaping)
- [ ] No command injection (avoid shell=True; use subprocess list form)
- [ ] Authentication checked before data access
- [ ] No path traversal (validate/sanitize file paths)
- [ ] Dependencies up to date (pip-audit, trivy)
- [ ] Errors don't leak sensitive info to users
- [ ] SSRF prevention: validate URLs before outbound requests

## Input Validation Pattern

```python
# External boundary validation (user input, external APIs, webhooks)
from pathlib import Path

def safe_path(base_dir: str, user_input: str) -> Path:
    """Prevent path traversal attacks."""
    base = Path(base_dir).resolve()
    target = (base / user_input).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError(f"Path traversal attempt: {user_input}")
    return target
```

---


# 🎯 API Conventions & Critical Patterns

## 1. Traefik Router Priority (CRITICAL)

**Problem:** Traefik's internal API intercepts `/api/*` requests before app routes.
**Solution:** Application routers MUST use priority `2147483647` (max int32).

```yaml
labels:
  - traefik.http.routers.my-api.rule=PathPrefix(`/api/v1`)
  - traefik.http.routers.my-api.priority=2147483647  # CRITICAL — never omit
```

## 2. Ray Memory Allocation Formula

**Problem:** Ray head crashes with OOM errors.
**Solution:** Always satisfy this formula before deploying Ray:

```
container_memory ≥ object_store_memory + shm_size + 1GB
```

Example:
```yaml
deploy:
  resources:
    limits:
      memory: 32g
shm_size: '8gb'
environment:
  - RAY_OBJECT_STORE_MEMORY=8000000000  # 8GB — must fit within (32-8-1)=23GB
```

## 3. Docker Networking Fix (Ubuntu apt docker.io)

**Problem:** Containers can't communicate after Docker reinstall via `apt install docker.io`.
**Solution:** Disable bridge netfilter (Ubuntu behavior differs from Docker CE).

```bash
sudo sysctl -w net.bridge.bridge-nf-call-iptables=0
sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=0
# Make persistent:
echo 'net.bridge.bridge-nf-call-iptables=0' | sudo tee -a /etc/sysctl.conf
echo 'net.bridge.bridge-nf-call-ip6tables=0' | sudo tee -a /etc/sysctl.conf
```

## 4. OAuth2-Proxy Auth Header Trust (CRITICAL for APIs)

**Problem:** Backend APIs return 401/403 even after user authenticates via OAuth2-Proxy.
**Root Cause:** OAuth2-Proxy sets headers (`X-Auth-Request-Email`, etc.) but backend APIs don't trust them.
**Solution:** Configure backend APIs to read OAuth2-Proxy forwarded headers.

```bash
# In .env:
PROXY_AUTH_ENABLED=true
PROXY_AUTH_HEADER=X-Auth-Request-Email
PROXY_AUTH_USER_HEADER=X-Auth-Request-User
PROXY_AUTH_GROUPS_HEADER=X-Auth-Request-Groups
```

```python
# In FastAPI — extract user from proxy headers:
async def get_current_user_from_proxy(request: Request) -> Optional[dict]:
    if os.getenv("PROXY_AUTH_ENABLED", "false").lower() != "true":
        return None
    email = request.headers.get("X-Auth-Request-Email")
    if email:
        return {"email": email, "user": email.split("@")[0]}
    return None
```

**Auth Pattern Reference by Service:**

| Service | Auth Type | Configuration |
|---------|-----------|---------------|
| MLflow UI | No backend auth | N/A |
| Grafana | Native proxy auth | `GF_AUTH_PROXY_ENABLED=true` |
| Ray UI/API | Custom proxy auth | `PROXY_AUTH_ENABLED=true` |
| Homer | No backend auth | N/A |
| Custom FastAPI | Custom proxy auth | Implement header extraction |

## 5. FastAPI Conventions

```python
# Async handlers (always)
@router.get("/resource/{id}")
async def get_resource(id: str) -> ResourceResponse:
    ...

# Type annotations (always)
from pydantic import BaseModel
from typing import Optional, List

class ResourceResponse(BaseModel):
    id: str
    status: str
    metadata: Optional[dict] = None

# Error handling for external calls
try:
    result = await external_service.call()
except httpx.TimeoutException:
    raise HTTPException(status_code=504, detail="Upstream timeout")
except httpx.ConnectError:
    raise HTTPException(status_code=503, detail="Service unavailable")
```

## 6. Docker Compose Service Conventions

```yaml
services:
  my-service:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    networks:
      - ml-platform          # Always attach to shared network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    labels:
      - traefik.enable=true
      - traefik.http.routers.my-service.rule=PathPrefix(`/api/my-service`)
      - traefik.http.routers.my-service.priority=2147483647
```

## 7. Inference API Conventions (OpenAI-compatible)

```python
# All LLM APIs use OpenAI-compatible format:
POST /v1/chat/completions
{
    "model": "model-name",
    "messages": [{"role": "user", "content": "..."}],
    "max_tokens": 2048,
    "temperature": 0.7
}

# Health checks:
GET /health  → {"status": "healthy", "model": "...", "gpu_memory_used": "..."}
```

---


# 🏗️ Platform Context — SHML Platform

## Service Topology

### MLflow Stack (8 services)
- `mlflow-server` — tracking server (`localhost:8080`)
- `mlflow-api` — enhanced API (`localhost:8000`)
- `postgres` — tracking DB
- `redis` — cache
- `nginx` — reverse proxy
- `prometheus` — metrics
- `grafana` — dashboards
- `backup` — automated backups

### Ray Compute Stack (10 services)
- `ray-compute-api` — job submission (`localhost:8000`)
- `ray-compute-ui` — Next.js dashboard (`localhost:3002`)
- `authentik-server` — OAuth (`localhost:9000`)
- `authentik-worker` — background tasks
- `authentik-postgres` — auth DB
- `authentik-redis` — cache
- `ray-prometheus` — metrics
- `ray-grafana` — dashboards
- `ray-loki` — logs
- `ray-promtail` — log shipping

### Traefik Gateway (1 service)
- `traefik` — reverse proxy, load balancer (`:80`, `:8090`)

### Inference Stack (4 services)
- `qwen3-vl-api` — LLM, RTX 2070, INT4 quantized (`/api/llm`)
- `z-image-api` — Image Gen, RTX 3090, on-demand (`/api/image`)
- `inference-gateway` — queue, rate limit, history (`/inference`)
- `inference-postgres` — chat history DB

**Total: 23 containers (19 core + 4 inference)**

## GPU Allocation

| GPU | VRAM | Service | Mode |
|-----|------|---------|------|
| RTX 3090 Ti (cuda:0) | 24GB | Z-Image / Training | On-demand / yields to training |
| RTX 2070 (cuda:1) | 8GB | Qwen3-VL-8B-INT4 | Always loaded |

## Network Architecture

```
ml-platform network (shared Docker bridge)
├── traefik (gateway) - :80, :8090
├── mlflow-server - :8080
├── mlflow-api - :8000
├── ray-compute-api - :8000
├── ray-compute-ui - :3002
├── authentik - :9000
├── qwen3-vl-api - :8000 (via /api/llm)
├── z-image-api - :8000 (via /api/image)
├── inference-gateway - :8000 (via /inference)
└── monitoring services
```

## Key Endpoints

```
# MLflow
http://localhost:8080         # MLflow UI
http://localhost:8000/api/v1  # MLflow API

# Ray
http://localhost:3002         # Ray UI
http://localhost:8000/api/v1  # Ray Compute API

# Inference
/api/llm/v1/chat/completions  # OpenAI-compatible LLM
/api/llm/health               # Qwen3-VL status
/api/image/v1/generate        # Image generation
/api/image/yield-to-training  # Free RTX 3090 for training
/inference/health             # Gateway status
/inference/conversations      # Chat history
/inference/queue/status       # Request queue

# Auth
http://localhost:9000         # Authentik dashboard
```

## Privacy Guarantees

- `TRANSFORMERS_OFFLINE=1` — No outbound model connections
- Models cached locally after one-time download
- Chat history in local PostgreSQL only
- Tailscale VPN required for remote access
- No telemetry, no prompt logging

## Workspace Layout

```
scripts/deploy/     — modular bash deploy libraries
deploy/systemd/     — canonical systemd unit files
.agent/             — agent context (identity, rules)
Taskfile.yml        — primary developer task runner
inference/          — LLM + image gen services
mlflow-server/      — MLflow tracking stack
ray_compute/        — Ray compute stack
monitoring/         — Prometheus, Grafana, Loki, Tempo
fusionauth/         — FusionAuth identity provider
```

## Version Information

| Component | Version |
|-----------|---------|
| Project | 0.1.0 |
| MLflow | 2.17.2 |
| Ray | 2.8.1 |
| Traefik | 2.10 |
| Authentik | 2024.8.6 |
| Docker Compose schema | 3.8 |
| License | MIT (axelofwar, 2025) |

## Remote Access

- Tailscale VPN required for remote access to all services
- `REMOTE_QUICK_REFERENCE.md` — public reference (no credentials)
- `REMOTE_ACCESS_COMPLETE.sh` — complete credentials (git-ignored, local only)

---


# 📝 Code Style Guide

## Python

### Type Annotations (required for all new code)

```python
from __future__ import annotations
from typing import Optional, Union, List, Dict, Any
from pathlib import Path

# Functions — annotate params and return type
def process_job(job_id: str, config: dict[str, Any]) -> JobResult:
    ...

# Classes — use dataclasses or Pydantic
from dataclasses import dataclass, field

@dataclass
class JobConfig:
    job_id: str
    resources: dict[str, int] = field(default_factory=dict)
    timeout_seconds: int = 300
```

### Async/Await

```python
# Use async for all I/O (HTTP, DB, file, subprocess)
import asyncio
import httpx

async def fetch_job_status(job_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

# Never block the event loop:
# ❌ time.sleep(1)
# ✅ await asyncio.sleep(1)
# ❌ requests.get(url)
# ✅ await client.get(url)
```

### Logging

```python
import logging

logger = logging.getLogger(__name__)  # Always use __name__

# Log levels: DEBUG (dev detail), INFO (normal ops), WARNING (degraded), ERROR (failure), CRITICAL (system failure)
logger.info("Job %s started, config=%s", job_id, config)
logger.warning("GPU memory low: %d MB remaining", remaining_mb)
logger.error("Job %s failed: %s", job_id, exc, exc_info=True)

# Never log secrets:
# ❌ logger.info("Auth token: %s", token)
# ✅ logger.info("Auth token present: %s", bool(token))
```

### Error Handling

```python
# Specific exceptions — never bare except
try:
    result = await service.call(payload)
except httpx.TimeoutException as e:
    logger.warning("Service timeout for job %s: %s", job_id, e)
    raise HTTPException(status_code=504, detail="Upstream timeout")
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))
# except Exception as e:  ← Only at top-level handlers

# Use context managers for resources
async with db.transaction():
    await db.execute(query, params)
```

### Import Conventions

```python
# Order: stdlib → third-party → local (separated by blank lines)
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.models import JobConfig
from app.db import get_session
```

### Naming

```python
# snake_case for functions, variables, modules
def get_job_status(job_id: str) -> str: ...
ray_head_url = "http://ray-head:8265"

# PascalCase for classes
class JobSubmissionRequest(BaseModel): ...

# UPPERCASE for constants
MAX_RETRIES = 3
DEFAULT_TIMEOUT_SECONDS = 30

# Prefix private with _
_internal_cache: dict = {}
```

## Shell Scripts

```bash
#!/usr/bin/env bash
set -euo pipefail  # Always: exit on error, undefined var error, pipe failure

# Use [[ ]] not [ ]
if [[ -n "${VAR:-}" ]]; then

# Quote all variables
echo "Processing: ${JOB_ID}"
cp "${source_file}" "${dest_dir}/"

# Use $() not backticks
current_dir=$(pwd)

# Prefer -exec over xargs for file ops
find . -name "*.log" -exec rm {} +
```

## TypeScript / React (chat-ui-v2)

```typescript
// Explicit types — no implicit any
interface JobStatus {
  jobId: string;
  status: 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
  createdAt: string;
  metrics?: Record<string, number>;
}

// Async/await for all promises
async function fetchJob(jobId: string): Promise<JobStatus> {
  const response = await fetch(`/api/v1/jobs/${jobId}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

// React: functional components + hooks
const JobCard: React.FC<{ job: JobStatus }> = ({ job }) => {
  const [expanded, setExpanded] = useState(false);
  return <div>...</div>;
};
```

## Complexity Budget

- Functions: ≤30 lines, single responsibility
- Files: ≤300 lines (split larger files)
- Nesting: ≤3 levels deep (extract early returns, helper functions)
- No "clever" one-liners that obscure intent

## What NOT to add without request

- Don't add docstrings to code you didn't change
- Don't add type annotations to existing untyped functions unless fixing a bug there
- Don't add error handling for impossible scenarios
- Don't create utility helpers for one-time use
- Don't refactor surrounding code when fixing a targeted bug

---


