#!/bin/bash
# Ray Cluster Installation with ML Libraries
# For PyTorch, YOLO, and MLflow integration

set -e

echo "================================================"
echo "Ray Cluster Installation"
echo "================================================"

# Check if Ray is already installed
if python3 -c "import ray; print(f'Ray version: {ray.__version__}')" 2>/dev/null; then
    echo "✓ Ray already installed"
    python3 -c "import ray; print(f'Ray version: {ray.__version__}')"
else
    echo "Installing Ray and dependencies..."
    
    # Install PyTorch first with CUDA 11.8 support
    pip3 install -U torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
    
    # Install Ray with all ML components (latest stable)
    pip3 install -U \
        "ray[default,data,train,tune,serve]" \
        ultralytics \
        opencv-python-headless \
        pandas \
        scikit-learn \
        xgboost \
        mlflow \
        fastapi \
        uvicorn[standard] \
        pydantic \
        python-multipart \
        aiofiles \
        psutil \
        gputil
    
    echo "✓ Ray and ML libraries installed"
fi

# Verify installations
echo ""
echo "Verifying installations..."
python3 -c "
import ray
import torch
import ultralytics
import mlflow
print(f'✓ Ray version: {ray.__version__}')
print(f'✓ PyTorch version: {torch.__version__}')
print(f'✓ CUDA available: {torch.cuda.is_available()}')
print(f'✓ CUDA version: {torch.version.cuda if torch.cuda.is_available() else \"N/A\"}')
print(f'✓ Ultralytics (YOLO) version: {ultralytics.__version__}')
print(f'✓ MLflow version: {mlflow.__version__}')
"

echo ""
echo "================================================"
echo "Creating Ray working directories..."
echo "================================================"

# Create Ray directories
sudo mkdir -p /opt/ray
sudo mkdir -p /opt/ray/tmp
sudo mkdir -p /opt/ray/logs
sudo mkdir -p /opt/ray/jobs
sudo chown -R $USER:$USER /opt/ray

echo "✓ Created /opt/ray directories"

# Create Ray configuration
cat > /opt/ray/ray_config.yaml <<'EOF'
# Ray Cluster Configuration for ML Workloads
# RTX 2070 + AMD Ryzen 9 3900X

cluster_name: mlflow-compute

max_workers: 4

# Resource definitions
available_node_types:
  ray.head.default:
    resources:
      CPU: 4  # Reserved for head node
      memory: 4294967296  # 4GB
    node_config: {}
  
  ray.worker.gpu:
    min_workers: 0
    max_workers: 1
    resources:
      CPU: 8
      memory: 8589934592  # 8GB
      GPU: 1  # RTX 2070
    node_config:
      docker:
        image: "mlflow-compute-gpu:latest"
        run_options:
          - "--gpus=all"
          - "--shm-size=4gb"
  
  ray.worker.cpu:
    min_workers: 0
    max_workers: 2
    resources:
      CPU: 6
      memory: 4294967296  # 4GB
    node_config:
      docker:
        image: "mlflow-compute-cpu:latest"

# Autoscaling
autoscaling_mode: default
idle_timeout_minutes: 10

# Head node
head_node_type: ray.head.default

# Setup commands
head_setup_commands:
  - pip3 install -U ray[default] torch ultralytics mlflow

worker_setup_commands:
  - pip3 install -U ray[default] torch ultralytics mlflow
EOF

echo "✓ Created Ray configuration"

echo ""
echo "================================================"
echo "Installation Complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "  1. Build Docker images: cd ../docker && ./build_images.sh"
echo "  2. Start Ray cluster: ray start --head"
echo "  3. Deploy API server: cd ../api && ./start_api.sh"
echo ""
