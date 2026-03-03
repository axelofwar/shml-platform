# SOTA Best Practices Research Summary

> Compiled from research links provided for SHML Platform native architecture migration

<!-- ═══════════════════════════════════════════════════════════════════════════
     NAVIGATION INDEX - Jump to sections with Ctrl+F + keyword
     ═══════════════════════════════════════════════════════════════════════════

     [NAV:CUTILE]       → §1 NVIDIA CUDA Tile - Low priority, Tensor Core optimization
     [NAV:AG-UI]        → §2 AG-UI Protocol - HIGH priority, real-time agent comms
     [NAV:PUFFER]       → §3 Puffer.ai - Low priority, RL library
     [NAV:UNSLOTH]      → §4 Unsloth 500K - CRITICAL, memory optimization for training
     [NAV:API-DESIGN]   → §5 Good API Design - HIGH priority, idempotency & rate limits
     [NAV:PRETRAIN]     → §6 PretrainZero - Medium, active learning pretraining
     [NAV:TOOLORCH]     → §7 ToolOrchestra - HIGH priority, orchestration patterns
     [NAV:PRIORITY]     → Implementation Priority Matrix
     [NAV:CHECKLIST]    → Architecture Integration Checklist

     KEY CONFIGS FOR OUR HARDWARE:
     • RTX 3090 Ti: 24GB (dedicated to training OR primary model)
     • RTX 2070: 8GB (dedicated to fallback model)
     • System RAM: 64GB for CPU offload
     • Max context training: Start 32K, scale up

     CROSS-REFERENCES:
     • archived_approaches/DYNAMIC_MPS_DESIGN.md → MPS approach (abandoned)
     • TRAINING_LIBRARY_INTEGRATION.md → SHML training library
     • app/request_router.py → Implements AG-UI events & routing
     • app/training_coordinator.py → Implements Unsloth configs

═══════════════════════════════════════════════════════════════════════════ -->

---

<!-- [NAV:CUTILE] -->
## 1. NVIDIA CUDA Tile - GPU Programming Model

**Source**: NVIDIA Developer Blog - cuTile

### Key Concepts
- **Tile-based GPU programming**: New abstraction for GPU kernel development
- **cuTile Python**: High-level Python API for tiled kernel development on Tensor Cores
- **Tensor Core optimization**: Modern approach to maximize GPU compute efficiency

### Applicability to Our Platform
- **Relevant for**: Training workloads using Tensor Cores on RTX 3090 Ti
- **Implementation**: Consider for custom training kernels when standard PyTorch/DeepSpeed isn't optimal
- **Priority**: Low - framework-level optimization (PyTorch/DeepSpeed handle this)

---

<!-- [NAV:AG-UI] -->
## 2. AG-UI Protocol & CopilotKit - Agent-User Interaction

**Source**: CopilotKit AG-UI Documentation

### Key Concepts
- **Agent-User Interaction Protocol (AG-UI)**: Open standard for real-time agent-frontend communication
- **~16 event types** for structured agent communication
- **Transport**: SSE (Server-Sent Events) or WebSocket
- **Complements MCP and A2A**: Not a replacement but an addition

### Event Types Include:
- `TEXT_MESSAGE_START/CONTENT/END`
- `TOOL_CALL_START/ARGS/END`
- `STATE_SNAPSHOT/DELTA`
- `RUN_STARTED/FINISHED/ERROR`

### Applicability to Our Platform
- **Highly Relevant for**: Chat UI, Jupyter notebooks, admin dashboards
- **Implementation Priority**: HIGH - adopt for all agent interactions
- **Benefits**:
  - Real-time streaming of agent thoughts/actions
  - Generative UI support
  - Human-in-the-loop confirmations
  - Progress tracking for long-running jobs

### Recommended Implementation
```python
# Example AG-UI event flow for training job
{
  "type": "RUN_STARTED",
  "runId": "training-job-123"
}
{
  "type": "STATE_DELTA",
  "delta": {"epoch": 1, "loss": 0.45, "gpu_util": 0.92}
}
{
  "type": "TOOL_CALL_START",
  "toolCallId": "checkpoint-001",
  "toolName": "save_checkpoint"
}
```

---

<!-- [NAV:PUFFER] -->
## 3. Puffer.ai - Reinforcement Learning Library

**Source**: Puffer.ai Documentation

### Key Concepts
- Fast RL training library
- Optimized for sample efficiency

### Applicability to Our Platform
- **Relevance**: Low for current scope (inference/ML training focus, not RL)
- **Future consideration**: If we add RL-based agent training

---

<!-- [NAV:UNSLOTH] -->
## 4. Unsloth 500K Context - Memory Optimization ⭐

**Source**: Unsloth AI Blog

### Key Techniques (CRITICAL for our training setup)

#### 4.1 Chunked Cross-Entropy Loss
- **60% VRAM reduction** for loss computation
- Auto-adjusts chunk size based on available VRAM
- **Implementation**: `model.loss_function = "chunked"`

#### 4.2 Gradient Checkpointing with CPU Offload
- Offloads activations to CPU RAM during backprop
- **Only 0.1% overhead** vs standard GPU-only checkpointing
- **Critical for**: Dual-GPU FSDP training with 64GB RAM

#### 4.3 Tiled MLP
- **2x context length for only 1.3x time cost**
- Enables 500K+ context window training

### Applicability to Our Platform
- **CRITICAL for**: Training jobs on RTX 3090 Ti (24GB) + RTX 2070 (8GB)
- **Implementation Priority**: HIGH

### Recommended Configuration
```python
# For FSDP training on our hardware
training_config = {
    "gradient_checkpointing": True,
    "gradient_checkpointing_offload": True,  # CPU offload
    "chunked_loss": True,
    "chunked_loss_num_chunks": "auto",  # Auto-adjust to VRAM
    "tiled_mlp": True,
    "max_context": 32768,  # Start conservative
    "cpu_offload_params": True,  # For 7B+ models
}

# Memory budget (our hardware - dedicated GPU allocation)
# 3090 Ti: 24GB for training (full VRAM available)
# 2070: 8GB for fallback inference (separate GPU)
# System RAM: 64GB for offload
```

---

<!-- [NAV:API-DESIGN] -->
## 5. Good API Design Principles ⭐

**Source**: PostHog Blog - "How to design a good API"

### Key Principles

#### 5.1 Idempotency Keys
- **All mutating operations** should accept idempotency keys
- Prevents duplicate operations on retry
- Store key → response mapping with TTL

```python
# Implementation pattern
POST /api/training/jobs
X-Idempotency-Key: job-abc123-user456

# Server stores: idempotency_key -> {job_id, created_at, response}
# Returns cached response on duplicate key within TTL
```

#### 5.2 Rate Limiting with Proper Headers
```http
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1672531200
Retry-After: 30
```

#### 5.3 Cursor-Based Pagination
- **Avoid offset pagination** for large datasets
- Use opaque cursors (encoded timestamp + id)

```json
{
  "data": [...],
  "pagination": {
    "next_cursor": "eyJ0IjoxNjcyNTMxMjAwLCJpZCI6MTIzfQ==",
    "has_more": true
  }
}
```

#### 5.4 API Versioning Philosophy
- **"Never break userspace"** - Linux philosophy
- Version only when absolutely necessary
- Use header-based versioning over URL versioning

### Applicability to Our Platform
- **Apply to**: All REST APIs (MLflow proxy, Ray API, Job Queue API)
- **Implementation Priority**: HIGH for new APIs

### Recommended Patterns for Our APIs
```yaml
# Training Job API
POST /api/v1/training/jobs
Headers:
  X-Idempotency-Key: required for POST/PUT
  X-RateLimit-Tier: developer|elevated|admin

# Inference API  
POST /api/v1/inference/completions
Headers:
  X-Request-ID: correlation tracking
  X-Priority: normal|high (admin only)

# Response headers (all endpoints)
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 57
X-RateLimit-Reset: 1704067200
X-Request-ID: echo back for tracing
```

---

<!-- [NAV:PRETRAIN] -->
## 6. PretrainZero - Reinforcement Active Pretraining

**Source**: arXiv:2512.03442v1

### Key Concepts
- **Active learning in RL pretraining**: Model learns to identify informative content
- **Min-max bilevel RL**: Mask generator vs mask predictor adversarial training
- **Self-supervised on Wikipedia**: No labeled data required

### Key Results
- Qwen3-4B-Base: +8.43 MMLU-Pro, +5.96 SuperGPQA, +10.60 math avg
- Works on base models without SFT cold-start

### Applicability to Our Platform
- **Relevance**: Medium - if we do model pretraining/continued pretraining
- **Not applicable for**: Fine-tuning or inference workloads
- **Future consideration**: For training custom base models

---

<!-- [NAV:TOOLORCH] -->
## 7. ToolOrchestra - Efficient Model & Tool Orchestration ⭐⭐

**Source**: arXiv:2511.21689v1 (NVIDIA)

### Key Concepts

#### 7.1 Small Orchestrator Pattern
- **8B model orchestrating larger models** (GPT-4, Claude, etc.)
- Achieves 37.1% on HLE, **outperforming GPT-4o (35.1%)** at 2.5x lower cost
- **Key insight**: Small models can effectively coordinate larger tools

#### 7.2 Multi-Objective Reward Design
```python
reward = {
    "outcome": binary_accuracy,      # Did it solve the task?
    "efficiency": -cost - latency,   # Minimize compute
    "preference": user_tool_weights  # Respect user preferences
}
```

#### 7.3 Tool Calling Architecture
- Unified JSON interface for all tools (APIs, models, interpreters)
- Model descriptions generated from task trajectories
- Heterogeneous pricing/availability during training

### Critical Insights for Our Platform

1. **Self-Enhancement Bias**: Models prefer their own variants (GPT-4 calls GPT-4-mini 98% of time)
2. **RL Training Required**: Prompting alone creates biased tool selection
3. **Diverse Tool Configs**: Training with varied tool availability improves generalization

### Applicability to Our Platform
- **HIGHLY RELEVANT for**: Our tiered GPU access system
- **Implementation Priority**: HIGH

### Recommended Architecture
```yaml
# Orchestrator Design for SHML Platform
orchestrator:
  model: "local-8b-finetuned"  # Or Qwen3-8B
  tools:
    - name: "vllm_inference_primary"
      cost: low
      gpu_required: gpu_0  # 3090 Ti (when not training)

    - name: "vllm_inference_fallback"
      cost: low
      gpu_required: gpu_1  # 2070 (always available)

    - name: "training_job_small"
      cost: medium  
      gpu_required: gpu_0  # 3090 Ti (exclusive during training)

    - name: "training_job_distributed"
      cost: high
      gpu_required: both_gpus
      admin_only: true

    - name: "external_api_openai"
      cost: per_token
      fallback: true

# Decision Logic
routing_policy:
  - if: simple_inference → vllm_inference
  - if: complex_reasoning → external_api (if user allows)
  - if: training_request → check_queue → training_job_*
  - if: admin_request → bypass_cost_optimization
```

---

<!-- [NAV:PRIORITY] -->
## Implementation Priority Matrix

| Practice | Priority | Component | Effort |
|----------|----------|-----------|--------|
| AG-UI Protocol | HIGH | Chat UI, Dashboards | Medium |
| Chunked Loss | HIGH | Training Service | Low |
| CPU Offload | HIGH | Training Service | Low |
| Idempotency Keys | HIGH | All APIs | Medium |
| Rate Limiting Headers | HIGH | Traefik/APIs | Low |
| Cursor Pagination | MEDIUM | MLflow, Logs | Medium |
| ToolOrchestra Pattern | HIGH | Job Router | High |
| Tiled MLP | MEDIUM | Training Service | Low |

---

<!-- [NAV:CHECKLIST] -->
## Architecture Integration Checklist

### API Layer
- [ ] Add idempotency middleware to Traefik
- [ ] Implement rate limit headers in all services
- [ ] Use cursor-based pagination for list endpoints
- [ ] Add X-Request-ID correlation

### Training Service
- [ ] Enable chunked cross-entropy loss
- [ ] Configure gradient checkpointing with CPU offload
- [ ] Set up memory budget based on GPU tier
- [ ] Implement tiled MLP for long-context training

### Agent/Orchestration Layer
- [ ] Implement AG-UI protocol for streaming
- [ ] Build orchestrator routing logic
- [ ] Add cost-aware tool selection
- [ ] Implement preference-aware rewards

### Monitoring
- [ ] Track tool selection distribution
- [ ] Monitor cost per request
- [ ] Alert on bias patterns (excessive external API calls)

---

## References

1. NVIDIA cuTile: https://developer.nvidia.com/blog/cuda-tile/
2. CopilotKit AG-UI: https://docs.copilotkit.ai/ag-ui
3. Unsloth 500K: https://unsloth.ai/blog/500k
4. PostHog API Design: https://posthog.com/blog/good-api-design
5. PretrainZero: https://arxiv.org/abs/2512.03442
6. ToolOrchestra: https://arxiv.org/abs/2511.21689

---

*Document generated: 2024*
*Platform: SHML-Platform*
*Version: 1.0*
