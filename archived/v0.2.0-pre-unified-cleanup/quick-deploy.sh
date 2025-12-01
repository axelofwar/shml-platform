#!/bin/bash
#
# ML Platform v2.0 - Quick Deploy
# One-command setup for development environment
#

set -e

cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║         ML Platform v2.0 - Quick Deploy                   ║
║         Unified MLflow + Ray Compute Architecture         ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
EOF

echo ""
echo "This script will:"
echo "  1. Create shared network"
echo "  2. Setup GPU sharing (if available)"
echo "  3. Deploy all services"
echo "  4. Verify connectivity"
echo ""
echo "Estimated time: 5-10 minutes"
echo ""

read -p "Continue? [Y/n] " -n 1 -r
echo
if [[ $REPLY =~ ^[Nn]$ ]]; then
    echo "Cancelled."
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 1/5: Environment Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check .env file
if [ ! -f "$PROJECT_ROOT/ml-platform/ray_compute/.env" ]; then
    echo ""
    echo "⚠️  No .env file found. Creating from template..."
    cp "$PROJECT_ROOT/ml-platform/ray_compute/.env.example" "$PROJECT_ROOT/ml-platform/ray_compute/.env"
    
    # Generate secure passwords
    POSTGRES_PASS=$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)
    API_KEY=$(openssl rand -base64 50 | tr -d '/+=' | cut -c1-50)
    
    # Update .env
    sed -i "s|POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$POSTGRES_PASS|" "$PROJECT_ROOT/ml-platform/ray_compute/.env"
    sed -i "s|API_SECRET_KEY=.*|API_SECRET_KEY=$API_KEY|" "$PROJECT_ROOT/ml-platform/ray_compute/.env"
    sed -i "s|RAY_ADDRESS=.*|RAY_ADDRESS=http://ray-head:8265|" "$PROJECT_ROOT/ml-platform/ray_compute/.env"
    sed -i "s|MLFLOW_TRACKING_URI=.*|MLFLOW_TRACKING_URI=http://mlflow-nginx:80|" "$PROJECT_ROOT/ml-platform/ray_compute/.env"
    sed -i "s|REDIS_HOST=.*|REDIS_HOST=ml-platform-redis|" "$PROJECT_ROOT/ml-platform/ray_compute/.env"
    
    echo "✅ Generated .env with secure passwords"
    echo "   Location: $PROJECT_ROOT/ml-platform/ray_compute/.env"
else
    echo "✅ Found existing .env file"
fi

# Check Docker
if ! docker info &>/dev/null; then
    echo "❌ Docker is not running or not accessible"
    echo "   Please start Docker and try again"
    exit 1
fi
echo "✅ Docker is running"

# Check ports (only check for listening services, not outbound connections)
if sudo ss -tlnp | grep -q ':80 '; then
    echo "⚠️  Port 80 is in use. Attempting to free..."
    sudo systemctl stop apache2 2>/dev/null || true
    sudo systemctl stop nginx 2>/dev/null || true
    sleep 2
    if sudo ss -tlnp | grep -q ':80 '; then
        echo "❌ Port 80 is still in use. Please free it manually:"
        echo "   sudo ss -tlnp | grep ':80'"
        exit 1
    fi
fi
echo "✅ Port 80 is available"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2/5: Network Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

bash "$SCRIPT_DIR/create-ml-platform-network.sh" || {
    echo "⚠️  Network creation had issues, but continuing..."
}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3/5: GPU Setup (if available)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if nvidia-smi &>/dev/null; then
    echo "✓ NVIDIA GPU detected"
    
    if ! pgrep -f nvidia-cuda-mps > /dev/null; then
        echo "Setting up GPU sharing..."
        sudo bash "$SCRIPT_DIR/setup-gpu-sharing.sh" || {
            echo "⚠️  GPU sharing setup failed. Continuing without MPS."
        }
    else
        echo "✓ GPU sharing already enabled"
    fi
else
    echo "ℹ️  No NVIDIA GPU detected. Skipping GPU setup."
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 4/5: Deploying Services"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Stop old services
echo "Stopping old services..."
cd "$PROJECT_ROOT"
docker-compose -f docker-compose.gateway.yml down 2>/dev/null || true
cd "$PROJECT_ROOT/mlflow-server"
docker-compose down 2>/dev/null || true
cd "$PROJECT_ROOT/ray_compute"
docker-compose -f docker-compose.api.yml down 2>/dev/null || true
docker-compose -f docker-compose.ray.yml down 2>/dev/null || true

echo ""
echo "Starting Traefik Gateway..."
cd "$PROJECT_ROOT"
docker-compose -f docker-compose.gateway.yml up -d
sleep 5

echo ""
echo "Starting MLflow Server..."
cd "$PROJECT_ROOT/mlflow-server"
docker-compose -f docker-compose.unified.yml up -d
sleep 10

echo ""
echo "Starting Ray Compute..."
cd "$PROJECT_ROOT/ray_compute"
docker-compose -f docker-compose.unified.yml up -d
sleep 10

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 5/5: Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "Waiting for services to be ready..."
sleep 15

# Test connectivity
echo ""
echo "Testing service health..."

FAILED=0

# Traefik
if curl -s http://localhost:8090/ping >/dev/null 2>&1; then
    echo "✅ Traefik Gateway"
else
    echo "❌ Traefik Gateway"
    FAILED=$((FAILED+1))
fi

# MLflow
if docker exec mlflow-server curl -sf http://localhost:5000/health >/dev/null 2>&1; then
    echo "✅ MLflow Server"
else
    echo "❌ MLflow Server"
    FAILED=$((FAILED+1))
fi

# Ray
if docker exec ray-head ray status >/dev/null 2>&1; then
    echo "✅ Ray Cluster"
else
    echo "❌ Ray Cluster"
    FAILED=$((FAILED+1))
fi

# Ray API
if docker exec ray-compute-api curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo "✅ Ray Compute API"
else
    echo "❌ Ray Compute API"
    FAILED=$((FAILED+1))
fi

# Inter-service communication
if docker exec ray-compute-api curl -sf http://mlflow-nginx:80/health >/dev/null 2>&1; then
    echo "✅ Ray → MLflow Communication"
else
    echo "❌ Ray → MLflow Communication"
    FAILED=$((FAILED+1))
fi

echo ""
if [ $FAILED -eq 0 ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✨ Success! ML Platform is operational"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⚠️  $FAILED service(s) failed health check"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check logs: docker logs <container-name>"
    echo "  2. Verify network: docker network inspect ml-platform"
    echo "  3. See IMPLEMENTATION_CHECKLIST.md for detailed steps"
fi

# Get IPs
LOCAL_IP=$(hostname -I | awk '{print $1}')
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "not configured")

echo ""
echo "🌐 Access URLs:"
echo ""
echo "  Traefik Dashboard:  http://localhost:8090"
echo "  MLflow UI:          http://localhost/mlflow"
echo "  Ray Dashboard:      http://localhost/ray"
echo "  Ray API Docs:       http://localhost/ray-docs"
echo "  Grafana:            http://localhost/grafana"
echo ""
if [ "$LOCAL_IP" != "" ]; then
    echo "  LAN Access:         http://$LOCAL_IP/mlflow"
fi
if [ "$TAILSCALE_IP" != "not configured" ]; then
    echo "  VPN Access:         http://$TAILSCALE_IP/mlflow"
fi
echo ""
echo "🐳 Container Status:"
docker ps --format "table {{.Names}}\t{{.Status}}" | head -15
echo ""
echo "📚 Documentation:"
echo "  Quick Reference:    cat ML_PLATFORM_QUICK_REFERENCE.md"
echo "  Full Guide:         cat ML_PLATFORM_DEPLOYMENT.md"
echo "  Checklist:          cat IMPLEMENTATION_CHECKLIST.md"
echo ""
echo "🛠️  Management:"
echo "  Stop all:           bash scripts/stop-ml-platform.sh"
echo "  View logs:          docker logs -f <container>"
echo "  Check status:       docker ps"
echo ""

# Test Python connection
cat << 'EOF'
🐍 Test Python Connection:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

python3 << PYTHON
import mlflow
mlflow.set_tracking_uri("http://localhost/api/2.0/mlflow")
print("✅ Connected to MLflow:", mlflow.get_tracking_uri())
PYTHON

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF

echo ""
echo "🎉 Deployment complete! Enjoy your ML Platform!"
echo ""
