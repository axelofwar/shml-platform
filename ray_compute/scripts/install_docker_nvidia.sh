#!/bin/bash
# Docker + NVIDIA Container Toolkit Installation
# Run AFTER nvidia-smi works

set -e

echo "================================================"
echo "Docker + NVIDIA Container Toolkit Installation"
echo "================================================"

# Verify NVIDIA drivers are installed
if ! nvidia-smi &>/dev/null; then
    echo "❌ Error: NVIDIA drivers not found!"
    echo "Run ./install_nvidia_drivers.sh first and reboot"
    exit 1
fi

echo "✓ NVIDIA drivers detected:"
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
echo ""

# Check if Docker is already installed
if docker --version &>/dev/null; then
    echo "✓ Docker already installed: $(docker --version)"
else
    echo "Installing Docker..."

    # Remove old versions
    sudo apt remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

    # Install prerequisites
    sudo apt update
    sudo apt install -y \
        ca-certificates \
        curl \
        gnupg \
        lsb-release

    # Add Docker's official GPG key
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

    # Set up repository
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Install Docker Engine
    sudo apt update
    sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Add current user to docker group
    sudo usermod -aG docker $USER

    echo "✓ Docker installed successfully"
fi

# Install NVIDIA Container Toolkit
if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi &>/dev/null; then
    echo "✓ NVIDIA Container Toolkit already installed and working"
else
    echo ""
    echo "Installing NVIDIA Container Toolkit..."

    # Add NVIDIA Container Toolkit repository (updated for Ubuntu 24.04+)
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

    sudo apt update
    sudo apt install -y nvidia-container-toolkit

    # Configure Docker to use NVIDIA runtime
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker

    echo "✓ NVIDIA Container Toolkit installed"
fi

echo ""
echo "================================================"
echo "Testing GPU access in Docker..."
echo "================================================"
echo ""

# Test GPU access
if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu20.04 nvidia-smi; then
    echo ""
    echo "================================================"
    echo "✓ SUCCESS! GPU is accessible in Docker"
    echo "================================================"
else
    echo ""
    echo "❌ GPU test failed. You may need to:"
    echo "  1. Log out and back in (for docker group)"
    echo "  2. Restart Docker: sudo systemctl restart docker"
    exit 1
fi

echo ""
echo "Next steps:"
echo "  1. Log out and back in (or run: newgrp docker)"
echo "  2. Run: ./install_ray_cluster.sh"
echo ""
