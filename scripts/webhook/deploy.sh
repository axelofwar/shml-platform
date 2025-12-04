#!/bin/bash
# GitHub Webhook Deploy Script
# Triggered by GitHub push events to main branch
# Sends notifications to Telegram and optionally Email

set -e

# Arguments from webhook
REPO="$1"
REF="$2"
COMMIT_MSG="$3"
PUSHER="$4"

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_FILE="/opt/sfml-platform/logs/deploy.log"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[${TIMESTAMP}] $1" | tee -a "$LOG_FILE"
}

# Send Telegram notification
send_telegram() {
    local message="$1"
    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
        # URL encode the message
        local encoded_message=$(echo "$message" | sed 's/ /%20/g; s/\n/%0A/g')
        curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=${message}" \
            -d "parse_mode=HTML" > /dev/null 2>&1 || true
    fi
}

# Send Email notification (using system mail if available)
send_email() {
    local subject="$1"
    local body="$2"
    if [ -n "${DEPLOY_EMAIL:-}" ] && command -v mail &> /dev/null; then
        echo "$body" | mail -s "$subject" "$DEPLOY_EMAIL" 2>/dev/null || true
    fi
}

log "=========================================="
log "Deployment triggered"
log "Repository: $REPO"
log "Ref: $REF"
log "Commit: $COMMIT_MSG"
log "Pusher: $PUSHER"
log "=========================================="

# Send start notification
send_telegram "🚀 <b>Deployment Started</b>
📦 Repository: $REPO
🔀 Branch: ${REF#refs/heads/}
📝 Commit: ${COMMIT_MSG:0:50}
👤 By: $PUSHER
⏰ Time: $TIMESTAMP"

# Determine which deployment to run
deploy_result=0

case "$REPO" in
    "axelofwar/sfml-platform"|"*/sfml-platform")
        log "Deploying SFML Platform..."
        cd /opt/sfml-platform

        # Pull latest changes
        if git pull origin main 2>&1 | tee -a "$LOG_FILE"; then
            log "Git pull successful"
        else
            log "Git pull failed"
            deploy_result=1
        fi

        # Restart services if pull was successful
        if [ $deploy_result -eq 0 ]; then
            log "Restarting services..."
            # Use docker compose to recreate changed services
            if docker compose pull 2>&1 | tee -a "$LOG_FILE"; then
                log "Docker pull successful"
            fi

            if docker compose up -d --remove-orphans 2>&1 | tee -a "$LOG_FILE"; then
                log "Docker compose up successful"
            else
                log "Docker compose up failed"
                deploy_result=1
            fi
        fi
        ;;
    *)
        log "Unknown repository: $REPO - no deployment configured"
        deploy_result=0
        ;;
esac

# Send completion notification
if [ $deploy_result -eq 0 ]; then
    log "Deployment completed successfully"
    send_telegram "✅ <b>Deployment Successful</b>
📦 Repository: $REPO
🔀 Branch: ${REF#refs/heads/}
⏱️ Duration: $(( $(date +%s) - $(date -d "$TIMESTAMP" +%s) ))s"

    send_email "✅ SFML Platform Deployment Successful" \
        "Repository: $REPO\nBranch: ${REF#refs/heads/}\nCommit: $COMMIT_MSG\nBy: $PUSHER\nTime: $TIMESTAMP"
else
    log "Deployment failed"
    send_telegram "❌ <b>Deployment Failed</b>
📦 Repository: $REPO
🔀 Branch: ${REF#refs/heads/}
📝 Check logs at /logs/ for details"

    send_email "❌ SFML Platform Deployment Failed" \
        "Repository: $REPO\nBranch: ${REF#refs/heads/}\nCommit: $COMMIT_MSG\nBy: $PUSHER\nTime: $TIMESTAMP\n\nCheck logs for details."
fi

exit $deploy_result
