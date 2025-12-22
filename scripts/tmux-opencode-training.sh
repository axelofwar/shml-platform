#!/bin/bash
# Tmux session for training monitoring with OpenCode
# Usage: ./scripts/tmux-opencode-training.sh
#
# Layout:
#   ┌─────────────────────┬─────────────────────┐
#   │ OpenCode (50%)      │ Training Logs (50%) │
#   ├─────────────────────┴─────────────────────┤
#   │ GPU + Platform Status (30%)               │
#   └───────────────────────────────────────────┘

SESSION="opencode-training"
PROJECT_ROOT="/home/axelofwar/Projects/shml-platform"

# Kill existing session if present
tmux kill-session -t $SESSION 2>/dev/null

# Create new session
tmux new-session -d -s $SESSION -c $PROJECT_ROOT

# Set window name
tmux rename-window -t $SESSION:0 "training"

# Main pane: OpenCode
tmux send-keys -t $SESSION:0 "cd $PROJECT_ROOT" C-m
tmux send-keys -t $SESSION:0 "# Training monitor - OpenCode ready" C-m

# Split vertically (left 50%, right 50%)
tmux split-window -t $SESSION:0 -h -p 50 -c $PROJECT_ROOT

# Right pane: Training logs (find latest)
tmux send-keys -t $SESSION:0.1 "# Watching for latest training logs..." C-m
tmux send-keys -t $SESSION:0.1 "LOG_FILE=\$(find logs/ -name '*.log' -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2)" C-m
tmux send-keys -t $SESSION:0.1 "if [ -n \"\$LOG_FILE\" ]; then tail -f \"\$LOG_FILE\"; else echo 'No training logs found'; fi" C-m

# Split bottom horizontally for monitoring
tmux select-pane -t $SESSION:0.0
tmux split-window -t $SESSION:0.0 -v -p 30 -c $PROJECT_ROOT

# Bottom pane: Combined GPU + Platform status
tmux send-keys -t $SESSION:0.2 "watch -n 3 'nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader && echo && docker ps --format \"table {{.Names}}\t{{.Status}}\" | grep -E \"(nemotron|qwen|ray|mlflow)\" | head -10'" C-m

# Select main pane
tmux select-pane -t $SESSION:0.0

# Attach to session
tmux attach -t $SESSION
