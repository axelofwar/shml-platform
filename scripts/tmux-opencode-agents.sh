#!/bin/bash
# Tmux session for OpenCode with dedicated sub-agent workflows
# Usage: ./scripts/tmux-opencode-agents.sh
#
# Layout:
#   ┌─────────────────────┬─────────────────────┐
#   │ @general (Planning) │ @explore (Codebase) │
#   ├─────────────────────┼─────────────────────┤
#   │ @build (Implement)  │ Status/Logs         │
#   └─────────────────────┴─────────────────────┘

SESSION="opencode-agents"
PROJECT_ROOT="/home/axelofwar/Projects/shml-platform"

# Kill existing session if present
tmux kill-session -t $SESSION 2>/dev/null

# Create new session
tmux new-session -d -s $SESSION -c $PROJECT_ROOT

# Set window name
tmux rename-window -t $SESSION:0 "agents"

# Top-left: @general (Planning agent)
tmux send-keys -t $SESSION:0 "cd $PROJECT_ROOT" C-m
tmux send-keys -t $SESSION:0 "echo '📋 @general Agent - High-level planning and research'" C-m
tmux send-keys -t $SESSION:0 "echo 'Example: opencode'" C-m
tmux send-keys -t $SESSION:0 "echo '> @general research YOLOv8 P2 head improvements'" C-m

# Split vertically (50/50)
tmux split-window -t $SESSION:0 -h -p 50 -c $PROJECT_ROOT

# Top-right: @explore (Codebase exploration)
tmux send-keys -t $SESSION:0.1 "cd $PROJECT_ROOT" C-m
tmux send-keys -t $SESSION:0.1 "echo '🔍 @explore Agent - Codebase navigation and analysis'" C-m
tmux send-keys -t $SESSION:0.1 "echo 'Example: opencode'" C-m
tmux send-keys -t $SESSION:0.1 "echo '> @explore find all Ray training job submission code'" C-m

# Split bottom-left horizontally
tmux select-pane -t $SESSION:0.0
tmux split-window -t $SESSION:0.0 -v -p 50 -c $PROJECT_ROOT

# Bottom-left: @build (Implementation agent)
tmux send-keys -t $SESSION:0.2 "cd $PROJECT_ROOT" C-m
tmux send-keys -t $SESSION:0.2 "echo '🔨 @build Agent - Code generation and implementation'" C-m
tmux send-keys -t $SESSION:0.2 "echo 'Example: opencode'" C-m
tmux send-keys -t $SESSION:0.2 "echo '> @build create FastAPI endpoint for model inference'" C-m

# Split bottom-right horizontally
tmux select-pane -t $SESSION:0.1
tmux split-window -t $SESSION:0.1 -v -p 50 -c $PROJECT_ROOT

# Bottom-right: Status monitoring
tmux send-keys -t $SESSION:0.3 "cd $PROJECT_ROOT" C-m
tmux send-keys -t $SESSION:0.3 "# MCP Tools Status" C-m
tmux send-keys -t $SESSION:0.3 "curl -s http://localhost:8000/mcp/health | jq 2>/dev/null || echo 'MCP server not responding'" C-m

# Select top-left pane
tmux select-pane -t $SESSION:0.0

# Attach to session
tmux attach -t $SESSION
