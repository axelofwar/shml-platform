#!/bin/bash
# SHML Shell Aliases
# Source this file in your .bashrc or .zshrc:
#   source /path/to/shml-platform/cli/aliases.sh

# Project directory
export SHML_DIR="${SHML_DIR:-/home/axelofwar/Projects/shml-platform}"

# === Core Shortcuts ===
alias shml='python3 $SHML_DIR/cli/shml.py'

# === Agent Shortcuts ===
alias sa='shml agent'
alias sar='shml agent run'
alias sac='shml agent chat'
alias sas='shml agent status'

# === GPU Shortcuts ===
alias sg='shml gpu'
alias sgs='shml gpu status'
alias sgy='shml gpu yield'
alias sgr='shml gpu reclaim'

# === Training Shortcuts ===
alias st='shml training'
alias sts='shml training status'
alias stsub='shml training submit'

# === MCP Shortcuts ===
alias sm='shml mcp'
alias smt='shml mcp tools'
alias smc='shml mcp call'

# === Platform Shortcuts ===
alias sp='shml platform'
alias sps='shml platform status'
alias spstart='shml platform start'
alias spstop='shml platform stop'
alias spl='shml platform logs'

# === Quick Shortcuts ===
alias run='shml run'
alias chat='shml chat'

# === Common Tasks ===

# Quick GPU check with nvidia-smi
alias gpustat='nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv'

# Watch GPU usage
alias gpuwatch='watch -n 1 nvidia-smi'

# Agent service logs
alias agentlogs='docker logs agent-service -f --tail=100'
alias nemlogs='docker logs nemotron-api -f --tail=100'

# Platform quick actions
alias pstart='$SHML_DIR/start_all_safe.sh start'
alias pstop='$SHML_DIR/start_all_safe.sh stop'
alias prestart='$SHML_DIR/start_all_safe.sh restart'
alias pstatus='$SHML_DIR/check_platform_status.sh'

# === Functions ===

# Quick agent task
agentrun() {
    shml agent run "$*"
}

# Quick chat
agentchat() {
    shml agent chat "$*"
}

# Call MCP tool with pretty output
mcptool() {
    local tool="$1"
    shift
    shml mcp call "$tool" "$@"
}

# Tail multiple service logs
logs() {
    local services="${@:-agent-service nemotron-api}"
    docker compose -f $SHML_DIR/docker-compose.yml logs -f $services
}

# Quick service restart
srestart() {
    local service="${1:-inference}"
    $SHML_DIR/start_all_safe.sh restart "$service"
}

# Submit training with GPU yield
train() {
    local script="$1"
    local gpu="${2:-0}"
    shml training submit "$script" --gpu "$gpu"
}

# Watch training status
watchtraining() {
    watch -n 5 'shml training status 2>/dev/null || echo "No training jobs"'
}

# Health check all services
healthcheck() {
    echo "🔍 Checking services..."
    echo ""
    curl -s http://localhost/api/agent/health 2>/dev/null && echo " ✓ Agent Service" || echo " ✗ Agent Service"
    curl -s http://localhost:8010/health 2>/dev/null && echo " ✓ Nemotron" || echo " ✗ Nemotron"
    curl -s http://localhost:5001/health 2>/dev/null && echo " ✓ MLflow" || echo " ✗ MLflow"
    curl -s http://localhost:8265/api/version 2>/dev/null && echo " ✓ Ray" || echo " ✗ Ray"
}

echo "🚀 SHML aliases loaded! Type 'shml --help' for commands"
