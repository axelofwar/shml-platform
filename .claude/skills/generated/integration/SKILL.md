---
name: integration
description: "Skill for the Integration area of shml-platform. 97 symbols across 17 files."
---

# Integration

97 symbols | 17 files | Cohesion: 70%

## When to Use

- Working with code in `tests/`
- Understanding how is_traefik_running, traefik_available, test_protected_route_requires_oauth work
- Modifying integration-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/integration/test_full_stack.py` | is_auth_required, is_protected, test_mlflow_ui_protected_lan, test_mlflow_api_protected_lan, test_mlflow_ui_protected_external (+18) |
| `tests/integration/test_new_services.py` | test_nessie_oauth_redirect, test_fiftyone_oauth_redirect, test_slo_exporter_no_traefik_route, test_nessie_requires_developer_role, test_fiftyone_requires_developer_role (+9) |
| `tests/integration/test_inference_stack.py` | get_inference_url, test_gateway_health, test_llm_health, test_image_health, test_chat_completion_request (+9) |
| `tests/integration/test_chat_api_live.py` | test_valid_developer_key_can_list_models, test_admin_has_full_access, test_rate_limit_status_endpoint, test_developer_has_100_per_minute_limit, test_admin_has_unlimited_requests (+4) |
| `tests/integration/test_fusionauth_admin_flow.py` | _skip_if_unreachable, test_admin_route_requires_authentication, test_admin_route_redirects_to_oauth_sign_in, test_auth_login_page_is_publicly_accessible, test_well_known_openid_is_accessible (+3) |
| `tests/integration/test_traefik_routing.py` | is_traefik_running, traefik_available, test_protected_route_requires_oauth, test_chat_ui_requires_oauth_and_developer_role, test_mlflow_requires_oauth (+2) |
| `tests/integration/test_api_endpoints.py` | test_health_endpoint_authenticated, test_swagger_docs_authenticated, test_get_full_schema_authenticated, test_list_experiments_authenticated, test_list_models_authenticated (+1) |
| `scripts/platform/service_discovery.py` | _can_resolve, container_ip, resolve_host |
| `tests/integration/test_observability.py` | test_dozzle_requires_auth, test_homer_requires_auth |
| `tests/client/admin/conftest.py` | cleanup_test_resources, cleanup_before_and_after_tests |

## Entry Points

Start here when exploring this area:

- **`is_traefik_running`** (Function) — `tests/integration/test_traefik_routing.py:47`
- **`traefik_available`** (Function) — `tests/integration/test_traefik_routing.py:57`
- **`test_protected_route_requires_oauth`** (Function) — `tests/integration/test_traefik_routing.py:73`
- **`test_chat_ui_requires_oauth_and_developer_role`** (Function) — `tests/integration/test_traefik_routing.py:99`
- **`test_mlflow_requires_oauth`** (Function) — `tests/integration/test_traefik_routing.py:114`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `is_traefik_running` | Function | `tests/integration/test_traefik_routing.py` | 47 |
| `traefik_available` | Function | `tests/integration/test_traefik_routing.py` | 57 |
| `test_protected_route_requires_oauth` | Function | `tests/integration/test_traefik_routing.py` | 73 |
| `test_chat_ui_requires_oauth_and_developer_role` | Function | `tests/integration/test_traefik_routing.py` | 99 |
| `test_mlflow_requires_oauth` | Function | `tests/integration/test_traefik_routing.py` | 114 |
| `test_homer_dashboard_requires_oauth` | Function | `tests/integration/test_traefik_routing.py` | 179 |
| `test_viewer_cannot_access_chat` | Function | `tests/integration/test_traefik_routing.py` | 203 |
| `test_dozzle_requires_auth` | Function | `tests/integration/test_observability.py` | 40 |
| `test_homer_requires_auth` | Function | `tests/integration/test_observability.py` | 54 |
| `test_nessie_oauth_redirect` | Function | `tests/integration/test_new_services.py` | 174 |
| `test_fiftyone_oauth_redirect` | Function | `tests/integration/test_new_services.py` | 271 |
| `test_slo_exporter_no_traefik_route` | Function | `tests/integration/test_new_services.py` | 387 |
| `test_nessie_requires_developer_role` | Function | `tests/integration/test_new_services.py` | 593 |
| `test_fiftyone_requires_developer_role` | Function | `tests/integration/test_new_services.py` | 605 |
| `test_valid_developer_key_can_list_models` | Function | `tests/integration/test_chat_api_live.py` | 250 |
| `test_admin_has_full_access` | Function | `tests/integration/test_chat_api_live.py` | 319 |
| `test_rate_limit_status_endpoint` | Function | `tests/integration/test_chat_api_live.py` | 418 |
| `test_developer_has_100_per_minute_limit` | Function | `tests/integration/test_chat_api_live.py` | 433 |
| `test_admin_has_unlimited_requests` | Function | `tests/integration/test_chat_api_live.py` | 450 |
| `test_list_conversations` | Function | `tests/integration/test_chat_api_live.py` | 475 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Start_impersonation → _refill` | cross_community | 6 |
| `Cleanup_before_and_after_tests → _refill` | cross_community | 6 |
| `Start_impersonation → _generate_request_id` | cross_community | 5 |
| `Start_impersonation → _get_async_client` | cross_community | 5 |
| `Cleanup_before_and_after_tests → _generate_request_id` | cross_community | 5 |
| `Cleanup_before_and_after_tests → _get_async_client` | cross_community | 5 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Inference | 8 calls |
| Libs | 3 calls |
| Admin | 3 calls |
| Api | 1 calls |

## How to Explore

1. `gitnexus_context({name: "is_traefik_running"})` — see callers and callees
2. `gitnexus_query({query: "integration"})` — find related execution flows
3. Read key files listed above for implementation details
