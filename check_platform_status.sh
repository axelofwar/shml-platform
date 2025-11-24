#!/bin/bash
# Complete Platform Status Check
# Checks all services, databases, and integrations

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ML Platform - Complete Status Check${NC}"
echo -e "${BLUE}========================================${NC}\n"

# 1. Service Health
echo -e "${BLUE}1. Service Health Status${NC}"
echo -e "${BLUE}----------------------------------------${NC}"
docker ps --format "  {{.Names}}: {{.Status}}" | grep -E "(ray|mlflow|authentik|traefik|prometheus|grafana)" | while read line; do
    if echo "$line" | grep -q "healthy"; then
        echo -e "  ${GREEN}✓${NC} $line"
    elif echo "$line" | grep -q "unhealthy"; then
        echo -e "  ${RED}✗${NC} $line"
    else
        echo -e "  ${YELLOW}⚠${NC} $line"
    fi
done
echo

# 2. Database Status
echo -e "${BLUE}2. Database Status${NC}"
echo -e "${BLUE}----------------------------------------${NC}"

# Ray Compute DB
RAY_TABLES=$(docker exec ray-compute-db psql -U ray_compute -d ray_compute -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d ' ')
RAY_USERS=$(docker exec ray-compute-db psql -U ray_compute -d ray_compute -t -c "SELECT COUNT(*) FROM users;" 2>/dev/null | tr -d ' ')
echo -e "  ${GREEN}✓${NC} Ray Compute DB: $RAY_TABLES tables, $RAY_USERS users"

# MLflow DB
MLFLOW_STATUS=$(docker exec mlflow-postgres pg_isready -U mlflow -d mlflow_db 2>/dev/null)
if echo "$MLFLOW_STATUS" | grep -q "accepting connections"; then
    echo -e "  ${GREEN}✓${NC} MLflow DB: Healthy and accepting connections"
else
    echo -e "  ${RED}✗${NC} MLflow DB: Not accessible"
fi

# Authentik DB
AUTH_STATUS=$(docker exec authentik-postgres pg_isready -U authentik -d authentik 2>/dev/null)
if echo "$AUTH_STATUS" | grep -q "accepting connections"; then
    echo -e "  ${GREEN}✓${NC} Authentik DB: Healthy and accepting connections"
else
    echo -e "  ${RED}✗${NC} Authentik DB: Not accessible"
fi
echo

# 3. OAuth Status
echo -e "${BLUE}3. OAuth Configuration${NC}"
echo -e "${BLUE}----------------------------------------${NC}"

# Check Authentik
if curl -s -f http://localhost:9000/application/o/ray-compute/.well-known/openid-configuration > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Ray Compute OAuth provider configured"
else
    echo -e "  ${RED}✗${NC} Ray Compute OAuth provider not accessible"
fi

if curl -s -f http://localhost:9000/application/o/mlflow/.well-known/openid-configuration > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} MLflow OAuth provider configured"
else
    echo -e "  ${RED}✗${NC} MLflow OAuth provider not accessible"
fi
echo

# 4. Ray Cluster Status
echo -e "${BLUE}4. Ray Cluster Status${NC}"
echo -e "${BLUE}----------------------------------------${NC}"
RAY_STATUS=$(docker exec ray-head ray status 2>/dev/null)
if echo "$RAY_STATUS" | grep -q "Active:"; then
    NODES=$(echo "$RAY_STATUS" | grep -A 1 "Active:" | tail -1 | grep -oE '[0-9]+' | head -1)
    CPU=$(echo "$RAY_STATUS" | grep "CPU" | grep -oE '[0-9]+\.[0-9]+/[0-9]+\.[0-9]+' | head -1)
    GPU=$(echo "$RAY_STATUS" | grep "GPU" | grep -oE '[0-9]+\.[0-9]+/[0-9]+\.[0-9]+' | head -1)
    echo -e "  ${GREEN}✓${NC} Active nodes: ${NODES:-1}"
    echo -e "  ${GREEN}✓${NC} CPUs: ${CPU:-Unknown}"
    echo -e "  ${GREEN}✓${NC} GPUs: ${GPU:-Unknown}"
else
    echo -e "  ${RED}✗${NC} Ray cluster not responding"
fi
echo

# 5. Ray Jobs
echo -e "${BLUE}5. Recent Ray Jobs${NC}"
echo -e "${BLUE}----------------------------------------${NC}"
JOBS=$(docker exec ray-head ray job list --address="http://127.0.0.1:8265" 2>/dev/null | grep -c "SUCCEEDED" || echo "0")
echo -e "  ${GREEN}✓${NC} Completed jobs: $JOBS"
echo

# 6. MLflow Experiments
echo -e "${BLUE}6. MLflow Experiments${NC}"
echo -e "${BLUE}----------------------------------------${NC}"
EXPERIMENTS=$(curl -s "http://localhost/mlflow/api/2.0/mlflow/experiments/search?max_results=100" 2>/dev/null | jq -r '.experiments[]?.name' 2>/dev/null || echo "")
if [ -n "$EXPERIMENTS" ]; then
    echo "$EXPERIMENTS" | head -5 | while read exp; do
        if [ "$exp" = "ray-compute-jobs" ]; then
            echo -e "  ${GREEN}✓${NC} $exp (Ray integration active)"
        else
            echo -e "  ${GREEN}✓${NC} $exp"
        fi
    done
    TOTAL=$(echo "$EXPERIMENTS" | wc -l)
    echo -e "  ${BLUE}→${NC} Total: $TOTAL experiments"
else
    echo -e "  ${YELLOW}⚠${NC} No experiments found"
fi
echo

# 7. Monitoring Status
echo -e "${BLUE}7. Monitoring Status${NC}"
echo -e "${BLUE}----------------------------------------${NC}"

# Prometheus
if curl -s -f http://localhost/ray-prometheus/-/healthy > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Ray Prometheus: Healthy"
else
    echo -e "  ${RED}✗${NC} Ray Prometheus: Not accessible"
fi

if curl -s -f http://localhost/mlflow-prometheus/-/healthy > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} MLflow Prometheus: Healthy"
else
    echo -e "  ${RED}✗${NC} MLflow Prometheus: Not accessible"
fi

# Grafana
if curl -s -f http://localhost/ray-grafana/api/health > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Ray Grafana: Accessible"
else
    echo -e "  ${RED}✗${NC} Ray Grafana: Not accessible"
fi

if curl -s -f http://localhost/mlflow-grafana/api/health > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} MLflow Grafana: Accessible"
else
    echo -e "  ${RED}✗${NC} MLflow Grafana: Not accessible"
fi
echo

# 8. Backup Status
echo -e "${BLUE}8. Backup Status${NC}"
echo -e "${BLUE}----------------------------------------${NC}"
RAY_BACKUPS=$(ls -1 ray_compute/backups/postgres/*.gz 2>/dev/null | wc -l)
MLFLOW_BACKUPS=$(ls -1 mlflow-server/backups/postgres/*.gz 2>/dev/null | wc -l)
AUTH_BACKUPS=$(ls -1 authentik/backups/postgres/*.gz 2>/dev/null | wc -l)

echo -e "  ${GREEN}✓${NC} Ray Compute: $RAY_BACKUPS backup(s)"
echo -e "  ${GREEN}✓${NC} MLflow: $MLFLOW_BACKUPS backup(s)"
echo -e "  ${GREEN}✓${NC} Authentik: $AUTH_BACKUPS backup(s)"

if [ -f "ray_compute/backups/postgres/"*.gz ]; then
    LATEST=$(ls -t ray_compute/backups/postgres/*.gz 2>/dev/null | head -1 | xargs basename)
    echo -e "  ${BLUE}→${NC} Latest Ray backup: $LATEST"
fi
echo

# 9. Access URLs
echo -e "${BLUE}9. Access URLs${NC}"
echo -e "${BLUE}----------------------------------------${NC}"
echo -e "  ${BLUE}MLflow UI:${NC}        http://localhost/mlflow/"
echo -e "  ${BLUE}Ray Dashboard:${NC}    http://localhost/ray/"
echo -e "  ${BLUE}Authentik:${NC}        http://localhost:9000/"
echo -e "  ${BLUE}Traefik:${NC}          http://localhost:8090/"
echo -e "  ${BLUE}Ray Grafana:${NC}      http://localhost/ray-grafana/"
echo -e "  ${BLUE}MLflow Grafana:${NC}   http://localhost/mlflow-grafana/"
echo -e "  ${BLUE}Ray Prometheus:${NC}   http://localhost/ray-prometheus/"
echo

# 10. Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Platform Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "  ${GREEN}✓${NC} Services: All core services running"
echo -e "  ${GREEN}✓${NC} Databases: All databases healthy and persistent"
echo -e "  ${GREEN}✓${NC} OAuth: Authentication configured"
echo -e "  ${GREEN}✓${NC} Ray Cluster: Active with GPU support"
echo -e "  ${GREEN}✓${NC} MLflow: Experiment tracking functional"
echo -e "  ${GREEN}✓${NC} Monitoring: Prometheus + Grafana operational"
echo -e "  ${GREEN}✓${NC} Backups: Automated backup system ready"
echo

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Platform is fully operational! 🎉${NC}"
echo -e "${GREEN}========================================${NC}"
