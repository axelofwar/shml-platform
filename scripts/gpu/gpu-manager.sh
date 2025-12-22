#!/bin/bash
#
# GPU Resource Management for SHML Platform
# Handles exclusive GPU access for training vs inference
#
# Strategy:
# - GPU 0 (RTX 3090 Ti): Training priority - inference yields when training starts
# - GPU 1 (RTX 2070): Always available for fallback inference
#
# This script provides functions for:
# 1. Stopping MPS on GPU 0 for exclusive training access
# 2. Restarting MPS after training completes
# 3. Managing CUDA contexts

set -e

# Configuration
MPS_PIPE_DIR="${CUDA_MPS_PIPE_DIRECTORY:-/tmp/nvidia-mps}"
MPS_LOG_DIR="${CUDA_MPS_LOG_DIRECTORY:-/tmp/nvidia-log}"
TRAINING_GPU="${TRAINING_GPU:-0}"
INFERENCE_GPU="${INFERENCE_GPU:-1}"
SIGNAL_DIR="${TRAINING_SIGNAL_DIR:-/tmp/shml/training-signals}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error() {
    log "ERROR: $*" >&2
}

# Check if MPS is running
is_mps_running() {
    pgrep -f "nvidia-cuda-mps-server" > /dev/null 2>&1
}

# Get processes using a specific GPU
get_gpu_processes() {
    local gpu_id=$1
    nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader -i "$gpu_id" 2>/dev/null || true
}

# Check if GPU is free (no processes)
is_gpu_free() {
    local gpu_id=$1
    local procs
    procs=$(get_gpu_processes "$gpu_id")
    [ -z "$procs" ]
}

# Stop MPS daemon and server
stop_mps() {
    log "Stopping MPS daemon..."

    if ! is_mps_running; then
        log "MPS not running"
        return 0
    fi

    # Send quit command to MPS control
    echo quit | sudo nvidia-cuda-mps-control 2>/dev/null || true

    # Wait for server to stop
    local timeout=30
    local count=0
    while is_mps_running && [ $count -lt $timeout ]; do
        sleep 1
        count=$((count + 1))
    done

    if is_mps_running; then
        error "MPS did not stop gracefully, forcing..."
        sudo pkill -9 nvidia-cuda-mps-server 2>/dev/null || true
        sudo pkill -9 nvidia-cuda-mps-control 2>/dev/null || true
        sleep 2
    fi

    log "MPS stopped"
}

# Start MPS daemon
start_mps() {
    log "Starting MPS daemon..."

    if is_mps_running; then
        log "MPS already running"
        return 0
    fi

    # Ensure directories exist
    sudo mkdir -p "$MPS_PIPE_DIR" "$MPS_LOG_DIR"
    sudo chmod 777 "$MPS_PIPE_DIR" "$MPS_LOG_DIR"

    # Set environment
    export CUDA_MPS_PIPE_DIRECTORY="$MPS_PIPE_DIR"
    export CUDA_MPS_LOG_DIRECTORY="$MPS_LOG_DIR"

    # Start control daemon
    sudo nvidia-cuda-mps-control -d
    sleep 2

    # Configure thread percentage (allow some sharing)
    echo "set_default_active_thread_percentage 50" | sudo nvidia-cuda-mps-control || true

    if is_mps_running; then
        log "MPS started successfully"
    else
        error "Failed to start MPS"
        return 1
    fi
}

# Request exclusive GPU access for training
# This will:
# 1. Signal inference service to yield
# 2. Wait for GPU to be free
# 3. Optionally stop MPS for exclusive access
request_training_gpu() {
    local job_id="${1:-training-$(date +%s)}"
    local gpu_id="${2:-$TRAINING_GPU}"
    local timeout="${3:-120}"  # 2 minutes default

    log "Requesting GPU $gpu_id for training job: $job_id"

    # Create signal file
    mkdir -p "$SIGNAL_DIR"
    cat > "$SIGNAL_DIR/${job_id}.signal" << EOF
{
    "job_id": "$job_id",
    "gpus": [$gpu_id],
    "priority": 10,
    "started": "$(date -Iseconds)",
    "pid": $$
}
EOF

    log "Signal file created: $SIGNAL_DIR/${job_id}.signal"

    # Also try HTTP signal if inference service is reachable
    if command -v curl &> /dev/null; then
        curl -sf -X POST "http://coding-model-primary:8000/training/start" \
            -H "Content-Type: application/json" \
            -d "{\"job_id\": \"$job_id\", \"gpus\": [$gpu_id], \"priority\": 10}" \
            2>/dev/null || log "HTTP signal failed (container may not be reachable)"
    fi

    # Wait for GPU to be free
    log "Waiting for GPU $gpu_id to be free (timeout: ${timeout}s)..."
    local count=0
    while ! is_gpu_free "$gpu_id" && [ $count -lt $timeout ]; do
        if [ $((count % 10)) -eq 0 ]; then
            local procs
            procs=$(get_gpu_processes "$gpu_id")
            log "GPU $gpu_id still in use: $procs"
        fi
        sleep 1
        count=$((count + 1))
    done

    if ! is_gpu_free "$gpu_id"; then
        error "Timeout waiting for GPU $gpu_id to be free"
        # Clean up signal
        rm -f "$SIGNAL_DIR/${job_id}.signal"
        return 1
    fi

    # Check if we need to stop MPS for exclusive access
    if is_mps_running; then
        log "MPS is running - training will use MPS context"
        # For most training, MPS is fine. Only stop if needed for exclusive access.
        # Uncomment below if exclusive access is required:
        # stop_mps
    fi

    log "GPU $gpu_id ready for training"
    echo "$job_id"  # Return job ID for cleanup
}

# Release GPU after training
release_training_gpu() {
    local job_id="$1"

    log "Releasing GPU for training job: $job_id"

    # Remove signal file
    rm -f "$SIGNAL_DIR/${job_id}.signal"

    # Send HTTP stop signal
    if command -v curl &> /dev/null; then
        curl -sf -X POST "http://coding-model-primary:8000/training/stop?job_id=$job_id" \
            2>/dev/null || log "HTTP stop signal failed"
    fi

    # Restart MPS if it was stopped
    if ! is_mps_running; then
        start_mps
    fi

    log "GPU released"
}

# Run a training command with GPU management
run_training() {
    local job_id
    job_id=$(request_training_gpu)

    if [ $? -ne 0 ]; then
        error "Failed to acquire GPU"
        return 1
    fi

    log "Running training command: $*"

    # Run the training command
    local exit_code=0
    "$@" || exit_code=$?

    # Release GPU
    release_training_gpu "$job_id"

    return $exit_code
}

# Show status
show_status() {
    echo "=== GPU Status ==="
    nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv

    echo ""
    echo "=== MPS Status ==="
    if is_mps_running; then
        echo "MPS: Running"
        echo "get_server_list" | sudo nvidia-cuda-mps-control 2>/dev/null || echo "  (no active servers)"
    else
        echo "MPS: Not running"
    fi

    echo ""
    echo "=== Training Signals ==="
    if [ -d "$SIGNAL_DIR" ]; then
        ls -la "$SIGNAL_DIR"/*.signal 2>/dev/null || echo "  No active signals"
    else
        echo "  Signal directory not found"
    fi

    echo ""
    echo "=== GPU Processes ==="
    nvidia-smi --query-compute-apps=pid,name,gpu_uuid,used_memory --format=csv
}

# Main entry point
case "${1:-status}" in
    start-mps)
        start_mps
        ;;
    stop-mps)
        stop_mps
        ;;
    request)
        request_training_gpu "${2:-}" "${3:-}"
        ;;
    release)
        release_training_gpu "$2"
        ;;
    run)
        shift
        run_training "$@"
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {start-mps|stop-mps|request [job_id] [gpu_id]|release <job_id>|run <command>|status}"
        exit 1
        ;;
esac
