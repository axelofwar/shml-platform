# Qwopus — Qwen3.5-27B Coding Model

Qwen3.5-27B Q4_K_M via llama.cpp GGUF quantization.

## Quick Start

```bash
# Download model (one-time, ~16.5GB)
huggingface-cli download Qwen/Qwen3.5-27B-GGUF \
    --include "*Q4_K_M*" \
    --local-dir ../../data/models/qwopus/

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
| **Total Parameters** | 27B |
| **Architecture** | Transformer (Qwen3.5) |
| **Quantization** | Q4_K_M (~16.5GB VRAM) |
| **Context Window** | 65536 tokens |
| **GPU** | RTX 3090 Ti (cuda:0, 24GB) |

## GPU Strategy

**Architecture:**
- **RTX 3090 Ti (cuda:0)**: Qwen3.5-27B Q4_K_M - **PRIMARY CODING MODEL**
  - 16.5GB VRAM for weights, ~7.5GB headroom for 65K context KV cache
  - Yields to Ray training when needed via coding-manager
- **RTX 2070 (cuda:1)**: watchdog-llm (Qwen3-4B Q4_K_M) — always-on watchdog triage

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

Update via `CODING_MODEL_URL` env var or Docker network DNS `qwopus-coding:8000`.

## Performance

- **Latency**: ~50-100ms first token (Q4_K_M on RTX 3090)
- **Throughput**: ~30-50 tokens/sec
- **Memory**: ~16.5GB VRAM weights

## References

- HuggingFace GGUF: https://huggingface.co/Qwen/Qwen3.5-27B-GGUF
- llama.cpp: https://github.com/ggerganov/llama.cpp
