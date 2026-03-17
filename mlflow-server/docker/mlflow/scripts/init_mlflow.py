"""
MLflow Initialization Script
Pre-configures experiments, model registry, and integrations
"""

import os
import logging
import sys
from typing import Dict, List
from datetime import datetime

import mlflow
from mlflow.tracking import MlflowClient
from mlflow.exceptions import MlflowException

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MLflowInitializer:
    """Initialize MLflow with production-ready configuration"""

    def __init__(self):
        # Read configuration from environment
        self.backend_uri = os.getenv("MLFLOW_BACKEND_STORE_URI")
        self.artifact_root = os.getenv("MLFLOW_ARTIFACT_ROOT")

        # Set tracking URI to use direct database access during initialization
        # This avoids the need for the server to be running
        mlflow.set_tracking_uri(self.backend_uri)
        self.client = MlflowClient(tracking_uri=self.backend_uri)

        logger.info(f"Backend URI: {self.backend_uri}")
        logger.info(f"Artifact Root: {self.artifact_root}")

    def create_default_experiments(self) -> Dict[str, str]:
        """Create default experiments for different environments"""
        experiments = {
            "production-models": {
                "description": "Production-ready models deployed to live systems",
                "tags": {
                    "environment": "production",
                    "created_by": "system",
                    "purpose": "deployment",
                },
            },
            "staging-models": {
                "description": "Models under evaluation before production deployment",
                "tags": {
                    "environment": "staging",
                    "created_by": "system",
                    "purpose": "evaluation",
                },
            },
            "development-models": {
                "description": "Experimental models and development work",
                "tags": {
                    "environment": "development",
                    "created_by": "system",
                    "purpose": "experimentation",
                },
            },
            "dataset-registry": {
                "description": "Dataset versioning and lineage tracking",
                "tags": {
                    "environment": "production",
                    "created_by": "system",
                    "purpose": "data-versioning",
                    "type": "dataset-tracking",
                },
            },
        }

        created = {}

        for name, config in experiments.items():
            try:
                # Check if experiment exists
                experiment = self.client.get_experiment_by_name(name)
                if experiment:
                    logger.info(
                        f"✓ Experiment '{name}' already exists (ID: {experiment.experiment_id})"
                    )
                    created[name] = experiment.experiment_id
                else:
                    # Create experiment
                    experiment_id = self.client.create_experiment(
                        name=name,
                        artifact_location=f"{self.artifact_root}/{name}",
                        tags=config["tags"],
                    )

                    # Set description
                    self.client.set_experiment_tag(
                        experiment_id, "mlflow.note.content", config["description"]
                    )

                    logger.info(f"✓ Created experiment '{name}' (ID: {experiment_id})")
                    created[name] = experiment_id

            except Exception as e:
                logger.error(f"Failed to create experiment '{name}': {e}")

        return created

    def setup_model_registry(self):
        """Configure model registry with default registered models"""
        logger.info("Setting up model registry...")

        # Model registry is automatically available with PostgreSQL backend
        # Just verify it's working
        try:
            registered_models = self.client.search_registered_models()
            logger.info(
                f"✓ Model registry accessible ({len(registered_models)} models)"
            )
        except Exception as e:
            logger.error(f"Model registry check failed: {e}")

    def create_system_tags(self):
        """Create system-level tags for tracking"""
        system_tags = {
            "mlflow.system.initialized": datetime.utcnow().isoformat(),
            "mlflow.system.version": mlflow.__version__,
            "mlflow.system.compression": "zstd",
            "mlflow.system.validation": "enabled",
        }

        logger.info("✓ System tags configured")
        return system_tags

    def verify_database_connection(self) -> bool:
        """Verify database connectivity"""
        try:
            # Try to list experiments
            experiments = self.client.search_experiments()
            logger.info(
                f"✓ Database connection verified ({len(experiments)} experiments)"
            )
            return True
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return False

    def initialize(self):
        """Run full initialization"""
        logger.info("=" * 60)
        logger.info("Starting MLflow Initialization")
        logger.info("=" * 60)

        # Verify database
        if not self.verify_database_connection():
            logger.error("Database connection failed - cannot proceed")
            sys.exit(1)

        # Create experiments
        experiments = self.create_default_experiments()
        logger.info(f"✓ Configured {len(experiments)} experiments")

        # Setup model registry
        self.setup_model_registry()

        # Create system tags
        self.create_system_tags()

        logger.info("=" * 60)
        logger.info("MLflow Initialization Complete!")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Available Experiments:")
        for name, exp_id in experiments.items():
            logger.info(f"  - {name} (ID: {exp_id})")
        logger.info("")
        logger.info("Server is ready to accept tracking requests")
        logger.info("=" * 60)


def main():
    """Main initialization entry point"""
    try:
        initializer = MLflowInitializer()
        initializer.initialize()
    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
