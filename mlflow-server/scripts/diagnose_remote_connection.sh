#!/bin/bash
# Remote Machine MLflow Diagnostic Script
# Run this on the remote machine to diagnose connection issues

echo "🔍 MLflow Remote Connection Diagnostic"
echo "========================================"
echo ""

# Check environment
echo "1. Environment Configuration:"
echo "   MLFLOW_TRACKING_URI: ${MLFLOW_TRACKING_URI:-Not set}"
echo ""

# Prompt for server URL if not set
if [ -z "$MLFLOW_TRACKING_URI" ]; then
    read -p "Enter MLflow server URL (e.g., http://SERVER_IP:8080): " SERVER_URL
    export MLFLOW_TRACKING_URI="$SERVER_URL"
fi

echo "2. Testing connectivity to: $MLFLOW_TRACKING_URI"
echo ""

# Test health endpoint
echo "   Health Check:"
if curl -sf "$MLFLOW_TRACKING_URI/health" > /dev/null 2>&1; then
    echo "   ✅ Server is reachable"
    SERVER_VERSION=$(curl -s "$MLFLOW_TRACKING_URI/version")
    echo "   Version: $SERVER_VERSION"
else
    echo "   ❌ Cannot reach server at $MLFLOW_TRACKING_URI"
    echo "   Please check:"
    echo "     - Server is running"
    echo "     - Network connectivity"
    echo "     - Firewall rules"
    echo "     - Correct IP address and port"
    exit 1
fi

echo ""
echo "3. Testing Experiments API:"
RESPONSE=$(curl -s -X POST "$MLFLOW_TRACKING_URI/api/2.0/mlflow/experiments/search" \
  -H "Content-Type: application/json" \
  -d '{"max_results": 100}')

if echo "$RESPONSE" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    echo "   ✅ API is working correctly"
    echo ""
    echo "   Experiments found:"
    python3 -c "
import sys, json
data = json.loads(sys.argv[1])
exps = data.get('experiments', [])
for exp in exps:
    exp_id = exp['experiment_id']
    name = exp['name']
    try:
        id_int = int(exp_id)
        status = '✅' if id_int <= 2147483647 else '⚠️  OUT OF RANGE'
    except:
        status = '⚠️  INVALID'
    print(f'     {exp_id}: {name} {status}')
" "$RESPONSE"
else
    echo "   ❌ API returned invalid response:"
    echo "$RESPONSE"
fi

echo ""
echo "4. Testing with Python MLflow Client:"
python3 << 'EOFPYTHON'
import os
import mlflow
from mlflow.tracking import MlflowClient

tracking_uri = os.environ.get('MLFLOW_TRACKING_URI')
print(f"   Connecting to: {tracking_uri}")

try:
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient()

    experiments = client.search_experiments()
    print(f"   ✅ Python client working: {len(experiments)} experiments found")

    # Check for problematic IDs
    for exp in experiments:
        exp_id = int(exp.experiment_id)
        if exp_id > 2147483647:
            print(f"   ⚠️  WARNING: Experiment '{exp.name}' has out-of-range ID: {exp_id}")

except Exception as e:
    print(f"   ❌ Python client error: {e}")
EOFPYTHON

echo ""
echo "5. Browser Cache Check:"
echo "   If you see errors in the Web UI but the tests above work:"
echo "   - Clear your browser cache (Ctrl+Shift+Del)"
echo "   - Try incognito/private mode"
echo "   - Hard refresh the page (Ctrl+Shift+R or Cmd+Shift+R)"
echo ""

echo "6. Recommendations:"
echo "   ✅ Use Python client for reliable access"
echo "   ✅ Clear browser cache if Web UI shows errors"
echo "   ✅ Verify MLFLOW_TRACKING_URI is set correctly"
echo ""
echo "========================================"
EOFPYTHON
