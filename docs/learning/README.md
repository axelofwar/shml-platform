# Tecton Interview Prep — Engineering Learning Series

**Purpose:** A four-part educational reference built alongside the SHML platform execution board. Each part maps directly to a skill gap identified in the [Tecton fit analysis](../tecton_fit_analysis_and_skill_plan.md) and is grounded in real code, real metrics, and real infrastructure decisions made during the 6-week sprint.

**How to use this:**
- Read each part before or after implementing the corresponding execution board item
- Use the "Interview Angles" sections to practice verbal explanations of each concept
- Reference the "Your Platform Evidence" sections when crafting resume bullets or answering "tell me about a time…" questions
- The code snippets reference real files in `shml-platform/` — open them side by side

---

## Series Index

| Part | Title | Execution Board Items | Skill Gaps Addressed |
|------|-------|-----------------------|----------------------|
| [Part 1](PART1_BENCHMARKING_AND_REGRESSION.md) | Benchmarking, Regression Gates & MLflow Governance | EB-01 | Measurement discipline, MLflow artifact policy, regression framework design |
| [Part 2](PART2_DISTRIBUTED_COMPUTE_ENGINES.md) | Distributed Compute: Ray vs Spark | EB-02 | Spark platform depth, engine tradeoffs, shuffle vs task parallelism |
| [Part 3](PART3_TABLE_FORMATS_AND_QUERY_OPTIMIZATION.md) | Table Formats & Query Optimization | EB-03, EB-04 | Iceberg/Delta internals, schema evolution, explain plans, partition pruning |
| [Part 4](PART4_FEATURE_PLATFORM_DESIGN.md) | Feature Platform Design & SLOs | EB-05 | Feature store architecture, freshness guarantees, offline/online consistency |

---

## Mapping to Tecton Job Description

The Tecton Senior Batch Data role requires depth in five areas. This series covers each:

```
┌─────────────────────────────────┐     ┌──────────────────────┐
│  Tecton Requirement             │ ──► │  Learning Series     │
├─────────────────────────────────┤     ├──────────────────────┤
│  Spark platform depth           │     │  Part 2              │
│  Query optimization             │     │  Part 3              │
│  Iceberg/Delta production ops   │     │  Part 3              │
│  Feature platform product sense │     │  Part 4              │
│  Measurement + reliability      │     │  Part 1              │
└─────────────────────────────────┘     └──────────────────────┘
```

## Prerequisites

- Familiarity with Python, SQL, and Docker
- Access to the SHML platform (Ray cluster, MLflow, PostgreSQL, Traefik/OAuth)
- The `.venv` at `/home/axelofwar/Projects/.venv` with `mlflow`, `ray`, `pyspark` installed
