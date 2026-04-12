---
name: ray-compute
description: "Skill for the Ray_compute area of shml-platform. 599 symbols across 41 files."
---

# Ray_compute

599 symbols | 41 files | Cohesion: 73%

## When to Use

- Working with code in `tests/`
- Understanding how test_list_models_requires_auth, test_list_api_keys_requires_auth, test_conversations_requires_auth work
- Modifying ray_compute-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/ray_compute/test_training.py` | _make_user, _make_job, _make_db, _make_client, test_returns_all_5_models (+79) |
| `tests/unit/ray_compute/test_auth.py` | _make_db, _make_request, test_no_headers_returns_none, test_existing_user_by_oauth_sub, test_existing_user_by_email_updates_oauth_sub (+58) |
| `tests/unit/ray_compute/test_mlflow_integration.py` | reset_module_state, test_init_reads_environment_defaults, test_init_respects_disable_env, test_initialize_noops_when_disabled, test_initialize_creates_missing_experiment (+41) |
| `tests/unit/ray_compute/test_api_keys.py` | _make_user, _make_api_key_record, _make_db, _make_client, test_list_returns_200 (+38) |
| `tests/unit/ray_compute/test_job_management.py` | _make_client, _make_client_for_restart, _make_user, _make_job, _make_db (+33) |
| `tests/unit/ray_compute/test_server_v2.py` | _request, _user, _db_for_model, _job_request, test_get_current_user_profile_returns_user (+30) |
| `tests/unit/ray_compute/test_logs.py` | _make_app_for_logs, _make_test_user, _make_job, _make_db, test_admin_can_access_any_job (+30) |
| `tests/unit/ray_compute/test_usage_tracking.py` | test_user_tier, test_premium_tier, test_admin_tier, test_unknown_tier_defaults_to_user, test_empty_string_defaults_to_user (+29) |
| `tests/unit/ray_compute/test_scheduler.py` | _user, _job, test_priority_score_uses_tier_timeout_and_priority_adjustments, test_priority_score_defaults_unknown_role, test_enqueue_job_adds_queue_entry (+21) |
| `ray_compute/api/mlflow_integration.py` | MLflowAutoLogger, initialize, MLflowRESTClient, _api_call, create_run (+14) |

## Entry Points

Start here when exploring this area:

- **`test_list_models_requires_auth`** (Function) — `tests/chat-api/test_endpoints.py:44`
- **`test_list_api_keys_requires_auth`** (Function) — `tests/chat-api/test_endpoints.py:56`
- **`test_conversations_requires_auth`** (Function) — `tests/chat-api/test_endpoints.py:62`
- **`test_instructions_requires_auth`** (Function) — `tests/chat-api/test_endpoints.py:68`
- **`test_rate_limit_requires_auth`** (Function) — `tests/chat-api/test_endpoints.py:74`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `TestClient` | Class | `sdk/tests/test_client.py` | 29 |
| `JobSubmitRequest` | Class | `ray_compute/api/server_v2.py` | 228 |
| `QuotaResponse` | Class | `ray_compute/api/server_v2.py` | 329 |
| `RayComputeClient` | Class | `ray_compute/api/client.py` | 20 |
| `MetricDirection` | Class | `libs/evaluation/benchmarking/models.py` | 7 |
| `RegressionRule` | Class | `libs/evaluation/benchmarking/models.py` | 40 |
| `RegressionOutcome` | Class | `libs/evaluation/benchmarking/models.py` | 48 |
| `MLflowAutoLogger` | Class | `ray_compute/api/mlflow_integration.py` | 14 |
| `MLflowRESTClient` | Class | `ray_compute/api/mlflow_integration.py` | 255 |
| `FeatureRegistry` | Class | `libs/feature_store/registry.py` | 155 |
| `AuthError` | Class | `ray_compute/api/auth.py` | 90 |
| `JobQueue` | Class | `ray_compute/api/models.py` | 169 |
| `GPUAllocation` | Class | `ray_compute/api/scheduler.py` | 274 |
| `FeatureQueryResponse` | Class | `libs/feature_store/api.py` | 87 |
| `TechniqueConfig` | Class | `ray_compute/api/training.py` | 79 |
| `TrainingJobRequest` | Class | `ray_compute/api/training.py` | 119 |
| `TrainingHyperparameters` | Class | `ray_compute/api/training.py` | 87 |
| `ApiKey` | Class | `ray_compute/api/models.py` | 242 |
| `MLflowArtifactManager` | Class | `libs/evaluation/benchmarking/mlflow_artifacts.py` | 18 |
| `ComputeConfig` | Class | `ray_compute/api/training.py` | 109 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Submit_training_job → Query` | cross_community | 7 |
| `Submit_training_job → Calculate_job_usage` | cross_community | 7 |
| `Submit_training_job → Get_tier_limits` | cross_community | 6 |
| `Start_impersonation → _refill` | cross_community | 6 |
| `Wrapper → MLflowError` | cross_community | 6 |
| `Wrapper → _generate_request_id` | cross_community | 6 |
| `Wrapper → _get_async_client` | cross_community | 6 |
| `Create_api_key → Encode_special` | cross_community | 5 |
| `Start_impersonation → _generate_request_id` | cross_community | 5 |
| `Start_impersonation → _get_async_client` | cross_community | 5 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Libs | 71 calls |
| Api | 55 calls |
| Inference | 49 calls |
| Integrations | 7 calls |
| Feature_store | 4 calls |
| Integration | 3 calls |

## How to Explore

1. `gitnexus_context({name: "test_list_models_requires_auth"})` — see callers and callees
2. `gitnexus_query({query: "ray_compute"})` — find related execution flows
3. Read key files listed above for implementation details
