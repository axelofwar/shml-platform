#!/bin/bash
# OpenCode Demo - Quick Start Guide
# Shows how to use OpenCode with Nemotron for coding tasks

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 OpenCode + Nemotron Quick Start Demo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo "This script demonstrates OpenCode usage patterns."
echo "OpenCode is an AI coding assistant with a terminal UI."
echo

# Check if OpenCode is installed
if ! command -v opencode &> /dev/null; then
    echo "❌ OpenCode not installed"
    echo "   Run: curl -fsSL https://opencode.ai/install | bash"
    exit 1
fi

echo "✅ OpenCode installed (version $(opencode --version))"
echo

# Show configuration
echo "📋 Current Configuration:"
echo "   Primary Model: Nemotron-3-Nano-30B-A3B"
echo "   Vision Model: Qwen3-VL-8B"
echo "   Fallback: Qwen2.5-Coder-3B"
echo "   Config: ~/.config/opencode/config.toml"
echo

# Basic usage examples
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📚 Basic Usage Examples"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

echo "1️⃣  Start OpenCode in current directory:"
echo "   $ opencode"
echo

echo "2️⃣  Simple coding task:"
echo "   > write a python function to reverse a string"
echo

echo "3️⃣  Use sub-agents:"
echo "   > @general research best practices for training YOLOv8"
echo "   > @explore find all training scripts in this project"
echo "   > @build implement a new training pipeline"
echo

echo "4️⃣  File operations:"
echo "   > read train.py and explain the main loop"
echo "   > update all python files to use type hints"
echo

echo "5️⃣  Shell commands:"
echo "   > !ls -la *.py"
echo "   > !git status"
echo

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⌨️  Keybindings Reference"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

cat << 'EOF'
Tab         - Switch between Build/Plan agents
Ctrl+x h    - Help dialog
Ctrl+x n    - New session
Ctrl+x l    - List sessions
Ctrl+x u    - Undo (reverts file changes!)
Ctrl+x r    - Redo
Ctrl+x e    - Open external editor ($EDITOR)
@           - Fuzzy file search
!           - Run shell command

Slash Commands:
/help       - Show all commands
/sessions   - Switch between sessions
/undo       - Undo last message + file changes
/redo       - Redo undone message
/compact    - Summarize session to save tokens
/share      - Share session URL
EOF

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 Ready to Start!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

read -p "Do you want to start OpenCode now? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🚀 Starting OpenCode..."
    echo
    cd /home/axelofwar/Projects/shml-platform
    opencode
else
    echo "📚 When ready, run:"
    echo "   $ cd /home/axelofwar/Projects/shml-platform"
    echo "   $ opencode"
    echo
    echo "💡 Try this first prompt:"
    echo '   > write a python hello world script with logging'
    echo
fi
