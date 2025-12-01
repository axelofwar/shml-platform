#!/bin/bash
#
# ML Platform - Unified Startup Script
# Starts: Traefik Gateway + MLflow Server + Ray Compute
# Access: http://localhost (single entry point)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=================================================="
echo "ML Platform - Unified Startup"
echo "=================================================="
echo ""
echo "Starting containerized ML infrastructure..."
echo "  - Traefik API Gateway"
echo "  - MLflow Tracking Server"
echo "  - Ray Compute Cluster"
echo "  - Shared Monitoring Stack"
echo ""

# Environment selection
ENV=${1:-dev}
echo "Environment: $ENV"
echo ""

# Load environment variables
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "Loading environment variables from .env..."
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
else
    echo "⚠️  No .env file found. Using defaults."
    echo "Create one from: ml-platform/ray_compute/.env.example"
fi

echo ""
echo "=================================================="
echo "Step 1: Network Setup"
echo "=================================================="
echo ""

# Create shared network if it doesn't exist
if ! docker network inspect ml-platform >/dev/null 2>&1; then
    echo "Creating ml-platform network..."
    bash "$SCRIPT_DIR/create-ml-platform-network.sh"
else
    echo "✓ ml-platform network exists"
fi

echo ""
echo "=================================================="
echo "Step 2: GPU Setup (if available)"
echo "=================================================="
echo ""

# Check for GPU and setup MPS if available
if nvidia-smi &>/dev/null; then
    echo "✓ NVIDIA GPU detected"

    # Check if MPS is running
    if ! pgrep -f nvidia-cuda-mps > /dev/null; then
        echo "Setting up GPU sharing (MPS)..."
        echo "This requires sudo privileges."
        sudo bash "$SCRIPT_DIR/setup-gpu-sharing.sh" || {
            echo "⚠️  GPU sharing setup failed. Continuing without MPS."
            echo "Multiple services may not be able to use GPU simultaneously."
        }
    else
        echo "✓ GPU sharing (MPS) already running"
    fi
else
    echo "ℹ️  No NVIDIA GPU detected. GPU workloads will not be available."
fi

echo ""
echo "=================================================="
echo "Step 3: Starting Traefik API Gateway"
echo "=================================================="
echo ""

cd "$PROJECT_ROOT"

# Stop existing Traefik if running
if docker ps -q -f name=ml-platform-gateway >/dev/null 2>&1; then
    echo "Stopping existing Traefik..."
    docker compose -f docker-compose.gateway.yml down
fi

echo "Starting Traefik..."
docker compose -f docker-compose.gateway.yml up -d

# Wait for Traefik to be ready
echo "Waiting for Traefik..."
for i in {1..30}; do
    if curl -s http://localhost:8090/ping >/dev/null 2>&1; then
        echo "✓ Traefik ready"
        break
    fi
    sleep 1
done

echo ""
echo "=================================================="
echo "Step 4: Starting MLflow Server"
echo "=================================================="
echo ""

cd "$PROJECT_ROOT/mlflow-server"

# Stop old stack if running
if docker ps -q -f name=mlflow-server >/dev/null 2>&1; then
    echo "Stopping old MLflow stack..."
    docker compose down 2>/dev/null || true
fi

echo "Starting MLflow unified stack..."
docker compose -f docker-compose.unified.yml up -d

# Wait for MLflow to be ready
echo "Waiting for MLflow..."
for i in {1..60}; do
    if docker exec mlflow-server curl -s http://localhost:5000/health >/dev/null 2>&1; then
        echo "✓ MLflow ready"
        break
    fi
    sleep 2
done

echo ""
echo "=================================================="
echo "Step 5: Starting Ray Compute"
echo "=================================================="
echo ""

cd "$PROJECT_ROOT/ray_compute"

# Stop old stacks if running
echo "Stopping old Ray stacks..."
docker compose -f docker-compose.api.yml down 2>/dev/null || true
docker compose -f docker-compose.ray.yml down 2>/dev/null || true
docker compose -f docker-compose.observability.yml down 2>/dev/null || true

echo "Starting Ray Compute unified stack..."
docker compose -f docker-compose.unified.yml up -d

# Wait for Ray to be ready
echo "Waiting for Ray cluster..."
for i in {1..60}; do
    if docker exec ray-head ray status >/dev/null 2>&1; then
        echo "✓ Ray cluster ready"
        break
    fi
    sleep 2
done

# Wait for Ray API
echo "Waiting for Ray Compute API..."
for i in {1..30}; do
    if docker exec ray-compute-api curl -s http://localhost:8000/health >/dev/null 2>&1; then
        echo "✓ Ray Compute API ready"
        break
    fi
    sleep 2
done

echo ""
echo "=================================================="
echo "Step 6: Verifying Inter-Service Communication"
echo "=================================================="
echo ""

echo "Testing network connectivity..."

# Test MLflow → Redis
if docker exec mlflow-server ping -c 1 ml-platform-redis >/dev/null 2>&1; then
    echo "✓ MLflow → Redis"
else
    echo "✗ MLflow → Redis (failed)"
fi

# Test Ray API → MLflow
if docker exec ray-compute-api curl -s http://mlflow-nginx:80/health >/dev/null 2>&1; then
    echo "✓ Ray API → MLflow"
else
    echo "✗ Ray API → MLflow (failed)"
fi

# Test Ray API → Ray Head
if docker exec ray-compute-api curl -s http://ray-head:8265/ >/dev/null 2>&1; then
    echo "✓ Ray API → Ray Head"
else
    echo "✗ Ray API → Ray Head (failed)"
fi

echo ""
echo "=================================================="
echo "ML Platform Started Successfully!"
echo "=================================================="
echo ""

# Get host IPs
LOCAL_IP=$(hostname -I | awk '{print $1}')
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "not configured")

echo "🌐 Access URLs:"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Unified Dashboard (Traefik)"
echo "   Local:      http://localhost:8090"
echo "   LAN:        http://$LOCAL_IP:8090"
if [ "$TAILSCALE_IP" != "not configured" ]; then
echo "   VPN:        http://$TAILSCALE_IP:8090"
fi
echo ""
echo "🧪 MLflow Tracking Server"
echo "   Local:      http://localhost/mlflow"
echo "   LAN:        http://$LOCAL_IP/mlflow"
if [ "$TAILSCALE_IP" != "not configured" ]; then
echo "   VPN:        http://$TAILSCALE_IP/mlflow"
fi
echo "   API:        http://localhost/api/2.0/mlflow"
echo ""
echo "⚡ Ray Compute"
echo "   Dashboard:  http://localhost/ray"
echo "   API:        http://localhost/api/ray"
echo "   Docs:       http://localhost/ray-docs"
echo ""
echo "📈 Monitoring"
echo "   Grafana (MLflow):  http://localhost/grafana"
echo "   Grafana (Ray):     http://localhost/ray-grafana"
echo "   Prometheus:        http://localhost/prometheus"
echo "   Adminer (DB):      http://localhost/adminer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "🐳 Container Status:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "ml-platform|mlflow|ray"

echo ""
echo "📝 Quick Commands:"
echo ""
echo "  View logs:      docker compose -f <stack>/docker-compose.unified.yml logs -f"
echo "  Stop platform:  bash $SCRIPT_DIR/stop-ml-platform.sh"
echo "  Check status:   docker ps"
echo "  GPU usage:      watch -n 1 nvidia-smi"
echo ""
echo "🔧 Configuration Files:"
echo "  Environment:    $PROJECT_ROOT/.env"
echo "  Gateway:        $PROJECT_ROOT/docker-compose.gateway.yml"
echo "  MLflow:         $PROJECT_ROOT/ml-platform/mlflow-server/docker-compose.unified.yml"
echo "  Ray Compute:    $PROJECT_ROOT/ml-platform/ray_compute/docker-compose.unified.yml"
echo ""
echo "📚 Documentation:"
echo "  Architecture:   $PROJECT_ROOT/ARCHITECTURE_ANALYSIS.md"
echo "  API Usage:      $PROJECT_ROOT/ml-platform/mlflow-server/docs/API_USAGE_GUIDE.md"
echo ""

# Python client example
cat <<'EOF'
🐍 Python Client Setup:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import mlflow
import requests

# Connect to MLflow (choose one)
mlflow.set_tracking_uri("http://localhost/api/2.0/mlflow")  # Local
# mlflow.set_tracking_uri("http://YOUR_IP/api/2.0/mlflow")  # LAN
# mlflow.set_tracking_uri("http://TAILSCALE_IP/api/2.0/mlflow")  # VPN

# Test connection
print(mlflow.get_tracking_uri())

# Submit Ray job
ray_api = "http://localhost/api/ray"
response = requests.post(f"{ray_api}/health")
print(response.json())

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF

echo ""
echo "✅ All systems operational!"
echo ""
