#!/usr/bin/env bash
# ==============================================================================
# update_gitlab_board.sh — Sync SHL-Nano T8 pipeline state → GitLab Issues.
#
# Called by shl-gitlab-sync.timer every 10min and by shl_nano_pipeline.sh.
#
# Reads .state/ checkpoint files and resolves matching GitLab T8 issues when
# each stage finishes.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE_DIR="$PLATFORM_DIR/data/shl-nano/.state"
GITLAB_UTIL="$PLATFORM_DIR/scripts/platform/gitlab_utils.py"

_state() { [[ -f "$STATE_DIR/$1" ]] && echo true || echo false; }
_ts()    { [[ -f "$STATE_DIR/$1" ]] && date -r "$STATE_DIR/$1" '+%Y-%m-%d %H:%M' || echo "—"; }

log() { echo "[gitlab_board $(date '+%H:%M:%S')] $*"; }

# ── Check GitLab credentials ────────────────────────────────────────────────
HAS_GITLAB_TOKEN=false
if [[ -n "${GITLAB_API_TOKEN:-}" || -n "${GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN:-}" ]]; then
    HAS_GITLAB_TOKEN=true
elif [[ -f "$PLATFORM_DIR/.env" ]] && grep -qE '^GITLAB_(API_TOKEN|AXELOFWAR_PERSONAL_ACCESS_TOKEN)=' "$PLATFORM_DIR/.env"; then
    HAS_GITLAB_TOKEN=true
fi

if ! $HAS_GITLAB_TOKEN; then
    log "WARN: No GitLab PAT found in env or .env — skipping GitLab sync"
    exit 0
fi
if [[ ! -f "$GITLAB_UTIL" ]]; then
    log "WARN: $GITLAB_UTIL not found — skipping"
    exit 0
fi

# ── Read pipeline state ──────────────────────────────────────────────────────
S1=$(_state "data_exported");       T1=$(_ts "data_exported")
S2=$(_state "base_trained");        T2=$(_ts "base_trained")
S3=$(_state "sft_done");            T3=$(_ts "sft_done")
S4=$(_state "server_started");      T4=$(_ts "server_started")
S5=$(_state "watchdog_data_done");  T5=$(_ts "watchdog_data_done")

SERVER_UP=false
curl -sf --max-time 2 http://localhost:8021/health >/dev/null 2>&1 && SERVER_UP=true || true

log "T8 state: S1=$S1 S2=$S2 S3=$S3 S4=$S4 S5=$S5 server=$SERVER_UP"

_gl() {
    python3 "$GITLAB_UTIL" "$@" 2>&1 | sed 's/^/[gitlab] /' || true
}

# ── Transition issues based on completed checkpoints ────────────────────────
$S1 && _gl resolve-issue "T8.1" \
    --comment "✅ T8.1 data_exported checkpoint reached at ${T1}"

$S2 && _gl resolve-issue "T8.2" \
    --comment "✅ T8.2 base_trained checkpoint reached at ${T2}"

$S3 && _gl resolve-issue "T8.3 SFT" \
    --comment "✅ T8.3 sft_done checkpoint reached at ${T3}"

$S4 && _gl resolve-issue "T8.4" \
    --comment "✅ T8.4 server_started at ${T4}"

$S5 && _gl resolve-issue "T8.5" \
    --comment "✅ T8.5 watchdog_data_done at ${T5}"

# Full pipeline done + server running → resolve the T8 milestone issue
if $S1 && $S2 && $S3 && $S4 && $SERVER_UP; then
    _gl resolve-issue "Track 8: nanochat" \
        --comment "✅ Full T8 pipeline complete. Server live at :8021 ($(date -u '+%Y-%m-%d %H:%M UTC'))"
fi

log "GitLab board sync complete"
