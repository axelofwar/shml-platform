#!/bin/bash
set -e

echo "🔄 Restarting ML Platform..."

cd "$(dirname "$0")"

# Stop
./stop_all.sh

sleep 2

# Start
./start_all.sh

echo "✅ ML Platform restarted"
