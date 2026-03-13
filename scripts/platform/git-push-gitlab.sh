#!/usr/bin/env bash
# =============================================================================
# git-push-gitlab.sh — Reliable git push to GitLab via dynamic container IP
#
# The GitLab container IP changes on restart, so this script:
#   1. Looks up the current IP of shml-gitlab
#   2. Updates the git remote URL
#   3. Pushes the specified branch
#
# Usage:
#   bash scripts/platform/git-push-gitlab.sh [branch]          # default: current branch
#   bash scripts/platform/git-push-gitlab.sh main
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load token from .env
ENV_FILE="$PLATFORM_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found" >&2
    exit 1
fi

GITLAB_TOKEN=$(grep -m1 'GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN=' "$ENV_FILE" | cut -d= -f2)
if [[ -z "$GITLAB_TOKEN" ]]; then
    echo "ERROR: GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN not set in .env" >&2
    exit 1
fi

# Get current GitLab container IP
GITLAB_IP=$(docker inspect shml-gitlab --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null)
if [[ -z "$GITLAB_IP" ]]; then
    echo "ERROR: shml-gitlab container not running or not found" >&2
    exit 1
fi

# Default branch = current HEAD
BRANCH="${1:-$(git -C "$PLATFORM_DIR" symbolic-ref --short HEAD 2>/dev/null || echo "main")}"

# Update remote URL
PUSH_URL="http://axelofwar:${GITLAB_TOKEN}@${GITLAB_IP}:8929/gitlab/ml-platform/shml-platform.git"
git -C "$PLATFORM_DIR" remote set-url gitlab "$PUSH_URL" 2>/dev/null || \
    git -C "$PLATFORM_DIR" remote add gitlab "$PUSH_URL" 2>/dev/null

echo "Pushing ${BRANCH} → gitlab (${GITLAB_IP}:8929)..."
git -C "$PLATFORM_DIR" push gitlab "$BRANCH" 2>&1
echo "✓ Push complete"
