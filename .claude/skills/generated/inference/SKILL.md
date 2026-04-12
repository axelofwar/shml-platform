---
name: inference
description: "Skill for the Inference area of shml-platform. 926 symbols across 71 files."
---

# Inference

926 symbols | 71 files | Cohesion: 77%

## When to Use

- Working with code in `tests/`
- Understanding how auth_token, test_api_route_without_auth_returns_401, test_webhook_github_endpoint_requires_signature work
- Modifying inference-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/unit/inference/test_router_tools.py` | _init_git_repo, test_valid_repo_initializes, test_non_repo_raises, test_returns_branch_name, test_clean_working_tree (+63) |
| `tests/unit/inference/test_agent_executor.py` | _resp, _FakeResp, _make_executor, test_git_unavailable_disables_branch_and_pr, test_completes_successfully_no_files (+46) |
| `tests/unit/inference/test_executor_full.py` | _make_response, _make_router, _make_plan, test_stores_router, test_default_merge_strategy (+43) |
| `tests/unit/inference/test_chatapi_database.py` | _make_conn, _make_db, _admin, _developer, test_admin_creates_key_for_anyone (+38) |
| `tests/unit/inference/test_chatapi_main.py` | _make_model_info, _client, test_health_all_available, test_health_primary_down, test_health_all_down (+35) |
| `tests/unit/inference/test_chatapi_schemas.py` | test_platform_scope, test_minimal_creation, test_full_creation, test_defaults_and_fields, test_user_message (+33) |
| `tests/unit/inference/test_utils.py` | test_request_id_generation, generate_request_id, test_user_identification, get_user_id, test_conversation_creation (+33) |
| `tests/unit/inference/test_router_base.py` | test_defaults, test_available_defaults, test_unavailable_with_error, health_check, test_estimate_cost_free_model (+32) |
| `tests/unit/inference/test_model_router.py` | test_client_initially_none, test_has_primary_and_fallback_models, test_models_initially_unavailable, test_primary_model_metadata, test_fallback_model_metadata (+32) |
| `tests/unit/inference/test_chat_api.py` | test_user_instruction_defaults, test_instruction_list, test_minimal_user, test_user_all_fields, test_invalid_auth_method_rejected (+28) |

## Entry Points

Start here when exploring this area:

- **`auth_token`** (Function) — `tests/conftest.py:50`
- **`test_api_route_without_auth_returns_401`** (Function) — `tests/integration/test_traefik_routing.py:137`
- **`test_webhook_github_endpoint_requires_signature`** (Function) — `tests/integration/test_observability.py:127`
- **`test_nessie_branch_crud`** (Function) — `tests/integration/test_new_services.py:205`
- **`test_fiftyone_api_health`** (Function) — `tests/integration/test_new_services.py:304`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `MergeStrategy` | Class | `inference/router/executor.py` | 31 |
| `Subtask` | Class | `inference/router/executor.py` | 41 |
| `ExecutionPlan` | Class | `inference/router/executor.py` | 67 |
| `MergeResult` | Class | `inference/router/executor.py` | 91 |
| `ParallelExecutor` | Class | `inference/router/executor.py` | 102 |
| `TaskPlanner` | Class | `inference/router/executor.py` | 523 |
| `UserRole` | Class | `inference/chat-api/app/schemas.py` | 13 |
| `InstructionScope` | Class | `inference/chat-api/app/schemas.py` | 76 |
| `UserInstruction` | Class | `inference/chat-api/app/schemas.py` | 81 |
| `InstructionList` | Class | `inference/chat-api/app/schemas.py` | 105 |
| `ChatMessage` | Class | `inference/chat-api/app/schemas.py` | 150 |
| `Conversation` | Class | `inference/chat-api/app/schemas.py` | 218 |
| `ConversationSummary` | Class | `inference/chat-api/app/schemas.py` | 231 |
| `RouterConfig` | Class | `inference/router/router.py` | 50 |
| `ModelRouter` | Class | `inference/router/router.py` | 103 |
| `CompletionRequest` | Class | `inference/router/base.py` | 68 |
| `ProviderStatus` | Class | `inference/router/base.py` | 102 |
| `CompletionResponse` | Class | `inference/router/base.py` | 85 |
| `ProviderError` | Class | `inference/router/base.py` | 160 |
| `RateLimitError` | Class | `inference/router/base.py` | 169 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Initialize → _generate_request_id` | cross_community | 8 |
| `Initialize → _get_async_client` | cross_community | 8 |
| `Run → _generate_request_id` | cross_community | 7 |
| `Openai_chat_completions → _generate_request_id` | cross_community | 7 |
| `Openai_chat_completions → _get_async_client` | cross_community | 7 |
| `Main → Encode_special` | cross_community | 6 |
| `Main → FiftyOneError` | cross_community | 6 |
| `Execute_agent → Encode_special` | cross_community | 6 |
| `Wrapper → _generate_request_id` | cross_community | 6 |
| `Wrapper → _get_async_client` | cross_community | 6 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Libs | 31 calls |
| Ray_compute | 11 calls |
| Chat-api | 9 calls |
| App | 9 calls |
| Tools | 9 calls |
| Shml | 6 calls |
| Face | 5 calls |
| Integrations | 3 calls |

## How to Explore

1. `gitnexus_context({name: "auth_token"})` — see callers and callees
2. `gitnexus_query({query: "inference"})` — find related execution flows
3. Read key files listed above for implementation details
