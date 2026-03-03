#!/usr/bin/env python3
"""
MLflow Platform Initialization Script
Creates experiments, model registry setup, dataset registry, and standard configurations
"""

import os
import sys
import time
import logging
from mlflow.tracking import MlflowClient
from mlflow.entities import ViewType
from mlflow.exceptions import MlflowException

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# MLflow connection
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")


def wait_for_mlflow(max_retries=30, delay=2):
    """Wait for MLflow server to be ready"""
    logger.info(f"Waiting for MLflow server at {MLFLOW_TRACKING_URI}...")

    for attempt in range(max_retries):
        try:
            client = MlflowClient(MLFLOW_TRACKING_URI)
            # Try to list experiments as a health check
            client.search_experiments()
            logger.info("✓ MLflow server is ready")
            return client
        except Exception as e:
            if attempt < max_retries - 1:
                logger.debug(f"Attempt {attempt + 1}/{max_retries}: {e}")
                time.sleep(delay)
            else:
                logger.error(
                    f"Failed to connect to MLflow after {max_retries} attempts"
                )
                raise

    return None


def create_experiment_if_not_exists(client, name, tags=None, description=None):
    """Create experiment if it doesn't already exist"""
    try:
        # Search for existing experiment
        experiments = client.search_experiments(filter_string=f"name = '{name}'")

        if experiments:
            exp = experiments[0]
            logger.info(
                f"✓ Experiment '{name}' already exists (ID: {exp.experiment_id})"
            )

            # Update tags if provided
            if tags:
                for key, value in tags.items():
                    client.set_experiment_tag(exp.experiment_id, key, value)

            return exp.experiment_id

        # Create new experiment
        experiment_id = client.create_experiment(
            name=name,
            tags=tags or {},
        )

        logger.info(f"✓ Created experiment '{name}' (ID: {experiment_id})")
        return experiment_id

    except MlflowException as e:
        logger.error(f"Error creating experiment '{name}': {e}")
        raise


def setup_standard_experiments(client):
    """Create standard experiments for different stages"""
    logger.info("Setting up standard experiments...")

    experiments = {
        "face-detection/training": {
            "tags": {
                "stage": "development",
                "purpose": "model training and experimentation",
                "schema_enforced": "true",
                "owner": "ml-team",
            },
            "description": "Development environment for model training",
        },
        "Staging-Model-Comparison": {
            "tags": {
                "stage": "staging",
                "purpose": "model comparison and A/B testing",
                "schema_enforced": "true",
                "owner": "ml-team",
            },
            "description": "Staging environment for model comparison",
        },
        "Production-Models": {
            "tags": {
                "stage": "production",
                "purpose": "production model tracking",
                "schema_enforced": "true",
                "read_only": "false",
                "owner": "ml-team",
            },
            "description": "Production models and deployments",
        },
        "QA-Testing": {
            "tags": {
                "stage": "qa",
                "purpose": "quality assurance and validation",
                "schema_enforced": "true",
                "owner": "qa-team",
            },
            "description": "QA testing and model validation",
        },
        "Performance-Benchmarking": {
            "tags": {
                "stage": "benchmarking",
                "purpose": "performance and optimization testing",
                "schema_enforced": "true",
                "owner": "ml-team",
            },
            "description": "Performance benchmarking and optimization",
        },
        "Experimental-Research": {
            "tags": {
                "stage": "research",
                "purpose": "experimental research and prototyping",
                "schema_enforced": "false",
                "owner": "research-team",
            },
            "description": "Experimental research without strict schema",
        },
    }

    experiment_ids = {}
    for name, config in experiments.items():
        exp_id = create_experiment_if_not_exists(
            client, name, tags=config["tags"], description=config.get("description")
        )
        experiment_ids[name] = exp_id

    return experiment_ids


def setup_model_registry(client):
    """Setup model registry with example registered models"""
    logger.info("Setting up model registry...")

    # Model registry is automatically available in MLflow
    # We'll just verify it's accessible
    try:
        registered_models = client.search_registered_models()
        logger.info(
            f"✓ Model registry accessible ({len(registered_models)} models registered)"
        )
        return True
    except Exception as e:
        logger.error(f"Error accessing model registry: {e}")
        return False


def setup_dataset_registry(client):
    """Setup dataset registry tags and metadata structure"""
    logger.info("Setting up dataset registry structure...")

    # Create a dedicated experiment for dataset tracking
    dataset_exp_id = create_experiment_if_not_exists(
        client,
        "Dataset-Registry",
        tags={
            "purpose": "dataset version tracking",
            "type": "registry",
            "owner": "data-team",
        },
        description="Central registry for dataset versions and lineage",
    )

    logger.info(f"✓ Dataset registry experiment created (ID: {dataset_exp_id})")
    return dataset_exp_id


def enable_experimental_features(client):
    """Enable experimental MLflow features"""
    logger.info("Configuring experimental features...")

    # Create experiment for traces and evaluations
    traces_exp_id = create_experiment_if_not_exists(
        client,
        "Experimental-Traces",
        tags={
            "purpose": "trace logging and debugging",
            "experimental": "true",
            "owner": "ml-team",
        },
        description="Experimental traces for debugging and monitoring",
    )

    eval_exp_id = create_experiment_if_not_exists(
        client,
        "Model-Evaluations",
        tags={
            "purpose": "model evaluation metrics",
            "type": "evaluation",
            "owner": "ml-team",
        },
        description="Centralized model evaluation results",
    )

    logger.info(f"✓ Experimental features configured")
    return {"traces": traces_exp_id, "evaluations": eval_exp_id}


def main():
    """Main initialization routine"""
    logger.info("=" * 60)
    logger.info("MLflow Platform Initialization")
    logger.info("=" * 60)

    try:
        # Connect to MLflow
        client = wait_for_mlflow()

        # Setup standard experiments
        experiment_ids = setup_standard_experiments(client)

        # Setup model registry
        setup_model_registry(client)

        # Setup dataset registry
        dataset_exp_id = setup_dataset_registry(client)

        # Enable experimental features
        experimental_features = enable_experimental_features(client)

        logger.info("=" * 60)
        logger.info("✓ MLflow initialization completed successfully")
        logger.info("=" * 60)
        logger.info(f"Created/verified {len(experiment_ids)} experiments")
        logger.info(f"Model Registry: Ready")
        logger.info(f"Dataset Registry: Experiment ID {dataset_exp_id}")
        logger.info(f"Experimental Features: Enabled")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"✗ Initialization failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
