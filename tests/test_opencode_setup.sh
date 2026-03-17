#!/bin/bash
# OpenCode + Nemotron Integration Test
# Verifies the OpenCode setup with local Nemotron-3-Nano model

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧪 OpenCode + Nemotron Integration Test"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

# 1. Check OpenCode installation
echo "1️⃣  Checking OpenCode installation..."
if ! command -v opencode &> /dev/null; then
    echo "❌ OpenCode not found in PATH"
    echo "   Run: curl -fsSL https://opencode.ai/install | bash"
    exit 1
fi

OPENCODE_VERSION=$(opencode --version 2>&1 || echo "unknown")
echo "✅ OpenCode installed: v$OPENCODE_VERSION"
echo

# 2. Check configuration files
echo "2️⃣  Checking configuration files..."
CONFIG_DIR="$HOME/.config/opencode"

if [ ! -f "$CONFIG_DIR/config.toml" ]; then
    echo "❌ config.toml not found"
    echo "   Expected: $CONFIG_DIR/config.toml"
    exit 1
fi
echo "✅ config.toml found"

if [ ! -f "$CONFIG_DIR/opencode.json" ]; then
    echo "⚠️  opencode.json not found (optional)"
else
    echo "✅ opencode.json found"
fi

if [ ! -d "$CONFIG_DIR/agents" ]; then
    echo "⚠️  agents/ directory not found"
else
    echo "✅ agents/ directory found"
    AGENT_COUNT=$(ls -1 "$CONFIG_DIR/agents"/*.md 2>/dev/null | wc -l)
    echo "   └─ $AGENT_COUNT custom agent(s)"
fi
echo

# 3. Check Nemotron service
echo "3️⃣  Checking Nemotron service..."
NEMOTRON_URL="http://localhost:8010/health"

if curl -s -f "$NEMOTRON_URL" &> /dev/null; then
    echo "✅ Nemotron service healthy (port 8010)"
else
    echo "❌ Nemotron service not responding"
    echo "   URL: $NEMOTRON_URL"
    echo "   Run: ./start_all_safe.sh start inference"
    exit 1
fi
echo

# 4. Check Nemotron inference
echo "4️⃣  Testing Nemotron inference..."
INFERENCE_TEST=$(curl -s http://localhost:8010/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "nemotron-coding",
        "messages": [{"role": "user", "content": "Say hello in one word"}],
        "max_tokens": 10,
        "temperature": 0.6
    }' | jq -r '.choices[0].message.content' 2>/dev/null || echo "ERROR")

if [ "$INFERENCE_TEST" = "ERROR" ]; then
    echo "❌ Nemotron inference failed"
    echo "   Check: docker logs nemotron-coding"
    exit 1
fi

echo "✅ Nemotron inference working"
echo "   Response: $INFERENCE_TEST"
echo

# 5. Check fallback model
echo "5️⃣  Checking fallback model (RTX 2070)..."
if docker ps --format '{{.Names}}' | grep -q "coding-model-fallback"; then
    echo "✅ Fallback model running (Qwen2.5-Coder-3B)"
else
    echo "⚠️  Fallback model not running"
fi
echo

# 6. Check vision model
echo "6️⃣  Checking vision model (Qwen3-VL)..."
if docker ps --format '{{.Names}}' | grep -q "qwen3-vl-api"; then
    echo "✅ Vision model running (RTX 2070)"
else
    echo "⚠️  Vision model not running"
    echo "   Run: ./start_all_safe.sh start inference"
fi
echo

# 7. GPU status
echo "7️⃣  GPU allocation:"
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader | while IFS=, read -r idx name mem_used mem_total; do
    echo "   GPU $idx: $name - $mem_used / $mem_total"
done
echo

# 8. OpenCode config verification
echo "8️⃣  OpenCode configuration:"
if grep -q "nemotron-coding" "$CONFIG_DIR/config.toml" 2>/dev/null; then
    echo "✅ Nemotron provider configured"
else
    echo "❌ Nemotron provider not found in config"
fi

if grep -q "qwen3-vl" "$CONFIG_DIR/config.toml" 2>/dev/null; then
    echo "✅ Vision provider configured"
else
    echo "⚠️  Vision provider not found in config"
fi

if grep -q "shml-platform" "$CONFIG_DIR/config.toml" 2>/dev/null; then
    echo "✅ MCP server configured"
else
    echo "⚠️  MCP server not configured (optional)"
fi
echo

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ OpenCode + Nemotron setup verified!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo "🚀 Ready to use OpenCode:"
echo "   $ cd /path/to/project"
echo "   $ opencode"
echo
echo "💡 Quick test:"
echo "   $ cd ${PLATFORM_ROOT:-.}"
echo "   $ opencode"
echo "   > write a python hello world script"
echo
echo "📚 Documentation: https://opencode.ai/docs"
echo
