#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/axelofwar/Projects/shml-platform"
POLICY_FILE="$ROOT/.openclaw/governance.policy.yaml"
LOG_DIR="$ROOT/.openclaw/logs"
OVERRIDE_LOG="$LOG_DIR/governance-overrides.jsonl"
DECISION_LOG="$LOG_DIR/governance-decisions.jsonl"
OPENCLAW_BIN="${OPENCLAW_BIN:-$HOME/.nvm/versions/node/v22.22.0/bin/openclaw}"

mkdir -p "$LOG_DIR"

now_iso() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

require_openclaw() {
  if ! command -v "$OPENCLAW_BIN" >/dev/null 2>&1; then
    echo "OpenClaw binary not found at: $OPENCLAW_BIN" >&2
    exit 1
  fi
}

show_usage() {
  cat <<'EOF'
OpenClaw Governor - budget, cancel, override, and learning controls

Usage:
  scripts/openclaw/openclaw_governor.sh status
  scripts/openclaw/openclaw_governor.sh budget
  scripts/openclaw/openclaw_governor.sh policy
  scripts/openclaw/openclaw_governor.sh cancel [reason]
  scripts/openclaw/openclaw_governor.sh override <tier> <reason>
  scripts/openclaw/openclaw_governor.sh learn <outcome> <note>

Commands:
  status      Show OpenClaw gateway + sessions status
  budget      Show policy budget guardrails
  policy      Print governance policy path
  cancel      Emergency cancel: restarts gateway to terminate active runs
  override    Record a manual tier override (local-fast|remote-balanced|remote-premium)
  learn       Append a governance decision outcome record
EOF
}

append_jsonl() {
  local file="$1"
  local payload="$2"
  printf '%s\n' "$payload" >> "$file"
}

cmd_status() {
  require_openclaw
  "$OPENCLAW_BIN" gateway status
  "$OPENCLAW_BIN" sessions --all-agents
}

cmd_budget() {
  if [[ ! -f "$POLICY_FILE" ]]; then
    echo "Policy file missing: $POLICY_FILE" >&2
    exit 1
  fi
  echo "Policy: $POLICY_FILE"
  awk '/^budget:/,/^admin_controls:/' "$POLICY_FILE"
}

cmd_policy() {
  echo "$POLICY_FILE"
}

cmd_cancel() {
  require_openclaw
  local reason="${1:-manual-cancel}"
  "$OPENCLAW_BIN" gateway restart
  append_jsonl "$DECISION_LOG" "{\"ts\":\"$(now_iso)\",\"action\":\"cancel\",\"method\":\"gateway-restart\",\"reason\":\"$reason\"}"
  echo "Active run cancellation executed via gateway restart."
}

cmd_override() {
  local tier="${1:-}"
  local reason="${2:-}"

  if [[ -z "$tier" || -z "$reason" ]]; then
    echo "Usage: $0 override <tier> <reason>" >&2
    exit 1
  fi

  case "$tier" in
    local-fast|remote-balanced|remote-premium) ;;
    *)
      echo "Invalid tier: $tier" >&2
      exit 1
      ;;
  esac

  append_jsonl "$OVERRIDE_LOG" "{\"ts\":\"$(now_iso)\",\"tier\":\"$tier\",\"reason\":\"$reason\",\"actor\":\"$(whoami)\"}"
  echo "Override recorded: $tier"
}

cmd_learn() {
  local outcome="${1:-}"
  local note="${2:-}"

  if [[ -z "$outcome" || -z "$note" ]]; then
    echo "Usage: $0 learn <outcome> <note>" >&2
    exit 1
  fi

  append_jsonl "$DECISION_LOG" "{\"ts\":\"$(now_iso)\",\"action\":\"learn\",\"outcome\":\"$outcome\",\"note\":\"$note\",\"actor\":\"$(whoami)\"}"
  echo "Learning event recorded."
}

main() {
  local cmd="${1:-help}"
  shift || true

  case "$cmd" in
    status) cmd_status "$@" ;;
    budget) cmd_budget "$@" ;;
    policy) cmd_policy "$@" ;;
    cancel) cmd_cancel "$@" ;;
    override) cmd_override "$@" ;;
    learn) cmd_learn "$@" ;;
    help|-h|--help) show_usage ;;
    *)
      echo "Unknown command: $cmd" >&2
      show_usage
      exit 1
      ;;
  esac
}

main "$@"
