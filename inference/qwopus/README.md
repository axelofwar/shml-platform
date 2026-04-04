# Nemotron-3-Nano-30B-A3B Coding Model

NVIDIA's Nemotron-3-Nano-30B-A3B via llama.cpp GGUF quantization.

## Quick Start

```bash
# Download model (one-time, ~22GB)
huggingface-cli download unsloth/Nemotron-3-Nano-30B-A3B-GGUF \
    --include "*UD-Q4_K_XL*" \
    --local-dir ../../data/models/nemotron-3/

# Start service
docker compose up -d

# Test inference
curl http://localhost:8010/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwopus-coding",
    "messages": [{"role": "user", "content": "Write a Python hello world"}],
    "temperature": 0.6
  }'

# Check health
curl http://localhost:8010/health
```

## Model Specs

| Property | Value |
|----------|-------|
| **Total Parameters** | 30B (3.5B active - MoE) |
| **Architecture** | Mamba2-MoE Hybrid |
| **Quantization** | Q4_K_XL (~22GB VRAM) |
| **Context Window** | 32K (input), 128K effective |
| **SWE-Bench** | 38.8% (vs Qwen2.5-Coder 25%) |
| **LiveCodeBench** | 68.3% |
| **AIME25** | 89.1% (reasoning) |

## GPU Strategy

**Architecture (December 2025):**
- **RTX 3090 Ti (cuda:0)**: Nemotron-3-Nano-30B-A3B - **PRIMARY CODING MODEL**
  - Replaces Qwen2.5-Coder-32B (95% vs 90% Claude Sonnet quality)
  - Yields to Ray training when needed
  - 22GB VRAM usage
- **RTX 2070 (cuda:1)**: Qwen2.5-Coder-3B - **FALLBACK** + Agentic Services
  - 6GB VRAM for fallback coding model
  - Can dynamically load Qwen3-VL for vision tasks
  - Available for other inference services during agentic workflows

Before training on RTX 3090 Ti:
```bash
../../inference/scripts/yield_to_training.sh
```

## OpenAI-Compatible API

The llama-server provides OpenAI-compatible endpoints:

- `/v1/chat/completions` - Chat interface
- `/v1/completions` - Text completion
- `/v1/models` - List models
- `/health` - Health check

## Integration

### OpenCode

See `.opencode/config.toml`:
```toml
[providers.local-coding]
type = "openai"
baseURL = "http://localhost:8010/v1"
```

### Agent Service

Update `inference/coding-model/app/model_manager_simple.py`:
```python
CODING_MODEL_ENDPOINT = "http://qwopus-coding:8010/v1"
```

## Performance

- **Latency**: ~50-100ms first token (Q4_K_XL on RTX 3090)
- **Throughput**: ~30-50 tokens/sec
- **Memory**: 22GB VRAM (loaded), 24GB available

## References

- Unsloth Docs: https://docs.unsloth.ai/models/nemotron-3
- HuggingFace GGUF: https://huggingface.co/unsloth/Nemotron-3-Nano-30B-A3B-GGUF
- llama.cpp: https://github.com/ggerganov/llama.cpp
