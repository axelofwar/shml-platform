"""
SHML Platform Libraries

Shared utilities for the SHML ML Platform:
- shml_spark: SparkSessionFactory with Nessie/Iceberg/AQE pre-configured
- shml_features: FeatureClient SDK bridging FiftyOne, Iceberg, and pgvector
"""

try:
    from libs.shml_spark import (
        create_spark_session,
        create_branch,
        merge_branch,
        tag_release,
    )
    from libs.shml_features import FeatureClient
except ImportError:
    pass

__all__ = [
    "create_spark_session",
    "create_branch",
    "merge_branch",
    "tag_release",
    "FeatureClient",
]
