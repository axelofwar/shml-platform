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
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

import psycopg2
import psycopg2.extras
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
# Registry (Postgres-backed)
# ---------------------------------------------------------------------------


class FeatureRegistry:
    """Manages feature view definitions and materialization tracking.

    Tables:
      - feature_views: declarative definitions
      - feature_view_runs: materialization run history
    """

    def __init__(self, pg_config: dict[str, Any]):
        self._pg_config = pg_config
        self._conn: Optional[psycopg2.extensions.connection] = None

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._pg_config)
        return self._conn

    # ------ Schema init ------

    def init_schema(self) -> None:
        """Create registry tables if they don't exist."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
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
                );
            """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_view_runs (
                    run_id TEXT PRIMARY KEY,
                    feature_view_name TEXT NOT NULL REFERENCES feature_views(name),
                    status TEXT NOT NULL DEFAULT 'pending',
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    rows_written INT DEFAULT 0,
                    error_message TEXT,
                    ray_job_id TEXT,
                    mlflow_run_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fvr_view_name
                ON feature_view_runs(feature_view_name, created_at DESC);
            """
            )

            conn.commit()
            logger.info("Feature registry schema initialized")

    # ------ CRUD ------

    def register(self, defn: FeatureViewDefinition) -> None:
        """Register or update a feature view definition."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feature_views
                    (name, version, entity_name, entity_keys, schema_columns,
                     source_table, schedule, freshness_slo_minutes,
                     freshness_slo_percentile, error_budget_windows,
                     compute_engine, owner, description, status, tags)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                (
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
                ),
            )
            conn.commit()
            logger.info("Registered feature view: %s (v%d)", defn.name, defn.version)

    def get(self, name: str) -> Optional[dict]:
        """Get a feature view definition by name."""
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM feature_views WHERE name = %s", (name,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_views(self, status: Optional[str] = None) -> list[FeatureViewSummary]:
        """List all feature views with current freshness status."""
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Join with source tables to compute freshness
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
            params: list = []
            if status:
                query += " WHERE fv.status = %s"
                params.append(status)
            query += " ORDER BY fv.name"

            cur.execute(query, params)
            rows = cur.fetchall()

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

            # Try to get row count from source table
            total_rows = self._get_table_row_count(row["source_table"])

            summaries.append(
                FeatureViewSummary(
                    name=row["name"],
                    version=row["version"],
                    entity_name=row["entity_name"],
                    entity_keys=(
                        row["entity_keys"]
                        if isinstance(row["entity_keys"], list)
                        else json.loads(row["entity_keys"])
                    ),
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

    def _get_table_row_count(self, table_name: str) -> Optional[int]:
        """Get approximate row count for a source table."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                # Use reltuples for fast approximate count
                cur.execute(
                    "SELECT reltuples::BIGINT FROM pg_class WHERE relname = %s",
                    (table_name,),
                )
                row = cur.fetchone()
                return int(row[0]) if row and row[0] >= 0 else None
        except Exception:
            return None

    def delete(self, name: str) -> bool:
        """Delete a feature view and its run history."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM feature_view_runs WHERE feature_view_name = %s", (name,)
            )
            cur.execute("DELETE FROM feature_views WHERE name = %s", (name,))
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    # ------ Materialization tracking ------

    def record_run_start(self, run: MaterializationRun) -> None:
        """Record the start of a materialization run."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feature_view_runs
                    (run_id, feature_view_name, status, started_at, ray_job_id, mlflow_run_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    run.run_id,
                    run.feature_view_name,
                    run.status.value,
                    run.started_at or datetime.now(timezone.utc),
                    run.ray_job_id,
                    run.mlflow_run_id,
                ),
            )
            conn.commit()

    def record_run_complete(
        self,
        run_id: str,
        status: MaterializationStatus,
        rows_written: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """Record the completion of a materialization run."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE feature_view_runs
                SET status = %s,
                    completed_at = %s,
                    rows_written = %s,
                    error_message = %s
                WHERE run_id = %s
            """,
                (
                    status.value,
                    datetime.now(timezone.utc),
                    rows_written,
                    error_message,
                    run_id,
                ),
            )
            conn.commit()

    def get_run_history(
        self,
        feature_view_name: str,
        limit: int = 20,
    ) -> list[dict]:
        """Get materialization run history for a feature view."""
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM feature_view_runs
                WHERE feature_view_name = %s
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (feature_view_name, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_freshness_per_view(self) -> list[dict]:
        """Get freshness metrics for all active views — used by SLO exporter.

        Returns a list of dicts with keys:
          name, freshness_minutes, slo_minutes, slo_met, last_materialized_at
        """
        conn = self._get_conn()
        now = datetime.now(timezone.utc)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
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
            rows = cur.fetchall()

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

    # ------ Cleanup ------

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
