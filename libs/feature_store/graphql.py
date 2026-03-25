"""GraphQL schema for the SHML Feature Store.

Provides a Strawberry GraphQL API that mirrors the REST catalog endpoints.
Mounted at ``/features/graphql`` by api.py.

Usage (example query):
    query {
      featureViews {
        name
        entityName
        schedule
        sloMet
        freshnessMinutes
      }
    }
"""

from __future__ import annotations

from typing import List, Optional

import strawberry
from strawberry.fastapi import GraphQLRouter

from .registry import FeatureRegistry, MaterializationStatus


# ---------------------------------------------------------------------------
# GraphQL types
# ---------------------------------------------------------------------------


@strawberry.type
class FeatureViewType:
    name: str
    version: int
    entity_name: str
    entity_keys: List[str]
    source_table: str
    schedule: str
    freshness_slo_minutes: int
    owner: str
    status: str
    freshness_minutes: Optional[float]
    slo_met: Optional[bool]
    total_rows: Optional[int]


@strawberry.type
class MaterializationResultType:
    status: str
    run_id: str
    feature_view: str
    message: str


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


@strawberry.type
class Query:
    @strawberry.field
    async def feature_views(
        self,
        info: strawberry.types.Info,
        status: Optional[str] = None,
    ) -> List[FeatureViewType]:
        """List all registered feature views."""
        from .api import get_registry
        registry: FeatureRegistry = await get_registry()
        summaries = await registry.list_views(status=status)
        return [
            FeatureViewType(
                name=s.name,
                version=s.version,
                entity_name=s.entity_name,
                entity_keys=s.entity_keys,
                source_table=s.source_table,
                schedule=s.schedule,
                freshness_slo_minutes=s.freshness_slo_minutes,
                owner=s.owner,
                status=s.status,
                freshness_minutes=s.freshness_minutes,
                slo_met=s.slo_met,
                total_rows=s.total_rows,
            )
            for s in summaries
        ]

    @strawberry.field
    async def feature_view(
        self,
        info: strawberry.types.Info,
        name: str,
    ) -> Optional[FeatureViewType]:
        """Get a single feature view by name."""
        import json
        from .api import get_registry

        registry: FeatureRegistry = await get_registry()
        defn = await registry.get(name)
        if defn is None:
            return None
        entity_keys = defn.get("entity_keys", [])
        if isinstance(entity_keys, str):
            entity_keys = json.loads(entity_keys)
        return FeatureViewType(
            name=defn["name"],
            version=defn.get("version", 1),
            entity_name=defn.get("entity_name", ""),
            entity_keys=entity_keys,
            source_table=defn.get("source_table", ""),
            schedule=defn.get("schedule", "@hourly"),
            freshness_slo_minutes=defn.get("freshness_slo_minutes", 60),
            owner=defn.get("owner", ""),
            status=defn.get("status", "active"),
            freshness_minutes=None,
            slo_met=None,
            total_rows=None,
        )


# ---------------------------------------------------------------------------
# Mutation
# ---------------------------------------------------------------------------


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def trigger_materialization(
        self,
        info: strawberry.types.Info,
        feature_view: str,
        ray_job_id: Optional[str] = None,
        mlflow_run_id: Optional[str] = None,
    ) -> MaterializationResultType:
        """Trigger a materialization run for a feature view."""
        from datetime import datetime, timezone

        from .api import get_registry
        from .registry import MaterializationRun

        registry: FeatureRegistry = await get_registry()
        defn = await registry.get(feature_view)
        if defn is None:
            return MaterializationResultType(
                status="error",
                run_id="",
                feature_view=feature_view,
                message=f"Feature view '{feature_view}' not found",
            )

        run = MaterializationRun(
            feature_view_name=feature_view,
            status=MaterializationStatus.PENDING,
            started_at=datetime.now(timezone.utc),
            ray_job_id=ray_job_id,
            mlflow_run_id=mlflow_run_id,
        )
        await registry.record_run_start(run)
        return MaterializationResultType(
            status="submitted",
            run_id=run.run_id,
            feature_view=feature_view,
            message=f"Materialization queued for '{feature_view}'",
        )


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

schema = strawberry.Schema(query=Query, mutation=Mutation)


def make_graphql_router() -> GraphQLRouter:
    """Return a Strawberry GraphQL router to mount on FastAPI."""
    return GraphQLRouter(schema, graphiql=True)
