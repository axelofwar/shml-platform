#!/usr/bin/env bash
set -euo pipefail

MAP_FILE="${MAP_FILE:-config/secrets/infisical-gitlab-variable-map.tsv}"
INFISICAL_ENV_SLUG="${INFISICAL_ENV_SLUG:-prod}"
GITLAB_API_URL="${GITLAB_API_URL:-}"

usage() {
  cat <<'EOF'
Sync GitLab CI/CD variables from Infisical (Path A).

Required env vars:
  INFISICAL_PROJECT_ID   Infisical project ID to read from
  GITLAB_PROJECT_ID      GitLab project numeric ID or URL-encoded path
  GITLAB_API_TOKEN       GitLab token with api scope on the target project
  GITLAB_API_URL         Example: https://gitlab.example.com/gitlab/api/v4

Optional env vars:
  INFISICAL_ENV_SLUG     Environment slug (default: prod)
  MAP_FILE               TSV mapping file (default: config/secrets/infisical-gitlab-variable-map.tsv)

TSV format (tab-separated):
  infisical_secret_name<TAB>gitlab_variable_key<TAB>masked<TAB>protected<TAB>environment_scope<TAB>required

Example:
  GITHUB_TOKEN\tPUBLIC_MIRROR_GITHUB_TOKEN\ttrue\ttrue\t*\ttrue
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ -z "${INFISICAL_PROJECT_ID:-}" ]]; then
  echo "INFISICAL_PROJECT_ID is required" >&2
  exit 1
fi

if [[ -z "${GITLAB_PROJECT_ID:-}" ]]; then
  echo "GITLAB_PROJECT_ID is required" >&2
  exit 1
fi

if [[ -z "${GITLAB_API_TOKEN:-}" ]]; then
  echo "GITLAB_API_TOKEN is required" >&2
  exit 1
fi

if [[ -z "$GITLAB_API_URL" ]]; then
  echo "GITLAB_API_URL is required (example: https://gitlab.example.com/gitlab/api/v4)" >&2
  exit 1
fi

if ! command -v infisical >/dev/null 2>&1; then
  echo "infisical CLI is required (https://infisical.com/docs/cli/overview)" >&2
  exit 1
fi

if [[ ! -f "$MAP_FILE" ]]; then
  echo "Mapping file not found: $MAP_FILE" >&2
  exit 1
fi

urlencode() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

fetch_secret() {
  local secret_name="$1"
  local value=""

  if value="$(infisical secrets get "$secret_name" --projectId "$INFISICAL_PROJECT_ID" --env "$INFISICAL_ENV_SLUG" --plain 2>/dev/null)" && [[ -n "$value" ]]; then
    printf '%s' "$value"
    return 0
  fi

  if value="$(infisical secrets get "$secret_name" --projectId "$INFISICAL_PROJECT_ID" --environment "$INFISICAL_ENV_SLUG" --plain 2>/dev/null)" && [[ -n "$value" ]]; then
    printf '%s' "$value"
    return 0
  fi

  return 1
}

upsert_gitlab_variable() {
  local key="$1"
  local value="$2"
  local masked="$3"
  local protected="$4"
  local environment_scope="$5"
  local encoded_key
  local put_code
  local post_code
  local response_file

  encoded_key="$(urlencode "$key")"
  response_file="$(mktemp)"

  put_code="$(curl -sS -o "$response_file" -w '%{http_code}' \
    --request PUT \
    --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
    --form "value=$value" \
    --form "masked=$masked" \
    --form "protected=$protected" \
    --form "raw=true" \
    --form "environment_scope=$environment_scope" \
    "$GITLAB_API_URL/projects/$GITLAB_PROJECT_ID/variables/$encoded_key")"

  if [[ "$put_code" == "200" ]]; then
    rm -f "$response_file"
    echo "Updated GitLab variable: $key"
    return 0
  fi

  if [[ "$put_code" != "404" ]]; then
    echo "Failed to update variable '$key' (HTTP $put_code)" >&2
    cat "$response_file" >&2
    rm -f "$response_file"
    return 1
  fi

  post_code="$(curl -sS -o "$response_file" -w '%{http_code}' \
    --request POST \
    --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
    --form "key=$key" \
    --form "value=$value" \
    --form "masked=$masked" \
    --form "protected=$protected" \
    --form "raw=true" \
    --form "environment_scope=$environment_scope" \
    "$GITLAB_API_URL/projects/$GITLAB_PROJECT_ID/variables")"

  if [[ "$post_code" == "201" ]]; then
    rm -f "$response_file"
    echo "Created GitLab variable: $key"
    return 0
  fi

  echo "Failed to create variable '$key' (HTTP $post_code)" >&2
  cat "$response_file" >&2
  rm -f "$response_file"
  return 1
}

synced=0
failed=0

while IFS=$'\t' read -r infisical_secret_name gitlab_key masked protected environment_scope required_flag; do
  [[ -z "${infisical_secret_name:-}" ]] && continue
  [[ "${infisical_secret_name:0:1}" == "#" ]] && continue

  if [[ -z "${gitlab_key:-}" ]]; then
    echo "Skipping malformed row (missing gitlab key): ${infisical_secret_name}" >&2
    failed=$((failed + 1))
    continue
  fi

  masked="${masked:-true}"
  protected="${protected:-true}"
  environment_scope="${environment_scope:-*}"
  required_flag="${required_flag:-true}"

  if secret_value="$(fetch_secret "$infisical_secret_name")"; then
    if upsert_gitlab_variable "$gitlab_key" "$secret_value" "$masked" "$protected" "$environment_scope"; then
      synced=$((synced + 1))
    else
      failed=$((failed + 1))
    fi
  else
    if [[ "$required_flag" == "true" ]]; then
      echo "Missing required Infisical secret: $infisical_secret_name" >&2
      failed=$((failed + 1))
    else
      echo "Skipping optional secret not found: $infisical_secret_name"
    fi
  fi
done < "$MAP_FILE"

echo "Synced variables: $synced"
if [[ $failed -gt 0 ]]; then
  echo "Failures: $failed" >&2
  exit 1
fi

echo "Infisical -> GitLab variable sync completed successfully."
