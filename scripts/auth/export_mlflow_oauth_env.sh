#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

TARGET_ENV_FILE="${1:-${HOME}/.config/shml/mlflow_oauth.env}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  source "${ENV_FILE}"
  set +a
fi

PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-}"
FUSIONAUTH_PROXY_CLIENT_ID="${FUSIONAUTH_PROXY_CLIENT_ID:-}"
FUSIONAUTH_PROXY_CLIENT_SECRET="${FUSIONAUTH_PROXY_CLIENT_SECRET:-}"

if [[ -z "${PUBLIC_DOMAIN}" ]]; then
  echo "Missing PUBLIC_DOMAIN (expected in ${ENV_FILE})" >&2
  exit 1
fi

if [[ -z "${FUSIONAUTH_PROXY_CLIENT_ID}" || -z "${FUSIONAUTH_PROXY_CLIENT_SECRET}" ]]; then
  echo "Missing FusionAuth proxy client credentials in ${ENV_FILE}" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

token_response="$({
  curl -sS -X POST "https://${PUBLIC_DOMAIN}/oauth2/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=client_credentials" \
    --data-urlencode "client_id=${FUSIONAUTH_PROXY_CLIENT_ID}" \
    --data-urlencode "client_secret=${FUSIONAUTH_PROXY_CLIENT_SECRET}" \
    --data-urlencode "scope=openid profile email"
} || true)"

access_token="$(jq -r '.access_token // empty' <<<"${token_response}")"
expires_in="$(jq -r '.expires_in // 0' <<<"${token_response}")"

if [[ -z "${access_token}" ]]; then
  service_account_user="${SERVICE_ACCOUNT_USER:-elevated-developer-service@ml-platform.local}"
  service_account_password="${SERVICE_ACCOUNT_PASSWORD:-${FUSIONAUTH_ELEVATED_DEVELOPER_SERVICE_ACCOUNT_PASSWORD:-${FUSIONAUTH_ADMIN_SERVICE_ACCOUNT_PASSWORD:-}}}"

  if [[ -n "${service_account_password}" ]]; then
    token_response="$({
      curl -sS -X POST "https://${PUBLIC_DOMAIN}/oauth2/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        --data-urlencode "grant_type=password" \
        --data-urlencode "client_id=${FUSIONAUTH_PROXY_CLIENT_ID}" \
        --data-urlencode "client_secret=${FUSIONAUTH_PROXY_CLIENT_SECRET}" \
        --data-urlencode "username=${service_account_user}" \
        --data-urlencode "password=${service_account_password}" \
        --data-urlencode "scope=openid profile email"
    } || true)"

    access_token="$(jq -r '.access_token // empty' <<<"${token_response}")"
    expires_in="$(jq -r '.expires_in // 0' <<<"${token_response}")"
  fi
fi

if [[ -z "${access_token}" ]]; then
  echo "Failed to obtain OAuth token from FusionAuth" >&2
  echo "Tried: client_credentials, then password grant with service account" >&2
  echo "Response: ${token_response}" >&2
  exit 1
fi

status_code="$({
  curl -sS -o /tmp/mlflow_oauth_probe.json -w "%{http_code}" \
    -X POST "https://${PUBLIC_DOMAIN}/api/2.0/mlflow/experiments/search" \
    -H "Authorization: Bearer ${access_token}" \
    -H "Content-Type: application/json" \
    -d '{"max_results":1}'
} || true)"

if [[ "${status_code}" != "200" ]]; then
  echo "Token minted, but protected MLflow API probe failed (HTTP ${status_code})" >&2
  echo "Body: $(cat /tmp/mlflow_oauth_probe.json 2>/dev/null || true)" >&2
  exit 1
fi

mkdir -p "$(dirname "${TARGET_ENV_FILE}")"

cat > "${TARGET_ENV_FILE}" <<EOF
export MLFLOW_TRACKING_URI="https://${PUBLIC_DOMAIN}"
export MLFLOW_TRACKING_TOKEN="${access_token}"
export SHML_MLFLOW_TOKEN_EXPIRES_IN="${expires_in}"
EOF

chmod 600 "${TARGET_ENV_FILE}"

echo "Wrote MLflow OAuth environment to ${TARGET_ENV_FILE}"
echo "Use: source ${TARGET_ENV_FILE}"
echo "Probe: https://${PUBLIC_DOMAIN}/api/2.0/mlflow/experiments/search -> HTTP 200"
