#!/usr/bin/env bash
set -euo pipefail

MAP_FILE="${MAP_FILE:-config/secrets/infisical-docker-secret-map.tsv}"
OUTPUT_ROOT="${OUTPUT_ROOT:-.}"
INFISICAL_ENV_SLUG="${INFISICAL_ENV_SLUG:-prod}"

usage() {
  cat <<'EOF'
Render Docker secret files from Infisical (Path A).

Required env vars:
  INFISICAL_PROJECT_ID   Infisical project ID to read from

Optional env vars:
  INFISICAL_ENV_SLUG     Environment slug (default: prod)
  MAP_FILE               TSV mapping file (default: config/secrets/infisical-docker-secret-map.tsv)
  OUTPUT_ROOT            Prefix for output paths (default: .)

TSV format (tab-separated):
  infisical_secret_name<TAB>output_file_path<TAB>required

Example:
  GITHUB_TOKEN\tsecrets/public_mirror_github_token.txt\ttrue
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

if ! command -v infisical >/dev/null 2>&1; then
  echo "infisical CLI is required (https://infisical.com/docs/cli/overview)" >&2
  exit 1
fi

if [[ ! -f "$MAP_FILE" ]]; then
  echo "Mapping file not found: $MAP_FILE" >&2
  exit 1
fi

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

rendered=0
failed=0

while IFS=$'\t' read -r secret_name output_path required_flag; do
  [[ -z "${secret_name:-}" ]] && continue
  [[ "${secret_name:0:1}" == "#" ]] && continue
  if [[ -z "${output_path:-}" ]]; then
    echo "Skipping malformed row (missing output_path): ${secret_name}" >&2
    failed=$((failed + 1))
    continue
  fi

  if secret_value="$(fetch_secret "$secret_name")"; then
    full_output_path="$OUTPUT_ROOT/$output_path"
    mkdir -p "$(dirname "$full_output_path")"
    tmp_file="$(mktemp)"
    printf '%s' "$secret_value" > "$tmp_file"
    chmod 600 "$tmp_file"
    mv "$tmp_file" "$full_output_path"
    rendered=$((rendered + 1))
    echo "Rendered: $output_path"
  else
    if [[ "${required_flag:-true}" == "true" ]]; then
      echo "Missing required Infisical secret: $secret_name" >&2
      failed=$((failed + 1))
    else
      echo "Skipping optional secret not found: $secret_name"
    fi
  fi
done < "$MAP_FILE"

echo "Rendered files: $rendered"
if [[ $failed -gt 0 ]]; then
  echo "Failures: $failed" >&2
  exit 1
fi

echo "Infisical -> Docker secret render completed successfully."
