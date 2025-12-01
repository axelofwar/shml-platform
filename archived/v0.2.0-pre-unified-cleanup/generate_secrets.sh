#!/bin/bash
# Generate all secrets and populate .env files
# This script creates secure random passwords for all platform services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}ML Platform - Secret Generation${NC}"
echo -e "${BLUE}===============================================${NC}"
echo ""

# Check if .env files exist
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  .env not found, copying from .env.example${NC}"
    cp .env.example .env
fi

if [ ! -f ray_compute/.env ]; then
    echo -e "${YELLOW}⚠️  ray_compute/.env not found, copying from .env.example${NC}"
    cp ray_compute/.env.example ray_compute/.env
fi

if [ ! -f mlflow-server/.env ]; then
    echo -e "${YELLOW}⚠️  mlflow-server/.env not found, copying from .env.example${NC}"
    cp mlflow-server/.env.example mlflow-server/.env
fi

echo -e "${GREEN}✓ Environment files ready${NC}"
echo ""

# Function to generate secure passwords
generate_password() {
    local length=$1
    openssl rand -base64 $length | tr -dc 'a-zA-Z0-9' | head -c $length
}

# Function to generate base64 secrets
generate_secret() {
    local length=$1
    openssl rand -base64 $length
}

# Function to prompt for password (generate or custom)
prompt_password() {
    local service_name=$1
    local default_length=$2
    local is_secret=${3:-false}

    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}${service_name}${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "Choose an option:"
    echo "  1) Generate random password (recommended)"
    echo "  2) Enter custom password"
    echo ""
    read -p "Selection [1]: " choice
    choice=${choice:-1}

    if [ "$choice" = "2" ]; then
        while true; do
            read -sp "Enter password: " password1
            echo ""
            read -sp "Confirm password: " password2
            echo ""
            if [ "$password1" = "$password2" ]; then
                if [ ${#password1} -lt 12 ]; then
                    echo -e "${RED}⚠️  Password too short (minimum 12 characters)${NC}"
                    continue
                fi
                echo "$password1"
                break
            else
                echo -e "${RED}⚠️  Passwords don't match, try again${NC}"
            fi
        done
    else
        if [ "$is_secret" = "true" ]; then
            generate_secret $default_length
        else
            generate_password $default_length
        fi
    fi
    echo ""
}

echo -e "${GREEN}Let's configure your credentials!${NC}"
echo -e "${GREEN}You can generate random passwords or set your own.${NC}"
echo ""
read -p "Press Enter to continue..."
echo ""

# Prompt for user-facing passwords
echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo -e "${BLUE}  User-Facing Credentials${NC}"
echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo ""

GRAFANA_PASSWORD=$(prompt_password "Grafana Dashboard Password (admin user)" 24)
AUTHENTIK_BOOTSTRAP_PASSWORD=$(prompt_password "Authentik Admin Password (akadmin user)\nNote: You can change this after first login" 24)

echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo -e "${BLUE}  Database & System Secrets${NC}"
echo -e "${BLUE}  (Auto-generating for security)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════${NC}"
echo ""

# Auto-generate system secrets
echo "Generating database passwords and system secrets..."
AUTHENTIK_SECRET=$(generate_secret 50)
AUTHENTIK_DB_PASSWORD=$(generate_password 32)
SHARED_DB_PASSWORD=$(generate_password 32)
RAY_DB_PASSWORD=$(generate_password 32)
MLFLOW_DB_PASSWORD=$(generate_password 32)
API_SECRET=$(generate_secret 50)

echo -e "${GREEN}✓ System secrets generated${NC}"
echo ""

# Get network IPs
LOCAL_IP=$(hostname -I | awk '{print $1}')
TAILSCALE_IP=$(ip addr show tailscale0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' || echo "NOT_CONFIGURED")

echo -e "${GREEN}✓ Secrets generated${NC}"
echo ""

# Function to safely update env variable (handles special characters)
update_env_var() {
    local file=$1
    local key=$2
    local value=$3

    # Create temporary file
    local temp_file="${file}.tmp"

    # Update or append the variable
    if grep -q "^${key}=" "$file"; then
        # Replace existing line
        awk -v key="$key" -v value="$value" '
            BEGIN { FS=OFS="=" }
            $1 == key { $2=value; found=1 }
            { print }
        ' "$file" > "$temp_file"
        mv "$temp_file" "$file"
    else
        # Append new line
        echo "${key}=${value}" >> "$file"
    fi
}

# Update main .env
echo -e "${BLUE}Updating main .env file...${NC}"
update_env_var ".env" "AUTHENTIK_SECRET_KEY" "${AUTHENTIK_SECRET}"
update_env_var ".env" "AUTHENTIK_DB_PASSWORD" "${AUTHENTIK_DB_PASSWORD}"
update_env_var ".env" "AUTHENTIK_BOOTSTRAP_PASSWORD" "${AUTHENTIK_BOOTSTRAP_PASSWORD}"
update_env_var ".env" "GRAFANA_ADMIN_PASSWORD" "${GRAFANA_PASSWORD}"
update_env_var ".env" "SHARED_DB_PASSWORD" "${SHARED_DB_PASSWORD}"
echo -e "${GREEN}✓ Main .env updated${NC}"

# Update ray_compute/.env
echo -e "${BLUE}Updating ray_compute/.env file...${NC}"
update_env_var "ray_compute/.env" "POSTGRES_PASSWORD" "${RAY_DB_PASSWORD}"
update_env_var "ray_compute/.env" "AUTHENTIK_SECRET_KEY" "${AUTHENTIK_SECRET}"
update_env_var "ray_compute/.env" "AUTHENTIK_DB_PASSWORD" "${AUTHENTIK_DB_PASSWORD}"
update_env_var "ray_compute/.env" "GRAFANA_ADMIN_PASSWORD" "${GRAFANA_PASSWORD}"
update_env_var "ray_compute/.env" "API_SECRET_KEY" "${API_SECRET}"
update_env_var "ray_compute/.env" "TAILSCALE_IP" "${TAILSCALE_IP}"

echo -e "${GREEN}✓ Ray Compute .env updated${NC}"

# Update mlflow-server/.env
echo -e "${BLUE}Updating mlflow-server/.env file...${NC}"
update_env_var "mlflow-server/.env" "DB_PASSWORD" "${MLFLOW_DB_PASSWORD}"
update_env_var "mlflow-server/.env" "SERVER_LOCAL_IP" "${LOCAL_IP}"
update_env_var "mlflow-server/.env" "SERVER_TAILSCALE_IP" "${TAILSCALE_IP}"

# Update backend store URI with actual password
BACKEND_STORE_URI="postgresql://mlflow:${MLFLOW_DB_PASSWORD}@postgres:5432/mlflow_db"
update_env_var "mlflow-server/.env" "MLFLOW_BACKEND_STORE_URI" "${BACKEND_STORE_URI}"

echo -e "${GREEN}✓ MLflow .env updated${NC}"

# Create secrets directory and save individual secrets
mkdir -p secrets
echo "${MLFLOW_DB_PASSWORD}" > secrets/db_password.txt
echo "${RAY_DB_PASSWORD}" > secrets/ray_db_password.txt
echo "${AUTHENTIK_DB_PASSWORD}" > secrets/authentik_db_password.txt
chmod 600 secrets/*
echo -e "${GREEN}✓ Secret files created in secrets/ directory${NC}"

echo ""
echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}🔐 Credentials Summary${NC}"
echo -e "${BLUE}===============================================${NC}"
echo ""

# Display credentials
echo -e "${GREEN}Network Configuration:${NC}"
echo "  Local IP: ${LOCAL_IP}"
echo "  Tailscale IP: ${TAILSCALE_IP}"
echo ""

echo -e "${GREEN}Database Passwords:${NC}"
echo "  MLflow DB Password: ${MLFLOW_DB_PASSWORD}"
echo "  Ray DB Password: ${RAY_DB_PASSWORD}"
echo "  Authentik DB Password: ${AUTHENTIK_DB_PASSWORD}"
echo ""

echo -e "${GREEN}Grafana Dashboard:${NC}"
echo "  URL: http://localhost/grafana/"
echo "  Username: admin"
echo "  Password: ${GRAFANA_PASSWORD}"
echo ""

echo -e "${GREEN}Authentik Admin (OAuth):${NC}"
echo "  URL: http://localhost:9000/"
echo "  Username: akadmin"
echo "  Bootstrap Password: ${AUTHENTIK_BOOTSTRAP_PASSWORD}"
echo "  Note: Change password after first login"
echo ""

echo -e "${GREEN}Secret Keys:${NC}"
echo "  Authentik Secret: ${AUTHENTIK_SECRET:0:20}..."
echo "  API Secret: ${API_SECRET:0:20}..."
echo ""

# Save credentials to a secure file
CREDENTIALS_FILE="CREDENTIALS.txt"
cat > "${CREDENTIALS_FILE}" << EOF
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

Command to view credentials:
  cat CREDENTIALS.txt

⚠️  IMPORTANT SECURITY NOTES:
  1. Keep this file secure - it contains all platform passwords
  2. Never commit CREDENTIALS.txt or .env files to git
  3. Change Authentik password after first login
  4. Consider using a password manager
  5. Backup this file to a secure location

EOF

chmod 600 "${CREDENTIALS_FILE}"

echo -e "${YELLOW}⚠️  IMPORTANT:${NC}"
echo "  1. All credentials saved to: ${CREDENTIALS_FILE}"
echo "  2. Backup this file to a secure location NOW"
echo "  3. Never commit .env or CREDENTIALS.txt to git"
echo "  4. Change Authentik password after first login"
echo ""

echo -e "${GREEN}===============================================${NC}"
echo -e "${GREEN}✓ Secret generation complete!${NC}"
echo -e "${GREEN}===============================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Review ${CREDENTIALS_FILE}"
echo "  2. Backup ${CREDENTIALS_FILE} securely"
echo "  3. Run: sudo ./start_all_safe.sh"
echo ""
