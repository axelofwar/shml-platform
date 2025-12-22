#!/bin/bash
# Submit Ray job from host without direct container access
# Works by running submission script in a temporary container on platform network

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "========================================================================"
echo "Ray Job Submission (Host → Platform Network)"
echo "========================================================================"
echo ""
echo "This script runs the job submission from within the Docker network"
echo "No direct container exec needed - uses temporary container"
echo ""

# Run Python submission script in temporary container on platform network
docker run --rm \
  --network shml-platform_platform \
  -v "${PROJECT_ROOT}:/workspace" \
  -w /workspace \
  python:3.11-slim bash -c "
    pip install -q 'ray[default]>=2.30.0' && \
    python3 scripts/submit_phase1_training.py
  "

echo ""
echo "✓ Job submission complete"
