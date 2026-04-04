#!/usr/bin/env bash
# training-guard.sh — ExecStartPre guard for qwen35-server.service
# Exit 1 (preventing start) when GPU 0 is occupied by an active training job.
# systemd interprets a non-zero exit from ExecStartPre as "don't start unit".

set -euo pipefail

TRAINING_GPU=0

# Check CUDA compute processes on GPU 0
if command -v nvidia-smi &>/dev/null; then
    GPU_PIDS=$(nvidia-smi --id="${TRAINING_GPU}" --query-compute-apps=pid \
        --format=csv,noheader 2>/dev/null || true)
    if echo "${GPU_PIDS}" | grep -q "[0-9]"; then
        echo "training-guard: GPU ${TRAINING_GPU} has active compute processes — blocking llama-server start"
        exit 1
    fi
fi

# Check Ray head for active/pending jobs
RAY_JOBS=$(python3 -c "
import urllib.request, json, sys
try:
    r = urllib.request.urlopen('http://localhost:8265/api/jobs/', timeout=3)
    jobs = json.loads(r.read())
    active = [j for j in jobs if j.get('status') in ('RUNNING', 'PENDING')]
    print(len(active))
except Exception:
    print(0)
" 2>/dev/null || echo "0")

if [[ "$RAY_JOBS" =~ ^[0-9]+$ ]] && (( RAY_JOBS > 0 )); then
    echo "training-guard: ${RAY_JOBS} Ray job(s) active — blocking llama-server start"
    exit 1
fi

echo "training-guard: GPU ${TRAINING_GPU} is free — allowing llama-server start"
exit 0
