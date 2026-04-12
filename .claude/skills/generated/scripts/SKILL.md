---
name: scripts
description: "Skill for the Scripts area of shml-platform. 149 symbols across 20 files."
---

# Scripts

149 symbols | 20 files | Cohesion: 93%

## When to Use

- Working with code in `scripts/`
- Understanding how invalidate, health_check, submit_job work
- Modifying scripts-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `scripts/training_orchestrator.py` | TrainingJobConfig, invalidate, _request, health_check, submit_job (+23) |
| `scripts/validate_pipeline.py` | get_db_password, report_pass, report_fail, report_skip, validate_mlflow (+6) |
| `scripts/obsidian_watcher.py` | _load_module, run_ingestion, _DebounceHandler, trigger, cancel (+5) |
| `scripts/continue_mcp_bridge.py` | _http_get, _http_post, _write, _ok, _err (+5) |
| `scripts/memory_watchdog.py` | MemorySnapshot, snapshot, check_alerts, log_snapshot, run_watchdog (+5) |
| `scripts/generate_connection_map.py` | _safe_id, _build_service_lookup, generate_mermaid, generate_status_table, generate_gap_analysis (+4) |
| `scripts/setup_mlflow_registry.py` | setup_registry, register_model_from_run, compare_model_versions, promote_to_production, list_model_versions (+2) |
| `scripts/ingest_research_to_obsidian.py` | ParsedDoc, parse_md, slug, make_note, _infer_tags (+2) |
| `mlflow-server/scripts/initialize_mlflow.py` | wait_for_mlflow, create_experiment_if_not_exists, setup_standard_experiments, setup_model_registry, setup_dataset_registry (+2) |
| `mlflow-server/scripts/consolidate_datasets.py` | get_file_info, format_size, analyze_existing_datasets, plan_consolidation, execute_consolidation (+2) |

## Entry Points

Start here when exploring this area:

- **`invalidate`** (Function) — `scripts/training_orchestrator.py:256`
- **`health_check`** (Function) — `scripts/training_orchestrator.py:352`
- **`submit_job`** (Function) — `scripts/training_orchestrator.py:356`
- **`get_job_status`** (Function) — `scripts/training_orchestrator.py:400`
- **`list_jobs`** (Function) — `scripts/training_orchestrator.py:404`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `TrainingJobConfig` | Class | `scripts/training_orchestrator.py` | 104 |
| `TrainingOrchestrator` | Class | `scripts/training_orchestrator.py` | 706 |
| `ParsedDoc` | Class | `scripts/ingest_research_to_obsidian.py` | 37 |
| `MLflowInitializer` | Class | `mlflow-server/docker/mlflow/scripts/init_mlflow.py` | 21 |
| `OAuthConfig` | Class | `scripts/training_orchestrator.py` | 48 |
| `RayAPIConfig` | Class | `scripts/training_orchestrator.py` | 88 |
| `OAuthTokenManager` | Class | `scripts/training_orchestrator.py` | 155 |
| `RayAPIClient` | Class | `scripts/training_orchestrator.py` | 275 |
| `JobMonitor` | Class | `scripts/training_orchestrator.py` | 430 |
| `MemorySnapshot` | Class | `scripts/memory_watchdog.py` | 106 |
| `AuthenticationError` | Class | `scripts/training_orchestrator.py` | 264 |
| `ProcessInfo` | Class | `scripts/memory_watchdog.py` | 95 |
| `invalidate` | Function | `scripts/training_orchestrator.py` | 256 |
| `health_check` | Function | `scripts/training_orchestrator.py` | 352 |
| `submit_job` | Function | `scripts/training_orchestrator.py` | 356 |
| `get_job_status` | Function | `scripts/training_orchestrator.py` | 400 |
| `list_jobs` | Function | `scripts/training_orchestrator.py` | 404 |
| `cancel_job` | Function | `scripts/training_orchestrator.py` | 415 |
| `get_job_logs` | Function | `scripts/training_orchestrator.py` | 420 |
| `wait_for_completion` | Function | `scripts/training_orchestrator.py` | 446 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → MLflowError` | cross_community | 6 |
| `Main → Invalidate` | intra_community | 5 |
| `Main → _generate_request_id` | cross_community | 5 |
| `Main → _get_async_client` | cross_community | 5 |
| `Main → AuthenticationError` | cross_community | 5 |
| `Main → PermissionDeniedError` | cross_community | 5 |
| `Main → RateLimitError` | cross_community | 5 |
| `Main → ValidationError` | cross_community | 5 |
| `Submit → _refill` | cross_community | 5 |
| `Main → TimeoutError` | cross_community | 4 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Integrations | 9 calls |
| Libs | 6 calls |
| Api | 6 calls |
| Inference | 5 calls |
| Integration | 2 calls |
| Llm | 1 calls |

## How to Explore

1. `gitnexus_context({name: "invalidate"})` — see callers and callees
2. `gitnexus_query({query: "scripts"})` — find related execution flows
3. Read key files listed above for implementation details
