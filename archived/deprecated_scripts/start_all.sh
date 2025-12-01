#!/bin/bash
# ML Platform - Unified Startup Script
# Starts all services in the correct order with health checks

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "ML Platform - Starting All Services"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if network exists, create if not
echo "📡 Checking network..."
if ! docker network inspect ml-platform >/dev/null 2>&1; then
    echo "Creating ml-platform network..."
    docker network create ml-platform --subnet 172.30.0.0/16
    echo -e "${GREEN}✓ Network created${NC}"
else
    echo -e "${GREEN}✓ Network exists${NC}"
fi
echo ""

# Check required secrets exist
echo "🔐 Checking secrets..."
SECRETS_MISSING=0

if [ ! -f "./ml-platform/mlflow-server/secrets/db_password.txt" ]; then
    echo -e "${RED}✗ Missing: ml-platform/mlflow-server/secrets/db_password.txt${NC}"
    SECRETS_MISSING=1
fi

if [ ! -f "./ml-platform/mlflow-server/secrets/grafana_password.txt" ]; then
    echo -e "${RED}✗ Missing: ml-platform/mlflow-server/secrets/grafana_password.txt${NC}"
    SECRETS_MISSING=1
fi

if [ ! -f "./ml-platform/ray_compute/secrets/db_password.txt" ]; then
    echo -e "${RED}✗ Missing: ml-platform/ray_compute/secrets/db_password.txt${NC}"
    SECRETS_MISSING=1
fi

if [ $SECRETS_MISSING -eq 1 ]; then
    echo ""
    echo -e "${YELLOW}Creating missing secrets with default values...${NC}"

    mkdir -p ml-platform/mlflow-server/secrets ml-platform/ray_compute/secrets

    [ ! -f "./ml-platform/mlflow-server/secrets/db_password.txt" ] && echo "mlflow_secure_password_$(date +%s)" > ./ml-platform/mlflow-server/secrets/db_password.txt
    [ ! -f "./ml-platform/mlflow-server/secrets/grafana_password.txt" ] && echo "admin" > ./ml-platform/mlflow-server/secrets/grafana_password.txt
    [ ! -f "./ml-platform/ray_compute/secrets/db_password.txt" ] && echo "ray_secure_password_$(date +%s)" > ./ml-platform/ray_compute/secrets/db_password.txt

    echo -e "${GREEN}✓ Secrets created${NC}"
else
    echo -e "${GREEN}✓ All secrets present${NC}"
fi
echo ""

# Start services in stages
echo "🚀 Starting services..."
echo ""

# Stage 1: Infrastructure
echo "Stage 1: Infrastructure (Traefik, Redis)"
docker-compose up -d traefik redis
echo "Waiting for infrastructure to be ready..."
sleep 5
echo -e "${GREEN}✓ Infrastructure ready${NC}"
echo ""

# Stage 2: Databases & Auth Infrastructure
echo "Stage 2: Databases & Auth (PostgreSQL, Redis, Authentik)"
docker-compose up -d mlflow-postgres ray-postgres authentik-db authentik-redis
echo "Waiting for databases to be healthy..."
sleep 10

# Start Authentik services
docker-compose up -d authentik-server authentik-worker
echo "Waiting for Authentik to be ready..."
sleep 15

echo -e "${GREEN}✓ Databases and Authentik ready${NC}"
echo ""

# Stage 3: Core Services
echo "Stage 3: Core Services (MLflow, Ray Head)"
docker-compose up -d mlflow-server ray-head

echo "Waiting for mlflow-server to be healthy..."
for i in {1..60}; do
    if [ "$(docker inspect --format='{{.State.Health.Status}}' mlflow-server 2>/dev/null)" = "healthy" ]; then
        echo -e "${GREEN}✓ mlflow-server is healthy${NC}"
        break
    fi
    if [ $i -eq 60 ]; then
        echo -e "${RED}✗ mlflow-server failed to become healthy${NC}"
        echo "Checking logs:"
        docker logs mlflow-server --tail 20
        exit 1
    fi
    sleep 2
done

echo "Waiting for ray-head to be healthy..."
for i in {1..60}; do
    if [ "$(docker inspect --format='{{.State.Health.Status}}' ray-head 2>/dev/null)" = "healthy" ]; then
        echo -e "${GREEN}✓ ray-head is healthy${NC}"
        break
    fi
    if [ $i -eq 60 ]; then
        echo -e "${RED}✗ ray-head failed to become healthy${NC}"
        echo "Checking logs:"
        docker logs ray-head --tail 20
        exit 1
    fi
    sleep 2
done
echo ""

# Stage 4: Frontend & API
echo "Stage 4: Frontend & API (Nginx, MLflow API, Ray API)"
docker-compose up -d mlflow-nginx mlflow-api ray-compute-api

echo "Waiting for mlflow-nginx to be healthy..."
for i in {1..30}; do
    if [ "$(docker inspect --format='{{.State.Health.Status}}' mlflow-nginx 2>/dev/null)" = "healthy" ]; then
        echo -e "${GREEN}✓ mlflow-nginx is healthy${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${YELLOW}⚠ mlflow-nginx status: $(docker inspect --format='{{.State.Health.Status}}' mlflow-nginx 2>/dev/null)${NC}"
    fi
    sleep 2
done

echo "Waiting for mlflow-api to be healthy..."
for i in {1..30}; do
    if [ "$(docker inspect --format='{{.State.Health.Status}}' mlflow-api 2>/dev/null)" = "healthy" ]; then
        echo -e "${GREEN}✓ mlflow-api is healthy${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${YELLOW}⚠ mlflow-api status: $(docker inspect --format='{{.State.Health.Status}}' mlflow-api 2>/dev/null)${NC}"
    fi
    sleep 2
done

echo "Waiting for ray-compute-api to be healthy..."
for i in {1..30}; do
    if [ "$(docker inspect --format='{{.State.Health.Status}}' ray-compute-api 2>/dev/null)" = "healthy" ]; then
        echo -e "${GREEN}✓ ray-compute-api is healthy${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${YELLOW}⚠ ray-compute-api status: $(docker inspect --format='{{.State.Health.Status}}' ray-compute-api 2>/dev/null)${NC}"
    fi
    sleep 2
done
echo ""

# Stage 5: Monitoring
echo "Stage 5: Monitoring (Prometheus, Grafana)"
docker-compose up -d \
    mlflow-prometheus mlflow-grafana \
    ray-prometheus ray-grafana
echo "Waiting for monitoring services..."
sleep 10
echo -e "${GREEN}✓ Monitoring services started${NC}"
echo ""

# Stage 6: Utilities
echo "Stage 6: Utilities (Adminer, Backup)"
docker-compose up -d mlflow-adminer mlflow-backup
echo "Waiting for utilities..."
sleep 5
echo -e "${GREEN}✓ Utilities started${NC}"
echo ""

# Stage 7: Initialize Experiments
echo "Stage 7: Initializing Experiment Schema"
echo "Creating standard experiments..."
if [ -f "./ml-platform/mlflow-server/scripts/initialize_experiments.py" ]; then
    docker exec mlflow-server python /mlflow/scripts/initialize_experiments.py
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Experiments initialized${NC}"
    else
        echo -e "${YELLOW}⚠ Experiment initialization had errors (this is OK on first run)${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Initialization script not found${NC}"
fi
echo ""

# Show status
echo "=========================================="
echo "Container Status"
echo "=========================================="
docker-compose ps
echo ""

# Get dynamic service information
echo "=========================================="
echo "🎉 ML Platform Services Started!"
echo "=========================================="
echo ""

# Get network IPs
LAN_IP=$(hostname -I | awk '{print $1}')
TAILSCALE_IP=$(ip -4 addr show tailscale0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' || echo "")

# Get Traefik port
TRAEFIK_PORT=$(docker port ml-platform-traefik 8080 2>/dev/null | cut -d: -f2 || echo "8090")

echo "📊 Service Access URLs:"
echo ""
echo "🌐 LAN Access (Local Network):"
echo "  MLflow UI:           http://${LAN_IP}/mlflow/"
echo "  MLflow HTTPS:        https://${LAN_IP}/mlflow/ (self-signed cert)"
echo "  MLflow API:          http://${LAN_IP}/api/v1"
echo "  API Docs:            http://${LAN_IP}/api/v1/docs"
echo "  Ray Dashboard:       http://${LAN_IP}/ray/"
echo "  Traefik Dashboard:   http://${LAN_IP}:${TRAEFIK_PORT}/"
echo ""
if [ -n "$TAILSCALE_IP" ]; then
echo "🔐 Tailscale VPN Access:"
echo "  MLflow UI:           http://${TAILSCALE_IP}/mlflow/"
echo "  MLflow HTTPS:        https://${TAILSCALE_IP}/mlflow/"
echo "  MLflow API:          http://${TAILSCALE_IP}/api/v1"
echo "  API Docs:            http://${TAILSCALE_IP}/api/v1/docs"
echo "  Ray Dashboard:       http://${TAILSCALE_IP}/ray/"
echo "  Traefik Dashboard:   http://${TAILSCALE_IP}:${TRAEFIK_PORT}/"
echo ""
fi
echo "📊 Monitoring:"
echo "  MLflow Grafana:      http://${LAN_IP}/mlflow-grafana/"
echo "  MLflow Prometheus:   http://${LAN_IP}/mlflow-prometheus/"
echo "  Ray Grafana:         http://${LAN_IP}/ray-grafana/"
echo ""
echo "🔧 Management:"
echo "  Adminer (DB):        http://${LAN_IP}/adminer/"
echo ""
echo "📦 Running Containers:"
docker ps --filter "network=ml-platform" --format "  {{.Names}}: {{.Status}}" | sort
echo ""

# Health check summary
echo "🏥 Health Status:"
for container in mlflow-server mlflow-nginx ray-head ray-compute-api mlflow-postgres ray-compute-db; do
    if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        health=$(docker inspect --format='{{.State.Health.Status}}' $container 2>/dev/null || echo "no healthcheck")
        case $health in
            "healthy")
                echo -e "  ${container}: ${GREEN}✓ healthy${NC}"
                ;;
            "unhealthy")
                echo -e "  ${container}: ${RED}✗ unhealthy${NC}"
                ;;
            "starting")
                echo -e "  ${container}: ${YELLOW}⏳ starting${NC}"
                ;;
            *)
                echo -e "  ${container}: ${YELLOW}⚠ $health${NC}"
                ;;
        esac
    fi
done
echo ""

echo "📝 Useful Commands:"
echo "  View logs:           docker-compose logs -f [service-name]"
echo "  Stop all:            ./stop_all.sh"
echo "  Restart service:     docker-compose restart [service-name]"
echo ""
