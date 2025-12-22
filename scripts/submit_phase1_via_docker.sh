#!/bin/bash
# Submit Phase 1 training job via Ray Job Submission API (from within container)
# No direct docker exec to training containers - uses Ray's HTTP API

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "========================================================================"
echo "Phase 1 Training Job Submission (HTTP API)"
echo "========================================================================"
echo ""

# Copy submission script into ray-compute-api container
echo "Copying submission script to ray-compute-api container..."
docker cp "${PROJECT_ROOT}/scripts/submit_phase1_training.py" ray-compute-api:/tmp/submit_phase1_training.py

echo "Copying training script to ray-compute-api container..."
docker cp "${PROJECT_ROOT}/ray_compute/jobs/training/phase1_foundation.py" ray-compute-api:/tmp/phase1_foundation.py

echo ""
echo "Submitting job via Ray Job Submission API..."
echo ""

# Run submission script from inside container (where Ray is installed)
docker exec -i ray-compute-api python3 /tmp/submit_phase1_training.py

echo ""
echo "✓ Job submission complete"
echo ""
