#!/bin/bash
# Stop Ray cluster gracefully

set -e

echo "Stopping Ray cluster..."
ray stop --force

echo "Cleaning up Ray temporary files..."
rm -rf /opt/ray/tmp/*

echo "✓ Ray cluster stopped"
