#!/bin/bash
# SHML CLI Setup Script
# Installs the CLI tool and sets up shell completion

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_PATH="$SCRIPT_DIR/shml.py"

echo "🚀 SHML CLI Setup"
echo "=================="

# Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
pip install --quiet typer rich httpx

# Make CLI executable
chmod +x "$CLI_PATH"

# Create symlink in PATH
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"

# Remove existing symlink if present
rm -f "$LOCAL_BIN/shml"

# Create new symlink
ln -sf "$CLI_PATH" "$LOCAL_BIN/shml"
echo "✓ Created symlink: $LOCAL_BIN/shml -> $CLI_PATH"

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
    echo ""
    echo "⚠️  ~/.local/bin is not in your PATH"
    echo ""
    echo "Add this to your ~/.bashrc or ~/.zshrc:"
    echo '  export PATH="$HOME/.local/bin:$PATH"'
    echo ""
    echo "Then run: source ~/.bashrc  (or ~/.zshrc)"
fi

# Generate shell completion
echo ""
echo "📋 Generating shell completion..."

# Bash completion
BASH_COMPLETION_DIR="$HOME/.local/share/bash-completion/completions"
mkdir -p "$BASH_COMPLETION_DIR"
"$CLI_PATH" --install-completion bash 2>/dev/null || \
    _SHML_COMPLETE=bash_source "$CLI_PATH" > "$BASH_COMPLETION_DIR/shml" 2>/dev/null || true

# Zsh completion
ZSH_COMPLETION_DIR="$HOME/.zfunc"
mkdir -p "$ZSH_COMPLETION_DIR"
"$CLI_PATH" --install-completion zsh 2>/dev/null || \
    _SHML_COMPLETE=zsh_source "$CLI_PATH" > "$ZSH_COMPLETION_DIR/_shml" 2>/dev/null || true

echo "✓ Completion installed"

# Test the CLI
echo ""
echo "🧪 Testing CLI..."
if command -v shml &> /dev/null; then
    echo "✓ CLI is available in PATH"
else
    echo "⚠️  CLI not found in PATH yet. Run: source ~/.bashrc"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✓ SHML CLI Setup Complete!"
echo ""
echo "Usage:"
echo "  shml --help              # Show all commands"
echo "  shml run \"task\"          # Run agent task"
echo "  shml chat \"question\"     # Quick chat"
echo "  shml status              # Show status"
echo "  shml gpu status          # GPU status"
echo "  shml mcp tools           # List MCP tools"
echo "  shml platform start      # Start services"
echo ""
echo "Tab completion enabled for bash/zsh!"
echo "═══════════════════════════════════════════════════════════"
