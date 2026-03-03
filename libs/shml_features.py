"""Feature client SDK for SHML Platform.

Bridges FiftyOne (visual curation), Iceberg/Nessie (versioned storage),
and pgvector (embedding similarity search) into a unified feature API.

Usage:
    from shml_features import FeatureClient

    client = FeatureClient()

    # Get evaluation features for a model version
    eval_df = client.get_eval_features(model_version="latest")

    # Find similar hard examples via embedding search
    similar = client.find_similar_examples(embedding, k=10)

    # Materialize features from an MLflow run to Iceberg
    client.materialize_eval_features(run_id="abc123")
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger("shml-features")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ.get("POSTGRES_FEATURES_DB", "inference")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "inference")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow-nginx:80")


class FeatureClient:
    """Unified feature access for the SHML ML platform.

    Provides:
    - Evaluation feature retrieval (from Iceberg via Spark or direct Postgres)
    - Hard example similarity search (via pgvector)
    - Feature materialization from MLflow runs
    - FiftyOne dataset integration helpers
    """

    def __init__(
        self,
        postgres_host: str | None = None,
        postgres_port: int | None = None,
        postgres_db: str | None = None,
        postgres_user: str | None = None,
        postgres_password: str | None = None,
    ):
        self._pg_config = {
            "host": postgres_host or POSTGRES_HOST,
            "port": postgres_port or POSTGRES_PORT,
            "dbname": postgres_db or POSTGRES_DB,
            "user": postgres_user or POSTGRES_USER,
            "password": postgres_password or POSTGRES_PASSWORD,
        }
        self._conn: psycopg2.extensions.connection | None = None

    def _get_conn(self) -> psycopg2.extensions.connection:
        """Get or create a PostgreSQL connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._pg_config)
        return self._conn

    # -----------------------------------------------------------------------
    # Schema initialization
    # -----------------------------------------------------------------------

    def init_schema(self) -> None:
        """Create feature tables if they don't exist.

        Uses pgvector for embedding storage and similarity search.
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            # Ensure pgvector extension (already enabled on inference DB)
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # Evaluation features (per model version)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_eval (
                    id SERIAL PRIMARY KEY,
                    model_version TEXT NOT NULL,
                    run_id TEXT,
                    map50 FLOAT,
                    map50_95 FLOAT,
                    recall FLOAT,
                    precision FLOAT,
                    fps FLOAT,
                    dataset TEXT,
                    phase TEXT,
                    hardware TEXT,
                    extra JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (model_version, run_id)
                );
            """
            )

            # Hard example catalog (per image, with CLIP embeddings)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_hard_examples (
                    id SERIAL PRIMARY KEY,
                    image_id TEXT NOT NULL,
                    run_id TEXT,
                    embedding vector(512),
                    failure_cluster_id INT,
                    false_negative_count INT DEFAULT 0,
                    face_size_bucket TEXT,
                    difficulty_score FLOAT,
                    extra JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """
            )

            # Index for embedding similarity search
            # Use HNSW (works with any number of rows, unlike IVFFlat which needs lists * rows)
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_hard_examples_embedding
                ON feature_hard_examples USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            """
            )

            # Training lineage (per run)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_training_lineage (
                    id SERIAL PRIMARY KEY,
                    run_id TEXT UNIQUE NOT NULL,
                    experiment_name TEXT,
                    dataset_version TEXT,
                    config_hash TEXT,
                    parent_run_id TEXT,
                    phase TEXT,
                    hardware_profile TEXT,
                    model_version TEXT,
                    params JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """
            )

            # Dataset quality (per dataset + split)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_dataset_quality (
                    id SERIAL PRIMARY KEY,
                    dataset_name TEXT NOT NULL,
                    split TEXT NOT NULL,
                    total_images INT,
                    missing_annot_rate FLOAT,
                    misaligned_rate FLOAT,
                    face_size_distribution JSONB DEFAULT '{}',
                    extra JSONB DEFAULT '{}',
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (dataset_name, split)
                );
            """
            )

            conn.commit()
            logger.info("Feature schema initialized")

    # -----------------------------------------------------------------------
    # Feature retrieval
    # -----------------------------------------------------------------------

    def get_eval_features(
        self,
        model_version: str = "latest",
        limit: int = 100,
    ) -> list[dict]:
        """Get evaluation features for a model version.

        Parameters
        ----------
        model_version : str
            Model version string, or "latest" for most recent.
        limit : int
            Maximum rows to return.

        Returns
        -------
        list[dict]
            Evaluation feature records.
        """
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if model_version == "latest":
                cur.execute(
                    "SELECT * FROM feature_eval ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            else:
                cur.execute(
                    "SELECT * FROM feature_eval WHERE model_version = %s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (model_version, limit),
                )
            return [dict(row) for row in cur.fetchall()]

    def find_similar_examples(
        self,
        embedding: list[float],
        k: int = 10,
        cluster_id: int | None = None,
    ) -> list[dict]:
        """Find hard examples similar to the given embedding via pgvector.

        Parameters
        ----------
        embedding : list[float]
            512-dimensional CLIP embedding.
        k : int
            Number of nearest neighbors.
        cluster_id : int, optional
            Filter to a specific failure cluster.

        Returns
        -------
        list[dict]
            Similar hard example records with distance.
        """
        if not embedding or len(embedding) == 0:
            logger.warning("find_similar_examples called with empty embedding")
            return []

        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Check if the table has any rows with non-null embeddings
            cur.execute(
                "SELECT COUNT(*) FROM feature_hard_examples WHERE embedding IS NOT NULL"
            )
            count = cur.fetchone()["count"]
            if count == 0:
                logger.warning("No embeddings in feature_hard_examples — cannot search")
                return []

            emb_str = "[" + ",".join(str(x) for x in embedding) + "]"
            if cluster_id is not None:
                cur.execute(
                    """
                    SELECT *, embedding <=> %s::vector AS distance
                    FROM feature_hard_examples
                    WHERE failure_cluster_id = %s
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (emb_str, cluster_id, emb_str, k),
                )
            else:
                cur.execute(
                    """
                    SELECT *, embedding <=> %s::vector AS distance
                    FROM feature_hard_examples
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (emb_str, emb_str, k),
                )
            return [dict(row) for row in cur.fetchall()]

    # -----------------------------------------------------------------------
    # Feature materialization
    # -----------------------------------------------------------------------

    def materialize_eval_features(self, run_id: str) -> bool:
        """Materialize evaluation features from an MLflow run to the feature store.

        Reads metrics from the MLflow run and inserts/upserts into ``feature_eval``.

        Parameters
        ----------
        run_id : str
            MLflow run ID.

        Returns
        -------
        bool
            True if materialization succeeded.
        """
        import requests

        url = f"{MLFLOW_TRACKING_URI}/api/2.0/mlflow/runs/get"
        resp = requests.get(url, params={"run_id": run_id}, timeout=15)
        if not resp.ok:
            logger.error("Failed to fetch run %s: %s", run_id, resp.text)
            return False

        run_data = resp.json().get("run", {})
        metrics = {
            m["key"]: m["value"] for m in run_data.get("data", {}).get("metrics", [])
        }
        params = {
            p["key"]: p["value"] for p in run_data.get("data", {}).get("params", [])
        }
        tags = {t["key"]: t["value"] for t in run_data.get("data", {}).get("tags", [])}

        model_version = tags.get("model_version", params.get("model", "unknown"))

        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feature_eval
                    (model_version, run_id, map50, map50_95, recall, precision,
                     fps, dataset, phase, hardware, extra)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (model_version, run_id) DO UPDATE SET
                    map50 = EXCLUDED.map50,
                    map50_95 = EXCLUDED.map50_95,
                    recall = EXCLUDED.recall,
                    precision = EXCLUDED.precision,
                    fps = EXCLUDED.fps,
                    extra = EXCLUDED.extra,
                    created_at = NOW()
                """,
                (
                    model_version,
                    run_id,
                    metrics.get("final_mAP50") or metrics.get("mAP50"),
                    metrics.get("final_mAP50_95") or metrics.get("mAP50_95"),
                    metrics.get("final_recall") or metrics.get("recall"),
                    metrics.get("final_precision") or metrics.get("precision"),
                    metrics.get("fps"),
                    params.get("dataset", tags.get("dataset")),
                    tags.get("phase"),
                    tags.get("hardware", params.get("device")),
                    json.dumps(
                        {
                            "optimizer": params.get("optimizer"),
                            "epochs": params.get("epochs"),
                            "batch_size": params.get("batch_size"),
                        }
                    ),
                ),
            )
            conn.commit()
            logger.info("Materialized eval features for run %s", run_id[:8])
            return True

    def materialize_training_lineage(self, run_id: str) -> bool:
        """Materialize training lineage from an MLflow run.

        Parameters
        ----------
        run_id : str
            MLflow run ID.

        Returns
        -------
        bool
            True if materialization succeeded.
        """
        import requests
        import hashlib

        url = f"{MLFLOW_TRACKING_URI}/api/2.0/mlflow/runs/get"
        resp = requests.get(url, params={"run_id": run_id}, timeout=15)
        if not resp.ok:
            logger.error("Failed to fetch run %s: %s", run_id, resp.text)
            return False

        run_data = resp.json().get("run", {})
        info = run_data.get("info", {})
        params = {
            p["key"]: p["value"] for p in run_data.get("data", {}).get("params", [])
        }
        tags = {t["key"]: t["value"] for t in run_data.get("data", {}).get("tags", [])}

        # Config hash for reproducibility tracking
        config_str = json.dumps(params, sort_keys=True)
        config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:16]

        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feature_training_lineage
                    (run_id, experiment_name, dataset_version, config_hash,
                     parent_run_id, phase, hardware_profile, params)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    config_hash = EXCLUDED.config_hash,
                    params = EXCLUDED.params,
                    created_at = NOW()
                """,
                (
                    run_id,
                    tags.get("mlflow.experimentName"),
                    params.get("dataset_version", tags.get("dataset_version")),
                    config_hash,
                    tags.get("mlflow.parentRunId"),
                    tags.get("phase"),
                    tags.get("hardware", params.get("device")),
                    json.dumps(params),
                ),
            )
            conn.commit()
            logger.info("Materialized lineage for run %s", run_id[:8])
            return True

    # -----------------------------------------------------------------------
    # FiftyOne integration helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def load_fiftyone_dataset(
        name: str,
        dataset_dir: str,
        dataset_type: str = "yolo",
        labels_path: str | None = None,
    ):
        """Load or create a FiftyOne dataset.

        Parameters
        ----------
        name : str
            Dataset name in FiftyOne.
        dataset_dir : str
            Path to image directory.
        dataset_type : str
            Format: "yolo", "coco", "voc", "tf".
        labels_path : str, optional
            Path to label file (for COCO format).

        Returns
        -------
        fiftyone.Dataset
            The loaded dataset.
        """
        import fiftyone as fo

        # Check if dataset already exists
        if fo.dataset_exists(name):
            logger.info("Loading existing FiftyOne dataset: %s", name)
            return fo.load_dataset(name)

        type_map = {
            "yolo": fo.types.YOLOv5Dataset,
            "coco": fo.types.COCODetectionDataset,
            "voc": fo.types.VOCDetectionDataset,
        }
        fo_type = type_map.get(dataset_type)
        if fo_type is None:
            raise ValueError(f"Unsupported dataset type: {dataset_type}")

        kwargs = {"dataset_dir": dataset_dir, "dataset_type": fo_type}
        if labels_path and dataset_type == "coco":
            kwargs["labels_path"] = labels_path

        dataset = fo.Dataset.from_dir(name=name, **kwargs)
        dataset.persistent = True
        logger.info("Created FiftyOne dataset: %s (%d samples)", name, len(dataset))
        return dataset

    @staticmethod
    def export_hard_examples_to_fiftyone(
        dataset_name: str,
        image_dir: str,
        hard_example_ids: list[str],
    ):
        """Tag hard examples in a FiftyOne dataset for visual review.

        Parameters
        ----------
        dataset_name : str
            Existing FiftyOne dataset name.
        image_dir : str
            Path to images.
        hard_example_ids : list[str]
            Image IDs to tag as hard examples.
        """
        import fiftyone as fo

        dataset = fo.load_dataset(dataset_name)
        view = dataset.match({"filepath": {"$regex": "|".join(hard_example_ids)}})
        view.tag_samples("hard_example")
        logger.info("Tagged %d hard examples in %s", len(view), dataset_name)
        return view

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
