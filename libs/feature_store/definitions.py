"""Built-in feature view definitions for SHML Platform.

Registers the existing feature tables as formal FeatureView contracts.
These definitions map directly to the tables created by FeatureClient.init_schema()
in libs/shml_features.py.

Run this module to seed the registry:
    python -m ray_compute.features.definitions
"""

from __future__ import annotations

import logging
import os

from .registry import (
    ColumnSchema,
    ComputeEngine,
    EntityDefinition,
    FeatureRegistry,
    FeatureViewDefinition,
    FeatureViewStatus,
    FreshnessSLO,
)

logger = logging.getLogger("shml-features.definitions")

# ---------------------------------------------------------------------------
# Built-in feature view definitions
# ---------------------------------------------------------------------------

EVAL_FEATURES = FeatureViewDefinition(
    name="eval_metrics",
    version=1,
    entity=EntityDefinition(
        name="model_version",
        join_keys=["model_version", "run_id"],
        description="Evaluation metrics keyed by model version and training run",
    ),
    schema=[
        ColumnSchema(
            name="model_version", type="TEXT", description="Model version identifier"
        ),
        ColumnSchema(name="run_id", type="TEXT", description="MLflow run ID"),
        ColumnSchema(name="map50", type="FLOAT", description="mAP@0.50"),
        ColumnSchema(name="map50_95", type="FLOAT", description="mAP@0.50:0.95"),
        ColumnSchema(name="recall", type="FLOAT", description="Detection recall"),
        ColumnSchema(name="precision", type="FLOAT", description="Detection precision"),
        ColumnSchema(
            name="fps", type="FLOAT", description="Inference throughput (frames/sec)"
        ),
        ColumnSchema(
            name="dataset", type="TEXT", description="Evaluation dataset name"
        ),
        ColumnSchema(name="phase", type="TEXT", description="Training phase"),
        ColumnSchema(
            name="hardware", type="TEXT", description="GPU used for evaluation"
        ),
        ColumnSchema(
            name="extra", type="JSONB", description="Additional metrics and hyperparams"
        ),
    ],
    source_table="feature_eval",
    schedule="@hourly",
    freshness_slo=FreshnessSLO(max_staleness_minutes=120, target_percentile=99.0),
    compute_engine=ComputeEngine.RAY,
    owner="platform-team",
    description=(
        "Per-model evaluation metrics materialized from MLflow runs. "
        "Updated after each training or evaluation job completes."
    ),
    status=FeatureViewStatus.ACTIVE,
    tags={"domain": "model-quality", "tier": "critical"},
)

TRAINING_LINEAGE = FeatureViewDefinition(
    name="training_lineage",
    version=1,
    entity=EntityDefinition(
        name="training_run",
        join_keys=["run_id"],
        description="Training provenance keyed by MLflow run ID",
    ),
    schema=[
        ColumnSchema(name="run_id", type="TEXT", description="MLflow run ID (unique)"),
        ColumnSchema(
            name="experiment_name", type="TEXT", description="MLflow experiment"
        ),
        ColumnSchema(
            name="dataset_version", type="TEXT", description="Dataset version used"
        ),
        ColumnSchema(
            name="config_hash",
            type="TEXT",
            description="SHA-256 of hyperparameter config",
        ),
        ColumnSchema(
            name="parent_run_id",
            type="TEXT",
            description="Parent run (for resumed training)",
        ),
        ColumnSchema(name="phase", type="TEXT", description="Training phase tag"),
        ColumnSchema(name="hardware_profile", type="TEXT", description="GPU hardware"),
        ColumnSchema(
            name="model_version", type="TEXT", description="Resulting model version"
        ),
        ColumnSchema(
            name="params", type="JSONB", description="Full hyperparameter snapshot"
        ),
    ],
    source_table="feature_training_lineage",
    schedule="@hourly",
    freshness_slo=FreshnessSLO(max_staleness_minutes=120, target_percentile=99.0),
    compute_engine=ComputeEngine.RAY,
    owner="platform-team",
    description=(
        "Training lineage tracking — every run's dataset, config, parent, and hardware. "
        "Enables reproducibility audits and config drift detection."
    ),
    status=FeatureViewStatus.ACTIVE,
    tags={"domain": "lineage", "tier": "standard"},
)

DATASET_QUALITY = FeatureViewDefinition(
    name="dataset_quality",
    version=1,
    entity=EntityDefinition(
        name="dataset_split",
        join_keys=["dataset_name", "split"],
        description="Dataset quality metrics keyed by dataset name and split",
    ),
    schema=[
        ColumnSchema(
            name="dataset_name", type="TEXT", description="Dataset identifier"
        ),
        ColumnSchema(name="split", type="TEXT", description="train/val/test split"),
        ColumnSchema(name="total_images", type="INT", description="Image count"),
        ColumnSchema(
            name="missing_annot_rate",
            type="FLOAT",
            description="Fraction of images with no annotations",
        ),
        ColumnSchema(
            name="misaligned_rate",
            type="FLOAT",
            description="Fraction with misaligned bboxes",
        ),
        ColumnSchema(
            name="face_size_distribution",
            type="JSONB",
            description="Size bucket histogram",
        ),
        ColumnSchema(
            name="extra", type="JSONB", description="Additional quality metrics"
        ),
    ],
    source_table="feature_dataset_quality",
    schedule="@daily",
    freshness_slo=FreshnessSLO(
        max_staleness_minutes=1440, target_percentile=99.0
    ),  # 24 hours
    compute_engine=ComputeEngine.RAY,
    owner="platform-team",
    description=(
        "Per-dataset-split quality metrics — image counts, annotation coverage, "
        "face size distributions. Updated daily or after dataset changes."
    ),
    status=FeatureViewStatus.ACTIVE,
    tags={"domain": "data-quality", "tier": "standard"},
)

HARD_EXAMPLES = FeatureViewDefinition(
    name="hard_examples",
    version=1,
    entity=EntityDefinition(
        name="image",
        join_keys=["image_id"],
        description="Hard example catalog with CLIP embeddings for similarity search",
    ),
    schema=[
        ColumnSchema(name="image_id", type="TEXT", description="Image file identifier"),
        ColumnSchema(
            name="run_id",
            type="TEXT",
            description="MLflow run that identified this example",
        ),
        ColumnSchema(
            name="embedding",
            type="vector(512)",
            description="CLIP embedding for similarity search",
        ),
        ColumnSchema(
            name="failure_cluster_id", type="INT", description="Failure mode cluster"
        ),
        ColumnSchema(
            name="false_negative_count",
            type="INT",
            description="Missed detection count",
        ),
        ColumnSchema(
            name="face_size_bucket", type="TEXT", description="tiny/small/medium/large"
        ),
        ColumnSchema(
            name="difficulty_score", type="FLOAT", description="Computed difficulty 0-1"
        ),
    ],
    source_table="feature_hard_examples",
    schedule="@daily",
    freshness_slo=FreshnessSLO(max_staleness_minutes=1440, target_percentile=95.0),
    compute_engine=ComputeEngine.RAY,
    owner="platform-team",
    description=(
        "Hard example catalog with CLIP embeddings enabling pgvector similarity search. "
        "Populated after evaluation runs identify difficult samples."
    ),
    status=FeatureViewStatus.ACTIVE,
    tags={"domain": "hard-examples", "tier": "standard", "vector_search": "true"},
)

# Convenience list
BUILTIN_VIEWS = [EVAL_FEATURES, TRAINING_LINEAGE, DATASET_QUALITY, HARD_EXAMPLES]


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def _load_pg_password() -> str:
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password:
        for sp in [
            "/run/secrets/shared_db_password",
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "secrets",
                "shared_db_password.txt",
            ),
        ]:
            try:
                with open(sp) as f:
                    return f.read().strip()
            except FileNotFoundError:
                continue
    return password


def get_pg_dsn() -> str:
    """Build asyncpg-compatible DSN from environment."""
    password = _load_pg_password()
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_FEATURES_DB", "inference")
    user = os.environ.get("POSTGRES_USER", "inference")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def get_pg_config() -> dict:
    """Build PostgreSQL config dict (kept for backward compatibility)."""
    password = _load_pg_password()
    return {
        "host": os.environ.get("POSTGRES_HOST", "postgres"),
        "port": int(os.environ.get("POSTGRES_PORT", "5432")),
        "dbname": os.environ.get("POSTGRES_FEATURES_DB", "inference"),
        "user": os.environ.get("POSTGRES_USER", "inference"),
        "password": password,
    }


async def register_builtin_views(registry: FeatureRegistry | None = None) -> FeatureRegistry:
    """Register all built-in feature views. Creates and inits registry if none provided."""
    if registry is None:
        registry = FeatureRegistry(get_pg_dsn())
        await registry.init()
    for view in BUILTIN_VIEWS:
        await registry.register(view)
        logger.info(
            "Registered: %s (entity=%s, slo=%dm)",
            view.name,
            view.entity.name,
            view.freshness_slo.max_staleness_minutes,
        )
    return registry


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )

    async def _main() -> None:
        reg = await register_builtin_views()
        views = await reg.list_views()
        print(
            f"\n{'Name':<25} {'Entity':<18} {'Source Table':<28} {'Schedule':<10} {'SLO':<8} {'Status'}"
        )
        print("-" * 110)
        for v in views:
            print(
                f"{v.name:<25} {v.entity_name:<18} {v.source_table:<28} {v.schedule:<10} {v.freshness_slo_minutes}m     {v.status}"
            )
        await reg.close()

    asyncio.run(_main())
