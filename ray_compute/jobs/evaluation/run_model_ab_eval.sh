#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# A/B Model Evaluation Runner
# ═══════════════════════════════════════════════════════════════════════════
#
# Runs Nemotron and Qwen3.5 sequentially on GPU 0, collecting full eval
# results for each, then compares them side-by-side.
#
# Since both models require the RTX 3090 Ti (24GB), they cannot run
# simultaneously. This script manages the lifecycle:
#
#   1. Stop any running coding model
#   2. Start Nemotron → wait for health → run eval → save results → stop
#   3. Start Qwen → wait for health → run eval → save results → stop
#   4. Merge results and print comparison
#   5. Restart the winner (or Nemotron by default)
#
# Usage:
#   bash ray_compute/jobs/evaluation/run_model_ab_eval.sh [OPTIONS]
#
# Options:
#   --category CATEGORY    Task category: all|coding|tool_use|long_context|ecosystem (default: all)
#   --no-restart           Don't restart any model after eval
#   --restart MODEL        Which model to restart: winner|nemotron|qwen (default: nemotron)
#   --skip-nemotron        Skip Nemotron eval (use existing results)
#   --skip-qwen            Skip Qwen eval (use existing results)
#   --timeout SECS         Health check timeout in seconds (default: 180)
#
# Requirements:
#   - Docker with NVIDIA runtime
#   - Nemotron GGUF at data/models/nemotron-3/
#   - Qwen GGUF at data/models/qwen3.5/
#   - Python 3 with httpx
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
RESULTS_DIR="$PLATFORM_ROOT/ray_compute/jobs/evaluation/results"
EVAL_SCRIPT="$PLATFORM_ROOT/ray_compute/jobs/evaluation/eval_coding_model.py"

NEMOTRON_COMPOSE="$PLATFORM_ROOT/inference/nemotron/docker-compose.yml"
QWEN_COMPOSE="$PLATFORM_ROOT/inference/qwen/docker-compose.yml"

# Nemotron uses Traefik (no direct port), so we expose it temporarily
NEMOTRON_EVAL_PORT=8010
QWEN_EVAL_PORT=8020
NEMOTRON_INTERNAL_PORT=8000
QWEN_INTERNAL_PORT=8000

CATEGORY="all"
RESTART_MODEL="nemotron"
SKIP_NEMOTRON=false
SKIP_QWEN=false
HEALTH_TIMEOUT=180
NO_RESTART=false

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# ── Parse Arguments ───────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case $1 in
        --category) CATEGORY="$2"; shift 2 ;;
        --no-restart) NO_RESTART=true; shift ;;
        --restart) RESTART_MODEL="$2"; shift 2 ;;
        --skip-nemotron) SKIP_NEMOTRON=true; shift ;;
        --skip-qwen) SKIP_QWEN=true; shift ;;
        --timeout) HEALTH_TIMEOUT="$2"; shift 2 ;;
        --help|-h)
            head -35 "$0" | tail -30
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────

log() { echo -e "\n\033[1;36m══ $1\033[0m"; }
warn() { echo -e "\033[1;33m⚠  $1\033[0m"; }
err() { echo -e "\033[1;31m✗  $1\033[0m"; }
ok() { echo -e "\033[1;32m✓  $1\033[0m"; }

wait_for_health() {
    local url="$1"
    local name="$2"
    local timeout="${3:-$HEALTH_TIMEOUT}"
    local elapsed=0
    local interval=5

    log "Waiting for $name to become healthy ($url)..."

    while [[ $elapsed -lt $timeout ]]; do
        if curl -sf "$url" > /dev/null 2>&1; then
            ok "$name is healthy (${elapsed}s)"
            return 0
        fi
        sleep $interval
        elapsed=$((elapsed + interval))
        echo -n "."
    done

    err "$name failed to start within ${timeout}s"
    return 1
}

stop_model() {
    local compose_file="$1"
    local name="$2"

    if docker compose -f "$compose_file" ps --status running 2>/dev/null | grep -q .; then
        log "Stopping $name..."
        docker compose -f "$compose_file" down --timeout 10 2>/dev/null || true
        # Wait for GPU memory to free
        sleep 5
        ok "$name stopped"
    else
        echo "  $name not running"
    fi
}

start_model_for_eval() {
    local compose_file="$1"
    local name="$2"
    local port="$3"
    local internal_port="$4"

    log "Starting $name for evaluation..."

    # For Nemotron: it doesn't expose ports directly (Traefik-only),
    # so we use docker run with port mapping or a temporary override.
    # For Qwen: port 8020 is already mapped in the compose file.
    docker compose -f "$compose_file" up -d 2>&1

    # Wait for the container to be healthy
    local health_url
    if [[ "$name" == "nemotron" ]]; then
        # Nemotron doesn't expose ports directly; access via container network
        # We'll use docker exec to check health, then use a temp port forward
        local container="nemotron-coding"
        # Start a port forward in the background
        docker run -d --name "nemotron-eval-proxy" \
            --network shml-platform \
            -p "${port}:${internal_port}" \
            alpine/socat \
            "TCP-LISTEN:${internal_port},fork,reuseaddr" \
            "TCP:${container}:${internal_port}" 2>/dev/null || {
                # If socat container fails, try direct port publish
                warn "socat proxy failed, trying docker compose port override..."
                docker compose -f "$compose_file" down --timeout 5 2>/dev/null || true
                sleep 2
                # Start with port override
                NEMOTRON_EVAL_PORT_OVERRIDE="${port}:${internal_port}" \
                    docker compose -f "$compose_file" up -d \
                    --scale nemotron-manager=0 2>&1
            }
        health_url="http://localhost:${port}/health"
    else
        health_url="http://localhost:${port}/health"
    fi

    wait_for_health "$health_url" "$name"
}

cleanup_nemotron_proxy() {
    docker rm -f nemotron-eval-proxy 2>/dev/null || true
}

gpu_memory_free() {
    nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits -i 0 2>/dev/null | tr -d ' '
}

# ── Main ──────────────────────────────────────────────────────────────────

main() {
    log "A/B Model Evaluation — $TIMESTAMP"
    echo "  Category: $CATEGORY"
    echo "  Results:  $RESULTS_DIR/"
    echo "  Timeout:  ${HEALTH_TIMEOUT}s"

    mkdir -p "$RESULTS_DIR"

    # Check prerequisites
    if [[ ! -f "$EVAL_SCRIPT" ]]; then
        err "Eval script not found: $EVAL_SCRIPT"
        exit 1
    fi

    # ── Phase 1: Stop any running coding models ──

    log "Phase 1: Clearing GPU 0 for evaluation"
    stop_model "$NEMOTRON_COMPOSE" "Nemotron"
    stop_model "$QWEN_COMPOSE" "Qwen"
    cleanup_nemotron_proxy

    local free_mb
    free_mb=$(gpu_memory_free)
    ok "GPU 0 free memory: ${free_mb}MB"

    # ── Phase 2: Evaluate Nemotron ──

    NEMOTRON_RESULTS="$RESULTS_DIR/nemotron_${TIMESTAMP}.json"

    if [[ "$SKIP_NEMOTRON" == true ]]; then
        warn "Skipping Nemotron evaluation (--skip-nemotron)"
        # Find latest nemotron results
        NEMOTRON_RESULTS=$(ls -t "$RESULTS_DIR"/nemotron_*.json 2>/dev/null | head -1 || echo "")
        if [[ -z "$NEMOTRON_RESULTS" ]]; then
            warn "No existing Nemotron results found"
        fi
    else
        log "Phase 2: Evaluating Nemotron (Nemotron-3-Nano-30B-A3B)"

        start_model_for_eval "$NEMOTRON_COMPOSE" "nemotron" "$NEMOTRON_EVAL_PORT" "$NEMOTRON_INTERNAL_PORT"

        python3 "$EVAL_SCRIPT" \
            --target nemotron \
            --nemotron-url "http://localhost:${NEMOTRON_EVAL_PORT}/v1" \
            --category "$CATEGORY" \
            --output "$NEMOTRON_RESULTS" \
            2>&1 | tee "$RESULTS_DIR/nemotron_${TIMESTAMP}.log"

        ok "Nemotron results saved: $NEMOTRON_RESULTS"

        # Stop Nemotron and free GPU
        stop_model "$NEMOTRON_COMPOSE" "Nemotron"
        cleanup_nemotron_proxy
        sleep 5  # Let GPU memory fully release
    fi

    # ── Phase 3: Evaluate Qwen ──

    QWEN_RESULTS="$RESULTS_DIR/qwen_${TIMESTAMP}.json"

    if [[ "$SKIP_QWEN" == true ]]; then
        warn "Skipping Qwen evaluation (--skip-qwen)"
        QWEN_RESULTS=$(ls -t "$RESULTS_DIR"/qwen_*.json 2>/dev/null | head -1 || echo "")
        if [[ -z "$QWEN_RESULTS" ]]; then
            warn "No existing Qwen results found"
        fi
    else
        log "Phase 3: Evaluating Qwen (Qwen3.5-35B-A3B)"

        start_model_for_eval "$QWEN_COMPOSE" "qwen" "$QWEN_EVAL_PORT" "$QWEN_INTERNAL_PORT"

        python3 "$EVAL_SCRIPT" \
            --target qwen \
            --qwen-url "http://localhost:${QWEN_EVAL_PORT}/v1" \
            --category "$CATEGORY" \
            --output "$QWEN_RESULTS" \
            2>&1 | tee "$RESULTS_DIR/qwen_${TIMESTAMP}.log"

        ok "Qwen results saved: $QWEN_RESULTS"

        # Stop Qwen and free GPU
        stop_model "$QWEN_COMPOSE" "Qwen"
        sleep 5
    fi

    # ── Phase 4: Comparison ──

    if [[ -n "$NEMOTRON_RESULTS" && -f "$NEMOTRON_RESULTS" && \
          -n "$QWEN_RESULTS" && -f "$QWEN_RESULTS" ]]; then
        log "Phase 4: Head-to-head comparison"

        python3 -c "
import json, sys

with open('$NEMOTRON_RESULTS') as f:
    nemotron = json.load(f)
with open('$QWEN_RESULTS') as f:
    qwen = json.load(f)

n_results = nemotron.get('results', {}).get('nemotron', [])
q_results = qwen.get('results', {}).get('qwen', [])

# Aggregate by category
categories = {}
for r in n_results:
    cat = r.get('category', 'unknown')
    categories.setdefault(cat, {'nemotron': [], 'qwen': []})
    categories[cat]['nemotron'].append(r)
for r in q_results:
    cat = r.get('category', 'unknown')
    categories.setdefault(cat, {'nemotron': [], 'qwen': []})
    categories[cat]['qwen'].append(r)

print()
print('=' * 80)
print('  A/B EVALUATION RESULTS')
print('=' * 80)

n_total_passed = 0
n_total_checks = 0
q_total_passed = 0
q_total_checks = 0

for cat, data in sorted(categories.items()):
    print(f'\n  ── {cat.upper()} ──')
    print(f\"  {'Task':<35s} {'Nemotron':>10s} {'Qwen':>10s} {'Winner':>10s}\")
    print(f'  {\"─\" * 67}')

    for nr in data['nemotron']:
        task_id = nr['task_id']
        qr = next((q for q in data['qwen'] if q['task_id'] == task_id), None)

        n_score = f\"{nr['checks_passed']}/{nr['checks_total']}\"
        n_total_passed += nr['checks_passed']
        n_total_checks += nr['checks_total']

        if qr and not qr.get('skipped'):
            q_score = f\"{qr['checks_passed']}/{qr['checks_total']}\"
            q_total_passed += qr['checks_passed']
            q_total_checks += qr['checks_total']
            if nr['checks_passed'] > qr['checks_passed']:
                winner = 'Nemotron'
            elif qr['checks_passed'] > nr['checks_passed']:
                winner = 'Qwen'
            else:
                winner = 'Tie'
        else:
            q_score = 'N/A'
            winner = ''

        name = nr.get('task_name', task_id)[:35]
        print(f'  {name:<35s} {n_score:>10s} {q_score:>10s} {winner:>10s}')

n_pct = n_total_passed / max(1, n_total_checks) * 100
q_pct = q_total_passed / max(1, q_total_checks) * 100

print()
print('=' * 80)
print(f'  OVERALL: Nemotron {n_total_passed}/{n_total_checks} ({n_pct:.0f}%) | Qwen {q_total_passed}/{q_total_checks} ({q_pct:.0f}%)')
winner = 'Qwen' if q_pct > n_pct else 'Nemotron' if n_pct > q_pct else 'Tie'
print(f'  RECOMMENDATION: {winner}')
print('=' * 80)
print()
" 2>&1 | tee "$RESULTS_DIR/comparison_${TIMESTAMP}.txt"

    else
        warn "Cannot compare — missing results for one or both models"
    fi

    # ── Phase 5: Restart preferred model ──

    if [[ "$NO_RESTART" == true ]]; then
        log "Phase 5: Skipping model restart (--no-restart)"
    else
        local restart_target="$RESTART_MODEL"
        log "Phase 5: Restarting $restart_target"

        if [[ "$restart_target" == "nemotron" ]]; then
            docker compose -f "$NEMOTRON_COMPOSE" up -d 2>&1
            wait_for_health "http://localhost:${NEMOTRON_EVAL_PORT}/health" "Nemotron" 120 || \
                warn "Nemotron restart may not have direct port access (Traefik-only)"
        elif [[ "$restart_target" == "qwen" ]]; then
            docker compose -f "$QWEN_COMPOSE" up -d 2>&1
            wait_for_health "http://localhost:${QWEN_EVAL_PORT}/health" "Qwen" 120
        fi
    fi

    log "A/B Evaluation Complete"
    echo "  Results:    $RESULTS_DIR/"
    echo "  Nemotron:   ${NEMOTRON_RESULTS:-N/A}"
    echo "  Qwen:       ${QWEN_RESULTS:-N/A}"
    echo "  Comparison: $RESULTS_DIR/comparison_${TIMESTAMP}.txt"
    echo "  Timestamp:  $TIMESTAMP"
}

# ── Trap for cleanup ──────────────────────────────────────────────────────

cleanup() {
    cleanup_nemotron_proxy
    echo ""
    warn "Evaluation interrupted. GPU may still have a model loaded."
    warn "Run: docker compose -f inference/nemotron/docker-compose.yml down"
    warn "Run: docker compose -f inference/qwen/docker-compose.yml down"
}
trap cleanup EXIT

main "$@"

# Remove trap on clean exit
trap - EXIT
