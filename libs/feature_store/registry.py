"""Feature View registry — declarative feature contracts with SLOs.

This module implements the Tecton-like "FeatureView" abstraction that bridges
the existing SHML feature tables (feature_eval, feature_training_lineage,
feature_dataset_quality, feature_hard_examples) into a unified contract layer.

Each FeatureView defines:
  - Entity keys (what the feature describes)
  - Schema (output columns and types)
  - Schedule (how often compute runs)
  - Freshness SLO (max acceptable staleness)
  - Owner (team or individual responsible)
  - Compute engine + source

The registry is stored in PostgreSQL (feature_views + feature_view_runs tables)
and queried by the SLO exporter for per-view freshness tracking.

Async implementation: uses asyncpg connection pool.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

import asyncpg
from pydantic import BaseModel, Field

logger = logging.getLogger("shml-features.registry")


# ---------------------------------------------------------------------------
# Core enums
# ---------------------------------------------------------------------------


class ComputeEngine(str, Enum):
    RAY = "ray"
    SPARK = "spark"
    SQL = "sql"


class FeatureViewStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DRAFT = "draft"


class MaterializationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Pydantic models (API / definition layer)
# ---------------------------------------------------------------------------


class EntityDefinition(BaseModel):
    """Primary key of a feature — what entity is being described."""

    name: str = Field(
        ..., description="Entity name, e.g. 'model_version', 'user', 'dataset'"
    )
    join_keys: list[str] = Field(
        ..., description="Column(s) that uniquely identify the entity"
    )
    description: str = Field("", description="Human-readable entity description")


class ColumnSchema(BaseModel):
    """One column in a feature view output."""

    name: str
    type: str = Field(
        ..., description="SQL type: TEXT, FLOAT, INT, JSONB, TIMESTAMPTZ, vector(N)"
    )
    description: str = ""


class FreshnessSLO(BaseModel):
    """Freshness guarantee for a feature view."""

    max_staleness_minutes: int = Field(..., description="Max acceptable age in minutes")
    target_percentile: float = Field(
        99.0, description="SLO target percentile (e.g. 99.0)"
    )
    error_budget_windows_per_month: int = Field(
        720, description="Eval windows per month"
    )


class FeatureViewDefinition(BaseModel):
    """Declarative definition of a feature view — the core contract."""

    name: str = Field(..., description="Unique feature view name")
    version: int = Field(1, description="Schema version")
    entity: EntityDefinition
    schema_columns: list[ColumnSchema] = Field(..., alias="schema")
    source_table: str = Field(..., description="Underlying Postgres table name")
    schedule: str = Field("@hourly", description="Cron schedule (or @hourly/@daily)")
    freshness_slo: FreshnessSLO
    compute_engine: ComputeEngine = ComputeEngine.RAY
    owner: str = Field("platform-team", description="Owning team or individual")
    description: str = ""
    status: FeatureViewStatus = FeatureViewStatus.ACTIVE
    tags: dict[str, str] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


class FeatureViewSummary(BaseModel):
    """Lightweight view returned by catalog endpoints."""

    name: str
    version: int
    entity_name: str
    entity_keys: list[str]
    source_table: str
    schedule: str
    freshness_slo_minutes: int
    owner: str
    status: str
    last_materialized_at: Optional[datetime] = None
    freshness_minutes: Optional[float] = None
    slo_met: Optional[bool] = None
    total_rows: Optional[int] = None


class MaterializationRun(BaseModel):
    """Record of one materialization execution."""

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    feature_view_name: str
    status: MaterializationStatus = MaterializationStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    rows_written: int = 0
    error_message: Optional[str] = None
    ray_job_id: Optional[str] = None
    mlflow_run_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Registry (asyncpg-backed, connection pool)
# ---------------------------------------------------------------------------


class FeatureRegistry:
    """Manages feature view definitions and materialization tracking.

    Tables:
      - feature_views: declarative definitions
      - feature_view_runs: materialization run history

    All public methods are async and use an asyncpg connection pool.
    Call ``await registry.init()`` before first use.
    """

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10):
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None

    async def init(self) -> None:
        """Create the connection pool and schema tables if needed."""
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
        )
        await self.init_schema()

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def __aenter__(self):
        await self.init()
        return self

    async def __aexit__(self, *_):
        await self.close()

    def _pool_or_raise(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError(
                "FeatureRegistry not initialised — call `await registry.init()` first"
            )
        return self._pool

    # ------ Schema init ------

    async def init_schema(self) -> None:
        """Create registry tables if they don't exist."""
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_views (
                    name TEXT PRIMARY KEY,
                    version INT NOT NULL DEFAULT 1,
                    entity_name TEXT NOT NULL,
                    entity_keys JSONB NOT NULL,
                    schema_columns JSONB NOT NULL,
                    source_table TEXT NOT NULL,
                    schedule TEXT NOT NULL DEFAULT '@hourly',
                    freshness_slo_minutes INT NOT NULL DEFAULT 60,
                    freshness_slo_percentile FLOAT NOT NULL DEFAULT 99.0,
                    error_budget_windows INT NOT NULL DEFAULT 720,
                    compute_engine TEXT NOT NULL DEFAULT 'ray',
                    owner TEXT NOT NULL DEFAULT 'platform-team',
                    description TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    tags JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_view_runs (
                    run_id TEXT PRIMARY KEY,
                    feature_view_name TEXT NOT NULL
                        REFERENCES feature_views(name),
                    status TEXT NOT NULL DEFAULT 'pending',
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    rows_written INT DEFAULT 0,
                    error_message TEXT,
                    ray_job_id TEXT,
                    mlflow_run_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fvr_view_name
                ON feature_view_runs(feature_view_name, created_at DESC)
                """
            )
        logger.info("Feature registry schema initialised")

    # ------ CRUD ------

    async def register(self, defn: FeatureViewDefinition) -> None:
        """Register or update a feature view definition."""
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO feature_views
                    (name, version, entity_name, entity_keys, schema_columns,
                     source_table, schedule, freshness_slo_minutes,
                     freshness_slo_percentile, error_budget_windows,
                     compute_engine, owner, description, status, tags)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15)
                ON CONFLICT (name) DO UPDATE SET
                    version = EXCLUDED.version,
                    entity_name = EXCLUDED.entity_name,
                    entity_keys = EXCLUDED.entity_keys,
                    schema_columns = EXCLUDED.schema_columns,
                    source_table = EXCLUDED.source_table,
                    schedule = EXCLUDED.schedule,
                    freshness_slo_minutes = EXCLUDED.freshness_slo_minutes,
                    freshness_slo_percentile = EXCLUDED.freshness_slo_percentile,
                    error_budget_windows = EXCLUDED.error_budget_windows,
                    compute_engine = EXCLUDED.compute_engine,
                    owner = EXCLUDED.owner,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    tags = EXCLUDED.tags,
                    updated_at = NOW()
                """,
                defn.name,
                defn.version,
                defn.entity.name,
                json.dumps(defn.entity.join_keys),
                json.dumps([c.model_dump() for c in defn.schema_columns]),
                defn.source_table,
                defn.schedule,
                defn.freshness_slo.max_staleness_minutes,
                defn.freshness_slo.target_percentile,
                defn.freshness_slo.error_budget_windows_per_month,
                defn.compute_engine.value,
                defn.owner,
                defn.description,
                defn.status.value,
                json.dumps(defn.tags),
            )
        logger.info("Registered feature view: %s (v%d)", defn.name, defn.version)

    async def get(self, name: str) -> Optional[dict]:
        """Get a feature view definition by name."""
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM feature_views WHERE name = $1", name
            )
        return dict(row) if row else None

    async def list_views(self, status: Optional[str] = None) -> list[FeatureViewSummary]:
        """List all feature views with current freshness status."""
        pool = self._pool_or_raise()
        query = """
            SELECT
                fv.name,
                fv.version,
                fv.entity_name,
                fv.entity_keys,
                fv.source_table,
                fv.schedule,
                fv.freshness_slo_minutes,
                fv.owner,
                fv.status,
                (SELECT MAX(completed_at) FROM feature_view_runs
                 WHERE feature_view_name = fv.name AND status = 'succeeded')
                    AS last_materialized_at
            FROM feature_views fv
        """
        if status:
            query += " WHERE fv.status = $1 ORDER BY fv.name"
        else:
            query += " ORDER BY fv.name"

        async with pool.acquire() as conn:
            rows = (
                await conn.fetch(query, status)
                if status
                else await conn.fetch(query)
            )

        now = datetime.now(timezone.utc)
        summaries = []
        for row in rows:
            last_mat = row["last_materialized_at"]
            freshness = None
            slo_met = None
            if last_mat:
                if last_mat.tzinfo is None:
                    last_mat = last_mat.replace(tzinfo=timezone.utc)
                freshness = round((now - last_mat).total_seconds() / 60.0, 1)
                slo_met = freshness <= row["freshness_slo_minutes"]

            total_rows = await self._get_table_row_count(row["source_table"])
            entity_keys = row["entity_keys"]
            if isinstance(entity_keys, str):
                entity_keys = json.loads(entity_keys)

            summaries.append(
                FeatureViewSummary(
                    name=row["name"],
                    version=row["version"],
                    entity_name=row["entity_name"],
                    entity_keys=entity_keys,
                    source_table=row["source_table"],
                    schedule=row["schedule"],
                    freshness_slo_minutes=row["freshness_slo_minutes"],
                    owner=row["owner"],
                    status=row["status"],
                    last_materialized_at=last_mat,
                    freshness_minutes=freshness,
                    slo_met=slo_met,
                    total_rows=total_rows,
                )
            )
        return summaries

    async def _get_table_row_count(self, table_name: str) -> Optional[int]:
        """Get approximate row count for a source table (pg_class fast path)."""
        pool = self._pool_or_raise()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT reltuples::BIGINT AS n FROM pg_class WHERE relname = $1",
                    table_name,
                )
            return int(row["n"]) if row and row["n"] >= 0 else None
        except Exception:
            return None

    async def delete(self, name: str) -> bool:
        """Delete a feature view and its run history."""
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM feature_view_runs WHERE feature_view_name = $1",
                    name,
                )
                result = await conn.execute(
                    "DELETE FROM feature_views WHERE name = $1", name
                )
        return result.endswith("1")

    # ------ Materialization tracking ------

    async def record_run_start(self, run: MaterializationRun) -> None:
        """Record the start of a materialization run."""
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO feature_view_runs
                    (run_id, feature_view_name, status, started_at,
                     ray_job_id, mlflow_run_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                run.run_id,
                run.feature_view_name,
                run.status.value,
                run.started_at or datetime.now(timezone.utc),
                run.ray_job_id,
                run.mlflow_run_id,
            )

    async def record_run_complete(
        self,
        run_id: str,
        status: MaterializationStatus,
        rows_written: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """Record the completion of a materialization run."""
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE feature_view_runs
                SET status = $1,
                    completed_at = $2,
                    rows_written = $3,
                    error_message = $4
                WHERE run_id = $5
                """,
                status.value,
                datetime.now(timezone.utc),
                rows_written,
                error_message,
                run_id,
            )

    async def get_run_history(
        self,
        feature_view_name: str,
        limit: int = 20,
    ) -> list[dict]:
        """Get materialization run history for a feature view."""
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM feature_view_runs
                WHERE feature_view_name = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                feature_view_name,
                limit,
            )
        return [dict(r) for r in rows]

    async def get_freshness_per_view(self) -> list[dict]:
        """Freshness metrics for all active views — used by SLO exporter."""
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    fv.name,
                    fv.freshness_slo_minutes AS slo_minutes,
                    (SELECT MAX(completed_at) FROM feature_view_runs
                     WHERE feature_view_name = fv.name AND status = 'succeeded')
                        AS last_materialized_at
                FROM feature_views fv
                WHERE fv.status = 'active'
                """
            )

        now = datetime.now(timezone.utc)
        results = []
        for row in rows:
            last_mat = row["last_materialized_at"]
            freshness = None
            slo_met = None
            if last_mat:
                if last_mat.tzinfo is None:
                    last_mat = last_mat.replace(tzinfo=timezone.utc)
                freshness = round((now - last_mat).total_seconds() / 60.0, 1)
                slo_met = freshness <= row["slo_minutes"]
            results.append(
                {
                    "name": row["name"],
                    "freshness_minutes": freshness,
                    "slo_minutes": row["slo_minutes"],
                    "slo_met": slo_met,
                    "last_materialized_at": last_mat,
                }
            )
        return results

    async def query_source_table(
        self,
        source_table: str,
        where_parts: list[str],
        params: list[Any],
        columns: Optional[list[str]] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Generic SELECT from a source feature table.

        Args:
            source_table: Feature source table name (validated by callers).
            where_parts:  List of ``column = $N`` clauses (already numbered).
            params:       Positional parameter values matching $N placeholders.
            columns:      Specific column names (None = SELECT *).
            limit:        Max rows to return.

        Returns:
            List of row dicts with datetime values serialised to ISO strings.
        """
        pool = self._pool_or_raise()
        select_cols = ", ".join(columns) if columns else "*"
        next_n = len(params) + 1
        where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        query = (
            f"SELECT {select_cols} FROM {source_table} "
            f"{where_sql} ORDER BY created_at DESC LIMIT ${next_n}"
        )
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params, limit)
        result = []
        for row in rows:
            d = dict(row)
            for k, v in d.items():
                if isinstance(v, datetime):
                    d[k] = v.isoformat()
            result.append(d)
        return result
