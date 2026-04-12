---
name: memory
description: "Skill for the Memory area of shml-platform. 49 symbols across 5 files."
---

# Memory

49 symbols | 5 files | Cohesion: 79%

## When to Use

- Working with code in `inference/`
- Understanding how shutdown, lifespan, initialize work
- Modifying memory-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `inference/coding-model/app/memory/memory_manager.py` | MemoryManager, initialize, _load_models, _ensure_schema, close (+10) |
| `inference/coding-model/app/memory/change_staging.py` | ChangeStaging, approve_change, apply_change, revert_change, approve_and_apply_all (+8) |
| `inference/coding-model/app/memory/schemas.py` | MemoryTag, Memory, MemorySearchResult, StagedChange, ChangeSet (+7) |
| `inference/coding-model/app/main.py` | lifespan, store_conversation, approve_all_changes, stage_multiple_changes, reject_all_changes (+2) |
| `inference/coding-model/app/model_manager_simple.py` | SimpleModelManager, shutdown |

## Entry Points

Start here when exploring this area:

- **`shutdown`** (Function) — `inference/coding-model/app/model_manager_simple.py:151`
- **`lifespan`** (Function) — `inference/coding-model/app/main.py:58`
- **`initialize`** (Function) — `inference/coding-model/app/memory/memory_manager.py:97`
- **`close`** (Function) — `inference/coding-model/app/memory/memory_manager.py:1129`
- **`store_conversation`** (Function) — `inference/coding-model/app/main.py:459`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `SimpleModelManager` | Class | `inference/coding-model/app/model_manager_simple.py` | 42 |
| `MemoryManager` | Class | `inference/coding-model/app/memory/memory_manager.py` | 77 |
| `ChangeStaging` | Class | `inference/coding-model/app/memory/change_staging.py` | 24 |
| `MemoryTag` | Class | `inference/coding-model/app/memory/schemas.py` | 54 |
| `Memory` | Class | `inference/coding-model/app/memory/schemas.py` | 94 |
| `MemorySearchResult` | Class | `inference/coding-model/app/memory/schemas.py` | 224 |
| `StagedChange` | Class | `inference/coding-model/app/memory/schemas.py` | 282 |
| `ChangeSet` | Class | `inference/coding-model/app/memory/schemas.py` | 318 |
| `ChangeStatus` | Class | `inference/coding-model/app/memory/schemas.py` | 272 |
| `MemoryTagType` | Class | `inference/coding-model/app/memory/schemas.py` | 12 |
| `MemoryTier` | Class | `inference/coding-model/app/memory/schemas.py` | 34 |
| `MemoryQuery` | Class | `inference/coding-model/app/memory/schemas.py` | 196 |
| `ProjectContext` | Class | `inference/coding-model/app/memory/schemas.py` | 170 |
| `ConversationContext` | Class | `inference/coding-model/app/memory/schemas.py` | 242 |
| `MemoryChunk` | Class | `inference/coding-model/app/memory/schemas.py` | 65 |
| `MemoryConfig` | Class | `inference/coding-model/app/memory/memory_manager.py` | 35 |
| `shutdown` | Function | `inference/coding-model/app/model_manager_simple.py` | 151 |
| `lifespan` | Function | `inference/coding-model/app/main.py` | 58 |
| `initialize` | Function | `inference/coding-model/app/memory/memory_manager.py` | 97 |
| `close` | Function | `inference/coding-model/app/memory/memory_manager.py` | 1129 |

## Connected Areas

| Area | Connections |
|------|-------------|
| App | 1 calls |
| Inference | 1 calls |

## How to Explore

1. `gitnexus_context({name: "shutdown"})` — see callers and callees
2. `gitnexus_query({query: "memory"})` — find related execution flows
3. Read key files listed above for implementation details
