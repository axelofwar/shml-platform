#!/bin/sh
set -eu

CONFIG_FILE="/etc/gitlab-runner/config.toml"
RUNNER_URL="${GITLAB_RUNNER_URL:-http://gitlab:8929/gitlab/}"
CLONE_URL="${GITLAB_RUNNER_CLONE_URL:-http://gitlab:8929/gitlab}"
DOCKER_IMAGE="${GITLAB_RUNNER_DOCKER_IMAGE:-python:3.11}"
DESCRIPTION="${GITLAB_RUNNER_DESCRIPTION:-shml-docker-runner}"
TAGS="${GITLAB_RUNNER_TAGS:-docker,shml}"
RUN_UNTAGGED="${GITLAB_RUNNER_RUN_UNTAGGED:-true}"
LOCKED="${GITLAB_RUNNER_LOCKED:-false}"
NETWORK_MODE="${GITLAB_RUNNER_NETWORK_MODE:-shml-platform}"
RUNNER_LIMIT="${GITLAB_RUNNER_LIMIT:-1}"
REQUEST_CONCURRENCY="${GITLAB_RUNNER_REQUEST_CONCURRENCY:-1}"
GLOBAL_CONCURRENT="${GITLAB_RUNNER_CONCURRENT:-1}"

if [ ! -f "$CONFIG_FILE" ] || ! grep -q '^\[\[runners\]\]' "$CONFIG_FILE"; then
  if [ -z "${GITLAB_RUNNER_REGISTRATION_TOKEN:-}" ]; then
    echo "GITLAB_RUNNER_REGISTRATION_TOKEN is required for first-time runner registration." >&2
    exit 1
  fi

  gitlab-runner register --non-interactive \
    --url "$RUNNER_URL" \
    --registration-token "$GITLAB_RUNNER_REGISTRATION_TOKEN" \
    --executor "docker" \
    --docker-image "$DOCKER_IMAGE" \
    --description "$DESCRIPTION" \
    --tag-list "$TAGS" \
    --run-untagged="$RUN_UNTAGGED" \
    --locked="$LOCKED"
fi

if ! grep -q '^  clone_url = ' "$CONFIG_FILE"; then
  sed -i '/^  url =/a\  clone_url = "'"$CLONE_URL"'"' "$CONFIG_FILE"
fi

if ! grep -q '^    network_mode = ' "$CONFIG_FILE"; then
  sed -i '/^    image =/a\    network_mode = "'"$NETWORK_MODE"'"' "$CONFIG_FILE"
fi

if ! grep -q '^  limit = ' "$CONFIG_FILE"; then
  sed -i '/^  name =/a\  limit = '"$RUNNER_LIMIT" "$CONFIG_FILE"
fi

if ! grep -q '^  request_concurrency = ' "$CONFIG_FILE"; then
  sed -i '/^  limit =/a\  request_concurrency = '"$REQUEST_CONCURRENCY" "$CONFIG_FILE"
fi

if grep -q '^concurrent = ' "$CONFIG_FILE"; then
  sed -i 's/^concurrent = .*/concurrent = '"$GLOBAL_CONCURRENT"'/' "$CONFIG_FILE"
else
  sed -i '1i concurrent = '"$GLOBAL_CONCURRENT" "$CONFIG_FILE"
fi

exec gitlab-runner run --user=gitlab-runner --working-directory=/home/gitlab-runner
