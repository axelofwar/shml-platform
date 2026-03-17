#!/bin/bash
#
# MLflow Containerized Deployment Script
# One-command setup for production-ready MLflow server
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Banner
cat << "EOF"
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║       MLflow Production Deployment (Containerized)          ║
║       Privacy-Focused | Auto-Compression | Schema Validation║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
EOF
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    log_error "Please run as regular user, not root"
    exit 1
fi

# Check Docker installation
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed. Install Docker first:"
    echo "  curl -fsSL https://get.docker.com | sh"
    echo "  sudo usermod -aG docker $USER"
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    log_error "Docker Compose is not installed or not accessible"
    exit 1
fi

log_success "Docker and Docker Compose found"

# Create directory structure
log_info "Creating directory structure..."
mkdir -p data/{postgres,mlflow/{artifacts,mlruns},redis,prometheus,grafana}
mkdir -p backups/{postgres,artifacts}
mkdir -p logs/{mlflow,nginx}
mkdir -p secrets
mkdir -p config/schema
mkdir -p docker/mlflow/{plugins,scripts}
mkdir -p docker/nginx/{conf.d,ssl}
mkdir -p docker/grafana/{dashboards,datasources}

log_success "Directory structure created"

# Generate secrets
log_info "Generating secrets..."

if [ ! -f secrets/db_password.txt ]; then
    openssl rand -base64 32 > secrets/db_password.txt
    chmod 600 secrets/db_password.txt
    log_success "Generated database password"
else
    log_warning "Database password already exists"
fi

if [ ! -f secrets/grafana_password.txt ]; then
    openssl rand -base64 24 > secrets/grafana_password.txt
    chmod 600 secrets/grafana_password.txt
    log_success "Generated Grafana password"
else
    log_warning "Grafana password already exists"
fi

# Create .env file
log_info "Creating environment configuration..."
if [ ! -f .env ]; then
    cat > .env << EOF
# MLflow Configuration
MLFLOW_TRACKING_URI=http://localhost:8080
DB_PASSWORD=$(cat secrets/db_password.txt)

# Deployment settings
COMPOSE_PROJECT_NAME=mlflow-production
COMPOSE_FILE=deploy/compose/docker-compose.yml

# Performance settings (optimized for 24-core system)
POSTGRES_MAX_CONNECTIONS=100
MLFLOW_WORKERS=8
MLFLOW_WORKER_CONNECTIONS=2000
MLFLOW_WORKER_TIMEOUT=3600
REDIS_MAXMEMORY=512mb

# Backup retention (configurable)
BACKUP_RETENTION_DAYS=90           # Dev/staging: 90 days
BACKUP_RETENTION_PRODUCTION=0      # Production: forever (0 = no auto-delete)
EOF
    chmod 600 .env
    log_success "Environment file created"
else
    log_warning "Environment file already exists"
fi

# Set permissions
log_info "Setting permissions..."
chmod -R 755 data logs backups
chmod 700 secrets
log_success "Permissions configured"

# Check for existing deployment
if docker compose ps | grep -q "Up"; then
    log_warning "Existing deployment found"
    read -p "Stop and redeploy? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Stopping existing deployment..."
        docker compose down
    else
        log_info "Keeping existing deployment"
        exit 0
    fi
fi

# Build and start containers
log_info "Building Docker images..."
docker compose build --no-cache

log_info "Starting services..."
docker compose up -d

# Wait for services to be healthy
log_info "Waiting for services to start..."
sleep 10

# Check service health
check_service() {
    local service=$1
    local max_wait=60
    local waited=0

    log_info "Checking $service..."
    while [ $waited -lt $max_wait ]; do
        if docker compose ps $service | grep -q "healthy\|Up"; then
            log_success "$service is healthy"
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done

    log_error "$service failed to start"
    return 1
}

check_service "postgres"
check_service "redis"
check_service "mlflow"
check_service "nginx"

# Get Tailscale IP if available
TAILSCALE_IP=""
if command -v tailscale &> /dev/null && tailscale status &> /dev/null 2>&1; then
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
fi

# Display deployment information
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                 Deployment Complete!                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Access URLs:"
echo "  MLflow UI (HTTP):    http://localhost:8080"
if [ -n "$TAILSCALE_IP" ]; then
echo "  MLflow UI (VPN):     http://$TAILSCALE_IP:8080"
fi
echo "  Grafana:             http://localhost:3000"
echo "  Adminer (DB):        http://localhost:8081"
echo ""
echo "🔐 Credentials:"
echo "  Database Password:   $(cat secrets/db_password.txt)"
echo "  Grafana User:        admin"
echo "  Grafana Password:    $(cat secrets/grafana_password.txt)"
echo ""
echo "📁 Data Persistence:"
echo "  PostgreSQL:          ./data/postgres/"
echo "  Artifacts:           ./data/mlflow/artifacts/"
echo "  Backups:             ./backups/"
echo ""
echo "🔄 Useful Commands:"
echo "  View logs:           docker compose logs -f [service]"
echo "  Stop services:       docker compose stop"
echo "  Start services:      docker compose start"
echo "  Restart:             docker compose restart [service]"
echo "  Full cleanup:        docker compose down -v"
echo ""
echo "📚 Documentation:"
echo "  Deployment Guide:    ./DEPLOYMENT.md"
echo "  Schema Validation:   ./SCHEMA_GUIDE.md"
echo "  API Reference:       http://localhost:8080/api/2.0/mlflow/..."
echo ""
echo "🧪 Test Connection:"
echo "  curl http://localhost:8080/health"
echo ""

# Save deployment info
cat > DEPLOYMENT_INFO.txt << EOF
MLflow Containerized Deployment
Deployed: $(date)
Version: MLflow $(docker compose exec mlflow mlflow --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' || echo "2.17.2")

Access:
- MLflow UI: http://localhost:8080
$([ -n "$TAILSCALE_IP" ] && echo "- Tailscale VPN: http://$TAILSCALE_IP:8080")
- Grafana: http://localhost:3000
- Adminer: http://localhost:8081

Credentials stored in:
- secrets/db_password.txt
- secrets/grafana_password.txt

Data Locations:
- PostgreSQL: $(pwd)/data/postgres/
- Artifacts: $(pwd)/data/mlflow/artifacts/
- Backups: $(pwd)/backups/

Container Status:
$(docker compose ps)
EOF

log_success "Deployment information saved to DEPLOYMENT_INFO.txt"
echo ""
log_info "Your MLflow server is ready! 🚀"
