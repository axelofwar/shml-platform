# Docker Compose Organization

The SHML Platform uses multiple Docker Compose files, each managing a logical group of services.

---

## Compose Files

| File | Services | Purpose |
|------|----------|---------|
| `docker-compose.yml` | *(empty — documentation only)* | Documents available compose files and usage |
| `docker-compose.infra.yml` | Traefik, Postgres, Redis, FusionAuth, OAuth2-Proxy, Grafana, Prometheus, Homer, Dozzle, cAdvisor, Node Exporter, Nessie, FiftyOne, Code Server, Webhook Deployer, Postgres Backup, SBA Portal | Core infrastructure and shared services |
| `docker-compose.logging.yml` | Loki, Promtail | Centralized log aggregation |
| `docker-compose.tracing.yml` | Tempo, OTEL Collector | Distributed tracing |
| `docker-compose.secrets.yml` | Infisical, Infisical Postgres, Infisical Redis | Secrets management |
| `docker-compose.dev.yml` | Dev Redis, Dev Postgres, Dev Test Runner | Development/testing environment |
| `mlflow-server/docker-compose.yml` | MLflow Server, MLflow Nginx, MLflow API, MLflow Prometheus | Experiment tracking stack |
| `ray_compute/docker-compose.yml` | Ray Head, Ray Compute API, Ray UI, Ray Prometheus | Distributed GPU compute |
| `inference/coding-model/docker-compose.yml` | Coding model containers | LLM inference |
| `inference/chat-api/docker-compose.yml` | Chat API | Chat interface backend |
| `chat-ui-v2/docker-compose.yml` | Chat UI | Chat web frontend |

---

## Why `docker compose up` Doesn't Work

!!! danger "Do NOT run `docker compose up` directly"
    The main `docker-compose.yml` is intentionally empty. Running `docker compose up` from the project root will **not** start any services.

**Root cause:** Docker Compose's `include:` directive conflicts with network definitions. When included files define `networks: platform: external: true`, it conflicts with the parent's network definition — even when they refer to the same network.

**Additional reasons:**

1. **Startup order matters.** Services have hard dependencies (e.g., OAuth2-Proxy needs FusionAuth, which needs PostgreSQL). Docker Compose `depends_on` only waits for container start, not health.
2. **Network must pre-exist.** Sub-compose files declare the network as `external: true`, so it must be created before they start.
3. **NVIDIA MPS conflicts.** The host's MPS daemon must be stopped before Ray containers can access GPUs.
4. **Middleware registration.** Protected services return `500` errors if Traefik's `oauth2-auth@docker` middleware isn't registered yet.

---

## Startup Order (start_all_safe.sh)

The `start_all_safe.sh` script is the **only supported entry point** for managing services. It handles:

```
Phase 1: Network creation (shml-platform bridge network)
Phase 2: Infrastructure (Traefik, Postgres, Redis)
Phase 3: Auth (FusionAuth → wait healthy → OAuth2-Proxy)
Phase 4: Tailscale Funnel (HTTPS routing)
Phase 5: MLflow stack
Phase 6: Ray compute stack (stops NVIDIA MPS first)
Phase 7: Inference services (if GPUs available)
Phase 8: Monitoring verification
```

Each phase **waits for health checks** before proceeding to the next.

---

## Usage

```bash
# Full restart (recommended)
./start_all_safe.sh

# Start specific service group
./start_all_safe.sh start infra
./start_all_safe.sh start auth
./start_all_safe.sh start mlflow
./start_all_safe.sh start ray
./start_all_safe.sh start inference

# Stop everything
./start_all_safe.sh stop

# Check status
./start_all_safe.sh status

# Diagnose auth middleware
./start_all_safe.sh diagnose
```

---

## Shared Resources

All compose files share:

- **Network:** `shml-platform` (`172.30.0.0/16`, bridge driver)
- **Env file:** `.env` (loaded via `--env-file .env`)
- **Secrets:** `secrets/` directory (Docker secrets for passwords)
- **Config:** `config/platform.env` (non-sensitive service discovery)

!!! tip "Adding a New Service"
    1. Add it to the appropriate compose file (or create a new one).
    2. Use `networks: platform: external: true` if not in `docker-compose.infra.yml`.
    3. Add Traefik labels for routing.
    4. Add a startup phase to `start_all_safe.sh`.
    5. Add the service to the [Service Inventory](services.md).
