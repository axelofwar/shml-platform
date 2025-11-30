#!/bin/bash
# Ray Compute Enhanced Setup Script
# Sets up Auth, Observability, and Database

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "============================================================"
echo "Ray Compute Enhanced Setup"
echo "============================================================"
echo ""

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo "❌ Do not run this script as root"
   exit 1
fi

# Check prerequisites
echo "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || { echo "❌ Docker not installed"; exit 1; }
command -v docker-compose >/dev/null 2>&1 || command -v docker compose >/dev/null 2>&1 || { echo "❌ Docker Compose not installed"; exit 1; }
command -v psql >/dev/null 2>&1 || { echo "❌ PostgreSQL client not installed. Run: sudo apt install postgresql-client"; exit 1; }

echo "✅ Prerequisites met"
echo ""

# Create .env if not exists
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    
    # Generate random passwords
    DB_PASSWORD=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
    AUTHENTIK_SECRET=$(openssl rand -base64 50 | tr -dc 'a-zA-Z0-9' | head -c 50)
    AUTHENTIK_DB_PASSWORD=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
    API_SECRET=$(openssl rand -base64 50 | tr -dc 'a-zA-Z0-9' | head -c 50)
    GRAFANA_PASSWORD=$(openssl rand -base64 16 | tr -dc 'a-zA-Z0-9' | head -c 16)
    NTFY_ID=$(openssl rand -hex 8)
    
    # Update .env
    sed -i "s/POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$DB_PASSWORD/" .env
    sed -i "s/AUTHENTIK_SECRET_KEY=.*/AUTHENTIK_SECRET_KEY=$AUTHENTIK_SECRET/" .env
    sed -i "s/AUTHENTIK_DB_PASSWORD=.*/AUTHENTIK_DB_PASSWORD=$AUTHENTIK_DB_PASSWORD/" .env
    sed -i "s/API_SECRET_KEY=.*/API_SECRET_KEY=$API_SECRET/" .env
    sed -i "s/GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$GRAFANA_PASSWORD/" .env
    sed -i "s/NTFY_ADMIN_TOPIC=.*/NTFY_ADMIN_TOPIC=ray-compute-admin-$NTFY_ID/" .env
    sed -i "s/NTFY_USER_TOPIC=.*/NTFY_USER_TOPIC=ray-compute-jobs-$NTFY_ID/" .env
    sed -i "s/NTFY_SYSTEM_TOPIC=.*/NTFY_SYSTEM_TOPIC=ray-compute-system-$NTFY_ID/" .env
    
    echo "✅ Generated .env with random passwords"
    echo "⚠️  IMPORTANT: Save these credentials!"
    echo ""
    echo "Database Password: $DB_PASSWORD"
    echo "Grafana Password: $GRAFANA_PASSWORD"
    echo "ntfy Topic ID: $NTFY_ID"
    echo ""
    echo "Subscribe to notifications:"
    echo "  Admin: https://ntfy.sh/ray-compute-admin-$NTFY_ID"
    echo "  Jobs: https://ntfy.sh/ray-compute-jobs-$NTFY_ID"
    echo "  System: https://ntfy.sh/ray-compute-system-$NTFY_ID"
    echo ""
    read -p "Press Enter to continue..."
fi

# Source environment
set -a
source .env
set +a

echo "============================================================"
echo "Phase 1: Database Setup"
echo "============================================================"
echo ""

# Create Ray Compute database
echo "Setting up Ray Compute PostgreSQL database..."

# Check if database exists
if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw ray_compute; then
    echo "Database ray_compute already exists"
else
    echo "Creating database and user..."
    sudo -u postgres psql <<EOF
CREATE DATABASE ray_compute;
CREATE USER ray_compute WITH ENCRYPTED PASSWORD '$POSTGRES_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE ray_compute TO ray_compute;
EOF
    echo "✅ Database created"
fi

# Apply schema
echo "Applying database schema..."
export PGPASSWORD="$POSTGRES_PASSWORD"
psql -h localhost -U ray_compute -d ray_compute -f config/database_schema.sql
unset PGPASSWORD

echo "✅ Database schema applied"
echo ""

echo "============================================================"
echo "Phase 2: Authentication (Authentik)"
echo "============================================================"
echo ""

# Start Authentik
echo "Starting Authentik containers..."
docker-compose -f docker-compose.auth.yml up -d

echo "Waiting for Authentik to be ready (this may take 2-3 minutes)..."
timeout 180 bash -c 'until curl -s http://localhost:9000/if/flow/initial-setup/ > /dev/null; do sleep 5; done' || {
    echo "❌ Authentik failed to start within 3 minutes"
    echo "Check logs: docker-compose -f docker-compose.auth.yml logs"
    exit 1
}

echo "✅ Authentik is running"
echo ""
echo "🔧 MANUAL SETUP REQUIRED:"
echo "1. Open http://${TAILSCALE_IP:-localhost}:9000 (or http://localhost:9000)"
echo "2. Complete initial setup wizard:"
echo "   - Email: admin@raycompute.local"
echo "   - Password: (choose secure password)"
echo "3. Create OAuth Application:"
echo "   - Applications → Create"
echo "   - Name: Ray Compute API"
echo "   - Slug: ray-compute-api"
echo "   - Provider: Create new OAuth2/OpenID provider"
echo "   - Redirect URIs: http://${TAILSCALE_IP:-localhost}:8266/auth/callback"
echo "   - Client type: Confidential"
echo "4. Copy Client ID and Client Secret"
echo "5. Update .env:"
echo "   AUTHENTIK_CLIENT_ID=<your-client-id>"
echo "   AUTHENTIK_CLIENT_SECRET=<your-client-secret>"
echo ""
read -p "Press Enter when Authentik setup is complete..."

echo ""
echo "============================================================"
echo "Phase 3: Observability Stack"
echo "============================================================"
echo ""

# Start observability
echo "Starting Prometheus, Loki, and Grafana..."
docker-compose -f docker-compose.observability.yml up -d

echo "Waiting for Grafana to be ready..."
timeout 60 bash -c 'until curl -s http://localhost:3000/api/health > /dev/null; do sleep 3; done' || {
    echo "⚠️  Grafana may still be starting. Check: docker-compose -f docker-compose.observability.yml logs grafana"
}

echo "✅ Observability stack is running"
echo ""
echo "Access Dashboards:"
echo "  - Grafana: http://${TAILSCALE_IP:-localhost}:3000"
echo "    User: $GRAFANA_ADMIN_USER"
echo "    Pass: $GRAFANA_ADMIN_PASSWORD"
echo "  - Prometheus: http://${TAILSCALE_IP:-localhost}:9090"
echo "  - Loki: http://${TAILSCALE_IP:-localhost}:3100"
echo ""

echo "============================================================"
echo "Phase 4: Install Python Dependencies"
echo "============================================================"
echo ""

echo "Installing Python packages..."
pip3 install --user \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0 \
    python-jose[cryptography]==3.3.0 \
    passlib[bcrypt]==1.7.4 \
    python-multipart==0.0.6 \
    psycopg2-binary==2.9.9 \
    sqlalchemy==2.0.23 \
    alembic==1.13.0 \
    redis==5.0.1 \
    apprise==1.6.0 \
    prometheus-client==0.19.0 \
    py3nvml==0.2.7 \
    zstandard==0.22.0 \
    aiofiles==23.2.1

echo "✅ Python dependencies installed"
echo ""

echo "============================================================"
echo "Setup Complete!"
echo "============================================================"
echo ""
echo "Next Steps:"
echo "1. Configure notifications in config/notifications.conf"
echo "2. Subscribe to ntfy topics on your phone (see URLs above)"
echo "3. Start Ray Compute API:"
echo "   cd api && python3 server_v2.py"
echo ""
echo "Verify services:"
echo "  docker ps"
echo "  curl http://localhost:9000/-/health  # Authentik"
echo "  curl http://localhost:3000/api/health  # Grafana"
echo "  curl http://localhost:9090/-/healthy  # Prometheus"
echo ""
echo "Documentation:"
echo "  - AUTH_SETUP.md (OAuth configuration)"
echo "  - ADMIN_GUIDE.md (Admin operations)"
echo "  - USER_GUIDE.md (User guide)"
echo ""
echo "✨ Happy Computing!"
