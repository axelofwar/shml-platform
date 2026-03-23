"""Feature Serving API — REST endpoints for the SHML Feature Platform.

Provides:
  - Feature catalog: list/get/register feature views
  - Feature retrieval: query feature values by entity key
  - Materialization: trigger and track materialization runs
  - Freshness: per-view SLO status

Mounts as a router on the Ray Compute API (server_v2.py).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .registry import (
    FeatureRegistry,
    FeatureViewDefinition,
    FeatureViewSummary,
    MaterializationRun,
    MaterializationStatus,
)
from .definitions import get_pg_dsn, register_builtin_views
from .graphql import make_graphql_router

logger = logging.getLogger("shml-features.api")

router = APIRouter(tags=["features"])

# Mount GraphQL sub-router at /features/graphql
router.include_router(make_graphql_router(), prefix="/features/graphql")

# ---------------------------------------------------------------------------
# Singleton registry — lazy async init
# ---------------------------------------------------------------------------

_registry: FeatureRegistry | None = None
_registry_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _registry_lock
    if _registry_lock is None:
        _registry_lock = asyncio.Lock()
    return _registry_lock


async def get_registry() -> FeatureRegistry:
    """Get or lazily initialise the feature registry singleton (concurrency-safe)."""
    global _registry
    if _registry is not None:
        return _registry
    async with _get_lock():
        if _registry is None:  # double-check after acquiring lock
            reg = FeatureRegistry(get_pg_dsn())
            await reg.init()
            await register_builtin_views(reg)
            _registry = reg
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
    registry = await get_registry()
    return await registry.list_views(status=status)


@router.get("/features/catalog/{name}")
async def get_feature_view(name: str):
    """Get a single feature view definition."""
    registry = await get_registry()
    defn = await registry.get(name)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Feature view '{name}' not found")
    return defn


@router.post("/features/catalog", status_code=201)
async def register_feature_view(defn: FeatureViewDefinition):
    """Register or update a feature view definition."""
    registry = await get_registry()
    await registry.register(defn)
    return {"status": "registered", "name": defn.name, "version": defn.version}


@router.delete("/features/catalog/{name}")
async def delete_feature_view(name: str):
    """Delete a feature view and its run history."""
    registry = await get_registry()
    deleted = await registry.delete(name)
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
    import json

    registry = await get_registry()
    defn = await registry.get(view_name)
    if not defn:
        raise HTTPException(
            status_code=404, detail=f"Feature view '{view_name}' not found"
        )

    source_table = defn["source_table"]
    entity_keys = defn["entity_keys"]
    if isinstance(entity_keys, str):
        entity_keys = json.loads(entity_keys)

    # Validate requested columns against schema
    columns = None
    if req.columns:
        schema_cols = defn.get("schema_columns", [])
        if isinstance(schema_cols, str):
            schema_cols = json.loads(schema_cols)
        valid_cols = {c["name"] for c in schema_cols}
        invalid = set(req.columns) - valid_cols
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid columns: {invalid}")
        columns = req.columns

    # Build $N-style WHERE clause — $N index is the position in params (1-based)
    where_parts: list[str] = []
    params: list[Any] = []
    for key in entity_keys:
        if key in req.entity_keys:
            params.append(req.entity_keys[key])
            where_parts.append(f"{key} = ${len(params)}")

    if not where_parts:
        raise HTTPException(
            status_code=400,
            detail=f"At least one entity key required. Valid keys: {entity_keys}",
        )

    rows = await registry.query_source_table(
        source_table, where_parts, params, columns, req.limit
    )

    # Compute freshness from first row
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
    registry = await get_registry()
    defn = await registry.get(view_name)
    if not defn:
        raise HTTPException(
            status_code=404, detail=f"Feature view '{view_name}' not found"
        )

    rows = await registry.query_source_table(
        defn["source_table"], [], [], None, limit
    )
    return {"feature_view": view_name, "rows": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Materialization endpoints
# ---------------------------------------------------------------------------


@router.post("/features/{view_name}/materialize")
async def trigger_materialization(
    view_name: str, req: MaterializeRequest | None = None
):
    """Trigger a materialization run for a feature view."""
    registry = await get_registry()
    defn = await registry.get(view_name)
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
    await registry.record_run_start(run)

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
    registry = await get_registry()
    await registry.record_run_complete(run_id, status, rows_written, error_message)
    return {"status": "updated", "run_id": run_id}
