#!/usr/bin/env bash
# =============================================================================
# shl_nano_pipeline.sh — Full Track 8 nanochat pipeline orchestrator.
#
# Runs each stage only if not already completed (state tracked via .state/ dir).
# Safe to re-run: skips completed stages, retries only failed ones.
#
# Stages:
#   1. Export training data from Postgres
#   2. Clone nanochat + base pretrain (d8, GPU 1)
#   3. SFT on platform conversations (GPU 1)
#   4. Start OpenAI-compat server (GPU 1, port 8021)
#   5. Export watchdog audit log + generate synthetic data
#   6. Update Obsidian Kanban board
#
# Memory safety — ALL GPU work uses CUDA_VISIBLE_DEVICES=1 (RTX 2070).
# Will wait and retry for up to 30min if GPU 1 is insufficient.
#
# Usage:
#   bash scripts/data/shl_nano_pipeline.sh [--force] [--stage N] [--dry-run]
#
#   --force       Re-run all stages even if state files exist
#   --stage N     Run from stage N onwards (1–5)
#   --dry-run     Print what would happen; no training or file writes
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE_DIR="$PLATFORM_DIR/data/shl-nano/.state"
LOG_DIR="$PLATFORM_DIR/logs"
NANO_DIR="$PLATFORM_DIR/inference/shl-nano"
DATA_DIR="$PLATFORM_DIR/data/shl-nano"
GITLAB_UTIL="$PLATFORM_DIR/scripts/platform/gitlab_utils.py"
CURRENT_STAGE_NUMBER="0"
CURRENT_STAGE_NAME=""
CURRENT_STAGE_ISSUE=""

FORCE=false
START_STAGE=1
DRY_RUN=false
for arg in "$@"; do
    case "$arg" in
        --force)        FORCE=true ;;
        --dry-run)      DRY_RUN=true ;;
        --stage)        ;;
        --stage=*)      START_STAGE="${arg#--stage=}" ;;
    esac
done
# Handle "--stage N" (two tokens: --stage followed by number)
_prev=""
for _arg in "$@"; do
    if [[ "$_prev" == "--stage" ]]; then
        START_STAGE="$_arg"
    fi
    _prev="$_arg"
done
unset _prev _arg

# ── ANSI colours ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BLU='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${GRN}[T8 pipeline]${NC} $*" | tee -a "$LOG_DIR/shl_nano_pipeline.log"; }
warn()    { echo -e "${YLW}[T8 pipeline WARN]${NC} $*" | tee -a "$LOG_DIR/shl_nano_pipeline.log"; }
error()   { echo -e "${RED}[T8 pipeline ERROR]${NC} $*" | tee -a "$LOG_DIR/shl_nano_pipeline.log" >&2; exit 1; }
stage()   { echo -e "\n${BLU}━━━ Stage $1: $2 ━━━${NC}" | tee -a "$LOG_DIR/shl_nano_pipeline.log"; }
done_()   { touch "$STATE_DIR/$1"; info "✓ Stage marked complete: $1"; }
skip_()   { info "↩ Skipping stage (already done): $1  (use --force to re-run)"; }

mkdir -p "$STATE_DIR" "$LOG_DIR" "$DATA_DIR"
echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Pipeline started (stage=$START_STAGE force=$FORCE dry_run=$DRY_RUN)" \
    >> "$LOG_DIR/shl_nano_pipeline.log"

# ── Telegram notify helper ────────────────────────────────────────────────────
_tg() {
    local msg="$1"
    [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]] && return 0
    curl -sf -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}&text=${msg}&parse_mode=Markdown" \
        --max-time 5 >/dev/null 2>&1 || true
}

has_gitlab_event_support() {
    if [[ ! -f "$GITLAB_UTIL" ]]; then
        return 1
    fi
    if [[ -n "${GITLAB_API_TOKEN:-}" || -n "${GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN:-}" ]]; then
        return 0
    fi
    [[ -f "$PLATFORM_DIR/.env" ]] && grep -qE '^GITLAB_(API_TOKEN|AXELOFWAR_PERSONAL_ACCESS_TOKEN)=' "$PLATFORM_DIR/.env"
}

pipeline_issue_for_stage() {
    case "$1" in
        1) echo "T8.1" ;;
        2) echo "T8.2" ;;
        3) echo "T8.3" ;;
        4) echo "T8.4" ;;
        5) echo "T8.5" ;;
        6) echo "Track 8: nanochat" ;;
        *) echo "Track 8: nanochat" ;;
    esac
}

gitlab_pipeline_event() {
    local title="$1"
    local status="$2"
    local comment="$3"
    local labels="${4:-component::agent-service,source::pipeline}"
    local description="${5:-}"

    has_gitlab_event_support || return 0
    python3 "$GITLAB_UTIL" sync-issue "$title" \
        --title "$title" \
        --status "$status" \
        --labels "$labels" \
        --description "$description" \
        --comment "$comment" \
        --reopen >/dev/null 2>&1 || true
}

gitlab_pipeline_resolve() {
    local title="$1"
    local comment="$2"

    has_gitlab_event_support || return 0
    python3 "$GITLAB_UTIL" resolve-issue "$title" \
        --comment "$comment" >/dev/null 2>&1 || true
}

stage() {
    CURRENT_STAGE_NUMBER="$1"
    CURRENT_STAGE_NAME="$2"
    CURRENT_STAGE_ISSUE="$(pipeline_issue_for_stage "$1")"
    echo -e "\n${BLU}━━━ Stage $1: $2 ━━━${NC}" | tee -a "$LOG_DIR/shl_nano_pipeline.log"
    if [[ "$DRY_RUN" == "false" && "$1" != "6" ]]; then
        gitlab_pipeline_event \
            "$CURRENT_STAGE_ISSUE" \
            "status::in-progress" \
            "🔄 Event-driven pipeline update: Stage $1 started — $2." \
            "component::agent-service,source::pipeline,type::training"
    fi
}

done_() {
    touch "$STATE_DIR/$1"
    info "✓ Stage marked complete: $1"
    if [[ "$DRY_RUN" == "false" && -n "$CURRENT_STAGE_ISSUE" && "$CURRENT_STAGE_NUMBER" != "6" ]]; then
        gitlab_pipeline_resolve \
            "$CURRENT_STAGE_ISSUE" \
            "✅ Event-driven pipeline update: Stage ${CURRENT_STAGE_NUMBER} completed — ${CURRENT_STAGE_NAME}."
    fi
}

on_pipeline_error() {
    local exit_code=$?
    if [[ "$DRY_RUN" == "false" ]]; then
        local stage_desc="stage ${CURRENT_STAGE_NUMBER:-unknown}: ${CURRENT_STAGE_NAME:-unknown}"
        gitlab_pipeline_event \
            "T8 Pipeline Failure" \
            "status::todo" \
            "❌ Event-driven pipeline failure during ${stage_desc}. See logs/shl_nano_pipeline.log for details." \
            "component::agent-service,source::pipeline,type::bug,priority::high" \
            "Track 8 pipeline automation failed during ${stage_desc}."
        if [[ -n "$CURRENT_STAGE_ISSUE" && "$CURRENT_STAGE_NUMBER" != "6" ]]; then
            gitlab_pipeline_event \
                "$CURRENT_STAGE_ISSUE" \
                "status::blocked" \
                "❌ Event-driven pipeline update: ${stage_desc} failed. Investigation required." \
                "component::agent-service,source::pipeline"
        fi
    fi
    return "$exit_code"
}

trap 'on_pipeline_error' ERR

# ── GPU 1 availability check (wait up to 30m) ─────────────────────────────────
wait_for_gpu() {
    local min_mib="${1:-5120}"
    local max_wait=1800   # 30 min
    local waited=0
    while true; do
        local free_mib
        free_mib=$(nvidia-smi --id=1 --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | tr -d ' ' || echo "9999")
        if (( free_mib >= min_mib )); then
            info "GPU 1 ready: ${free_mib} MiB free"
            return 0
        fi
        warn "GPU 1 only ${free_mib} MiB free (need ${min_mib}). Waiting 60s … (${waited}s elapsed)"
        sleep 60
        waited=$(( waited + 60 ))
        if (( waited >= max_wait )); then
            error "GPU 1 still insufficient after ${max_wait}s. Aborting."
        fi
    done
}

# ── Source .env for Telegram creds ────────────────────────────────────────────
ENV_FILE="$PLATFORM_DIR/ray_compute/.env"
if [[ -f "$ENV_FILE" ]]; then
    # Disable -eu while sourcing — .env may have self-referential ${VAR} placeholders
    set +eu; set -a; source "$ENV_FILE" 2>/dev/null || true; set +a; set -eu
fi

PYTHON="${NANO_DIR}/.venv/bin/python"
PLATFORM_PYTHON="${PLATFORM_DIR}/.venv/bin/python3"

_tg "🔬 *SHL Nano Pipeline* started — stage=${START_STAGE} dry_run=${DRY_RUN}"
if [[ "$DRY_RUN" == "false" ]]; then
    gitlab_pipeline_event \
        "Track 8: nanochat" \
        "status::in-progress" \
        "🔄 Event-driven pipeline update: Track 8 pipeline run started (stage=${START_STAGE}, force=${FORCE})." \
        "component::agent-service,source::pipeline,type::training"
fi

# =============================================================================
# Stage 1 — Export training data
# =============================================================================
if (( START_STAGE <= 1 )); then
    stage 1 "Export training data from Postgres"
    if [[ "$FORCE" == "true" ]] || [[ ! -f "$STATE_DIR/data_exported" ]]; then
        if [[ "$DRY_RUN" == "true" ]]; then
            info "[dry-run] would run export_shl_nano_training_data.py"
        else
            # shml-postgres has no host-exposed port — detect Docker network IP
            _pg_host="localhost"
            _pg_port="5432"
            _docker_ip=$(docker inspect shml-postgres \
                --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
                2>/dev/null | tr -d ' \n' || true)
            if [[ -n "$_docker_ip" ]]; then
                _pg_host="$_docker_ip"
                info "Using Docker network IP for postgres: ${_pg_host}"
            fi
            ${PLATFORM_PYTHON:-python3} \
                "$SCRIPT_DIR/export_shl_nano_training_data.py" \
                --out-dir "$DATA_DIR" \
                --pg-host "$_pg_host" \
                --pg-port "$_pg_port" \
                --pg-db inference \
                --pg-user inference \
                --pg-pass "cc43YZwqiLKE4gEOW7WyRMvzZ58rIXwG" \
                2>&1 | tee -a "$LOG_DIR/shl_nano_pipeline.log"
            done_ "data_exported"
        fi
    else skip_ "data_exported"; fi
fi

# =============================================================================
# Stage 2 — Clone nanochat + base pretrain
# =============================================================================
if (( START_STAGE <= 2 )); then
    stage 2 "Clone nanochat + d8 base pretrain (GPU 1, ~45min)"
    if [[ "$FORCE" == "true" ]] || [[ ! -f "$STATE_DIR/base_trained" ]]; then
        if [[ "$DRY_RUN" == "true" ]]; then
            info "[dry-run] would run setup_shl_nano.sh"
        else
            wait_for_gpu 5120
            _tg "⚡ *Stage 2*: Starting d8 base pretrain on GPU 1 (~45 min)"
            bash "$SCRIPT_DIR/setup_shl_nano.sh" \
                2>&1 | tee -a "$LOG_DIR/shl_nano_pipeline.log"
            done_ "base_trained"
            _tg "✅ *Stage 2 done*: base pretrain complete"
        fi
    else skip_ "base_trained"; fi
fi

# =============================================================================
# Stage 3 — SFT on platform conversations
# =============================================================================
if (( START_STAGE <= 3 )); then
    stage 3 "SFT on SHL platform data (GPU 1, ~1hr)"
    if [[ "$FORCE" == "true" ]] || [[ ! -f "$STATE_DIR/sft_done" ]]; then
        if [[ "$DRY_RUN" == "true" ]]; then
            info "[dry-run] would run run_shl_nano_sft.sh"
        else
            wait_for_gpu 5120
            _tg "⚡ *Stage 3*: Starting SFT on GPU 1 (~60 min)"
            bash "$SCRIPT_DIR/run_shl_nano_sft.sh" \
                2>&1 | tee -a "$LOG_DIR/shl_nano_pipeline.log"
            done_ "sft_done"
            _tg "✅ *Stage 3 done*: SFT complete"
        fi
    else skip_ "sft_done"; fi
fi

# =============================================================================
# Stage 4 — Start inference server (background, systemd-managed after first run)
# =============================================================================
if (( START_STAGE <= 4 )); then
    stage 4 "Start shl-nano inference server (port 8021)"
    if [[ "$FORCE" == "true" ]] || [[ ! -f "$STATE_DIR/server_started" ]]; then
        if [[ "$DRY_RUN" == "true" ]]; then
            info "[dry-run] would start shl-nano server"
        else
            # Check if already running
            if curl -sf http://localhost:8021/health >/dev/null 2>&1; then
                info "shl-nano server already running at :8021"
            else
                wait_for_gpu 2048
                nohup bash "$SCRIPT_DIR/start_shl_nano_server.sh" \
                    >> "$LOG_DIR/shl-nano-server.log" 2>&1 &
                # Wait up to 60s for startup
                for i in $(seq 1 12); do
                    sleep 5
                    if curl -sf http://localhost:8021/health >/dev/null 2>&1; then
                        info "Server up after ${i}x5s"
                        break
                    fi
                done
                curl -sf http://localhost:8021/health && info "Health check OK" || \
                    warn "Server may still be loading weights — check logs/shl-nano-server.log"
                _tg "🚀 *Stage 4*: shl-nano server running at :8021"
            fi
            done_ "server_started"
        fi
    else skip_ "server_started"; fi
fi

# =============================================================================
# Stage 5 — Watchdog training data export + synthetic generation
# =============================================================================
if (( START_STAGE <= 5 )); then
    stage 5 "Export watchdog audit data + generate synthetic pairs"
    if [[ "$FORCE" == "true" ]] || [[ ! -f "$STATE_DIR/watchdog_data_done" ]]; then
        if [[ "$DRY_RUN" == "true" ]]; then
            info "[dry-run] would export watchdog + generate 200 synthetic examples"
        else
            # Export real audit log (may be empty early on)
            AUDIT_LOG=""
            for path in /var/log/watchdog/audit.log \
                        "$LOG_DIR/watchdog/audit.log" \
                        "$(docker inspect shml-watchdog --format '{{.LogPath}}' 2>/dev/null || echo '')"; do
                [[ -f "$path" ]] && { AUDIT_LOG="$path"; break; }
            done

            ${PLATFORM_PYTHON:-python3} "$SCRIPT_DIR/export_watchdog_training_data.py" \
                --log "${AUDIT_LOG:-/var/log/watchdog/audit.log}" \
                --out "$DATA_DIR/watchdog_audit.jsonl" \
                2>&1 | tee -a "$LOG_DIR/shl_nano_pipeline.log" || true

            # Generate synthetic data if gateway reachable
            GATEWAY="${GATEWAY_URL:-http://localhost:8081}"
            if curl -sf "${GATEWAY}/health" >/dev/null 2>&1 || \
               curl -sf "${GATEWAY}/v1/models" >/dev/null 2>&1; then
                info "Gateway reachable at $GATEWAY — generating 200 synthetic examples"
                ${PLATFORM_PYTHON:-python3} "$SCRIPT_DIR/gen_watchdog_synthetic_data.py" \
                    --n 200 \
                    --out "$DATA_DIR/watchdog_synthetic.jsonl" \
                    --gateway "$GATEWAY" \
                    2>&1 | tee -a "$LOG_DIR/shl_nano_pipeline.log"
            else
                warn "Gateway not reachable at $GATEWAY — skipping synthetic generation"
                warn "Run manually: python scripts/data/gen_watchdog_synthetic_data.py --n 200"
            fi
            done_ "watchdog_data_done"
        fi
    else skip_ "watchdog_data_done"; fi
fi

# =============================================================================
# Stage 6 — Sync GitLab Issues
# =============================================================================
stage 6 "Sync GitLab Issues"
if [[ "$DRY_RUN" == "false" ]]; then
    bash "$SCRIPT_DIR/update_gitlab_board.sh" \
        2>&1 | tee -a "$LOG_DIR/shl_nano_pipeline.log" || \
        warn "GitLab issue sync failed (non-fatal)"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
info "═══════════════════════════════════════════════════════════"
info "Pipeline complete. State files:"
ls "$STATE_DIR/" 2>/dev/null | sed "s/^/  ✓ /" || info "  (none yet — dry run)"
echo ""
info "Next steps:"
[[ ! -f "$STATE_DIR/data_exported" ]]   && info "  • Re-run stage 1: --stage=1"
[[ ! -f "$STATE_DIR/base_trained" ]]    && info "  • Re-run stage 2: --stage=2"
[[ ! -f "$STATE_DIR/sft_done" ]]        && info "  • Re-run stage 3: --stage=3"
[[ ! -f "$STATE_DIR/server_started" ]]  && info "  • Re-run stage 4: --stage=4"
if [[ -f "$STATE_DIR/sft_done" ]] && ! curl -sf http://localhost:8021/health >/dev/null 2>&1; then
    info "  • Activate tier-0: set NANO_ENDPOINT=http://shl-nano:8021 in agent-service env"
fi
info "═══════════════════════════════════════════════════════════"

_tg "🏁 *T8 pipeline complete* — all stages done"
if [[ "$DRY_RUN" == "false" ]]; then
    gitlab_pipeline_resolve \
        "T8 Pipeline Failure" \
        "✅ Event-driven pipeline update: Track 8 pipeline completed successfully at $(date -u '+%Y-%m-%d %H:%M UTC')."
fi
