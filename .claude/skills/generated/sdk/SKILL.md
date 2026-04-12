---
name: sdk
description: "Skill for the Sdk area of shml-platform. 43 symbols across 5 files."
---

# Sdk

43 symbols | 5 files | Cohesion: 69%

## When to Use

- Working with code in `libs/`
- Understanding how example_list_resources, get_job_logs, cancel_job work
- Modifying sdk-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `libs/training/shml_training/sdk/client.py` | SDKError, AuthError, APIError, __init__, JobError (+20) |
| `libs/training/shml_training/sdk/examples.py` | example_list_resources, example_quota_management, example_production_pipeline, example_advanced_training, example_batch_training (+6) |
| `libs/training/shml_training/sdk/cli.py` | cmd_techniques, cmd_quota, cmd_setup, cmd_submit, cmd_queue |
| `tests/unit/libs/test_training.py` | test_quota_returns_dict |
| `tests/test_sdk_integration.py` | test_credentials_file |

## Entry Points

Start here when exploring this area:

- **`example_list_resources`** (Function) — `libs/training/shml_training/sdk/examples.py:354`
- **`get_job_logs`** (Function) — `libs/training/shml_training/sdk/client.py:408`
- **`cancel_job`** (Function) — `libs/training/shml_training/sdk/client.py:426`
- **`get_queue_overview`** (Function) — `libs/training/shml_training/sdk/client.py:481`
- **`list_techniques`** (Function) — `libs/training/shml_training/sdk/client.py:527`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `SDKError` | Class | `libs/training/shml_training/sdk/client.py` | 199 |
| `AuthError` | Class | `libs/training/shml_training/sdk/client.py` | 205 |
| `APIError` | Class | `libs/training/shml_training/sdk/client.py` | 211 |
| `JobError` | Class | `libs/training/shml_training/sdk/client.py` | 225 |
| `QuotaError` | Class | `libs/training/shml_training/sdk/client.py` | 231 |
| `QuotaInfo` | Class | `libs/training/shml_training/sdk/client.py` | 175 |
| `TrainingConfig` | Class | `libs/training/shml_training/sdk/client.py` | 27 |
| `QueueStatus` | Class | `libs/training/shml_training/sdk/client.py` | 162 |
| `JobStatus` | Class | `libs/training/shml_training/sdk/client.py` | 120 |
| `example_list_resources` | Function | `libs/training/shml_training/sdk/examples.py` | 354 |
| `get_job_logs` | Function | `libs/training/shml_training/sdk/client.py` | 408 |
| `cancel_job` | Function | `libs/training/shml_training/sdk/client.py` | 426 |
| `get_queue_overview` | Function | `libs/training/shml_training/sdk/client.py` | 481 |
| `list_techniques` | Function | `libs/training/shml_training/sdk/client.py` | 527 |
| `list_tiers` | Function | `libs/training/shml_training/sdk/client.py` | 533 |
| `cmd_techniques` | Function | `libs/training/shml_training/sdk/cli.py` | 254 |
| `test_quota_returns_dict` | Function | `tests/unit/libs/test_training.py` | 436 |
| `example_quota_management` | Function | `libs/training/shml_training/sdk/examples.py` | 207 |
| `example_production_pipeline` | Function | `libs/training/shml_training/sdk/examples.py` | 383 |
| `get_quota` | Function | `libs/training/shml_training/sdk/client.py` | 489 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Libs | 2 calls |
| Tests | 2 calls |
| Unit | 2 calls |

## How to Explore

1. `gitnexus_context({name: "example_list_resources"})` — see callers and callees
2. `gitnexus_query({query: "sdk"})` — find related execution flows
3. Read key files listed above for implementation details
