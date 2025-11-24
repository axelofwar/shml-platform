# ML Platform - Unified Architecture

## Overview

This is a unified ML platform with **Traefik** as the single API gateway routing all services. Both MLflow and Ray Compute are accessed exclusively through Traefik routing.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Traefik API Gateway                       │
│               (ml-platform-gateway)                          │
│                   Port 80, 8090                              │
└──────────────────┬──────────────────────────────────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
       ▼                       ▼
┌──────────────┐      ┌──────────────┐
│ MLflow Stack │      │ Ray Compute  │
│              │      │              │
│ • Server     │      │ • Head Node  │
│ • Nginx      │      │ • API        │
│ • PostgreSQL │      │ • PostgreSQL │
│ • Redis      │      │ • Redis      │
│ • Grafana    │      │ • Grafana    │
│ • Prometheus │      │ • Prometheus │
│ • Adminer    │      │ • Authentik  │
└──────────────┘      └──────────────┘
       │                       │
       └───────────┬───────────┘
                   ▼
          ml-platform network
```

## Routing Table

All services accessible via `http://localhost/`:

| Path | Service | Description |
|------|---------|-------------|
| `/mlflow/` | MLflow UI | Experiment tracking, Model Registry |
| `/grafana/` | MLflow Grafana | MLflow metrics and monitoring |
| `/prometheus/` | MLflow Prometheus | Metrics storage |
| `/adminer/` | Adminer | Database management UI |
| `/ray/` | Ray Dashboard | Ray cluster monitoring |
| `/ray-grafana/` | Ray Grafana | Ray metrics and GPU monitoring |
| `:8090/` | Traefik Dashboard | View all routes and services |

## Quick Start

### 1. Start Ray Compute (includes Traefik)

```bash
cd ray_compute
docker-compose up -d
```

### 2. Start MLflow

```bash
cd mlflow-server
./START_SERVICES.sh
```

### 3. Verify All Services

```bash
cd mlflow-server
./test_all_services.sh
```

## Remote Client Usage

### MLflow Tracking

```python
import mlflow

# Configure via Traefik routing
mlflow.set_tracking_uri("http://localhost/mlflow")

# Or set environment variable
# export MLFLOW_TRACKING_URI="http://localhost/mlflow"

# Use normally
with mlflow.start_run():
    mlflow.log_param("alpha", 0.5)
    mlflow.log_metric("rmse", 0.87)
```

### Model Registry

```python
from mlflow.tracking import MlflowClient

client = MlflowClient("http://localhost/mlflow")

# Register model
mlflow.register_model("runs:/abc123/model", "my-model")

# Promote to production
client.transition_model_version_stage(
    name="my-model",
    version=1,
    stage="Production"
)
```

## Management Commands

### MLflow Services

```bash
# Start
cd mlflow-server && ./START_SERVICES.sh

# Stop
cd mlflow-server && ./STOP_SERVICES.sh

# Test
cd mlflow-server && ./test_all_services.sh

# Update passwords
cd mlflow-server && ./update_passwords.sh <new_password>
```

### Ray Compute Services

```bash
# Start (includes Traefik gateway)
cd ray_compute && docker-compose up -d

# Stop
cd ray_compute && docker-compose down

# Logs
cd ray_compute && docker-compose logs -f ray-head
```

### View All Routes

```bash
curl http://localhost:8090/api/http/routers | jq
```

## Network Configuration

All services must be on the `ml-platform` Docker network:

```bash
# Check network
docker network inspect ml-platform

# Services should include:
# - ml-platform-gateway (Traefik)
# - mlflow-nginx, mlflow-server, mlflow-postgres, etc.
# - ray-head, ray-compute-api, ray-compute-db, etc.
```

## Important Rules

### ✅ DO

- Access all services via Traefik routes (`http://localhost/service-path`)
- Use unified docker-compose.yml configurations
- Keep all services on ml-platform network
- Use START_SERVICES.sh and STOP_SERVICES.sh scripts

### ❌ DON'T

- Access services via direct ports (except Traefik :8090)
- Create separate standalone docker-compose files
- Bypass Traefik routing
- Expose individual service ports to host

## Troubleshooting

### Service not accessible

```bash
# 1. Check container is running
docker ps | grep <service-name>

# 2. Check it's on ml-platform network
docker network inspect ml-platform | grep <service-name>

# 3. Check Traefik has route
curl http://localhost:8090/api/http/routers | grep <service-name>

# 4. Check container logs
docker logs <service-name>
```

### Traefik not routing

```bash
# Restart Traefik
cd ray_compute
docker-compose restart traefik

# Check Traefik logs
docker logs ml-platform-gateway
```

### Network issues

```bash
# Recreate network (stop all services first)
docker network rm ml-platform
docker network create ml-platform

# Restart services
cd ray_compute && docker-compose up -d
cd ../mlflow-server && ./START_SERVICES.sh
```

## File Structure

```
Projects/
├── ml-platform/mlflow-server/
│   ├── docker-compose.yml          # Unified MLflow stack
│   ├── START_SERVICES.sh           # Start script
│   ├── STOP_SERVICES.sh            # Stop script
│   ├── test_all_services.sh        # Health checks
│   ├── update_passwords.sh         # Password management
│   └── docs/
│       ├── REMOTE_CLIENT_GUIDE.md  # Client usage
│       ├── MODEL_REGISTRY_GUIDE.md # Model Registry docs
│       └── DOCKER_COMPOSE_FIX.md   # Troubleshooting
│
└── ml-platform/ray_compute/
    ├── docker-compose.yml           # Includes Traefik gateway
    ├── start_all.sh                 # Start Ray + Traefik
    └── stop_all.sh                  # Stop Ray + Traefik
```

## Documentation

- **Remote Client Usage**: `ml-platform/mlflow-server/docs/REMOTE_CLIENT_GUIDE.md`
- **Model Registry**: `ml-platform/mlflow-server/docs/MODEL_REGISTRY_GUIDE.md`
- **Docker Compose Fix**: `ml-platform/mlflow-server/docs/DOCKER_COMPOSE_FIX.md`
- **Access URLs**: `ml-platform/mlflow-server/ACCESS_URLS.md`

## Credentials

All passwords set to: `AiSolutions2350!`

- MLflow Grafana: admin / AiSolutions2350!
- Ray Grafana: admin / AiSolutions2350!
- Authentik: akadmin / AiSolutions2350!

Stored in:
- `ml-platform/mlflow-server/secrets/grafana_password.txt`
- `ml-platform/ray_compute/.env` (GRAFANA_ADMIN_PASSWORD, AUTHENTIK_BOOTSTRAP_PASSWORD)

## Support

For issues or questions, check:
1. Service logs: `docker logs <container-name>`
2. Traefik dashboard: `http://localhost:8090/`
3. Test script output: `./test_all_services.sh`
4. Documentation in `docs/` directory
