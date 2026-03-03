# Week 1: Benchmarking + Regression Framework (MLflow-First)

## Objective
Establish a reproducible benchmark and regression framework where datasets, baselines, and reports are sourced from and persisted to MLflow artifacts.

## Non-Negotiable Policy

- Golden datasets must be registered from MLflow run artifacts.
- Benchmark/regression comparisons must reference MLflow run IDs.
- Regression outcome artifacts must be logged to MLflow under the candidate run.
- Local disk may be used only as temporary staging during MLflow artifact copy/download.

## Implemented Components

- `ray_compute/benchmarking/models.py`
  - Core types for scenarios, results, regression rules, and outcomes.
- `ray_compute/benchmarking/mlflow_artifacts.py`
  - Golden dataset registration from MLflow artifacts.
  - Golden dataset backup into dedicated backup experiment.
  - Artifact source policy enforcement (`runs:/` or `run_id + artifact_path`).
- `ray_compute/benchmarking/regression.py`
  - Deterministic regression evaluation logic.
- `ray_compute/benchmarking/runner.py`
  - MLflow-backed benchmark execution + persisted regression outcomes.
- `scripts/week1_benchmark_framework.py`
  - CLI for registering golden datasets, creating backups, and running regression checks.
- `ray_compute/config/benchmark_regression_rules.json`
  - Initial regression rules.

## Unit Tests

- `tests/unit/ray_compute/test_benchmarking_regression.py`
- `tests/unit/ray_compute/test_mlflow_artifact_policy.py`

These validate threshold logic and MLflow-artifact-only source policy.

## Golden Dataset Lifecycle

### 1) Register Golden Dataset (from existing MLflow run artifact)

```bash
python scripts/week1_benchmark_framework.py register-golden \
  --dataset-name adas-events-v1 \
  --dataset-version 1.0.0 \
  --source-run-id <source_run_id> \
  --source-artifact-path datasets/adas_events/parquet \
  --owner data-platform \
  --purpose benchmark-regression
```

### 2) Backup Golden Dataset

```bash
python scripts/week1_benchmark_framework.py backup-golden \
  --dataset-name adas-events-v1 \
  --dataset-version 1.0.0
```

This creates a backup run in experiment `platform-golden-datasets-backups`.

## Regression Gate Workflow

### 1) Prepare Candidate and Baseline Benchmark Runs

- Run benchmark jobs and collect MLflow run IDs for baseline/candidate.
- Ensure benchmark metrics include at minimum:
  - `runtime_seconds`
  - `queue_wait_seconds`
  - `throughput_rows_per_sec`
  - `failure_rate`

### 2) Execute Regression Comparison

```bash
python scripts/week1_benchmark_framework.py compare \
  --baseline-run-id <baseline_run_id> \
  --candidate-run-id <candidate_run_id> \
  --rules-file ray_compute/config/benchmark_regression_rules.json
```

The command writes:
- Console JSON summary
- `regression/regression_outcome.json` artifact under the candidate MLflow run
- `regression.passed` tag on candidate run

## Week 1 Exit Criteria Mapping

- Baseline benchmark metrics are persisted in MLflow runs.
- Golden dataset is sourced from MLflow artifacts and versioned by name/version.
- Golden dataset has at least one verified backup run.
- Regression checks are executable and persisted as MLflow artifacts.
- Unit tests for policy and regression logic are present.
