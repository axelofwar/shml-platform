# Dynamic MPS Control Architecture

<!-- ═══════════════════════════════════════════════════════════════════════════
     NAVIGATION INDEX - Jump to sections with Ctrl+F + keyword
     ═══════════════════════════════════════════════════════════════════════════

     [NAV:OVERVIEW]     → Design goals, training priority principles
     [NAV:HARDWARE]     → Why concurrent GPU sharing isn't feasible (memory math)
     [NAV:ARCH]         → System architecture diagram
     [NAV:ROUTER]       → Request Router - routing rules, complexity detection
     [NAV:COORD]        → Training Coordinator - state machine, checkpoints
     [NAV:MPS]          → MPS Controller - daemon control
     [NAV:ALLOC]        → GPU Allocator - resource tracking
     [NAV:STATE]        → State machine diagram (IDLE→TRAINING→PAUSED)
     [NAV:QUEUE]        → Queue management, timeout handling
     [NAV:CONFIG]       → Environment variables, API config
     [NAV:API]          → API endpoints (/training/*, /routing/*, /queue/*)
     [NAV:PHASES]       → Implementation phases checklist
     [NAV:RISK]         → Risk mitigation table
     [NAV:MONITOR]      → Prometheus metrics, alerts
     [NAV:WORKFLOW]     → Example workflows (normal, interrupt, timeout)

     KEY CONFIGS:
     • Checkpoint interval: 100 steps
     • Queue timeout: 30s → 60s
     • Checkpoint trigger: ≥3 requests
     • Idle timeout: 15 min + 5 min confirm
     • Context threshold: 8192 tokens
     • Complexity threshold: 0.6

     IMPLEMENTATION FILES:
     • app/mps_controller.py → MPS daemon control ✅ TESTED
     • app/gpu_allocator.py → GPU allocation tracking
     • app/request_router.py → Routing logic with complexity detection
     • app/training_coordinator.py → State machine & checkpointing
     • app/model_manager_simple.py → Integration target

     CROSS-REFERENCES:
     • SOTA_BEST_PRACTICES_SUMMARY.md [NAV:TOOLORCH] → Orchestration patterns
     • SOTA_BEST_PRACTICES_SUMMARY.md [NAV:UNSLOTH] → Memory optimization
     • SOTA_BEST_PRACTICES_SUMMARY.md [NAV:AG-UI] → Event protocol

═══════════════════════════════════════════════════════════════════════════ -->

<!-- [NAV:OVERVIEW] -->
## Overview

This document describes the architecture for dynamic GPU resource management that allows training jobs to have priority access while maintaining intelligent fallback inference capabilities.

## Design Goals

1. **Training Priority**: Training jobs always take precedence over inference
2. **Intelligent Routing**: Route requests to fallback unless "absolutely necessary" to use primary
3. **Primary Hidden During Training**: Primary model is NOT selectable - only auto and fallback
4. **Clean Resource Isolation**: Use checkpoint-based pausing (concurrent GPU sharing NOT feasible)
5. **User Control**: Admin can force primary with warning and re-confirmation

<!-- [NAV:HARDWARE] -->
## Hardware Analysis: Why Concurrent GPU Sharing Isn't Feasible

**Question**: Can we run 32B model at 40-50% GPU alongside training?

**Answer**: **No**, based on memory requirements:

| Component | VRAM Required |
|-----------|---------------|
| Qwen2.5-32B-AWQ (4-bit) | ~18GB |
| KV Cache (4K context) | ~1-2GB |
| CUDA overhead | ~1GB |
| **Total for inference** | **~20-22GB** |
| LoRA training (rank 16) | ~4-8GB |
| **Total for training** | **~6-12GB** |

RTX 3090 Ti has 24GB. Cannot fit both simultaneously without severe degradation.

**Solution**: Pause-based approach with checkpointing.

<!-- [NAV:ARCH] -->
## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Dynamic MPS Control Architecture                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      Request Router                                   │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │  Training Active?  ──Yes──►  Route Analysis                     │  │   │
│  │  │        │                         │                              │  │   │
│  │  │       No                    ┌────┴────┐                         │  │   │
│  │  │        │                    │         │                         │  │   │
│  │  │        ▼               Simple    Complex                        │  │   │
│  │  │  Auto-Select OK            │         │                          │  │   │
│  │  │  (normal routing)          │         ▼                          │  │   │
│  │  │                            │    Queue for Primary               │  │   │
│  │  │                            │    OR                              │  │   │
│  │  │                            │    Checkpoint Training             │  │   │
│  │  │                            │         │                          │  │   │
│  │  │                            ▼         ▼                          │  │   │
│  │  │                       Fallback   Primary (paused training)      │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Training Coordinator                               │   │
│  │                                                                       │   │
│  │  • Manages training job lifecycle                                     │   │
│  │  • Controls MPS daemon (start/stop)                                   │   │
│  │  • Handles checkpoint save/resume                                     │   │
│  │  • Queue management for primary requests                              │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                    ┌───────────────┴───────────────┐                        │
│                    ▼                               ▼                        │
│  ┌─────────────────────────────┐   ┌─────────────────────────────┐         │
│  │      MPS Controller         │   │     GPU Allocator            │         │
│  │                             │   │                              │         │
│  │  • nvidia-cuda-mps-control  │   │  • GPU 0: Primary/Training   │         │
│  │  • Start/stop MPS daemon    │   │  • GPU 1: Fallback (always)  │         │
│  │  • Thread percentage config │   │  • Resource tracking         │         │
│  └─────────────────────────────┘   └─────────────────────────────┘         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Components

<!-- [NAV:ROUTER] -->
### 1. Request Router

Analyzes incoming requests and routes them appropriately.

**Model Availability During Training:**
- **Primary**: HIDDEN (not selectable in UI)
- **Auto**: Selectable, goes through rigorous filtering
- **Fallback**: Selectable, always available

**UI Display When Auto Selects Primary:**
```json
{
  "model": "primary",
  "queued": true,
  "queue_position": 2,
  "estimated_wait_seconds": 30,
  "display": "primary (queued #2, ~30s wait)"
}
```

**Rigorous Filtering for Auto-Selection:**

| Stage | Check | If True | If False |
|-------|-------|---------|----------|
| 1 | RAG has relevant context (score > 0.75)? | → Fallback | Continue |
| 2 | History has relevant answer? | → Fallback | Continue |
| 3 | Prompt can be compressed to fit? | → Fallback | Continue |
| 4 | Simple request (complexity < 0.4, < 3 skills)? | → Fallback | Continue |
| 5 | Context > 8K (fallback limit)? | → Queue Primary | Check complexity |
| 6 | Multi-skill task (≥ 3 tools detected)? | → Queue Primary | Check tokens |
| 7 | High complexity (≥ 0.6)? | → Queue Primary | → Fallback |

**Skill/Tool Detection:**
```python
agentic_skills = [
    "file_read", "file_write", "file_search", "grep_search",
    "run_terminal", "git_operations", "database_query",
    "web_search", "code_analysis", "refactoring",
    "test_generation", "documentation", "deployment"
]
# If request requires >= 3 skills -> prefer primary
```

**User Role Considerations:**
- **Viewer**: API only, no model selection
- **Developer**: Standard routing, no force option
- **Elevated**: Slight priority boost (+0.2 complexity score)
- **Admin**: Can force primary with warning + re-auth during training

**Routing Rules During Training:**

| Criterion | Threshold | Action |
|-----------|-----------|--------|
| Context length | > 8192 tokens | Queue for Primary |
| Multi-skill task | ≥ 3 skills detected | Queue for Primary |
| High complexity | score ≥ 0.6 | Queue for Primary |
| RAG available | score > 0.75 | Fallback |
| History relevant | True | Fallback |
| Can compress | True | Fallback |
| Simple request | complexity < 0.4 | Fallback |
| Admin force | True | Queue + Warning + Re-auth |

<!-- [NAV:COORD] -->
### 2. Training Coordinator

Orchestrates the interplay between training and inference.

**Key Features:**
- Checkpoint validation before interrupting training
- Idle timeout with user confirmation
- Auto-resume after 15 min idle + 5 min no response

```python
class TrainingCoordinator:
    """Coordinates training jobs with inference workloads."""

    config = {
        "checkpoint_interval": 100,           # Steps between checkpoints
        "max_checkpoints_to_keep": 3,         # Keep last 3 (~1.5-3GB total)
        "force_checkpoint_threshold": 100,    # Force checkpoint if >100 steps
        "queue_timeout_seconds": 30,          # 30s request timeout
        "checkpoint_trigger_threshold": 3,    # Pause if >= 3 requests waiting
        "idle_timeout_seconds": 900,          # 15 min -> prompt user
        "confirmation_timeout_seconds": 300,  # 5 min -> auto-resume
    }

    states = {
        "idle": "No training active, full inference available",
        "training": "Training active, fallback-only inference",
        "paused": "Training paused, primary inference serving queue",
        "checkpointing": "Saving checkpoint before pause"
    }

    def start_training(self, job_config):
        """Start a training job with MPS disabled on GPU 0."""
        # 1. Signal primary model to yield
        # 2. Wait for model unload confirmation
        # 3. Stop MPS daemon on GPU 0
        # 4. Start training job with exclusive GPU access

    def pause_training(self, reason="primary_request"):
        """Pause training to serve primary model request."""
        # CRITICAL: Validate checkpoint before interrupting
        # 1. Check if >100 steps since last checkpoint
        # 2. If yes, force save checkpoint first
        # 3. Then signal training to pause
        # 4. Release GPU, start MPS, load primary

    def resume_training(self):
        """Resume training after primary requests are served."""
        # 1. Unload primary model
        # 2. Stop MPS daemon
        # 3. Resume training from checkpoint

    async def monitor_idle_timeout(self):
        """Monitor for idle and auto-resume."""
        # After 15 min idle: prompt user
        # After 5 min no response: auto-resume
```

<!-- [NAV:MPS] -->
### 3. MPS Controller

Low-level control of NVIDIA MPS daemon.

```python
class MPSController:
    """Controls NVIDIA Multi-Process Service daemon."""

    def __init__(self, gpu_id: int = 0):
        self.gpu_id = gpu_id
        self.pipe_dir = f"/tmp/nvidia-mps-{gpu_id}"
        self.log_dir = f"/var/log/nvidia-mps-{gpu_id}"

    async def start(self):
        """Start MPS daemon for this GPU."""
        # export CUDA_VISIBLE_DEVICES=0
        # export CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps-0
        # nvidia-cuda-mps-control -d

    async def stop(self):
        """Stop MPS daemon, releasing GPU for exclusive access."""
        # echo quit | nvidia-cuda-mps-control

    async def is_running(self) -> bool:
        """Check if MPS daemon is active."""

    async def set_default_thread_percentage(self, pct: int):
        """Set default thread percentage for new clients."""
        # echo "set_default_active_thread_percentage {pct}" | nvidia-cuda-mps-control
```

<!-- [NAV:ALLOC] -->
### 4. GPU Allocator

Tracks GPU resource allocation state.

```python
class GPUAllocator:
    """Tracks GPU allocation across training and inference."""

    allocation_states = {
        0: {  # GPU 0 (RTX 3090 Ti - 24GB)
            "current": "mps_inference",  # or "training", "idle"
            "process": "vllm-primary",   # or "ray-training"
            "memory_allocated": "22GB",
            "mps_enabled": True
        },
        1: {  # GPU 1 (RTX 2070 - 8GB)
            "current": "mps_inference",  # always inference
            "process": "vllm-fallback",
            "memory_allocated": "5.6GB",
            "mps_enabled": True
        }
    }

    def can_start_training(self, gpu_id: int) -> bool:
        """Check if GPU can be allocated to training."""

    def allocate_to_training(self, gpu_id: int, job_id: str):
        """Reserve GPU for training job."""

    def release_from_training(self, gpu_id: int):
        """Release GPU back to inference pool."""
```

<!-- [NAV:STATE] -->
## State Machine

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
                    ▼                                         │
            ┌───────────────┐                                 │
            │     IDLE      │◄────────────────────────────────┤
            │               │                                 │
            │ • MPS enabled │        training_complete        │
            │ • Primary up  │                                 │
            │ • Auto OK     │                                 │
            └───────┬───────┘                                 │
                    │                                         │
           training_start                                     │
                    │                                         │
                    ▼                                         │
            ┌───────────────┐                                 │
            │   TRAINING    │─────────training_complete───────┘
            │               │
            │ • MPS off     │
            │ • Primary off │◄──────────resume─────────┐
            │ • Auto=fallbk │                          │
            └───────┬───────┘                          │
                    │                                  │
           primary_request_queued                      │
           (complex/explicit)                          │
                    │                                  │
                    ▼                                  │
            ┌───────────────┐                          │
            │ CHECKPOINTING │                          │
            │               │                          │
            │ • Save state  │                          │
            │ • ~30-60s     │                          │
            └───────┬───────┘                          │
                    │                                  │
           checkpoint_saved                            │
                    │                                  │
                    ▼                                  │
            ┌───────────────┐                          │
            │    PAUSED     │                          │
            │               │                          │
            │ • MPS enabled │                          │
            │ • Primary up  │                          │
            │ • Queue drain │──────queue_empty─────────┘
            └───────────────┘
```

<!-- [NAV:QUEUE] -->
## Queue Management

### Primary Request Queue

```python
@dataclass
class QueuedRequest:
    request_id: str
    request: ChatCompletionRequest
    queued_at: datetime
    timeout: timedelta = timedelta(seconds=60)
    complexity_score: float  # 0-1, used for prioritization

class PrimaryRequestQueue:
    """Manages queued requests waiting for primary model."""

    max_queue_size: int = 10
    max_wait_time: timedelta = timedelta(seconds=60)

    # Trigger checkpoint if queue reaches this threshold
    checkpoint_trigger_threshold: int = 3

    async def enqueue(self, request: ChatCompletionRequest) -> str:
        """Add request to queue, return queue position."""

    async def should_trigger_checkpoint(self) -> bool:
        """Check if queue state warrants pausing training."""
        return (
            len(self.queue) >= self.checkpoint_trigger_threshold or
            any(r.is_high_priority for r in self.queue)
        )
```

### Timeout Handling

If a queued request exceeds timeout:
1. First attempt: Route to fallback with quality warning
2. If fallback can't handle (e.g., context too long): Return 503 with retry-after header

<!-- [NAV:CONFIG] -->
## Configuration

### Environment Variables

```bash
# Training Coordinator
TRAINING_CHECKPOINT_INTERVAL=100        # Steps between checkpoints
TRAINING_CHECKPOINT_ON_PAUSE=true       # Force checkpoint before pause
TRAINING_MAX_PAUSE_DURATION=300         # Max seconds paused for inference

# Request Router
ROUTING_CONTEXT_THRESHOLD=4096          # Tokens before preferring primary
ROUTING_MAX_TOKENS_THRESHOLD=2048       # Max tokens before preferring primary
ROUTING_COMPLEXITY_KEYWORDS="refactor,migrate,restructure,convert entire"
ROUTING_AUTO_DURING_TRAINING=fallback   # Where auto routes during training

# Queue Management
QUEUE_MAX_SIZE=10                       # Max pending primary requests
QUEUE_TIMEOUT_SECONDS=60                # Request timeout
QUEUE_CHECKPOINT_TRIGGER=3              # Requests before triggering pause

# MPS Control
MPS_GPU_ID=0                            # GPU to manage
MPS_PIPE_DIRECTORY=/tmp/nvidia-mps-0
MPS_LOG_DIRECTORY=/var/log/nvidia-mps-0
```

### API Configuration Endpoint

```yaml
# /training/config (GET/POST)
training_config:
  checkpoint_interval: 100
  checkpoint_on_pause: true
  max_pause_duration: 300

routing_config:
  context_threshold: 4096
  max_tokens_threshold: 2048
  complexity_keywords:
    - refactor
    - migrate
    - restructure
    - convert entire
  auto_during_training: fallback

queue_config:
  max_size: 10
  timeout_seconds: 60
  checkpoint_trigger: 3
```

<!-- [NAV:API] -->
## API Endpoints

### Training Control

```
POST /training/start
  body: { job_id, script_path, gpus, priority, checkpoint_interval }
  response: { status, estimated_start_time, queue_position }

POST /training/stop
  body: { job_id, save_checkpoint }
  response: { status, checkpoint_path }

POST /training/pause
  body: { job_id, reason }
  response: { status, checkpoint_path, resume_token }

POST /training/resume
  body: { resume_token }
  response: { status, resumed_from_step }

GET /training/status
  response: {
    state,
    current_job,
    progress,
    queued_requests,
    gpu_allocation,
    mps_status
  }
```

### Routing Control

```
GET /routing/config
  response: { current_config, training_active, effective_routing }

POST /routing/config
  body: { context_threshold, auto_during_training, ... }
  response: { updated_config }

GET /routing/analyze
  body: { request }
  response: {
    recommended_model,
    reason,
    complexity_score,
    will_queue
  }
```

### Queue Management

```
GET /queue/status
  response: {
    length,
    oldest_request_age,
    estimated_wait_time,
    will_trigger_checkpoint
  }

DELETE /queue/{request_id}
  response: { status, fallback_attempted }
```

<!-- [NAV:PHASES] -->
## Implementation Phases

### Phase 1: Core Infrastructure (This PR)
- [ ] MPS Controller class
- [ ] GPU Allocator class  
- [ ] Training Coordinator state machine
- [ ] Basic request router with token counting

### Phase 2: Queue & Checkpointing
- [ ] Primary request queue
- [ ] Checkpoint triggering logic
- [ ] Training pause/resume via SHML library integration

### Phase 3: API & Integration
- [ ] API endpoints
- [ ] Integration with existing model_manager_simple.py
- [ ] Integration with Traefik health checks

### Phase 4: Testing & Refinement
- [ ] End-to-end training + inference test
- [ ] Queue timeout testing
- [ ] Checkpoint corruption recovery
- [ ] Performance benchmarking

<!-- [NAV:RISK] -->
## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Checkpoint corruption | Keep last N checkpoints, validate on resume |
| MPS daemon stuck | Watchdog process to restart if unresponsive |
| Queue overflow | Hard limit + timeout with fallback routing |
| Primary model slow to load | Pre-warm model in background when queue grows |
| Training interrupted mid-batch | Flush batch to disk before checkpoint |

<!-- [NAV:MONITOR] -->
## Monitoring

### Metrics to Track

```
# Prometheus metrics
training_state{state="idle|training|paused|checkpointing"}
training_pause_total{reason="primary_request|timeout|manual"}
training_pause_duration_seconds
queue_length
queue_oldest_request_seconds
request_routing_total{destination="primary|fallback",reason="..."}
mps_state{gpu="0",state="running|stopped"}
checkpoint_save_duration_seconds
checkpoint_resume_duration_seconds
```

### Alerts

- Queue length > 5 for > 30s
- Training paused > 5 minutes
- MPS restart required
- Checkpoint save failed

<!-- [NAV:WORKFLOW] -->
## Example Workflows

### Workflow 1: Normal Training (No Primary Requests)

```
1. User: POST /training/start {job_id: "pii-pro-001"}
2. System: Signal primary to yield → wait for unload
3. System: Stop MPS daemon on GPU 0
4. System: Start Ray job with GPU 0 exclusive
5. System: Route all auto/inference requests to fallback
6. Training runs to completion
7. System: POST /training/stop → restart MPS → reload primary
```

### Workflow 2: Primary Request During Training

```
1. Training active on GPU 0
2. User: Chat request with 5K context (needs primary)
3. Router: Enqueue request (complexity_score=0.8)
4. Queue: 3 requests waiting → trigger checkpoint
5. Coordinator: Signal training to checkpoint
6. Training: Save checkpoint (step 5432) → release GPU
7. Coordinator: Start MPS → load primary
8. Router: Drain queue (3 requests)
9. Queue: Empty + 30s timeout → no new requests
10. Coordinator: Unload primary → stop MPS → resume training (step 5432)
```

### Workflow 3: Request Timeout

```
1. Training active, user request queued
2. 60 seconds pass, request still queued
3. Router: Check if fallback can handle
4. If yes: Route to fallback with warning header
5. If no: Return 503 with Retry-After: 120
```

## Next Steps

1. Review and approve this design
2. Implement Phase 1 (Core Infrastructure)
3. Write unit tests for state machine
4. Integrate with existing training detector
5. Test with pii-pro training job
