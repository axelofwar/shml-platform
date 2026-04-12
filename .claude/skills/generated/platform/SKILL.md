---
name: platform
description: "Skill for the Platform area of shml-platform. 55 symbols across 3 files."
---

# Platform

55 symbols | 3 files | Cohesion: 98%

## When to Use

- Working with code in `scripts/`
- Understanding how resolve_gitlab_base_url, list_issues, get_issue work
- Modifying platform-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `scripts/platform/gitlab_utils.py` | _load_env_file_cache, _env, _base_url, _project_id, _token (+38) |
| `scripts/platform/gitlab_setup.py` | _sprint_milestones, _existing_labels, _existing_milestones, _existing_boards, _board_list_labels (+6) |
| `scripts/platform/service_discovery.py` | resolve_gitlab_base_url |

## Entry Points

Start here when exploring this area:

- **`resolve_gitlab_base_url`** (Function) — `scripts/platform/service_discovery.py:56`
- **`list_issues`** (Function) — `scripts/platform/gitlab_utils.py:174`
- **`get_issue`** (Function) — `scripts/platform/gitlab_utils.py:192`
- **`create_issue`** (Function) — `scripts/platform/gitlab_utils.py:199`
- **`close_issue`** (Function) — `scripts/platform/gitlab_utils.py:222`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `resolve_gitlab_base_url` | Function | `scripts/platform/service_discovery.py` | 56 |
| `list_issues` | Function | `scripts/platform/gitlab_utils.py` | 174 |
| `get_issue` | Function | `scripts/platform/gitlab_utils.py` | 192 |
| `create_issue` | Function | `scripts/platform/gitlab_utils.py` | 199 |
| `close_issue` | Function | `scripts/platform/gitlab_utils.py` | 222 |
| `reopen_issue` | Function | `scripts/platform/gitlab_utils.py` | 229 |
| `add_issue_comment` | Function | `scripts/platform/gitlab_utils.py` | 236 |
| `update_issue` | Function | `scripts/platform/gitlab_utils.py` | 242 |
| `update_issue_labels` | Function | `scripts/platform/gitlab_utils.py` | 268 |
| `upsert_issue` | Function | `scripts/platform/gitlab_utils.py` | 279 |
| `resolve_issue` | Function | `scripts/platform/gitlab_utils.py` | 344 |
| `sync_issue` | Function | `scripts/platform/gitlab_utils.py` | 380 |
| `list_labels` | Function | `scripts/platform/gitlab_utils.py` | 448 |
| `ensure_label` | Function | `scripts/platform/gitlab_utils.py` | 454 |
| `list_milestones` | Function | `scripts/platform/gitlab_utils.py` | 476 |
| `ensure_milestone` | Function | `scripts/platform/gitlab_utils.py` | 486 |
| `list_boards` | Function | `scripts/platform/gitlab_utils.py` | 501 |
| `ensure_board` | Function | `scripts/platform/gitlab_utils.py` | 507 |
| `list_board_lists` | Function | `scripts/platform/gitlab_utils.py` | 518 |
| `ensure_board_list` | Function | `scripts/platform/gitlab_utils.py` | 524 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → _load_env_file_cache` | cross_community | 6 |
| `Main → Resolve_gitlab_base_url` | cross_community | 6 |
| `Main → Encode_special` | cross_community | 6 |
| `Main → _load_env_file_cache` | intra_community | 6 |
| `Main → Resolve_gitlab_base_url` | intra_community | 6 |
| `Main → Encode_special` | cross_community | 6 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Inference | 1 calls |

## How to Explore

1. `gitnexus_context({name: "resolve_gitlab_base_url"})` — see callers and callees
2. `gitnexus_query({query: "platform"})` — find related execution flows
3. Read key files listed above for implementation details
