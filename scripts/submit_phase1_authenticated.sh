#!/bin/bash
# Submit Ray job using internal Docker network (bypasses OAuth2-Proxy)
# Uses CICD API key for authentication

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Read configuration
SCRIPT_PATH="${1:-ray_compute/jobs/training/phase1_foundation.py}"
JOB_NAME="${2:-phase1-wider-balanced-200ep}"
GPU="${3:-1.0}"
CPU="${4:-8}"
MEMORY="${5:-48}"
MLFLOW_EXP="${6:-Phase1-WIDER-Balanced}"

# Get CICD admin key from env
if [ -f "$PROJECT_ROOT/.env" ]; then
    CICD_ADMIN_KEY=$(grep "FUSIONAUTH_CICD_SUPER_KEY" "$PROJECT_ROOT/.env" | cut -d'=' -f2)
fi

if [ -z "$CICD_ADMIN_KEY" ]; then
    echo "Error: CICD admin key not found in .env"
    exit 1
fi

echo "========================================================================"
echo "Ray Job Submission (Internal API)"
echo "========================================================================"
echo ""
echo "Job: $JOB_NAME"
echo "Script: $SCRIPT_PATH"
echo "Resources: ${GPU} GPU, ${CPU} CPU, ${MEMORY}GB RAM"
echo "MLflow: $MLFLOW_EXP"
echo ""

# Create temporary container to submit job
docker run --rm \
  --network shml-platform \
  -v "${PROJECT_ROOT}:/workspace" \
  -w /workspace \
  -e CICD_ADMIN_KEY="$CICD_ADMIN_KEY" \
  python:3.11-slim bash -c "
    set -e
    echo 'Installing dependencies...'
    pip install -q httpx typer rich > /dev/null 2>&1

    echo 'Submitting job via internal API...'
    python3 - <<'PYTHON_SCRIPT'
import sys
import os
import base64
import json
from pathlib import Path
import httpx

# Configuration
API_URL = 'http://ray-compute-api:8000/api/v1/jobs'
API_KEY = os.environ['CICD_ADMIN_KEY']
SCRIPT_PATH = '$SCRIPT_PATH'
JOB_NAME = '$JOB_NAME'

# Read script
script_path = Path(SCRIPT_PATH)
if not script_path.exists():
    print(f'Error: Script not found: {SCRIPT_PATH}', file=sys.stderr)
    sys.exit(1)

with open(script_path, 'rb') as f:
    script_content = base64.b64encode(f.read()).decode('utf-8')

# Build job request
job_data = {
    'name': JOB_NAME,
    'script_content': script_content,
    'script_name': script_path.name,
    'cpu': $CPU,
    'memory_gb': $MEMORY,
    'gpu': $GPU,
    'no_timeout': True,
    'priority': 'high',
    'requirements': [
        'ultralytics==8.3.54',
        'mlflow==2.17.2',
        'opencv-python-headless==4.10.0.84',
        'torch==2.1.0',
        'torchvision==0.16.0',
        'pillow==10.4.0',
        'pyyaml==6.0.2',
        'tqdm==4.66.5',
    ],
    'mlflow_experiment': '$MLFLOW_EXP',
    'output_mode': 'both',
}

# Submit job
headers = {
    'X-API-Key': API_KEY,
    'Content-Type': 'application/json',
}

try:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(API_URL, json=job_data, headers=headers)
        response.raise_for_status()
        result = response.json()

        print('')
        print('✓ Job Submitted Successfully')
        print('=' * 70)
        print(f\"Job ID:   {result['job_id']}\")
        print(f\"Name:     {result['name']}\")
        print(f\"Status:   {result['status']}\")
        print(f\"GPU:      {result['gpu_requested']}\")
        print(f\"CPU:      {result['cpu_requested']} cores\")
        print(f\"Memory:   {result['memory_gb_requested']} GB\")
        print('=' * 70)
        print('')
        print('Monitoring URLs:')
        print('  • Ray Dashboard: http://localhost/ray/')
        print('  • Grafana: http://localhost/grafana/d/face-detection-unified/')
        print('  • MLflow: http://localhost/mlflow/#/experiments')
        print('')
        print('Expected Duration: 60-72 hours (200 epochs)')
        print('Metrics will appear in Grafana after ~20 minutes')
        print('')

except httpx.HTTPStatusError as e:
    print(f'\\nError: HTTP {e.response.status_code}', file=sys.stderr)
    try:
        error_detail = e.response.json().get('detail', str(e))
        print(f'{error_detail}\\n', file=sys.stderr)
    except:
        print(f'{str(e)}\\n', file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f'\\nError: {str(e)}\\n', file=sys.stderr)
    sys.exit(1)
PYTHON_SCRIPT
"

echo ""
echo "✓ Submission complete"
