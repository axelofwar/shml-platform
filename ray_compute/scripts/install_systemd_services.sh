#!/bin/bash
# Install Ray Compute as systemd services (optional, for production)

set -e

echo "================================================"
echo "Installing Ray Compute as systemd services"
echo "================================================"
echo ""

CURRENT_USER=$(whoami)
WORKDIR=$(pwd)

echo "Installing services for user: $CURRENT_USER"
echo "Working directory: $WORKDIR"
echo ""

# Create systemd service files
echo "Creating systemd service files..."

# Ray head service
sed "s/%USER%/$CURRENT_USER/g" config/ray-head.service | \
    sudo tee /etc/systemd/system/ray-head.service > /dev/null

# API service - choose version
echo ""
echo "Which API server do you want to install?"
echo "  1) Standard API (server.py) - Local only"
echo "  2) Remote API (server_remote.py) - With artifact cleanup [RECOMMENDED]"
read -p "Enter choice [1-2]: " api_choice

case $api_choice in
    1)
        sed -e "s/%USER%/$CURRENT_USER/g" -e "s|%WORKDIR%|$WORKDIR|g" config/ray-compute-api.service | \
            sudo tee /etc/systemd/system/ray-compute-api.service > /dev/null
        API_SERVICE="ray-compute-api"
        ;;
    2)
        sed "s/axelofwar/$CURRENT_USER/g" config/ray-compute-api-remote.service | \
            sed "s|/home/$USER/Projects/mlflow-server/ray_compute|$WORKDIR|g" | \
            sudo tee /etc/systemd/system/ray-compute-api-remote.service > /dev/null
        API_SERVICE="ray-compute-api-remote"
        ;;
    *)
        echo "Invalid choice. Using Remote API (default)"
        sed "s/axelofwar/$CURRENT_USER/g" config/ray-compute-api-remote.service | \
            sed "s|/home/$USER/Projects/mlflow-server/ray_compute|$WORKDIR|g" | \
            sudo tee /etc/systemd/system/ray-compute-api-remote.service > /dev/null
        API_SERVICE="ray-compute-api-remote"
        ;;
esac

# Reload systemd
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

# Enable services
echo "Enabling services to start on boot..."
sudo systemctl enable ray-head.service
sudo systemctl enable $API_SERVICE.service

echo ""
echo "✓ Services installed"
echo ""
echo "Service commands:"
echo "  • Start:   sudo systemctl start ray-head $API_SERVICE"
echo "  • Stop:    sudo systemctl stop $API_SERVICE ray-head"
echo "  • Restart: sudo systemctl restart ray-head $API_SERVICE"
echo "  • Status:  sudo systemctl status ray-head $API_SERVICE"
echo "  • Logs:    sudo journalctl -u ray-head -f"
echo "            sudo journalctl -u $API_SERVICE -f"
echo ""
echo "Start services now?"
read -p "Start services? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo systemctl start ray-head
    sleep 3
    sudo systemctl start $API_SERVICE
    echo ""
    echo "✓ Services started"
    sudo systemctl status ray-head $API_SERVICE --no-pager
fi
echo ""
