# OpenCode Configuration for SHML Platform

This directory contains OpenCode configuration for local Nemotron-3 and Qwen3-VL integration.

## Quick Start

```bash
# Install OpenCode
curl -fsSL https://opencode.ai/install | bash

# Copy config (global)
mkdir -p ~/.config/opencode
cp -r .opencode/* ~/.config/opencode/

# Or use per-project
cd /opt/shml-platform
opencode
```

## Configuration Files

| File | Purpose |
|------|---------|
| `config.toml` | Main config (TOML format) |
| `opencode.json` | Alternative config (JSON format) |
| `agents/shml.md` | Custom SHML Platform agent |

## Model Configuration

### Coding Model (Nemotron-3)

```toml
[providers.local-coding]
type = "openai"
baseURL = "http://localhost:8010/v1"

[[providers.local-coding.models]]
id = "nemotron-coding"
name = "Nemotron-3-Nano-30B-A3B (Local)"
maxTokens = 32768
contextWindow = 131072
```

**Endpoint:** http://localhost:8010/v1  
**Requires:** `docker compose up -d` in `inference/nemotron/`

### Vision Model (Qwen3-VL)

```toml
[providers.local-vision]
type = "openai"
baseURL = "http://localhost:8000/api/llm/v1"

[[providers.local-vision.models]]
id = "qwen3-vl"
name = "Qwen3-VL-8B (Vision)"
supportsAttachments = true
```

**Endpoint:** http://localhost:8000/api/llm/v1  
**Requires:** Qwen3-VL service running (RTX 2070)

## MCP Tools

OpenCode connects to agent-service MCP tools:

```toml
[mcp.shml-platform]
type = "http"
url = "http://localhost:8000/mcp"
timeout = 120000
```

**Available Tools:**
- `training_status` - Ray job info, metrics
- `gpu_status` - VRAM usage, processes
- `mlflow_query` - Experiment lookup
- `vision_analyze` - Image analysis (Qwen3-VL)

## Usage

### Start OpenCode

```bash
cd /opt/shml-platform
opencode
```

### Example Prompts

```
"use shml-platform to check training status"
"use shml-platform to get GPU memory usage"
"use shml-platform vision_analyze on screenshot.png"
"@explore find all YOLOv8 training scripts"
"@general explain the Phase 5 augmentation strategy"
```

### Keybindings

| Key | Action |
|-----|--------|
| Tab | Switch Build/Plan agents |
| Ctrl+x h | Help dialog |
| Ctrl+x n | New session |
| Ctrl+x u | Undo (reverts files!) |
| @ | Fuzzy file search |
| ! | Shell command |

### Slash Commands

| Command | Description |
|---------|-------------|
| /help | Show commands |
| /sessions | Switch sessions |
| /undo | Undo last message + file changes |
| /compact | Summarize session |

## Headless/Remote Usage

```bash
# Start server
tmux new -s opencode
opencode serve --port 4096 --hostname 0.0.0.0

# Connect from another terminal
opencode run --attach http://localhost:4096 "check training status"
```

## SDK Usage (Node.js)

```bash
npm install @opencode-ai/sdk
```

```typescript
import { createOpencodeClient } from "@opencode-ai/sdk"

const client = createOpencodeClient({ baseUrl: "http://localhost:4096" })

const session = await client.session.create({
  body: { title: "Training check" }
})

const result = await client.session.prompt({
  path: { id: session.id },
  body: {
    parts: [{
      type: "text",
      text: "use shml-platform to check training status"
    }]
  }
})

console.log(result)
```

## Troubleshooting

### "Connection refused" to http://localhost:8010

Nemotron service not running:
```bash
cd inference/nemotron
docker compose up -d
```

### "Connection refused" to http://localhost:8000/mcp

Agent-service not running:
```bash
cd inference/agent-service
docker compose up -d
```

### MCP tools not available

Check agent-service logs:
```bash
docker logs agent-service -f
```

### GPU memory errors

Check if training is active:
```bash
nvidia-smi
```

If training active, use vision_analyze only (not vision_then_code).

## References

- OpenCode Docs: https://opencode.ai/docs
- MCP Integration: https://opencode.ai/docs/mcp
- SDK: https://www.npmjs.com/package/@opencode-ai/sdk
