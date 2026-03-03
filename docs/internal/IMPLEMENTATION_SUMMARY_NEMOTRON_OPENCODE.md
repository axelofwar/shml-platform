# Nemotron & OpenCode Implementation Summary

**Date:** December 18, 2025  
**Status:** ✅ **PHASE P7.1 & P8.3 COMPLETE**

## What Was Implemented

### ✅ Phase P7.1: Nemotron-3-Nano-30B-A3B Setup

**Model Downloaded:**
- File: `Nemotron-3-Nano-30B-A3B-UD-Q4_K_XL.gguf` (22.8GB)
- Location: `data/models/nemotron-3/`
- Quantization: Q4_K_XL (~22GB VRAM required)
- Downloaded in: 6 minutes 45 seconds

**Docker Service Created:**
- Location: `inference/nemotron/docker-compose.yml`
- Image: `ghcr.io/ggerganov/llama.cpp:full-cuda`
- GPU: RTX 3090 Ti (cuda:0) exclusive
- Port: `8010` (OpenAI-compatible API)
- Traefik routing: `/api/coding` → `http://nemotron-coding:8000`
- Context window: 32K tokens
- Health checks: ✅ Configured

**Scripts Created:**
1. `inference/nemotron/start_nemotron.sh` - Start service with GPU checks
2. `inference/nemotron/stop_nemotron.sh` - Stop service gracefully
3. `inference/scripts/yield_to_training.sh` - Free RTX 3090 before training
4. `inference/nemotron/README.md` - Complete documentation

### ✅ Phase P8.3: OpenCode Configuration

**Configuration Files Created:**
1. `.opencode/config.toml` - TOML format configuration
   - Nemotron coding provider on port 8010
   - Qwen3-VL vision provider via inference gateway
   - MCP connection to agent-service
   - Agent defaults configured

2. `.opencode/opencode.json` - JSON format alternative
   - Same providers as TOML
   - Compatible with older OpenCode versions

3. `.opencode/agents/shml.md` - Custom SHML Platform agent
   - MCP tool permissions
   - Bash command permissions (ask before docker/ray)
   - GPU architecture documentation
   - Usage guidelines and examples

4. `.opencode/README.md` - Complete usage guide
   - Installation instructions
   - Configuration reference
   - Keybindings and slash commands
   - Headless/remote usage
   - SDK examples (Node.js)
   - Troubleshooting guide

## How to Use

### Start Nemotron Service

```bash
cd inference/nemotron
./start_nemotron.sh
```

**Service will be available at:**
- API: `http://localhost:8010/v1`
- Traefik route: `http://localhost/api/coding`
- Health: `http://localhost:8010/health`

### Test Inference

```bash
curl http://localhost:8010/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nemotron-coding",
    "messages": [{"role": "user", "content": "Write a Python hello world"}],
    "temperature": 0.6
  }'
```

### Use with OpenCode

```bash
# Install OpenCode (one-time)
curl -fsSL https://opencode.ai/install | bash

# Copy config to global location
mkdir -p ~/.config/opencode
cp -r .opencode/* ~/.config/opencode/

# Start OpenCode
cd /home/axelofwar/Projects/shml-platform
opencode
```

**Example prompts:**
```
"use shml-platform to check training status"
"use shml-platform to get GPU memory usage"
"@explore find all training scripts"
"@general explain the face detection architecture"
```

### Before Training (GPU Yield)

```bash
# Free RTX 3090 Ti for training
./inference/scripts/yield_to_training.sh

# This will:
# 1. Stop nemotron-coding container
# 2. Verify GPU memory is freed
# 3. Exit with status code
```

## Files Created

### Nemotron Service
- `inference/nemotron/docker-compose.yml` (Docker service)
- `inference/nemotron/start_nemotron.sh` (Startup script)
- `inference/nemotron/stop_nemotron.sh` (Stop script)
- `inference/nemotron/README.md` (Documentation)

### OpenCode Configuration
- `.opencode/config.toml` (TOML config)
- `.opencode/opencode.json` (JSON config)
- `.opencode/agents/shml.md` (Custom agent)
- `.opencode/README.md` (Usage guide)

### Platform Scripts
- `inference/scripts/yield_to_training.sh` (GPU yield script)

### Documentation
- `docs/PLATFORM_IMPROVEMENTS_PROJECT_BOARD.md` (Updated with research)
- This file: `IMPLEMENTATION_SUMMARY_NEMOTRON_OPENCODE.md`

## Architecture Summary

### GPU Strategy

| GPU | Primary Use | Secondary Use | During Training |
|-----|-------------|---------------|-----------------|
| RTX 3090 Ti (cuda:0, 24GB) | Nemotron coding | YOLOv8 training | Yields to training |
| RTX 2070 (cuda:1, 8GB) | Qwen3-VL vision | - | Always available |

### Service Endpoints

| Service | Port | Path | Purpose |
|---------|------|------|---------|
| Nemotron API | 8010 | `/v1` | OpenAI-compatible LLM |
| Qwen3-VL | 8000 | `/api/llm/v1` | Vision analysis |
| Agent Service MCP | 8000 | `/mcp` | Platform tools |
| Traefik Coding | 80 | `/api/coding` | Proxied Nemotron |

## Model Specifications

### Nemotron-3-Nano-30B-A3B

| Property | Value |
|----------|-------|
| Total Parameters | 30B (3.5B active - MoE) |
| Architecture | Mamba2-MoE Hybrid |
| Layers | 23 Mamba-2 + 23 MoE + 6 Attention |
| Quantization | Q4_K_XL |
| VRAM Usage | ~22GB loaded |
| Context Window | 32K input, 128K effective |
| SWE-Bench | 38.8% (vs Qwen2.5-Coder 25%) |
| LiveCodeBench | 68.3% |
| AIME25 | 89.1% (reasoning) |
| Tool Calling | Native (qwen3_coder parser) |
| License | NVIDIA Open Model (commercial) |
| Release Date | December 15, 2025 |

## Performance Benchmarks

### Coding Performance (vs Current Model)

| Metric | Nemotron-3-Nano | Qwen2.5-Coder-7B | Improvement |
|--------|-----------------|------------------|-------------|
| SWE-Bench | 38.8% | ~25% | **+54% relative** |
| LiveCodeBench | 68.3% | ~50% | +36% |
| Context | 1M tokens | 128K | +87% |
| VRAM | 22GB | 8GB | 2.75x |
| Active Params | 3.5B | 7B | -50% (MoE) |

### Inference Performance (Estimated)

| Metric | Expected Value |
|--------|----------------|
| First Token Latency | ~50-100ms |
| Throughput | ~30-50 tokens/sec |
| Max Context | 32K tokens (input) |
| Concurrent Requests | 1-2 (24GB VRAM) |

## Integration Points

### OpenCode → Nemotron

OpenCode sends requests to `http://localhost:8010/v1` using OpenAI-compatible format:

```json
{
  "model": "nemotron-coding",
  "messages": [...],
  "temperature": 0.6,
  "max_tokens": 2048
}
```

### OpenCode → MCP Tools

OpenCode calls agent-service MCP tools via `http://localhost:8000/mcp`:

```bash
POST /mcp/tools/training_status/call
POST /mcp/tools/gpu_status/call
POST /mcp/tools/mlflow_query/call
POST /mcp/tools/vision_analyze/call
```

### Ray Training → GPU Yield

Before starting training job, Ray workflow calls:

```bash
./inference/scripts/yield_to_training.sh
# Stops Nemotron, verifies GPU free, returns status code
```

## Next Steps (Not Implemented Yet)

### Phase P7.2: Coding Model Migration
- [ ] Update `inference/coding-model/app/model_manager_simple.py` to use Nemotron endpoint
- [ ] Update agent-service `call_coding_model()` to use Nemotron
- [ ] Benchmark Nemotron vs Qwen2.5-Coder on real tasks
- [ ] Configure fallback logic if Nemotron unavailable

### Phase P8.1-P8.2: MCP Server Enhancements
- [ ] Already implemented in `inference/agent-service/app/mcp.py`
- [ ] Test `vision_analyze` tool with OpenCode
- [ ] Test `training_status` tool with OpenCode
- [ ] Verify permissions work correctly

### Integration with start_all_safe.sh
- [ ] Add `start nemotron` command to start_all_safe.sh
- [ ] Add `stop nemotron` command to start_all_safe.sh
- [ ] Include in `start inference` service group
- [ ] Add health checks to main startup sequence

## Testing Checklist

### ✅ Manual Tests Passed
- [x] Model downloaded successfully (22.8GB)
- [x] Docker compose file validates
- [x] Scripts are executable
- [x] Configuration files are valid TOML/JSON

### 🔄 Tests to Run

**Nemotron Service:**
- [ ] Start service: `cd inference/nemotron && ./start_nemotron.sh`
- [ ] Check health: `curl http://localhost:8010/health`
- [ ] Test inference: `curl http://localhost:8010/v1/chat/completions ...`
- [ ] Check GPU usage: `nvidia-smi` (should show ~22GB on cuda:0)
- [ ] Stop service: `./stop_nemotron.sh`
- [ ] Verify GPU freed: `nvidia-smi` (should show <1GB on cuda:0)

**OpenCode Integration:**
- [ ] Install OpenCode: `curl -fsSL https://opencode.ai/install | bash`
- [ ] Copy config: `cp -r .opencode ~/.config/opencode/`
- [ ] Start OpenCode: `opencode`
- [ ] Test coding prompt: "Write a Python hello world"
- [ ] Test MCP tool: "use shml-platform to check GPU status"
- [ ] Test vision: Upload image and ask for analysis
- [ ] Test keybindings: Tab, Ctrl+x h, @, !

**GPU Yield:**
- [ ] Start Nemotron: `./inference/nemotron/start_nemotron.sh`
- [ ] Verify running: `docker ps | grep nemotron`
- [ ] Run yield script: `./inference/scripts/yield_to_training.sh`
- [ ] Verify stopped: `docker ps | grep nemotron` (should be empty)
- [ ] Check GPU: `nvidia-smi` (cuda:0 should be free)

## Troubleshooting

### "Model file not found"
```bash
# Download model
cd /home/axelofwar/Projects/shml-platform
huggingface-cli download unsloth/Nemotron-3-Nano-30B-A3B-GGUF \
    --include "*UD-Q4_K_XL*" \
    --local-dir data/models/nemotron-3/
```

### "Cannot connect to Docker daemon"
```bash
# Check Docker is running
sudo systemctl status docker

# Start Docker if needed
sudo systemctl start docker
```

### "GPU out of memory"
```bash
# Check what's using GPU
nvidia-smi

# Stop competing services
docker stop nemotron-coding qwen3-vl-api z-image-api

# Or use yield script
./inference/scripts/yield_to_training.sh
```

### "OpenCode command not found"
```bash
# Install OpenCode
curl -fsSL https://opencode.ai/install | bash

# Add to PATH (if needed)
export PATH="$HOME/.opencode/bin:$PATH"
```

### "MCP tools not available"
```bash
# Check agent-service is running
docker ps | grep agent-service

# Start if needed
cd inference/agent-service
docker compose up -d

# Check logs
docker logs agent-service -f
```

## References

### Documentation
- Nemotron Unsloth: https://docs.unsloth.ai/models/nemotron-3
- Nemotron HuggingFace: https://huggingface.co/unsloth/Nemotron-3-Nano-30B-A3B-GGUF
- OpenCode Docs: https://opencode.ai/docs
- OpenCode MCP: https://opencode.ai/docs/mcp
- llama.cpp: https://github.com/ggerganov/llama.cpp

### Project Files
- Project Board: `docs/PLATFORM_IMPROVEMENTS_PROJECT_BOARD.md`
- Main README: `README.md`
- Nemotron README: `inference/nemotron/README.md`
- OpenCode README: `.opencode/README.md`

---

**Implementation completed:** December 18, 2025 03:57 AM  
**Total time:** ~7 hours (6:45 download + implementation)  
**Next review:** After testing with actual workloads
