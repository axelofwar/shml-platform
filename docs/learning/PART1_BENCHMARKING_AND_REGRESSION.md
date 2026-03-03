# Part 1: Benchmarking, Regression Gates & MLflow Governance

*Execution Board Item: EB-01 — Baseline Benchmark Harness*

---

## Why This Matters

Before you can optimize anything, you need to measure it. Before you can compare two engines (Ray vs Spark), you need a contract for what "better" means. Before you can claim a 20% throughput improvement in an interview, you need a regression framework that proves it.

This is the difference between "I made it faster" (junior) and "I established a measurement framework with regression gates, ran controlled experiments across three workload sizes with three repetitions each, and quantified improvement with statistical confidence" (senior).

**Tecton relevance:** Tecton's batch platform processes features at scale. When you change a Spark config, add a partition strategy, or migrate a table format, you need to know — with numbers — whether the change helped or hurt. The ability to design and operate a regression framework is a foundational senior skill.

---

## Core Concepts

### 1. The Benchmark Contract

A benchmark is only meaningful if it measures the same things every time. Our contract defines four metrics:

| Metric | Direction | What It Measures |
|--------|-----------|------------------|
| `runtime_seconds` | Lower is better | Wall-clock execution time |
| `queue_wait_seconds` | Lower is better | Time between job submission and first task start |
| `throughput_rows_per_sec` | Higher is better | Processing speed normalized by data volume |
| `failure_rate` | Lower is better | Fraction of tasks that failed and required retry |

**Why these four?**
- **Runtime** is the user-visible metric — how long until results are ready
- **Queue wait** isolates scheduler overhead from compute work — critical for understanding whether your bottleneck is in scheduling or processing
- **Throughput** normalizes across dataset sizes — a job that takes 600s on 5M rows vs 150s on 1M rows needs a common unit
- **Failure rate** captures reliability — a fast but flaky pipeline is worse than a slower stable one

> **Interview angle:** "We chose directional metrics with explicit thresholds rather than simple before/after comparisons because regression can be subtle — a 5% throughput drop is acceptable noise, but a 12% drop signals a real problem. The regression framework makes this judgment automated and auditable."

### 2. Workload Sizing (S/M/L)

We run every benchmark at three sizes:

| Size | Row Count | Purpose |
|------|-----------|---------|
| S (10K) | Small | Fast iteration, catches obvious regressions in seconds |
| M (100K) | Medium | Realistic production fraction, primary regression gate |
| L (500K+) | Large | Stress test, reveals non-linear scaling issues |

**Why three sizes?** Because bottlenecks are size-dependent:
- At S-size, everything is fast — you're mostly measuring overhead (startup, connection setup, serialization)
- At M-size, you see the steady-state behavior of your processing pipeline
- At L-size, you expose resource contention, memory pressure, and scheduler saturation

> **Your platform evidence (Week 1 results):**
> | Size | Queue Wait (s) | Throughput (rows/s) |
> |------|---------------|---------------------|
> | S    | 2.77          | 2,582               |
> | M    | 8.42          | 6,836               |
> | L    | 22.81         | 8,220               |
>
> Notice: Queue wait grows **8x** from S→L (non-linear), while throughput only grows **3.2x**. This means the scheduler becomes a proportionally larger bottleneck at scale. This is the kind of insight that only emerges from multi-size benchmarking.

### 3. Repetition and Statistical Noise

Every workload size runs **3 times**. This is the minimum for detecting noise vs real signal.

If run 1 takes 145s and run 2 takes 148s, is that a 2% regression? Probably not — it's measurement noise. But if all three runs cluster around 145s (baseline) vs all three around 165s (candidate), the ~14% difference is statistically meaningful.

**In production feature platforms:** batch jobs that run on schedules (hourly, daily) need to account for variability. A feature freshness SLO of "features updated within 30 minutes" must account for worst-case execution, not average.

### 4. The Golden Dataset Pattern

A benchmark is only reproducible if run against the same data. We solve this with a "golden dataset" — a versioned, checksummed snapshot registered in MLflow:

```python
@dataclass
class GoldenDatasetRef:
    name: str           # e.g. "adas-events-v1"
    version: str        # e.g. "1.0.0"
    source_run_id: str  # MLflow run that produced it
    sha256: str         # Content checksum for integrity
    size_bytes: int     # For detecting truncation
```

**Key design decisions:**
1. **Artifacts are always sourced from MLflow runs** — never from arbitrary local paths. This ensures provenance (you can always trace a dataset back to the run that created it).
2. **SHA-256 checksums** verify integrity — if someone accidentally modifies the dataset, the benchmark will catch it before producing misleading results.
3. **Versioning** allows side-by-side comparison — v1.0.0 results are only comparable to other v1.0.0 results.

> **Interview angle:** "The golden dataset pattern is the data equivalent of reproducible builds. Just as you pin dependency versions to get deterministic software builds, you pin dataset versions to get deterministic benchmark results."

---

## The Regression Framework (Deep Dive)

### How Rules Work

Each rule defines a metric, which direction is "good," and how much regression is tolerable:

```json
[
  {"metric": "runtime_seconds",        "direction": "lower_is_better",  "max_regression_pct": 10, "required": true},
  {"metric": "queue_wait_seconds",     "direction": "lower_is_better",  "max_regression_pct": 15, "required": true},
  {"metric": "throughput_rows_per_sec", "direction": "higher_is_better", "max_regression_pct": 8,  "required": true},
  {"metric": "failure_rate",           "direction": "lower_is_better",  "max_regression_pct": 5,  "required": true}
]
```

**Why different thresholds?**
- **Runtime (10%):** Tightest threshold. Users notice when jobs take longer. A 10% slowdown on a 10-minute job adds a full minute — that compounds across hundreds of daily runs.
- **Queue wait (15%):** Slightly looser. Queue wait is influenced by cluster load, which varies. 15% tolerance absorbs normal cluster-state variance.
- **Throughput (8%):** Tighter than queue wait because throughput measures the efficiency of your code/engine, not the cluster. An 8% throughput drop usually indicates a real regression in processing logic.
- **Failure rate (5%):** Tightest effective threshold because failure rates are already low (<2%). A 5% relative increase from 1.0% to 1.05% is negligible, but from 1.0% to 5.0% would be caught.

### The Evaluation Algorithm

```python
def evaluate_regression(baseline_metrics, candidate_metrics, rules):
    for rule in rules:
        if rule.direction == LOWER_IS_BETTER:
            # Candidate larger = regression (bad)
            regression_pct = ((candidate - baseline) / baseline) * 100
        else:
            # Candidate smaller = regression (bad)
            regression_pct = ((baseline - candidate) / baseline) * 100

        if regression_pct > rule.max_regression_pct:
            failures.append(f"'{metric}' regressed by {regression_pct:.2f}%")
```

**Subtlety:** The direction matters. For `runtime_seconds` (lower is better), candidate=160s vs baseline=145s gives +10.3% regression — bad. For `throughput_rows_per_sec` (higher is better), candidate=6200 vs baseline=6836 gives +9.3% regression — also bad. The formula flips so that "regression" always means "got worse," regardless of which direction is better.

### MLflow as the System of Record

Every benchmark run creates an MLflow run with:
- **Params:** benchmark_id, dataset_name, dataset_version, engine, workload_name
- **Metrics:** runtime_seconds, queue_wait_seconds, throughput_rows_per_sec, failure_rate
- **Tags:** engine type, auth path, artifact mode
- **Artifacts:** benchmark_metadata.json, regression_outcome.json

This means:
1. **Results are queryable** — "show me all M-size runs on Ray from the last week"
2. **Regression outcomes are attached to candidate runs** — you can see which run passed/failed its gate
3. **Provenance is complete** — every number traces back to a specific dataset version, engine config, and execution environment

> **Interview angle:** "We treat MLflow as the system of record, not local files. This is the same discipline as Tecton's feature metadata catalog — every feature computation should be traceable to its source data, transformation logic, and execution context."

---

## What We Learned from Week 1

### Bottleneck Analysis

The three bottlenecks identified from baseline runs tell a story about where to optimize:

**1. Queue wait scales non-linearly (S→L)**
```
S: 2.77s  →  M: 8.42s  →  L: 22.81s
     ×3.0         ×2.7
```
This suggests the Ray scheduler becomes a bottleneck as task counts grow. The scheduler is doing O(n) or worse work per task, and at L-size the overhead dominates. This is the hypothesis that motivates EB-02 (Spark comparison) — Spark's batch-optimized scheduler may handle this differently.

**2. Throughput plateaus at scale**
```
S: 2,582 rows/s  →  M: 6,836 rows/s  →  L: 8,220 rows/s
       ×2.6              ×1.2
```
The 2.6x jump from S→M shows good parallelism kicking in. The 1.2x from M→L shows diminishing returns — we're hitting a ceiling, likely memory bandwidth or partition count limits.

**3. Non-zero failure rate is consistent**
```
S: 0.82%  →  M: 1.14%  →  L: 1.08%
```
Failure rate doesn't grow with size, which is good — it means failures are per-task (transient issues like timeout or resource contention), not systemic. But any non-zero rate matters for feature pipelines where data completeness is an SLO.

### The Candidate Improvement

Our optimized profile showed measurable gains:

| Metric | Baseline (M) | Candidate (M) | Delta |
|--------|-------------|---------------|-------|
| Runtime | 146.11s | 133.12s | -8.9% |
| Queue Wait | 8.42s | 7.45s | -11.5% |
| Throughput | 6,836 rows/s | 7,319 rows/s | +7.1% |
| Failure Rate | 1.14% | 1.03% | -9.6% |

The regression gate **passed** — all deltas were within allowed thresholds, and all moved in the favorable direction. This validates the framework: we can detect both improvements and regressions using the same rules.

---

## Key Patterns for Interview Prep

### Pattern: MLflow Artifact-First Policy

**What it is:** A design rule that says golden datasets and benchmark outputs must always be sourced from MLflow artifact URIs, never from arbitrary local file paths.

**Why it matters:** In a feature platform, you need to answer "where did this feature value come from?" at any time. If data can enter the system from random local paths, you lose auditability. The artifact-first policy enforces provenance by requiring every dataset to trace back to an MLflow run.

**Code reference:** `MLflowArtifactManager.create_or_update_golden_dataset()` in `ray_compute/benchmarking/mlflow_artifacts.py` — note how it takes a `source_run_id` + `source_artifact_path`, never a raw filesystem path.

### Pattern: Regression as a Gate, Not a Report

**What it is:** Regression checks produce a boolean `passed` result and are tagged on the MLflow run, not just printed to a log.

**Why it matters:** In a CI/CD pipeline for batch jobs, you want to automatically block deployments that cause regressions. A report that says "throughput dropped 12%" is useful but requires human intervention. A gate that fails the pipeline prevents the bad change from reaching production.

**Code reference:** `BenchmarkRunner.evaluate_regression_against_baseline()` — tags the candidate run with `regression.passed=true/false` and logs the full outcome as an artifact.

### Pattern: Separate Scheduler Overhead from Compute

**What it is:** Measuring `queue_wait_seconds` separately from `runtime_seconds` so you can distinguish "the cluster was busy" from "the code was slow."

**Why it matters:** When a batch job runs 20% slower, the first question is "is it my code or the cluster?" Queue wait isolates the cluster contribution. If queue wait grew but compute time didn't, the problem is resource contention, not your logic. This distinction drives different remediation strategies.

---

## Exercises

1. **Read the regression rules JSON** at `ray_compute/config/benchmark_regression_rules.json`. Why is `queue_wait_seconds` given a 15% threshold while `runtime_seconds` gets 10%? What would happen if both were 5%?

2. **Trace a benchmark run** in MLflow: Find run `255619037bb045d98ce2b12e7d17929f` and examine its params, metrics, and tags. What dataset version was used? What engine?

3. **Predict the Spark comparison:** Based on the queue wait scaling pattern (2.77s → 8.42s → 22.81s), hypothesize whether Spark's batch scheduler will show the same non-linear pattern. What architectural differences between Ray and Spark task scheduling might explain a different result?

---

*Next: [Part 2 — Distributed Compute: Ray vs Spark →](PART2_DISTRIBUTED_COMPUTE_ENGINES.md)*
