#!/bin/bash
# NVIDIA Driver Installation Script for RTX 2070
# Ubuntu 20.04 LTS compatible

set -e

echo "================================================"
echo "NVIDIA Driver Installation for RTX 2070"
echo "Ubuntu 20.04 LTS"
echo "================================================"

# Check if already installed
if nvidia-smi &>/dev/null; then
    echo "✓ NVIDIA drivers already installed:"
    nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
    echo ""
    read -p "Reinstall/upgrade drivers? [y/N]: " reinstall
    if [[ ! "$reinstall" =~ ^[Yy]$ ]]; then
        exit 0
    fi
fi

echo ""
echo "Detected GPU:"
lspci | grep -i nvidia | grep VGA

# Check available drivers
echo ""
echo "Checking available drivers for your system..."
sudo apt update -qq
ubuntu-drivers devices

# Get recommended driver
RECOMMENDED_DRIVER=$(ubuntu-drivers devices 2>/dev/null | grep recommended | awk '{print $3}')

if [ -z "$RECOMMENDED_DRIVER" ]; then
    echo ""
    echo "⚠️  Auto-detection couldn't find recommended driver"
    echo ""
    echo "Available NVIDIA drivers for RTX 2070 on Ubuntu 20.04:"
    echo "  1) nvidia-driver-470  - Stable, older (CUDA 11.4)"
    echo "  2) nvidia-driver-535  - Long-term support (CUDA 12.2)"
    echo "  3) nvidia-driver-550  - Production branch (CUDA 12.4)"
    echo "  4) nvidia-driver-580  - Latest (CUDA 12.6) [DEFAULT]"
    echo ""
    read -p "Select driver [1-4] (default: 4): " choice
    choice=${choice:-4}

    case $choice in
        1) RECOMMENDED_DRIVER="nvidia-driver-470" ;;
        2) RECOMMENDED_DRIVER="nvidia-driver-535" ;;
        3) RECOMMENDED_DRIVER="nvidia-driver-550" ;;
        4) RECOMMENDED_DRIVER="nvidia-driver-580" ;;
        *)
            echo "Invalid choice, using nvidia-driver-580"
            RECOMMENDED_DRIVER="nvidia-driver-580"
            ;;
    esac
else
    echo ""
    echo "✓ Recommended driver: $RECOMMENDED_DRIVER"
    echo ""
    read -p "Use this driver? [Y/n]: " use_rec
    if [[ "$use_rec" =~ ^[Nn]$ ]]; then
        echo ""
        echo "Available drivers:"
        echo "  1) nvidia-driver-470"
        echo "  2) nvidia-driver-535"
        echo "  3) nvidia-driver-550"
        echo "  4) nvidia-driver-580"
        read -p "Select [1-4]: " choice
        case $choice in
            1) RECOMMENDED_DRIVER="nvidia-driver-470" ;;
            2) RECOMMENDED_DRIVER="nvidia-driver-535" ;;
            3) RECOMMENDED_DRIVER="nvidia-driver-550" ;;
            4) RECOMMENDED_DRIVER="nvidia-driver-580" ;;
        esac
    fi
fi

echo ""
echo "Selected driver: $RECOMMENDED_DRIVER"
echo ""

# Remove existing drivers if present
if dpkg -l | grep -q nvidia-driver; then
    echo "Removing existing NVIDIA drivers..."
    sudo apt remove --purge -y 'nvidia-*' 2>/dev/null || true
    sudo apt autoremove -y
fi

# Install selected driver
echo ""
echo "Installing $RECOMMENDED_DRIVER..."
echo "This may take 5-10 minutes..."
sudo apt install -y "$RECOMMENDED_DRIVER"

# Verify installation
echo ""
echo "================================================"
echo "✓ Installation Complete"
echo "================================================"
echo ""
echo "Installed driver:"
dpkg -l | grep nvidia-driver | grep ^ii | awk '{print $2, $3}'

echo ""
echo "================================================"
echo "⚠️  SYSTEM REBOOT REQUIRED"
echo "================================================"
echo ""
echo "The NVIDIA driver module must be loaded on reboot."
echo ""
echo "After reboot, verify with:"
echo "  nvidia-smi"
echo ""
echo "Expected output:"
echo "  GPU: NVIDIA GeForce RTX 2070"
echo "  Driver Version: 580.x (or your selected version)"
echo ""
read -p "Reboot now? [y/N]: " do_reboot
if [[ "$do_reboot" =~ ^[Yy]$ ]]; then
    echo "Rebooting in 3 seconds..."
    sleep 3
    sudo reboot
else
    echo ""
    echo "Please reboot manually:"
    echo "  sudo reboot"
    echo ""
    echo "After reboot, continue with:"
    echo "  cd /home/axelofwar/Projects/mlflow-server/ray_compute"
    echo "  sudo bash scripts/install_docker_nvidia.sh"
fi
