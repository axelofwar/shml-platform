---
name: unit
description: "Skill for the Unit area of shml-platform. 68 symbols across 13 files."
---

# Unit

68 symbols | 13 files | Cohesion: 90%

## When to Use

- Working with code in `tests/`
- Understanding how test_auth_router_is_public, test_admin_router_requires_full_auth_chain, test_admin_router_targets_fusionauth_service work
- Modifying unit-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/test_auth_compose_contract.py` | _label_dict, test_auth_router_is_public, test_admin_router_requires_full_auth_chain, test_admin_router_targets_fusionauth_service, test_api_and_oauth_routes_exist (+11) |
| `tests/unit/test_security_hardening.py` | read_compose, test_no_raw_docker_socket_mounts, test_dev_mode_not_enabled, test_fusionauth_admin_protected, test_fusionauth_localhost_binding (+10) |
| `tests/unit/test_platform_wiring.py` | test_mlflow_dashboard_valid_json, _read, compose_paths, env_example_content, taskfile_content (+4) |
| `tests/unit/test_copilot_suggestions.py` | get_project_root, server_v2_path, entrypoint_path, test_traefik_auth_assumption, funnel_service_path (+2) |
| `tests/unit/test_infra_compose_contract.py` | _label_dict, test_dashboard_router_requires_admin_auth, test_auth_router_labels_are_present, test_admin_router_requires_platform_admin, test_api_and_oauth_routes_are_explicitly_declared (+2) |
| `tests/unit/test_auth_notifications.py` | hooks, test_hooks_json_valid, webhook_config |
| `tests/unit/test_monitoring_config.py` | load_yaml, cfg, alert_file |
| `scripts/platform/gitlab_board_updater.py` | get_evidence, main |
| `libs/training/shml_training/core/checkpoint_manager.py` | load_best, load_epoch |
| `tests/unit/ray_compute/test_feature_platform.py` | dashboard |

## Entry Points

Start here when exploring this area:

- **`test_auth_router_is_public`** (Function) — `tests/unit/test_auth_compose_contract.py:56`
- **`test_admin_router_requires_full_auth_chain`** (Function) — `tests/unit/test_auth_compose_contract.py:62`
- **`test_admin_router_targets_fusionauth_service`** (Function) — `tests/unit/test_auth_compose_contract.py:70`
- **`test_api_and_oauth_routes_exist`** (Function) — `tests/unit/test_auth_compose_contract.py:74`
- **`test_rewrite_middleware_strips_auth_prefix`** (Function) — `tests/unit/test_auth_compose_contract.py:81`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_auth_router_is_public` | Function | `tests/unit/test_auth_compose_contract.py` | 56 |
| `test_admin_router_requires_full_auth_chain` | Function | `tests/unit/test_auth_compose_contract.py` | 62 |
| `test_admin_router_targets_fusionauth_service` | Function | `tests/unit/test_auth_compose_contract.py` | 70 |
| `test_api_and_oauth_routes_exist` | Function | `tests/unit/test_auth_compose_contract.py` | 74 |
| `test_rewrite_middleware_strips_auth_prefix` | Function | `tests/unit/test_auth_compose_contract.py` | 81 |
| `test_loadbalancer_port_matches_admin_port` | Function | `tests/unit/test_auth_compose_contract.py` | 86 |
| `test_forward_auth_middleware_defined` | Function | `tests/unit/test_auth_compose_contract.py` | 100 |
| `test_forward_auth_trusts_headers` | Function | `tests/unit/test_auth_compose_contract.py` | 105 |
| `test_error_middleware_redirects_to_sign_in` | Function | `tests/unit/test_auth_compose_contract.py` | 109 |
| `test_rbac_middlewares_defined` | Function | `tests/unit/test_auth_compose_contract.py` | 114 |
| `test_proxy_router_priority_is_high` | Function | `tests/unit/test_auth_compose_contract.py` | 130 |
| `test_admin_routes_always_require_oauth_and_role_check` | Function | `tests/unit/test_auth_compose_contract.py` | 147 |
| `test_public_auth_route_has_no_oauth_middleware` | Function | `tests/unit/test_auth_compose_contract.py` | 155 |
| `test_mlflow_dashboard_valid_json` | Function | `tests/unit/test_platform_wiring.py` | 225 |
| `hooks` | Function | `tests/unit/test_auth_notifications.py` | 31 |
| `test_hooks_json_valid` | Function | `tests/unit/test_auth_notifications.py` | 75 |
| `webhook_config` | Function | `tests/unit/test_auth_notifications.py` | 179 |
| `get_evidence` | Function | `scripts/platform/gitlab_board_updater.py` | 68 |
| `main` | Function | `scripts/platform/gitlab_board_updater.py` | 81 |
| `dashboard` | Function | `tests/unit/ray_compute/test_feature_platform.py` | 589 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Train → EvalDataset` | cross_community | 4 |
| `Train_rfdetr_face → EvalDataset` | cross_community | 4 |
| `Get_training_status → EvalDataset` | cross_community | 4 |
| `Main → EvalDataset` | cross_community | 3 |
| `Main → EvalDataset` | cross_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Platform | 1 calls |
| Skills | 1 calls |

## How to Explore

1. `gitnexus_context({name: "test_auth_router_is_public"})` — see callers and callees
2. `gitnexus_query({query: "unit"})` — find related execution flows
3. Read key files listed above for implementation details
