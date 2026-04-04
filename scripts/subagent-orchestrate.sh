#!/bin/bash
# SHML Platform - Subagent Orchestration via tmux
# Enables parallel AI agent workflows for autonomous feature development
#
# Usage:
#   ./scripts/subagent-orchestrate.sh launch <task-type> <task-description>
#   ./scripts/subagent-orchestrate.sh status
#   ./scripts/subagent-orchestrate.sh kill <session-name>
#
# Task Types:
#   research    - Web search and documentation gathering
#   code        - File creation and editing
#   test        - Test execution and validation
#   git         - Version control operations
#   vision      - Screenshot/image analysis
#   full        - Full autonomous development workflow
#
# Example:
#   ./scripts/subagent-orchestrate.sh launch full "Create a new API endpoint for user preferences"

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(dirname "$SCRIPT_DIR")"
SESSION_PREFIX="shml-agent"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check prerequisites
check_prerequisites() {
    if ! command -v tmux &> /dev/null; then
        log_error "tmux is not installed. Install with: sudo apt install tmux"
        exit 1
    fi

    if ! command -v opencode &> /dev/null; then
        log_warn "opencode CLI not found. Install with: npm install -g opencode"
    fi

    # Check if agent service is running
    if ! docker ps --format '{{.Names}}' | grep -q "shml-agent-service"; then
        log_warn "Agent service not running. Starting..."
        cd "$PLATFORM_DIR" && docker compose --env-file .env -f inference/agent-service/docker-compose.yml up -d
        sleep 5
    fi

    # Check if nemotron is running
    if ! docker ps --format '{{.Names}}' | grep -q "qwopus-coding"; then
        log_error "Nemotron coding model not running! Start with: ./start_all_safe.sh start inference"
        exit 1
    fi
}

# Create research subagent
launch_research_agent() {
    local task="$1"
    local session="${SESSION_PREFIX}-research"

    log_info "Launching research subagent for: $task"

    tmux new-session -d -s "$session" -c "$PLATFORM_DIR"
    tmux send-keys -t "$session" "
# Research Subagent - Web search and documentation
# Task: $task

# Subagent prompt for OpenCode
cat << 'RESEARCH_PROMPT' | opencode --no-interactive
You are a RESEARCH SUBAGENT. Your role is to gather context for the task.

TASK: $task

INSTRUCTIONS:
1. Use webfetch tool to search for:
   - Similar implementations in popular projects
   - Best practices documentation
   - Potential libraries or patterns to use
2. Summarize findings in a clear format
3. Create a file at: research/task_context.md with your findings
4. Include code snippets, links, and recommendations

OUTPUT FORMAT:
## Research Summary for: [Task]
### Similar Implementations Found
### Best Practices
### Recommended Approach
### Code Patterns to Follow
### Potential Issues to Watch For

Begin research now.
RESEARCH_PROMPT
" Enter

    log_success "Research subagent launched in tmux session: $session"
}

# Create code generation subagent
launch_code_agent() {
    local task="$1"
    local session="${SESSION_PREFIX}-code"

    log_info "Launching code generation subagent for: $task"

    tmux new-session -d -s "$session" -c "$PLATFORM_DIR"
    tmux send-keys -t "$session" "
# Code Generation Subagent
# Task: $task

opencode << 'CODE_PROMPT'
You are a CODE GENERATION SUBAGENT using Nemotron-3 for agentic coding.

TASK: $task

INSTRUCTIONS:
1. First, read the research context if available:
   - Use read tool on research/task_context.md
2. Analyze the existing codebase:
   - Use grep and glob tools to find similar patterns
   - Use read tool on relevant existing files
3. Generate the implementation:
   - Use write tool to create new files
   - Use edit tool to modify existing files
   - Follow existing code patterns and style
4. Create a summary:
   - Write changes to: changes/implementation_summary.md

QUALITY STANDARDS:
- Follow existing project patterns
- Add proper error handling
- Include docstrings/comments
- Use type hints (Python) or TypeScript types

Begin implementation now.
CODE_PROMPT
" Enter

    log_success "Code generation subagent launched in tmux session: $session"
}

# Create test subagent
launch_test_agent() {
    local task="$1"
    local session="${SESSION_PREFIX}-test"

    log_info "Launching test subagent for: $task"

    tmux new-session -d -s "$session" -c "$PLATFORM_DIR"
    tmux send-keys -t "$session" "
# Test Subagent
# Task: $task

opencode << 'TEST_PROMPT'
You are a TEST SUBAGENT. Verify the implementation works correctly.

TASK: Verify implementation of: $task

INSTRUCTIONS:
1. Read the implementation summary:
   - Use read tool on changes/implementation_summary.md
2. Identify test requirements:
   - What functions/endpoints need testing?
   - What edge cases exist?
3. Create tests:
   - Use write tool to create test files in tests/
   - Follow existing test patterns (pytest)
4. Run tests:
   - Use bash tool to run: pytest tests/ -v
5. Report results:
   - Write test results to: changes/test_results.md

Begin testing now.
TEST_PROMPT
" Enter

    log_success "Test subagent launched in tmux session: $session"
}

# Create git subagent
launch_git_agent() {
    local task="$1"
    local session="${SESSION_PREFIX}-git"

    log_info "Launching git subagent for: $task"

    tmux new-session -d -s "$session" -c "$PLATFORM_DIR"
    tmux send-keys -t "$session" "
# Git Subagent
# Task: $task

opencode << 'GIT_PROMPT'
You are a GIT SUBAGENT. Manage version control for the implementation.

TASK: Prepare git changes for: $task

INSTRUCTIONS:
1. Check current git status:
   - Use bash tool: git status
2. Create a feature branch:
   - Branch name: feature/$(echo '$task' | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | cut -c1-50)
   - Use bash tool: git checkout -b <branch-name>
3. Stage relevant changes:
   - Use bash tool: git add <files>
4. Create a commit with conventional commit format:
   - feat: for new features
   - fix: for bug fixes
   - docs: for documentation
   - refactor: for code changes
5. Prepare a pull request description:
   - Write to: changes/pr_description.md

DO NOT push to remote - that requires human approval.

Begin git operations now.
GIT_PROMPT
" Enter

    log_success "Git subagent launched in tmux session: $session"
}

# Create vision subagent
launch_vision_agent() {
    local task="$1"
    local session="${SESSION_PREFIX}-vision"

    log_info "Launching vision subagent for: $task"

    # Check if vision model is available
    if ! curl -s http://localhost:8080/api/llm/health &> /dev/null; then
        log_error "Vision model (Qwen3-VL) not available. Check Traefik routing."
        return 1
    fi

    tmux new-session -d -s "$session" -c "$PLATFORM_DIR"
    tmux send-keys -t "$session" "
# Vision Subagent - Image/Screenshot Analysis
# Task: $task
# Model: Qwen3-VL-8B (RTX 2070)

# Note: Vision analysis via MCP tools
curl -X POST http://localhost/api/agent/mcp/call \\
  -H 'Content-Type: application/json' \\
  -d '{
    \"tool\": \"vision_analyze\",
    \"arguments\": {
      \"image\": \"<base64 or URL>\",
      \"prompt\": \"$task\"
    }
  }'

echo 'Vision subagent ready. Provide image URL or base64 for analysis.'
" Enter

    log_success "Vision subagent launched in tmux session: $session"
}

# Full autonomous development workflow
launch_full_workflow() {
    local task="$1"

    log_info "Launching FULL AUTONOMOUS DEVELOPMENT workflow"
    log_info "Task: $task"
    echo ""

    # Create workspace directories
    mkdir -p "$PLATFORM_DIR/research"
    mkdir -p "$PLATFORM_DIR/changes"

    # Phase 1: Research (parallel)
    log_info "Phase 1: Research..."
    launch_research_agent "$task"

    # Wait for research to complete (basic polling)
    log_info "Waiting for research phase (30s timeout)..."
    sleep 30

    # Phase 2: Code Generation (depends on research)
    log_info "Phase 2: Code Generation..."
    launch_code_agent "$task"

    # Wait for code generation
    log_info "Waiting for code generation (60s timeout)..."
    sleep 60

    # Phase 3: Testing (parallel with git)
    log_info "Phase 3: Testing & Git Operations (parallel)..."
    launch_test_agent "$task" &
    launch_git_agent "$task" &
    wait

    log_success "Full workflow launched!"
    log_info "Monitor progress with: ./scripts/subagent-orchestrate.sh status"
    log_info "Attach to session: tmux attach-session -t shml-agent-<type>"
}

# Show status of all subagent sessions
show_status() {
    log_info "Active subagent sessions:"
    echo ""

    tmux list-sessions 2>/dev/null | grep "$SESSION_PREFIX" || echo "No active subagent sessions"

    echo ""
    log_info "Agent service status:"
    docker ps --filter name=shml-agent --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

    echo ""
    log_info "Model status:"
    docker ps --filter name=nemotron --format "table {{.Names}}\t{{.Status}}"
    docker ps --filter name=qwen3-vl --format "table {{.Names}}\t{{.Status}}"
}

# Kill a specific subagent session
kill_session() {
    local session="$1"

    if [ -z "$session" ]; then
        log_warn "Killing all subagent sessions..."
        tmux list-sessions -F "#{session_name}" 2>/dev/null | grep "$SESSION_PREFIX" | while read s; do
            tmux kill-session -t "$s"
            log_info "Killed session: $s"
        done
    else
        if tmux has-session -t "$session" 2>/dev/null; then
            tmux kill-session -t "$session"
            log_success "Killed session: $session"
        else
            log_error "Session not found: $session"
        fi
    fi
}

# Main entry point
main() {
    local command="${1:-help}"

    case "$command" in
        launch)
            check_prerequisites
            local task_type="${2:-full}"
            local task_desc="${3:-Autonomous development task}"

            case "$task_type" in
                research) launch_research_agent "$task_desc" ;;
                code) launch_code_agent "$task_desc" ;;
                test) launch_test_agent "$task_desc" ;;
                git) launch_git_agent "$task_desc" ;;
                vision) launch_vision_agent "$task_desc" ;;
                full) launch_full_workflow "$task_desc" ;;
                *)
                    log_error "Unknown task type: $task_type"
                    log_info "Valid types: research, code, test, git, vision, full"
                    exit 1
                    ;;
            esac
            ;;
        status)
            show_status
            ;;
        kill)
            kill_session "$2"
            ;;
        help|*)
            echo "SHML Platform - Subagent Orchestration"
            echo ""
            echo "Usage:"
            echo "  $0 launch <task-type> \"<task-description>\""
            echo "  $0 status"
            echo "  $0 kill [session-name]"
            echo ""
            echo "Task Types:"
            echo "  research  - Web search and documentation gathering"
            echo "  code      - File creation and editing"
            echo "  test      - Test execution and validation"
            echo "  git       - Version control operations"
            echo "  vision    - Screenshot/image analysis"
            echo "  full      - Complete autonomous workflow (all phases)"
            echo ""
            echo "Examples:"
            echo "  $0 launch full \"Add user preference API endpoint\""
            echo "  $0 launch research \"Best practices for FastAPI pagination\""
            echo "  $0 launch vision \"Analyze UI screenshot for accessibility\""
            echo "  $0 status"
            echo "  $0 kill shml-agent-research"
            ;;
    esac
}

main "$@"
