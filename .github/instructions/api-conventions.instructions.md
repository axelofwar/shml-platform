---
description: "Use when writing FastAPI handlers, docker-compose service definitions, Traefik routing labels, or OpenAI-compatible inference APIs. Covers Traefik priority 2147483647, Ray memory formula, and OAuth2-Proxy header trust."
applyTo: "**/*.py,**/*.yml,**/docker-compose*,**/traefik*"
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
