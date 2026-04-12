---
name: shml
description: "Skill for the Shml area of shml-platform. 126 symbols across 18 files."
---

# Shml

126 symbols | 18 files | Cohesion: 82%

## When to Use

- Working with code in `sdk/`
- Understanding how test_submits_with_direct_client_and_closes_it, test_closes_original_and_impersonated_clients, test_ray_status_uses_context_manager work
- Modifying shml-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `libs/client/shml/client.py` | Client, client, _get_headers, _handle_response, submit (+18) |
| `sdk/shml/client.py` | __init__, health_check, Job, _headers, _handle (+16) |
| `sdk/shml/main.py` | _out, _err, _ok, _client, train (+13) |
| `sdk/shml/config.py` | AuthConfig, list_profiles, TrainingConfig, to_rfdetr_dict, to_yaml (+13) |
| `sdk/shml/exceptions.py` | SHMLError, AuthenticationError, PermissionDeniedError, NotFoundError, RateLimitError (+7) |
| `libs/client/shml/models.py` | Job, JobSubmitResponse, User, Quota, ApiKey (+2) |
| `tests/unit/libs/test_client_shortcuts.py` | test_submits_with_direct_client_and_closes_it, test_closes_original_and_impersonated_clients, test_ray_status_uses_context_manager, test_ray_logs_uses_context_manager, test_ray_cancel_uses_context_manager_and_passes_reason |
| `sdk/tests/test_config.py` | test_to_rfdetr_dict, test_yaml_roundtrip, test_to_dict, test_defaults_are_numeric, test_default_construction |
| `libs/client/shml/shortcuts.py` | ray_submit, ray_status, ray_logs, ray_cancel |
| `sdk/tests/test_exceptions.py` | test_shml_error_message, test_authentication_error, test_job_error_preserves_context |

## Entry Points

Start here when exploring this area:

- **`test_submits_with_direct_client_and_closes_it`** (Function) — `tests/unit/libs/test_client_shortcuts.py:10`
- **`test_closes_original_and_impersonated_clients`** (Function) — `tests/unit/libs/test_client_shortcuts.py:35`
- **`test_ray_status_uses_context_manager`** (Function) — `tests/unit/libs/test_client_shortcuts.py:51`
- **`test_ray_logs_uses_context_manager`** (Function) — `tests/unit/libs/test_client_shortcuts.py:65`
- **`test_ray_cancel_uses_context_manager_and_passes_reason`** (Function) — `tests/unit/libs/test_client_shortcuts.py:77`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `Job` | Class | `libs/client/shml/models.py` | 24 |
| `JobSubmitResponse` | Class | `libs/client/shml/models.py` | 46 |
| `User` | Class | `libs/client/shml/models.py` | 55 |
| `Quota` | Class | `libs/client/shml/models.py` | 67 |
| `ApiKey` | Class | `libs/client/shml/models.py` | 83 |
| `ApiKeyWithSecret` | Class | `libs/client/shml/models.py` | 97 |
| `ImpersonationToken` | Class | `libs/client/shml/models.py` | 110 |
| `Client` | Class | `libs/client/shml/client.py` | 54 |
| `AuthConfig` | Class | `sdk/shml/config.py` | 671 |
| `Job` | Class | `sdk/shml/client.py` | 44 |
| `SHMLError` | Class | `sdk/shml/exceptions.py` | 33 |
| `AuthenticationError` | Class | `sdk/shml/exceptions.py` | 55 |
| `PermissionDeniedError` | Class | `sdk/shml/exceptions.py` | 65 |
| `NotFoundError` | Class | `sdk/shml/exceptions.py` | 75 |
| `RateLimitError` | Class | `sdk/shml/exceptions.py` | 82 |
| `ConfigError` | Class | `sdk/shml/exceptions.py` | 124 |
| `ProfileNotFoundError` | Class | `sdk/shml/exceptions.py` | 130 |
| `ValidationError` | Class | `sdk/shml/exceptions.py` | 141 |
| `PrometheusReporter` | Class | `sdk/shml/integrations/prometheus.py` | 17 |
| `NessieClient` | Class | `sdk/shml/integrations/nessie.py` | 18 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Run → _generate_request_id` | cross_community | 7 |
| `Run → NessieError` | cross_community | 6 |
| `Cancel → _refill` | cross_community | 6 |
| `Gpu_yield → _refill` | cross_community | 6 |
| `Reclaim → _refill` | cross_community | 6 |
| `Cancel → _generate_request_id` | cross_community | 5 |
| `Cancel → _get_async_client` | cross_community | 5 |
| `Cancel → SHMLError` | cross_community | 5 |
| `Gpu_status → SHMLError` | cross_community | 5 |
| `Gpu_yield → _generate_request_id` | cross_community | 5 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Inference | 13 calls |
| Libs | 2 calls |
| Integration | 2 calls |
| Integrations | 2 calls |
| Face | 1 calls |
| Tests | 1 calls |
| Training | 1 calls |

## How to Explore

1. `gitnexus_context({name: "test_submits_with_direct_client_and_closes_it"})` — see callers and callees
2. `gitnexus_query({query: "shml"})` — find related execution flows
3. Read key files listed above for implementation details
