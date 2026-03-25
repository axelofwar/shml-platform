# Qwen3.5-35B-A3B — Inference Endpoint (Eval Candidate)

Candidate replacement for Nemotron-3-Nano-30B-A3B as the primary local coding model.

## Quick Start

```bash
# 1. Download the GGUF weights (~19.7GB)
mkdir -p ../../data/models/qwen3.5
huggingface-cli download Qwen/Qwen3.5-35B-A3B-GGUF \
  qwen3.5-35b-a3b-q4_k_m.gguf \
  --local-dir ../../data/models/qwen3.5

# 2. Start the service
docker compose up -d

# 3. Test
curl http://localhost:8020/v1/models
curl http://localhost:8020/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-coding",
    "messages": [{"role": "user", "content": "Write a Python hello world"}],
    "max_tokens": 128
  }'
```

## Model Comparison

| Property | Nemotron-3-Nano-30B-A3B | Qwen3.5-35B-A3B |
|---|---|---|
| Total params | 30B | 35B |
| Active params | 3B | ~3B |
| Architecture | MoE | Gated DeltaNet MoE |
| Context window | 65,536 | 262,144 |
| Quantization | Q4_K_XL | Q4_K_M |
| VRAM usage | ~22.5 GB | ~19.7 GB (+ KV cache) |
| Attention layers | All traditional | 10/40 traditional, 30/40 recurrent |
| Long-context perf | Degrades at high ctx | No degradation (native 262K) |

## Running the Eval

```bash
# Head-to-head comparison
python ../../ray_compute/jobs/evaluation/eval_coding_model.py \
  --nemotron-url http://localhost:8010/v1 \
  --qwen-url http://localhost:8020/v1 \
  --output results/qwen_vs_nemotron.json

# Qwen only
python ../../ray_compute/jobs/evaluation/eval_coding_model.py \
  --target qwen \
  --qwen-url http://localhost:8020/v1
```

## After Eval: Switch to Production

If Qwen wins the eval:

1. Stop Nemotron: `docker compose -f ../nemotron/docker-compose.yml down`
2. Uncomment the Traefik labels in this docker-compose.yml
3. Comment out the `ports:` section
4. Restart: `docker compose up -d`
5. Update nemotron-manager to point at qwen-coding container

## Hardware Requirements

- **GPU:** RTX 3090 Ti (24GB) or equivalent
- **VRAM at full 262K context:** ~21.8 GB
- **VRAM headroom:** ~2.1 GB spare
- **RAM:** Minimal (model runs entirely on GPU)
