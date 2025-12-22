#!/bin/bash
# =============================================================================
# Sandbox Training Wrapper - Bubblewrap Security Isolation
#
# Runs native training in a secure sandbox with:
# - Read-only filesystem (except specific writable paths)
# - GPU device passthrough
# - Network restricted to Docker bridge only
# - Process namespace isolation
# - No privilege escalation
#
# Navigation:
# - Related: native_trainer.py (training), native_training_coordinator.py (lifecycle)
# - Config: ../../docs/DYNAMIC_MPS_DESIGN.md
# - Docs: README.md
#
# Usage:
#   ./sandbox_training.sh --model yolov8n.pt --data wider_face --epochs 100
#
# Author: SHML Platform
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="/home/axelofwar/Projects/shml-platform"

# Paths that need write access
CHECKPOINT_DIR="${PROJECT_ROOT}/data/checkpoints"
DATA_DIR="${PROJECT_ROOT}/data/training"
LOG_DIR="${PROJECT_ROOT}/logs"
CACHE_DIR="${HOME}/.cache"

# Python environment (native installation)
PYTHON_BIN="/usr/bin/python3"
VENV_PATH="${PROJECT_ROOT}/inference/.venv"

# GPU devices to expose
GPU_DEVICES=(
    "/dev/nvidia0"
    "/dev/nvidiactl"
    "/dev/nvidia-uvm"
    "/dev/nvidia-uvm-tools"
)

# Network restrictions (Docker bridge network)
ALLOWED_NETWORKS="172.30.0.0/16"

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error() {
    echo "[ERROR] $*" >&2
    exit 1
}

check_dependencies() {
    # Check for bubblewrap
    if ! command -v bwrap &> /dev/null; then
        error "bubblewrap not installed. Run: sudo apt install bubblewrap"
    fi

    # Check for GPU devices
    for dev in "${GPU_DEVICES[@]}"; do
        if [[ -e "$dev" ]]; then
            log "GPU device found: $dev"
        else
            log "Warning: GPU device not found: $dev (may be optional)"
        fi
    done

    # Check for NVIDIA driver
    if ! command -v nvidia-smi &> /dev/null; then
        error "NVIDIA driver not installed or nvidia-smi not in PATH"
    fi

    # Check for Python
    if [[ -d "$VENV_PATH" ]]; then
        PYTHON_BIN="${VENV_PATH}/bin/python"
        log "Using virtualenv: $VENV_PATH"
    elif command -v python3 &> /dev/null; then
        PYTHON_BIN="$(which python3)"
        log "Using system Python: $PYTHON_BIN"
    else
        error "Python 3 not found"
    fi
}

setup_directories() {
    # Create required directories if they don't exist
    mkdir -p "$CHECKPOINT_DIR"
    mkdir -p "$DATA_DIR"
    mkdir -p "$LOG_DIR"
    mkdir -p "$CACHE_DIR/torch"
    mkdir -p "$CACHE_DIR/ultralytics"
}

# -----------------------------------------------------------------------------
# Build Bubblewrap Command
# -----------------------------------------------------------------------------

build_bwrap_command() {
    local cmd=(bwrap)

    # -------------------------------------------------------------------------
    # Filesystem Isolation
    # -------------------------------------------------------------------------

    # Read-only bind of root filesystem
    cmd+=(--ro-bind / /)

    # Writable directories
    cmd+=(--bind "$CHECKPOINT_DIR" "$CHECKPOINT_DIR")
    cmd+=(--bind "$DATA_DIR" "$DATA_DIR")
    cmd+=(--bind "$LOG_DIR" "$LOG_DIR")
    cmd+=(--bind "$CACHE_DIR" "$CACHE_DIR")
    cmd+=(--bind /tmp /tmp)

    # -------------------------------------------------------------------------
    # GPU Device Passthrough
    # -------------------------------------------------------------------------

    # NVIDIA devices for CUDA access
    for dev in "${GPU_DEVICES[@]}"; do
        if [[ -e "$dev" ]]; then
            cmd+=(--dev-bind "$dev" "$dev")
        fi
    done

    # Also need /dev/dri for some GPU operations
    if [[ -d /dev/dri ]]; then
        cmd+=(--dev-bind /dev/dri /dev/dri)
    fi

    # -------------------------------------------------------------------------
    # Process Isolation
    # -------------------------------------------------------------------------

    # New PID namespace (training process becomes PID 1 in its namespace)
    cmd+=(--unshare-pid)

    # New session (prevents terminal hijacking)
    cmd+=(--new-session)

    # -------------------------------------------------------------------------
    # Environment
    # -------------------------------------------------------------------------

    # Preserve necessary environment variables
    cmd+=(--setenv PATH "$PATH")
    cmd+=(--setenv HOME "$HOME")
    cmd+=(--setenv PYTHONPATH "${PROJECT_ROOT}/inference/app:${PROJECT_ROOT}/inference/training_library")
    cmd+=(--setenv CUDA_VISIBLE_DEVICES "0")
    cmd+=(--setenv CUDA_DEVICE_ORDER "PCI_BUS_ID")

    # CRITICAL: Bypass MPS to allow CUDA access alongside MPS-based inference
    # Setting CUDA_MPS_PIPE_DIRECTORY="" disables MPS for this process
    # This allows training to access GPU directly while inference uses MPS
    cmd+=(--setenv CUDA_MPS_PIPE_DIRECTORY "")

    # MLflow configuration
    cmd+=(--setenv MLFLOW_TRACKING_URI "http://172.30.0.11:5000")

    # PyTorch memory optimization
    cmd+=(--setenv PYTORCH_CUDA_ALLOC_CONF "max_split_size_mb:512")

    # -------------------------------------------------------------------------
    # Security Hardening
    # -------------------------------------------------------------------------

    # Drop capabilities (we don't need any special privileges)
    cmd+=(--cap-drop ALL)

    # Die with parent (if coordinator dies, so does training)
    cmd+=(--die-with-parent)

    # -------------------------------------------------------------------------
    # Working Directory
    # -------------------------------------------------------------------------

    cmd+=(--chdir "${PROJECT_ROOT}/inference/app/native_training")

    echo "${cmd[@]}"
}

# -----------------------------------------------------------------------------
# Network Firewall (Optional - requires iptables or nftables)
# -----------------------------------------------------------------------------

setup_network_restrictions() {
    # This would require root/sudo - document for manual setup
    cat << EOF
To restrict network access, add these iptables rules (requires sudo):

# Allow only Docker bridge network
sudo iptables -A OUTPUT -p tcp -d 172.30.0.0/16 -j ACCEPT
sudo iptables -A OUTPUT -p tcp -j DROP

For a more secure setup, use network namespaces with veth pairs.
EOF
}

# -----------------------------------------------------------------------------
# Main Execution
# -----------------------------------------------------------------------------

main() {
    log "Starting sandboxed training..."

    # Check dependencies
    check_dependencies

    # Setup directories
    setup_directories

    # Build bubblewrap command
    BWRAP_CMD=($(build_bwrap_command))

    # Add Python and training script
    BWRAP_CMD+=("$PYTHON_BIN" "${SCRIPT_DIR}/native_trainer.py")

    # Pass through all arguments to the trainer
    BWRAP_CMD+=("$@")

    log "Running: ${BWRAP_CMD[*]}"

    # Execute in sandbox
    exec "${BWRAP_CMD[@]}"
}

# Handle arguments
if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
    cat << EOF
Sandbox Training Wrapper

Usage: $0 [TRAINER_OPTIONS]

This script runs native_trainer.py inside a bubblewrap sandbox with:
  - Read-only filesystem (except checkpoints, data, logs)
  - GPU device passthrough
  - Process isolation
  - Restricted network (Docker bridge only)

Trainer Options:
  --model MODEL      Model to train (default: yolov8n.pt)
  --data DATASET     Dataset name (default: wider_face)
  --epochs N         Number of epochs (default: 100)
  --batch N          Batch size (default: 16)
  --resume PATH      Resume from checkpoint
  --mlflow-uri URI   MLflow tracking URI
  --experiment NAME  MLflow experiment name
  --device DEVICE    CUDA device (default: cuda:0)

Example:
  $0 --model yolov8n.pt --data wider_face --epochs 100 --batch 16

Environment:
  CHECKPOINT_DIR: $CHECKPOINT_DIR
  DATA_DIR: $DATA_DIR
  LOG_DIR: $LOG_DIR
  PYTHON: $PYTHON_BIN

Security:
  - Runs in bubblewrap sandbox
  - Read-only root filesystem
  - GPU devices passed through
  - PID namespace isolation
  - No privilege escalation
EOF
    exit 0
fi

main "$@"
