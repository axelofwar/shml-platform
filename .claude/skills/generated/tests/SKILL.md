---
name: tests
description: "Skill for the Tests area of shml-platform. 156 symbols across 26 files."
---

# Tests

156 symbols | 26 files | Cohesion: 84%

## When to Use

- Working with code in `inference/`
- Understanding how test_record_populates_session_tier, test_record_populates_longterm_tier, test_record_persists_to_jsonl_file work
- Modifying tests-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `inference/agent-service/tests/test_sprint_patterns.py` | _make_store, test_record_populates_session_tier, test_record_populates_longterm_tier, test_record_persists_to_jsonl_file, test_reload_from_file_restores_longterm (+40) |
| `inference/agent-service/tests/test_agent_loop.py` | test_loop_config_defaults, test_loop_config_env_override, test_agent_loop_idle_when_no_issues, test_circuit_breaker_triggers_after_threshold, test_graduation_bumps_threshold_after_5_successes (+17) |
| `tests/test_gpu_ray_native.py` | print_header, print_success, print_error, wait_for_job, RayGPUTester (+11) |
| `inference/agent-service/tests/test_integration.py` | test_add_and_retrieve_bullets, test_deduplication, test_category_filtering, test_build_agent, test_agent_execution_mock (+7) |
| `inference/agent-service/app/memory_store.py` | MemoryEntry, to_dict, MemoryStore, record, get_recent_context (+2) |
| `tests/test_sdk_integration.py` | test_basic_imports, test_config_builder, test_client_creation, test_live_api_connection, test_job_submission_mock (+2) |
| `inference/agent-service/app/agent_loop.py` | LoopConfig, AgentLoop, _pick_issue, _handle_success, estimate_complexity (+1) |
| `sdk/tests/test_exceptions.py` | test_401_raises_authentication_error, test_403_raises_permission_denied, test_404_raises_not_found, test_429_raises_rate_limit, test_200_does_not_raise (+1) |
| `libs/training/shml_training/sdk/client.py` | to_api_format, TrainingClient, submit_training, list_models, submit_and_wait |
| `inference/agent-service/app/context.py` | AgentPlaybook, add_bullet, retrieve_relevant, _deduplicate |

## Entry Points

Start here when exploring this area:

- **`test_record_populates_session_tier`** (Function) — `inference/agent-service/tests/test_sprint_patterns.py:668`
- **`test_record_populates_longterm_tier`** (Function) — `inference/agent-service/tests/test_sprint_patterns.py:674`
- **`test_record_persists_to_jsonl_file`** (Function) — `inference/agent-service/tests/test_sprint_patterns.py:679`
- **`test_reload_from_file_restores_longterm`** (Function) — `inference/agent-service/tests/test_sprint_patterns.py:690`
- **`test_get_recent_context_empty`** (Function) — `inference/agent-service/tests/test_sprint_patterns.py:701`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `MemoryEntry` | Class | `inference/agent-service/app/memory_store.py` | 46 |
| `MemoryStore` | Class | `inference/agent-service/app/memory_store.py` | 79 |
| `RayGPUTester` | Class | `tests/test_gpu_ray_native.py` | 115 |
| `TrainingClient` | Class | `libs/training/shml_training/sdk/client.py` | 240 |
| `AgentPlaybook` | Class | `inference/agent-service/app/context.py` | 166 |
| `FakeIssue` | Class | `inference/agent-service/tests/test_sprint_patterns.py` | 52 |
| `CodeWorker` | Class | `inference/agent-service/app/code_worker.py` | 165 |
| `LoopConfig` | Class | `inference/agent-service/app/agent_loop.py` | 79 |
| `AgentLoop` | Class | `inference/agent-service/app/agent_loop.py` | 250 |
| `FakeIssue` | Class | `inference/agent-service/tests/test_agent_loop.py` | 26 |
| `GapDetector` | Class | `inference/agent-service/app/gap_detector.py` | 43 |
| `TestResult` | Class | `inference/agent-service/app/test_worker.py` | 30 |
| `HookBlocked` | Class | `inference/agent-service/app/hooks.py` | 92 |
| `test_record_populates_session_tier` | Function | `inference/agent-service/tests/test_sprint_patterns.py` | 668 |
| `test_record_populates_longterm_tier` | Function | `inference/agent-service/tests/test_sprint_patterns.py` | 674 |
| `test_record_persists_to_jsonl_file` | Function | `inference/agent-service/tests/test_sprint_patterns.py` | 679 |
| `test_reload_from_file_restores_longterm` | Function | `inference/agent-service/tests/test_sprint_patterns.py` | 690 |
| `test_get_recent_context_empty` | Function | `inference/agent-service/tests/test_sprint_patterns.py` | 701 |
| `test_get_recent_context_shows_n_latest` | Function | `inference/agent-service/tests/test_sprint_patterns.py` | 705 |
| `test_get_session_summary_counts` | Function | `inference/agent-service/tests/test_sprint_patterns.py` | 714 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Execute → _refill` | cross_community | 7 |
| `Execute → _generate_request_id` | cross_community | 6 |
| `Execute → _get_async_client` | cross_community | 6 |
| `Execute → _token` | cross_community | 6 |
| `Lifespan → Estimate_complexity` | cross_community | 6 |
| `Lifespan → Get_recent_context` | cross_community | 6 |
| `Start_agent_loop → Estimate_complexity` | cross_community | 6 |
| `Start_agent_loop → Get_recent_context` | cross_community | 6 |
| `Start_agent_loop → CodeWorker` | cross_community | 6 |
| `Start_agent_loop → Inc` | cross_community | 6 |

## Connected Areas

| Area | Connections |
|------|-------------|
| App | 22 calls |
| Sdk | 6 calls |
| Libs | 5 calls |
| Integration | 2 calls |
| Shml | 1 calls |

## How to Explore

1. `gitnexus_context({name: "test_record_populates_session_tier"})` — see callers and callees
2. `gitnexus_query({query: "tests"})` — find related execution flows
3. Read key files listed above for implementation details
