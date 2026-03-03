# Agentic Development Guide

> Full Autonomous AI-Assisted Development with SHML Platform

## Overview

This guide covers the SHML Platform's **FULL AGENTIC DEVELOPMENT** capabilities, enabling autonomous feature development with:

- ✅ **Nemotron-3 Nano 30B** - Coding model with tool calling (RTX 3090 Ti)
- ✅ **Qwen3-VL** - Vision model for screenshot/image analysis (RTX 2070)
- ✅ **ACE Agent Framework** - Generator-Reflector-Curator pattern
- ✅ **MCP Tools** - Training status, GPU monitoring, MLflow queries, vision
- ✅ **Composable Skills** - GitHub, Sandbox, Ray Jobs
- ✅ **OpenCode Integration** - CLI-based agent with full tool support
- ✅ **tmux Orchestration** - Parallel subagent workflows

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     User Interface Layer                            │
├─────────────┬─────────────┬─────────────────────────────────────────┤
│  OpenCode   │   VSCode    │              Chat UI                    │
│    CLI      │  Continue   │            (React)                      │
└──────┬──────┴──────┬──────┴──────────────────┬─────────────────────┘
       │             │                          │
       ▼             ▼                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      Agent Service (ACE Pattern)                     │
│  ┌──────────┐  ┌───────────┐  ┌─────────┐  ┌───────────────────────┐│
│  │Generator │→ │ Reflector │→ │ Curator │→ │    MCP Tools          ││
│  │(Propose) │  │ (Critique)│  │(Extract)│  │ - training_status     ││
│  └──────────┘  └───────────┘  └─────────┘  │ - gpu_status          ││
│                                             │ - mlflow_query        ││
│  Skills: GitHub | Sandbox | Ray Jobs        │ - vision_analyze      ││
└──────────────────────────────────────────────────────────────────────┘
       │                                            │
       ▼                                            ▼
┌────────────────────────────┐      ┌────────────────────────────────┐
│  Nemotron-3 Nano 30B       │      │       Qwen3-VL 8B              │
│  (RTX 3090 Ti, 24GB)       │      │    (RTX 2070, 8GB)             │
│  - Tool Calling ✅          │      │  - Vision Analysis ✅           │
│  - Code Generation          │      │  - Screenshot Understanding    │
│  - temp=0.6, top_p=0.95     │      │  - INT4 Quantized              │
└────────────────────────────┘      └────────────────────────────────┘
```

## Quick Start

### 1. Verify Services Running

```bash
# Check platform status
./start_all_safe.sh status

# Verify Nemotron is running
curl http://localhost:8010/health
# {"status":"ok"}

# Verify Agent Service is running
docker exec shml-agent-service curl http://localhost:8000/health
# {"status":"healthy",...}
```

### 2. Test Tool Calling

```bash
# Test Nemotron tool calling
curl http://localhost:8010/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nemotron-coding",
    "messages": [{"role": "user", "content": "Read the README.md file"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "read_file",
        "description": "Read file contents",
        "parameters": {
          "type": "object",
          "properties": {"path": {"type": "string"}},
          "required": ["path"]
        }
      }
    }],
    "tool_choice": "auto"
  }'
```

### 3. Launch OpenCode

```bash
# Interactive agentic session
opencode

# With specific task
opencode "Create a new health check endpoint for the user service"
```

## MCP Tools

The platform exposes these MCP tools via `/api/agent/mcp`:

| Tool | Description | GPU | Safe During Training |
|------|-------------|-----|---------------------|
| `training_status` | Ray job status, MLflow metrics | None | ✅ Always |
| `gpu_status` | VRAM usage, processes, temps | None | ✅ Always |
| `mlflow_query` | Query experiments and runs | None | ✅ Always |
| `vision_analyze` | Image analysis with Qwen3-VL | cuda:1 | ✅ Always |
| `vision_then_code` | Vision → Code pipeline | cuda:0 | ⚠️ Blocked during training |

### Using MCP Tools

```bash
# List available tools
curl http://localhost/api/agent/mcp/tools | jq .

# Check MCP health
curl http://localhost/api/agent/mcp/health | jq .

# Call a tool
curl -X POST http://localhost/api/agent/mcp/call \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "gpu_status",
    "arguments": {}
  }'
```

## Subagent Orchestration

Use tmux-based subagents for parallel workflows:

```bash
# Full autonomous development workflow
./scripts/subagent-orchestrate.sh launch full "Add user preferences API"

# Individual subagents
./scripts/subagent-orchestrate.sh launch research "Best practices for pagination"
./scripts/subagent-orchestrate.sh launch code "Create preferences endpoint"
./scripts/subagent-orchestrate.sh launch test "Test preferences API"
./scripts/subagent-orchestrate.sh launch git "Prepare PR for preferences feature"

# Check subagent status
./scripts/subagent-orchestrate.sh status

# Attach to a subagent session
tmux attach-session -t shml-agent-research
```

## VSCode Integration

### VS Code Tasks (Ctrl+Shift+P → "Run Task")

- **Start Platform (Safe)** - Full platform startup
- **Restart Inference Services** - Restart models
- **Launch Subagent - Full Workflow** - Interactive task prompt
- **Test Nemotron Tool Calling** - Verify tool calling works
- **Test MCP Tools** - List available MCP tools
- **OpenCode Session** - Launch OpenCode in terminal

### Continue.dev Integration

The platform is configured for Continue.dev (VSCode extension):

1. Install Continue.dev extension
2. Settings are pre-configured in `.vscode/settings.json`
3. Select "Nemotron-3 (Local)" as model

## OpenCode Configuration

Configuration at `~/.config/opencode/opencode.json`:

```json
{
  "model": "nemotron/nemotron-coding",
  "provider": {
    "nemotron": {
      "options": {"baseURL": "http://localhost:8010/v1"},
      "models": {
        "nemotron-coding": {
          "tool_call": true,
          "limit": {"context": 65536, "output": 16384}
        }
      }
    }
  },
  "tools": {
    "read": true, "write": true, "edit": true,
    "bash": true, "grep": true, "glob": true,
    "list": true, "webfetch": true, "patch": true
  }
}
```

## GPU Resource Management

### GPU Assignment

| GPU | Device | VRAM | Assignment |
|-----|--------|------|------------|
| RTX 3090 Ti | cuda:0 | 24GB | Nemotron-3 (coding), Z-Image (yields) |
| RTX 2070 | cuda:1 | 8GB | Qwen3-VL (vision, always loaded) |

### Training Safety

The platform automatically blocks certain operations during training:

```python
# MCP tools check training status automatically
training_active, info = await TrainingStatusChecker.is_training_active()

if training_active:
    # vision_then_code tool returns error instead of blocking RTX 3090
    return {"error": "RTX 3090 Ti busy with training"}
```

### Z-Image Yield Protocol

Before training, request Z-Image to free RTX 3090:

```bash
curl -X POST http://localhost/api/image/yield-to-training
```

## ACE Agent Pattern

The agent service implements the **ACE (Agentic Context Engineering)** pattern:

### Generator
- Proposes actions based on playbook context
- Uses active skills (GitHub, Sandbox, Ray)
- Generates tool calls for execution

### Reflector
- Self-critiques using Kimi K2-style rubrics
- Scores: accuracy, completeness, safety, style
- Suggests improvements before execution

### Curator
- Extracts lessons learned from successful tasks
- Updates playbook context for future tasks
- Builds project-specific knowledge base

## Composable Skills

Skills are activated based on task keywords:

### GitHubSkill
- **Triggers**: github, repository, pull request, issue, commit
- **Operations**: list_repos, create_issue, create_pr, list_commits
- **Auth**: Uses Composio with GitHub token from FusionAuth

### SandboxSkill
- **Triggers**: execute, run, test, sandbox, python, node
- **Operations**: run_code (in isolated container)
- **Permissions**: Requires elevated-developer role

### RayJobSkill
- **Triggers**: ray, training, distributed, gpu, cluster
- **Operations**: submit_job, get_status, get_metrics, cancel_job
- **Features**: Curriculum learning, face detection training

## Troubleshooting

### Nemotron Not Responding

```bash
# Check container health
docker logs nemotron-coding --tail 50

# Restart safely
./start_all_safe.sh restart inference
```

### Tool Calls Not Working

```bash
# Test tool calling directly
curl http://localhost:8010/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"nemotron-coding","messages":[{"role":"user","content":"Hi"}]}'
```

### Vision Model Errors

```bash
# Check Qwen3-VL status
docker logs qwen3-vl-api --tail 20

# Vision model auto-loads on first request
curl http://localhost:8080/api/llm/health
```

### Agent Service Issues

```bash
# Check agent service logs
docker logs shml-agent-service --tail 50

# Rebuild and restart
docker compose -f inference/agent-service/docker-compose.yml up -d --build
```

## Best Practices

### For Full Autonomous Development

1. **Start with Research** - Let the research subagent gather context first
2. **Use ACE Pattern** - Let Generator-Reflector-Curator improve code quality
3. **Monitor GPU Status** - Check before heavy operations
4. **Review Before Git Push** - Always review generated code before pushing

### For Tool Calling

1. **Clear Tool Descriptions** - Provide detailed function descriptions
2. **Required Parameters** - Mark essential params as required
3. **Error Handling** - Handle tool call failures gracefully
4. **Timeout Awareness** - Long operations may timeout

### For Vision Analysis

1. **RTX 2070 Always Available** - Vision never blocks training
2. **First Request Load Time** - ~30s to load model on first request
3. **Prompt Specificity** - Be specific in vision prompts
4. **Base64 or URL** - Both image formats supported

## Version Information

- **Nemotron-3**: Nano-30B-A3B Q4_K_XL (tool calling enabled)
- **Qwen3-VL**: 8B INT4 quantized
- **Agent Service**: ACE v1.0 with MCP support
- **OpenCode Config**: 65536 context, 16384 output tokens

---

**Last Updated**: December 2024
**Platform Version**: 0.2.0
