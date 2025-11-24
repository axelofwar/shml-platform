#!/bin/bash
# Enable OAuth authentication in Ray Compute API and MLflow Server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
BACKUP_FILE="${COMPOSE_FILE}.backup.$(date +%Y%m%d_%H%M%S)"

echo "============================================"
echo "  Enable OAuth for Ray Compute & MLflow"
echo "============================================"
echo

# Check if OAuth is already configured
if grep -q "server_v2:app" "$COMPOSE_FILE"; then
    echo "✓ OAuth is already enabled (using server_v2.py)"
    echo
    read -p "Do you want to restart services to apply changes? (yes/no): " restart
    if [ "$restart" = "yes" ]; then
        echo "Restarting services..."
        ./restart_all.sh
    fi
    exit 0
fi

echo "Creating backup: $BACKUP_FILE"
cp "$COMPOSE_FILE" "$BACKUP_FILE"

echo "Updating docker-compose.yml to enable OAuth..."

# Step 1: Update Ray Compute API to use server_v2.py
echo "  → Enabling OAuth in Ray Compute API (server_v2.py)..."
if grep -q 'CMD.*api\.server:app' "$COMPOSE_FILE"; then
    sed -i 's|CMD \["python", "-m", "uvicorn", "api.server:app"|CMD ["python", "-m", "uvicorn", "api.server_v2:app"|g' "$COMPOSE_FILE"
    echo "    ✓ Ray Compute API updated to use server_v2.py"
else
    echo "    ℹ Ray Compute API already using server_v2.py or different command"
fi

# Step 2: Add OAuth environment variables to ray-compute-api
echo "  → Adding OAuth environment variables to Ray Compute API..."
if ! grep -q "AUTHENTIK_URL" "$COMPOSE_FILE"; then
    # Find the line with "# Auth" in ray-compute-api section and add OAuth vars after it
    sed -i '/ray-compute-api:/,/^  [a-z]/ {
        /# Auth/a\
      \
      # OAuth Configuration\
      - OAUTH_ENABLED=${OAUTH_ENABLED:-false}\
      - AUTHENTIK_URL=${AUTHENTIK_INTERNAL_URL:-http://authentik-server:9000}\
      - AUTHENTIK_CLIENT_ID=${RAY_OAUTH_CLIENT_ID}\
      - AUTHENTIK_CLIENT_SECRET=${RAY_OAUTH_CLIENT_SECRET}
    }' "$COMPOSE_FILE"
    echo "    ✓ OAuth environment variables added to Ray Compute API"
else
    echo "    ℹ OAuth environment variables already present in Ray Compute API"
fi

# Step 3: Add OAuth environment variables to mlflow-api
echo "  → Adding OAuth environment variables to MLflow API..."
if ! grep -q "MLFLOW.*OAUTH" "$COMPOSE_FILE"; then
    # Find mlflow-api service and add OAuth vars
    sed -i '/mlflow-api:/,/^  [a-z]/ {
        /PYTHONUNBUFFERED/a\
      \
      # OAuth Configuration\
      - OAUTH_ENABLED=${OAUTH_ENABLED:-false}\
      - AUTHENTIK_URL=${AUTHENTIK_INTERNAL_URL:-http://authentik-server:9000}\
      - MLFLOW_OAUTH_CLIENT_ID=${MLFLOW_OAUTH_CLIENT_ID}\
      - MLFLOW_OAUTH_CLIENT_SECRET=${MLFLOW_OAUTH_CLIENT_SECRET}
    }' "$COMPOSE_FILE"
    echo "    ✓ OAuth environment variables added to MLflow API"
else
    echo "    ℹ OAuth environment variables already present in MLflow API"
fi

echo "✓ docker-compose.yml updated"

# Step 4: Update .env to enable OAuth
echo
echo "Enabling OAuth in .env file..."
if [ -f "$SCRIPT_DIR/.env" ]; then
    if ! grep -q "^OAUTH_ENABLED=" "$SCRIPT_DIR/.env"; then
        echo "" >> "$SCRIPT_DIR/.env"
        echo "# OAuth Configuration" >> "$SCRIPT_DIR/.env"
        echo "OAUTH_ENABLED=true" >> "$SCRIPT_DIR/.env"
        echo "    ✓ OAUTH_ENABLED=true added to .env"
    else
        sed -i 's/^OAUTH_ENABLED=.*/OAUTH_ENABLED=true/' "$SCRIPT_DIR/.env"
        echo "    ✓ OAUTH_ENABLED set to true in .env"
    fi
else
    echo "    ⚠ Warning: .env file not found"
fi

echo
echo "============================================"
echo "  OAuth Enabled Successfully!"
echo "============================================"
echo
echo "Changes made:"
echo "  ✓ Ray Compute API now uses server_v2.py (OAuth-enabled)"
echo "  ✓ OAuth environment variables added to Ray Compute API"
echo "  ✓ OAuth environment variables added to MLflow API"
echo "  ✓ OAUTH_ENABLED=true set in .env"
echo
echo "Backup saved to: $BACKUP_FILE"
echo
echo "Next steps:"
echo "  1. Review the changes: diff $COMPOSE_FILE $BACKUP_FILE"
echo "  2. Apply changes: ./restart_all.sh"
echo "  3. Verify OAuth: ./test_oauth.sh"
echo
echo "To test OAuth manually:"
echo "  curl -X POST http://localhost:9000/application/o/token/ \\"
echo "    -H 'Content-Type: application/x-www-form-urlencoded' \\"
echo "    -d 'grant_type=client_credentials' \\"
echo "    -d 'client_id=YOUR_CLIENT_ID' \\"
echo "    -d 'client_secret=YOUR_CLIENT_SECRET'"
echo
