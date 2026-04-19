#!/bin/bash
# =============================================================================
# telegram.sh — Centralized Telegram notification helper for SHML platform
# =============================================================================
# Provides a single, consistent send_telegram() function for all shell scripts.
# Uses jq for proper JSON encoding and HTML parse mode by default.
#
# Usage:
#   source scripts/lib/telegram.sh
#   send_telegram "Hello *world*"                    # HTML mode (default)
#   send_telegram --parse-mode Markdown "Hello _world_"  # Markdown mode
#
# Environment variables (required):
#   TELEGRAM_BOT_TOKEN  — Bot API token
#   TELEGRAM_CHAT_ID    — Target chat/group ID
# =============================================================================

# Idempotency guard — safe to source multiple times
[[ -n "${_SHML_TELEGRAM_LOADED:-}" ]] && return 0
_SHML_TELEGRAM_LOADED=1

# HTML-escape special characters for safe embedding in HTML messages
_html_escape() {
    printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'
}

# Send a Telegram message
# Usage: send_telegram [OPTIONS] MESSAGE
# Options:
#   --parse-mode MODE  — Parse mode: HTML (default) or Markdown
#
# Returns: 0 on success, 1 on failure (with warning to stderr)
send_telegram() {
    local parse_mode="HTML"  # Default to HTML for consistency with watchdog
    local message=""
    
    # Parse optional --parse-mode argument
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --parse-mode)
                parse_mode="$2"
                shift 2
                ;;
            *)
                # Accumulate remaining args as the message (preserves newlines)
                if [[ -z "$message" ]]; then
                    message="$1"
                else
                    message="$message
$1"
                fi
                shift
                ;;
        esac
    done
    
    # Validate required environment variables
    if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]] || [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
        return 0  # Silent skip if not configured
    fi
    
    # Build JSON payload with proper encoding
    local payload
    payload=$(jq -n \
        --arg chat "${TELEGRAM_CHAT_ID}" \
        --arg text "$message" \
        --arg mode "$parse_mode" \
        '{chat_id: $chat, text: $text, parse_mode: $mode}') || {
        echo "WARN: Failed to encode Telegram message" >&2
        return 1
    }
    
    # Send the request
    if ! curl -sf -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        > /dev/null 2>&1; then
        echo "WARN: Telegram send failed" >&2
        return 1
    fi
    
    return 0
}

# Export for use in subshells
export -f send_telegram
export -f _html_escape
