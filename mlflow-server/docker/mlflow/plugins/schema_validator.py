"""
MLflow Schema Validation Plugin
Enforces project schema for models, experiments, and artifacts.
Privacy-focused with support for reference paths.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from mlflow.tracking import MlflowClient
from mlflow.exceptions import MlflowException
from pydantic import BaseModel, Field, validator
import jsonschema

logger = logging.getLogger(__name__)


class RequiredMetadata(BaseModel):
    """Required metadata fields for all MLflow runs"""

    model_name: str = Field(
        ..., description="Model name in format: {project}_{architecture}_{purpose}"
    )
    model_version: str = Field(
        ..., pattern=r"^v\d+\.\d+\.\d+$", description="Semantic version (v1.0.0)"
    )
    author: str = Field(..., description="Model creator username")
    description: str = Field(
        ..., min_length=10, description="Model description (min 10 chars)"
    )
    training_date: str = Field(..., description="ISO8601 timestamp")

    # Framework info
    framework: str = Field(..., description="pytorch|tensorflow|sklearn|xgboost|other")
    model_type: str = Field(
        ..., description="detection|classification|regression|segmentation"
    )

    # Dataset info
    dataset_name: str = Field(..., description="Name of training dataset")
    dataset_version: str = Field(
        ..., description="Dataset version (v2024.11.21 or vX.Y.Z)"
    )
    dataset_path: Optional[str] = Field(
        None, description="Path to dataset (if using reference)"
    )
    dataset_size: int = Field(..., description="Number of training samples")

    # Model properties
    model_size_mb: float = Field(..., gt=0, description="Model file size in MB")
    input_shape: str = Field(
        ..., description="Expected input shape (e.g., '[3,224,224]')"
    )
    output_shape: str = Field(..., description="Output shape (e.g., '[1000]')")

    @validator("training_date")
    def validate_date(cls, v):
        try:
            datetime.fromisoformat(v)
            return v
        except ValueError:
            raise ValueError("training_date must be ISO8601 format")


class RequiredTags(BaseModel):
    """Mandatory tags for all runs"""

    environment: str = Field(..., pattern="^(production|staging|development)$")
    dataset_version: str = Field(..., description="Dataset version identifier")
    framework: str = Field(..., description="ML framework used")
    model_type: str = Field(..., description="Type of ML model")

    # Auto-generated (system will add if not present)
    created_timestamp: Optional[str] = None
    creator: Optional[str] = None
    git_commit: Optional[str] = None


class RequiredMetrics(BaseModel):
    """High-level metrics required for model comparison"""

    # Common to all models
    training_time_seconds: float = Field(..., gt=0)
    inference_time_ms: float = Field(..., gt=0)
    model_size_mb: float = Field(..., gt=0)

    # Task-specific metrics (at least one group required)
    # Classification/Detection
    accuracy: Optional[float] = Field(None, ge=0, le=1)
    precision: Optional[float] = Field(None, ge=0, le=1)
    recall: Optional[float] = Field(None, ge=0, le=1)
    f1_score: Optional[float] = Field(None, ge=0, le=1)

    # Object Detection specific
    mAP50: Optional[float] = Field(None, ge=0, le=1)
    mAP50_95: Optional[float] = Field(None, ge=0, le=1)

    # Regression specific
    rmse: Optional[float] = Field(None, ge=0)
    mae: Optional[float] = Field(None, ge=0)
    r2_score: Optional[float] = Field(None, ge=-1, le=1)

    def validate_task_metrics(self, model_type: str):
        """Ensure appropriate metrics exist for model type"""
        if model_type in ["classification", "detection"]:
            if not any([self.accuracy, self.precision, self.recall, self.f1_score]):
                raise ValueError(
                    f"{model_type} requires at least one of: accuracy, precision, recall, f1_score"
                )
            if model_type == "detection" and not self.mAP50:
                raise ValueError("Detection models require mAP50 metric")
        elif model_type == "regression":
            if not any([self.rmse, self.mae, self.r2_score]):
                raise ValueError(
                    "Regression models require at least one of: rmse, mae, r2_score"
                )


class RequiredArtifacts(BaseModel):
    """Required artifacts for complete model registration"""

    # Core model files
    model_file: str = Field(..., description="Model weights (.pt, .h5, .pkl, etc.)")
    config_file: str = Field(..., description="Model configuration (.yaml, .json)")
    requirements_file: str = Field(
        ..., description="Python dependencies (requirements.txt)"
    )

    # Documentation
    metrics_file: str = Field(..., description="Detailed metrics (.json, .yaml)")
    sample_input: str = Field(..., description="Example input data for testing")
    sample_output: str = Field(..., description="Example output data")

    # Optional but recommended
    preprocessing_script: Optional[str] = Field(
        None, description="Preprocessing code (.py)"
    )
    postprocessing_script: Optional[str] = Field(
        None, description="Postprocessing code (.py)"
    )
    training_script: Optional[str] = Field(None, description="Training code (.py)")

    # Privacy-aware: Allow reference paths
    use_reference_paths: bool = Field(
        False, description="If True, paths point to external storage"
    )


class SchemaValidator:
    """Validates MLflow runs against project schema"""

    def __init__(self, schema_dir: str = "/mlflow/schema"):
        self.schema_dir = Path(schema_dir)
        self.schema_dir.mkdir(parents=True, exist_ok=True)
        self.client = MlflowClient()

        # Initialize default schema
        self._initialize_schema()

    def _initialize_schema(self):
        """Create default schema files if not exists"""
        schema_file = self.schema_dir / "model_schema.json"
        if not schema_file.exists():
            default_schema = {
                "version": "1.0.0",
                "updated": datetime.utcnow().isoformat(),
                "required_metadata": RequiredMetadata.schema(),
                "required_tags": RequiredTags.schema(),
                "required_metrics": RequiredMetrics.schema(),
                "required_artifacts": RequiredArtifacts.schema(),
            }
            with open(schema_file, "w") as f:
                json.dump(default_schema, f, indent=2)
            logger.info(f"Created default schema at {schema_file}")

    def validate_run(self, run_id: str, allow_warnings: bool = True) -> Dict[str, Any]:
        """
        Validate a run against schema requirements

        Args:
            run_id: MLflow run ID
            allow_warnings: If True, warn on missing fields but don't fail

        Returns:
            Dict with validation results
        """
        run = self.client.get_run(run_id)
        results = {"valid": True, "errors": [], "warnings": [], "schema_changes": []}

        # Validate metadata (params)
        try:
            metadata = {k: v for k, v in run.data.params.items()}
            RequiredMetadata(**metadata)
        except Exception as e:
            if allow_warnings:
                results["warnings"].append(f"Metadata validation: {str(e)}")
            else:
                results["valid"] = False
                results["errors"].append(f"Metadata validation failed: {str(e)}")

        # Validate tags
        try:
            tags = {k: v for k, v in run.data.tags.items()}
            RequiredTags(**tags)
        except Exception as e:
            if allow_warnings:
                results["warnings"].append(f"Tags validation: {str(e)}")
            else:
                results["valid"] = False
                results["errors"].append(f"Tags validation failed: {str(e)}")

        # Validate metrics
        try:
            metrics = {k: v for k, v in run.data.metrics.items()}
            model_type = run.data.params.get("model_type", "unknown")
            metric_obj = RequiredMetrics(**metrics)
            metric_obj.validate_task_metrics(model_type)
        except Exception as e:
            if allow_warnings:
                results["warnings"].append(f"Metrics validation: {str(e)}")
            else:
                results["valid"] = False
                results["errors"].append(f"Metrics validation failed: {str(e)}")

        # Validate artifacts
        artifacts = self.client.list_artifacts(run_id)
        artifact_paths = [a.path for a in artifacts]

        required_artifacts = [
            "model",
            "config",
            "requirements.txt",
            "metrics.json",
            "sample_input",
            "sample_output",
        ]
        missing_artifacts = [
            a for a in required_artifacts if not any(a in p for p in artifact_paths)
        ]

        if missing_artifacts:
            msg = f"Missing required artifacts: {', '.join(missing_artifacts)}"
            if allow_warnings:
                results["warnings"].append(msg)
            else:
                results["valid"] = False
                results["errors"].append(msg)

        # Check for schema modifications
        schema_changes = self._detect_schema_changes(run)
        if schema_changes:
            results["schema_changes"] = schema_changes
            results["warnings"].append(
                f"⚠️  SCHEMA MODIFICATION DETECTED: {len(schema_changes)} new fields added. "
                "This will alter the project schema. Review changes before proceeding."
            )

        return results

    def _detect_schema_changes(self, run) -> List[str]:
        """Detect if run introduces new schema fields"""
        changes = []

        # Load current schema
        schema_file = self.schema_dir / "model_schema.json"
        with open(schema_file) as f:
            schema = json.load(f)

        # Check for new params
        known_params = set(schema["required_metadata"]["properties"].keys())
        run_params = set(run.data.params.keys())
        new_params = run_params - known_params
        if new_params:
            changes.extend([f"New param: {p}" for p in new_params])

        # Check for new tags
        known_tags = set(schema["required_tags"]["properties"].keys())
        run_tags = set(run.data.tags.keys())
        new_tags = run_tags - known_tags
        if new_tags:
            changes.extend([f"New tag: {t}" for t in new_tags])

        return changes

    def check_model_completeness(
        self, run_id: str, check_download: bool = True
    ) -> Dict[str, Any]:
        """
        Verify model has all components needed for download and inference

        Args:
            run_id: MLflow run ID
            check_download: If True, verify artifacts can be downloaded

        Returns:
            Dict with completeness check results
        """
        results = {
            "complete": True,
            "missing_components": [],
            "downloadable": True,
            "inference_ready": True,
        }

        run = self.client.get_run(run_id)
        artifacts = self.client.list_artifacts(run_id)
        artifact_paths = [a.path for a in artifacts]

        # Essential components for model loading
        essential = {
            "model_weights": ["model", ".pt", ".pth", ".h5", ".pkl", ".onnx"],
            "config": ["config", ".yaml", ".json"],
            "requirements": ["requirements.txt"],
            "architecture_def": ["model_def", "architecture", "config"],
        }

        for component, patterns in essential.items():
            if not any(
                any(p in artifact for artifact in artifact_paths) for p in patterns
            ):
                results["complete"] = False
                results["missing_components"].append(component)
                results["inference_ready"] = False

        # Check for sample I/O (needed for validation)
        if not any("sample_input" in a for a in artifact_paths):
            results["warnings"] = results.get("warnings", [])
            results["warnings"].append(
                "Missing sample_input - model validation will be difficult"
            )

        if not any("sample_output" in a for a in artifact_paths):
            results["warnings"] = results.get("warnings", [])
            results["warnings"].append(
                "Missing sample_output - cannot verify model output format"
            )

        # Check if using reference paths (privacy feature)
        if run.data.params.get("use_reference_paths") == "true":
            results["using_references"] = True
            results["reference_paths"] = {
                k: v
                for k, v in run.data.params.items()
                if k.endswith("_path") or k.endswith("_location")
            }
            results["downloadable"] = False
            results["note"] = "Model uses reference paths - artifacts stored externally"

        if not results["complete"]:
            results["error_message"] = (
                f"❌ Model incomplete. Missing: {', '.join(results['missing_components'])}. "
                "Model cannot be reliably downloaded and loaded without these components."
            )

        return results


# Global validator instance
validator = SchemaValidator()


def validate_before_log_model(run_id: str, model_path: str) -> None:
    """
    Hook called before logging model - validates completeness
    """
    logger.info(f"Validating model for run {run_id}")

    # Validate run schema
    validation = validator.validate_run(run_id, allow_warnings=True)

    if validation["warnings"]:
        logger.warning(f"Validation warnings for run {run_id}:")
        for warning in validation["warnings"]:
            logger.warning(f"  - {warning}")

    if validation["schema_changes"]:
        logger.warning(f"⚠️  SCHEMA CHANGES DETECTED for run {run_id}:")
        for change in validation["schema_changes"]:
            logger.warning(f"  - {change}")
        logger.warning("Review these changes before proceeding.")

    if not validation["valid"]:
        raise MlflowException(
            f"Model validation failed: {', '.join(validation['errors'])}"
        )


def validate_before_register_model(model_uri: str, name: str) -> None:
    """
    Hook called before registering model - ensures completeness
    """
    # Extract run_id from model URI
    if "runs:/" in model_uri:
        run_id = model_uri.split("runs:/")[1].split("/")[0]
    else:
        logger.warning("Could not extract run_id from model_uri, skipping validation")
        return

    logger.info(f"Checking model completeness for registration: {name}")

    completeness = validator.check_model_completeness(run_id)

    if not completeness["complete"]:
        raise MlflowException(
            f"Cannot register incomplete model: {completeness['error_message']}"
        )

    if completeness.get("warnings"):
        for warning in completeness["warnings"]:
            logger.warning(f"  - {warning}")

    if completeness.get("using_references"):
        logger.info(f"✓ Model uses reference paths: {completeness['reference_paths']}")
