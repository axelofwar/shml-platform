---
name: libs
description: "Skill for the Libs area of shml-platform. 1146 symbols across 99 files."
---

# Libs

1146 symbols | 99 files | Cohesion: 77%

## When to Use

- Working with code in `tests/`
- Understanding how test_search_wraps_query_with_wildcards, test_create_builds_full_payload, test_create_builds_payload work
- Modifying libs-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/libs/test_training_integrations.py` | test_check_preemption_disabled, test_get_queue_position_not_found, test_job_orchestrator_init_select_backend_and_submit_paths, test_job_orchestrator_init_swallows_ray_backend_error, test_start_sets_started_flag (+89) |
| `tests/unit/libs/test_admin_permissions_and_services.py` | test_base_service_properties, _service, test_list, test_list_inactive, test_get_by_name_found (+80) |
| `tests/unit/libs/test_client_sdk.py` | _config, _response, _job_payload, _user_payload, _quota_payload (+47) |
| `tests/unit/libs/test_training_optim.py` | FakeTensor, mT, __getitem__, __pow__, __truediv__ (+45) |
| `tests/unit/libs/test_admin_applications_service.py` | test_search_builds_payload, test_create_without_optional_fields_uses_collection_endpoint, test_create_with_explicit_application_id, _admin_ctx, _service (+31) |
| `tests/unit/libs/test_evaluation.py` | _mgr, test_init_no_tracking_uri, test_get_or_create_uses_existing_experiment, test_get_or_create_creates_new_experiment, test_resolve_golden_dataset_with_version (+28) |
| `tests/unit/libs/test_admin_users_roles_service.py` | test_search_wraps_query_with_wildcards, test_create_builds_full_payload, test_create_builds_payload, _users_service, test_list_builds_search_params (+27) |
| `libs/training/shml_training/integrations/progress.py` | AGUIEventEmitter, __init__, start, stop, add_callback (+24) |
| `tests/unit/libs/test_training_memory.py` | test_determine_num_chunks_respects_explicit_setting, test_determine_num_chunks_caches_auto_value, test_determine_num_chunks_falls_back_on_error, test_from_config_and_loss_function_are_cached, test_optimize_optimizer_returns_original_optimizer (+24) |
| `tests/unit/libs/test_admin_sdk_client.py` | _config, test_requires_api_key, test_role_override_admin_skips_introspection, test_from_env, test_introspect_failure_defaults_to_viewer (+22) |

## Entry Points

Start here when exploring this area:

- **`test_search_wraps_query_with_wildcards`** (Function) — `tests/unit/libs/test_admin_users_roles_service.py:89`
- **`test_create_builds_full_payload`** (Function) — `tests/unit/libs/test_admin_users_roles_service.py:100`
- **`test_create_builds_payload`** (Function) — `tests/unit/libs/test_admin_users_roles_service.py:372`
- **`test_search_without_filters_uses_wildcard_query`** (Function) — `tests/unit/libs/test_admin_registrations_service.py:41`
- **`test_register_with_roles_delegates_to_create`** (Function) — `tests/unit/libs/test_admin_registrations_service.py:52`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `RegistrationsService` | Class | `libs/client/shml/admin/services/registrations.py` | 14 |
| `GroupsService` | Class | `libs/client/shml/admin/services/groups.py` | 13 |
| `BaseService` | Class | `libs/client/shml/admin/services/base.py` | 18 |
| `APIKeysService` | Class | `libs/client/shml/admin/services/api_keys.py` | 13 |
| `JobOrchestrator` | Class | `libs/training/shml_training/integrations/orchestrator.py` | 325 |
| `Service` | Class | `tests/unit/libs/test_admin_permissions_and_services.py` | 61 |
| `MockService` | Class | `tests/client/admin/test_permissions.py` | 113 |
| `PermissionContext` | Class | `libs/client/shml/admin/permissions.py` | 22 |
| `FeatureClient` | Class | `libs/shml_features.py` | 43 |
| `Client` | Class | `sdk/shml/client.py` | 57 |
| `AGUIEventEmitter` | Class | `libs/training/shml_training/integrations/progress.py` | 74 |
| `PlatformSDK` | Class | `libs/client/shml/admin/client.py` | 28 |
| `FakeLoop` | Class | `tests/unit/libs/test_training_gpu_resource.py` | 231 |
| `ServiceEndpoint` | Class | `libs/training/shml_training/core/gpu_resource.py` | 66 |
| `GPUResourceManager` | Class | `libs/training/shml_training/core/gpu_resource.py` | 128 |
| `ProgressReporter` | Class | `libs/training/shml_training/integrations/progress.py` | 332 |
| `HTTPClient` | Class | `libs/client/shml/admin/http.py` | 84 |
| `FeatureViewSummary` | Class | `libs/feature_store/registry.py` | 118 |
| `FakeAlreadyExists` | Class | `tests/unit/libs/test_feature_store.py` | 108 |
| `FakeDF` | Class | `tests/unit/libs/test_feature_materialize.py` | 92 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Initialize → _generate_request_id` | cross_community | 8 |
| `Initialize → _get_async_client` | cross_community | 8 |
| `Initialize → AuthenticationError` | cross_community | 8 |
| `Execute → _refill` | cross_community | 7 |
| `Run → _generate_request_id` | cross_community | 7 |
| `Openai_chat_completions → _generate_request_id` | cross_community | 7 |
| `Openai_chat_completions → _get_async_client` | cross_community | 7 |
| `Execute → _generate_request_id` | cross_community | 6 |
| `Execute → _get_async_client` | cross_community | 6 |
| `Start_impersonation → _refill` | cross_community | 6 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Services | 22 calls |
| Api | 21 calls |
| Integrations | 18 calls |
| Inference | 14 calls |
| Admin | 11 calls |
| Integration | 10 calls |
| App | 9 calls |
| Shml | 6 calls |

## How to Explore

1. `gitnexus_context({name: "test_search_wraps_query_with_wildcards"})` — see callers and callees
2. `gitnexus_query({query: "libs"})` — find related execution flows
3. Read key files listed above for implementation details
