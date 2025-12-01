#!/bin/bash
# Quick test of resource manager

cd /home/axelofwar/Desktop/Projects/ml-platform

echo "Testing Resource Manager..."
echo "================================"
echo ""

# Check Python dependencies
echo "Checking Python dependencies..."
python3 -c "import psutil, yaml" 2>/dev/null && echo "✅ Dependencies OK" || {
    echo "Installing dependencies..."
    pip3 install --user psutil pyyaml
}

echo ""
echo "Running resource manager in dry-run mode..."
echo "This will show you what changes would be made without modifying anything."
echo ""

python3 scripts/resource_manager.py --dry-run

echo ""
echo "================================"
echo "Test complete!"
echo ""
echo "To apply these changes, run:"
echo "  ./start_all_safe.sh"
