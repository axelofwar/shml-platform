---
name: chat-api
description: "Skill for the Chat-api area of shml-platform. 60 symbols across 11 files."
---

# Chat-api

60 symbols | 11 files | Cohesion: 72%

## When to Use

- Working with code in `tests/`
- Understanding how test_developer_rate_limit_100_per_minute, test_developer_exceeds_rate_limit, test_admin_unlimited_requests work
- Modifying chat-api-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/chat-api/test_security_config.py` | load_compose, test_chat_api_direct_route_exists, test_coding_model_primary_requires_oauth, test_coding_model_fallback_requires_oauth, test_rate_limits_configured (+13) |
| `tests/chat-api/test_auth.py` | test_no_auth_returns_401, test_invalid_api_key_returns_401, test_valid_api_key_returns_user, test_oauth_headers_developer_role, test_oauth_headers_admin_role (+7) |
| `tests/unit/inference/test_chat_api.py` | test_limits_dict_has_all_roles, test_check_admin_bypasses_redis, test_check_developer_under_limit, test_check_viewer_at_limit, test_record_admin_always_true (+3) |
| `tests/chat-api/test_rate_limit.py` | test_developer_rate_limit_100_per_minute, test_developer_exceeds_rate_limit, test_admin_unlimited_requests, test_viewer_rate_limit_20_per_minute, test_viewer_exceeds_rate_limit (+2) |
| `tests/unit/inference/test_chatapi_auth.py` | DummyRequest, test_get_current_user_api_key_success, test_get_current_user_api_key_invalid_raises_401, test_get_current_user_oauth_headers_map_roles, test_get_current_user_requires_auth_when_missing (+1) |
| `inference/chat-api/app/auth.py` | get_current_user, require_developer_or_admin, require_admin |
| `tests/chat-api/test_ask_only_mode.py` | test_web_request_includes_ask_only_prompt, test_api_request_does_not_include_ask_only_prompt |
| `inference/gateway/app/rate_limit.py` | RateLimiter |
| `inference/chat-api/app/schemas.py` | User |
| `inference/router/base.py` | ModelInfo |

## Entry Points

Start here when exploring this area:

- **`test_developer_rate_limit_100_per_minute`** (Function) — `tests/chat-api/test_rate_limit.py:11`
- **`test_developer_exceeds_rate_limit`** (Function) — `tests/chat-api/test_rate_limit.py:30`
- **`test_admin_unlimited_requests`** (Function) — `tests/chat-api/test_rate_limit.py:47`
- **`test_viewer_rate_limit_20_per_minute`** (Function) — `tests/chat-api/test_rate_limit.py:64`
- **`test_viewer_exceeds_rate_limit`** (Function) — `tests/chat-api/test_rate_limit.py:83`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `RateLimiter` | Class | `inference/gateway/app/rate_limit.py` | 20 |
| `DummyRequest` | Class | `tests/unit/inference/test_chatapi_auth.py` | 20 |
| `User` | Class | `inference/chat-api/app/schemas.py` | 19 |
| `ModelInfo` | Class | `inference/router/base.py` | 32 |
| `test_developer_rate_limit_100_per_minute` | Function | `tests/chat-api/test_rate_limit.py` | 11 |
| `test_developer_exceeds_rate_limit` | Function | `tests/chat-api/test_rate_limit.py` | 30 |
| `test_admin_unlimited_requests` | Function | `tests/chat-api/test_rate_limit.py` | 47 |
| `test_viewer_rate_limit_20_per_minute` | Function | `tests/chat-api/test_rate_limit.py` | 64 |
| `test_viewer_exceeds_rate_limit` | Function | `tests/chat-api/test_rate_limit.py` | 83 |
| `test_rate_limit_check_returns_status` | Function | `tests/chat-api/test_rate_limit.py` | 100 |
| `test_api_key_inherits_role_limit` | Function | `tests/chat-api/test_rate_limit.py` | 137 |
| `test_limits_dict_has_all_roles` | Function | `tests/unit/inference/test_chat_api.py` | 417 |
| `test_check_admin_bypasses_redis` | Function | `tests/unit/inference/test_chat_api.py` | 427 |
| `test_check_developer_under_limit` | Function | `tests/unit/inference/test_chat_api.py` | 437 |
| `test_check_viewer_at_limit` | Function | `tests/unit/inference/test_chat_api.py` | 450 |
| `test_record_admin_always_true` | Function | `tests/unit/inference/test_chat_api.py` | 462 |
| `test_record_developer_allowed_adds_entry` | Function | `tests/unit/inference/test_chat_api.py` | 467 |
| `test_record_viewer_blocked_at_limit` | Function | `tests/unit/inference/test_chat_api.py` | 482 |
| `test_no_auth_returns_401` | Function | `tests/chat-api/test_auth.py` | 12 |
| `test_invalid_api_key_returns_401` | Function | `tests/chat-api/test_auth.py` | 34 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Inference | 9 calls |
| Libs | 8 calls |
| App | 2 calls |

## How to Explore

1. `gitnexus_context({name: "test_developer_rate_limit_100_per_minute"})` — see callers and callees
2. `gitnexus_query({query: "chat-api"})` — find related execution flows
3. Read key files listed above for implementation details
