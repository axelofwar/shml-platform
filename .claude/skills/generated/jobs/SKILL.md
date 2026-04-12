---
name: jobs
description: "Skill for the Jobs area of shml-platform. 96 symbols across 9 files."
---

# Jobs

96 symbols | 9 files | Cohesion: 69%

## When to Use

- Working with code in `libs/`
- Understanding how publish_event, release, cleanup work
- Modifying jobs-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `libs/training/jobs/autoresearch_face.py` | publish_event, GpuOrchestrator, _wait_llm_ready, release, cleanup (+22) |
| `libs/training/jobs/train_phase10_multiscale.py` | TrainingMetrics, nessie_create_branch, nessie_tag_model, ResourceTelemetryLogger, start (+16) |
| `libs/training/jobs/train_rfdetr_face.py` | _cleanup_on_failure, ensure_coco_annotations, _inline_yolo_to_coco, nessie_create_branch, MetricsReporter (+10) |
| `libs/training/jobs/train_phase9_finetune.py` | GradientClipCallback, register, TrainingMetrics, nessie_create_branch, nessie_tag_model (+5) |
| `libs/training/jobs/train_yolov8l_p2_face.py` | TrainingMetrics, nessie_create_branch, nessie_tag_model, Phase6BCallbacks, register (+5) |
| `ray_compute/web_ui/src/app/jobs/page.tsx` | JobsPage, fetchJobs, handleJobAction, toggleJobExpansion, loadJobLogs (+2) |
| `ray_compute/jobs/utils/gpu_yield.py` | _restore_host_llm, _atexit_reclaim, reclaim_gpu_after_training, __exit__ |
| `inference/shl-nano-server/shl_nano_server.py` | _check_vram |
| `tests/unit/libs/test_training_hardware.py` | mem_get_info |

## Entry Points

Start here when exploring this area:

- **`publish_event`** (Function) — `libs/training/jobs/autoresearch_face.py:134`
- **`release`** (Function) — `libs/training/jobs/autoresearch_face.py:269`
- **`cleanup`** (Function) — `libs/training/jobs/autoresearch_face.py:294`
- **`delta_vs`** (Function) — `libs/training/jobs/autoresearch_face.py:568`
- **`llm_propose_mutation`** (Function) — `libs/training/jobs/autoresearch_face.py:718`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `GpuOrchestrator` | Class | `libs/training/jobs/autoresearch_face.py` | 154 |
| `GradientClipCallback` | Class | `libs/training/jobs/train_phase9_finetune.py` | 201 |
| `TrainingMetrics` | Class | `libs/training/jobs/train_phase9_finetune.py` | 247 |
| `Phase9Callbacks` | Class | `libs/training/jobs/train_phase9_finetune.py` | 348 |
| `TrainingMetrics` | Class | `libs/training/jobs/train_yolov8l_p2_face.py` | 254 |
| `Phase6BCallbacks` | Class | `libs/training/jobs/train_yolov8l_p2_face.py` | 360 |
| `TrainingMetrics` | Class | `libs/training/jobs/train_phase10_multiscale.py` | 352 |
| `ResourceTelemetryLogger` | Class | `libs/training/jobs/train_phase10_multiscale.py` | 581 |
| `MetricsReporter` | Class | `libs/training/jobs/train_rfdetr_face.py` | 426 |
| `ExperimentResult` | Class | `libs/training/jobs/autoresearch_face.py` | 555 |
| `EpochWatcher` | Class | `libs/training/jobs/autoresearch_face.py` | 597 |
| `GradientClipCallback` | Class | `libs/training/jobs/train_phase10_multiscale.py` | 310 |
| `Phase10Callbacks` | Class | `libs/training/jobs/train_phase10_multiscale.py` | 456 |
| `publish_event` | Function | `libs/training/jobs/autoresearch_face.py` | 134 |
| `release` | Function | `libs/training/jobs/autoresearch_face.py` | 269 |
| `cleanup` | Function | `libs/training/jobs/autoresearch_face.py` | 294 |
| `delta_vs` | Function | `libs/training/jobs/autoresearch_face.py` | 568 |
| `llm_propose_mutation` | Function | `libs/training/jobs/autoresearch_face.py` | 718 |
| `evaluate_result` | Function | `libs/training/jobs/autoresearch_face.py` | 1052 |
| `write_journal` | Function | `libs/training/jobs/autoresearch_face.py` | 1118 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `JobsPage → AddToRemoveQueue` | cross_community | 8 |
| `Main → _load_env_file_cache` | cross_community | 6 |
| `Main → Resolve_gitlab_base_url` | cross_community | 6 |
| `Main → Encode_special` | cross_community | 6 |
| `Train → _refill` | cross_community | 6 |
| `Train → _refill` | cross_community | 6 |
| `Train → _refill` | cross_community | 6 |
| `Train_rfdetr_face → _refill` | cross_community | 6 |
| `JobsPage → GenId` | cross_community | 5 |
| `Train → _generate_request_id` | cross_community | 5 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Integrations | 24 calls |
| Inference | 10 calls |
| Benchmarking | 6 calls |
| Unit | 4 calls |
| Hooks | 4 calls |
| Platform | 2 calls |
| Api | 1 calls |
| Face | 1 calls |

## How to Explore

1. `gitnexus_context({name: "publish_event"})` — see callers and callees
2. `gitnexus_query({query: "jobs"})` — find related execution flows
3. Read key files listed above for implementation details
