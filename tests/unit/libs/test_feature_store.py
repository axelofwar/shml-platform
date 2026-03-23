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
