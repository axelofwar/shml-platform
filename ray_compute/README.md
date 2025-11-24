# Ray Compute Platform

**Status:** ⏸️ Infrastructure Ready, App Development Pending  
OAuth-enabled GPU platform with Ray 2.9.0-gpu, FastAPI, Authentik, Next.js Web UI

---

## Quick Start

**Note:** Services not yet deployed. Infrastructure & Web UI ready.

### Prerequisites

```bash
# Docker 24.0+, Compose 2.20+
docker --version
docker compose version

# NVIDIA GPU drivers
nvidia-smi

# Join ml-platform network
docker network inspect ml-platform
```

### When Deployed

```bash
cd ray_compute

# Start all
../start_all.sh  # Or stack-specific: ./start.sh

# Access
# Dashboard: http://localhost/ray/
# API: http://localhost/api/compute/
# Web UI: http://localhost/ray-ui/
```

---

## What's Included

**Services (Infrastructure Ready):**
- Ray 2.9.0-gpu head node (NVIDIA MPS fractional GPU sharing)
- FastAPI API server (auth, scheduler, queue, notifications)
- PostgreSQL 15 (8 tables: users, jobs, quotas, artifacts, audit)
- Authentik OAuth (3 user tiers: admin, premium, user)
- Next.js Web UI (production-ready, not deployed)
- Grafana + Prometheus + Loki (monitoring stack)
- Redis (shared cache, DB 1)

**Network:**
- Traefik gateway on port 80/8090
- Path routing: /ray/*, /api/compute/*, /ray-ui/*
- Shared: ml-platform network with MLflow

**GPU:**
- NVIDIA MPS enabled (fractional allocation)
- Per-user quotas (admin: unlimited, premium: full, user: 0.5 max)

---

## MLflow Integration

**Internal (Ray → MLflow):**

```python
import mlflow

# Use Docker DNS
mlflow.set_tracking_uri("http://mlflow-nginx:80")

@ray.remote
def train_model(data):
    with mlflow.start_run():
        model = train(data)
        mlflow.log_metric("accuracy", 0.95)
    return model
```

**External (Client → MLflow):**

```python
# Use LAN/VPN IP
mlflow.set_tracking_uri("http://localhost/mlflow/")
```

**Full Guide:** [/Projects/INTEGRATION_GUIDE.md](/Projects/INTEGRATION_GUIDE.md)

**Default Credentials** (change immediately!):
- Username: `admin`
- Password: `admin`

---

## 📖 Documentation

### User Guides
- **[Operations Guide](docs/OPERATIONS.md)** - Start/stop services, troubleshooting, daily operations
---

## OAuth Setup

**Authentik Configuration:**
- Client ID: ray-compute-api
- User Groups: admins (unlimited), premium (10 jobs, full GPU), users (3 jobs, 0.5 GPU)
- Redirect URIs: http://${TAILSCALE_IP}:3002/api/auth/callback/authentik

**Environment (.env):**
```bash
AUTHENTIK_CLIENT_ID=ray-compute-api
AUTHENTIK_CLIENT_SECRET=<secret>
NEXTAUTH_SECRET=<secret>
NEXTAUTH_URL=http://${TAILSCALE_IP}:3002
NEXT_PUBLIC_API_URL=http://${TAILSCALE_IP}:8000
```

**Full Guide:** docs/OAUTH_SETUP_GUIDE.md

---

## Access (When Deployed)

### Local (on server)

```bash
curl http://localhost/ray/
curl http://localhost/api/compute/health
```

### LAN (${SERVER_IP})

```bash
curl http://localhost/ray/
curl http://localhost/api/compute/health
```

### VPN (Tailscale: ${TAILSCALE_IP})

```bash
curl http://${TAILSCALE_IP}/ray/
curl http://${TAILSCALE_IP}/api/compute/health
```

---

## Management

### Service Control

```bash
# Status
docker compose -f docker-compose.ray.yml ps

# Logs
docker logs ray-head --tail 50
docker logs ray-compute-api --tail 50

# Restart
docker compose -f docker-compose.ray.yml restart
```

### Database

```bash
# CLI access
PGPASSWORD=$POSTGRES_PASSWORD psql -h localhost -p 5433 -U ray_compute -d ray_compute

# Check tables
psql -h localhost -p 5433 -U ray_compute -d ray_compute -c '\dt'

# Query jobs
psql -h localhost -p 5433 -U ray_compute -d ray_compute -c 'SELECT * FROM jobs LIMIT 10;'
```

### GPU Monitoring

```bash
# Check GPU
nvidia-smi

# Check MPS
nvidia-cuda-mps-control -d

# Container GPU access
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi
```

---

## Troubleshooting

### Ray Services Won't Start

```bash
# Check network
docker network inspect ml-platform

# Check GPU
nvidia-smi
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi

# Install nvidia-container-toolkit if needed
sudo apt install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### OAuth Login Failed

```bash
# Check Authentik
docker logs authentik-server --tail 50

# Verify redirect URIs
docker exec authentik-postgres psql -U authentik -d authentik \
  -c "SELECT _redirect_uris FROM authentik_providers_oauth2_oauth2provider WHERE client_id='ray-compute-api';"

# Restart
docker restart authentik-server ray-compute-ui
```

### API 500 Errors

```bash
# Check logs
docker logs ray-compute-api --tail 100

# Check Ray connection
docker exec ray-compute-api curl http://ray-head:8265/api/version

# Check MLflow connection
docker exec ray-compute-api curl http://mlflow-nginx:80/health
```

**Full Guide:** [/Projects/TROUBLESHOOTING.md](/Projects/TROUBLESHOOTING.md)

---

## Testing (Web UI)

### Unit Tests

```bash
cd web_ui
npm test
```

### E2E Tests

```bash
npm run test:e2e
```

### Coverage

```bash
npm run test:ci --coverage
```

---

## Documentation

**Core Docs:**
- [/Projects/ARCHITECTURE.md](/Projects/ARCHITECTURE.md) - Tool decisions, GPU sharing (NVIDIA MPS)
- [/Projects/API_REFERENCE.md](/Projects/API_REFERENCE.md) - Ray Jobs API + Ray Compute API specs
- [/Projects/INTEGRATION_GUIDE.md](/Projects/INTEGRATION_GUIDE.md) - MLflow+Ray integration
- [/Projects/CURRENT_DEPLOYMENT.md](/Projects/CURRENT_DEPLOYMENT.md) - Deployment status
- [/Projects/TROUBLESHOOTING.md](/Projects/TROUBLESHOOTING.md) - Common issues

**Ray Docs:**
- docs/OAUTH_SETUP_GUIDE.md - Authentik configuration
- LESSONS_LEARNED.md - Debugging insights (OAuth, React, Tailwind)
- CONTRIBUTING.md - Development guidelines
- INFRASTRUCTURE_STATUS.md - Service topology
- REPOSITORY_STATUS.md - Testing & CI/CD

---

## Development (Web UI)

### Local Setup

```bash
cd web_ui
npm install
npm run dev
# Visit: http://localhost:3000
```

### Environment (.env.local)

```bash
NEXTAUTH_URL=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_AUTHENTIK_URL=http://localhost:9000
AUTHENTIK_CLIENT_ID=ray-compute-api
AUTHENTIK_CLIENT_SECRET=<secret>
NEXTAUTH_SECRET=<secret>
```

---

## Pending Development

**API Server:**
- [ ] auth.py - OAuth middleware, session management
- [ ] scheduler.py - Fractional GPU bin-packing
- [ ] queue.py - Redis priority queue
- [ ] notifications.py - Apprise alerts

**Ray Cluster:**
- [ ] Deploy Ray head node
- [ ] Configure NVIDIA MPS
- [ ] Job submission endpoint
- [ ] Resource monitoring

**Web UI:**
- [ ] Login page (OAuth button)
- [ ] Job submission form
- [ ] Job details page (logs, artifacts)
- [ ] Real-time updates (WebSocket/polling)

---

## Status

**Version:** Ray 2.9.0-gpu  
**Database:** PostgreSQL 15 (schema ready)  
**Network:** ml-platform (shared with MLflow)  
**Gateway:** Traefik v2.10  
**OAuth:** Authentik (infrastructure ready)  
**Web UI:** Next.js 14 (production-ready, not deployed)  
**Deployment:** ⏸️ Infrastructure Ready, App Development Pending  
**Last Updated:** 2025-11-22

**See:** [/Projects/CURRENT_DEPLOYMENT.md](/Projects/CURRENT_DEPLOYMENT.md) for full status
1. Verify `NEXTAUTH_URL` matches your public URL
2. Check Authentik redirect URI: `http://YOUR_IP:3002/api/auth/callback/authentik`
3. Ensure `issuer` and `jwks_endpoint` are configured
4. Check Docker networking (internal vs public URLs)

See [OAuth Setup Guide](docs/OAUTH_SETUP_GUIDE.md) for details.

### Styles Not Loading

**Symptom**: Dashboard looks unstyled

**Solution**:
1. Verify `postcss.config.js` exists
