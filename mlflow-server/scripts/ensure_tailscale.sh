#!/bin/bash
# Ensure Tailscale is running and MLflow is accessible
# Run this on system startup if needed

set -e

echo "🔍 Checking Tailscale status..."

# Check if tailscaled is running
if ! systemctl is-active --quiet tailscaled; then
    echo "⚠️  Tailscaled not running, starting..."
    sudo systemctl start tailscaled
    sleep 3
fi

# Check if we're authenticated
if ! tailscale status &>/dev/null; then
    echo "❌ Tailscale not authenticated"
    echo "   Run: sudo tailscale up"
    exit 1
fi

TAILSCALE_IP=$(tailscale ip -4)
echo "✅ Tailscale connected: $TAILSCALE_IP"

# Verify MLflow is accessible via Tailscale
echo ""
echo "🧪 Testing MLflow accessibility..."

if curl -sf "http://$TAILSCALE_IP:8080/health" > /dev/null; then
    echo "✅ MLflow accessible via Tailscale"
    echo "   http://$TAILSCALE_IP:8080"
else
    echo "⚠️  MLflow not accessible yet, checking docker..."
    cd /home/axelofwar/Desktop/Projects/mlflow-server

    if ! docker ps | grep -q mlflow-server; then
        echo "🚀 Starting MLflow containers..."
        if ! groups | grep -q docker; then
            exec sg docker "$0 $@"
        fi
        docker compose up -d
        sleep 20
    fi

    echo "✅ MLflow should be accessible now"
fi

echo ""
echo "📋 Access Information:"
echo "   Tailscale IP:  http://$TAILSCALE_IP:8080"
echo "   Local IP:      http://$(hostname -I | awk '{print $1}'):8080"
echo ""
