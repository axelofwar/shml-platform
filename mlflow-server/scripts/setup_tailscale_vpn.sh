#!/bin/bash
#
# Tailscale VPN Quick Setup Script
# Easy remote access to MLflow server
# Privacy: ⭐⭐⭐⭐ (Excellent - uses WireGuard, Tailscale coordinates but can't see data)
# Time: 10 minutes
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

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Banner
echo "════════════════════════════════════════════════════════════════"
echo "           Tailscale VPN Setup for MLflow"
echo "           Easy Remote Access - Privacy Preserved"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    log_error "Please run as regular user, not root. Script will prompt for sudo when needed."
    exit 1
fi

# Introduction
echo "What is Tailscale?"
echo "  • Easy-to-use VPN based on WireGuard (modern, secure)"
echo "  • Access MLflow from anywhere (phone, laptop, tablet)"
echo "  • No port forwarding on your router needed"
echo "  • Free tier: 100 devices, 3 users (perfect for solo dev)"
echo "  • Privacy: End-to-end encrypted (Tailscale can't see your data)"
echo ""
echo "How it works:"
echo "  Your Device → Encrypted Tunnel → Your Network → MLflow Server"
echo ""
read -p "Press Enter to continue with installation..."

# Check if Tailscale is already installed
if command -v tailscale &> /dev/null; then
    log_warning "Tailscale is already installed"

    if tailscale status &> /dev/null; then
        log_info "Tailscale is already connected!"
        TAILSCALE_IP=$(tailscale ip -4)
        echo ""
        echo "Your Tailscale IP: $TAILSCALE_IP"
        echo "Access MLflow at: http://$TAILSCALE_IP:5000"
        echo ""
        echo "To access from other devices:"
        echo "  1. Install Tailscale app on your phone/laptop"
        echo "  2. Sign in with the same account"
        echo "  3. Open: http://$TAILSCALE_IP:5000"
        echo ""
        exit 0
    fi
else
    # Install Tailscale
    log_info "Installing Tailscale..."

    # Download and run official install script
    curl -fsSL https://tailscale.com/install.sh | sh

    log_success "Tailscale installed"
fi

# Start Tailscale
echo ""
log_info "Starting Tailscale..."
echo ""
echo "This will open a browser window for authentication."
echo "If you don't have a Tailscale account, you can create one (free)."
echo "Supports: Google, Microsoft, GitHub, or email login"
echo ""
read -p "Press Enter to continue..."

# Bring up Tailscale
sudo tailscale up

# Wait for connection
log_info "Waiting for Tailscale to connect..."
sleep 5

# Get Tailscale IP
if tailscale status &> /dev/null; then
    TAILSCALE_IP=$(tailscale ip -4)
    HOSTNAME=$(hostname)

    echo ""
    log_success "✓ Tailscale connected successfully!"
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "              Remote Access Configuration"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "Your Tailscale IP: $TAILSCALE_IP"
    echo "Your Hostname:     $HOSTNAME"
    echo ""
    echo "MLflow Access URLs:"
    echo "  Via IP:        http://$TAILSCALE_IP:5000"
    echo "  Via Hostname:  http://$HOSTNAME:5000"
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "              Setup on Other Devices"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "📱 Phone/Tablet:"
    echo "  1. Install Tailscale app from App Store/Play Store"
    echo "  2. Sign in with the same account you just created"
    echo "  3. Open Safari/Chrome: http://$TAILSCALE_IP:5000"
    echo ""
    echo "💻 Laptop/Desktop:"
    echo "  1. Install Tailscale: https://tailscale.com/download"
    echo "  2. Sign in with the same account"
    echo "  3. Open browser: http://$TAILSCALE_IP:5000"
    echo ""
    echo "🐧 Linux (your dev machine):"
    echo "  curl -fsSL https://tailscale.com/install.sh | sh"
    echo "  sudo tailscale up"
    echo "  export MLFLOW_TRACKING_URI=\"http://$TAILSCALE_IP:5000\""
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "              Testing Remote Access"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "From your development machine (after installing Tailscale):"
    echo ""
    echo "  # Test connection:"
    echo "  curl http://$TAILSCALE_IP:5000"
    echo ""
    echo "  # Configure MLflow client:"
    echo "  export MLFLOW_TRACKING_URI=\"http://$TAILSCALE_IP:5000\""
    echo ""
    echo "  # Test Python client:"
    echo "  python3 -c \"import mlflow; mlflow.set_tracking_uri('http://$TAILSCALE_IP:5000'); print('Connected!')\""
    echo ""
    echo "  # Train with remote tracking:"
    echo "  python scripts/train_local.py --mlflow --mlflow-run-name test_remote"
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "              Useful Tailscale Commands"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "  Check status:         tailscale status"
    echo "  Show IP:              tailscale ip"
    echo "  List devices:         tailscale status"
    echo "  Disconnect:           sudo tailscale down"
    echo "  Reconnect:            sudo tailscale up"
    echo "  View logs:            sudo journalctl -u tailscaled"
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "              Privacy & Security Notes"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "✅ Your MLflow data is end-to-end encrypted (Tailscale uses WireGuard)"
    echo "✅ Tailscale cannot see your experiment data or metrics"
    echo "✅ No port forwarding on your router (more secure)"
    echo "✅ Only devices in your Tailscale network can access MLflow"
    echo "✅ You can revoke device access anytime from Tailscale admin panel"
    echo ""
    echo "Tailscale Admin Panel: https://login.tailscale.com/admin/machines"
    echo "  • View all connected devices"
    echo "  • Revoke access to specific devices"
    echo "  • Enable MagicDNS for hostname-based access"
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    log_success "Tailscale setup complete! 🎉"
    echo ""

    # Save configuration to file
    CONFIG_FILE="/opt/mlflow/tailscale_config.txt"
    sudo tee "$CONFIG_FILE" > /dev/null << EOF
MLflow Tailscale Configuration
Generated: $(date)

Tailscale IP: $TAILSCALE_IP
Hostname: $HOSTNAME
MLflow URL: http://$TAILSCALE_IP:5000

Access from other devices:
1. Install Tailscale
2. Sign in with same account
3. Open: http://$TAILSCALE_IP:5000

Development machine configuration:
export MLFLOW_TRACKING_URI="http://$TAILSCALE_IP:5000"
EOF
    sudo chown mlflow:mlflow "$CONFIG_FILE"

    log_info "Configuration saved to: $CONFIG_FILE"
    echo ""

else
    log_error "Failed to connect to Tailscale. Please check logs: sudo journalctl -u tailscaled"
    exit 1
fi

# Test local MLflow connection
log_info "Testing local MLflow connection..."
if curl -s http://localhost:5000 >/dev/null 2>&1; then
    log_success "✓ MLflow is accessible locally"
else
    log_warning "⚠ Could not connect to local MLflow. Ensure service is running: sudo systemctl status mlflow"
fi

echo ""
log_info "Next step: Install Tailscale on your development machine and test connection!"
