"""Spark session factory with Nessie/Iceberg integration.

Provides a single-call factory for creating PySpark sessions pre-configured
with Iceberg, Nessie catalog, and AQE optimizations.

Usage:
    from shml_spark import create_spark_session

    spark = create_spark_session("my-job")
    spark.sql("SELECT * FROM nessie.shml.features.dataset_quality_v1")
"""

import os
from pyspark.sql import SparkSession


# ---------------------------------------------------------------------------
# Configuration (env-var driven for K8s portability)
# ---------------------------------------------------------------------------

NESSIE_URI = os.environ.get("NESSIE_URI", "http://nessie:19120/api/v2")
ICEBERG_WAREHOUSE = os.environ.get("ICEBERG_WAREHOUSE", "/tmp/iceberg-warehouse")
ICEBERG_JAR = os.environ.get(
    "ICEBERG_JAR",
    "org.apache.iceberg:iceberg-spark-runtime-4.0_2.13:1.10.1",
)


def create_spark_session(
    app_name: str = "shml-spark",
    *,
    nessie_uri: str | None = None,
    warehouse: str | None = None,
    nessie_ref: str = "main",
    extra_config: dict[str, str] | None = None,
    local_mode: bool = True,
) -> SparkSession:
    """Create a PySpark session with Iceberg + Nessie pre-configured.

    Parameters
    ----------
    app_name : str
        Spark application name.
    nessie_uri : str, optional
        Nessie REST API endpoint. Defaults to ``NESSIE_URI`` env var.
    warehouse : str, optional
        Iceberg warehouse path. Defaults to ``ICEBERG_WAREHOUSE`` env var.
    nessie_ref : str
        Default Nessie branch (default: ``main``).
    extra_config : dict, optional
        Additional Spark config key-value pairs.
    local_mode : bool
        If True, use ``local[*]`` master. If False, connect to cluster.

    Returns
    -------
    SparkSession
        Configured session with catalog ``nessie`` available.
    """
    nessie_uri = nessie_uri or NESSIE_URI
    warehouse = warehouse or ICEBERG_WAREHOUSE

    builder = (
        SparkSession.builder.appName(app_name)
        .config("spark.jars.packages", ICEBERG_JAR)
        # --- Nessie catalog (Iceberg REST) ---
        .config("spark.sql.catalog.nessie", "org.apache.iceberg.spark.SparkCatalog")
        .config(
            "spark.sql.catalog.nessie.catalog-impl",
            "org.apache.iceberg.nessie.NessieCatalog",
        )
        .config("spark.sql.catalog.nessie.uri", nessie_uri)
        .config("spark.sql.catalog.nessie.ref", nessie_ref)
        .config("spark.sql.catalog.nessie.warehouse", warehouse)
        # --- AQE optimizations (from EB-04 learnings) ---
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        .config("spark.sql.adaptive.skewJoin.enabled", "true")
        .config("spark.sql.adaptive.localShuffleReader.enabled", "true")
        # --- Iceberg defaults ---
        .config("spark.sql.defaultCatalog", "nessie")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
    )

    if local_mode:
        builder = builder.master("local[*]")

    # Apply any extra config
    if extra_config:
        for key, value in extra_config.items():
            builder = builder.config(key, value)

    return builder.getOrCreate()


def create_branch(
    spark: SparkSession, branch_name: str, from_ref: str = "main"
) -> None:
    """Create a Nessie branch for WAP (Write-Audit-Publish) workflow.

    Usage:
        create_branch(spark, "staging/annotations-v5")
        spark.conf.set("spark.sql.catalog.nessie.ref", "staging/annotations-v5")
        # ... write data ...
        merge_branch(spark, "staging/annotations-v5")
    """
    spark.sql(
        f"CREATE BRANCH IF NOT EXISTS `{branch_name}` IN nessie FROM `{from_ref}`"
    )


def merge_branch(spark: SparkSession, branch_name: str, into: str = "main") -> None:
    """Merge a Nessie branch into the target (default: main)."""
    spark.sql(f"MERGE BRANCH `{branch_name}` INTO `{into}` IN nessie")


def tag_release(spark: SparkSession, tag_name: str, ref: str = "main") -> None:
    """Tag the current state for rollback capability."""
    spark.sql(f"CREATE TAG IF NOT EXISTS `{tag_name}` IN nessie FROM `{ref}`")
