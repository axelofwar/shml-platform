#!/usr/bin/env bash
# =============================================================================
# update_gitlab_board.sh — Sync platform state files → GitLab Issues board.
#
# Replaces the Obsidian-only update_kanban.sh for GitLab-first tracking.
# Reads .state/ files and live service status, then transitions GitLab issue
# labels (status::backlog → status::in-progress → status::done) accordingly.
#
# Called by shl-nano-kanban.timer every 10min (alongside scan_repo_state.sh),
# and also directly callable:
#   bash scripts/data/update_gitlab_board.sh
#
# Requires:
#   GITLAB_API_TOKEN  — personal access token with api scope
#   GITLAB_PROJECT_ID — numeric project ID (default: 2)
#   GITLAB_URL        — base URL (default: http://shml-gitlab:8929)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
GITLAB_UTILS="$PLATFORM_DIR/scripts/platform/gitlab_utils.py"
STATE_DIR="$PLATFORM_DIR/data/shl-nano/.state"

# Load .env if available (best-effort)
_env_file="$PLATFORM_DIR/ray_compute/.env"
if [[ -f "$_env_file" ]]; then
    set +eu; set -a; source "$_env_file" 2>/dev/null || true; set +a; set -eu
fi

log() { echo "[board $(date '+%H:%M:%S')] $*"; }

# Check token is available
if [[ -z "${GITLAB_API_TOKEN:-}" ]]; then
    log "GITLAB_API_TOKEN not set — skipping GitLab board sync"
    exit 0
fi

_state()   { [[ -f "$STATE_DIR/$1" ]] && echo true || echo false; }

S1=$(_state "data_exported")
S2=$(_state "base_trained")
S3=$(_state "sft_done")
S4=$(_state "server_started")

SERVER_UP=false
curl -sf --max-time 2 http://localhost:8021/health >/dev/null 2>&1 && SERVER_UP=true || true

gl_transition() {
    # gl_transition <issue_title_search> <from_label> <to_label>
    local title="$1" from_label="$2" to_label="$3"
    python3 "$GITLAB_UTILS" upsert-issue "$title" \
        --remove-label "$from_label" \
        --add-label "$to_label" 2>/dev/null || true
}

# ── T8.1 Data Export ─────────────────────────────────────────────────────────
if [[ "$S1" == "true" ]]; then
    log "T8.1: data_exported → marking done"
    gl_transition "Phase 0.1: GitLab project" "status::in-progress" "status::done" || true
fi

# ── T8.2 Base Pretrain ───────────────────────────────────────────────────────
if [[ "$S2" == "true" ]]; then
    log "T8.2: base_trained → marking done"
    gl_transition "T8.2" "status::in-progress" "status::done" || true
elif [[ "$S1" == "true" ]]; then
    log "T8.2: data ready → moving to in-progress"
    gl_transition "T8.2" "status::backlog" "status::in-progress" || true
fi

# ── T8.3 SFT ─────────────────────────────────────────────────────────────────
if [[ "$S3" == "true" ]]; then
    log "T8.3: sft_done → marking done"
    gl_transition "T8.3" "status::in-progress" "status::done" || true
elif [[ "$S2" == "true" ]]; then
    log "T8.3: pretrain done → moving to in-progress"
    gl_transition "T8.3" "status::backlog" "status::in-progress" || true
fi

# ── T8.4 Server ──────────────────────────────────────────────────────────────
if [[ "$SERVER_UP" == "true" ]]; then
    log "T8.4: server live → marking done"
    gl_transition "T8.4" "status::in-progress" "status::done" || true
elif [[ "$S3" == "true" ]]; then
    log "T8.4: SFT done → moving to in-progress"
    gl_transition "T8.4" "status::backlog" "status::in-progress" || true
fi

log "GitLab board sync complete"
