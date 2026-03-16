#!/usr/bin/env bash
# =============================================================================
# scan_repo_state.sh — Periodic repo + service scanner that keeps KANBAN.md
#                      in sync with actual platform state.
#
# Runs every 30min via shl-platform-scan.timer
# Also callable manually: bash scripts/platform/scan_repo_state.sh
#
# What it detects:
#   • Autoresearch process + current mAP50 from log
#   • T8 pipeline state files → delegates to update_kanban.sh
#   • Docker container health (which services are running)
#   • Recent git commits (last 24h) — logged for audit
#   • nanochat server health (:8021)
#   • GEPA trigger history (gepa_trigger.log)
#   • CLOUD_API_KEY presence
#
# Outputs:
#   • data/platform-scan/evidence.json  — structured status snapshot
#   • docs/obsidian-vault/50-Projects/PLATFORM_STATUS.md  — human-readable
#   • Updates KANBAN.md via kanban_updater.py (deterministic card moves)
#   • Calls update_kanban.sh to sync T8 sub-board
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SERVICE_DISCOVERY="$SCRIPT_DIR/service_discovery.sh"
EVIDENCE_DIR="$PLATFORM_DIR/data/platform-scan"
EVIDENCE_JSON="$EVIDENCE_DIR/evidence.json"
STATUS_MD="$PLATFORM_DIR/docs/obsidian-vault/50-Projects/PLATFORM_STATUS.md"
KANBAN_MD="$PLATFORM_DIR/docs/obsidian-vault/50-Projects/KANBAN.md"
STATE_DIR="$PLATFORM_DIR/data/shl-nano/.state"
LOG_DIR="$PLATFORM_DIR/logs"
UPDATED_AT=$(date -u '+%Y-%m-%d %H:%M UTC')

mkdir -p "$EVIDENCE_DIR" "$LOG_DIR"

if [[ -f "$SERVICE_DISCOVERY" ]]; then
    # shellcheck disable=SC1090
    source "$SERVICE_DISCOVERY"
fi

log() { echo "[scan $(date '+%H:%M:%S')] $*"; }

# ── Source Telegram creds (best-effort) ─────────────────────────────────────
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
_env_file="$PLATFORM_DIR/ray_compute/.env"
if [[ -f "$_env_file" ]]; then
    # Disable -e and -u while sourcing so self-referential ${VAR} lines don't abort
    # shellcheck disable=SC1090
    set +eu; set -a; source "$_env_file" 2>/dev/null || true; set +a; set -eu
fi

notify() {
    local msg="$1"
    if [[ -n "$TELEGRAM_BOT_TOKEN" && -n "$TELEGRAM_CHAT_ID" ]]; then
        curl -sf -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="$TELEGRAM_CHAT_ID" \
            -d parse_mode=Markdown \
            -d text="$msg" >/dev/null 2>&1 || true
    fi
}

# ── 1. Autoresearch status ───────────────────────────────────────────────────
AR_RUNNING=false
AR_PID=""
AR_MAP50="null"
AR_EPOCH="null"
AR_LOG="/tmp/autoresearch_face_run_v3.log"

if pgrep -f "autoresearch_face" >/dev/null 2>&1; then
    AR_RUNNING=true
    AR_PID=$(pgrep -f "autoresearch_face" | head -1)
fi

if [[ -f "$AR_LOG" ]]; then
    # Parse lines like: "mAP50=0.812" or "Epoch 3/15: mAP50=0.812"
    _last_map=$(grep -oP 'mAP50[= ]+\K[\d.]+' "$AR_LOG" 2>/dev/null | tail -1 || true)
    _last_epoch=$(grep -oP 'Epoch +\K[\d]+(?=/\d)' "$AR_LOG" 2>/dev/null | tail -1 || true)
    [[ -n "$_last_map" ]] && AR_MAP50="$_last_map"
    [[ -n "$_last_epoch" ]] && AR_EPOCH="$_last_epoch"
fi

AR_DONE=false
if [[ "$AR_MAP50" != "null" ]]; then
    # If mAP50 > 0.814 and process is done → round 2 complete
    if ! $AR_RUNNING && awk "BEGIN{exit !($AR_MAP50 > 0.814)}"; then
        AR_DONE=true
        log "Autoresearch Round 2 COMPLETE — mAP50=$AR_MAP50"
        notify "✅ *Autoresearch Round 2 complete!*\nmAP50=$AR_MAP50 (beats 0.814 baseline)\n\nNext: T7.4 Phase 6B YOLOv8l P2 fine-tune"
    fi
fi

# ── 2. T8 nanochat state ─────────────────────────────────────────────────────
S1=false; S2=false; S3=false; S4=false; S5=false
[[ -f "$STATE_DIR/data_exported"      ]] && S1=true
[[ -f "$STATE_DIR/base_trained"       ]] && S2=true
[[ -f "$STATE_DIR/sft_done"           ]] && S3=true
[[ -f "$STATE_DIR/server_started"     ]] && S4=true
[[ -f "$STATE_DIR/watchdog_data_done" ]] && S5=true

NANO_SERVER_UP=false
curl -sf --max-time 2 http://localhost:8021/health >/dev/null 2>&1 && NANO_SERVER_UP=true || true

NANO_ENDPOINT_ACTIVE=false
docker exec shml-agent-service env 2>/dev/null | grep -q "NANO_ENDPOINT=http" \
    && NANO_ENDPOINT_ACTIVE=true || true

T8_ALL_DONE=false
if $S1 && $S2 && $S3 && $NANO_SERVER_UP && $NANO_ENDPOINT_ACTIVE && $S5; then
    T8_ALL_DONE=true
fi

# ── 3. Docker containers ─────────────────────────────────────────────────────
RUNNING_CONTAINERS="[]"
if command -v docker >/dev/null 2>&1; then
    _containers=$(docker ps --format '{{.Names}}' 2>/dev/null | jq -R . | jq -sc . 2>/dev/null || echo "[]")
    RUNNING_CONTAINERS="$_containers"
fi

AGENT_RUNNING=false
echo "$RUNNING_CONTAINERS" | grep -q "shml-agent-service" && AGENT_RUNNING=true || true

# ── 4. GEPA trigger history ──────────────────────────────────────────────────
GEPA_TRIGGERED=false
_gepa_log="$LOG_DIR/gepa_trigger.log"
if [[ -f "$_gepa_log" ]] && grep -q "cycle_complete\|evolution_cycle" "$_gepa_log" 2>/dev/null; then
    GEPA_TRIGGERED=true
fi
# Also check agent-service endpoint (200 from skills/evolve means it ran)
if $AGENT_RUNNING; then
    _gepa_resp=$(curl -sf --max-time 5 http://localhost:8000/api/skills/history 2>/dev/null || true)
    [[ -n "$_gepa_resp" ]] && echo "$_gepa_resp" | grep -q "coding-assistant" && GEPA_TRIGGERED=true || true
fi

# ── 5. CLOUD_API_KEY ─────────────────────────────────────────────────────────
CLOUD_KEY_SET=false
[[ -n "${CLOUD_API_KEY:-}" ]] && CLOUD_KEY_SET=true || true
# Also check secrets/ env files
for _ef in "$PLATFORM_DIR"/secrets/*.env "$PLATFORM_DIR"/.env; do
    [[ -f "$_ef" ]] && grep -q "CLOUD_API_KEY=.\+" "$_ef" 2>/dev/null && CLOUD_KEY_SET=true && break || true
done

# ── 6. Recent git commits (24h) ──────────────────────────────────────────────
RECENT_COMMITS="[]"
if git -C "$PLATFORM_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    _commits=$(git -C "$PLATFORM_DIR" log --since='24 hours ago' \
        --format='%h %s' --no-merges 2>/dev/null | head -20 | jq -R . | jq -sc . 2>/dev/null || echo "[]")
    RECENT_COMMITS="$_commits"
fi

# ── 7. GPU free ──────────────────────────────────────────────────────────────
GPU1_FREE=$(nvidia-smi --id=1 --query-gpu=memory.free --format=csv,noheader,nounits \
    2>/dev/null | tr -d ' ' || echo "0")

# ── Write evidence.json ──────────────────────────────────────────────────────
cat > "$EVIDENCE_JSON" <<JSON
{
  "updated_at": "${UPDATED_AT}",
  "autoresearch": {
    "running": ${AR_RUNNING},
    "pid": ${AR_PID:-null},
    "map50": ${AR_MAP50},
    "epoch": ${AR_EPOCH},
    "round2_done": ${AR_DONE}
  },
  "t8": {
    "data_exported": ${S1},
    "base_trained": ${S2},
    "sft_done": ${S3},
    "server_started": ${S4},
    "server_up": ${NANO_SERVER_UP},
    "endpoint_active": ${NANO_ENDPOINT_ACTIVE},
    "watchdog_data_done": ${S5},
    "all_done": ${T8_ALL_DONE}
  },
  "gepa_triggered": ${GEPA_TRIGGERED},
  "cloud_key_set": ${CLOUD_KEY_SET},
  "agent_running": ${AGENT_RUNNING},
  "running_containers": ${RUNNING_CONTAINERS},
  "gpu1_free_mib": ${GPU1_FREE},
  "recent_commits": ${RECENT_COMMITS}
}
JSON

log "Evidence written → $EVIDENCE_JSON"
log "  AR: running=$AR_RUNNING mAP50=$AR_MAP50 done=$AR_DONE"
log "  T8: S1=$S1 S2=$S2 S3=$S3 server=$NANO_SERVER_UP endpoint=$NANO_ENDPOINT_ACTIVE"
log "  GEPA: $GEPA_TRIGGERED | CLOUD_KEY: $CLOUD_KEY_SET | Agent: $AGENT_RUNNING"

# ── Update KANBAN.md via Python (deterministic card moves) ───────────────────
UPDATER="$SCRIPT_DIR/kanban_updater.py"
if [[ -f "$UPDATER" ]]; then
    python3 "$UPDATER" \
        --kanban "$KANBAN_MD" \
        --evidence "$EVIDENCE_JSON" \
        2>&1 | sed 's/^/[kanban_updater] /' || log "WARN: kanban_updater.py failed (non-fatal)"
else
    log "WARN: $UPDATER not found — skipping card moves"
fi

# ── Update T8 sub-board ──────────────────────────────────────────────────────
UPDATE_KANBAN="$PLATFORM_DIR/scripts/data/update_kanban.sh"
if [[ -f "$UPDATE_KANBAN" ]]; then
    bash "$UPDATE_KANBAN" 2>&1 | sed 's/^/[update_kanban] /' || true
fi

# ── Write PLATFORM_STATUS.md ─────────────────────────────────────────────────
_ar_status="🔄 Running (PID $AR_PID) | mAP50=$AR_MAP50 epoch=$AR_EPOCH"
$AR_DONE && _ar_status="✅ Round 2 complete | mAP50=$AR_MAP50"
! $AR_RUNNING && ! $AR_DONE && _ar_status="⏸️ Not running | last mAP50=$AR_MAP50"

_nano_status="⏳ Waiting for training"
$S1 && _nano_status="📤 Stage 1 done (data exported)"
$S2 && _nano_status="🔧 Stage 2 done (base pretrain)"
$S3 && _nano_status="🎓 Stage 3 done (SFT complete)"
$NANO_SERVER_UP && _nano_status="🟢 Server live at :8021"
$NANO_ENDPOINT_ACTIVE && _nano_status="✅ Tier-0 active in agent-service"

cat > "$STATUS_MD" <<MD
---
title: Platform Status
auto_synced: true
---
# Platform Status
*Auto-generated by \`scripts/platform/scan_repo_state.sh\` — ${UPDATED_AT}*
*Do not edit manually — this file is overwritten every 30min*

## Service Health

| Service | Status |
|---------|--------|
| Autoresearch Round 2 | ${_ar_status} |
| nanochat (SHL-Nano) | ${_nano_status} |
| Agent Service | $( $AGENT_RUNNING && echo "🟢 Running" || echo "🔴 Down") |
| GPU 1 free | ${GPU1_FREE} MiB |
| GEPA Engine triggered | $( $GEPA_TRIGGERED && echo "✅ Yes" || echo "⬜ Not yet") |
| CLOUD_API_KEY set | $( $CLOUD_KEY_SET && echo "✅ Yes, cloud failover active" || echo "⬜ No — local-only mode") |

## Recent Commits (24h)

$(git -C "$PLATFORM_DIR" log --since='24 hours ago' \
    --format='- \`%h\` %s (%ar)' --no-merges 2>/dev/null | head -15 || echo "*(no commits in last 24h)*")

## Kanban Boards

- [[KANBAN]] — Main platform board (all tracks T1–T8)
- [[TRACK-8-NANOCHAT]] — T8 nanochat detail (auto-synced every 10min)

*Evidence snapshot: \`data/platform-scan/evidence.json\`*
MD

log "Status written → $STATUS_MD"

# ── Sync findings to GitLab Issues ────────────────────────────────────────────
GITLAB_UTIL="$SCRIPT_DIR/gitlab_utils.py"

if [[ -f "$GITLAB_UTIL" ]]; then
    # Source .env for GitLab token (best-effort)
    _main_env="$PLATFORM_DIR/.env"
    export GITLAB_API_TOKEN="${GITLAB_API_TOKEN:-}"
    if [[ -z "$GITLAB_API_TOKEN" && -f "$_main_env" ]]; then
        GITLAB_API_TOKEN=$(grep -m1 'GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN=' "$_main_env" | cut -d= -f2)
        export GITLAB_API_TOKEN
    fi
    # Use Docker network URL (accessible from host or containers)
    if declare -F resolve_gitlab_base_url >/dev/null 2>&1; then
        export GITLAB_BASE_URL="$(resolve_gitlab_base_url)"
    else
        export GITLAB_BASE_URL="${GITLAB_BASE_URL:-http://127.0.0.1:8929/gitlab}"
    fi

    if [[ -n "$GITLAB_API_TOKEN" ]]; then
        # 1. Autoresearch completed → close issue if exists
        if $AR_DONE; then
            python3 "$GITLAB_UTIL" upsert-issue "Autoresearch Round 2" \
                --title "Autoresearch Round 2 Complete — mAP50=${AR_MAP50}" \
                --labels "type::training,source::scan,component::autoresearch" \
                --comment "✅ Autoresearch Round 2 finished: mAP50=${AR_MAP50} (target: 0.814)" \
                --close 2>&1 | sed 's/^/[gitlab] /' || true
        elif $AR_RUNNING; then
            python3 "$GITLAB_UTIL" upsert-issue "Autoresearch Round 2" \
                --title "Autoresearch Round 2 In Progress" \
                --labels "type::training,source::scan,component::autoresearch" \
                --comment "🔄 Progress update: mAP50=${AR_MAP50} epoch=${AR_EPOCH} (PID ${AR_PID})" \
                2>&1 | sed 's/^/[gitlab] /' || true
        fi

        # 2. Agent service down → create issue
        if ! $AGENT_RUNNING; then
            python3 "$GITLAB_UTIL" upsert-issue "Agent Service Down" \
                --labels "type::bug,priority::high,source::scan,component::agent-service" \
                --description "Agent service container is not running.\n\nDetected at ${UPDATED_AT}" \
                2>&1 | sed 's/^/[gitlab] /' || true
        else
            # Agent back up → close any existing issue
            python3 "$GITLAB_UTIL" upsert-issue "Agent Service Down" \
                --comment "✅ Agent service recovered at ${UPDATED_AT}" \
                --close 2>&1 | sed 's/^/[gitlab] /' || true
        fi

        # 3. Low GPU memory → create issue
        if [[ "${GPU1_FREE}" =~ ^[0-9]+$ ]] && (( GPU1_FREE < 512 )); then
            python3 "$GITLAB_UTIL" upsert-issue "GPU 1 Low Memory" \
                --labels "type::bug,priority::high,source::scan,component::infra" \
                --description "GPU 1 has only ${GPU1_FREE} MiB free.\n\nDetected at ${UPDATED_AT}" \
                2>&1 | sed 's/^/[gitlab] /' || true
        fi

        log "GitLab sync complete"
    else
        log "WARN: No GITLAB_API_TOKEN — skipping GitLab sync"
    fi
else
    log "WARN: $GITLAB_UTIL not found — skipping GitLab sync"
fi

log "Scan complete — ${UPDATED_AT}"
