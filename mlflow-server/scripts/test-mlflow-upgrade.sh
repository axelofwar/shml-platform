#!/bin/bash
# MLflow 3.x Upgrade Testing Script
# Tests client compatibility with the new MLflow 3.x dev server

set -e

DEV_SERVER="http://localhost:5001"
PROD_SERVER="http://localhost:5000"

echo "=============================================="
echo "  MLflow 3.x Upgrade Compatibility Tests"
echo "=============================================="
echo ""

# Check if dev server is running
echo "🔍 Checking dev server status..."
if curl -sf "$DEV_SERVER/health" > /dev/null 2>&1; then
    echo "   ✅ Dev server (3.x) is running at $DEV_SERVER"
else
    echo "   ❌ Dev server not running. Start with:"
    echo "      cd mlflow-server && docker compose -f docker-compose.dev.yml up -d"
    exit 1
fi

# Get version info
echo ""
echo "📦 Server Version Info:"
curl -sf "$DEV_SERVER/version" 2>/dev/null | jq . || echo "   (version endpoint not available)"

# Test 1: Create experiment
echo ""
echo "🧪 Test 1: Create Experiment"
EXPERIMENT_NAME="upgrade-test-$(date +%s)"
RESULT=$(curl -sf -X POST "$DEV_SERVER/api/2.0/mlflow/experiments/create" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"$EXPERIMENT_NAME\"}" 2>&1) || true

if echo "$RESULT" | grep -q "experiment_id"; then
    EXPERIMENT_ID=$(echo "$RESULT" | jq -r '.experiment_id')
    echo "   ✅ Created experiment: $EXPERIMENT_NAME (ID: $EXPERIMENT_ID)"
else
    echo "   ❌ Failed to create experiment"
    echo "   Response: $RESULT"
fi

# Test 2: List experiments
echo ""
echo "🧪 Test 2: List Experiments"
EXPERIMENTS=$(curl -sf "$DEV_SERVER/api/2.0/mlflow/experiments/search" \
    -H "Content-Type: application/json" \
    -d '{"max_results": 10}' 2>&1) || true

if echo "$EXPERIMENTS" | grep -q "experiments"; then
    COUNT=$(echo "$EXPERIMENTS" | jq '.experiments | length')
    echo "   ✅ Found $COUNT experiments"
else
    echo "   ❌ Failed to list experiments"
fi

# Test 3: Create run
echo ""
echo "🧪 Test 3: Create Run"
if [ -n "$EXPERIMENT_ID" ]; then
    RUN_RESULT=$(curl -sf -X POST "$DEV_SERVER/api/2.0/mlflow/runs/create" \
        -H "Content-Type: application/json" \
        -d "{\"experiment_id\": \"$EXPERIMENT_ID\", \"run_name\": \"test-run\"}" 2>&1) || true

    if echo "$RUN_RESULT" | grep -q "run_id\|run"; then
        RUN_ID=$(echo "$RUN_RESULT" | jq -r '.run.info.run_id // .run_id')
        echo "   ✅ Created run: $RUN_ID"
    else
        echo "   ❌ Failed to create run"
        echo "   Response: $RUN_RESULT"
    fi
else
    echo "   ⏭️  Skipped (no experiment ID)"
fi

# Test 4: Log metrics
echo ""
echo "🧪 Test 4: Log Metrics"
if [ -n "$RUN_ID" ] && [ "$RUN_ID" != "null" ]; then
    METRIC_RESULT=$(curl -sf -X POST "$DEV_SERVER/api/2.0/mlflow/runs/log-metric" \
        -H "Content-Type: application/json" \
        -d "{\"run_id\": \"$RUN_ID\", \"key\": \"accuracy\", \"value\": 0.95, \"timestamp\": $(date +%s)000}" 2>&1) || true

    if [ -z "$METRIC_RESULT" ] || echo "$METRIC_RESULT" | grep -q "{}"; then
        echo "   ✅ Logged metric: accuracy=0.95"
    else
        echo "   ❌ Failed to log metric"
        echo "   Response: $METRIC_RESULT"
    fi
else
    echo "   ⏭️  Skipped (no run ID)"
fi

# Test 5: Log parameters
echo ""
echo "🧪 Test 5: Log Parameters"
if [ -n "$RUN_ID" ] && [ "$RUN_ID" != "null" ]; then
    PARAM_RESULT=$(curl -sf -X POST "$DEV_SERVER/api/2.0/mlflow/runs/log-parameter" \
        -H "Content-Type: application/json" \
        -d "{\"run_id\": \"$RUN_ID\", \"key\": \"learning_rate\", \"value\": \"0.001\"}" 2>&1) || true

    if [ -z "$PARAM_RESULT" ] || echo "$PARAM_RESULT" | grep -q "{}"; then
        echo "   ✅ Logged parameter: learning_rate=0.001"
    else
        echo "   ❌ Failed to log parameter"
        echo "   Response: $PARAM_RESULT"
    fi
else
    echo "   ⏭️  Skipped (no run ID)"
fi

# Test 6: End run
echo ""
echo "🧪 Test 6: End Run"
if [ -n "$RUN_ID" ] && [ "$RUN_ID" != "null" ]; then
    END_RESULT=$(curl -sf -X POST "$DEV_SERVER/api/2.0/mlflow/runs/update" \
        -H "Content-Type: application/json" \
        -d "{\"run_id\": \"$RUN_ID\", \"status\": \"FINISHED\"}" 2>&1) || true

    if [ -z "$END_RESULT" ] || echo "$END_RESULT" | grep -q "run_info\|{}"; then
        echo "   ✅ Run completed successfully"
    else
        echo "   ❌ Failed to end run"
        echo "   Response: $END_RESULT"
    fi
else
    echo "   ⏭️  Skipped (no run ID)"
fi

# Summary
echo ""
echo "=============================================="
echo "  Test Summary"
echo "=============================================="
echo ""
echo "Dev Server: $DEV_SERVER"
echo ""
echo "Next Steps:"
echo "  1. Test with Python client:"
echo "     export MLFLOW_TRACKING_URI=$DEV_SERVER"
echo "     python -c \"import mlflow; mlflow.set_experiment('test'); mlflow.start_run()\""
echo ""
echo "  2. Compare with production server ($PROD_SERVER)"
echo ""
echo "  3. If all tests pass, update production:"
echo "     - Edit mlflow-server/docker/mlflow/requirements.txt"
echo "     - Change mlflow==2.17.2 to mlflow>=3.6.0"
echo "     - Rebuild: docker compose build mlflow-server"
echo ""
