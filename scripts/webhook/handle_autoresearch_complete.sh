#!/usr/bin/env bash
# handle_autoresearch_complete.sh
# Called by webhook-deployer when autoresearch publishes an experiment_complete event.
# Args: $1=experiment $2=iteration $3=kept $4=recall $5=mAP50 $6=best_recall $7=reason
#
# Effect: upserts a GitLab issue comment with the experiment result.
# Safe to fail — webhook-deployer logs stderr; training is never blocked by this.

set -euo pipefail

EXPERIMENT="${1:-unknown}"
ITERATION="${2:-?}"
KEPT="${3:-false}"
RECALL="${4:-0}"
MAP50="${5:-0}"
BEST_RECALL="${6:-0}"
REASON="${7:-}"

GITLAB_SCRIPT="/opt/shml-platform/scripts/platform/gitlab_utils.py"
PYTHON="${PYTHON_BIN:-python3}"

if [[ ! -f "$GITLAB_SCRIPT" ]]; then
    echo "[autoresearch-webhook] gitlab_utils.py not found at $GITLAB_SCRIPT — skipping"
    exit 0
fi

STATUS_ICON="✗"
[[ "$KEPT" == "true" || "$KEPT" == "True" || "$KEPT" == "1" ]] && STATUS_ICON="✓ KEPT"

COMMENT="### Autoresearch Iter ${ITERATION} — ${STATUS_ICON} \`${EXPERIMENT}\`

| Metric | Value |
|--------|-------|
| Recall | \`${RECALL}\` |
| mAP50 | \`${MAP50}\` |
| Best recall so far | \`${BEST_RECALL}\` |

**Decision:** ${REASON}

> 🎯 PII target: recall > 0.760 · floor: mAP50 ≥ 0.798"

# Post comment to the tracking issue (search by title prefix)
$PYTHON "$GITLAB_SCRIPT" upsert-issue \
    "Autoresearch Round 3" \
    --comment "$COMMENT" \
    --labels "type::training,component::autoresearch,status::in-progress,source::autoresearch" \
    2>&1 || true

echo "[autoresearch-webhook] Posted iter ${ITERATION} result (kept=${KEPT}, recall=${RECALL})"
