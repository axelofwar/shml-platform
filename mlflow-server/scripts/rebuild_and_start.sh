#!/bin/bash
set -e

cd /opt/shml-platform/mlflow-server

# Ensure we're in docker group
if ! groups | grep -q docker; then
    exec sg docker "$0" "$@"
fi
echo "🔨 Rebuilding MLflow container..."
docker compose build mlflow

echo ""
echo "🚀 Starting MLflow server..."
docker compose up -d mlflow

echo ""
echo "⏳ Waiting for server to start..."
sleep 25

echo ""
echo "📋 Checking startup logs..."
docker logs mlflow-server --tail 50

echo ""
echo "🧪 Testing experiments..."
curl -s -X POST http://localhost:8080/api/2.0/mlflow/experiments/search \
  -H "Content-Type: application/json" \
  -d '{"max_results": 100}' | python3 -m json.tool

echo ""
echo "✅ Deployment complete!"
