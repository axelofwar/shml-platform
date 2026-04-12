---
name: services
description: "Skill for the Services area of shml-platform. 48 symbols across 10 files."
---

# Services

48 symbols | 10 files | Cohesion: 61%

## When to Use

- Working with code in `libs/`
- Understanding how test_add_member_by_name_passes_through_lookup_failure, list_async, get work
- Modifying services-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `libs/client/shml/admin/services/groups.py` | list_async, get, get_async, get_by_name, get_by_name_async (+12) |
| `libs/client/shml/admin/services/api_keys.py` | list, list_async, get, get_async, get_key_summary (+4) |
| `libs/client/shml/admin/services/applications.py` | update, update_role, list, update_async, deactivate_async (+1) |
| `libs/client/shml/admin/services/registrations.py` | update, create_async, register_with_roles_async, register_one |
| `tests/unit/libs/test_admin_permissions_and_services.py` | test_add_member_by_name_passes_through_lookup_failure, test_invalidate_cache, test_get_key_summary |
| `tests/unit/libs/test_admin_applications_service.py` | test_update_role_builds_partial_payload, test_update_async_builds_full_payload, test_deactivate_and_reactivate_async_delegate_to_update_async |
| `libs/client/shml/admin/http.py` | patch_sync, get_sync |
| `libs/client/shml/admin/services/users.py` | update, list |
| `libs/client/shml/admin/services/roles.py` | update |
| `tests/unit/libs/test_admin_registrations_service.py` | test_register_with_roles_async_delegates_to_create_async |

## Entry Points

Start here when exploring this area:

- **`test_add_member_by_name_passes_through_lookup_failure`** (Function) — `tests/unit/libs/test_admin_permissions_and_services.py:441`
- **`list_async`** (Function) — `libs/client/shml/admin/services/groups.py:43`
- **`get`** (Function) — `libs/client/shml/admin/services/groups.py:48`
- **`get_async`** (Function) — `libs/client/shml/admin/services/groups.py:61`
- **`get_by_name`** (Function) — `libs/client/shml/admin/services/groups.py:66`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_add_member_by_name_passes_through_lookup_failure` | Function | `tests/unit/libs/test_admin_permissions_and_services.py` | 441 |
| `list_async` | Function | `libs/client/shml/admin/services/groups.py` | 43 |
| `get` | Function | `libs/client/shml/admin/services/groups.py` | 48 |
| `get_async` | Function | `libs/client/shml/admin/services/groups.py` | 61 |
| `get_by_name` | Function | `libs/client/shml/admin/services/groups.py` | 66 |
| `get_by_name_async` | Function | `libs/client/shml/admin/services/groups.py` | 94 |
| `add_member_async` | Function | `libs/client/shml/admin/services/groups.py` | 391 |
| `add_member_by_name` | Function | `libs/client/shml/admin/services/groups.py` | 438 |
| `add_member_by_name_async` | Function | `libs/client/shml/admin/services/groups.py` | 469 |
| `test_update_role_builds_partial_payload` | Function | `tests/unit/libs/test_admin_applications_service.py` | 238 |
| `patch_sync` | Function | `libs/client/shml/admin/http.py` | 405 |
| `update` | Function | `libs/client/shml/admin/services/users.py` | 256 |
| `update` | Function | `libs/client/shml/admin/services/roles.py` | 141 |
| `update` | Function | `libs/client/shml/admin/services/registrations.py` | 292 |
| `update` | Function | `libs/client/shml/admin/services/groups.py` | 255 |
| `update` | Function | `libs/client/shml/admin/services/applications.py` | 247 |
| `update_role` | Function | `libs/client/shml/admin/services/applications.py` | 484 |
| `get_sync` | Function | `libs/client/shml/admin/http.py` | 374 |
| `list` | Function | `libs/client/shml/admin/services/users.py` | 33 |
| `list` | Function | `libs/client/shml/admin/services/groups.py` | 33 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Libs | 21 calls |
| Api | 5 calls |
| Inference | 4 calls |

## How to Explore

1. `gitnexus_context({name: "test_add_member_by_name_passes_through_lookup_failure"})` — see callers and callees
2. `gitnexus_query({query: "services"})` — find related execution flows
3. Read key files listed above for implementation details
