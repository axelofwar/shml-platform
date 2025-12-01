#!/bin/bash
# Verify platform is ready for OAuth configuration

# Load environment variables if .env exists
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

echo "=========================================="
echo "  OAuth Readiness Check"
echo "=========================================="
echo

checks_passed=0
checks_total=0

check() {
    checks_total=$((checks_total + 1))
    if eval "$2" > /dev/null 2>&1; then
        echo "✓ $1"
        checks_passed=$((checks_passed + 1))
        return 0
    else
        echo "✗ $1"
        return 1
    fi
}

echo "=== Service Health ==="
check "Traefik is healthy" "docker inspect ml-platform-traefik --format='{{.State.Health.Status}}' | grep -q healthy"
check "Authentik is healthy" "docker inspect authentik-server --format='{{.State.Health.Status}}' | grep -q healthy"
check "MLflow API is healthy" "docker inspect mlflow-api --format='{{.State.Health.Status}}' | grep -q healthy"
check "Ray Compute API is healthy" "docker inspect ray-compute-api --format='{{.State.Health.Status}}' | grep -q healthy"

echo
echo "=== Network Tools ==="
check "curl available in ray-compute-api" "docker exec ray-compute-api which curl"
check "wget available in ray-compute-api" "docker exec ray-compute-api which wget"
check "curl available in mlflow-api" "docker exec mlflow-api which curl"

echo
echo "=== API Endpoints ==="
check "MLflow API /ping responds" "docker exec mlflow-api curl -sf http://localhost:8000/ping"
check "Ray API /ping responds" "docker exec ray-compute-api curl -sf http://localhost:8000/ping"
check "Authentik is accessible" "curl -sI http://localhost:9000/ | head -1 | grep -q '302\|200'"

echo
echo "=== OAuth Prerequisites ==="
check "OAuth scripts are executable" "test -x configure_oauth.sh && test -x enable_oauth.sh"
check "MLflow integration module exists" "test -f ray_compute/api/mlflow_integration.py"
check "OAuth guides exist" "test -f OAUTH_QUICKSTART.md && test -f OAUTH_SETUP_GUIDE.md"

echo
echo "=========================================="
echo "  Results: $checks_passed/$checks_total checks passed"
echo "=========================================="

if [ $checks_passed -eq $checks_total ]; then
    echo
    echo "✅ Platform is ready for OAuth configuration!"
    echo
    echo "Next steps:"
    echo "  1. Open Authentik: http://localhost:9000/"
    echo "  2. Login: akadmin / <your AUTHENTIK_BOOTSTRAP_PASSWORD from .env>"
    echo "  3. Follow: cat OAUTH_QUICKSTART.md"
    echo
    exit 0
else
    echo
    echo "⚠️  Some checks failed. Please review above."
    echo
    exit 1
fi
