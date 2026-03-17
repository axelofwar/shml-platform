#!/bin/bash
# FusionAuth User Registration Notification Script
# =================================================
# Triggered by FusionAuth webhook when a new user registers.
# Sends Telegram notification to admins for awareness / manual approval.
#
# Arguments (from webhook payload):
#   $1 — user.email
#   $2 — user.username (or empty)
#   $3 — user.id (FusionAuth UUID)
#   $4 — registration.applicationId
#   $5 — event type (e.g., user.create, user.registration.create)

set -euo pipefail

USER_EMAIL="${1:-unknown}"
USER_NAME="${2:-${USER_EMAIL%%@*}}"
USER_ID="${3:-unknown}"
APP_ID="${4:-unknown}"
EVENT_TYPE="${5:-user.create}"

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S %Z')

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR="${DEPLOY_LOG_DIR:-/var/log/shml-platform}"
LOG_FILE="${LOG_DIR}/user_registrations.log"

if ! mkdir -p "$LOG_DIR" 2>/dev/null; then
    LOG_DIR="/tmp/shml-platform"
    LOG_FILE="${LOG_DIR}/user_registrations.log"
    mkdir -p "$LOG_DIR"
fi

log() {
    echo "[${TIMESTAMP}] $1" | tee -a "$LOG_FILE"
}

# ---------------------------------------------------------------------------
# Resolve application name
# ---------------------------------------------------------------------------
resolve_app_name() {
    case "$APP_ID" in
        "e9fdb985-"*) echo "MLflow" ;;
        "a1b2c3d4-"*) echo "Ray Compute" ;;
        "${FUSIONAUTH_PROXY_CLIENT_ID:-}"*|"acda34f0-"*|"50a4dc27-"*) echo "OAuth2-Proxy (Web)" ;;
        *) echo "Unknown ($APP_ID)" ;;
    esac
}

APP_NAME=$(resolve_app_name)

# ---------------------------------------------------------------------------
# Telegram notification
# ---------------------------------------------------------------------------
send_telegram() {
    local message="$1"
    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
        curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=${message}" \
            -d "parse_mode=HTML" > /dev/null 2>&1 || true
    else
        log "WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping notification"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
log "New user registration event: ${EVENT_TYPE}"
log "  Email: ${USER_EMAIL}"
log "  Username: ${USER_NAME}"
log "  User ID: ${USER_ID}"
log "  Application: ${APP_NAME}"

# Build notification message
MSG="👤 <b>New User Registration</b>

📧 Email: <code>${USER_EMAIL}</code>
🏷️ Username: <code>${USER_NAME}</code>
🔑 User ID: <code>${USER_ID}</code>
📱 Application: ${APP_NAME}
📋 Event: ${EVENT_TYPE}
⏰ Time: ${TIMESTAMP}

<b>Action Required:</b>
Default role: <code>viewer</code>
To upgrade, visit FusionAuth Admin → Users → ${USER_EMAIL}
Or run: <code>scripts/auth/user-management.sh set-role ${USER_EMAIL} developer</code>"

send_telegram "$MSG"

log "Notification sent for ${USER_EMAIL}"
exit 0
