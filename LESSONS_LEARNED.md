# Lessons Learned

Patterns, gotchas, optimizations, and applied research learnings from building and
operating the SHML Platform. Updated as we discover things worth keeping.

---

## Autonomous Agent Patterns — claw-code + free-code Audit (2025-06)

### Full Audit Summary (43 Patterns Across Two Forks)

**Sources audited:**
- **claw-code** (`instructkr/claw-code`) — Rust port; 9 modules; 21 patterns (T1–T21)
- **free-code** (`paoloanzn/free-code`) — Leaked production TypeScript (2026-03-31); 10 source files; 22 patterns (22–43); Bun + React/Ink + Zod v4 + MCP/LSP

**Sprint 1 — Implemented (commit `fdad720a3`):**

| Pattern | File | Change | Expected Gain |
|---------|------|---------|---------------|
| T1 | `nemotron/docker-compose.yml` | `--reasoning-format auto` + perf flags | +25% Tier-2 tool-call success |
| P26 | `skills.py` | Sort skill pool by `__name__` | ~40-70% KV cache hit → first-token latency |
| P22/P23 | `config.py` | `THINKING_MODE`, `MAX_THINKING_TOKENS`, `ULTRATHINK_BUDGET_TOKENS`, `MAX_SESSION_COST_USD`, `MAX_LOOP_ITERATIONS` | Adaptive thinking + budget guardrails |
| P37 | `agent.py` | Ultrathink regex → 32K budget; auto → 10K default | 4× reasoning depth on hard problems |
| P38 | `agent_loop.py` | `consecutive_denials` + `AWAITING_HUMAN` gate at 3 | Eliminates infinite loops on repeated MR rejections |
| P31 | `agent_loop.py` | Verification nudge: warn when ≥3 files planned, no test files | Catches coverage gaps earlier |

**Key gotchas from the audit:**
- `--reasoning-budget 0` in llama-server KILLS chain-of-thought entirely — never set to 0
- Sorted tool pool = stable system prompt prefix = KV cache hits. One `.sort()` = ~50% latency reduction
- `ultrathink` is a keyword detected in the user prompt (`re.IGNORECASE`) — no API param, just a signal
- One-shot agents (`Explore`, `Plan` in free-code) skip agentId/SendMessage overhead (~135 tokens saved per call)
- Hook exit code 2 = blocking error; first-line `{"async":true}` = background execution (free-code pattern)
- Workspace trust gate: interactive mode requires dialog acceptance for ALL hooks (security: prevents RCE from untrusted workspace)

**Sprint 2 priorities (not yet implemented):**
- P36: MEMORY.md two-tier memory (cross-session context, ~30-50% re-learning reduction)
- P28/P33: Parallel file I/O + multi-agent file locking with `fcntl`
- P34: Context-aware token budgets (bump to 40K when `plan.files_to_touch > 5`)
- P41: Lifecycle hook bus (25+ event types from free-code `hooks.ts`)
- TurboQuant: pending llama.cpp merge — track arXiv:2504.19874 + llama.cpp PR feed

### TurboQuant Initiative — Status

- **Paper:** arXiv:2504.19874 — expanding to full model weight compression (confirmed by @Mayhem4Markets)
- **Impact:** Qwen3.5-27B fp16 (54GB) → ~9GB effective; 6× VRAM savings
- **Platform effect:** Would upgrade T1 router from 8B INT4 → 27B TurboQuant at same VRAM cost → +20-25% correct first-attempt rate
- **Status:** Pending llama.cpp merge — **do not implement yet**, monitor PR feed

---

## Research Findings & Platform Applications

### TurboQuant / QJL / PolarQuant — KV Cache Compression
**Source:** Google DeepMind blog + arXiv:2504.19874 (ICLR 2026)
**Date:** 2025-05

**What it is:**
A family of three data-oblivious, zero-overhead online quantization algorithms for
reducing KV cache memory with near-zero accuracy loss:
- **TurboQuant** — random Hadamard rotation + Beta-distribution-aware scalar quantizer; asymptotically optimal distortion
- **QJL** — 1-bit residual cleanup on top of any base quantizer; zero computation overhead
- **PolarQuant** — zero-overhead polar coordinate representation for key vectors

**Key numbers:**
- 3.5 bits/channel → **quality-neutral** KV cache (essentially free compression)
- 4-bit TurboQuant → **8× attention logit speedup** on H100 vs 32-bit baseline
- Near-theoretical lower bound: differs from Shannon entropy limit by only ~2.7× constant
- No calibration dataset required; runs fully online per token

**Platform applications:**
1. **Qwen3-VL-8B-INT4 on RTX 2070 (8 GB)** — the model is already INT4-weight-quantized, but KV cache is the remaining VRAM pressure at long contexts. TurboQuant 3.5-bit KV cache compression could yield ~2–3 GB back for longer context windows (useful for multi-image conversations in the chat UI).
2. **embedding-service** — vector search indexed with TurboQuant-compressed keys could reduce FAISS/hnswlib index size by ~8× vs float32 while matching quality, enabling larger in-memory indices on the same hardware.
3. **inference-gateway attention logging** — if logged attention weights are compressed with QJL before writing to Postgres/Loki, storage costs drop without quality loss.

**How to experiment:**
```python
# Install once TurboQuant is released (arXiv authors typically release code post-acceptance)
pip install turbo-quant  # placeholder — check github.com/google-deepmind/turbo_quant
# Integration point in inference/qwen3-vl/app/model.py — pass kv_cache_bits=3.5
```

**Status:** Monitor for official code release. Applicable immediately to embedding-service FAISS indices once library exists.

---

### TurboQuant on RTX 3090 Ti (24 GB) — Inference + Training
**Date:** 2026-03

The 3090 has three active workloads with very different TurboQuant relevance:

#### Workload 1: Nemotron-3-Nano-30B-A3B inference (highest impact)

**Architecture (verified from GGUF metadata):**
Nemotron-3-Nano-30B-A3B uses the `nemotron_h_moe` architecture: 52 total layers, of which only **6 are hybrid attention layers** (at positions 5, 12, 19, 26, 33, 42 — approximately every 7–9 layers). The remaining 46 are Mamba2 SSM layers.

- **Mamba2 SSM layers (46/52)**: fixed recurrent state, O(d_model) memory — **no KV cache**
- **Hybrid attention layers (6/52)**: 2 KV heads (aggressive GQA), head_dim=128 — **produce KV cache**

Because only 6 layers with 2 KV heads contribute, the KV cache is much smaller than a pure transformer of equivalent depth.

**Exact VRAM budget at ctx=65536 on RTX 3090 Ti:**

| KV dtype | KV cache size | Remaining after weights+KV+workspace | Notes |
|----------|--------------|--------------------------------------|-------|
| f16 (default) | 384 MiB | 633 MiB | safe, but tight headroom |
| **q8_0 (applied)** | **192 MiB** | **825 MiB** | **+192 MiB vs f16 — sweet spot** |
| q4_0 | 96 MiB | 921 MiB | optional if more headroom needed |

- Model weights: 22.8 GB GGUF = ~23,347 MiB; GPU total = 24,564 MiB; headroom = 1,217 MiB
- f16 KV was **not causing OOM** (only 384 MiB at this hybrid architecture), but q8_0 adds 192 MiB of safety buffer
- Formula: `n_attn_layers × n_kv_heads × head_dim × ctx × bytes × 2` = 6 × 2 × 128 × 65536 × 2 × 2 = 384 MiB (f16)

**Change made:** `inference/nemotron/docker-compose.yml` passes `--cache-type-k q8_0 --cache-type-v q8_0`.
This saves 192 MiB VRAM — beneficial for long coding sessions with many concurrent contexts, not strictly required.

**To push further:** Change both to `q4_0` (saves 288 MiB vs f16). The TurboQuant paper validates 3.5-bit as quality-neutral; llama.cpp `q4_0` is coarser but still within that threshold.

#### Workload 2: YOLO native training (batch size was the bottleneck)

TurboQuant does **not** apply to YOLO training — YOLOv8 is a CNN with no attention / KV cache. However, the training code had a severely under-utilised 3090: `batch_size=16` with halving/quartering per phase.

**The problem with the old formula:**
```python
# Wrong: linear scaling (halves per step)
640px → 16
960px → max(16 // 2, 4) = 8       # 4× under-utilised
1280px → max(16 // 4, 2) = 4      # 16× under-utilised
```

**The correct formula — memory scales with area (imgsz²):**
```python
# Correct: area-proportional scaling (base=64 for 24GB)
640px  → 64
960px  → int(64 × (640/960)²)  = 28
1280px → int(64 × (640/1280)²) = 16
```

**Change made:** `native_trainer.py` — `batch_size` default raised from 16 → 64; `_calculate_batch_size` uses area-ratio formula. YOLOv8n activation memory at 640px with AMP is ~40–80 MB per image; at batch 64 that's ~3–5 GB activations, well within the 24 GB budget. This gives **4× more gradient signal per step** at 640px, measurably improving convergence speed and final mAP.

#### Workload 3: shl-nano SFT (future)

If shl-nano fine-tuning runs on the 3090 with a transformer model:
- **vLLM `kv_cache_dtype`**: pass `kv_cache_dtype=fp8` or `kv_cache_dtype=int8` to halve/quarter KV cache during generation phases of the training loop
- **bitsandbytes INT8 optimizer**: reduces optimizer state from 3× model size (fp32 states) to ~1.5×, freeing 5–10 GB for a 7B model
- **TurboQuant directly**: once the library is released, apply to the model's attention layers during the forward pass to free KV cache VRAM during long-context SFT examples

**Priority:** Not actionable until shl-nano SFT is scheduled. Apply `kv_cache_dtype=int8` at that point as the first experiment.

---

### PufferLib / PuffeRL — High-Performance RL Training
**Source:** puffer.ai + arXiv:2406.12905
**Date:** 2025-05

**What it is:**
- Pure-Python RL training library targeting **1M+ steps/second/core** via:
  - C-native PufferEnv format (compile with nvcc for CUDA-accelerated advantage function)
  - Zero-copy shared memory batching (single buffer, no inter-process copies)
  - Busy-wait flags instead of pipes/queues (near-zero IPC overhead)
  - Double-buffered async env workers (always collects more envs than needed, returns as ready)
- **PuffeRL** algorithm: CleanRL PPO+LSTM with custom research improvements
- **Protein** optimizer: automatic hyperparameter + reward tuning built-in
- **torchrun** distributed training: `torchrun --nproc-per-node=6 -m pufferlib.pufferl train ...`
- Gym / Gymnasium / PettingZoo 1-line compatibility wrappers

**Platform applications:**
1. **Ray compute RL jobs** — Ray task submissions for RL workloads (e.g. training agents to optimize GPU scheduling, curriculum-learning face detection, or robot sim) can use PufferLib's vectorized envs with Ray's distributed execution. The `torchrun` distributed mode maps directly onto Ray's worker pool.
2. **Face detection curriculum** (`inference/face_detection/`) — the existing frame-selection pipeline could be reformulated as a PufferLib custom env where the agent learns which detection thresholds maximize downstream recall. C-native env = negligible overhead vs current pure-Python loops.
3. **Hyperparameter search for shl-nano** — PufferLib's Protein built-in HPO replaces manual Ray Tune sweeps for shl-nano fine-tuning; especially useful for reward shaping in any RL-based text quality scorer.
4. **PufferTank Docker image** as base for Ray worker nodes that run RL jobs: includes nvcc, CUDA env, and all dependencies pre-configured (`github.com/pufferai/puffertank`).

**Integration pattern with Ray:**
```python
import ray
import pufferlib.vector as pf_vec
from pufferlib.emulation import GymnasiumPufferEnv

@ray.remote(num_gpus=0.5)
def run_puffer_worker(env_creator, num_envs: int):
    vecenv = pf_vec.make(env_creator, num_envs=num_envs, backend=pf_vec.Multiprocessing)
    # ... PuffeRL training loop
```

**Status:** Add `pufferlib` to `requirements.txt` when first RL workload is ready. PufferTank image is the cleanest Ray worker base.

---

### Cloudflare Workers for Platforms / Workers AI — Edge Routing & Inference Fallback
**Source:** Cloudflare Workers for Platforms docs, Workers AI product page
**Date:** 2025-05

**What it is:**
- **Dispatch namespaces**: run unlimited isolated user Workers under one account; each tenant's code is fully sandboxed with custom resource limits (CPU, memory, subrequests)
- **Dynamic dispatch Worker**: top-level router that inspects request headers/subdomain and `dispatch.get("tenant-id")` to the right child Worker
- **Workers AI**: 50+ open-source models (Llama-3, Mistral, FLUX, Whisper, etc.) on Cloudflare's GPU network; pay-per-inference, zero server management
- **AI Gateway**: unified proxy in front of any AI provider — adds caching, rate limiting, request retry, model fallback (OpenAI → Anthropic → Workers AI), and full observability (latency, token counts, cost tracking) with zero code changes
- **Vectorize**: vector DB co-located in Cloudflare network for semantic search near-edge
- **Durable Objects**: stateful Workers — persistent WebSocket sessions, rate-limiting counters, co-op lock state

**Platform applications:**
1. **AI Gateway as external model observability layer** — wrap any external API calls (e.g. if a user ever hits an OpenAI-compatible external endpoint as a fallback) with Cloudflare AI Gateway to get caching + cost tracking without modifying inference-gateway code.
2. **Workers for Platforms pattern for agent dispatch** — the `inference-gateway`'s request routing logic (queue, rate-limit per-user, model selection) closely mirrors Cloudflare's dynamic dispatch Worker pattern. Consider adopting the same architecture inside the local gateway for multi-tenant model dispatch.
3. **Workers AI as cold-start fallback** — when RTX 3090 Ti is occupied by training, route image gen to Workers AI FLUX model as a low-latency fallback; z-image-api's existing `yield-to-training` endpoint pairs naturally with a redirect to Workers AI's `@cf/black-forest-labs/flux-1-schnell`.
4. **Durable Objects pattern for inference-gateway session state** — replace the stateless rate-limit counters in inference-gateway with a Durable Object-style in-memory actor pattern (Python equivalent: an asyncio Lock + per-user `deque`) to avoid Redis round-trips on every request.

**Local implementation note:** For the self-hosted platform, replicate the Dispatch Namespace pattern inside `inference/router/` — a single FastAPI gateway that resolves `model_id → backend_url` from a Redis-backed registry, paralleling Cloudflare's `dispatch.get()`.

**Status:** AI Gateway pattern directly actionable in `inference/gateway/main.py`. Workers AI fallback requires Cloudflare account + secret — document in `.env.example` when implemented.

---

## CI & Test Patterns

### All Compose Stacks Validated in CI (2025-05)
**Problem:** `docker compose config -q` in the `docker-build` CI job only validated 2 of 16 compose stacks; stacks with missing env var substitutions silently passed.

**Solution:** Expanded the dummy `.env` in `.github/workflows/ci.yml` to include all 48 env vars referenced across all stacks; replaced the 2-file check with a loop over all 16 stacks using a `FAILED=1` accumulation pattern.

**Pattern:**
```bash
FAILED=0
for stack_name in infra auth logging tracing ...; do
  if ! docker compose -f deploy/compose/docker-compose.${stack_name}.yml config -q; then
    echo "FAILED: $stack_name"
    FAILED=1
  fi
done
[[ $FAILED -eq 0 ]] || exit 1
```

### Auth Compose Contract Test Pattern (2025-05)
**Problem:** The auth stack (`docker-compose.auth.yml`) is the most security-critical compose file but had no regression test preventing accidental middleware chain removal.

**Solution:** `tests/unit/test_auth_compose_contract.py` — parse the YAML and assert on specific middleware chain orderings. This catches configuration regressions at PR time without requiring any running services.

**Key gotcha:** Traefik middleware chains in Docker Compose labels are order-sensitive. Assert on exact ordering, not just presence:
```python
# For /admin: oauth2-errors MUST precede oauth2-auth MUST precede role-auth-admin
chain = get_router_middlewares(services, "fusionauth", "admin")
assert chain.index("oauth2-errors") < chain.index("oauth2-auth")
assert chain.index("oauth2-auth") < chain.index("role-auth-admin")
```

### Live FusionAuth Smoke Test Skip Pattern (2025-05)
Integration tests that depend on live services should skip gracefully when the service is unreachable rather than fail. Pattern used in `tests/integration/test_fusionauth_admin_flow.py`:
```python
def _skip_if_unreachable():
    try:
        requests.get(BASE_URL, timeout=5)
    except requests.exceptions.ConnectionError:
        pytest.skip("Platform unreachable — skipping live integration test")
```
This allows the same test file to run safely in CI (where services are up) and locally (where they may not be).

---

## GPU & Inference Patterns

### Traefik Router Priority (critical — always set to 2147483647)
**Problem:** Traefik's internal API dashboard intercepts all `/api/*` prefixed routes before application routes.
**Solution:** All inference and application routers must include `priority=2147483647` (max int32).
```yaml
- traefik.http.routers.my-router.priority=2147483647
```
Missing this label on any new service will silently route requests to the Traefik API instead of the app.

### RTX 2070 KV Cache VRAM Pressure at Long Contexts
Qwen3-VL-8B runs INT4 weights (~4.5 GB static VRAM), but the KV cache grows linearly with context length. At 4096 tokens with bf16 KV, the cache consumes an additional ~2 GB. At 8192 tokens it hits the 8 GB ceiling. **Mitigation:** Use `max_model_len=4096` until TurboQuant 3.5-bit KV compression is available, or quantize KV cache to int8 (`kv_cache_dtype=int8` in vLLM).

### GPU Yield / Training Coordination
Z-Image auto-unloads from RTX 3090 Ti after 5 min idle. For training:
```bash
curl -X POST http://localhost/api/image/yield-to-training  # explicit eviction
```
Ray training jobs should always check `training_status` MCP tool before requesting GPU allocation.

---

## Secrets & Auth Patterns

### OAuth2-Proxy Forward Auth Header Trust
Backend APIs will return 401 even after successful OAuth2-Proxy authentication unless they
explicitly read the forwarded identity headers:
```python
email = request.headers.get("X-Auth-Request-Email")  # set by oauth2-proxy
```
Set `PROXY_AUTH_ENABLED=true` in `.env` and implement the header extraction pattern in all FastAPI services that need user identity.

### FusionAuth /auth Route Must NOT Have oauth2-auth Middleware
A common misconfiguration is applying the full auth middleware chain (including `oauth2-auth`) to the `/auth` path itself, which causes an infinite redirect loop. The `/auth` router must be middleware-free or use only the rewrite middleware:
```yaml
# CORRECT: /auth path has no oauth2-auth
- traefik.http.routers.fusionauth-public.middlewares=fusionauth-headers,fusionauth-rewrite
# WRONG: causes redirect loop
- traefik.http.routers.fusionauth-public.middlewares=oauth2-auth,fusionauth-headers
```

---

## MCP & AutoResearch Patterns

### alphaXiv MCP for arXiv Literature Research
`mcp/mcp-config.json` includes `alphaxiv` server at `https://api.alphaxiv.org/mcp/v1`.
Use it in agent-service prompts to search for techniques by keyword, pull paper abstracts,
and compare method benchmarks — without leaving the agent loop.

**Effective prompts:**
- "Search alphaXiv for KV cache quantization methods from 2024–2025, summarize the top 3 by citation count"
- "Find the arXiv abstract for 2504.19874 and extract the key benchmark numbers"
- "What papers cite QJL (arXiv:2405.07987)? Are any directly applicable to 8B inference on 8GB VRAM?"

Combine with `brave-search` for blog posts and `prometheus` for current platform metrics to build full research → experiment → deploy loops inside the agent.

---

## Coding Model History

| Model | Period | Notes |
|-------|--------|-------|
| **Nemotron-3-Nano-30B-A3B** (GGUF Q4_K_XL, ~22.8GB) | 2026-03 | Evaluated as primary coding model on RTX 3090 Ti. `nemotron_h_moe` architecture: 52 layers, only 6 hybrid attention (Mamba2 SSM otherwise). KV cache very small vs pure transformers. Replaced by Qwen3.5-27B Q4_K_M for better context handling, simpler llama.cpp serving, and stronger coding benchmarks. |
| **Qwen3.5-27B Q4_K_M** (qwopus-coding, ~16.5GB) | 2026-04+ | Current primary coding model on RTX 3090 Ti (cuda:0). Served via `coding-manager` (port 8011) + llama.cpp (port 8010). OpenAI-compatible. Better tool calling than Nemotron. |

---

## Monitoring & Watchdog Patterns (2026-04)

### Two Independent Health-Monitor Paths for Inference Containers
**Problem:** After fixing `watchdog.sh` to suppress false alerts for qwopus-coding (when GPU manager has it intentionally stopped), Telegram alerts continued every 5 minutes with the exact same text.

**Root cause:** The platform has **two completely independent** health-check systems for the coding server:
1. `scripts/self-healing/watchdog.sh` → `check_llama_server()` — runs inside the watchdog container, uses Docker DNS (`http://qwopus-coding:8000/health`)
2. `inference/agent-service/app/scheduler.py` → `_job_llama_server_watchdog()` — runs inside the agent-service container on a 5-minute async scheduler

Fixing one does not fix the other. Always audit all monitoring paths when silencing alerts.

**Lesson:** Before declaring an alert "fixed," search the full repo for the exact alert text:
```bash
grep -rn "exact alert text" --include='*.py' --include='*.sh'
```

### Stale Health-Check URLs After Containerization
**Problem:** The scheduler probed `http://host-gateway:8000/health` (a Docker `extra_hosts` alias for the host bridge IP). This URL was correct when Qwen3.5 ran as a bare host process. After containerizing as `qwopus-coding`, the container has **no host port mapping** — all traffic routes via Docker DNS.

**Fix:** Change default from `http://host-gateway:8000/health` → `http://qwopus-coding:8000/health` in both:
- `scheduler.py` default constant
- `docker-compose.yml` `LLAMA_SERVER_HEALTH_URL` env var

**Lesson:** When migrating a service from host process → Docker container, grep all compose files and application code for the old hostname/port. Both the Python default AND the compose env var override must be updated.

### GPU-Manager-Aware Alert Suppression Pattern
**Problem:** The scheduler checked only Ray jobs API to decide if training was active. But the GPU manager (`http://gpu-manager:8000/health`) is the authoritative source for GPU state — it knows about training, transitioning, and intentional stops that Ray may not reflect.

**Solution applied (scheduler.py `_job_llama_server_watchdog()`):**
```
1. Probe qwopus-coding health → if 200 OK → return (no alert)
2. Query GPU manager → if training_active=true OR gpu_0_state in (training, transitioning) → return
3. Query Ray jobs API → if any RUNNING/PENDING jobs → return
4. Alert (server down in inference mode, no training active)
```

This mirrors the 3-layer check already in `watchdog.sh` (`is_gpu_managed_idle()` + `is_training_active()`).

**Lesson:** The GPU manager is the single source of truth for "is this GPU intentionally not running inference." Always check it before alerting on inference container health.

### Docker Runner Containers Stuck in "Created" State
**Problem:** `start_all_safe.sh start devtools` creates GitLab runner containers via `docker compose up -d`, but the runners stay in Docker `created` state — never transitioning to `running`. GitLab API shows them as `online=True` (stale registration), but no CI jobs process.

**Root cause:** The runners depend on GitLab health, which resolves after compose returns. The entrypoint script (`gitlab_runner_entrypoint.sh`) registers then runs — but the container never starts.

**Fix:** Added `created` state detection in `start_devtools()`:
```bash
runner_actual_status=$(docker inspect --format='{{.State.Status}}' "$runner_container" 2>/dev/null)
if [[ "$runner_actual_status" == "created" ]]; then
    docker start "$runner_container"
fi
```

**Lesson:** `docker compose up -d` does not guarantee containers reach `running` state. Always verify with `docker inspect --format='{{.State.Status}}'` and explicitly `docker start` containers stuck in `created`.

### Watchdog Container Pre-Check Pattern
**Problem:** `check_llama_server()` in `watchdog.sh` was sending Telegram alerts and creating GitLab issues when qwopus-coding was intentionally stopped by the GPU manager.

**Fix pattern (apply to any container health check):**
```bash
# 1. Container doesn't exist → skip silently
docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null || return 0
# 2. Container exited with code 0 → managed stop → skip
if [[ "$exit_code" == "0" ]]; then return 0; fi
# 3. Check GPU manager state BEFORE logging ALERT
is_gpu_managed_idle && return 0
# 4. Only now: alert
```

**Lesson:** Order matters. The GPU-managed-idle check must happen **before** the ALERT log entry, not after. Otherwise, log aggregators (Loki/Grafana) show phantom alerts that were actually suppressed downstream.

## Agent Service — ACE Workflow Patterns (2026-04)

### pgvector Column Type vs Actual DB Schema
**Problem:** `PlaybookBullet.embedding = Column(Vector(384))` in SQLAlchemy ORM, but PostgreSQL column was actually `JSONB` — the Alembic migration `001_pgvector_embedding.py` was never run.

**Symptom:** `'list' object has no attribute 'split'` in pgvector's `Vector._from_db()`.

**Root cause chain:** asyncpg auto-deserializes JSONB → Python list → pgvector's SQLAlchemy `result_processor` calls `from_text(list)` → `str.split(',')` on a list → `AttributeError`.

**Fix:** Changed column declaration to `Column(JSONB)` to match reality. Added defensive handling in `to_context_bullet()` for list/None embeddings.

**Lesson:** Always verify actual DB column types with a raw query (`SELECT column_name, data_type FROM information_schema.columns`) before trusting ORM declarations. If a migration exists but was never run, the ORM and DB will disagree silently until runtime.

### user_role Must Be in initial_state
**Problem:** The ACE generator node logged `Role 'viewer' blocked skills: ['ShellSkill', 'GitLabSkill', ...]` even though the service should have elevated permissions.

**Root cause:** `initial_state` in `main.py` never set `user_role`, so `state.get("user_role", "viewer")` always defaulted to `viewer`.

**Lesson:** When adding RBAC to a state machine, grep all `state.get("user_role"` call sites to ensure the default matches operational intent. Defensive defaults (like `"viewer"`) are great for security but must be overridden at the entry point.

### Docker env_file vs environment: Precedence
**Problem:** `TELEGRAM_BOT_TOKEN` was empty inside the container despite being set in `../../.env`.

**Root cause:** `docker-compose.yml` had both `env_file: ../../.env` AND explicit `environment: TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}`. The `environment:` section takes precedence over `env_file`, and `${TELEGRAM_BOT_TOKEN:-}` resolved to empty in the shell (var not exported).

**Fix:** Removed explicit `TELEGRAM_*` declarations from `environment:` and relied on `env_file` alone.

**Lesson:** Docker Compose `environment:` always wins over `env_file:`. If you use `env_file`, don't redeclare the same vars in `environment:` with `${VAR:-}` defaults — the default will override the env_file value.

### Volume Mounts Don't Hot-Reload Python Modules
**Problem:** Edited `agent.py` on host (via volume mount `./app:/app/app:ro`), expected the running container to use the new code — but it didn't.

**Root cause:** Python imports modules once at startup. The volume mount makes the file visible inside the container, but the Python process has already loaded the old version into memory. A container restart is required.

**Lesson:** Volume mounts for live reload only work with frameworks that have file watchers (uvicorn `--reload`, Next.js dev, etc.). For standard Python services, restart the container after edits.

### Watchdog Restart Loops During Benchmarking (April 2026)
**Problem:** Stopping `qwopus-coding` to free GPU VRAM for a Carnice-27B benchmark caused the watchdog to immediately restart qwopus — consuming all VRAM before the benchmark could load.

**Root cause:** The container had `restart: unless-stopped` and the watchdog viewed it as CRITICAL (always running). `docker stop` triggers restart policy, and the watchdog's 60s cycle also restarts it.

**Fix:** Created `scripts/self-healing/watchdog-ctl.sh` — a host-side helper:
- `watchdog-ctl pause 30m` — pause auto-remediation with auto-resume
- `watchdog-ctl resume` — manually resume
- The watchdog already had `IS_PAUSED` + control file mechanism; the script just writes to it via `docker exec`

**Lesson:** Always pause the watchdog before planned maintenance: `watchdog-ctl pause 1h`. Use `docker update --restart=no` before `docker stop` to prevent Docker's own restart policy from racing the watchdog.

### Carnice-27B Benchmark Results (April 2026)
**Setup:** Carnice-27B Q4_K_M (16GB GGUF) via `ghcr.io/ggml-org/llama.cpp:server-cuda` on RTX 3090 Ti.

**Results:**
- Throughput: ~39 tok/s (vs qwopus ~50-60 tok/s for AWQ)
- Reasoning: PASS — uses `reasoning_content` field (thinking model)
- Tool calling: Partial — produces tool-like JSON but not reliable OpenAI function calling
- Code generation: Needs `max_tokens≥2048` — model consumes tokens in reasoning, leaving `content` empty at low limits
- Long context: Successfully handled 2000+ token context windows

**Decision:** Keep qwopus-coding (Qwen3.5-27B AWQ via vLLM) as production coding LLM. Carnice is a viable backup for offline/GGUF-only scenarios.

**Lesson:** GGUF Q4 models via llama.cpp are ~30-40% slower than AWQ models via vLLM for the same parameter count. Thinking models need generous `max_tokens` to produce visible output. No prebuilt CUDA llama.cpp binary exists for Linux x86 — use the Docker image `ghcr.io/ggml-org/llama.cpp:server-cuda`.

### Host Systemd Services Invisible to Docker Watchdog (April 2026)
**Problem:** Hermes Gateway and Hermes Workspace run as systemd user services outside Docker. The watchdog (running inside a container) couldn't see or probe them.

**Fix:**
1. Added `extra_hosts: ["host.docker.internal:host-gateway"]` to `docker-compose.watchdog.yml`
2. Added `HOST_SERVICES` array in `watchdog.sh` with HTTP probes via `host.docker.internal`
3. Added `check_host_services()` with nsenter-based auto-restart (spawns privileged helper container)

**Lesson:** Docker containers can reach host services via `host.docker.internal` with `extra_hosts` in compose. For remediation, `nsenter -t 1 -m -u -i -n` into PID 1 allows running `systemctl --user restart` from inside a privileged container.
