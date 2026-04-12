---
name: api
description: "Skill for the Api area of shml-platform. 169 symbols across 38 files."
---

# Api

169 symbols | 38 files | Cohesion: 61%

## When to Use

- Working with code in `ray_compute/`
- Understanding how auth_session, get_cluster_status, get_cluster_nodes work
- Modifying api-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `mlflow-server/api/main.py` | load_schema, validate_run_against_schema, format_error_response, get_schema, get_experiment_schema (+12) |
| `ray_compute/api/client_remote.py` | health_check, get_resources, list_jobs, get_logs, cancel_job (+10) |
| `ray_compute/api/api_keys.py` | ApiKeyCreateResponse, ApiKeyRotateResponse, list_api_keys, create_api_key, rotate_api_key (+5) |
| `ray_compute/api/training.py` | get_training_job_logs, TrainingJobStatus, get_training_job_status, get_queue_overview, get_job_queue_status (+4) |
| `ray_compute/api/server_remote.py` | JobInfo, get_job_workspace, health_check, submit_job, list_jobs (+3) |
| `ray_compute/api/server_v2.py` | list_jobs, GPUInfo, ClusterGPUInfo, get_cluster_gpus, sync_job_statuses (+2) |
| `ray_compute/api/scheduler.py` | TrainingScheduler, get_job_status, get_queue_overview, remove_from_queue, deallocate (+2) |
| `ray_compute/api/mlflow_integration.py` | log_artifact, log_job_start, log_job_artifact, log_job_end, close (+2) |
| `tests/unit/ray_compute/test_mlflow_integration.py` | test_log_artifact_calls_mlflow, test_log_job_helpers_delegate_to_global_logger, test_log_artifact_returns_when_not_enabled, test_log_artifact_exception_is_caught, test_close_closes_http_client (+2) |
| `mlflow-server/api/main_enhanced.py` | check_rate_limit, load_schema, validate_run_against_schema, format_error_response, create_run (+2) |

## Entry Points

Start here when exploring this area:

- **`auth_session`** (Function) — `tests/integration/test_new_services.py:70`
- **`get_cluster_status`** (Function) — `ray_compute/api/cluster.py:72`
- **`get_cluster_nodes`** (Function) — `ray_compute/api/cluster.py:136`
- **`get_gpu_info`** (Function) — `ray_compute/api/cluster.py:174`
- **`get_actors`** (Function) — `ray_compute/api/cluster.py:216`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `ClusterStatus` | Class | `ray_compute/api/cluster.py` | 42 |
| `AuditLogger` | Class | `ray_compute/api/audit.py` | 120 |
| `ApiKeyCreateResponse` | Class | `ray_compute/api/api_keys.py` | 77 |
| `ApiKeyRotateResponse` | Class | `ray_compute/api/api_keys.py` | 90 |
| `TrainingJobStatus` | Class | `ray_compute/api/training.py` | 181 |
| `TrainingScheduler` | Class | `ray_compute/api/scheduler.py` | 350 |
| `Query` | Class | `libs/feature_store/graphql.py` | 62 |
| `UserQuota` | Class | `ray_compute/api/models.py` | 64 |
| `ArtifactVersion` | Class | `ray_compute/api/models.py` | 190 |
| `ResourceUsageDaily` | Class | `ray_compute/api/models.py` | 210 |
| `SystemAlert` | Class | `ray_compute/api/models.py` | 286 |
| `AuditLog` | Class | `ray_compute/api/audit.py` | 62 |
| `Base` | Class | `tests/unit/ray_compute/conftest.py` | 139 |
| `RemoteComputeClient` | Class | `ray_compute/api/client_remote.py` | 24 |
| `JobInfo` | Class | `ray_compute/api/server_remote.py` | 144 |
| `ImpersonationResponse` | Class | `ray_compute/api/api_keys.py` | 110 |
| `AuditLog` | Class | `ray_compute/api/models.py` | 225 |
| `GPUInfo` | Class | `ray_compute/api/server_v2.py` | 348 |
| `ClusterGPUInfo` | Class | `ray_compute/api/server_v2.py` | 359 |
| `TimeoutError` | Class | `libs/client/shml/admin/exceptions.py` | 207 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Initialize → AuthenticationError` | cross_community | 8 |
| `Submit_training_job → Query` | cross_community | 7 |
| `Submit_training_job → Calculate_job_usage` | cross_community | 7 |
| `Initialize → PermissionDeniedError` | cross_community | 7 |
| `Initialize → RateLimitError` | cross_community | 7 |
| `Initialize → ValidationError` | cross_community | 7 |
| `Submit_training_job → Get_tier_limits` | cross_community | 6 |
| `Start_impersonation → _refill` | cross_community | 6 |
| `Chat_completions → AuthenticationError` | cross_community | 6 |
| `Chat_completions → PermissionDeniedError` | cross_community | 6 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Ray_compute | 46 calls |
| Libs | 13 calls |
| Inference | 4 calls |
| Admin | 4 calls |
| Integrations | 2 calls |
| App | 2 calls |
| Feature_store | 2 calls |

## How to Explore

1. `gitnexus_context({name: "auth_session"})` — see callers and callees
2. `gitnexus_query({query: "api"})` — find related execution flows
3. Read key files listed above for implementation details
