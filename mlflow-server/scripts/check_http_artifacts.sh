#!/bin/bash
# Check if MLflow server has HTTP artifact proxying enabled
# Run from training machine

echo "============================================================"
echo "MLflow Server - HTTP Artifact Proxy Check"
echo "============================================================"

MLFLOW_URI="http://<SERVER_IP>:5000"

echo -e "\n1. Testing server connectivity..."
if curl -s "$MLFLOW_URI/health" | grep -q "OK"; then
    echo "   ✅ Server responding"
else
    echo "   ❌ Server not responding"
    exit 1
fi

echo -e "\n2. Checking artifact proxy capability..."
# Try to get server info
RESPONSE=$(curl -s "$MLFLOW_URI/api/2.0/mlflow/experiments/list" 2>&1)
if echo "$RESPONSE" | grep -q "experiment"; then
    echo "   ✅ API responding"
else
    echo "   ⚠️  API response unclear"
fi

echo -e "\n3. Testing artifact upload (small file)..."
export MLFLOW_TRACKING_URI="$MLFLOW_URI"

python3 << 'EOF'
import mlflow
import tempfile
import os

mlflow.set_experiment("pii-pro-model-registry")

try:
    with mlflow.start_run(run_name="http_artifact_test") as run:
        # Log a small test file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("HTTP artifact upload test\n")
            test_file = f.name
        
        mlflow.log_artifact(test_file, "http_test")
        os.unlink(test_file)
        
        print("   ✅ HTTP artifact upload successful!")
        print(f"   Run ID: {run.info.run_id}")
        print(f"   Artifact URI: {run.info.artifact_uri}")
        
        # Check if it's using HTTP proxying or direct file access
        if run.info.artifact_uri.startswith("file://"):
            print("   ⚠️  Using direct file:// access (need --serve-artifacts)")
            print("   Run setup_http_artifacts.sh on server to enable HTTP proxying")
            exit(1)
        elif run.info.artifact_uri.startswith("http://") or run.info.artifact_uri.startswith("mlflow-artifacts://"):
            print("   ✅ Using HTTP proxied artifacts")
        
except PermissionError as e:
    print(f"   ❌ Permission error: {e}")
    print("   Server needs --serve-artifacts flag")
    print("   Run setup_http_artifacts.sh on MLflow server")
    exit(1)
except Exception as e:
    print(f"   ❌ Error: {e}")
    exit(1)
EOF

if [ $? -eq 0 ]; then
    echo -e "\n============================================================"
    echo "✅ HTTP Artifact Proxying is ENABLED"
    echo "============================================================"
    echo "Server is correctly configured for HTTP artifact uploads"
else
    echo -e "\n============================================================"
    echo "❌ HTTP Artifact Proxying is NOT ENABLED"
    echo "============================================================"
    echo ""
    echo "On MLflow server (<SERVER_IP>), run:"
    echo "  bash setup_http_artifacts.sh"
    echo ""
    echo "This will enable --serve-artifacts flag for HTTP proxying"
fi
