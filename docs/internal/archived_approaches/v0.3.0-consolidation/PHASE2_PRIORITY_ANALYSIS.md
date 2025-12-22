# Phase 2 Implementation Priority Analysis
## Agent Service vs Multi-Model Orchestration vs New Skills

**Date:** December 7, 2025  
**Current State:** Phase 1 Complete (Agent Service), Vision Model Blocked  
**Decision Point:** What to implement next?

---

## Current Status Summary

### ✅ Phase 1 Complete: Agent Service (ACE Pattern)

**Completed (~6 hours):**
- ACE context system (playbook with semantic retrieval)
- G-R-C workflow (LangGraph StateGraph)
- 4 composable skills (GitHub, Sandbox, Ray, WebSearch)
- WebSocket streaming for real-time updates
- Session diary and reflection engine
- REST + WebSocket APIs
- PostgreSQL persistence
- Integrated with start_all_safe.sh

**Status:** Production-ready with 1 known limitation (SandboxSkill needs Docker socket - elevated permissions required)

**See:** `docs/internal/AGENT_STATUS_AND_NEXT_STEPS.md`

### ⚠️ Vision Model Issue (Blocking Multi-Model Orchestration)

**Problem:** Qwen3-VL model loaded but **not processing images**

**Location:** `inference/qwen3-vl/app/model.py` lines 130-140
```python
# CURRENT CODE - Only processes TEXT, not images!
inputs = self.processor(
    text=formatted,
    return_tensors="pt",
    padding=True,
).to(self.model.device)
# Missing: images parameter
```

**Impact:**
- Screenshots are ignored
- No VL → Coding handoff possible
- Multimodal agent workflows blocked

**See:** `docs/internal/MULTI_MODEL_ORCHESTRATION_PLAN.md`

---

## Option Analysis

### Option 1: Fix Vision Model + Multi-Model Orchestration

**Estimated Time:** 11-15 hours total

#### Phase 1: Vision Model Fix (2-4h)
- Update schemas.py for multimodal messages
- Implement image processing in model.py
- Test with real screenshots

#### Phase 2: Model Swap (2-3h)
- Replace Qwen3-VL-8B → Qwen2-VL-2B (~2GB)
- Upgrade fallback 3B → 7B (~4.5GB)
- Fits on RTX 2070 (6.8GB available)

#### Phase 3: Gateway Orchestration (4-6h)
- Content analyzer (detect images)
- VL → Coding handoff protocol
- ImageAnalysis schema
- Auto-routing logic

#### Phase 4: Integration Testing (2-3h)
- Test screenshot → VL → Coding flow
- Test with Chat UI (paste screenshots)
- Verify training doesn't block

**Value Delivered:**
- ✅ Screenshot understanding (errors, UI, code)
- ✅ Multimodal agent workflows
- ✅ Better quality fallback (7B vs 3B)
- ✅ Always-available inference (RTX 2070)

**Risks:**
- High complexity (3 moving parts)
- GPU memory tuning required
- May discover more issues

**Dependencies:**
- Blocks: Multimodal agent features
- Enables: ImageProcessingSkill, advanced agents

---

### Option 2: Implement Tier 1 Skills (Platform Integration)

**Estimated Time:** 11-15 hours total

#### MLflowSkill (4-6h)
**Operations:**
- create_experiment, log_metrics, log_artifacts
- register_model, transition_stage
- search_experiments, get_run

**Value:**
- Automate 80% of ML workflow
- Agent can track experiments
- Self-documenting training runs

**Example Workflow:**
```python
# User: "Train YOLOv8 and log to MLflow"
# Agent orchestrates:
exp = await MLflowSkill.execute("create_experiment", {
    "name": "yolov8-faces-v2"
})
job = await RayJobSkill.execute("submit_job", {
    "script": "train.py",
    "env_vars": {"MLFLOW_EXPERIMENT_ID": exp["id"]}
})
# Monitor, register, document
```

#### TraefikSkill (3-4h)
**Operations:**
- list_routes, get_service_status
- health_check, get_metrics
- debug_connectivity

**Value:**
- Self-healing (detect unhealthy services)
- Troubleshoot routing issues
- Monitor traffic patterns

**Example:**
```python
# User: "Why is MLflow not responding?"
# Agent debugs:
routes = await TraefikSkill.execute("list_routes", {})
status = await DockerSkill.execute("get_logs", {
    "container": "shml-mlflow-server"
})
# Analyzes logs, suggests fix
```

#### DockerSkill (4-5h)
**Operations:**
- list_containers, get_logs, get_stats
- inspect_network, health_check

**Value:**
- Platform self-awareness
- Resource monitoring
- Automated debugging

**Example:**
```python
# User: "Check platform health"
# Agent checks:
for service in ["mlflow", "ray", "agent"]:
    stats = await DockerSkill.execute("get_stats", {
        "container": f"shml-{service}"
    })
    # Reports CPU, memory, health
```

**Risks:**
- Docker socket requires privileged access
- Same issue as SandboxSkill

---

### Option 3: Hybrid Approach (Skill + Vision Fix)

**Estimated Time:** 8-10 hours

#### Week 1: MLflowSkill (4-6h)
- Highest ROI skill
- Enables ML workflow automation
- No privilege requirements

#### Week 2: Vision Model Fix Only (2-4h)
- Fix Qwen-VL image processing
- Skip model swap (keep 8B + 3B)
- Skip gateway orchestration

**Value:**
- ML workflow automation (immediate)
- Basic screenshot processing (partial)

**Trade-offs:**
- Multimodal not fully functional
- Manual VL → Coding routing
- Lower quality fallback (3B)

---

### Option 4: Focus on Agent Enhancements

**Estimated Time:** 6-8 hours

#### Fix SandboxSkill Docker Socket (2h)
- Add Docker socket mount to docker-compose.yml
- Test code execution end-to-end
- Document security implications

#### Implement Checkpointing (2-3h)
- Custom AgentPlaybook serialization
- Enable MemorySaver checkpointer
- Test workflow resumption

#### WebSocket Testing (1-2h)
- Test real-time stage streaming
- Verify human-in-loop approval
- Load test multiple concurrent sessions

#### Performance Optimization (1-2h)
- Measure G-R-C cycle time
- Optimize playbook retrieval
- Cache embeddings

**Value:**
- Agent fully functional (no limitations)
- Production-ready performance
- Better user experience

---

## Recommendation Matrix

| Option | Time | Value | Risk | Dependencies |
|--------|------|-------|------|--------------|
| **1. Vision + Orchestration** | 11-15h | ⭐⭐⭐ | High | Blocks: Multimodal |
| **2. Tier 1 Skills** | 11-15h | ⭐⭐⭐⭐ | Medium | Blocks: None |
| **3. Hybrid (MLflow + Vision)** | 8-10h | ⭐⭐⭐ | Medium | Partial multimodal |
| **4. Agent Enhancements** | 6-8h | ⭐⭐ | Low | Completes Phase 1 |

---

## Decision Framework

### If Priority is USER VALUE:
**→ Choose Option 2: Tier 1 Skills**

**Rationale:**
- MLflowSkill = 80% of ML workflow automation
- Immediate productivity gain
- No blocking issues
- Agent can orchestrate MLflow + Ray end-to-end

**Example User Benefit:**
```
Before: 30 steps to train model (create experiment, submit job, monitor, log, register)
After: 1 command to agent: "Train YOLOv8 on dataset X"
```

### If Priority is MULTIMODAL:
**→ Choose Option 1: Vision + Orchestration**

**Rationale:**
- Enables screenshot understanding
- Unlocks multimodal agent workflows
- Better quality fallback model (7B)
- Foundation for future vision features

**Blocked Until Complete:**
- Screenshot paste in Chat UI
- ImageProcessingSkill
- Visual debugging workflows

### If Priority is STABILITY:
**→ Choose Option 4: Agent Enhancements**

**Rationale:**
- Fix SandboxSkill (most requested feature)
- Enable checkpointing (workflow resumption)
- Production performance optimization
- Complete Phase 1 fully

### If Priority is BALANCED:
**→ Choose Option 3: Hybrid**

**Rationale:**
- MLflowSkill for immediate value
- Vision fix for basic multimodal
- Shorter timeline (8-10h vs 11-15h)
- Skip complex orchestration (defer to later)

---

## Recommended Path: Option 2 + Vision Fix Later

### Week 1-2: Tier 1 Skills (11-15h)

**Day 1-2: MLflowSkill (4-6h)**
- Implement 7 operations (create_experiment, log_metrics, etc.)
- Test with real MLflow server
- Document integration patterns

**Day 3: TraefikSkill (3-4h)**
- Implement 5 operations (list_routes, health_check, etc.)
- Test routing debugging
- Document troubleshooting workflows

**Day 4-5: DockerSkill (4-5h)**
- Implement 6 operations (list_containers, get_logs, etc.)
- Handle Docker socket (privileged or read-only)
- Document security model

**Deliverable:**
- 3 new platform-aware skills
- Multi-skill workflows tested
- User can orchestrate entire ML pipeline via agent

### Week 3: Vision Model Fix (2-4h)

**Day 1: Fix Qwen-VL (2-4h)**
- Update model.py to process images
- Test with screenshots
- Document image processing

**Defer to later:**
- Model swap (8B → 2B, 3B → 7B)
- Gateway orchestration
- Auto-routing

**Deliverable:**
- Basic screenshot processing works
- Foundation for multimodal later

### Week 4: Agent Enhancements (6-8h)

**Day 1: SandboxSkill Fix (2h)**
- Add Docker socket mount
- Test code execution
- Document security

**Day 2: Checkpointing (2-3h)**
- Custom serialization
- Enable MemorySaver
- Test resumption

**Day 3: WebSocket + Performance (2-3h)**
- Test streaming
- Optimize performance
- Load testing

**Deliverable:**
- Agent fully production-ready
- No known limitations

---

## Timeline to Production-Ready

| Week | Focus | Hours | Status |
|------|-------|-------|--------|
| **Week 0** | Phase 1: Core Agent | 6h | ✅ Complete |
| **Week 1-2** | Tier 1 Skills (MLflow, Traefik, Docker) | 11-15h | 📋 Recommended |
| **Week 3** | Vision Model Fix | 2-4h | 📋 Planned |
| **Week 4** | Agent Enhancements | 6-8h | 📋 Planned |
| **Total** | | 25-33h | ~4 weeks part-time |

**Production Ready After Week 4:**
- ✅ Agent Service with 7 skills (4 existing + 3 new)
- ✅ ML workflow automation (train → log → register → deploy)
- ✅ Platform self-healing (detect and fix issues)
- ✅ Basic multimodal (screenshots)
- ✅ Full stability (no limitations)

---

## Immediate Next Steps

### This Week (Week 1):

**Monday-Tuesday: MLflowSkill (6h)**
```bash
# 1. Create skill file
vim inference/agent-service/app/skills.py
# Add MLflowSkill class

# 2. Test with MLflow server
python test_mlflow_skill.py

# 3. Update SKILL_REGISTRY
# 4. Restart agent service
./start_all_safe.sh restart agent

# 5. Test end-to-end workflow
curl -X POST http://localhost/api/agent/v1/agent/execute \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Create MLflow experiment named test-experiment",
    "category": "ml-workflow"
  }'
```

**Wednesday: TraefikSkill (4h)**
```bash
# Similar process
# Test with Traefik API
curl http://localhost:8090/api/http/routers
```

**Thursday-Friday: DockerSkill (5h)**
```bash
# Similar process
# Test with Docker API
docker ps
```

### Next Week (Week 2):

**Monday-Tuesday: Vision Model Fix (4h)**
- Update schemas.py
- Implement image processing
- Test with screenshots

**Wednesday-Thursday: SandboxSkill Fix (2h)**
- Add Docker socket
- Test code execution

**Friday: Checkpointing (3h)**
- Custom serialization
- Enable MemorySaver

---

## Success Metrics

### Week 1-2 Success (Tier 1 Skills):
- [ ] MLflowSkill: 7 operations working
- [ ] TraefikSkill: 5 operations working
- [ ] DockerSkill: 6 operations working
- [ ] Agent can execute multi-skill workflow (train → log → register → document)
- [ ] All 3 skills tested with real services
- [ ] Documentation updated

### Week 3 Success (Vision Fix):
- [ ] Qwen-VL processes images correctly
- [ ] Screenshots extracted and analyzed
- [ ] Basic multimodal chat works
- [ ] Foundation for future orchestration

### Week 4 Success (Enhancements):
- [ ] SandboxSkill executes code successfully
- [ ] Checkpointing works (workflow resumption)
- [ ] WebSocket streaming tested
- [ ] Performance optimized (< 5s per G-R-C cycle)
- [ ] Agent fully production-ready

---

## Alternative: Fast Track to Multimodal

**If multimodal is critical, pivot to Option 1:**

### Week 1: Vision Model Fix (2-4h) + Model Swap (2-3h)
- Fix Qwen-VL image processing
- Swap to Qwen2-VL-2B + Qwen2.5-Coder-7B
- Test on RTX 2070

### Week 2: Gateway Orchestration (4-6h)
- Content analyzer
- VL → Coding handoff
- ImageAnalysis schema

### Week 3: Integration Testing (2-3h) + Chat UI (2-3h)
- Test end-to-end flow
- Enable screenshot paste in Chat UI
- Verify with users

### Week 4: Tier 1 Skills (Start MLflowSkill)
- Begin platform automation

**Trade-off:** Delays ML workflow automation by 3 weeks

---

## Final Recommendation

### Recommended: Option 2 (Tier 1 Skills First)

**Rationale:**
1. **Immediate User Value**: ML workflow automation = 80% productivity gain
2. **No Blockers**: All skills can be implemented now
3. **Synergy**: Skills enhance agent capabilities immediately
4. **Stable Foundation**: Build on completed Phase 1
5. **Vision Later**: Multimodal is nice-to-have, not critical path

**User Impact:**
```
Week 0: Agent can generate/reflect/curate (but limited platform knowledge)
Week 2: Agent can orchestrate entire ML pipeline (train → log → deploy)
Week 3: Agent can debug platform issues (self-healing)
Week 4: Agent can understand screenshots (multimodal)
Week 5: Agent fully production-ready (no limitations)
```

**Decision Point:** Start MLflowSkill Monday?

---

**Prepared by:** AI Assistant  
**Date:** December 7, 2025  
**Status:** ✅ Comprehensive Priority Analysis
**Recommendation:** Implement Tier 1 Skills (MLflow, Traefik, Docker) → Vision Fix → Agent Enhancements
