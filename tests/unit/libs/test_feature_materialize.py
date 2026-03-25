from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch


_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _install_pyiceberg_stubs() -> None:
    pyiceberg = ModuleType("pyiceberg")
    catalog = ModuleType("pyiceberg.catalog")
    exceptions = ModuleType("pyiceberg.exceptions")
    schema = ModuleType("pyiceberg.schema")
    types = ModuleType("pyiceberg.types")
    partitioning = ModuleType("pyiceberg.partitioning")
    transforms = ModuleType("pyiceberg.transforms")

    exceptions.NamespaceAlreadyExistsError = type("NamespaceAlreadyExistsError", (Exception,), {})
    schema.Schema = lambda *fields: {"fields": fields}
    types.NestedField = lambda **kwargs: kwargs
    types.StringType = lambda: "string"
    types.FloatType = lambda: "float32"
    types.DoubleType = lambda: "float64"
    types.LongType = lambda: "int64"
    types.IntegerType = lambda: "int32"
    types.BooleanType = lambda: "bool"
    types.TimestampType = lambda: "ts"
    partitioning.PartitionSpec = lambda *fields: {"fields": list(fields)}
    partitioning.PartitionField = lambda **kwargs: kwargs
    transforms.IdentityTransform = lambda: "identity"

    sys.modules["pyiceberg"] = pyiceberg
    sys.modules["pyiceberg.catalog"] = catalog
    sys.modules["pyiceberg.exceptions"] = exceptions
    sys.modules["pyiceberg.schema"] = schema
    sys.modules["pyiceberg.types"] = types
    sys.modules["pyiceberg.partitioning"] = partitioning
    sys.modules["pyiceberg.transforms"] = transforms


def _install_polars_stub() -> None:
    polars = ModuleType("polars")
    polars.Utf8 = object()
    polars.String = object()
    polars.Float32 = object()
    polars.Float64 = object()
    polars.Int32 = object()
    polars.Int64 = object()
    polars.Boolean = object()
    polars.Datetime = object()
    polars.lit = lambda value: MagicMock(alias=lambda name: (value, name))
    polars.from_arrow = lambda table: {"from_arrow": table}
    sys.modules["polars"] = polars


def test_get_catalog_and_ensure_namespace():
    _install_pyiceberg_stubs()
    _install_polars_stub()
    import libs.feature_store.materialize as materialize

    mock_catalog = MagicMock()
    sys.modules["pyiceberg.catalog"].load_catalog = MagicMock(return_value=mock_catalog)

    catalog = materialize._get_catalog("dev")
    materialize._ensure_namespace(mock_catalog, "demo")

    sys.modules["pyiceberg.catalog"].load_catalog.assert_called_once()
    mock_catalog.create_namespace.assert_called_once_with("demo")


def test_ensure_namespace_ignores_existing_error():
    _install_pyiceberg_stubs()
    _install_polars_stub()
    import libs.feature_store.materialize as materialize

    exc = sys.modules["pyiceberg.exceptions"].NamespaceAlreadyExistsError
    mock_catalog = MagicMock()
    mock_catalog.create_namespace.side_effect = exc("exists")

    materialize._ensure_namespace(mock_catalog, "demo")


def test_materialize_feature_view_append_and_create_paths():
    _install_pyiceberg_stubs()
    _install_polars_stub()
    import libs.feature_store.materialize as materialize

    class FakeDF:
        columns = ["entity_id", "country"]
        dtypes = [sys.modules["polars"].Int64, sys.modules["polars"].String]

        def with_columns(self, *args, **kwargs):
            return self

        def to_arrow(self):
            return {"arrow": True}

        def __len__(self):
            return 2

    append_table = MagicMock()
    create_table = MagicMock()
    create_table.append = MagicMock()
    catalog_append = MagicMock()
    catalog_append.table_exists.return_value = True
    catalog_append.load_table.return_value = append_table

    catalog_create = MagicMock()
    catalog_create.table_exists.return_value = False
    catalog_create.load_table.return_value = create_table

    with patch.object(materialize, "_get_catalog", side_effect=[catalog_append, catalog_create]), patch.object(
        materialize, "_ensure_namespace"
    ):
        table_id_append = materialize.materialize_feature_view("fv1", FakeDF(), partition_cols=["country"])
        table_id_create = materialize.materialize_feature_view("fv2", FakeDF(), partition_cols=["country"])

    assert table_id_append == "shml.fv1"
    append_table.append.assert_called_once()
    assert table_id_create == "shml.fv2"
    catalog_create.create_table.assert_called_once()
    create_table.append.assert_called_once()


def test_read_feature_view_applies_filters():
    _install_pyiceberg_stubs()
    _install_polars_stub()
    import libs.feature_store.materialize as materialize

    scan = MagicMock()
    scan.filter.return_value = scan
    scan.to_arrow.return_value = {"rows": 2}
    table = MagicMock()
    table.scan.return_value = scan
    catalog = MagicMock()
    catalog.load_table.return_value = table

    with patch.object(materialize, "_get_catalog", return_value=catalog):
        result = materialize.read_feature_view("fv1", filters=["a", "b"])

    assert result == {"from_arrow": {"rows": 2}}
    assert scan.filter.call_count == 2
