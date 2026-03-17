#!/bin/bash
# Load credentials from .env.credentials into current shell
# Usage: source load_credentials.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREDS_FILE="${SCRIPT_DIR}/.env.credentials"

if [ -f "$CREDS_FILE" ]; then
    export $(grep -v '^#' "$CREDS_FILE" | grep -v '^$' | xargs)
    echo "✅ Credentials loaded from .env.credentials"
    echo ""
    echo "Available environment variables:"
    echo "  MLFLOW_TRACKING_URI=$MLFLOW_TRACKING_URI"
    echo "  DATABASE_URL=$DATABASE_URL"
    echo "  GRAFANA_URL=$GRAFANA_URL"
    echo "  ADMINER_URL=$ADMINER_URL"
    echo ""
    echo "PostgreSQL connection:"
    echo "  Host: $POSTGRES_HOST"
    echo "  User: $POSTGRES_USER"
    echo "  Database: $POSTGRES_DB"
else
    echo "❌ Error: .env.credentials not found at $CREDS_FILE"
    return 1
fi
