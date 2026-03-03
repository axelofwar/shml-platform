#!/bin/bash
# Tmux session for OpenCode development workflow
# Usage: ./scripts/tmux-opencode-dev.sh
#
# Layout:
#   ┌──────────────────────────────────────────┐
#   │ OpenCode TUI (Main - 70% height)         │
#   │                                          │
#   ├──────────────────────────────────────────┤
#   │ GPU Monitor (30% height)                 │
#   └──────────────────────────────────────────┘

SESSION="opencode-dev"
PROJECT_ROOT="/home/axelofwar/Projects/shml-platform"

# Kill existing session if present
tmux kill-session -t $SESSION 2>/dev/null

# Create new session
tmux new-session -d -s $SESSION -c $PROJECT_ROOT

# Set window name
tmux rename-window -t $SESSION:0 "dev"

# Main pane: OpenCode
tmux send-keys -t $SESSION:0 "cd $PROJECT_ROOT" C-m
tmux send-keys -t $SESSION:0 "# OpenCode ready - type 'opencode' to start" C-m

# Split horizontally (main 70%, bottom 30%)
tmux split-window -t $SESSION:0 -v -p 30 -c $PROJECT_ROOT

# Bottom pane: GPU Monitor
tmux send-keys -t $SESSION:0.1 "watch -n 2 'nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader'" C-m

# Select main pane
tmux select-pane -t $SESSION:0.0

# Attach to session
tmux attach -t $SESSION
