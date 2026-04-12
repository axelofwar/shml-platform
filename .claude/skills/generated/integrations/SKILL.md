---
name: integrations
description: "Skill for the Integrations area of shml-platform. 119 symbols across 34 files."
---

# Integrations

119 symbols | 34 files | Cohesion: 73%

## When to Use

- Working with code in `sdk/`
- Understanding how register_base_model, main, replay_to_remote work
- Modifying integrations-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `sdk/shml/integrations/fiftyone.py` | _require, healthy, list_datasets, create_dataset, load_dataset (+10) |
| `sdk/shml/integrations/prometheus.py` | report_training_end, _get_gauge, report_metric, report_metrics, report_epoch (+4) |
| `sdk/shml/integrations/mlflow.py` | _import_mlflow, setup_experiment, log_params, log_metric, log_metrics (+4) |
| `sdk/shml/integrations/nessie.py` | get_main_hash, create_branch, create_tag, list_branches, list_tags (+3) |
| `sdk/shml/integrations/features.py` | log_features, get_features, log_model_metrics, log_dataset_stats, FeatureClient (+2) |
| `sdk/shml/exceptions.py` | MLflowError, FiftyOneError, NessieError, IntegrationError, FeatureStoreError |
| `libs/training/shml_training/integrations/progress.py` | AGUIEvent, to_dict, to_json, to_sse, _sender_loop |
| `libs/training/shml_training/integrations/ray.py` | RayJobConfig, submit_ray_job, __init__, _configure_resources, train |
| `ray_compute/jobs/inference/rfdetr_inference_baseline.py` | nessie_create_branch, nessie_tag, run_baseline, main |
| `libs/training/shml_training/integrations/mlflow_utils.py` | start_training_run, log_epoch_metrics, end_run, auto_promote_if_qualified |

## Entry Points

Start here when exploring this area:

- **`register_base_model`** (Function) — `scripts/registry/register_base_models.py:85`
- **`main`** (Function) — `scripts/registry/register_base_models.py:142`
- **`replay_to_remote`** (Function) — `scripts/benchmarking/replay_baselines_to_remote.py:80`
- **`start_run`** (Function) — `ray_compute/api/mlflow_integration.py:69`
- **`get_file_hash`** (Function) — `mlflow-server/scripts/register_model_versions.py:84`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `MLflowError` | Class | `sdk/shml/exceptions.py` | 164 |
| `FiftyOneError` | Class | `sdk/shml/exceptions.py` | 174 |
| `NessieError` | Class | `sdk/shml/exceptions.py` | 169 |
| `AGUIEvent` | Class | `libs/training/shml_training/integrations/progress.py` | 50 |
| `IntegrationError` | Class | `sdk/shml/exceptions.py` | 153 |
| `FeatureStoreError` | Class | `sdk/shml/exceptions.py` | 179 |
| `RayJobConfig` | Class | `libs/training/shml_training/integrations/ray.py` | 37 |
| `FeatureClient` | Class | `sdk/shml/integrations/features.py` | 17 |
| `register_base_model` | Function | `scripts/registry/register_base_models.py` | 85 |
| `main` | Function | `scripts/registry/register_base_models.py` | 142 |
| `replay_to_remote` | Function | `scripts/benchmarking/replay_baselines_to_remote.py` | 80 |
| `start_run` | Function | `ray_compute/api/mlflow_integration.py` | 69 |
| `get_file_hash` | Function | `mlflow-server/scripts/register_model_versions.py` | 84 |
| `register_model_version` | Function | `mlflow-server/scripts/register_model_versions.py` | 93 |
| `main` | Function | `mlflow-server/scripts/register_model_versions.py` | 197 |
| `register_yolo_model` | Function | `mlflow-server/scripts/register_model.py` | 26 |
| `main` | Function | `mlflow-server/scripts/register_model.py` | 249 |
| `register_model` | Function | `mlflow-server/scripts/register_historical_models.py` | 58 |
| `main` | Function | `mlflow-server/scripts/register_historical_models.py` | 118 |
| `train_model_with_clean_artifacts` | Function | `mlflow-server/scripts/example_clean_artifacts.py` | 12 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Run → _generate_request_id` | cross_community | 7 |
| `Main → FiftyOneError` | cross_community | 6 |
| `Run → NessieError` | cross_community | 6 |
| `Run → MLflowError` | cross_community | 6 |
| `Wrapper → MLflowError` | cross_community | 6 |
| `Train → MLflowError` | cross_community | 6 |
| `Run_baseline → _refill` | cross_community | 6 |
| `Main → MLflowError` | cross_community | 6 |
| `Ray_train_wrapper → AGUIEvent` | cross_community | 5 |
| `On_train_end → MLflowError` | cross_community | 5 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Inference | 6 calls |
| Face | 6 calls |
| Api | 4 calls |
| Llm | 2 calls |
| Libs | 2 calls |
| Ray_compute | 1 calls |
| Admin | 1 calls |
| Unit | 1 calls |

## How to Explore

1. `gitnexus_context({name: "register_base_model"})` — see callers and callees
2. `gitnexus_query({query: "integrations"})` — find related execution flows
3. Read key files listed above for implementation details
