#!/bin/bash
# Generate all secrets - simplified version without interactive prompts
# You can edit CREDENTIALS.txt after generation to see/change passwords

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==============================================="
echo "ML Platform - Secret Generation (Auto)"
echo "==============================================="
echo ""

# Generate passwords (tr removes newlines to avoid splitting)
AUTHENTIK_SECRET=$(openssl rand -base64 50 | tr -d '\n')
AUTHENTIK_DB_PASSWORD=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
AUTHENTIK_BOOTSTRAP_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)
GRAFANA_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)
SHARED_DB_PASSWORD=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
RAY_DB_PASSWORD=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
MLFLOW_DB_PASSWORD=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
API_SECRET=$(openssl rand -base64 50 | tr -d '\n')

# Get network IPs
LOCAL_IP=$(hostname -I | awk '{print $1}')
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "100.80.251.28")

echo "✓ Secrets generated"

# Function to update env variable using perl (handles all special chars)
update_env() {
    local file=$1
    local key=$2
    local value=$3

    # Escape value for perl
    local escaped=$(printf '%s' "$value" | perl -pe 's/([\\$@%])/\\$1/g')

    # Update or add
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        perl -i -pe "s|^${key}=.*|${key}=${escaped}|" "$file"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

# Update main .env
echo "Updating .env files..."
update_env ".env" "AUTHENTIK_SECRET_KEY" "$AUTHENTIK_SECRET"
update_env ".env" "AUTHENTIK_DB_PASSWORD" "$AUTHENTIK_DB_PASSWORD"
update_env ".env" "AUTHENTIK_BOOTSTRAP_PASSWORD" "$AUTHENTIK_BOOTSTRAP_PASSWORD"
update_env ".env" "GRAFANA_ADMIN_PASSWORD" "$GRAFANA_PASSWORD"
update_env ".env" "SHARED_DB_PASSWORD" "$SHARED_DB_PASSWORD"
update_env ".env" "TAILSCALE_IP" "$TAILSCALE_IP"

# Update ray_compute/.env
update_env "ray_compute/.env" "POSTGRES_PASSWORD" "$RAY_DB_PASSWORD"
update_env "ray_compute/.env" "AUTHENTIK_SECRET_KEY" "$AUTHENTIK_SECRET"
update_env "ray_compute/.env" "AUTHENTIK_DB_PASSWORD" "$AUTHENTIK_DB_PASSWORD"
update_env "ray_compute/.env" "GRAFANA_ADMIN_PASSWORD" "$GRAFANA_PASSWORD"
update_env "ray_compute/.env" "API_SECRET_KEY" "$API_SECRET"
update_env "ray_compute/.env" "TAILSCALE_IP" "$TAILSCALE_IP"

# Update mlflow-server/.env
update_env "mlflow-server/.env" "DB_PASSWORD" "$MLFLOW_DB_PASSWORD"
update_env "mlflow-server/.env" "SERVER_LOCAL_IP" "$LOCAL_IP"
update_env "mlflow-server/.env" "SERVER_TAILSCALE_IP" "$TAILSCALE_IP"
update_env "mlflow-server/.env" "CLIENT_IP" "$LOCAL_IP"
BACKEND_URI="postgresql://mlflow:${MLFLOW_DB_PASSWORD}@postgres:5432/mlflow_db"
update_env "mlflow-server/.env" "MLFLOW_BACKEND_STORE_URI" "$BACKEND_URI"

echo "✓ Environment files updated"

# Create secrets directory
mkdir -p secrets
echo "$MLFLOW_DB_PASSWORD" > secrets/db_password.txt
echo "$RAY_DB_PASSWORD" > secrets/ray_db_password.txt
echo "$AUTHENTIK_DB_PASSWORD" > secrets/authentik_db_password.txt
chmod 600 secrets/*

# Save credentials
cat > CREDENTIALS.txt << EOF
ML Platform Credentials
Generated: $(date)
===============================================

Network Configuration:
  Local IP: ${LOCAL_IP}
  Tailscale IP: ${TAILSCALE_IP}

Database Passwords:
  MLflow DB Password: ${MLFLOW_DB_PASSWORD}
  Ray DB Password: ${RAY_DB_PASSWORD}
  Authentik DB Password: ${AUTHENTIK_DB_PASSWORD}

Grafana Dashboard:
  URL: http://localhost/grafana/ or http://${TAILSCALE_IP}/grafana/
  Username: admin
  Password: ${GRAFANA_PASSWORD}

Ray Grafana:
  URL: http://localhost/ray-grafana/ or http://${TAILSCALE_IP}/ray-grafana/
  Username: admin
  Password: ${GRAFANA_PASSWORD}

Authentik Admin (OAuth):
  URL: http://localhost:9000/ or http://${TAILSCALE_IP}:9000/
  Username: akadmin
  Bootstrap Password: ${AUTHENTIK_BOOTSTRAP_PASSWORD}
  Note: CHANGE PASSWORD AFTER FIRST LOGIN!

MLflow UI:
  URL: http://localhost/mlflow/ or http://${TAILSCALE_IP}/mlflow/

Ray Dashboard:
  URL: http://localhost/ray/ or http://${TAILSCALE_IP}/ray/

Traefik Dashboard:
  URL: http://localhost:8090/ or http://${TAILSCALE_IP}:8090/

Secret Keys:
  Authentik Secret: ${AUTHENTIK_SECRET}
  API Secret: ${API_SECRET}

Database Connection Strings:
  MLflow: postgresql://mlflow:${MLFLOW_DB_PASSWORD}@localhost:5432/mlflow_db
  Ray: postgresql://ray_compute:${RAY_DB_PASSWORD}@localhost:5433/ray_compute
  Authentik: postgresql://authentik:${AUTHENTIK_DB_PASSWORD}@localhost:5434/authentik

⚠️  SECURITY NOTES:
  1. Keep this file secure - contains all passwords
  2. Never commit to git
  3. Change Authentik password after first login
  4. Backup securely

EOF

chmod 600 CREDENTIALS.txt

echo ""
echo "==============================================="
echo "✓ Setup Complete!"
echo "==============================================="
echo ""
echo "Credentials saved to: CREDENTIALS.txt"
echo ""
echo "Next step:"
echo "  sudo ./start_all_safe.sh"
echo ""
