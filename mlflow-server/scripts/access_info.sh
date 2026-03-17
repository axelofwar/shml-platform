#!/bin/bash
# Quick access info for MLflow server

set -e

# Get IPs
LOCAL_IP=$(hostname -I | awk '{print $1}')
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "Not connected")
TAILSCALE_HOST=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['Self']['DNSName'])" 2>/dev/null || echo "")

echo "╔════════════════════════════════════════════════════════╗"
echo "║         MLflow Server Access Information              ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "🌐 Local Network (same WiFi):"
echo "   http://$LOCAL_IP:8080"
echo ""

if [ "$TAILSCALE_IP" != "Not connected" ]; then
    echo "🔒 Tailscale VPN (access from anywhere):"
    echo "   http://$TAILSCALE_IP:8080"
    if [ -n "$TAILSCALE_HOST" ]; then
        echo "   http://$TAILSCALE_HOST:8080"
    fi
    echo ""
    echo "✅ Tailscale is connected!"
else
    echo "⚠️  Tailscale not connected"
    echo "   Run: sudo tailscale up"
fi

echo ""
echo "📱 On your phone/tablet:"
echo "   1. Install Tailscale app"
echo "   2. Log in with same account"
echo "   3. Access: http://$TAILSCALE_IP:8080"
echo ""
echo "💻 On remote machines:"
echo "   export MLFLOW_TRACKING_URI=\"http://$TAILSCALE_IP:8080\""
echo ""
echo "🔧 Endpoints:"
echo "   Web UI:        http://$TAILSCALE_IP:8080"
echo "   REST API:      http://$TAILSCALE_IP:8080/api/2.0/mlflow/*"
echo "   Health Check:  http://$TAILSCALE_IP:8080/health"
echo "   Grafana:       http://$TAILSCALE_IP:3000"
echo "   Adminer:       http://$TAILSCALE_IP:8081"
echo ""
