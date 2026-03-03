"""Feature Serving API — REST endpoints for the SHML Feature Platform.

Provides:
  - Feature catalog: list/get/register feature views
  - Feature retrieval: query feature values by entity key
  - Materialization: trigger and track materialization runs
  - Freshness: per-view SLO status

Mounts as a router on the Ray Compute API (server_v2.py).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .registry import (
    FeatureRegistry,
    FeatureViewDefinition,
    FeatureViewSummary,
    MaterializationRun,
    MaterializationStatus,
)
from .definitions import get_pg_config, register_builtin_views

logger = logging.getLogger("shml-features.api")

router = APIRouter(tags=["features"])

# ---------------------------------------------------------------------------
# Singleton registry
# ---------------------------------------------------------------------------

_registry: FeatureRegistry | None = None


def get_registry() -> FeatureRegistry:
    """Get or create the feature registry singleton."""
    global _registry
    if _registry is None:
        _registry = FeatureRegistry(get_pg_config())
        _registry.init_schema()
        # Register built-in views on first access
        register_builtin_views(_registry)
    return _registry


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class FeatureQueryRequest(BaseModel):
    """Request to retrieve features by entity key."""

    entity_keys: dict[str, Any] = Field(
        ..., description="Entity key-value pairs, e.g. {'model_version': 'rfdetr-v3'}"
    )
    columns: list[str] | None = Field(
        None, description="Specific columns to return (default: all)"
    )
    limit: int = Field(100, ge=1, le=1000)


class FeatureQueryResponse(BaseModel):
    """Response with feature values."""

    feature_view: str
    entity_keys: dict[str, Any]
    rows: list[dict[str, Any]]
    row_count: int
    freshness_minutes: float | None = None
    slo_met: bool | None = None


class MaterializeRequest(BaseModel):
    """Request to trigger materialization for a feature view."""

    feature_view_name: str
    ray_job_id: str | None = None
    mlflow_run_id: str | None = None


class RegistryStatsResponse(BaseModel):
    """Overall feature platform health stats."""

    total_views: int
    active_views: int
    views_meeting_slo: int
    views_breaching_slo: int
    views_no_data: int
    oldest_feature_minutes: float | None


# ---------------------------------------------------------------------------
# Catalog endpoints
# ---------------------------------------------------------------------------


@router.get("/features/catalog", response_model=list[FeatureViewSummary])
async def list_feature_views(
    status: str | None = Query(
        None, description="Filter by status: active, deprecated, draft"
    ),
):
    """List all registered feature views with freshness status."""
    registry = get_registry()
    return registry.list_views(status=status)


@router.get("/features/catalog/{name}")
async def get_feature_view(name: str):
    """Get a single feature view definition."""
    registry = get_registry()
    defn = registry.get(name)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Feature view '{name}' not found")
    return defn


@router.post("/features/catalog", status_code=201)
async def register_feature_view(defn: FeatureViewDefinition):
    """Register or update a feature view definition."""
    registry = get_registry()
    registry.register(defn)
    return {"status": "registered", "name": defn.name, "version": defn.version}


@router.delete("/features/catalog/{name}")
async def delete_feature_view(name: str):
    """Delete a feature view and its run history."""
    registry = get_registry()
    deleted = registry.delete(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Feature view '{name}' not found")
    return {"status": "deleted", "name": name}


# ---------------------------------------------------------------------------
# Feature retrieval endpoints
# ---------------------------------------------------------------------------


@router.post("/features/{view_name}/query", response_model=FeatureQueryResponse)
async def query_features(view_name: str, req: FeatureQueryRequest):
    """Query feature values by entity key.

    Example:
        POST /api/v1/features/eval_metrics/query
        {"entity_keys": {"model_version": "rfdetr-v3"}, "limit": 10}
    """
    registry = get_registry()
    defn = registry.get(view_name)
    if not defn:
        raise HTTPException(
            status_code=404, detail=f"Feature view '{view_name}' not found"
        )

    source_table = defn["source_table"]
    entity_keys = defn["entity_keys"]
    if isinstance(entity_keys, str):
        import json

        entity_keys = json.loads(entity_keys)

    # Build WHERE clause from entity keys
    where_parts = []
    params: list[Any] = []
    for key in entity_keys:
        if key in req.entity_keys:
            where_parts.append(f"{key} = %s")
            params.append(req.entity_keys[key])

    if not where_parts:
        raise HTTPException(
            status_code=400,
            detail=f"At least one entity key required. Valid keys: {entity_keys}",
        )

    # Column selection
    import psycopg2
    import psycopg2.extras

    conn = registry._get_conn()

    if req.columns:
        # Validate columns against schema
        valid_cols = {c["name"] for c in defn["schema_columns"]}
        invalid = set(req.columns) - valid_cols
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid columns: {invalid}")
        select_cols = ", ".join(req.columns)
    else:
        select_cols = "*"

    query = f"SELECT {select_cols} FROM {source_table} WHERE {' AND '.join(where_parts)} ORDER BY created_at DESC LIMIT %s"
    params.append(req.limit)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]

    # Serialize datetime/non-JSON-native types
    for row in rows:
        for k, v in row.items():
            if isinstance(v, datetime):
                row[k] = v.isoformat()

    # Compute freshness
    freshness = None
    slo_met = None
    if rows:
        latest = rows[0].get("created_at")
        if latest:
            if isinstance(latest, str):
                latest = datetime.fromisoformat(latest)
            now = datetime.now(timezone.utc)
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            freshness = round((now - latest).total_seconds() / 60.0, 1)
            slo_met = freshness <= defn["freshness_slo_minutes"]

    return FeatureQueryResponse(
        feature_view=view_name,
        entity_keys=req.entity_keys,
        rows=rows,
        row_count=len(rows),
        freshness_minutes=freshness,
        slo_met=slo_met,
    )


@router.get("/features/{view_name}/latest")
async def get_latest_features(
    view_name: str,
    limit: int = Query(10, ge=1, le=100),
):
    """Get the most recent feature values (no key filter)."""
    registry = get_registry()
    defn = registry.get(view_name)
    if not defn:
        raise HTTPException(
            status_code=404, detail=f"Feature view '{view_name}' not found"
        )

    import psycopg2
    import psycopg2.extras

    conn = registry._get_conn()

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT * FROM {defn['source_table']} ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    for row in rows:
        for k, v in row.items():
            if isinstance(v, datetime):
                row[k] = v.isoformat()

    return {"feature_view": view_name, "rows": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Materialization endpoints
# ---------------------------------------------------------------------------


@router.post("/features/{view_name}/materialize")
async def trigger_materialization(
    view_name: str, req: MaterializeRequest | None = None
):
    """Trigger a materialization run for a feature view.

    In production, this would submit a Ray job. Currently records the run
    for tracking and returns the run_id for status polling.
    """
    registry = get_registry()
    defn = registry.get(view_name)
    if not defn:
        raise HTTPException(
            status_code=404, detail=f"Feature view '{view_name}' not found"
        )

    run = MaterializationRun(
        feature_view_name=view_name,
        status=MaterializationStatus.PENDING,
        started_at=datetime.now(timezone.utc),
        ray_job_id=req.ray_job_id if req else None,
        mlflow_run_id=req.mlflow_run_id if req else None,
    )
    registry.record_run_start(run)

    return {
        "status": "submitted",
        "run_id": run.run_id,
        "feature_view": view_name,
        "message": f"Materialization queued for '{view_name}'",
    }


@router.patch("/features/runs/{run_id}")
async def update_materialization_run(
    run_id: str,
    status: MaterializationStatus = Query(...),
    rows_written: int = Query(0),
    error_message: str | None = Query(None),
):
    """Update the status of a materialization run (called by the compute job)."""
    registry = get_registry()
    registry.record_run_complete(run_id, status, rows_written, error_message)
    return {"status": "updated", "run_id": run_id}


@router.get("/features/{view_name}/runs")
async def get_materialization_history(
    view_name: str, limit: int = Query(20, ge=1, le=100)
):
    """Get materialization run history for a feature view."""
    registry = get_registry()
    runs = registry.get_run_history(view_name, limit=limit)
    for r in runs:
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = v.isoformat()
    return {"feature_view": view_name, "runs": runs, "count": len(runs)}


# ---------------------------------------------------------------------------
# Health / SLO endpoints
# ---------------------------------------------------------------------------


@router.get("/features/health", response_model=RegistryStatsResponse)
async def feature_platform_health():
    """Get overall feature platform health — SLO compliance summary."""
    registry = get_registry()
    views = registry.list_views(status="active")

    meeting = 0
    breaching = 0
    no_data = 0
    oldest = None

    for v in views:
        if v.slo_met is None:
            no_data += 1
        elif v.slo_met:
            meeting += 1
        else:
            breaching += 1

        if v.freshness_minutes is not None:
            if oldest is None or v.freshness_minutes > oldest:
                oldest = v.freshness_minutes

    return RegistryStatsResponse(
        total_views=len(views) + len(registry.list_views(status="deprecated")),
        active_views=len(views),
        views_meeting_slo=meeting,
        views_breaching_slo=breaching,
        views_no_data=no_data,
        oldest_feature_minutes=oldest,
    )


@router.get("/features/freshness")
async def get_all_freshness():
    """Per-view freshness — consumed by the SLO exporter for Prometheus metrics."""
    registry = get_registry()
    return registry.get_freshness_per_view()
