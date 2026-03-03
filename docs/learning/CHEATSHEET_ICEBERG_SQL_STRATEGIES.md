# Iceberg & Spark SQL Strategy Cheatsheet

Quick reference for all join strategies, query optimizations, and Iceberg-specific SQL operations. Each entry includes: what it is, when Spark picks it, how to force it, and the performance tradeoff.

---

## 1. Join Strategies

Spark has 5 physical join strategies. The optimizer picks one based on table sizes, join type, and hints.

### 1a. BroadcastHashJoin (BHJ)

```
┌──────────────────┐     broadcast     ┌──────────────────┐
│  Small table     │ ──────────────▶   │  Each executor   │
│  (dim_regions)   │   (replicated)    │  has full copy   │
│  4 rows, 200B    │                   │  + hash table    │
└──────────────────┘                   └──────────────────┘
                                              │
                 Probe: stream large table ───▶│ hash lookup
                 No shuffle on large side      │
```

| Property | Detail |
|----------|--------|
| **When chosen** | One side < `spark.sql.autoBroadcastJoinThreshold` (default 10MB) |
| **Shuffle cost** | **Zero** on the large table; small table broadcast once |
| **Best for** | Fact + dimension joins where dim table is small |
| **Force it** | `SELECT /*+ BROADCAST(d) */ ...` or `df.join(broadcast(dim), ...)` |
| **Avoid when** | Both tables are large (OOM on broadcast), or outer join on broadcast side |

**Spark plan signature:**
```
BroadcastHashJoin [region], [region_code], Inner, BuildRight, false
  BroadcastExchange HashedRelationBroadcastMode(...)
```

### 1b. ShuffledHashJoin (SHJ)

```
┌──────────────┐  shuffle by key   ┌──────────────┐
│  Table A     │ ────────────────▶ │  Partition N  │ ← both sides
│              │                   │  build hash   │    co-located
└──────────────┘                   │  table on     │    by join key
┌──────────────┐  shuffle by key   │  smaller side │
│  Table B     │ ────────────────▶ │  probe with   │
│              │                   │  larger side  │
└──────────────┘                   └──────────────┘
```

| Property | Detail |
|----------|--------|
| **When chosen** | One side fits in memory per-partition; `spark.sql.join.preferSortMergeJoin=false` |
| **Shuffle cost** | **Both sides shuffled** by join key |
| **Best for** | Medium-sized builds where hash fits in memory per partition |
| **Force it** | `SELECT /*+ SHUFFLE_HASH(b) */ ...` |
| **Avoid when** | Build side is too large for in-memory hash table → OOM |

**Spark plan signature:**
```
ShuffledHashJoin [key], [key], Inner, BuildRight
  Exchange hashpartitioning(key, 200)
```

### 1c. SortMergeJoin (SMJ)

```
┌──────────────┐  shuffle + sort   ┌──────────────┐
│  Table A     │ ────────────────▶ │  Partition N  │
│              │                   │  sorted by    │
└──────────────┘                   │  join key     │
                                   │              │ ← merge scan
┌──────────────┐  shuffle + sort   │  Partition N  │    (both sorted)
│  Table B     │ ────────────────▶ │  sorted by    │
│              │                   │  join key     │
└──────────────┘                   └──────────────┘
```

| Property | Detail |
|----------|--------|
| **When chosen** | Default for equi-joins when neither side is broadcastable |
| **Shuffle cost** | **Both sides shuffled AND sorted** by join key |
| **Best for** | Large × large joins; doesn't require fitting in memory |
| **Force it** | `SELECT /*+ MERGE(a, b) */ ...` or default behavior |
| **Avoid when** | One side is small (use broadcast instead — much cheaper) |

**Spark plan signature:**
```
SortMergeJoin [key], [key], Inner
  Sort [key ASC]
    Exchange hashpartitioning(key, 200)
```

### 1d. BroadcastNestedLoopJoin (BNLJ)

| Property | Detail |
|----------|--------|
| **When chosen** | Non-equi joins (theta joins: `a.x > b.y`) with one small side |
| **Shuffle cost** | None (broadcast); but $O(n \times m)$ comparison |
| **Best for** | Cross joins, range joins, inequality conditions on small tables |
| **Force it** | Automatic for non-equi + small table |
| **Avoid when** | Both sides are large — quadratic blowup |

### 1e. CartesianProduct

| Property | Detail |
|----------|--------|
| **When chosen** | Non-equi join with no broadcastable side; `spark.sql.crossJoin.enabled=true` |
| **Shuffle cost** | Both sides; $O(n \times m)$ rows produced |
| **Best for** | Literally never in production. Often indicates a missing join condition |
| **Avoid when** | Always. Rethink your query |

### Join Strategy Decision Tree

```
                        Is it an equi-join?
                       /                    \
                     Yes                     No
                      │                       │
              Is one side small?        Is one side small?
             /                \        /                \
           Yes                 No    Yes                 No
            │                  │      │                   │
    BroadcastHashJoin    SortMergeJoin   BroadcastNested   CartesianProduct
                              │          LoopJoin          (avoid!)
                              │
                     Is one side medium
                     and fits in memory?
                    /                    \
                  Yes                     No
                   │                      │
           ShuffledHashJoin         SortMergeJoin
```

---

## 2. Exchange (Shuffle) Types

Every `Exchange` node in a Spark plan = data movement across the network.

| Exchange Type | When Used | Cost |
|--------------|-----------|------|
| `hashpartitioning(key, N)` | GROUP BY, JOIN — co-locate rows by key | Network I/O proportional to data size |
| `rangepartitioning(col, N)` | ORDER BY — distribute for global sort | Sampling + shuffle |
| `RoundRobinPartitioning(N)` | `REPARTITION(N)` without key | Even distribution, no locality |
| `SinglePartition` | Collect to driver (`collect()`, scalar subquery) | All data to one node — dangerous |
| `BroadcastExchange` | Broadcast join — replicate small table | Small data to all executors |

**Goal:** Minimize Exchange nodes. Each one serializes, sends over network, and deserializes.

---

## 3. Predicate Pushdown & Partition Pruning

### Predicate Pushdown (to data source)

```sql
-- This filter is pushed INTO the Iceberg scan
WHERE event_date >= '2026-02-10' AND region IS NOT NULL

-- In the plan:
BatchScan [filters=event_date >= 20494, region IS NOT NULL]
```

Iceberg uses **manifest-level min/max statistics** to skip entire files that can't contain matching rows. This happens BEFORE any Parquet row-group filtering.

### Partition Pruning (to partition metadata)

```sql
-- Iceberg table: PARTITIONED BY (days(event_date))
WHERE event_date = '2026-02-26'

-- In the plan:
PartitionFilters: [days(event_date) = 20513]
-- Only opens files in the 2026-02-26 partition
```

### Column Pruning

```sql
-- Only reads 2 columns from Parquet, not all 7
SELECT region, SUM(event_count) FROM features
-- In plan: BatchScan [region, event_count]
```

### Pushdown Hierarchy

```
Most effective (data never read)
  │
  ├── Partition pruning        → skip entire partitions
  ├── File-level min/max skip  → skip entire Parquet files
  ├── Row-group statistics     → skip Parquet row groups within files
  ├── Column pruning           → read only needed columns
  │
  └── Post-scan filtering      → read everything, filter in memory
                                  (least effective)
```

---

## 4. Aggregation Strategies

### Partial Aggregation (Map-Side Combine)

```
Stage 1 (per partition):
  HashAggregate(keys=[region], functions=[partial_sum(event_count)])
  → Each partition produces partial sums locally

  Exchange hashpartitioning(region, 8)  ← shuffle partial results (small!)

Stage 2 (merge):
  HashAggregate(keys=[region], functions=[sum(event_count)])
  → Merges partial sums into final result
```

**Why it matters:** Partial aggregation reduces shuffle volume dramatically. If you have 1M rows with 100 distinct regions, you shuffle 100 partial sums instead of 1M rows.

### ObjectHashAggregate vs HashAggregate

| Strategy | When Used | Memory |
|----------|-----------|--------|
| `HashAggregate` | Primitive types (int, long, double) | Fixed-size hash map |
| `ObjectHashAggregate` | Complex types (arrays, maps, UDT) | Heap objects — slower, more GC |

---

## 5. Iceberg-Specific SQL Operations

### DDL (Data Definition Language)

```sql
-- Create with hidden partitioning
CREATE TABLE t USING iceberg PARTITIONED BY (days(ts), bucket(16, user_id));

-- Schema evolution
ALTER TABLE t ADD COLUMN region STRING;
ALTER TABLE t RENAME COLUMN old_name TO new_name;
ALTER TABLE t ALTER COLUMN x TYPE BIGINT;    -- widen int → bigint
ALTER TABLE t DROP COLUMN deprecated_col;

-- Partition evolution (Iceberg-only — metadata only, no rewrite)
ALTER TABLE t ADD PARTITION FIELD hours(ts);
ALTER TABLE t DROP PARTITION FIELD days(ts);
ALTER TABLE t REPLACE PARTITION FIELD days(ts) WITH hours(ts);
```

### DML (Data Manipulation Language)

```sql
-- Append
INSERT INTO t VALUES (1, 'a', current_timestamp());

-- Overwrite matching partitions
INSERT OVERWRITE t SELECT * FROM staging WHERE event_date = '2026-02-26';

-- Merge (upsert)
MERGE INTO t USING staging s
ON t.user_id = s.user_id AND t.event_date = s.event_date
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;

-- Delete
DELETE FROM t WHERE event_date < '2026-01-01';

-- Update
UPDATE t SET region = 'unknown' WHERE region IS NULL;
```

### Time Travel

```sql
-- By timestamp
SELECT * FROM t FOR SYSTEM_TIME AS OF '2026-02-25 14:00:00';
-- or
SELECT * FROM t TIMESTAMP AS OF '2026-02-25 14:00:00';

-- By snapshot ID
SELECT * FROM t VERSION AS OF 12345678901234;

-- Snapshot history
SELECT * FROM t.snapshots;

-- Changelog (what changed between snapshots)
SELECT * FROM t.changes BETWEEN 123 AND 456;
```

### Metadata Tables

```sql
SELECT * FROM t.snapshots;      -- snapshot history
SELECT * FROM t.history;        -- table history
SELECT * FROM t.files;          -- current data files
SELECT * FROM t.manifests;      -- manifest list
SELECT * FROM t.partitions;     -- partition statistics
SELECT * FROM t.all_data_files; -- all files (incl. deleted)
SELECT * FROM t.refs;           -- branches and tags
```

### Maintenance Procedures

```sql
-- Compact small files into larger ones
CALL catalog.system.rewrite_data_files(
    table => 'db.t',
    options => map('target-file-size-bytes', '134217728')  -- 128 MB
);

-- Sort-order compaction (Z-ORDER equivalent)
CALL catalog.system.rewrite_data_files(
    table => 'db.t',
    strategy => 'sort',
    sort_order => 'user_id, event_date'
);

-- Expire old snapshots (free storage)
CALL catalog.system.expire_snapshots(
    table => 'db.t',
    older_than => TIMESTAMP '2026-02-20 00:00:00',
    retain_last => 5
);

-- Remove orphan files (cleanup after failed writes)
CALL catalog.system.remove_orphan_files(
    table => 'db.t',
    older_than => TIMESTAMP '2026-02-20 00:00:00'
);

-- Rewrite manifests (optimize metadata)
CALL catalog.system.rewrite_manifests('db.t');
```

### Branching & Tagging (WAP Pattern)

```sql
-- Create a branch (for write-audit-publish)
ALTER TABLE t CREATE BRANCH audit_branch;

-- Write to the branch
INSERT INTO t.branch_audit_branch VALUES (...);

-- Validate, then promote
ALTER TABLE t EXECUTE fast_forward('main', 'audit_branch');

-- Create a tag (immutable reference point)
ALTER TABLE t CREATE TAG v1 AS OF VERSION 123;
```

---

## 6. Iceberg Partition Transforms

| Transform | SQL | Example Output | Best For |
|-----------|-----|---------------|----------|
| `identity` | `PARTITIONED BY (region)` | `"us-east-1"` | Low cardinality categorical columns |
| `days` | `PARTITIONED BY (days(ts))` | `2026-02-26` | Daily batch data |
| `hours` | `PARTITIONED BY (hours(ts))` | `2026-02-26-14` | Hourly streaming data |
| `months` | `PARTITIONED BY (months(ts))` | `2026-02` | Monthly aggregations |
| `years` | `PARTITIONED BY (years(ts))` | `2026` | Annual archives |
| `bucket(N)` | `PARTITIONED BY (bucket(16, id))` | `0`–`15` | High cardinality ID columns (distribute evenly) |
| `truncate(W)` | `PARTITIONED BY (truncate(10, name))` | `"alexand"` (first 10 chars) | String prefix grouping |

**Hidden partitioning:** Consumers don't need to know the transform — they write natural predicates (`WHERE ts = '2026-02-26 14:30:00'`) and Iceberg applies the correct partition filter.

---

## 7. AQE (Adaptive Query Execution)

```python
spark.conf.set("spark.sql.adaptive.enabled", "true")                    # Master switch
spark.conf.set("spark.sql.adaptive.coalescePartitions.enabled", "true") # Merge tiny partitions
spark.conf.set("spark.sql.adaptive.skewJoin.enabled", "true")           # Split hot partitions
spark.conf.set("spark.sql.adaptive.localShuffleReader.enabled", "true") # Avoid network when possible
```

| AQE Feature | What It Does | Plan Indicator |
|-------------|-------------|----------------|
| **Coalesce partitions** | Merges post-shuffle partitions that are too small | `CoalescedShuffleRead` |
| **Skew join** | Splits oversized partitions into sub-partitions | `SkewedJoin` |
| **Broadcast conversion** | Converts SMJ → BHJ at runtime if one side turns out small | `BroadcastHashJoin` (with `isFinalPlan=true`) |
| **Local shuffle read** | Reads shuffle data from local disk instead of network | `LocalShuffleReader` |

**Plan indicator:** `AdaptiveSparkPlan isFinalPlan=false` means AQE is active but hasn't finalized yet (plan may change at runtime based on statistics).

---

## 8. Quick Reference: Explain Plan Reading

```
result.explain(True)   # Shows all 4 plans
result.explain("cost") # Shows estimated row counts
```

| What to Find | Where to Look | Good | Bad |
|-------------|--------------|------|-----|
| Partition pruning | `BatchScan ... [filters=...]` | Date/key filters present | `groupedBy=` with no filters |
| Column pruning | `BatchScan [col1, col2]` | Only needed cols listed | All columns listed |
| Join strategy | `BroadcastHashJoin` / `SortMergeJoin` | BHJ for small dims | SMJ on 100-row table |
| Shuffle count | Count `Exchange` nodes | ≤ 2 per query | 5+ exchanges |
| Aggregation | `partial_sum` / `partial_count` | Partial agg before shuffle | Full agg after shuffle |
| AQE active | `AdaptiveSparkPlan` | `isFinalPlan=false` | No AQE wrapper |
| Skew | `SkewedJoin` | Present when needed | Absent with data skew |

---

## 9. Performance Anti-Patterns

| Anti-Pattern | Symptom | Fix |
|-------------|---------|-----|
| Missing partition filter | Full table scan; no `PartitionFilters` | Add WHERE clause on partition column |
| Small files | Thousands of `BatchScan` file opens | Run `rewrite_data_files` compaction |
| Broadcast too-large table | OOM on driver/executors | Lower `autoBroadcastJoinThreshold` or use SMJ |
| Too many shuffle partitions | Thousands of tiny tasks | Enable AQE coalescing or set `spark.sql.shuffle.partitions` lower |
| SortMergeJoin on small dim | Unnecessary shuffle + sort | Add `/*+ BROADCAST(dim) */` hint |
| Collect to driver | `SinglePartition` exchange | Use `take(N)` or `show()` instead of `collect()` |
| Non-equi join on large tables | CartesianProduct → $O(n^2)$ | Restructure as equi-join + post-filter |
| No predicate pushdown | Filters applied post-scan | Rewrite filter to use partition/pushdown-eligible columns |

---

*Part of the [Tecton Learning Series](./PART1_BENCHMARKING_AND_REGRESSION.md)*
