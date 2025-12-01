#!/bin/bash
#
# Setup NVIDIA MPS (Multi-Process Service) for GPU Sharing
# Allows multiple containers to use GPU simultaneously
# Required for: Ray workers, MLflow training, inference services
#

set -e

echo "================================================"
echo "NVIDIA MPS Setup for Multi-Service GPU Access"
echo "================================================"
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script requires root privileges"
    echo "Please run: sudo $0"
    exit 1
fi

# Check NVIDIA drivers
echo "1. Checking NVIDIA drivers..."
if ! nvidia-smi &>/dev/null; then
    echo "❌ NVIDIA drivers not found!"
    echo "Please install NVIDIA drivers first"
    exit 1
fi
echo "✓ NVIDIA drivers found"
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader

echo ""
echo "2. Checking NVIDIA Docker runtime..."
if ! docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null; then
    echo "❌ NVIDIA Docker runtime not working!"
    echo "Please install nvidia-docker2"
    exit 1
fi
echo "✓ NVIDIA Docker runtime configured"

echo ""
echo "3. Setting up MPS directories..."
MPS_PIPE_DIR="/tmp/nvidia-mps"
MPS_LOG_DIR="/tmp/nvidia-log"

mkdir -p "$MPS_PIPE_DIR"
mkdir -p "$MPS_LOG_DIR"
chmod 777 "$MPS_PIPE_DIR"
chmod 777 "$MPS_LOG_DIR"

echo "✓ MPS directories created:"
echo "  Pipe: $MPS_PIPE_DIR"
echo "  Logs: $MPS_LOG_DIR"

echo ""
echo "4. Configuring MPS settings..."

# Set MPS environment variables
export CUDA_MPS_PIPE_DIRECTORY="$MPS_PIPE_DIR"
export CUDA_MPS_LOG_DIRECTORY="$MPS_LOG_DIR"

# Stop any existing MPS daemon
echo "  Stopping existing MPS daemon..."
echo quit | nvidia-cuda-mps-control 2>/dev/null || true

# Start MPS control daemon
echo "  Starting MPS control daemon..."
nvidia-cuda-mps-control -d

# Check if MPS is running
sleep 2
if pgrep -f nvidia-cuda-mps > /dev/null; then
    echo "✓ MPS daemon started successfully"
else
    echo "⚠️  MPS daemon may not have started"
fi

echo ""
echo "5. Configuring MPS for multi-client access..."

# Allow multiple clients
echo "set_default_active_thread_percentage 50" | nvidia-cuda-mps-control || true

# Get MPS status
echo ""
echo "MPS Status:"
echo "get_server_list" | nvidia-cuda-mps-control

echo ""
echo "================================================"
echo "GPU Sharing Configuration"
echo "================================================"
echo ""

# Display GPU info
nvidia-smi --query-gpu=index,name,memory.total,compute_cap --format=csv,noheader | while read line; do
    echo "GPU: $line"
done

echo ""
echo "MPS Configuration:"
echo "  - Multiple processes can use GPU simultaneously"
echo "  - Each process gets ~50% thread allocation"
echo "  - Automatic GPU memory management"
echo "  - Suitable for: Training + Inference workloads"
echo ""

echo "================================================"
echo "Testing GPU Access"
echo "================================================"
echo ""

# Test GPU access from Docker
echo "Testing Docker GPU access with MPS..."
docker run --rm --gpus all \
    -e CUDA_MPS_PIPE_DIRECTORY="$MPS_PIPE_DIR" \
    -e CUDA_MPS_LOG_DIRECTORY="$MPS_LOG_DIR" \
    -v "$MPS_PIPE_DIR:$MPS_PIPE_DIR" \
    nvidia/cuda:11.8.0-base-ubuntu20.04 \
    nvidia-smi --query-gpu=name,utilization.gpu --format=csv,noheader

echo ""
echo "✓ GPU access test successful!"

echo ""
echo "================================================"
echo "MPS Setup Complete!"
echo "================================================"
echo ""
echo "Next Steps:"
echo "1. Start ML Platform services"
echo "2. Multiple containers can now share GPU"
echo "3. Monitor GPU usage: watch -n 1 nvidia-smi"
echo ""
echo "To stop MPS:"
echo "  echo quit | sudo nvidia-cuda-mps-control"
echo ""
echo "To restart MPS:"
echo "  sudo $0"
echo ""

# Create systemd service for MPS persistence
echo "Creating systemd service for MPS persistence..."

cat > /etc/systemd/system/nvidia-mps.service <<'EOF'
[Unit]
Description=NVIDIA MPS (Multi-Process Service) Control Daemon
After=syslog.target

[Service]
Type=forking
Environment="CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps"
Environment="CUDA_MPS_LOG_DIRECTORY=/tmp/nvidia-log"
ExecStartPre=/bin/sh -c 'mkdir -p /tmp/nvidia-mps /tmp/nvidia-log && chmod 777 /tmp/nvidia-mps /tmp/nvidia-log'
ExecStart=/usr/bin/nvidia-cuda-mps-control -d
ExecStopPost=/bin/sh -c 'echo quit | /usr/bin/nvidia-cuda-mps-control'
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable nvidia-mps.service
systemctl restart nvidia-mps.service

echo "✓ Systemd service created and enabled"
echo "  MPS will now start automatically on boot"
echo ""
