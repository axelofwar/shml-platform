#!/bin/bash
# Display all service credentials in a formatted view
# Usage: ./show_credentials.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREDS_FILE="${SCRIPT_DIR}/.env.credentials"

if [ ! -f "$CREDS_FILE" ]; then
    echo "❌ Error: .env.credentials not found"
    exit 1
fi

# Source credentials
source "$CREDS_FILE"

cat << 'EOF'

╔═══════════════════════════════════════════════════════════════╗
║          🔐 MLflow Production - Service Credentials          ║
╚═══════════════════════════════════════════════════════════════╝

EOF

echo "📊 MLflow Tracking Server"
echo "   URL:      $MLFLOW_URL"
echo "   Auth:     $MLFLOW_AUTH"
echo ""

echo "🗄️  PostgreSQL Database"
echo "   URL:      $ADMINER_URL"
echo "   Host:     $POSTGRES_HOST"
echo "   Port:     $POSTGRES_PORT"
echo "   User:     $POSTGRES_USER"
echo "   Password: $POSTGRES_PASSWORD"
echo "   Database: $POSTGRES_DB"
echo ""

echo "📈 Grafana Monitoring"
echo "   URL:      $GRAFANA_URL"
echo "   User:     $GRAFANA_USER"
echo "   Password: $GRAFANA_PASSWORD"
echo ""

echo "💾 Adminer Database UI"
echo "   URL:      $ADMINER_URL"
echo "   System:   $ADMINER_SYSTEM"
echo "   Server:   $ADMINER_SERVER"
echo "   User:     $ADMINER_USERNAME"
echo "   Password: $ADMINER_PASSWORD"
echo "   Database: $ADMINER_DATABASE"
echo ""

echo "📊 Prometheus Metrics"
echo "   URL:      $PROMETHEUS_URL"
echo ""

echo "🔌 Quick Connect Commands:"
echo ""
echo "   # Load credentials in shell"
echo "   source load_credentials.sh"
echo ""
echo "   # Connect with psql"
echo "   PGPASSWORD='$POSTGRES_PASSWORD' psql -h localhost -U $POSTGRES_USER -d $POSTGRES_DB"
echo ""
echo "   # Use in Python"
echo "   import mlflow"
echo "   mlflow.set_tracking_uri('$MLFLOW_TRACKING_URI')"
echo ""

cat << 'EOF'
╚═══════════════════════════════════════════════════════════════╝

EOF
