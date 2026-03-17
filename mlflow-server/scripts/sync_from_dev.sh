#!/bin/bash
#
# Sync MLflow runs from development machine to dedicated server
# Run this on your development machine after training completes
#

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configuration
SOURCE_DIR="/workspace/mlruns"
REMOTE_USER="mlflow"
REMOTE_HOST=""  # Will be prompted or detected from Tailscale
REMOTE_DIR="/opt/mlflow/mlruns"

echo "════════════════════════════════════════════════════════════════"
echo "           Sync MLflow Runs to Dedicated Server"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Check if source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
    log_error "Source directory not found: $SOURCE_DIR"
    exit 1
fi

# Count runs to sync
RUN_COUNT=$(find "$SOURCE_DIR" -type d -name "[0-9]*" | wc -l)
log_info "Found $RUN_COUNT runs to sync"

# Get remote host (Tailscale IP or hostname)
if command -v tailscale &> /dev/null && tailscale status &> /dev/null 2>&1; then
    log_info "Tailscale detected. Looking for MLflow server..."

    # List Tailscale devices
    echo ""
    echo "Available devices on your Tailscale network:"
    tailscale status | grep -v "^#"
    echo ""
fi

# Prompt for remote host if not set
if [ -z "$REMOTE_HOST" ]; then
    read -p "Enter MLflow server IP or hostname: " REMOTE_HOST
    if [ -z "$REMOTE_HOST" ]; then
        log_error "Remote host cannot be empty"
        exit 1
    fi
fi

# Prompt for remote user (default: mlflow)
read -p "Enter remote username (default: mlflow): " INPUT_USER
REMOTE_USER=${INPUT_USER:-mlflow}

# Test connection
log_info "Testing SSH connection to $REMOTE_USER@$REMOTE_HOST..."
if ssh -o ConnectTimeout=5 -o BatchMode=yes "$REMOTE_USER@$REMOTE_HOST" exit 2>/dev/null; then
    log_success "SSH connection successful"
elif ssh -o ConnectTimeout=5 "$REMOTE_USER@$REMOTE_HOST" exit 2>/dev/null; then
    log_success "SSH connection successful (password auth)"
else
    log_error "Cannot connect to $REMOTE_USER@$REMOTE_HOST"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Ensure Tailscale is running: tailscale status"
    echo "  2. Ensure SSH is accessible: ssh $REMOTE_USER@$REMOTE_HOST"
    echo "  3. Setup SSH keys for passwordless access:"
    echo "     ssh-copy-id $REMOTE_USER@$REMOTE_HOST"
    exit 1
fi

# Dry run first to show what will be synced
echo ""
log_info "Dry run - showing what will be synced..."
rsync -avzn --progress "$SOURCE_DIR/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

echo ""
read -p "Proceed with sync? (y/N): " CONFIRM
if [[ ! $CONFIRM =~ ^[Yy]$ ]]; then
    log_info "Sync cancelled"
    exit 0
fi

# Actual sync
echo ""
log_info "Syncing runs to $REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR ..."
rsync -avz --progress "$SOURCE_DIR/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

log_success "Sync complete!"

# Show remote MLflow URL
if command -v tailscale &> /dev/null && tailscale status &> /dev/null 2>&1; then
    echo ""
    echo "Access your runs at: http://$REMOTE_HOST:5000"
fi

echo ""
log_info "To configure real-time tracking (sync during training):"
echo ""
echo "  export MLFLOW_TRACKING_URI=\"http://$REMOTE_HOST:5000\""
echo "  python scripts/train_local.py --mlflow --mlflow-run-name v5.0"
echo ""
