#!/usr/bin/env bash
# handle_watchdog_alert.sh
# Called by webhook-deployer when watchdog publishes to shml:health:alert channel.
# Args: $1=alert_type $2=service $3=message $4=severity
#
# Effect: creates a priority::critical GitLab issue with full context.

set -euo pipefail

ALERT_TYPE="${1:-unknown}"
SERVICE="${2:-unknown}"
MESSAGE="${3:-No message}"
SEVERITY="${4:-warning}"

GITLAB_SCRIPT="/opt/shml-platform/scripts/platform/gitlab_utils.py"
PYTHON="${PYTHON_BIN:-python3}"

if [[ ! -f "$GITLAB_SCRIPT" ]]; then
    echo "[watchdog-webhook] gitlab_utils.py not found — skipping"
    exit 0
fi

PRIORITY="priority::high"
[[ "$SEVERITY" == "critical" ]] && PRIORITY="priority::critical"

TITLE="[Watchdog] ${ALERT_TYPE} — ${SERVICE}"
DESCRIPTION="## Watchdog Alert

**Type:** \`${ALERT_TYPE}\`
**Service:** \`${SERVICE}\`
**Severity:** \`${SEVERITY}\`
**Time:** $(date -u +%Y-%m-%dT%H:%M:%SZ)

### Message
\`\`\`
${MESSAGE}
\`\`\`

*Auto-created by watchdog webhook handler.*"

$PYTHON "$GITLAB_SCRIPT" upsert-issue \
    "[Watchdog] ${ALERT_TYPE}" \
    --title "$TITLE" \
    --description "$DESCRIPTION" \
    --labels "type::bug,component::watchdog,${PRIORITY},source::watchdog" \
    2>&1 || true

echo "[watchdog-webhook] Alert issue created: ${TITLE}"
