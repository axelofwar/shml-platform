#!/bin/bash
# GPU Monitoring Verification Script

echo "=== GPU Monitoring Setup Verification ==="
echo ""

# 1. Check DCGM Exporter
echo "1. DCGM Exporter Status:"
if sudo docker ps --filter name=dcgm-exporter --format "{{.Status}}" | grep -q "Up"; then
    echo "   ✓ DCGM Exporter running"
    
    # Check metrics endpoint
    if curl -s http://localhost:9400/metrics | grep -q "DCGM_FI_DEV_GPU_UTIL"; then
        echo "   ✓ Metrics endpoint accessible"
        
        # Show GPU info
        echo ""
        echo "   Detected GPUs:"
        curl -s http://localhost:9400/metrics | grep "DCGM_FI_DEV_GPU_TEMP{" | sed 's/.*modelName="\([^"]*\)".*/     - \1/' | sort -u
    else
        echo "   ✗ Metrics endpoint not responding"
    fi
else
    echo "   ✗ DCGM Exporter not running"
fi
echo ""

# 2. Check Prometheus scraping
echo "2. Prometheus Integration:"
if sudo docker exec global-prometheus wget -qO- 'http://localhost:9090/api/v1/targets' 2>/dev/null | grep -q "dcgm-exporter"; then
    echo "   ✓ DCGM target configured in Prometheus"
    
    # Test query
    if sudo docker exec global-prometheus wget -qO- 'http://localhost:9090/api/v1/query?query=DCGM_FI_DEV_GPU_UTIL' 2>/dev/null | grep -q '"status":"success"'; then
        echo "   ✓ GPU metrics queryable in Prometheus"
    else
        echo "   ⚠ GPU metrics not yet available (may need 30-60 seconds)"
    fi
else
    echo "   ✗ DCGM target not found in Prometheus"
fi
echo ""

# 3. Check Grafana dashboard
echo "3. Grafana Dashboard:"
if sudo docker exec unified-grafana test -f /var/lib/grafana/dashboards/platform/gpu-monitoring.json; then
    echo "   ✓ GPU monitoring dashboard exists"
    echo "   ✓ Location: Platform → GPU Monitoring"
else
    echo "   ✗ GPU monitoring dashboard not found"
fi
echo ""

# 4. Check Tailscale access
echo "4. Remote Access:"
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null)
if [ -n "$TAILSCALE_IP" ]; then
    echo "   ✓ Tailscale configured: $TAILSCALE_IP"
    
    if curl -s -o /dev/null -w "%{http_code}" "http://$TAILSCALE_IP/grafana/" | grep -q "302\|200"; then
        echo "   ✓ Grafana accessible via Tailscale"
        echo ""
        echo "   Access URLs:"
        echo "   - Grafana: http://$TAILSCALE_IP/grafana/"
        echo "   - MLflow:  http://$TAILSCALE_IP/mlflow/"
        echo "   - Ray:     http://$TAILSCALE_IP/ray/"
    else
        echo "   ⚠ Grafana not responding via Tailscale"
    fi
else
    echo "   ⚠ Tailscale not configured"
fi
echo ""

echo "=== Verification Complete ==="
