#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

RAY_CONTAINER="${RAY_CONTAINER:-ray-head}"
CONTAINER_TRAIN_DIR="${CONTAINER_TRAIN_DIR:-/tmp/ray/jobs/training}"
CONTAINER_UTILS_DIR="${CONTAINER_UTILS_DIR:-/tmp/ray/jobs/utils}"
HOST_TRAIN_SCRIPT="ray_compute/jobs/training/train_phase10_multiscale.py"
HOST_GPU_YIELD="ray_compute/jobs/utils/gpu_yield.py"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but not found in PATH" >&2
  exit 1
fi

if [[ ! -f "$HOST_TRAIN_SCRIPT" ]]; then
  echo "Missing training script: $HOST_TRAIN_SCRIPT" >&2
  exit 1
fi

if [[ ! -f "$HOST_GPU_YIELD" ]]; then
  echo "Missing GPU yield module: $HOST_GPU_YIELD" >&2
  exit 1
fi

if ! docker inspect "$RAY_CONTAINER" >/dev/null 2>&1; then
  echo "Container not found: $RAY_CONTAINER" >&2
  exit 1
fi

if [[ "$(docker inspect -f '{{.State.Running}}' "$RAY_CONTAINER" 2>/dev/null || echo false)" != "true" ]]; then
  echo "Container is not running: $RAY_CONTAINER" >&2
  exit 1
fi

echo "[sync] Updating phase10 training runtime in $RAY_CONTAINER"
docker exec "$RAY_CONTAINER" mkdir -p "$CONTAINER_TRAIN_DIR" "$CONTAINER_UTILS_DIR"
docker cp "$HOST_TRAIN_SCRIPT" "$RAY_CONTAINER:$CONTAINER_TRAIN_DIR/train_phase10_multiscale.py"
docker cp "$HOST_GPU_YIELD" "$RAY_CONTAINER:$CONTAINER_UTILS_DIR/gpu_yield.py"
docker exec "$RAY_CONTAINER" python3 -m py_compile "$CONTAINER_TRAIN_DIR/train_phase10_multiscale.py"
docker exec "$RAY_CONTAINER" sh -lc "python3 - <<'PY'
import sys
sys.path.insert(0, '/tmp/ray/jobs')
from utils.gpu_yield import yield_gpu_for_training
print('[sync] gpu_yield import ok:', callable(yield_gpu_for_training))
PY"

echo "[run] python3 $CONTAINER_TRAIN_DIR/train_phase10_multiscale.py $*"
exec docker exec -it "$RAY_CONTAINER" python3 "$CONTAINER_TRAIN_DIR/train_phase10_multiscale.py" "$@"
