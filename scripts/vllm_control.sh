#!/usr/bin/env bash
# =============================================================================
# vLLM Control Script (DEPRECATED - Use llm_control.sh instead)
# =============================================================================
# vLLM cannot serve Qwen3.5-27B on 24GB GPU due to hybrid architecture
# (attention + delta networks) + CPU offload incompatibility in v0.17.1.
# Switched to llama.cpp which handles CPU+GPU split natively.
#
# This script is kept as a wrapper for backwards compatibility.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[DEPRECATED] Redirecting to llm_control.sh (llama.cpp backend)"
exec "$SCRIPT_DIR/llm_control.sh" "$@"
