---
title: "Platform Context"
domain: platform
applies-to: "**"
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
