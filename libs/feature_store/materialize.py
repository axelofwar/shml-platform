"""Feature store materialization — writes Polars DataFrames to Apache Iceberg via Nessie.

Uses pyiceberg (>=0.7) with the Nessie REST catalog. Does not require Spark.

Usage:
    from libs.feature_store.materialize import materialize_feature_view

    import polars as pl
    df = pl.DataFrame({"entity_id": [1, 2], "value": [0.1, 0.9]})
    materialize_feature_view(
        feature_view="eval_metrics",
        df=df,
        branch="main",
    )
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Nessie / Iceberg configuration (from environment)
# ---------------------------------------------------------------------------

NESSIE_URI = os.environ.get("NESSIE_URI", "http://nessie:19120/api/v2")
ICEBERG_WAREHOUSE = os.environ.get("ICEBERG_WAREHOUSE", "/data/iceberg-warehouse")
NESSIE_DEFAULT_REF = os.environ.get("NESSIE_DEFAULT_REF", "main")
ICEBERG_NAMESPACE = os.environ.get("ICEBERG_NAMESPACE", "shml")


def _get_catalog(branch: str = NESSIE_DEFAULT_REF):
    """Build a pyiceberg NessieCatalog for *branch*."""
    from pyiceberg.catalog import load_catalog

    catalog = load_catalog(
        "nessie",
        **{
            "type": "rest",
            "uri": NESSIE_URI,
            "ref": branch,
            "warehouse": ICEBERG_WAREHOUSE,
        },
    )
    return catalog


def _ensure_namespace(catalog, namespace: str = ICEBERG_NAMESPACE) -> None:
    """Create Iceberg namespace if it doesn't exist yet."""
    from pyiceberg.exceptions import NamespaceAlreadyExistsError

    try:
        catalog.create_namespace(namespace)
        logger.info("Created Iceberg namespace: %s", namespace)
    except NamespaceAlreadyExistsError:
        pass


def _polars_to_pyarrow(df):
    """Convert Polars DataFrame to PyArrow Table for pyiceberg write."""
    return df.to_arrow()


def _build_iceberg_schema(df):
    """Infer pyiceberg schema from Polars DataFrame."""
    from pyiceberg.schema import Schema
    from pyiceberg.types import (
        NestedField,
        StringType,
        FloatType,
        DoubleType,
        LongType,
        IntegerType,
        BooleanType,
        TimestampType,
    )
    import polars as pl

    _pl_to_iceberg = {
        pl.Utf8: StringType(),
        pl.String: StringType(),
        pl.Float32: FloatType(),
        pl.Float64: DoubleType(),
        pl.Int32: IntegerType(),
        pl.Int64: LongType(),
        pl.Boolean: BooleanType(),
        pl.Datetime: TimestampType(),
    }

    fields = []
    for i, (name, dtype) in enumerate(zip(df.columns, df.dtypes), start=1):
        iceberg_type = _pl_to_iceberg.get(dtype, StringType())
        fields.append(NestedField(field_id=i, name=name, field_type=iceberg_type, required=False))

    return Schema(*fields)


def materialize_feature_view(
    feature_view: str,
    df,
    branch: str = NESSIE_DEFAULT_REF,
    namespace: str = ICEBERG_NAMESPACE,
    partition_cols: Optional[list[str]] = None,
) -> str:
    """Write a Polars DataFrame to an Iceberg table via the Nessie catalog.

    Creates the table on first run (schema inferred from df). Subsequent runs
    append new data (mode="append").  A ``_materialized_at`` timestamp column
    is injected automatically.

    Args:
        feature_view: Name of the feature view / Iceberg table.
        df: Polars DataFrame to write.
        branch: Nessie branch (default: main).
        namespace: Iceberg namespace (default: shml).
        partition_cols: Optional partition column names.

    Returns:
        Full Iceberg table identifier, e.g. "shml.eval_metrics".
    """
    import polars as pl

    # Inject materialization timestamp
    df = df.with_columns(
        pl.lit(datetime.now(tz=timezone.utc).isoformat()).alias("_materialized_at")
    )

    table_id = f"{namespace}.{feature_view}"
    catalog = _get_catalog(branch)
    _ensure_namespace(catalog, namespace)

    arrow_table = _polars_to_pyarrow(df)

    if catalog.table_exists(table_id):
        tbl = catalog.load_table(table_id)
        tbl.append(arrow_table)
        logger.info(
            "Appended %d rows to Iceberg table %s (branch=%s)",
            len(df),
            table_id,
            branch,
        )
    else:
        from pyiceberg.partitioning import PartitionSpec, PartitionField
        from pyiceberg.transforms import IdentityTransform

        schema = _build_iceberg_schema(df)

        partition_spec = PartitionSpec()
        if partition_cols:
            fields = []
            for col in partition_cols:
                if col in df.columns:
                    col_id = df.columns.index(col) + 1
                    fields.append(
                        PartitionField(
                            source_id=col_id,
                            field_id=1000 + col_id,
                            transform=IdentityTransform(),
                            name=f"{col}_partition",
                        )
                    )
            if fields:
                partition_spec = PartitionSpec(*fields)

        catalog.create_table(
            identifier=table_id,
            schema=schema,
            partition_spec=partition_spec,
        )
        tbl = catalog.load_table(table_id)
        tbl.append(arrow_table)
        logger.info(
            "Created and wrote %d rows to new Iceberg table %s (branch=%s)",
            len(df),
            table_id,
            branch,
        )

    return table_id


def read_feature_view(
    feature_view: str,
    branch: str = NESSIE_DEFAULT_REF,
    namespace: str = ICEBERG_NAMESPACE,
    filters: Optional[list] = None,
):
    """Read an Iceberg feature view table as a Polars DataFrame.

    Args:
        feature_view: Name of the feature view / Iceberg table.
        branch: Nessie branch.
        namespace: Iceberg namespace.
        filters: Optional pyiceberg expression filters.

    Returns:
        Polars DataFrame.
    """
    import polars as pl

    table_id = f"{namespace}.{feature_view}"
    catalog = _get_catalog(branch)
    tbl = catalog.load_table(table_id)

    scan = tbl.scan()
    if filters:
        for f in filters:
            scan = scan.filter(f)

    arrow_table = scan.to_arrow()
    df = pl.from_arrow(arrow_table)
    logger.info("Read %d rows from Iceberg table %s", len(df), table_id)
    return df
