# Part 4: Feature Platform Design & SLOs

*Execution Board Item: EB-05 — Feature Platform Mini-Slice (Tecton-Like)*

---

## Why This Matters

Tecton **is** a feature platform. If you're interviewing for a senior batch data role there, you need to understand not just how to run Spark jobs, but why those jobs exist — they compute features. The questions that matter at a feature platform company aren't "how do I make this Spark job faster?" but "how do I guarantee that features are fresh, correct, and available for every model prediction?"

This part connects everything from Parts 1-3 into the product that Tecton ships: a system that computes, stores, and serves ML features with reliability guarantees.

---

## What Is a Feature Platform?

### The Problem It Solves

Every ML model needs features — computed values derived from raw data. Without a platform, every team reinvents feature engineering:

```
Team A: "We compute user_spend from the payments table in our training notebook"
Team B: "We also compute user_spend but from the billing table — slightly different logic"
Team C: "We copy Team A's code but run it in a different environment"

Result:
- Training/serving skew (notebook logic ≠ production logic)
- Duplicated compute (3 teams computing similar features independently)
- No freshness guarantees (features computed "whenever the notebook runs")
- No monitoring (nobody knows when features are stale)
```

### The Feature Platform Solution

```
┌─────────────────────────────────────────────────────────────┐
│  Feature Platform                                            │
│                                                              │
│  ┌───────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  Feature       │    │  Compute     │    │  Serving     │  │
│  │  Definitions   │───▶│  Engine      │───▶│  Layer       │  │
│  │                │    │              │    │              │  │
│  │  - Entity keys │    │  - Batch     │    │  - Online    │  │
│  │  - Transform   │    │    (Spark)   │    │    (low-lat) │  │
│  │  - Schedule    │    │  - Stream    │    │  - Offline   │  │
│  │  - Freshness   │    │    (Flink)   │    │    (batch)   │  │
│  │    SLO         │    │  - On-demand │    │              │  │
│  └───────────────┘    │    (Ray)     │    └──────────────┘  │
│                        └──────────────┘                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Metadata + Monitoring                                 │  │
│  │  - Feature catalog  - Freshness dashboards             │  │
│  │  - Lineage          - SLO alerts                       │  │
│  │  - Access control   - Data quality checks              │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**The platform provides:**
1. **Single definition:** One place to define `user_spend`, used by all teams
2. **Compute orchestration:** The platform runs the computation on schedule
3. **Dual serving:** Same features available for batch training and real-time inference
4. **Freshness guarantees:** SLOs that promise "features are at most 1 hour old"
5. **Monitoring:** Dashboards that show feature health, staleness, and data quality

---

## Core Abstractions

### 1. Entity

An entity is the "primary key" of a feature — the thing being described.

```python
# Entity: What are we computing features for?
class Entity:
    name: str           # e.g., "user", "driver", "listing"
    join_keys: list      # e.g., ["user_id"], ["driver_id", "city"]
    description: str
```

**Examples:**
| Entity | Join Keys | Feature Examples |
|--------|-----------|-----------------|
| `user` | `[user_id]` | total_spend, login_count, avg_session_length |
| `driver` | `[driver_id]` | trips_last_7d, avg_rating, cancellation_rate |
| `listing` | `[listing_id]` | views_last_24h, booking_rate, price_percentile |

### 2. Feature View

A feature view defines **what** to compute and **how often**:

```python
class FeatureView:
    name: str                    # e.g., "user_activity_features"
    entity: Entity               # What entity this is for
    schema: list                 # Output columns
    source: DataSource           # Where raw data comes from
    transformation: Callable     # The compute logic
    schedule: str                # How often to run ("@hourly", "@daily")
    freshness_slo: timedelta     # Maximum allowed staleness
    owner: str                   # Team/person responsible
```

**Key insight:** The feature view is a **contract**. It promises:
- "I will produce these columns for this entity"
- "I will run at this schedule"
- "Results will be at most this stale"
- "This person is responsible if it breaks"

> **Interview angle:** "A feature view is the unit of ownership in a feature platform. It's analogous to a microservice contract — it declares its interface (schema), its SLO (freshness), and its owner. When something breaks, you know exactly which feature view is affected and who to page."

### 3. Feature Table (Storage)

Where computed features land. This is where Iceberg (Part 3) plugs in:

```
Feature View (compute)  ──writes──▶  Feature Table (Iceberg)  ──serves──▶  Consumers

Feature Table structure:
┌─────────────┬────────────┬─────────────┬────────────┬──────────────────┐
│  user_id    │  total_spend│  login_count│  event_date│  _processed_at   │
├─────────────┼────────────┼─────────────┼────────────┼──────────────────┤
│  user_001   │  1523.40   │  47         │  2026-02-26│  2026-02-26 14:00│
│  user_002   │  89.20     │  12         │  2026-02-26│  2026-02-26 14:00│
└─────────────┴────────────┴─────────────┴────────────┴──────────────────┘
  ↑ join key     ↑ features                  ↑ partition    ↑ metadata
```

**Why Iceberg for feature tables:**
- **Schema evolution:** Add new features without reprocessing history
- **Time travel:** Reconstruct training datasets from any point in time
- **Partition evolution:** Start daily, move to hourly as data grows
- **Compaction:** Keep read latency low for online serving reads

---

## SLOs (Service Level Objectives)

### What Are Feature SLOs?

An SLO is a measurable promise about system behavior. For features:

| SLO | Definition | Example Target | Why It Matters |
|-----|-----------|---------------|----------------|
| **Freshness** | Maximum age of feature data | ≤ 60 minutes | Stale features → bad predictions |
| **Availability** | Uptime of feature serving | ≥ 99.9% | Missing features → failed predictions |
| **Completeness** | % of entities with values | ≥ 99.5% | Missing entities → model fallbacks |
| **Latency** | P99 serving response time | ≤ 50ms (online) | Slow features → slow user experience |

### Freshness: The Most Important SLO

Freshness is the gap between "when the data happened" and "when the feature reflects it":

```
Event occurs       Feature computed      Feature served
     │                    │                    │
     ├────────────────────┤                    │
     │   Processing lag   │                    │
     │   (compute time)   ├────────────────────┤
     │                    │   Serving lag       │
     ├────────────────────┴────────────────────┤
     │            Total freshness              │
     │            (must be < SLO)              │
```

**Freshness = processing lag + serving lag**

- **Processing lag:** How long batch compute takes (runtime from your Week 1 benchmarks)
- **Serving lag:** How long until computed results are queryable (depends on commit + cache invalidation)

**Your Week 1 data makes this concrete:**

| Workload Size | Runtime (s) | If scheduled hourly, freshness = |
|--------------|------------|----------------------------------|
| S (10K rows) | 38s | 38s + serving lag ≈ **~1 min** (well within 60-min SLO) |
| M (100K rows) | 146s | 146s + serving lag ≈ **~3 min** (comfortably within SLO) |
| L (500K rows) | 615s | 615s + serving lag ≈ **~11 min** (within SLO but tighter) |

If your workload grows to 2M rows and runtime scales to 2400s (40 min), you're consuming 67% of your 60-minute freshness budget on compute alone. This is when you need to optimize (EB-04) or partition the workload across more resources.

### Error Budgets

An error budget is "how much SLO violation is acceptable per month":

```
SLO: 99.9% availability = 43.2 minutes of downtime per month

Month so far: 2 incidents × 10 min each = 20 min consumed
Remaining budget: 23.2 minutes

Decision: Can I do a risky deployment? With 23 min of budget left, probably yes.
          With 3 min left? Definitely no — wait until next month.
```

The same logic applies to freshness:

```
SLO: Features fresh within 60 minutes, 99% of the time
Error budget: 1% × 720 hourly windows = 7.2 windows can be late per month

If you've already been late 6 times this month, you should NOT experiment
with new Spark configs — fix stability first.
```

> **Interview angle:** "Error budgets turn reliability from a vague goal into a resource allocation problem. When the budget is large, we innovate — try new engines, new partitioning strategies. When the budget is small, we stabilize — harden the pipeline, add retries, reduce variance. This is SRE thinking applied to data pipelines."

---

## Building the Mini-Slice (EB-05)

### What We're Building

A minimal but complete feature pipeline that demonstrates the entire lifecycle:

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌───────────┐
│  Raw Events  │────▶│  Feature     │────▶│  Iceberg     │────▶│  Retrieval│
│  (source)    │     │  Transform   │     │  Table       │     │  API      │
│              │     │  (Spark/Ray) │     │  (offline    │     │           │
│              │     │              │     │   store)     │     │           │
└─────────────┘     └──────────────┘     └──────────────┘     └───────────┘
                           │                     │
                           ▼                     ▼
                    ┌──────────────┐     ┌──────────────┐
                    │  MLflow      │     │  Grafana     │
                    │  (lineage)   │     │  (SLO        │
                    │              │     │   dashboard) │
                    └──────────────┘     └──────────────┘
```

### Components

**1. Feature Definition**

```python
user_activity_features = FeatureView(
    name="user_activity_features",
    entity=Entity(name="user", join_keys=["user_id"]),
    schema=[
        ("total_events", "BIGINT"),
        ("unique_event_types", "INT"),
        ("total_spend", "DOUBLE"),
        ("avg_spend_per_event", "DOUBLE"),
        ("last_activity_date", "DATE"),
    ],
    source="raw_events",           # Source table or topic
    schedule="@hourly",            # Compute every hour
    freshness_slo=timedelta(minutes=60),
    owner="platform-team",
)
```

**2. Feature Transform (the Spark/Ray job)**

```python
def compute_user_activity_features(spark, source_table, target_table, event_date):
    """Compute user activity features for a given date."""
    raw = spark.read.table(source_table).filter(col("event_date") == event_date)

    features = raw.groupBy("user_id").agg(
        count("*").alias("total_events"),
        countDistinct("event_type").alias("unique_event_types"),
        sum("amount").alias("total_spend"),
        (sum("amount") / count("*")).alias("avg_spend_per_event"),
        max("event_date").alias("last_activity_date"),
    )

    # Write-Audit-Publish pattern
    features.writeTo(target_table) \
        .option("merge-schema", "true") \
        .append()

    return features.count()
```

**3. SLO Monitoring (Prometheus + Grafana)**

```python
# Push freshness and completeness metrics after each compute
from prometheus_client import Gauge, push_to_gateway

feature_freshness = Gauge(
    'feature_freshness_seconds',
    'Seconds since feature was last computed',
    ['feature_view']
)

feature_completeness = Gauge(
    'feature_completeness_ratio',
    'Fraction of entities with non-null feature values',
    ['feature_view']
)

feature_compute_duration = Gauge(
    'feature_compute_duration_seconds',
    'Time taken to compute features',
    ['feature_view']
)

def report_slo_metrics(feature_view_name, compute_seconds, entity_count, null_count):
    feature_freshness.labels(feature_view=feature_view_name).set(compute_seconds)
    feature_completeness.labels(feature_view=feature_view_name).set(
        (entity_count - null_count) / entity_count
    )
    feature_compute_duration.labels(feature_view=feature_view_name).set(compute_seconds)
    push_to_gateway('pushgateway:9091', job='feature_compute', registry=registry)
```

**4. Grafana Dashboard Panels**

| Panel | Metric | Alert Threshold |
|-------|--------|-----------------|
| Feature Freshness | `feature_freshness_seconds` | > 3600 (60 min SLO) |
| Feature Completeness | `feature_completeness_ratio` | < 0.995 (99.5% SLO) |
| Compute Duration Trend | `feature_compute_duration_seconds` | > 2400 (budget ceiling) |
| Error Budget Burn | `slo_violations / budget` | > 80% |

---

## Offline vs Online: The Consistency Problem

### The Split

Feature platforms serve features in two modes:

| Mode | Use Case | Latency | Storage |
|------|----------|---------|---------|
| **Offline** | Model training, batch inference | Seconds–minutes | Iceberg/Delta table |
| **Online** | Real-time prediction serving | < 50ms p99 | Redis, DynamoDB, Bigtable |

### The Consistency Guarantee

Training data and serving data must come from the **same computation**:

```
❌ WRONG:
  Training: SELECT features FROM offline_table  (computed by Spark daily)
  Serving:  SELECT features FROM online_cache   (computed by streaming job)
  → Different code paths = different values = training/serving skew

✓ RIGHT:
  Computation: Spark job produces features
  Write: Same result written to both offline (Iceberg) and online (Redis)
  Training: Reads from Iceberg (time-travel to training date)
  Serving: Reads from Redis (latest values)
  → Same code, same values, no skew
```

**This is the hardest problem in feature platforms.** Tecton's core value proposition is solving this consistency problem. Understanding it deeply is the highest-signal interview topic.

> **Interview angle:** "Training/serving skew is the most common source of silent model quality degradation. A feature platform eliminates it by ensuring that training reads (offline) and serving reads (online) come from the same materializer output. The feature view abstraction guarantees that the same transformation logic produces both offline and online values."

---

## Putting It All Together: The Feature Lifecycle

```
1. DEFINE
   Feature View → schema, entity, transform, schedule, SLO

2. COMPUTE
   Scheduler triggers → Spark/Ray job runs → produces feature DataFrame

3. VALIDATE
   Data quality checks: null rate, value distribution, row count delta

4. PUBLISH
   Atomic write to Iceberg (offline) + sync to Redis (online)

5. SERVE
   Training pipeline reads from Iceberg (point-in-time query)
   Serving API reads from Redis (latest values)

6. MONITOR
   Freshness gauge → Grafana panel → alert if > SLO
   Completeness gauge → alert if < 99.5%
   Compute duration → alert if approaching freshness budget

7. MAINTAIN
   Iceberg compaction → keep read latency low
   Snapshot expiry → manage storage costs
   Schema evolution → add new features without downtime
```

**Each step maps to something we've built:**
- Steps 1-2: EB-02 (Spark compute path)
- Steps 3-4: EB-03 (Iceberg writes with WAP pattern)
- Steps 5-6: EB-05 (serving + monitoring)
- Step 7: EB-03 (compaction + maintenance)

---

## Key Patterns for Interview Prep

### Pattern: Backfill Governance

When you add a new feature or fix a bug, you need to recompute historical values (backfill). Uncontrolled backfills cause:
- Resource contention (backfill jobs compete with production jobs)
- Stale reads (consumers reading partially-backfilled data)
- Cost spikes (reprocessing months of data)

**Governed backfill approach:**
1. Declare backfill window: "Recompute 2026-01-01 to 2026-02-26"
2. Use isolated compute resources (separate Spark pool or Ray namespace)
3. Write to staging snapshot (Iceberg branch), not production
4. Validate completeness and quality on staging
5. Atomic merge of staging into production

### Pattern: Feature Ownership Model

| Role | Responsibility |
|------|---------------|
| **Feature owner** | Defines the feature view, owns transform logic, responds to SLO violations |
| **Platform team** | Operates compute infrastructure, manages catalogs, maintains serving layer |
| **Consumer (ML team)** | Requests features, defines training dataset requirements, reports quality issues |

### Pattern: Point-in-Time Correctness

When constructing a training dataset, you must join features **as of the label timestamp**, not the current timestamp:

```sql
-- ❌ WRONG: Uses current feature values for all training examples
SELECT labels.*, features.*
FROM labels JOIN features ON labels.user_id = features.user_id

-- ✓ RIGHT: Uses feature values as they existed at label time
SELECT labels.*, features.*
FROM labels
JOIN features
  FOR SYSTEM_TIME AS OF labels.event_timestamp
ON labels.user_id = features.user_id
```

This is Iceberg time travel applied to training dataset construction. Without it, you have **data leakage** — the model trains on future information.

---

## Exercises

1. **Design a feature view** for a feature you'd use in a real model. Define: entity, join keys, schema, schedule, freshness SLO. What's the freshness budget breakdown (compute time + serving lag)?

2. **Calculate an error budget:** Your freshness SLO is 60 minutes, 99% of the time. You run hourly. How many late runs per month can you tolerate? If your L-size benchmark takes 615s, what's your slack?

3. **Identify training/serving skew:** Given a feature computed by a daily batch job and served from a cache updated by a streaming job, list three ways the values could diverge. How does a feature platform prevent each?

4. **Design the monitoring dashboard:** What Grafana panels would you build to monitor the feature pipeline? What alert thresholds would you set? What's the escalation path when freshness exceeds SLO?

---

### Part 4 Exercise Answers (Executed 2026-02-28)

All answers computed via [`scripts/benchmarking/part4_exercises.py`](../../shml-platform/scripts/benchmarking/part4_exercises.py) using actual EB-02 benchmark data.

#### Exercise 1 — Feature View Design

**Feature:** `user_activity_features_v1`

| Property | Value |
|----------|-------|
| Entity | `user` (join key: `user_id`) |
| Schedule | `@hourly` |
| Freshness SLO | 60 minutes (99th percentile) |
| Compute engine | Spark (EB-02 validated) |

**Schema:** `total_events_7d` (BIGINT), `unique_event_types` (INT), `total_spend_7d` (DOUBLE), `avg_spend_per_event` (DOUBLE), `last_activity_date` (DATE), `purchase_ratio` (DOUBLE)

**Freshness budget (actual EB-02 data):**

```
Compute time (M workload, 1M rows):  46.6s
Serving lag (commit + cache):        30.0s
Total freshness:                     76.6s (1.3 min)
Budget (60 min SLO):                 3600s
Utilization:                         2.1%
Growth ceiling:                      ~77M rows before budget breach
```

#### Exercise 2 — Error Budget

```
SLO:                 60-min freshness, 99% compliance
Schedule:            hourly → 720 windows/month
Error budget:        1% × 720 = 7.2 → 7 late runs/month (~1.8/week)

With L workload (244s actual from EB-02):
  Total freshness:   274.4s (4.6 min)
  Budget utilization: 7.6%
  Slack:             3325.6s (92.4%)
  Danger zone:       runtime > 2850s (47.5 min)

If runtime doubles:  518.8s → slack = 3081.2s ✅ still safe
Runtime must reach ~12× current before SLO breach
```

#### Exercise 3 — Training/Serving Skew

| Skew Type | Cause | Impact | Platform Fix |
|-----------|-------|--------|-------------|
| **Logic divergence** | Batch SQL ≠ streaming code (e.g., refund exclusion) | Systematic prediction bias | Single FeatureView → one transform, dual write |
| **Temporal divergence** | Batch uses yesterday's window; cache has real-time | Training/production performance mismatch | Point-in-time reads via Iceberg `FOR SYSTEM_TIME AS OF` |
| **Schema divergence** | Batch schema evolves; cache schema stale | Feature values off by orders of magnitude | Iceberg schema IDs; atomic dual-store migration |

**Root cause:** All 3 share one anti-pattern — separate code paths for training and serving. A feature platform eliminates this with a single FeatureView definition that materializes to both offline (Iceberg) and online (Redis) stores.

#### Exercise 4 — Monitoring Dashboard

| Panel | Metric | P1 Alert | Warning |
|-------|--------|----------|--------|
| Feature Freshness | `freshness_seconds / 60` | > 60 min | > 48 min (80% budget) |
| Completeness | `completeness_ratio × 100` | < 99.5% | < 99.8% |
| Compute Duration | `compute_duration_seconds` | > 2400s (67% budget) | Trend slope > 5s/day |
| Error Budget Burn | `violations / budget` | > 80% (freeze changes) | > 50% |
| Data Quality | `null_rate per column` | Any col > 5% nulls | New col > 0% nulls |
| Throughput | `rows / duration` | < 50% of baseline | < 80% of baseline |

**Escalation:** P1 → page on-call (<15 min), P2 → investigate (<1 hr), P3 → business hours (<4 hr), P4 → next sprint

---

*Previous: [← Part 3: Table Formats & Query Optimization](PART3_TABLE_FORMATS_AND_QUERY_OPTIMIZATION.md)*

---

## Series Complete

You now have a reference that covers:
- **Part 1:** Why and how to measure things (benchmarking, regression, MLflow governance)
- **Part 2:** How distributed compute engines work and when to choose each (Ray vs Spark)
- **Part 3:** How table formats solve real data problems (Iceberg, schema evolution, query optimization)
- **Part 4:** How feature platforms tie it all together (SLOs, freshness, consistency)

Each part connects to a specific execution board item. As you implement EB-02 through EB-05, revisit the relevant part — the concepts will become concrete when you see them in your own metrics and code.
