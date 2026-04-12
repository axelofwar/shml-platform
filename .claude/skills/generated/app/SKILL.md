---
name: app
description: "Skill for the App area of shml-platform. 763 symbols across 90 files."
---

# App

763 symbols | 90 files | Cohesion: 80%

## When to Use

- Working with code in `inference/`
- Understanding how get_current_user, verify_oauth_token, track_requests work
- Modifying app-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `inference/pii-blur/app/main.py` | BlurMethod, DetectionResult, VideoJobResult, load_tracker, ensure_loaded (+46) |
| `inference/agent-service/app/main.py` | agent_websocket, send_periodic_pings, execute_agent, handle_agent_workflow, preview_routing (+27) |
| `inference/coding-model/app/request_router.py` | set_queue_length, get_available_models, get_config, RoutingResult, estimate_wait_time (+21) |
| `inference/coding-model/app/training_coordinator.py` | steps_since_checkpoint, needs_checkpoint_before_interrupt, is_expired, wait_time_seconds, pause_training (+17) |
| `inference/agent-service/app/mcp.py` | MCPServerInfo, get_server_info, get_tools, _nemoclaw_request, _create_sandbox (+17) |
| `inference/agent-service/app/code_worker.py` | _post_plan_comment, set_ready_for_review, _context_aware_max_tokens, BuildResult, _shell (+16) |
| `inference/agent-service/app/hybrid_router.py` | emit_metrics, HybridRouter, get_hybrid_router, RoutingDecision, HandoffEvent (+15) |
| `inference/coding-model/app/training_detector.py` | MultiSourceTrainingDetector, TrainingDetector, RayJobDetector, __init__, FileSignalDetector (+15) |
| `inference/agent-service/app/skill_evolution.py` | LessonCluster, _similarity, _cluster_lessons, _infer_domain, SkillEvolutionEngine (+15) |
| `inference/agent-service/app/gitlab_client.py` | get_issue, update_issue, add_comment, close_issue, _replace_status_label (+15) |

## Entry Points

Start here when exploring this area:

- **`get_current_user`** (Function) — `mlflow-server/api/main_enhanced.py:181`
- **`verify_oauth_token`** (Function) — `mlflow-server/api/main_enhanced.py:231`
- **`track_requests`** (Function) — `mlflow-server/api/main_enhanced.py:367`
- **`inc`** (Function) — `tests/unit/libs/test_training_tracking_callbacks.py:71`
- **`labels`** (Function) — `tests/unit/libs/test_training_tracking_callbacks.py:79`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `UserContext` | Class | `mlflow-server/api/main_enhanced.py` | 173 |
| `FakeMetricHandle` | Class | `tests/unit/libs/test_training_tracking_callbacks.py` | 60 |
| `RequestAnalytics` | Class | `inference/agent-service/app/analytics.py` | 132 |
| `BlurMethod` | Class | `inference/pii-blur/app/main.py` | 327 |
| `DetectionResult` | Class | `inference/pii-blur/app/main.py` | 345 |
| `VideoJobResult` | Class | `inference/pii-blur/app/main.py` | 359 |
| `AgentResponse` | Class | `inference/agent-service/app/schemas.py` | 96 |
| `HybridRouter` | Class | `inference/agent-service/app/hybrid_router.py` | 228 |
| `SessionDiary` | Class | `inference/agent-service/app/diary.py` | 21 |
| `ConversationTurn` | Class | `inference/agent-service/app/conversation_history.py` | 25 |
| `PlaybookBullet` | Class | `inference/agent-service/app/context.py` | 123 |
| `ModelSelection` | Class | `inference/agent-service/app/model_router.py` | 94 |
| `MultiModelPlan` | Class | `inference/agent-service/app/model_router.py` | 106 |
| `RoutingDecision` | Class | `inference/agent-service/app/hybrid_router.py` | 43 |
| `HandoffEvent` | Class | `inference/agent-service/app/hybrid_router.py` | 67 |
| `MPSStatus` | Class | `inference/coding-model/app/mps_controller.py` | 30 |
| `MPSController` | Class | `inference/coding-model/app/mps_controller.py` | 43 |
| `MPSManager` | Class | `inference/coding-model/app/mps_controller.py` | 421 |
| `MultimodalMessage` | Class | `inference/gateway/app/vision_schemas.py` | 29 |
| `ImageAnalysis` | Class | `inference/gateway/app/vision_schemas.py` | 36 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Initialize → _generate_request_id` | cross_community | 8 |
| `Initialize → _get_async_client` | cross_community | 8 |
| `Initialize → AuthenticationError` | cross_community | 8 |
| `Execute → _refill` | cross_community | 7 |
| `Initialize → PermissionDeniedError` | cross_community | 7 |
| `Initialize → RateLimitError` | cross_community | 7 |
| `Initialize → ValidationError` | cross_community | 7 |
| `Openai_chat_completions → HybridRouter` | cross_community | 7 |
| `Openai_chat_completions → ModelSelection` | cross_community | 7 |
| `Openai_chat_completions → _generate_request_id` | cross_community | 7 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Inference | 45 calls |
| Tests | 34 calls |
| Api | 19 calls |
| Libs | 10 calls |
| Benchmarking | 4 calls |
| Integrations | 3 calls |
| Chat-api | 2 calls |
| Face | 1 calls |

## How to Explore

1. `gitnexus_context({name: "get_current_user"})` — see callers and callees
2. `gitnexus_query({query: "app"})` — find related execution flows
3. Read key files listed above for implementation details
