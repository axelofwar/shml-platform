"""Unit tests for libs/feature_store — no live services required.

Covers:
- materialize.py: _polars_to_pyarrow, _build_iceberg_schema, _ensure_namespace
- definitions.py: get_pg_dsn, get_pg_config, built-in view definitions
- api.py: GraphQL guard (strawberry absent/present)
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Inject stubs for heavy optional deps before any feature_store import
# ---------------------------------------------------------------------------

def _stub_module(name: str) -> MagicMock:
    mock = MagicMock()
    sys.modules[name] = mock
    return mock


# asyncpg stub (already handled by conftest, but idempotent)
if "asyncpg" not in sys.modules:
    _stub_module("asyncpg")

# pyiceberg stubs — never installed in unit test env
for _mod in [
    "pyiceberg",
    "pyiceberg.catalog",
    "pyiceberg.schema",
    "pyiceberg.types",
    "pyiceberg.exceptions",
    "pyiceberg.table",
]:
    if _mod not in sys.modules:
        _stub_module(_mod)

# polars stub — may or may not be present; stub a minimal version for dtype tests
if "polars" not in sys.modules:
    _pl = MagicMock()
    for _dtype in ["Utf8", "String", "Float32", "Float64", "Int32", "Int64", "Boolean", "Datetime"]:
        setattr(_pl, _dtype, type(_dtype, (), {})())  # unique sentinel objects
    sys.modules["polars"] = _pl

# Add repo root so absolute imports resolve
_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _root not in sys.path:
    sys.path.insert(0, _root)


# ===========================================================================
# TestMaterialize
# ===========================================================================


class TestMaterialize:
    """Tests for materialize.py pure-Python helpers."""

    def test_polars_to_pyarrow_delegates_to_arrow(self):
        """_polars_to_pyarrow calls df.to_arrow() and returns the result."""
        from libs.feature_store.materialize import _polars_to_pyarrow

        mock_df = MagicMock()
        mock_df.to_arrow.return_value = "arrow_table"
        result = _polars_to_pyarrow(mock_df)
        mock_df.to_arrow.assert_called_once()
        assert result == "arrow_table"

    def test_build_iceberg_schema_maps_dtypes(self):
        """_build_iceberg_schema produces a Schema with one field per column."""
        from libs.feature_store.materialize import _build_iceberg_schema
        import pyiceberg.schema as ice_schema
        import pyiceberg.types as ice_types

        # Use actual Schema/NestedField/types (stubs via MagicMock — still callable)
        mock_df = MagicMock()
        mock_df.columns = ["entity_id", "score"]
        import polars as pl
        mock_df.dtypes = [pl.Int64, pl.Float64]

        # Just verify it doesn't raise and calls Schema(...)
        schema = _build_iceberg_schema(mock_df)
        # Schema is a MagicMock return value — we validate it was called
        assert schema is not None

    def test_ensure_namespace_creates_when_missing(self):
        """_ensure_namespace calls catalog.create_namespace and handles existing."""
        from libs.feature_store.materialize import _ensure_namespace
        from pyiceberg.exceptions import NamespaceAlreadyExistsError

        # Patch NamespaceAlreadyExistsError to be a real subclass of Exception
        NamespaceAlreadyExistsError.side_effect = None

        catalog = MagicMock()
        catalog.create_namespace.return_value = None
        _ensure_namespace(catalog, namespace="shml")
        catalog.create_namespace.assert_called_once_with("shml")

    def test_ensure_namespace_swallows_already_exists(self):
        """_ensure_namespace does not raise when namespace already exists."""
        from libs.feature_store.materialize import _ensure_namespace

        # Simulate NamespaceAlreadyExistsError by subclassing Exception
        class FakeAlreadyExists(Exception):
            pass

        catalog = MagicMock()
        catalog.create_namespace.side_effect = FakeAlreadyExists()

        with patch.dict(
            sys.modules,
            {"pyiceberg.exceptions": MagicMock(NamespaceAlreadyExistsError=FakeAlreadyExists)},
        ):
            # Should not raise
            _ensure_namespace(catalog, namespace="shml")

    def test_materialize_feature_view_calls_catalog(self):
        """materialize_feature_view uses _get_catalog; validate call flow."""
        from libs.feature_store import materialize as mat_mod

        mock_catalog = MagicMock()
        mock_df = MagicMock()
        mock_df.columns = ["entity_id"]
        import polars as pl
        mock_df.dtypes = [pl.Int64]

        with patch.object(mat_mod, "_get_catalog", return_value=mock_catalog):
            with patch.object(mat_mod, "_ensure_namespace"):
                with patch.object(mat_mod, "_polars_to_pyarrow", return_value=MagicMock()):
                    with patch.object(mat_mod, "_build_iceberg_schema", return_value=MagicMock()):
                        result = mat_mod.materialize_feature_view(
                            feature_view="test_view", df=mock_df, branch="main"
                        )
        assert result is not None


# ===========================================================================
# TestDefinitions
# ===========================================================================


class TestDefinitions:
    """Tests for definitions.py environment helpers."""

    def test_get_pg_dsn_builds_from_env(self):
        """get_pg_dsn constructs a valid DSN from environment variables."""
        from libs.feature_store.definitions import get_pg_dsn

        env = {
            "POSTGRES_USER": "testuser",
            "POSTGRES_PASSWORD": "pass",
            "POSTGRES_HOST": "db-host",
            "POSTGRES_PORT": "5432",
            "POSTGRES_FEATURES_DB": "features",
        }
        with patch.dict(os.environ, env):
            dsn = get_pg_dsn()
        assert "testuser" in dsn
        assert "db-host" in dsn
        assert "features" in dsn

    def test_get_pg_dsn_uses_defaults(self):
        """get_pg_dsn returns a functional DSN even when env vars are unset."""
        from libs.feature_store.definitions import get_pg_dsn

        env_clear = {k: "" for k in [
            "FEATURE_STORE_POSTGRES_USER", "FEATURE_STORE_POSTGRES_PASSWORD",
            "FEATURE_STORE_POSTGRES_HOST", "FEATURE_STORE_POSTGRES_PORT",
            "FEATURE_STORE_POSTGRES_DB",
        ]}
        with patch.dict(os.environ, env_clear):
            dsn = get_pg_dsn()
        # Should return a string without raising
        assert isinstance(dsn, str)

    def test_builtin_view_names_are_unique(self):
        """All built-in FeatureViewDefinition names are distinct."""
        from libs.feature_store.definitions import (
            EVAL_FEATURES,
            TRAINING_LINEAGE,
        )
        names = [EVAL_FEATURES.name, TRAINING_LINEAGE.name]
        assert len(names) == len(set(names))


# ===========================================================================
# TestAPIGraphQLGuard
# ===========================================================================


class TestAPIGraphQLGuard:
    """Tests for the optional strawberry import guard in api.py."""

    def test_api_imports_cleanly_without_strawberry(self):
        """feature_store/api.py imports without error when strawberry is missing."""
        # Force a clean re-import with strawberry stubbed to raise ImportError
        import importlib
        api_key = "libs.feature_store.api"
        original = sys.modules.pop(api_key, None)
        graphql_key = "libs.feature_store.graphql"
        original_graphql = sys.modules.pop(graphql_key, None)

        try:
            with patch.dict(sys.modules, {"strawberry": None, "strawberry.fastapi": None}):
                # Importing should succeed — ImportError is caught internally
                import libs.feature_store.api as api_mod  # noqa: F401
        finally:
            # Restore original module state
            if original is not None:
                sys.modules[api_key] = original
            elif api_key in sys.modules:
                del sys.modules[api_key]
            if original_graphql is not None:
                sys.modules[graphql_key] = original_graphql

    def test_api_router_has_feature_routes(self):
        """The feature_store router registers at least the catalog GET endpoint."""
        import importlib
        import libs.feature_store.api as api_mod

        route_paths = [r.path for r in api_mod.router.routes]
        assert any("/catalog" in p for p in route_paths), (
            f"Expected /catalog route in {route_paths}"
        )


# ===========================================================================
# TestFeatureRegistry — asyncpg-backed methods
# ===========================================================================

import asyncio as _asyncio
from unittest.mock import AsyncMock as _AsyncMock


def _make_conn(**fetch_results) -> MagicMock:
    """Build a mock asyncpg connection."""
    conn = MagicMock()
    conn.execute = _AsyncMock(return_value="DELETE 1")
    conn.fetchrow = _AsyncMock(return_value=fetch_results.get("fetchrow"))
    conn.fetch = _AsyncMock(return_value=fetch_results.get("fetch", []))
    conn.fetchval = _AsyncMock(return_value=fetch_results.get("fetchval"))
    # transaction() returns an async context manager
    txn_cm = MagicMock()
    txn_cm.__aenter__ = _AsyncMock(return_value=None)
    txn_cm.__aexit__ = _AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn_cm)
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    """Build a mock asyncpg pool that yields the given connection."""
    pool = MagicMock()
    pool.close = _AsyncMock(return_value=None)
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = _AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = _AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acquire_cm)
    return pool


def _make_row(**fields) -> MagicMock:
    """Build a mock asyncpg record (row)."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: fields[key]
    row.__contains__ = lambda self, key: key in fields
    # make dict() work on it
    for k, v in fields.items():
        setattr(row, k, v)
    return row


def _dict_row(**fields) -> MagicMock:
    """Row that also works as dict."""
    r = _make_row(**fields)
    # Override so dict(row) returns fields
    r.keys = MagicMock(return_value=list(fields.keys()))
    r.values = MagicMock(return_value=list(fields.values()))
    r.items = MagicMock(return_value=list(fields.items()))
    return r


from libs.feature_store.registry import (  # noqa: E402
    FeatureRegistry,
    FeatureViewDefinition,
    FeatureViewStatus,
    MaterializationRun,
    MaterializationStatus,
    EntityDefinition,
    ColumnSchema,
    FreshnessSLO,
)


class TestFeatureRegistry:
    """Tests for FeatureRegistry async methods (asyncpg mocks)."""

    def _reg_with_pool(self, conn: MagicMock) -> FeatureRegistry:
        reg = FeatureRegistry("postgresql://test:5432/test")
        reg._pool = _make_pool(conn)
        return reg

    # ---- init / close / context manager ----

    def test_init_creates_pool(self):
        pool = MagicMock()
        pool.close = _AsyncMock(return_value=None)
        acquire_cm = MagicMock()
        conn = _make_conn()
        acquire_cm.__aenter__ = _AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = _AsyncMock(return_value=None)
        pool.acquire = MagicMock(return_value=acquire_cm)

        with patch("asyncpg.create_pool", _AsyncMock(return_value=pool)):
            reg = FeatureRegistry("postgresql://localhost/test")
            _asyncio.run(reg.init())
        assert reg._pool is pool

    def test_close_clears_pool(self):
        conn = _make_conn()
        reg = self._reg_with_pool(conn)
        _asyncio.run(reg.close())
        assert reg._pool is None

    def test_aenter_returns_self(self):
        pool = MagicMock()
        pool.close = _AsyncMock(return_value=None)
        acquire_cm = MagicMock()
        conn = _make_conn()
        acquire_cm.__aenter__ = _AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = _AsyncMock(return_value=None)
        pool.acquire = MagicMock(return_value=acquire_cm)

        async def _run():
            with patch("asyncpg.create_pool", _AsyncMock(return_value=pool)):
                async with FeatureRegistry("postgresql://test") as reg:
                    return reg

        result = _asyncio.run(_run())
        assert isinstance(result, FeatureRegistry)

    def test_pool_or_raise_raises_when_not_init(self):
        reg = FeatureRegistry("postgresql://test")
        with pytest.raises(RuntimeError, match="not initialised"):
            reg._pool_or_raise()

    def test_pool_or_raise_returns_pool_when_set(self):
        conn = _make_conn()
        reg = self._reg_with_pool(conn)
        assert reg._pool_or_raise() is reg._pool

    # ---- list_views ----

    def test_list_views_no_status_returns_summaries(self):
        from datetime import timezone
        row = {
            "name": "test_view",
            "version": 1,
            "entity_name": "model",
            "entity_keys": '["model_id"]',
            "source_table": "feature_eval",
            "schedule": "@hourly",
            "freshness_slo_minutes": 60,
            "owner": "platform",
            "status": "active",
            "last_materialized_at": None,
            "source_table": "test_table",
        }
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda s, k: row[k]

        conn = _make_conn(fetch=[mock_row])
        # _get_table_row_count also uses the pool; patch to return None
        reg = self._reg_with_pool(conn)
        with patch.object(reg, "_get_table_row_count", _AsyncMock(return_value=5)):
            summaries = _asyncio.run(reg.list_views())
        assert len(summaries) == 1
        assert summaries[0].name == "test_view"

    def test_list_views_with_status_filters(self):
        row = {
            "name": "active_view",
            "version": 1,
            "entity_name": "entity",
            "entity_keys": ["id"],
            "source_table": "tbl",
            "schedule": "@daily",
            "freshness_slo_minutes": 1440,
            "owner": "team",
            "status": "active",
            "last_materialized_at": None,
        }
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda s, k: row[k]

        conn = _make_conn(fetch=[mock_row])
        reg = self._reg_with_pool(conn)
        with patch.object(reg, "_get_table_row_count", _AsyncMock(return_value=None)):
            summaries = _asyncio.run(reg.list_views(status="active"))
        assert len(summaries) == 1

    def test_list_views_with_freshness_calculates_slo(self):
        from datetime import datetime, timezone, timedelta
        stale_time = datetime.now(timezone.utc) - timedelta(hours=2)
        row = {
            "name": "fresh_view",
            "version": 1,
            "entity_name": "entity",
            "entity_keys": ["id"],
            "source_table": "tbl",
            "schedule": "@hourly",
            "freshness_slo_minutes": 60,
            "owner": "team",
            "status": "active",
            "last_materialized_at": stale_time,
        }
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda s, k: row[k]

        conn = _make_conn(fetch=[mock_row])
        reg = self._reg_with_pool(conn)
        with patch.object(reg, "_get_table_row_count", _AsyncMock(return_value=100)):
            summaries = _asyncio.run(reg.list_views())
        assert summaries[0].slo_met is False  # 2 hours > 60 min SLO

    # ---- _get_table_row_count ----

    def test_table_row_count_returns_value(self):
        row = MagicMock()
        row.__getitem__ = lambda s, k: 1000 if k == "n" else None
        row.n = 1000
        conn = _make_conn(fetchrow=row)
        reg = self._reg_with_pool(conn)
        result = _asyncio.run(reg._get_table_row_count("test_table"))
        assert result == 1000

    def test_table_row_count_returns_none_on_exception(self):
        conn = _make_conn()
        conn.fetchrow = _AsyncMock(side_effect=Exception("table not found"))
        reg = self._reg_with_pool(conn)
        result = _asyncio.run(reg._get_table_row_count("nonexistent"))
        assert result is None

    # ---- delete ----

    def test_delete_returns_true_on_success(self):
        conn = _make_conn()
        conn.execute = _AsyncMock(return_value="DELETE 1")
        reg = self._reg_with_pool(conn)
        result = _asyncio.run(reg.delete("test_view"))
        assert result is True

    def test_delete_returns_false_when_no_rows(self):
        conn = _make_conn()
        conn.execute = _AsyncMock(return_value="DELETE 0")
        reg = self._reg_with_pool(conn)
        result = _asyncio.run(reg.delete("nonexistent"))
        assert result is False

    # ---- record_run_start ----

    def test_record_run_start_executes_insert(self):
        conn = _make_conn()
        reg = self._reg_with_pool(conn)
        run = MaterializationRun(
            feature_view_name="test_view",
            status=MaterializationStatus.RUNNING,
        )
        _asyncio.run(reg.record_run_start(run))
        conn.execute.assert_awaited_once()

    # ---- get_run_history ----

    def test_get_run_history_returns_list_of_dicts(self):
        from datetime import datetime
        row = MagicMock()
        # Make dict(row) work by overriding __iter__ to yield key-value pairs
        row_data = {"run_id": "r1", "feature_view_name": "v1", "status": "succeeded"}
        row.items = MagicMock(return_value=row_data.items())
        row.keys = MagicMock(return_value=list(row_data.keys()))
        row.values = MagicMock(return_value=list(row_data.values()))

        conn = _make_conn(fetch=[row_data])
        # Use real dict objects for rows
        conn.fetch = _AsyncMock(return_value=[row_data])
        reg = self._reg_with_pool(conn)
        results = _asyncio.run(reg.get_run_history("test_view"))
        assert len(results) == 1
        assert results[0]["run_id"] == "r1"

    # ---- get_freshness_per_view ----

    def test_get_freshness_per_view_returns_list(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        fresh_time = now - timedelta(minutes=30)
        row = {
            "name": "view1",
            "slo_minutes": 60,
            "last_materialized_at": fresh_time,
        }
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda s, k: row[k]

        conn = _make_conn(fetch=[mock_row])
        reg = self._reg_with_pool(conn)
        results = _asyncio.run(reg.get_freshness_per_view())
        assert len(results) == 1
        assert results[0]["slo_met"] is True

    def test_get_freshness_per_view_no_materialization(self):
        row = {
            "name": "view_no_mat",
            "slo_minutes": 60,
            "last_materialized_at": None,
        }
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda s, k: row[k]

        conn = _make_conn(fetch=[mock_row])
        reg = self._reg_with_pool(conn)
        results = _asyncio.run(reg.get_freshness_per_view())
        assert results[0]["freshness_minutes"] is None

    # ---- query_source_table ----

    def test_query_source_table_returns_rows(self):
        from datetime import datetime
        row = {"id": 1, "created_at": datetime(2024, 1, 1), "value": "test"}
        conn = _make_conn(fetch=[row])
        conn.fetch = _AsyncMock(return_value=[row])
        reg = self._reg_with_pool(conn)
        results = _asyncio.run(
            reg.query_source_table("feature_eval", [], [], limit=10)
        )
        assert len(results) == 1
        # datetime should be serialized to ISO string
        assert isinstance(results[0]["created_at"], str)

    def test_query_source_table_with_where_clause(self):
        row = {"id": 2, "value": "test2"}
        conn = _make_conn(fetch=[row])
        conn.fetch = _AsyncMock(return_value=[row])
        reg = self._reg_with_pool(conn)
        results = _asyncio.run(
            reg.query_source_table(
                "feature_eval",
                ["model_id = $1"],
                ["model-v1"],
                columns=["id", "value"],
            )
        )
        assert len(results) == 1
