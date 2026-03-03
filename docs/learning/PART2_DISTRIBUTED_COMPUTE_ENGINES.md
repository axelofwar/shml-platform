# Part 2: Distributed Compute — Ray vs Spark

*Execution Board Item: EB-02 — Spark Batch Path (Parallel Engine)*

---

## Why This Matters

Tecton's job description explicitly calls for **Spark platform depth** — Databricks/EMR/Dataproc production tuning. Your current stack uses Ray. The question isn't "which is better?" — it's "when do you use which, and why?"

A senior engineer who says "I use Spark" is less compelling than one who says "I ran the same workload on both engines, measured the tradeoffs, and here's my decision framework for choosing between them." That's the signal EB-02 produces.

---

## Mental Model: Two Philosophies of Distributed Compute

### Ray: Task-Parallel, Actor-Based

Ray thinks in **tasks and actors**. You submit individual functions to a scheduler, and Ray decides where to run them.

```
┌─────────────────────────────────────────────────┐
│  Ray Architecture                                │
│                                                  │
│  Client  ──►  GCS (Global Control Store)         │
│                    │                             │
│              ┌─────┼─────┐                       │
│              ▼     ▼     ▼                       │
│           Worker Worker Worker  (task execution) │
│                                                  │
│  Scheduling: Per-task, dynamic, work-stealing    │
│  Granularity: Fine (individual function calls)   │
│  Strength: Heterogeneous workloads, GPU tasks    │
└─────────────────────────────────────────────────┘
```

**Key characteristics:**
- **Dynamic scheduling:** Tasks are scheduled one at a time as resources become available
- **Low startup overhead:** No JVM, no query planning — submit and go
- **Fine granularity:** Each task can be a different function with different resource requirements
- **Actor model:** Stateful workers that persist between tasks (useful for GPU model serving)
- **Weakness at scale:** The per-task scheduling overhead adds up — every task goes through GCS, which becomes a bottleneck (this is what we observed in Week 1 queue wait scaling)

### Spark: Stage-Parallel, DAG-Optimized

Spark thinks in **transformations on datasets**. You describe a computation graph (DAG), and Spark's optimizer decides how to execute it.

```
┌─────────────────────────────────────────────────┐
│  Spark Architecture                              │
│                                                  │
│  Driver  ──►  Catalyst Optimizer                 │
│                    │                             │
│              ┌─────┼─────┐                       │
│              ▼     ▼     ▼                       │
│           Executor Executor Executor             │
│           (JVM processes with task slots)         │
│                                                  │
│  Scheduling: Per-stage, bulk, barrier sync       │
│  Granularity: Coarse (bulk data partitions)      │
│  Strength: Large-scale data shuffles, SQL ops    │
└─────────────────────────────────────────────────┘
```

**Key characteristics:**
- **Bulk scheduling:** All tasks in a stage are scheduled together — amortizes scheduler overhead
- **Query optimizer (Catalyst):** Rewrites your logical plan into an efficient physical plan before execution
- **Shuffle engine:** Purpose-built for redistributing data across partitions (sort-merge, hash shuffle)
- **Lazy evaluation:** Nothing executes until an action is called — allows optimization across the entire DAG
- **Weakness for heterogeneous work:** Every task in a stage does the same thing — no mixing GPU inference with CPU transforms in one stage

### The Fundamental Tradeoff

```
                     Ray                          Spark
                     ───                          ─────
Scheduling model:    Per-task, dynamic            Per-stage, bulk
Startup cost:        Low (~ms)                    High (~seconds, JVM)
Scheduler overhead
at scale:            Grows with task count        Amortized across stage
Best for:            ML training, GPU inference,  ETL, large shuffles,
                     heterogeneous pipelines      SQL-like transforms
Query optimization:  None (you write the plan)    Catalyst (automatic)
Shuffle:             Manual (repartition)         Built-in, optimized
```

> **Interview angle:** "Ray and Spark optimize for different bottlenecks. Ray minimizes per-task latency — great for interactive or heterogeneous workloads. Spark minimizes per-record overhead at scale — great for bulk data processing where the same operation applies to millions of rows. The right choice depends on whether your bottleneck is scheduling overhead or data movement."

---

## What We're Testing (EB-02 Hypothesis)

From Week 1 baselines, we observed:

| Observation | Measurement | Hypothesis |
|-------------|-------------|------------|
| Queue wait scales non-linearly | 2.77s (S) → 22.81s (L) | Spark's bulk scheduling should show flatter queue wait scaling |
| Throughput plateaus at L | 8,220 rows/s (L) vs 6,836 (M) — only 1.2× | Spark's partition-level parallelism may push the throughput ceiling higher |
| Failure rate is per-task | ~1% across all sizes | Spark's stage-level retry may show different failure patterns |

### The Experiment Design

We port the same workload (YFCC100M batch transform) to both engines and compare:

| Control Variable | Value |
|-----------------|-------|
| Dataset | `adas-events-v1:1.0.0` (golden, checksummed) |
| Sizes | S (10K), M (100K), L (500K+) |
| Repetitions | 3 per size per engine |
| Metrics | runtime_seconds, queue_wait_seconds, throughput_rows_per_sec, failure_rate |
| Regression rules | Same thresholds from Week 1 |

This is a controlled experiment — same input, same output contract, different engine. Any performance difference is attributable to the engine's execution model.

---

## Spark Core Concepts (What You Need to Know)

### 1. The DataFrame API

Spark DataFrames are the primary abstraction. They look like pandas but execute distributed:

```python
# Pandas (single machine)
df = pd.read_csv("data.csv")
result = df[df["license"].isin([1,2,3,7])].groupby("tag").count()

# PySpark (distributed)
df = spark.read.csv("data.csv", header=True, inferSchema=True)
result = df.filter(col("license").isin([1,2,3,7])).groupBy("tag").count()
```

**The API is almost identical, but the execution model is completely different:**
- Pandas loads everything into memory on one machine
- Spark distributes the data across executors and processes partitions in parallel
- Spark is lazy — `filter` and `groupBy` build a plan but don't execute until `.count()` (an action)

### 2. Partitions

Data in Spark is divided into **partitions** — chunks that can be processed independently by different executors.

```
┌──────────────────┐
│  Input Dataset    │
│  (1M rows)       │
├──────────────────┤
│  Partition 0     │  → Executor 1
│  (250K rows)     │
├──────────────────┤
│  Partition 1     │  → Executor 2
│  (250K rows)     │
├──────────────────┤
│  Partition 2     │  → Executor 3
│  (250K rows)     │
├──────────────────┤
│  Partition 3     │  → Executor 1 (reused)
│  (250K rows)     │
└──────────────────┘
```

**Partition sizing rules of thumb:**
- Too few partitions → underutilized executors, poor parallelism
- Too many partitions → scheduling overhead, small-file problems
- Target: **128 MB per partition** for most workloads
- Formula: `num_partitions = data_size_bytes / (128 * 1024 * 1024)`

> **Interview angle:** "Partition tuning is one of the highest-ROI optimizations in Spark. I've seen jobs run 5x faster by simply changing `spark.sql.shuffle.partitions` from the default 200 to a number that matches the actual data volume and cluster size."

### 3. Shuffles

A **shuffle** happens when data needs to move between partitions — typically during `groupBy`, `join`, `repartition`, or `sort` operations.

```
Before shuffle (map side):        After shuffle (reduce side):
┌───────┐ ┌───────┐ ┌───────┐    ┌───────┐ ┌───────┐ ┌───────┐
│ A,B,C │ │ A,D,E │ │ B,C,F │    │ A,A   │ │ B,B   │ │ C,C   │
│       │ │       │ │       │    │ D     │ │ F     │ │ E     │
└───────┘ └───────┘ └───────┘    └───────┘ └───────┘ └───────┘
    Partition 0  1  2                  0         1         2
```

**Why shuffles matter:**
- They are the most expensive operation in Spark — all data must be serialized, sent over the network, and deserialized
- Most Spark "tuning" is really "shuffle reduction" — can you restructure the computation to avoid or minimize data movement?
- Key config: `spark.sql.shuffle.partitions` (default 200) — this is often wrong for your workload

**Shuffle optimization strategies:**
1. **Broadcast joins:** If one side of a join is small (<10MB), broadcast it to all executors instead of shuffling both sides
2. **Partition pruning:** If data is partitioned by date and you only need today's data, Spark skips all other partitions
3. **Bucketing:** Pre-partition tables by a join key so that joins on that key require no shuffle
4. **Coalesce vs repartition:** `coalesce(n)` reduces partitions without a full shuffle; `repartition(n)` does a full shuffle

### 4. Catalyst Optimizer

Spark's query optimizer that transforms your logical plan into an optimized physical plan:

```
Logical Plan (what you wrote):
  Filter(license IN (1,2,3,7))
    Scan(yfcc100m_dataset)

Optimized Physical Plan (what Spark executes):
  FileScan parquet [pushed predicate: license IN (1,2,3,7)]
```

**Key optimizations Catalyst performs:**
- **Predicate pushdown:** Moves filters closer to the data source (or into the scan)
- **Column pruning:** Only reads columns that are actually used
- **Join reordering:** Puts the smallest table on the build side of a hash join
- **Constant folding:** Pre-computes expressions that don't depend on data

You can inspect the plan with `df.explain(True)` — this shows the parsed, analyzed, optimized, and physical plans. **Being able to read explain plans is a core interview skill.**

### 5. Spark Session and Configuration

```python
from pyspark.sql import SparkSession

spark = SparkSession.builder \
    .appName("yfcc100m-batch-transform") \
    .config("spark.sql.shuffle.partitions", "50") \
    .config("spark.executor.memory", "4g") \
    .config("spark.driver.memory", "2g") \
    .config("spark.sql.adaptive.enabled", "true") \
    .getOrCreate()
```

**Key configs to know:**
| Config | Default | What It Controls |
|--------|---------|------------------|
| `spark.sql.shuffle.partitions` | 200 | Number of output partitions after shuffle |
| `spark.executor.memory` | 1g | Memory per executor JVM |
| `spark.executor.cores` | 1 | CPU cores per executor |
| `spark.sql.adaptive.enabled` | true (Spark 3+) | Adaptive Query Execution — dynamically adjusts partitions |
| `spark.sql.adaptive.coalescePartitions.enabled` | true | Auto-coalesce small shuffle partitions |
| `spark.default.parallelism` | total cores | Default parallelism for RDD operations |

---

## The Port: Ray Pipeline → Spark Pipeline

### Current Ray Pattern (YFCC100M Face Pipeline)

```python
# Current: Procedural Python + asyncio
def extract_face_metadata(sql_file, target_count, batch_size):
    for record in stream_sql_inserts(sql_file):  # Line-by-line generator
        if has_face_tag(record['user_tags']):     # Python function call
            if is_commercial_safe(record['license']):  # Python function call
                batch.append(record)
                if len(batch) >= batch_size:
                    execute_values(cursor, INSERT_SQL, batch)  # psycopg2 bulk insert
```

**Bottlenecks in this pattern:**
- Single-threaded extraction — one CPU core parses the entire 65GB file
- Python function call overhead per row — GIL-bound
- No query optimization — filter order is whatever the developer wrote

### Spark Equivalent

```python
# Spark: Declarative, distributed
df = spark.read.csv(sql_export_path, sep="\t", header=True, schema=schema)

result = df \
    .filter(has_face_tag_udf(col("user_tags"))) \
    .filter(col("license").isin(COMMERCIAL_SAFE_LICENSES)) \
    .select("photo_id", "user_tags", "download_url", "license", "latitude", "longitude")

result.write \
    .mode("overwrite") \
    .parquet(output_path)
```

**What's different:**
1. **Distributed read:** Spark splits the input across partitions, multiple executors parse simultaneously
2. **Optimized filter:** Catalyst can push the `license IN (...)` predicate to the scan level — cheaper than the tag check
3. **Parallel execution:** No GIL — each executor processes its partition independently
4. **Schema enforcement:** Types are declared upfront, not inferred row-by-row

### What Can't Be Ported

The **async HTTP download phase** (downloading actual images from Flickr URLs) is I/O-bound network work that doesn't benefit from Spark's data-parallel model. This stays as asyncio or gets handled by Ray actors.

**This is the architectural insight:** The batch transform (parse, filter, enrich metadata) is Spark's strength. The I/O-intensive download is Ray's strength (or plain asyncio). A mature platform uses both engines for what they're best at.

> **Interview angle:** "We split the pipeline at the I/O boundary. Batch metadata processing — parsing, filtering, enriching — runs on Spark because it benefits from Catalyst optimization and partition-level parallelism. The HTTP download phase stays on Ray because it's network-I/O-bound and benefits from async task scheduling. This engine-per-workload-type pattern is common in production feature platforms."

---

## Measuring the Comparison

After implementing the Spark path, we run the same benchmark suite:

```python
# The benchmark framework doesn't care about the engine — it measures the same metrics
scenario = BenchmarkScenario(
    benchmark_id="yfcc100m-face-extract",
    dataset_name="adas-events-v1",
    dataset_version="1.0.0",
    workload_name="M",
    engine="spark",      # ← Only this changes
    parameters={"spark.sql.shuffle.partitions": "50", ...}
)
```

**Expected results to validate:**
| Metric | Ray (baseline) | Spark (hypothesis) | Why |
|--------|---------------|-------------------|-----|
| Queue wait | Non-linear growth | Flatter scaling | Spark schedules per-stage, not per-task |
| Throughput at L | Plateaus at ~8K/s | Higher ceiling | Partition-level parallelism, no GIL |
| Startup time | ~ms | ~seconds | JVM initialization cost |
| Failure pattern | Per-task (~1%) | Per-stage (all-or-nothing) | Spark retries entire stages |

### EB-02 Actual Results (Feb 2026)

After implementing and running the selector, here are the **real numbers** from the remote
MLflow server (experiment `platform-benchmarking`, 3 reps per cell, averaged):

| Engine | Size | Rows | Workers | Avg Runtime | Avg Throughput | Avg QueueWait |
|--------|------|------|---------|-------------|----------------|---------------|
| Ray    | S    | 100K | 2       | 0.61s       | 164,118/s      | 1.10s         |
| Ray    | M    | 1M   | 4       | 5.62s       | 177,950/s      | 1.70s         |
| Ray    | L    | 5M   | 8       | 26.96s      | 185,450/s      | 2.90s         |
| Spark  | S    | 100K | 2       | 6.70s       | 15,286/s       | 0.00s         |
| Spark  | M    | 1M   | 4       | 46.61s      | 21,456/s       | 0.00s         |
| Spark  | L    | 5M   | 8       | 244.39s     | 20,459/s       | 0.00s         |

**What the hypothesis got right:**
- ✅ Spark startup time dominates at small scales (S: 11x slower due to SparkSession JVM init)
- ✅ Spark queue_wait ≈ 0 (stage-level scheduling, no per-task overhead)
- ✅ Spark failure_rate = 0 (Spark retries internally; Ray executor recorded 0 too in EB-02)

**What the hypothesis got wrong:**
- ❌ Spark throughput did NOT exceed Ray. Ray averaged 175K/s while Spark averaged 19K/s.
  **Root cause:** The workload is row-level Python dict processing — Spark's strength is
  Catalyst-optimizable DataFrame operations and Parquet I/O, not Python list serialization.
  The `createDataFrame(python_list)` path forces Python→JVM→Arrow serde on every row.
- ❌ We predicted Spark's partition parallelism would help at L scale. It didn't, because the
  bottleneck is serde, not compute parallelism.

**Interview takeaway:** "I ran the same batch transform on Ray and Spark. Ray won 8-11x because
the workload was row-level Python processing. Spark's optimizer can't help when the computation
is Python UDFs applied to in-memory dicts. If the workload were SQL-expressible joins on Parquet
files, I'd expect Spark to win because Catalyst would push filters, choose broadcast joins, and
AQE would coalesce partitions. Engine choice is workload-shape dependent."

---

## Key Patterns for Interview Prep

### Pattern: Engine Selection Framework

Don't just know Ray and Spark — know a framework for choosing between them:

| Factor | Choose Ray | Choose Spark |
|--------|-----------|--------------|
| Workload type | GPU inference, RL training, heterogeneous tasks | ETL, large joins, SQL-like transforms |
| Data volume | <100GB or real-time stream | >100GB batch processing |
| Latency requirement | Sub-second task scheduling | Throughput over latency |
| State management | Stateful actors (model servers) | Stateless transforms |
| Team expertise | ML engineers familiar with Python | Data engineers familiar with SQL |

### Pattern: Adaptive Query Execution (AQE)

Spark 3+ includes AQE, which dynamically adjusts the execution plan based on runtime statistics:
- **Coalesces small shuffle partitions** — if partition 47 only has 100 rows, merge it with partition 48
- **Converts sort-merge joins to broadcast joins** — if one side turns out to be small after filtering
- **Handles skew** — splits oversized partitions at runtime

AQE is essentially Spark doing what a human tuning expert would do, but automatically. **Know this feature and its configs — it's a common interview topic.**

### Pattern: Cost Proxy Model

For engine comparison, raw runtime isn't enough. You need a cost proxy:

```
cost = runtime_seconds × (executor_count × executor_cores × cost_per_core_second)
```

This normalizes across different cluster sizes. A Spark job that's 20% slower but uses half the executors might be cheaper overall. Feature platform teams care about **cost per feature row processed**, not just wall-clock time.

---

## Exercises (Now Completed — Answers Below)

1. **Read an explain plan:** Run `df.explain(True)` on a simple PySpark query and identify: (a) where predicate pushdown happens, (b) which join strategy Spark chose, (c) how many shuffle exchanges there are.

   **EB-02 Answer:** The Spark executor captures `df_agg._jdf.queryExecution().simpleString()` as
   metadata in each MLflow run artifact. The plan shows: (a) Filter pushdown of `is_face = true
   AND confidence > 0.5` happens at the DataFrame scan level (no file-level pushdown since we're
   reading from a Python list, not Parquet — in production, PushedFilters would appear). (b) No
   joins in this workload — single-table filter→enrich→aggregate. (c) One Exchange for the
   `groupBy(sensor_type, region)` aggregation → `hashpartitioning(sensor_type, region, N)`.

2. **Predict the partition count:** If you have 10GB of Parquet data and each executor has 4GB memory, how many partitions should you target?

   **Answer:** `10GB / 128MB target = ~80 partitions`. With default `shuffle.partitions=200`,
   you'd get 200 partitions of ~50MB each after a shuffle — acceptable but wastes some scheduling
   overhead. With AQE, set `shuffle.partitions=200` and let AQE coalesce to the optimal count.
   We observed this in EB-02: Spark warned about "very large task size" when we had too FEW
   partitions (workers=8 for 5M rows → 27MB per task as serialized Python objects).

3. **Design the selector:** Sketch a `--backend ray|spark` flag for the submission script.

   **EB-02 Answer:** Implemented at `scripts/benchmarking/backend_selector.py`:
   - `EngineConfig` dataclass holds engine name + config dict
   - `get_executor(config) → Callable[[BenchmarkScenario], BenchmarkResult]`
   - Lazy-imports engine modules (don't need PySpark to run Ray, and vice versa)
   - `build_scenario()` creates `BenchmarkScenario` with standard tags
   - Convergence: Same `BenchmarkResult` metrics contract, same MLflow logging, same regression rules
   - Divergence: Ray uses `multiprocessing.Pool`, Spark uses `SparkSession.builder + DataFrame API`

---

*Previous: [← Part 1: Benchmarking & Regression](PART1_BENCHMARKING_AND_REGRESSION.md)*
*Next: [Part 3 — Table Formats & Query Optimization →](PART3_TABLE_FORMATS_AND_QUERY_OPTIMIZATION.md)*
