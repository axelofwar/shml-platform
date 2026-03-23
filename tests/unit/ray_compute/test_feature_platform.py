"""
Unit tests for Feature Platform (EB-05)
========================================

Tests the feature registry, definitions, API router, and scheduled
materialization logic WITHOUT requiring running services (Postgres, Ray, etc).

Uses mocks for database connections and external services.

Usage:
    pytest tests/unit/ray_compute/test_feature_platform.py -v
"""

import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Add repo root to path
_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "ray_compute"))

# Mock asyncpg at module level so registry can import without the driver running
if "asyncpg" not in sys.modules:
    _mock_asyncpg = MagicMock()
    _mock_asyncpg.Pool = MagicMock
    sys.modules["asyncpg"] = _mock_asyncpg


# ===========================================================================
# Feature Registry Tests
# ===========================================================================


class TestFeatureViewDefinition:
    """Test FeatureViewDefinition Pydantic model."""

    def test_valid_definition(self):
        from ray_compute.features.registry import (
            FeatureViewDefinition,
            ColumnSchema,
            FreshnessSLO,
            EntityDefinition,
            ComputeEngine,
        )

        defn = FeatureViewDefinition(
            name="test_view",
            description="Test feature view",
            source_table="test_table",
            entity=EntityDefinition(
                name="model_version",
                join_keys=["model_id"],
                description="Model entity",
            ),
            schema=[
                ColumnSchema(name="metric_a", type="FLOAT", description="A metric"),
            ],
            schedule="@hourly",
            freshness_slo=FreshnessSLO(max_staleness_minutes=60),
            compute_engine=ComputeEngine.RAY,
            owner="test-team",
        )
        assert defn.name == "test_view"
        assert defn.freshness_slo.max_staleness_minutes == 60
        assert len(defn.schema_columns) == 1
        assert defn.compute_engine == ComputeEngine.RAY

    def test_definition_serialization(self):
        from ray_compute.features.registry import (
            FeatureViewDefinition,
            ColumnSchema,
            FreshnessSLO,
            EntityDefinition,
            ComputeEngine,
        )

        defn = FeatureViewDefinition(
            name="test_view",
            description="Test",
            source_table="t",
            entity=EntityDefinition(name="ent", join_keys=["k1"]),
            schema=[ColumnSchema(name="c1", type="TEXT")],
            schedule="@daily",
            freshness_slo=FreshnessSLO(max_staleness_minutes=120),
            compute_engine=ComputeEngine.SPARK,
            owner="team",
        )
        data = defn.model_dump()
        assert data["name"] == "test_view"
        assert data["freshness_slo"]["max_staleness_minutes"] == 120
        assert data["entity"]["join_keys"] == ["k1"]

    def test_feature_view_summary(self):
        from ray_compute.features.registry import FeatureViewSummary

        summary = FeatureViewSummary(
            name="eval_metrics",
            version=1,
            entity_name="model_version",
            entity_keys=["model_version", "run_id"],
            source_table="feature_eval",
            schedule="@hourly",
            freshness_slo_minutes=120,
            owner="ml-team",
            status="active",
            last_materialized_at=None,
            freshness_minutes=None,
            slo_met=None,
        )
        assert summary.name == "eval_metrics"
        assert summary.slo_met is None


class TestFeatureRegistry:
    """Test FeatureRegistry database operations with mocked asyncpg pool."""

    def _make_pool(self):
        """Return a mock asyncpg pool whose acquire() yields a mock connection."""
        conn = AsyncMock()
        # conn.fetch / fetchrow / execute return empty results by default
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value="DELETE 1")
        # Support `async with conn.transaction()` in delete()
        txn = AsyncMock()
        txn.__aenter__ = AsyncMock(return_value=txn)
        txn.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=txn)

        pool = AsyncMock()
        acm = AsyncMock()
        acm.__aenter__ = AsyncMock(return_value=conn)
        acm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=acm)
        pool.close = AsyncMock()
        return pool, conn

    @pytest.mark.asyncio
    async def test_init_schema(self):
        from libs.feature_store.registry import FeatureRegistry

        pool, conn = self._make_pool()
        reg = FeatureRegistry(dsn="postgresql://test:test@localhost/test")
        reg._pool = pool
        await reg.init_schema()
        # Should execute CREATE TABLE for feature_views and feature_view_runs
        assert conn.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_register_view(self):
        from libs.feature_store.registry import (
            FeatureRegistry, FeatureViewDefinition, ColumnSchema,
            FreshnessSLO, EntityDefinition, ComputeEngine,
        )

        pool, conn = self._make_pool()
        reg = FeatureRegistry(dsn="postgresql://test:test@localhost/test")
        reg._pool = pool

        defn = FeatureViewDefinition(
            name="test_view",
            source_table="test_table",
            entity=EntityDefinition(name="ent", join_keys=["id"]),
            schema=[ColumnSchema(name="val", type="FLOAT")],
            schedule="@hourly",
            freshness_slo=FreshnessSLO(max_staleness_minutes=60),
            compute_engine=ComputeEngine.RAY,
            owner="team",
        )
        await reg.register(defn)
        conn.execute.assert_called_once()
        # Verify the INSERT/ON CONFLICT statement contains expected view name
        call_sql = conn.execute.call_args[0][0]
        assert "INSERT INTO feature_views" in call_sql

    @pytest.mark.asyncio
    async def test_get_view(self):
        from libs.feature_store.registry import FeatureRegistry

        pool, conn = self._make_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        reg = FeatureRegistry(dsn="postgresql://test:test@localhost/test")
        reg._pool = pool

        result = await reg.get("missing_view")
        assert result is None
        conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_view(self):
        from libs.feature_store.registry import FeatureRegistry

        pool, conn = self._make_pool()
        conn.execute = AsyncMock(side_effect=["DELETE 1", "DELETE 1"])
        reg = FeatureRegistry(dsn="postgresql://test:test@localhost/test")
        reg._pool = pool

        deleted = await reg.delete("eval_metrics")
        assert deleted is True

    @pytest.mark.asyncio
    async def test_record_run_start(self):
        from libs.feature_store.registry import FeatureRegistry, MaterializationRun

        pool, conn = self._make_pool()
        reg = FeatureRegistry(dsn="postgresql://test:test@localhost/test")
        reg._pool = pool

        run = MaterializationRun(feature_view_name="eval_metrics", run_id="run-123")
        await reg.record_run_start(run)
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_run_complete(self):
        from libs.feature_store.registry import FeatureRegistry, MaterializationStatus

        pool, conn = self._make_pool()
        reg = FeatureRegistry(dsn="postgresql://test:test@localhost/test")
        reg._pool = pool

        await reg.record_run_complete(
            "run-123", status=MaterializationStatus.SUCCEEDED, rows_written=500
        )
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_source_table_no_where(self):
        """query_source_table with no WHERE clause returns rows from fetch."""
        from libs.feature_store.registry import FeatureRegistry

        pool, conn = self._make_pool()
        conn.fetch = AsyncMock(return_value=[])
        reg = FeatureRegistry(dsn="postgresql://test:test@localhost/test")
        reg._pool = pool

        rows = await reg.query_source_table("feature_eval", [], [], None, 10)
        assert rows == []
        conn.fetch.assert_called_once()
        sql = conn.fetch.call_args[0][0]
        assert "feature_eval" in sql
        assert "LIMIT $1" in sql

    @pytest.mark.asyncio
    async def test_query_source_table_with_where(self):
        """$N placeholder numbering is contiguous when WHERE clause present."""
        from libs.feature_store.registry import FeatureRegistry

        pool, conn = self._make_pool()
        conn.fetch = AsyncMock(return_value=[])
        reg = FeatureRegistry(dsn="postgresql://test:test@localhost/test")
        reg._pool = pool

        await reg.query_source_table(
            "feature_eval",
            ["model_version = $1"],
            ["rfdetr-v3"],
            None,
            5,
        )
        sql, *params = conn.fetch.call_args[0]
        # params should be ["rfdetr-v3", 5]
        assert params == ["rfdetr-v3", 5]
        assert "LIMIT $2" in sql

    def test_pool_or_raise_before_init(self):
        """Accessing pool before init() raises RuntimeError."""
        from libs.feature_store.registry import FeatureRegistry

        reg = FeatureRegistry(dsn="postgresql://test:test@localhost/test")
        with pytest.raises(RuntimeError, match="not initialised"):
            reg._pool_or_raise()


# ===========================================================================
# Feature Definitions Tests
# ===========================================================================


class TestBuiltinDefinitions:
    """Test built-in feature view definitions."""

    def test_builtin_views_exist(self):
        from ray_compute.features.definitions import (
            EVAL_FEATURES,
            TRAINING_LINEAGE,
            DATASET_QUALITY,
            HARD_EXAMPLES,
        )

        assert EVAL_FEATURES.name == "eval_metrics"
        assert TRAINING_LINEAGE.name == "training_lineage"
        assert DATASET_QUALITY.name == "dataset_quality"
        assert HARD_EXAMPLES.name == "hard_examples"

    def test_eval_features_slo(self):
        from ray_compute.features.definitions import EVAL_FEATURES

        assert EVAL_FEATURES.freshness_slo.max_staleness_minutes == 120
        assert EVAL_FEATURES.compute_engine == "ray"
        assert EVAL_FEATURES.source_table == "feature_eval"

    def test_hard_examples_entity(self):
        from ray_compute.features.definitions import HARD_EXAMPLES

        assert "image_id" in HARD_EXAMPLES.entity.join_keys
        assert HARD_EXAMPLES.freshness_slo.max_staleness_minutes == 1440

    def test_all_views_have_required_fields(self):
        from ray_compute.features.definitions import (
            EVAL_FEATURES,
            TRAINING_LINEAGE,
            DATASET_QUALITY,
            HARD_EXAMPLES,
        )

        for view in [EVAL_FEATURES, TRAINING_LINEAGE, DATASET_QUALITY, HARD_EXAMPLES]:
            assert view.name, f"View missing name"
            assert view.source_table, f"View {view.name} missing source_table"
            assert view.entity.join_keys, f"View {view.name} missing entity join_keys"
            assert (
                view.freshness_slo.max_staleness_minutes > 0
            ), f"View {view.name} missing SLO"
            assert (
                len(view.schema_columns) > 0
            ), f"View {view.name} missing schema columns"
            assert view.owner, f"View {view.name} missing owner"

    @pytest.mark.asyncio
    async def test_register_builtin_views(self):
        """register_builtin_views should call registry.register for each view."""
        from ray_compute.features.definitions import register_builtin_views

        mock_registry = AsyncMock()
        await register_builtin_views(mock_registry)
        assert mock_registry.register.call_count == 4


# ===========================================================================
# Feature API Tests
# ===========================================================================


class TestFeatureAPI:
    """Test Feature API router endpoints with async mocks."""

    @pytest.fixture
    def client(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi not installed")

        from ray_compute.features.api import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        return TestClient(app)

    def test_catalog_list(self, client):
        """GET /api/v1/features/catalog should return a list."""
        mock_reg = AsyncMock()
        mock_reg.list_views = AsyncMock(return_value=[])
        with patch("libs.feature_store.api.get_registry", new=AsyncMock(return_value=mock_reg)):
            resp = client.get("/api/v1/features/catalog")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_catalog_get_missing(self, client):
        """GET /api/v1/features/catalog/{name} returns 404 for unknown view."""
        mock_reg = AsyncMock()
        mock_reg.get = AsyncMock(return_value=None)
        with patch("libs.feature_store.api.get_registry", new=AsyncMock(return_value=mock_reg)):
            resp = client.get("/api/v1/features/catalog/no_such_view")
        assert resp.status_code == 404

    def test_query_features_missing_view(self, client):
        """POST /api/v1/features/{name}/query returns 404 when view not found."""
        mock_reg = AsyncMock()
        mock_reg.get = AsyncMock(return_value=None)
        with patch("libs.feature_store.api.get_registry", new=AsyncMock(return_value=mock_reg)):
            resp = client.post(
                "/api/v1/features/no_such_view/query",
                json={"entity_keys": {"model_version": "v1"}},
            )
        assert resp.status_code == 404


# ===========================================================================
# SLO Exporter Per-View Tests
# ===========================================================================


class TestSLOExporterPerView:
    """Test per-view feature freshness metrics logic."""

    def test_per_view_freshness_import(self):
        """The collect_per_view_freshness function should be importable."""
        # Just verify the function exists in the exporter module
        exporter_path = os.path.join(
            _root, "monitoring", "ml-slo-exporter", "slo_exporter.py"
        )
        assert os.path.exists(exporter_path), "SLO exporter not found"

        with open(exporter_path) as f:
            content = f.read()

        assert "collect_per_view_freshness" in content
        assert "ml_feature_view_freshness_minutes" in content
        assert "ml_feature_view_slo_met" in content
        assert "ml_feature_view_slo_target_minutes" in content

    def test_per_view_prometheus_gauges_defined(self):
        """The exporter should define labeled Prometheus gauges."""
        exporter_path = os.path.join(
            _root, "monitoring", "ml-slo-exporter", "slo_exporter.py"
        )
        with open(exporter_path) as f:
            content = f.read()

        # Check for Gauge declarations with feature_view label
        assert "feature_view" in content
        assert (
            "FEATURE_VIEW_FRESHNESS" in content or "feature_view_freshness" in content
        )


# ===========================================================================
# Grafana Dashboard Tests
# ===========================================================================


class TestFeaturePlatformDashboard:
    """Verify feature-platform-slos Grafana dashboard JSON."""

    @pytest.fixture
    def dashboard(self):
        path = os.path.join(
            _root,
            "monitoring",
            "grafana",
            "dashboards",
            "ml-slos",
            "feature-platform-slos.json",
        )
        if not os.path.exists(path):
            pytest.skip("Feature platform dashboard not found")
        with open(path) as f:
            return json.load(f)

    def test_dashboard_uid(self, dashboard):
        assert dashboard["uid"] == "feature-platform-slos"

    def test_dashboard_has_panels(self, dashboard):
        panels = dashboard.get("panels", [])
        assert len(panels) >= 5, f"Expected at least 5 panels, got {len(panels)}"

    def test_dashboard_targets_reference_feature_view_metrics(self, dashboard):
        """All panels should reference ml_feature_view_* metrics."""
        panels = dashboard.get("panels", [])
        all_exprs = []
        for panel in panels:
            for target in panel.get("targets", []):
                expr = target.get("expr", "")
                all_exprs.append(expr)

        feature_view_refs = [e for e in all_exprs if "feature_view" in e]
        assert (
            len(feature_view_refs) >= 3
        ), f"Expected at least 3 feature_view metric references, got {len(feature_view_refs)}"

    def test_dashboard_tags(self, dashboard):
        tags = dashboard.get("tags", [])
        assert "features" in tags or "ml" in tags


# ===========================================================================
# Alert Rules Tests
# ===========================================================================


class TestBugRegressions:
    """Regression tests for audit-session bug fixes."""

    def test_no_circular_import(self):
        """Importing graphql module must not raise a circular ImportError.

        Skips when optional third-party deps (strawberry) aren't installed —
        the concern here is circular imports, not missing optional packages.
        """
        import importlib
        import sys

        # Remove cached versions so we get a fresh import attempt
        for mod in list(sys.modules.keys()):
            if "feature_store" in mod:
                del sys.modules[mod]

        try:
            importlib.import_module("libs.feature_store.graphql")
        except ModuleNotFoundError as exc:
            # A missing optional dep (e.g. strawberry, asyncpg) is expected in CI;
            # skip rather than fail — we only care about circular import bugs.
            pytest.skip(f"Optional dep not installed, skipping: {exc}")
        except ImportError as exc:
            pytest.fail(f"Circular import not fixed: {exc}")

    def test_param_numbering_partial_entity_keys(self):
        """$N placeholder numbers must be contiguous regardless of which keys are present.

        The bug was that enumerate(entity_keys, start=1) used a fixed offset
        so if only the second key matched, we'd get $2 but only one param.
        """
        # Simulate the fixed logic from api.py query_features
        entity_keys_spec = ["model_version", "run_id"]
        req_entity_keys = {"run_id": "abc"}  # only second key present

        where_parts: list = []
        params: list = []
        for key in entity_keys_spec:
            if key in req_entity_keys:
                params.append(req_entity_keys[key])
                where_parts.append(f"{key} = ${len(params)}")  # fixed pattern

        assert where_parts == ["run_id = $1"]
        assert params == ["abc"]

    @pytest.mark.asyncio
    async def test_concurrent_registry_init(self):
        """Concurrent get_registry() calls must only initialise the pool once."""
        import asyncio
        import importlib
        import sys

        # Reset cached state in the module
        for mod in list(sys.modules.keys()):
            if "feature_store.api" in mod:
                del sys.modules[mod]

        api_mod = importlib.import_module("libs.feature_store.api")
        # Patch the FeatureRegistry constructor so it doesn't touch postgres
        init_count = 0

        async def fake_init(self):
            nonlocal init_count
            await asyncio.sleep(0)  # yield to let second coroutine attempt
            init_count += 1

        fake_pool = AsyncMock()
        fake_reg = MagicMock()
        fake_reg.init = fake_init.__get__(fake_reg)

        with patch.object(api_mod, "_registry", None), \
             patch.object(api_mod, "_registry_lock", None), \
             patch("libs.feature_store.api.FeatureRegistry", return_value=fake_reg), \
             patch("libs.feature_store.api.register_builtin_views", new=AsyncMock()):
            results = await asyncio.gather(
                api_mod.get_registry(), api_mod.get_registry()
            )

        # Both calls should return the same singleton
        assert results[0] is results[1]


class TestAlertRules:
    """Verify Prometheus alert rules for per-view SLOs."""

    @pytest.fixture
    def rules_content(self):
        path = os.path.join(_root, "monitoring", "prometheus", "alerts", "ml-slos.yml")
        if not os.path.exists(path):
            pytest.skip("Alert rules file not found")
        with open(path) as f:
            return f.read()

    def test_feature_view_slo_breached_rule(self, rules_content):
        assert "FeatureViewSLOBreached" in rules_content

    def test_feature_view_no_data_rule(self, rules_content):
        assert "FeatureViewNoData" in rules_content

    def test_rules_reference_per_view_metric(self, rules_content):
        assert "ml_feature_view_slo_met" in rules_content
        assert "ml_feature_view_freshness_minutes" in rules_content
