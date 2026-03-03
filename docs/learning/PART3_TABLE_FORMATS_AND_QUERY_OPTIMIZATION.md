# Part 3: Table Formats & Query Optimization

*Execution Board Items: EB-03 (Table Format Path) + EB-04 (Query Optimization Case Study)*

---

## Why This Matters

Tecton's feature platform stores computed features in managed tables. Those tables aren't CSVs or raw Parquet files — they use **table formats** (Iceberg, Delta Lake, Hudi) that provide database-like guarantees on top of object storage. If you don't understand how these formats work — schema evolution, partition evolution, compaction, time travel — you can't design or debug the systems that depend on them.

Gap #4 from your fit analysis: **"Iceberg/Delta Lake production implementation evidence."** This part closes it.

---

## What Is a Table Format (And Why Raw Parquet Isn't Enough)

### The Problem with Raw Files

Imagine you have a feature pipeline that writes daily Parquet files:

```
/features/user_spend/
  dt=2026-02-24/part-00000.parquet
  dt=2026-02-24/part-00001.parquet
  dt=2026-02-25/part-00000.parquet
  dt=2026-02-25/part-00001.parquet
  dt=2026-02-26/part-00000.parquet
```

This works... until it doesn't:

| Problem | What Happens |
|---------|--------------|
| **Schema change** | You add a column. Old files don't have it. Readers crash or return nulls. |
| **Concurrent writes** | Two jobs write to the same partition simultaneously. One overwrites the other. Data loss. |
| **Failed writes** | A job crashes halfway through writing 10 files. 5 files exist, 5 don't. Partial data. |
| **Time travel** | "What were the features yesterday at 3pm?" No mechanism to query historical state. |
| **Small files** | 10,000 tiny Parquet files. Every query does 10,000 file opens. Slow. |
| **Partition change** | You realize daily partitions are too coarse — you want hourly. Rewrite everything. |

### What Table Formats Solve

A table format adds a **metadata layer** on top of the raw files:

```
┌─────────────────────────────────────────────┐
│  Table Format (Iceberg / Delta / Hudi)       │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │  Metadata (manifest files/log)       │    │
│  │  - Which files belong to the table   │    │
│  │  - Schema (current + evolution)      │    │
│  │  - Partition spec (current + old)    │    │
│  │  - Snapshot history (time travel)    │    │
│  │  - Column-level min/max statistics   │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │  Data Files (Parquet/ORC/Avro)       │    │
│  │  part-00000.parquet                  │    │
│  │  part-00001.parquet                  │    │
│  │  ...                                │    │
│  └──────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

**Guarantees provided:**
- **ACID transactions:** Writes are atomic — either all files appear or none do
- **Schema evolution:** Add/rename/drop columns with backward-compatible reads
- **Partition evolution:** Change partition strategy without rewriting data
- **Time travel:** Query the table "as of" any past snapshot
- **File management:** Compaction merges small files; manifests track which files are alive vs deleted

---

## Iceberg vs Delta Lake: Decision Framework

| Dimension | Apache Iceberg | Delta Lake |
|-----------|---------------|------------|
| **Governance** | Apache Foundation (vendor-neutral) | Databricks-originated (Linux Foundation since 2024) |
| **Engine support** | Spark, Flink, Trino, Dremio, Ray (PyIceberg) | Spark (native), limited Flink/Trino support |
| **Schema evolution** | Full: add, rename, drop, reorder, type promotion | Full: add, rename, overwrite, merge schema |
| **Partition evolution** | First-class (change strategy without rewrite) | Requires rewrite via `REPLACE TABLE` |
| **Time travel** | Snapshot-based (snapshot IDs + timestamps) | Version-based (Delta log version numbers) |
| **Hidden partitioning** | Yes (transforms: bucket, truncate, day/hour/year) | No (partitioning exposed in directory structure) |
| **Catalog** | REST, Hive, AWS Glue, Nessie | Unity Catalog, Hive Metastore |
| **Compaction** | `rewrite_data_files` procedure | `OPTIMIZE` command + Z-ORDER |
| **Community momentum** | Accelerating (Netflix, Apple, LinkedIn, Snowflake) | Strong (Databricks ecosystem) |

### Why We Choose Iceberg for This Sprint

Per the scope lock: **"Iceberg preferred unless dependency friction exceeds 0.5 day."**

Reasons:
1. **Vendor-neutral** — demonstrates broader architectural judgment than choosing a Databricks product
2. **Partition evolution** — Iceberg's hidden partitioning is more sophisticated and generates better interview stories
3. **Engine flexibility** — works with both Spark and Ray (via PyIceberg), aligning with our dual-engine approach
4. **Industry convergence** — Snowflake, Netflix, Apple, and most feature platform vendors are standardizing on Iceberg

> **Interview angle:** "I chose Iceberg over Delta because partition evolution is a first-class operation — you can change from daily to hourly partitioning without rewriting existing data. In a feature platform where partitioning strategy evolves as data volumes grow, this avoids expensive maintenance operations."

---

## Iceberg Core Operations (What You Need to Know)

### 1. Creating a Table

```python
from pyspark.sql import SparkSession

spark = SparkSession.builder \
    .config("spark.sql.catalog.local", "org.apache.iceberg.spark.SparkCatalog") \
    .config("spark.sql.catalog.local.type", "hadoop") \
    .config("spark.sql.catalog.local.warehouse", "/data/warehouse") \
    .getOrCreate()

# Create table with explicit schema and partitioning
spark.sql("""
    CREATE TABLE local.features.user_activity (
        user_id     STRING,
        event_type  STRING,
        event_count BIGINT,
        total_spend DOUBLE,
        event_date  DATE,
        processed_at TIMESTAMP
    )
    USING iceberg
    PARTITIONED BY (days(event_date))
""")
```

**Key detail: `PARTITIONED BY (days(event_date))`**

This is Iceberg's **hidden partitioning** — the table is partitioned by the day extracted from `event_date`, but consumers don't need to know. They just filter on `event_date` and Iceberg handles partition pruning automatically.

Compare with Hive-style partitioning where consumers must include the partition column explicitly:
```sql
-- Hive-style: Consumer must know the partition layout
SELECT * FROM user_activity WHERE dt = '2026-02-26'

-- Iceberg: Consumer writes natural predicates, Iceberg prunes
SELECT * FROM user_activity WHERE event_date = '2026-02-26'
```

### 2. Schema Evolution

```sql
-- Add a new column (backward compatible — old rows get NULL)
ALTER TABLE local.features.user_activity
ADD COLUMN region STRING AFTER event_type;

-- Rename a column (metadata-only, no data rewrite)
ALTER TABLE local.features.user_activity
RENAME COLUMN total_spend TO total_spend_usd;

-- Widen a type (int → long, float → double)
ALTER TABLE local.features.user_activity
ALTER COLUMN event_count TYPE BIGINT;
```

**Why this matters for feature platforms:**
Feature definitions evolve. A feature that starts as `total_spend DOUBLE` might need to become `total_spend_cents BIGINT` (to avoid floating-point precision issues). With Iceberg, this is a metadata operation — no data rewriting required. Without a table format, you'd need to reprocess all historical data.

**Schema evolution rules (Iceberg):**
- **Safe changes:** Add column, rename column, reorder columns, widen type (int→long, float→double)
- **Breaking changes:** Drop column (requires explicit flag), narrow type (long→int)
- **Schema ID tracking:** Each version of the schema gets an ID. Data files reference the schema they were written with. Iceberg reconciles at read time.

### 3. Time Travel

```sql
-- Query the table as it existed at a specific timestamp
SELECT * FROM local.features.user_activity
FOR SYSTEM_TIME AS OF '2026-02-25 14:00:00';

-- Query a specific snapshot by ID
SELECT * FROM local.features.user_activity
FOR SYSTEM_VERSION AS OF 12345;

-- See snapshot history
SELECT * FROM local.features.user_activity.snapshots;
```

**Why this matters for feature platforms:**
- **Debugging:** "The model trained on features from 2pm yesterday had bad accuracy — what did the features look like at that time?"
- **Reproducibility:** Training runs should be reproducible. Time-travel lets you reconstruct the exact feature values that were used.
- **Auditing:** "What features were served to user X at time T?" Compliance teams need this.

> **Interview angle:** "Time travel is how we implement feature reproducibility. When a model training run references features 'as of' training time, Iceberg's snapshot isolation guarantees that the features are exactly what was available at that moment — even if newer data has since arrived."

### 4. Compaction (Table Maintenance)

Over time, batch pipelines write many small files (one per micro-batch, one per partition). Small files degrade read performance because each file requires filesystem/metadata overhead.

```sql
-- Compact small files into larger ones
CALL local.system.rewrite_data_files(
    table => 'local.features.user_activity',
    options => map('target-file-size-bytes', '134217728')  -- 128 MB target
);

-- Remove old snapshots (for storage cleanup)
CALL local.system.expire_snapshots(
    table => 'local.features.user_activity',
    older_than => TIMESTAMP '2026-02-20 00:00:00',
    retain_last => 5
);

-- Remove orphan files (files not referenced by any snapshot)
CALL local.system.remove_orphan_files(
    table => 'local.features.user_activity',
    older_than => TIMESTAMP '2026-02-20 00:00:00'
);
```

**The maintenance cycle:**
```
Write data  →  Small files accumulate  →  Read perf degrades
    ↑                                          │
    │          Compact files (merge)  ←────────┘
    │                 │
    │          Expire old snapshots
    │                 │
    └──── Remove orphan files ────────────────┘
```

**How often to compact:**
- **High-frequency writes (hourly):** Compact daily
- **Daily batch writes:** Compact weekly
- **Low-frequency writes:** Compact when file count exceeds threshold (e.g., >1000 files per partition)

> **Interview angle:** "Compaction is a tradeoff between write amplification and read performance. We compact eagerly for high-read feature tables (where every millisecond of read latency matters for serving) and lazily for archive tables (where storage cost matters more than read speed)."

---

## Partition Evolution (Iceberg's Killer Feature)

### The Scenario

You start with daily partitioning:

```sql
CREATE TABLE features USING iceberg PARTITIONED BY (days(event_date));
```

After 6 months, data volume grows 10x. Daily partitions are too large — queries that need a single hour still scan a full day's data. You want hourly partitioning.

### Without Iceberg

```
Option A: Rewrite all data with new partitioning (expensive, risky)
Option B: Start hourly going forward, live with mixed layout (messy)
Option C: Build a view that unions old and new tables (fragile)
```

### With Iceberg

```sql
-- Change partition strategy (metadata-only, no data rewrite)
ALTER TABLE features
ADD PARTITION FIELD hours(event_date);

-- New writes use hourly partitioning
-- Old data stays in daily partitions
-- Queries transparently read from both — Iceberg handles it
```

**How it works internally:**
- Iceberg tracks partition specs with version numbers
- Each data file is associated with the partition spec that was active when it was written
- At read time, Iceberg applies the correct partition filter for each file based on its partition spec
- No data rewriting required — old files stay exactly where they are

This is genuinely unique to Iceberg. Delta Lake requires `REPLACE TABLE` (full rewrite) to change partitioning.

---

## Query Optimization (EB-04)

Query optimization is where table formats and engine tuning intersect. EB-04 asks you to capture baseline query plans, apply optimizations, and quantify the deltas.

### Reading Spark Explain Plans

```python
df = spark.read.table("local.features.user_activity")
result = df.filter(col("event_date") == "2026-02-26").groupBy("region").sum("event_count")
result.explain(True)
```

This produces four levels of plans:

```
== Parsed Logical Plan ==
Aggregate [region], [region, sum(event_count)]
  Filter (event_date = 2026-02-26)
    Relation local.features.user_activity

== Analyzed Logical Plan ==
(same but with resolved types and columns)

== Optimized Logical Plan ==
Aggregate [region], [region, sum(event_count)]
  Filter (event_date = 2026-02-26)       ← Predicate pushdown candidate
    Relation local.features.user_activity

== Physical Plan ==
HashAggregate(keys=[region], functions=[sum(event_count)])
  Exchange hashpartitioning(region, 200)  ← SHUFFLE (expensive!)
    HashAggregate(keys=[region], functions=[partial_sum(event_count)])
      FileScan iceberg [region, event_count]
        PushedFilters: [event_date = 2026-02-26]  ← Pushed to Iceberg!
        PartitionFilters: [days(event_date) = 20513]  ← Partition pruning!
```

### What to Look For

| Plan Element | Good Sign | Bad Sign |
|-------------|-----------|----------|
| `PushedFilters` | Predicates pushed to scan | Empty — filters applied after full scan |
| `PartitionFilters` | Partitions pruned | Missing — scanning all partitions |
| `Exchange` | Minimal shuffles | Multiple shuffles (expensive) |
| `BroadcastHashJoin` | Small table broadcast | `SortMergeJoin` on a small table |
| `HashAggregate` partial | Partial aggregation before shuffle | Full aggregation after shuffle |

### Three Optimizations to Implement (EB-04)

**Optimization 1: Partition Pruning**

```sql
-- Before: Full table scan
SELECT region, SUM(event_count) FROM features GROUP BY region;
-- Plan: FileScan reads ALL partitions

-- After: Add date filter
SELECT region, SUM(event_count) FROM features
WHERE event_date >= '2026-02-20' GROUP BY region;
-- Plan: PartitionFilters prune to 7 days of data
```

Measurement: Compare runtime and data scanned (bytes) before and after.

**Optimization 2: Join Strategy**

```sql
-- Before: SortMergeJoin (both sides shuffled)
SELECT f.*, d.region_name
FROM features f JOIN dim_regions d ON f.region = d.region_code;
-- Plan: Exchange on both sides → SortMergeJoin

-- After: Broadcast hint (dim_regions is small)
SELECT /*+ BROADCAST(d) */ f.*, d.region_name
FROM features f JOIN dim_regions d ON f.region = d.region_code;
-- Plan: BroadcastExchange on d → BroadcastHashJoin (no shuffle on f)
```

Measurement: Compare shuffle bytes and runtime.

**Optimization 3: Adaptive Partition Coalescing**

```python
# Before: Fixed 200 shuffle partitions (most are tiny)
spark.conf.set("spark.sql.shuffle.partitions", "200")
spark.conf.set("spark.sql.adaptive.enabled", "false")

# After: AQE auto-coalesces
spark.conf.set("spark.sql.adaptive.enabled", "true")
spark.conf.set("spark.sql.adaptive.coalescePartitions.enabled", "true")
spark.conf.set("spark.sql.adaptive.coalescePartitions.minPartitionSize", "64MB")
```

Measurement: Compare partition count, task count, and runtime.

### The Case Study Format

```markdown
## Optimization: [Name]

### Baseline
- Query: [SQL]
- Plan: [Physical plan excerpt]
- Runtime: X seconds
- Data scanned: Y GB
- Shuffle bytes: Z GB

### Change Applied
- [What was changed and why]

### Result
- Runtime: X' seconds (Δ -N%)
- Data scanned: Y' GB (Δ -N%)
- Shuffle bytes: Z' GB (Δ -N%)

### Why It Works
- [Explain-plan-level reasoning]
```

> **Interview angle:** "I structured each optimization as a controlled experiment — same query, same data, one variable changed. The explain plan shows why the optimization works at the engine level, not just that the number got smaller. For example, the broadcast join eliminated a 2.3GB shuffle because the dimension table was only 4MB — well within broadcast threshold."

---

## Key Patterns for Interview Prep

### Pattern: Schema-on-Read vs Schema-on-Write

**Schema-on-write** (traditional DB): Data must conform to the schema when written. Schema changes require ALTER TABLE + backfill.

**Schema-on-read** (raw files): No schema enforcement. Reader applies whatever schema it expects. Breaks silently when data changes.

**Table formats** (Iceberg/Delta): Schema-on-write with evolution. New data must conform to the current schema, but the schema can evolve, and old data is reconciled at read time using schema IDs. This is the best of both worlds.

### Pattern: Write-Audit-Publish (WAP)

A production pattern for safe table updates:

```
1. Write: Produce new data files (not yet visible to readers)
2. Audit: Validate data quality, row counts, schema compatibility
3. Publish: Atomically commit the new snapshot (now visible)
```

Iceberg supports this via **staged commits** — you can write files, inspect them, and decide whether to commit or abort. This prevents bad data from ever being visible to downstream consumers.

### Pattern: Compaction as SLO-Driven Maintenance

Don't compact on a fixed schedule — compact when read performance degrades below SLO:

```
IF avg_read_latency > slo_threshold:
    trigger_compaction(target_file_size=128MB)
    alert("Compaction triggered: read latency {avg_read_latency}ms > SLO {slo_threshold}ms")
```

This connects table maintenance to observable business outcomes (feature serving latency) rather than arbitrary timers.

---

## Exercises

1. **Create an Iceberg table** with PySpark, insert 1000 rows, add a column, insert 1000 more rows. Query "as of" before the schema change — what value does the new column have for old rows?

2. **Read an explain plan** for a query with a join and a filter. Identify: (a) where partition pruning happens, (b) the join strategy, (c) how many shuffles occur.

3. **Predict the compaction benefit:** If you have 500 files averaging 2MB each in a partition, and you compact to 128MB target size, how many files will remain? What's the expected read latency improvement?

4. **Design partition evolution:** You have a table partitioned by `days(event_date)` with 1 year of data. Data grows from 1GB/day to 50GB/day. Design the partition evolution strategy. What's the query plan impact?

---

### EB-03 Actual Results (Executed 2026-02-27)

All 4 exercises were executed via [`scripts/benchmarking/eb03_iceberg_exercises.py`](../../shml-platform/scripts/benchmarking/eb03_iceberg_exercises.py) using PySpark 4.1.1 + Iceberg 1.10.1 (`iceberg-spark-runtime-4.0_2.13`).

#### Exercise 1 — Schema Evolution & Time Travel

**Setup:** Created `local.exercises.user_activity` with hidden partitioning (`days(event_date)`). Inserted 1000 rows, then added a `region STRING` column, then inserted 1000 more with region populated.

**Time-travel result:** When querying the old snapshot (before schema change) via `VERSION AS OF {snapshot_id}`, the old schema is returned — the `region` column does **not appear** in the result set at all.

| Query Target | Columns | Region Value |
|-------------|---------|-------------|
| Old snapshot (pre-schema-change) | 6 original columns | Column not present |
| Current state (post-schema-change) | 7 columns | NULL for old rows, populated for new rows |

**Key insight:** Iceberg tracks a schema ID per data file in its metadata. When you time-travel to an old snapshot, you get that snapshot's schema. When you query the current state, old data files are *reconciled* at read time — new columns get NULL for rows written before the column was added. This is fundamentally different from database ALTER TABLE which rewrites data.

#### Exercise 2 — Explain Plan Analysis

**Query:** `JOIN user_activity ua ON dim_regions dr WHERE event_date BETWEEN '2026-02-10' AND '2026-02-20' GROUP BY event_type, region_name, cost_zone`

**Physical plan findings:**

| Plan Element | Result | Why |
|-------------|--------|-----|
| **(a) Partition pruning** | ✅ Present — `filters=event_date >= 20494, event_date <= 20504` | Iceberg pushes date predicate into BatchScan; only partition files for the 11-day window are opened |
| **(b) Join strategy** | **BroadcastHashJoin** (BuildRight) | `dim_regions` has 4 rows (~200 bytes) — well under the 10MB broadcast threshold. No shuffle on the fact table side |
| **(c) Shuffles** | 3 Exchange nodes | Exchange #1: hashpartitioning for partial aggregation. Exchange #2: hashpartitioning for final aggregation merge. Exchange #3: rangepartitioning for ORDER BY. *Zero shuffles for the join itself* (broadcast eliminated it) |

**Optimized plan showed:** Column pruning (only 5 of 7 columns read from `user_activity`), `isnotnull(region)` filter pushed down (inner join requires non-null keys), and AQE enabled (`isFinalPlan=false` — plan may be refined at runtime).

#### Exercise 3 — Compaction

**Live compaction:**
- Before: 140 files × 1.4 KB avg = 191.4 KB total (20 batches × 7 day-partitions)
- After: 7 files × 2.2 KB avg = 15.2 KB total
- Compaction time: 0.46s
- File count reduction: 140 → 7 (20× fewer files)

**Theoretical answer (500 × 2MB → 128MB target):**

```
Total data    = 500 × 2 MB = 1,000 MB (1 GB)
Target size   = 128 MB
Output files  = ceil(1000 / 128) = 8 files
File opens    = 500 → 8 (62.5× reduction)

Read latency improvement:
  Before: 500 file opens × ~7.5ms each = ~3.75s metadata overhead
  After:    8 file opens × ~7.5ms each = ~0.06s metadata overhead
  Savings: ~3.7 seconds per scan, plus better Parquet row-group
           alignment for predicate pushdown and column-chunk co-location
```

#### Exercise 4 — Partition Evolution

**Live execution:**
1. Created table with `PARTITIONED BY (days(event_ts))` — 700 rows, 8 daily partitions
2. Evolved spec via Iceberg Java API: `updateSpec().addField("event_ts_hour", hours(event_ts)).commit()`
   - Metadata-only operation — zero data rewrite
   - Spec changed from `[days(event_ts)]` to `[days(event_ts), hours(event_ts)]`
3. Inserted 3500 more rows — new data written with both day and hour partition values
4. Old files show `{2026-02-04, NULL}` for their partition tuple (hourly value wasn't tracked when written)
5. Cross-spec query worked transparently — Spark reads both old (daily-only) and new (daily+hourly) files

> **Note:** `ALTER TABLE ... ADD PARTITION FIELD hours(event_ts)` SQL failed due to Iceberg SQL extension binary incompatibility with Spark 4.1.1 (`Origin` constructor changed). The Iceberg Java API (`table.updateSpec()`) worked correctly. This is a known compatibility gap between `iceberg-spark-runtime-4.0` and Spark 4.1.1.

**Design answer (1GB/day → 50GB/day scenario):**

```
Phase 1 (low volume):  PARTITIONED BY days(event_date)
                        1 GB/day → 1 file per day partition → fine

Phase 2 (high volume): ALTER TABLE ADD PARTITION FIELD hours(event_date)
                        50 GB/day → ~2.1 GB/hour → manageable file sizes

Key properties:
  • Old data stays in daily partitions — no rewrite
  • New data writes to hourly partitions — finer granularity
  • Mixed partition specs are transparent to queries
  • WHERE event_date = '2026-12-15' AND hour(event_ts) = 14:
    - Old data: scans 1 daily partition (all hours)
    - New data: scans 1 hourly partition (2.1 GB instead of 50 GB) → 24× pruning
  • No impact on queries without hour filter (scans day partitions normally)
```

---

### EB-04 Actual Results — Query Optimization Case Study (Executed 2026-02-28)

3 controlled experiments via [`scripts/benchmarking/eb04_query_optimization.py`](../../shml-platform/scripts/benchmarking/eb04_query_optimization.py) on 50K-row Iceberg fact table with 2 dimension tables.

| Optimization | Baseline | Optimized | Speedup | Key Change |
|-------------|----------|-----------|---------|------------|
| 1. Partition pruning | 0.45s (full scan, 60 days) | 0.15s (7-day filter) | **3.0×** | `PartitionFilters` prunes 88% of partitions |
| 2. Join strategy | 0.27s (SortMergeJoin, 4 exchanges) | 0.21s (BroadcastHashJoin, 3 exchanges) | **1.3×** | 5-row dim broadcast eliminates 1 shuffle |
| 3. AQE coalescing | 0.86s (200 fixed partitions) | 0.19s (AQE → 1 partition) | **4.6×** | `CoalescedShuffleRead` merges 200 → 1 partition |

**Key findings:**
- Partition pruning provides the largest bang-for-buck — it's free (just add a WHERE clause)
- AQE partition coalescing has dramatic impact when `spark.sql.shuffle.partitions` is over-provisioned relative to data size
- BroadcastHashJoin benefit is modest here but critical at scale — eliminates full-data shuffle on the fact table
- All explain plans showed `AdaptiveSparkPlan isFinalPlan=false` confirming AQE runtime plan refinement

See also: [Iceberg & Spark SQL Strategy Cheatsheet](CHEATSHEET_ICEBERG_SQL_STRATEGIES.md)

---

*Previous: [← Part 2: Distributed Compute](PART2_DISTRIBUTED_COMPUTE_ENGINES.md)*
*Next: [Part 4 — Feature Platform Design & SLOs →](PART4_FEATURE_PLATFORM_DESIGN.md)*
