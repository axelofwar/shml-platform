# Agentic Coding Model Service

Self-hosted **Qwen3-Coder-30B-A3B** with dynamic GPU allocation for seamless coding assistance alongside ML training.

## Features

- **Dynamic GPU Allocation**: Automatically switches between GPUs based on training status
  - **RTX 3090 Ti (24GB)**: Best quality FP8 model when training is idle
  - **RTX 2070 (8GB)**: AWQ quantized fallback, always available during training
- **OpenAI-Compatible API**: Works with VS Code extensions (Continue.dev, Cline, etc.)
- **Training-Aware**: Monitors Ray cluster and yields GPU to training jobs
- **Agentic Coding**: Native tool-calling support for complex coding tasks
- **RAG-Enhanced Memory**: Conversation history with hybrid search + reranking
- **Change Staging**: Copilot-like approve/reject workflow for code changes

## Memory System Features

### Conversation Memory
- **Hybrid Search**: Vector similarity + BM25 keyword search
- **Cross-Encoder Reranking**: 20-30% precision improvement
- **Auto-Tagging**: Conversations classified as bugs, lessons, design decisions, etc.
- **Project Scoping**: Memories scoped to specific projects/workspaces
- **Decay System**: Importance decay with configurable archive/delete thresholds

### Auto-Tag Categories
| Tag | Description |
|-----|-------------|
| `bug` | Bug reports and fixes |
| `lesson` | Lessons learned |
| `implementation` | Feature implementations |
| `design_decision` | Architecture choices |
| `research` | Research and learning |
| `known_issue` | Known problems |
| `repeatable_pattern` | Reusable patterns |
| `edge_case_solved` | Edge case solutions |
| `configuration` | Config/setup discussions |
| `debug_session` | Debugging sessions |
| `performance` | Optimization work |
| `security` | Security discussions |

### Change Staging
Similar to GitHub Copilot's change approval:
- Stage code changes without immediately applying
- Review diffs before approval
- Apply, reject, or revert changes
- Full audit trail

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        TRAINING IDLE                                     │
│  ┌───────────────────────┐      ┌─────────────────────────────────────┐ │
│  │   RTX 3090 Ti (24GB)  │      │         RTX 2070 (8GB)              │ │
│  │ Qwen3-Coder-30B-FP8   │      │   Available for Qwen3-VL            │ │
│  │ 64K context, best     │      │                                     │ │
│  └───────────────────────┘      └─────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                        Training Job Starts
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      TRAINING ACTIVE                                     │
│  ┌───────────────────────┐      ┌─────────────────────────────────────┐ │
│  │   RTX 3090 Ti (24GB)  │      │         RTX 2070 (8GB)              │ │
│  │ 🔒 RAY TRAINING       │      │ Qwen3-Coder-30B-AWQ                 │ │
│  │    Model unloaded     │      │ 16K context, good quality           │ │
│  └───────────────────────┘      └─────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Build and Start

```bash
cd /opt/shml-platform/inference/coding-model
docker compose build
docker compose up -d
```

### 2. Check Status

```bash
# Health check
curl http://localhost:8000/health

# Detailed GPU status
curl http://localhost:8000/status
```

### 3. Test Completion

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-coder",
    "messages": [{"role": "user", "content": "Write a Python function to merge sort"}],
    "temperature": 0.7,
    "max_tokens": 1024
  }'
```

## VS Code Integration

### Continue.dev

Add to `~/.continue/config.json`:

```json
{
  "models": [
    {
      "title": "Qwen3-Coder (Local)",
      "provider": "openai",
      "model": "qwen3-coder",
      "apiBase": "http://localhost/api/coding/v1",
      "apiKey": "not-needed"
    }
  ]
}
```

### Cline

In VS Code settings:

```json
{
  "cline.apiProvider": "openai-compatible",
  "cline.openaiBaseUrl": "http://localhost/api/coding/v1",
  "cline.openaiApiKey": "not-needed",
  "cline.openaiModelId": "qwen3-coder"
}
```

## API Endpoints

### Core Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | OpenAI-compatible chat |
| `/v1/models` | GET | List available models |
| `/health` | GET | Health check |
| `/status` | GET | Detailed GPU/model status |
| `/admin/yield-primary` | POST | Force unload 3090 Ti model |
| `/admin/reclaim-primary` | POST | Force load 3090 Ti model |

### Memory Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/memory/store` | POST | Store conversation as memory |
| `/memory/search` | POST | Search memories (hybrid + rerank) |
| `/memory/context` | POST | Get context for prompt injection |
| `/memory/{id}` | DELETE | Delete memory (soft/hard) |
| `/memory/decay` | POST | Apply importance decay |

### Change Staging Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/changes/stage` | POST | Stage a code change |
| `/changes/stage-multiple` | POST | Stage multiple changes |
| `/changes/pending` | GET | Get pending changes |
| `/changes/{id}/approve` | POST | Approve a change |
| `/changes/{id}/reject` | POST | Reject a change |
| `/changes/{id}/apply` | POST | Apply approved change |
| `/changes/{id}/revert` | POST | Revert applied change |
| `/changes/approve-all` | POST | Approve & apply all pending |
| `/changes/reject-all` | POST | Reject all pending |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PRIMARY_MODEL_ID` | `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8` | Model for RTX 3090 Ti |
| `FALLBACK_MODEL_ID` | `Qwen/Qwen3-Coder-30B-A3B-Instruct-AWQ` | Model for RTX 2070 |
| `RAY_ADDRESS` | `http://ray-head:8265` | Ray cluster address |
| `YIELD_DELAY_SECONDS` | `30` | Wait before yielding to training |
| `RECLAIM_DELAY_SECONDS` | `60` | Wait before reclaiming after training |
| `IDLE_TIMEOUT_SECONDS` | `600` | Unload after idle (0=never) |

## Model Comparison

| Aspect | Primary (3090 Ti) | Fallback (2070) |
|--------|-------------------|-----------------|
| Model | Qwen3-Coder-30B-FP8 | Qwen3-Coder-30B-AWQ |
| VRAM | ~18GB | ~6-7GB |
| Context | 64K tokens | 16K tokens |
| Quality | Best | Good |
| Availability | When training idle | Always |

## Monitoring

GPU metrics are exported via DCGM exporter and visible in Grafana:
- `http://localhost/grafana` → GPU Dashboard
- Prometheus: `DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_MEM_COPY_UTIL`

## Troubleshooting

### Model won't load
```bash
# Check logs
docker logs coding-model -f

# Verify HuggingFace cache
docker exec coding-model ls -la /models
```

### Out of memory
```bash
# Force yield primary model
curl -X POST http://localhost:8000/admin/yield-primary

# Reduce context length in config
MAX_MODEL_LEN=8192
```

### Training detection not working
```bash
# Check Ray status manually
curl http://ray-head:8265/api/jobs/
```
