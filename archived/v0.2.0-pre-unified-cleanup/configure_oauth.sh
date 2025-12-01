#!/bin/bash
# OAuth Configuration Script for ML Platform
# This script helps configure OAuth credentials after setting up Authentik providers

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAY_SECRETS_DIR="$SCRIPT_DIR/ray_compute/secrets"
ENV_FILE="$SCRIPT_DIR/.env"

echo "============================================"
echo "  ML Platform OAuth Configuration"
echo "============================================"
echo

echo "This script will help you configure OAuth for Ray Compute and MLflow."
echo "You need to complete the Authentik setup first following: OAUTH_SETUP_GUIDE.md"
echo

# Function to prompt for input with default
prompt_with_default() {
    local prompt="$1"
    local default="$2"
    local value

    read -p "$prompt [$default]: " value
    echo "${value:-$default}"
}

# Function to prompt for secret
prompt_secret() {
    local prompt="$1"
    local value

    read -sp "$prompt: " value
    echo "$value"
}

echo "=== Step 1: Ray Compute OAuth Configuration ==="
echo
RAY_CLIENT_ID=$(prompt_with_default "Ray Compute OAuth Client ID" "")
if [ -z "$RAY_CLIENT_ID" ]; then
    echo "Error: Client ID is required"
    exit 1
fi

echo
RAY_CLIENT_SECRET=$(prompt_secret "Ray Compute OAuth Client Secret")
if [ -z "$RAY_CLIENT_SECRET" ]; then
    echo
    echo "Error: Client Secret is required"
    exit 1
fi

echo
echo

echo "=== Step 2: MLflow OAuth Configuration ==="
echo
MLFLOW_CLIENT_ID=$(prompt_with_default "MLflow OAuth Client ID" "")
if [ -z "$MLFLOW_CLIENT_ID" ]; then
    echo "Error: Client ID is required"
    exit 1
fi

echo
MLFLOW_CLIENT_SECRET=$(prompt_secret "MLflow OAuth Client Secret")
if [ -z "$MLFLOW_CLIENT_SECRET" ]; then
    echo
    echo "Error: Client Secret is required"
    exit 1
fi

echo
echo

echo "=== Step 3: Authentik Configuration ==="
echo
AUTHENTIK_BASE_URL=$(prompt_with_default "Authentik Base URL" "http://localhost:9000")
AUTHENTIK_INTERNAL_URL=$(prompt_with_default "Authentik Internal URL (for containers)" "http://authentik-server:9000")

echo
echo "=== Configuration Summary ==="
echo "Ray Compute Client ID: $RAY_CLIENT_ID"
echo "MLflow Client ID: $MLFLOW_CLIENT_ID"
echo "Authentik Base URL: $AUTHENTIK_BASE_URL"
echo "Authentik Internal URL: $AUTHENTIK_INTERNAL_URL"
echo

read -p "Do you want to save this configuration? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Configuration cancelled."
    exit 0
fi

# Create backup of existing .env if it exists
if [ -f "$ENV_FILE" ]; then
    BACKUP_FILE="${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    echo "Creating backup: $BACKUP_FILE"
    cp "$ENV_FILE" "$BACKUP_FILE"
fi

# Update or create .env file
echo
echo "Updating .env file..."

# Remove old OAuth entries if they exist
if [ -f "$ENV_FILE" ]; then
    sed -i.tmp '/^# OAuth Configuration/,/^$/d' "$ENV_FILE"
    rm -f "${ENV_FILE}.tmp"
fi

# Append new OAuth configuration
cat >> "$ENV_FILE" <<EOF

# OAuth Configuration
# Generated on $(date)

# Ray Compute OAuth
AUTHENTIK_OAUTH_CLIENT_ID=$RAY_CLIENT_ID
AUTHENTIK_OAUTH_CLIENT_SECRET=$RAY_CLIENT_SECRET
AUTHENTIK_OAUTH_SERVER_URL=${AUTHENTIK_INTERNAL_URL}/application/o/ray-compute/
AUTHENTIK_BASE_URL=$AUTHENTIK_BASE_URL

# MLflow OAuth
MLFLOW_OAUTH_CLIENT_ID=$MLFLOW_CLIENT_ID
MLFLOW_OAUTH_CLIENT_SECRET=$MLFLOW_CLIENT_SECRET
MLFLOW_OAUTH_SERVER_URL=${AUTHENTIK_INTERNAL_URL}/application/o/mlflow/

# OAuth Settings
OAUTH_ENABLED=true
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30
EOF

echo "✓ .env file updated"

# Create secrets files for Ray Compute
echo
echo "Creating secret files for Ray Compute..."

mkdir -p "$RAY_SECRETS_DIR"
echo -n "$RAY_CLIENT_SECRET" > "$RAY_SECRETS_DIR/oauth_client_secret.txt"
chmod 600 "$RAY_SECRETS_DIR/oauth_client_secret.txt"

echo "✓ Secret files created"

echo
echo "============================================"
echo "  Configuration Complete!"
echo "============================================"
echo
echo "Next steps:"
echo "1. Update docker-compose.yml to use server_v2.py (OAuth-enabled)"
echo "2. Restart services: ./restart_all.sh"
echo "3. Test OAuth authentication"
echo
echo "Configuration files updated:"
echo "  - $ENV_FILE"
echo "  - $RAY_SECRETS_DIR/oauth_client_secret.txt"
echo
echo "To enable OAuth in Ray Compute API, run:"
echo "  ./enable_oauth.sh"
echo
