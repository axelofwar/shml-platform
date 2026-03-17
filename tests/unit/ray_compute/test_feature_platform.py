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
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Add ray_compute to path
_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "ray_compute"))

# Mock psycopg2 at module level so ray_compute.features.registry can import
# without the actual driver being installed in the test environment.
if "psycopg2" not in sys.modules:
    _mock_pg = MagicMock()
    _mock_pg.extras = MagicMock()
    sys.modules["psycopg2"] = _mock_pg
    sys.modules["psycopg2.extras"] = _mock_pg.extras


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
    """Test FeatureRegistry database operations with mocked Postgres."""

    @pytest.fixture
    def mock_conn(self):
        """Create a mock psycopg2 connection with proper context manager."""
        conn = MagicMock()
        conn.closed = False  # prevents _get_conn from reconnecting
        cursor = MagicMock()
        # Make conn.cursor() work as a context manager that yields our cursor
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=cursor)
        ctx.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = ctx
        return conn, cursor

    @pytest.fixture
    def registry(self, mock_conn):
        """Create a FeatureRegistry with mocked connection."""
        from ray_compute.features.registry import FeatureRegistry

        conn, cursor = mock_conn
        reg = FeatureRegistry(
            pg_config={
                "host": "localhost",
                "port": 5432,
                "dbname": "test",
                "user": "test",
                "password": "test",
            }
        )
        # Directly inject the mock connection
        reg._conn = conn
        return reg

    def test_init_schema(self, registry, mock_conn):
        conn, cursor = mock_conn
        registry.init_schema()
        # Should have executed CREATE TABLE statements
        assert cursor.execute.call_count >= 2  # feature_views + feature_view_runs

    def test_register_view(self, registry, mock_conn):
        from ray_compute.features.registry import (
            FeatureViewDefinition,
            ColumnSchema,
            FreshnessSLO,
            EntityDefinition,
            ComputeEngine,
        )

        conn, cursor = mock_conn

        defn = FeatureViewDefinition(
            name="test_view",
            description="Test",
            source_table="test_table",
            entity=EntityDefinition(name="test_ent", join_keys=["id"]),
            schema=[ColumnSchema(name="val", type="FLOAT")],
            schedule="@hourly",
            freshness_slo=FreshnessSLO(max_staleness_minutes=60),
            compute_engine=ComputeEngine.RAY,
            owner="team",
        )
        registry.register(defn)
        # Should have called INSERT/UPSERT
        assert cursor.execute.called

    def test_list_views(self, registry, mock_conn):
        conn, cursor = mock_conn
        cursor.fetchall.return_value = [
            {
                "name": "eval_metrics",
                "version": 1,
                "entity_name": "model_version",
                "entity_keys": ["model_version", "run_id"],
                "source_table": "feature_eval",
                "schedule": "@hourly",
                "freshness_slo_minutes": 120,
                "owner": "ml-team",
                "status": "active",
                "last_materialized_at": None,
            }
        ]
        views = registry.list_views()
        assert cursor.execute.called

    def test_record_run_start(self, registry, mock_conn):
        from ray_compute.features.registry import MaterializationRun

        conn, cursor = mock_conn
        run = MaterializationRun(
            feature_view_name="eval_metrics",
            run_id="run-123",
        )
        registry.record_run_start(run)
        assert cursor.execute.called

    def test_record_run_complete(self, registry, mock_conn):
        from ray_compute.features.registry import MaterializationStatus

        conn, cursor = mock_conn
        registry.record_run_complete(
            "run-123",
            status=MaterializationStatus.SUCCEEDED,
            rows_written=500,
        )
        assert cursor.execute.called


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

    def test_register_builtin_views(self):
        """register_builtin_views should call registry.register for each view."""
        from ray_compute.features.definitions import register_builtin_views

        mock_registry = MagicMock()
        register_builtin_views(mock_registry)
        assert mock_registry.register.call_count == 4


# ===========================================================================
# Feature API Tests
# ===========================================================================


class TestFeatureAPI:
    """Test Feature API router endpoints."""

    @pytest.fixture
    def client(self):
        """Create a FastAPI test client with the features router."""
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
        with patch("ray_compute.features.api.get_registry") as mock_get:
            mock_reg = MagicMock()
            mock_reg.list_views.return_value = []
            mock_get.return_value = mock_reg

            resp = client.get("/api/v1/features/catalog")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    def test_health_endpoint(self, client):
        """GET /api/v1/features/health should return status."""
        with patch("ray_compute.features.api.get_registry") as mock_get:
            mock_reg = MagicMock()
            mock_reg.list_views.return_value = []
            mock_reg.get_freshness_per_view.return_value = [
                {
                    "name": "eval_metrics",
                    "slo_met": True,
                    "freshness_minutes": 30,
                    "slo_minutes": 120,
                },
            ]
            mock_get.return_value = mock_reg

            resp = client.get("/api/v1/features/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data or "total_views" in data


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
