#!/bin/bash
# SHML Shell Aliases
# Source this file in your .bashrc or .zshrc:
#   source /path/to/shml-platform/cli/aliases.sh

# Project directory
export SHML_DIR="${SHML_DIR:-${PLATFORM_ROOT:-.}}"

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

# === Skills & Learning ===

# List available skills (GitHub Copilot / agent-service)
alias skills='ls $SHML_DIR/.github/skills/'
alias askills='ls $SHML_DIR/inference/agent-service/skills/'

# View a skill
skill() {
    local name="${1:?Usage: skill <name>}"
    cat "$SHML_DIR/.github/skills/$name/SKILL.md" 2>/dev/null \
        || cat "$SHML_DIR/inference/agent-service/skills/$name/SKILL.md" 2>/dev/null \
        || echo "Skill '$name' not found"
}

# List + open stored prompts
alias prompts='ls $SHML_DIR/.github/prompts/'
prompt() {
    local name="${1:?Usage: prompt <filename>}"
    cat "$SHML_DIR/.github/prompts/$name" 2>/dev/null || echo "Prompt '$name' not found"
}

# View learnings log (today or specific date)
alias learnings='cat $SHML_DIR/.agent/learnings/$(date +%Y-%m-%d).jsonl 2>/dev/null | python3 -c "import sys,json; [print(json.dumps(json.loads(l), indent=2)) for l in sys.stdin if l.strip()]" || echo "No learnings for today"'
alias learnhist='ls $SHML_DIR/.agent/learnings/'

# === Connection Map ===

# Regenerate the platform connection map
alias connmap='python3 $SHML_DIR/scripts/generate_connection_map.py'

# === Obsidian Ingestion ===

# Ingest research / docs into Obsidian vault
alias obsidian-ingest='python3 $SHML_DIR/scripts/ingest_research_to_obsidian.py'

# Watch for new files and auto-ingest
alias obsidian-watch='python3 $SHML_DIR/scripts/obsidian_watcher.py'

# Open Obsidian vault path
alias vault='cd $SHML_DIR/docs/obsidian-vault'

# === Watchdog ===

# Run a one-shot memory/resource watchdog snapshot
alias watchdog='python3 $SHML_DIR/scripts/memory_watchdog.py --once'

# Run the foreground memory watchdog continuously
alias watchdog-live='python3 $SHML_DIR/scripts/memory_watchdog.py'

# Run self-healing watchdog loop
alias watchdog-loop='bash $SHML_DIR/scripts/self-healing/watchdog.sh'

# View watchdog admin panel status
alias watchdog-status='python3 $SHML_DIR/scripts/self-healing/watchdog_admin.py status'

# === GitLab Operations ===

alias gl='python3 $SHML_DIR/scripts/platform/gitlab_utils.py'
alias gl-issues='python3 $SHML_DIR/scripts/platform/gitlab_utils.py list-issues'
alias gl-issue='python3 $SHML_DIR/scripts/platform/gitlab_utils.py create-issue'
alias gl-board='python3 $SHML_DIR/scripts/platform/gitlab_utils.py setup-board'

# === Platform Scan & Board Sync ===

# Re-scan repo state and sync to GitLab Issues
alias platform-scan='bash $SHML_DIR/scripts/platform/scan_repo_state.sh'

# Update T8 pipeline state in GitLab Issues
alias gitlab-sync='bash $SHML_DIR/scripts/data/update_gitlab_board.sh'

# === Log Shortcuts ===

alias gw-logs='docker logs inference-gateway -f --tail=100'
alias llm-logs='docker logs qwen3-vl-api -f --tail=100'
alias img-logs='docker logs z-image-api -f --tail=100'
alias pglogs='docker logs shml-postgres -f --tail=100'

echo "🚀 SHML aliases loaded! Type 'skills' to list skills, 'shml --help' for CLI"
