---
name: admin
description: "Skill for the Admin area of shml-platform. 119 symbols across 22 files."
---

# Admin

119 symbols | 22 files | Cohesion: 77%

## When to Use

- Working with code in `libs/`
- Understanding how destroySandbox, print_json, print_table work
- Modifying admin-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `libs/client/shml/admin/cli.py` | print_json, print_table, select_from_list, confirm, CLI (+23) |
| `tests/client/admin/conftest.py` | mock_config, get_test_api_key, get_fusionauth_url, is_fusionauth_available, sdk_config (+8) |
| `tests/client/admin/test_permissions.py` | test_has_any_permission, test_admin_has_all_permissions, test_viewer_limited_permissions, test_explicit_permissions_override_role, create_user (+6) |
| `libs/client/shml/admin/http.py` | RateLimiter, __init__, _refill, acquire, acquire_sync (+5) |
| `tests/client/admin/test_models.py` | test_admin_has_all_permissions, test_developer_read_permissions, test_developer_limited_write, test_viewer_read_only, test_role_has_permission_function (+3) |
| `tests/unit/libs/test_client_edge_cases.py` | test_sdk_config_requires_base_url, test_sdk_config_accepts_valid_url, test_rate_limit_error_carries_retry_after, test_service_unavailable_error_is_platform_error, test_validation_error_is_platform_error (+2) |
| `libs/client/shml/admin/exceptions.py` | PlatformSDKError, RateLimitError, ValidationError, ServiceUnavailableError, ConnectionError (+1) |
| `libs/client/shml/admin/permissions.py` | permissions, has_any_permission, sync_wrapper, async_wrapper, has_permission (+1) |
| `tests/client/admin/test_client.py` | test_config_defaults, test_config_from_env, test_config_validation, test_config_validate_connection, test_config_repr_hides_key |
| `libs/client/shml/admin/models.py` | get_permissions_for_role, role_has_permission, PaginatedResponse, has_permission |

## Entry Points

Start here when exploring this area:

- **`destroySandbox`** (Function) — `chat-ui-v2/src/hooks/useSandboxes.ts:213`
- **`print_json`** (Function) — `libs/client/shml/admin/cli.py:27`
- **`print_table`** (Function) — `libs/client/shml/admin/cli.py:32`
- **`select_from_list`** (Function) — `libs/client/shml/admin/cli.py:57`
- **`confirm`** (Function) — `libs/client/shml/admin/cli.py:86`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `CLI` | Class | `libs/client/shml/admin/cli.py` | 96 |
| `SDKConfig` | Class | `libs/client/shml/admin/config.py` | 14 |
| `PlatformSDKError` | Class | `libs/client/shml/admin/exceptions.py` | 15 |
| `RateLimitError` | Class | `libs/client/shml/admin/exceptions.py` | 112 |
| `ValidationError` | Class | `libs/client/shml/admin/exceptions.py` | 138 |
| `ServiceUnavailableError` | Class | `libs/client/shml/admin/exceptions.py` | 165 |
| `ConnectionError` | Class | `libs/client/shml/admin/exceptions.py` | 191 |
| `RateLimiter` | Class | `libs/client/shml/admin/http.py` | 27 |
| `PermissionDeniedError` | Class | `libs/client/shml/admin/exceptions.py` | 64 |
| `UsersService` | Class | `libs/client/shml/admin/services/users.py` | 13 |
| `ApplicationsService` | Class | `libs/client/shml/admin/services/applications.py` | 13 |
| `PaginatedResponse` | Class | `libs/client/shml/admin/models.py` | 227 |
| `destroySandbox` | Function | `chat-ui-v2/src/hooks/useSandboxes.ts` | 213 |
| `print_json` | Function | `libs/client/shml/admin/cli.py` | 27 |
| `print_table` | Function | `libs/client/shml/admin/cli.py` | 32 |
| `select_from_list` | Function | `libs/client/shml/admin/cli.py` | 57 |
| `confirm` | Function | `libs/client/shml/admin/cli.py` | 86 |
| `connect` | Function | `libs/client/shml/admin/cli.py` | 103 |
| `cmd_user_list` | Function | `libs/client/shml/admin/cli.py` | 146 |
| `cmd_user_get` | Function | `libs/client/shml/admin/cli.py` | 177 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Execute → _refill` | cross_community | 7 |
| `Initialize → PermissionDeniedError` | cross_community | 7 |
| `Initialize → RateLimitError` | cross_community | 7 |
| `Initialize → ValidationError` | cross_community | 7 |
| `Start_impersonation → _refill` | cross_community | 6 |
| `Train → _refill` | cross_community | 6 |
| `On_train_end → _refill` | cross_community | 6 |
| `Train → _refill` | cross_community | 6 |
| `Train → _refill` | cross_community | 6 |
| `Cleanup_before_and_after_tests → _refill` | cross_community | 6 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Libs | 31 calls |
| Integration | 3 calls |
| Services | 1 calls |

## How to Explore

1. `gitnexus_context({name: "destroySandbox"})` — see callers and callees
2. `gitnexus_query({query: "admin"})` — find related execution flows
3. Read key files listed above for implementation details
