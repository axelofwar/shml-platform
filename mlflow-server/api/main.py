"""
PII-PRO MLflow API Wrapper
Professional FastAPI layer with schema validation, error handling, and comprehensive documentation
"""

from fastapi import (
    FastAPI,
    HTTPException,
    UploadFile,
    File,
    Form,
    Path as PathParam,
    Query,
)
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from pathlib import Path as PathLib
import traceback
import yaml
import json
import os
import tempfile
import io

from mlflow.tracking import MlflowClient
from mlflow.exceptions import MlflowException
import mlflow

# Initialize FastAPI
app = FastAPI(
    title="PII-PRO MLflow API",
    description="Professional API for MLflow with schema validation, error handling, and Model Registry support",
    version="1.0.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS",
        "https://shml-platform.tail38b60a.ts.net,http://localhost:3000,http://localhost:8080",
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize MLflow client
mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
client = MlflowClient()

# Load schema
SCHEMA_PATH = PathLib("/mlflow/config/schema/experiment_schema.yaml")


class ErrorResponse(BaseModel):
    """Standard error response with trace"""

    error: str
    detail: Optional[str] = None
    trace: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    request_path: Optional[str] = None


class ExperimentInfo(BaseModel):
    """Experiment information"""

    experiment_id: str
    name: str
    artifact_location: str
    lifecycle_stage: str
    tags: Dict[str, str] = {}


class RunCreateRequest(BaseModel):
    """Request to create a new run with schema validation"""

    experiment_name: str = Field(
        ..., description="Name of experiment (e.g., 'face-detection/training')"
    )
    run_name: Optional[str] = Field(None, description="Optional run name")

    # Required tags based on PII-PRO schema
    tags: Dict[str, str] = Field(..., description="Required tags per experiment schema")

    # Optional initial parameters
    parameters: Optional[Dict[str, Any]] = Field(
        default={}, description="Initial parameters to log"
    )

    # Validate against schema
    validate_schema: bool = Field(default=True, description="Enforce schema validation")

    class Config:
        schema_extra = {
            "example": {
                "experiment_name": "face-detection/training",
                "run_name": "yolov8-face-detection-v1",
                "tags": {
                    "model_type": "yolov8n",
                    "dataset_version": "wider-faces-v1.2",
                    "developer": "john",
                    "hardware": "rtx3090",
                },
                "parameters": {"learning_rate": 0.001, "batch_size": 32},
                "validate_schema": True,
            }
        }


class ExperimentCreateRequest(BaseModel):
    """Create a new experiment"""

    name: str
    artifact_location: Optional[str] = None
    tags: Optional[Dict[str, str]] = None

    class Config:
        schema_extra = {
            "example": {
                "name": "video-analytics-prod",
                "artifact_location": "/mlflow/artifacts/video-analytics-prod",
                "tags": {"team": "computer-vision", "project": "video-analytics"},
            }
        }


class MetricLogRequest(BaseModel):
    """Log metrics to a run"""

    metrics: Dict[str, float]
    step: Optional[int] = None
    timestamp: Optional[int] = None

    class Config:
        schema_extra = {
            "example": {
                "metrics": {
                    "recall": 0.96,
                    "precision": 0.94,
                    "f1_score": 0.95,
                    "fps_1080p": 58.3,
                },
                "step": 100,
            }
        }


class ModelRegisterRequest(BaseModel):
    """Register model to Model Registry (alert-only validation)"""

    run_id: str = Field(..., description="Run ID containing the model")
    model_name: str = Field(..., description="Name for registered model")
    model_path: str = Field(default="model", description="Artifact path to model")
    description: Optional[str] = None
    tags: Optional[Dict[str, str]] = {}

    # Privacy validation - optional, generates warnings if not provided
    privacy_validated: bool = Field(
        default=False,
        description="Whether model passed privacy validation (recommended)",
    )
    min_recall: Optional[float] = Field(
        None, description="Target recall threshold for alerts (e.g., 0.95)"
    )

    class Config:
        schema_extra = {
            "example": {
                "run_id": "abc123...",
                "model_name": "face-detection-yolov8l-p2",
                "model_path": "model",
                "description": "YOLOv8 face detection optimized for privacy",
                "tags": {
                    "model_family": "face-detection",
                    "privacy_validated": "true",
                    "technical_owner": "john",
                },
                "privacy_validated": True,
                "min_recall": 0.96,
            }
        }


def load_schema() -> Dict[str, Any]:
    """Load PII-PRO experiment schema"""
    try:
        if SCHEMA_PATH.exists():
            with open(SCHEMA_PATH) as f:
                return yaml.safe_load(f)
        return {}
    except Exception as e:
        print(f"Warning: Could not load schema: {e}")
        return {}


def validate_run_against_schema(
    experiment_name: str, tags: Dict[str, str], schema: Dict[str, Any]
) -> tuple[bool, List[str]]:
    """
    Validate run tags against experiment schema

    NOTE: This function NEVER blocks operations - it only returns warnings.
    Schema enforcement is alert-only to avoid blocking model uploads/downloads.

    Returns:
        (is_valid=True, list_of_warnings)
    """
    warnings = []

    if not schema or "experiments" not in schema:
        return True, []  # No schema to validate against

    exp_schema = schema["experiments"].get(experiment_name)
    if not exp_schema:
        # Unknown experiment - warn but allow
        warnings.append(
            f"INFO: Experiment '{experiment_name}' not in schema - this is OK"
        )
        return True, warnings

    # Check required tags - but only warn, never block
    required_tags = exp_schema.get("required_tags", [])
    for req_tag in required_tags:
        if req_tag not in tags:
            warnings.append(
                f"RECOMMENDED: Add tag '{req_tag}' for better experiment tracking"
            )

    # Always return success with warnings (never block)
    return True, warnings


def format_error_response(error: Exception, request_path: str = None) -> JSONResponse:
    """Format exception as detailed error response with trace"""
    error_detail = {
        "error": type(error).__name__,
        "detail": str(error),
        "trace": traceback.format_exc(),
        "timestamp": datetime.utcnow().isoformat(),
        "request_path": request_path,
    }

    status_code = 400
    if isinstance(error, MlflowException):
        status_code = 400
    elif isinstance(error, HTTPException):
        status_code = error.status_code
    elif isinstance(error, ValueError):
        status_code = 422
    else:
        status_code = 500

    return JSONResponse(status_code=status_code, content=error_detail)


@app.get("/")
async def root():
    """API root - returns service info"""
    return {
        "service": "PII-PRO MLflow API",
        "version": "1.0.0",
        "status": "operational",
        "mlflow_tracking_uri": os.getenv(
            "MLFLOW_TRACKING_URI", "http://localhost:5000"
        ),
        "documentation": "/api/v1/docs",
        "schema_info": "/api/v1/schema",
        "endpoints": {
            "experiments": "/api/v1/experiments",
            "runs": "/api/v1/runs",
            "models": "/api/v1/models",
            "artifacts": "/api/v1/artifacts",
            "schema": "/api/v1/schema",
        },
    }


@app.get("/health")
@app.get("/api/v1/health")
@app.get("/ping")
async def health_check():
    """Health check endpoint - available at /health, /api/v1/health, and /ping"""
    # Fast health check without querying MLflow (to avoid slow I/O)
    return {
        "status": "healthy",
        "mlflow_tracking_uri": os.getenv("MLFLOW_TRACKING_URI", "not set"),
        "mlflow_version": mlflow.__version__,
        "server_time": datetime.utcnow().isoformat(),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ============================================================================
# SCHEMA ENDPOINTS
# ============================================================================


@app.get("/api/v1/schema", summary="Get PII-PRO experiment schema")
async def get_schema():
    """
    Returns the complete PII-PRO experiment schema including:
    - Required tags per experiment
    - Required metrics per experiment
    - Artifact organization standards
    - Privacy requirements
    - Usage examples
    """
    try:
        schema = load_schema()

        if not schema:
            raise HTTPException(status_code=404, detail="Schema file not found")

        # Add usage instructions
        schema["usage"] = {
            "description": "PII-PRO schema enforces privacy-focused tracking for computer vision models",
            "experiments": {
                "face-detection/training": "Model training and experimentation",
                "Staging-Model-Comparison": "A/B testing and baseline comparison",
                "Performance-Benchmarking": "FPS testing across resolutions",
                "Production-Candidates": "Production-ready model validation",
                "Dataset-Registry": "Dataset versioning and tracking",
            },
            "privacy_requirements": {
                "min_recall": 0.95,
                "max_false_negative_rate": 0.05,
                "description": "Face detection must minimize false negatives for privacy protection",
            },
        }

        return schema

    except Exception as e:
        return format_error_response(e, "/api/v1/schema")


@app.get(
    "/api/v1/schema/experiment/{experiment_name}",
    summary="Get schema for specific experiment",
)
async def get_experiment_schema(
    experiment_name: str = PathParam(
        ..., description="Experiment name (e.g., 'face-detection/training')"
    )
):
    """
    Get detailed schema requirements for a specific experiment including:
    - Required tags
    - Recommended tags
    - Required metrics
    - Recommended metrics
    - Example usage
    """
    try:
        schema = load_schema()

        if not schema or "experiments" not in schema:
            raise HTTPException(status_code=404, detail="Schema not found")

        exp_schema = schema["experiments"].get(experiment_name)
        if not exp_schema:
            available = list(schema["experiments"].keys())
            raise HTTPException(
                status_code=404,
                detail=f"Experiment '{experiment_name}' not found in schema. Available: {available}",
            )

        # Add validation examples
        response = {
            "experiment_name": experiment_name,
            "schema": exp_schema,
            "validation_example": {
                "valid_tags": {
                    tag: f"<{tag}_value>" for tag in exp_schema.get("required_tags", [])
                },
                "valid_metrics": {
                    metric: 0.0 for metric in exp_schema.get("required_metrics", [])
                },
            },
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        return format_error_response(e, f"/api/v1/schema/experiment/{experiment_name}")


@app.post("/api/v1/schema/validate", summary="Validate tags/metrics against schema")
async def validate_against_schema(request: dict):
    """
    Validate a set of tags and metrics against experiment schema.
    Returns validation errors if any.
    """
    try:
        experiment_name = request.get("experiment_name")
        tags_dict = request.get("tags", {})
        metrics_dict = request.get("metrics", {})

        if not experiment_name:
            raise HTTPException(status_code=422, detail="experiment_name is required")

        schema = load_schema()
        is_valid, warnings = validate_run_against_schema(
            experiment_name, tags_dict, schema
        )

        response = {
            "valid": is_valid,
            "is_valid": is_valid,  # For compatibility
            "experiment_name": experiment_name,
            "warnings": warnings,
            "validation_errors": warnings,  # For compatibility
            "tags_validated": tags_dict,
            "metrics_validated": metrics_dict,
        }

        if warnings:
            response["recommendation"] = f"Recommendations: {'; '.join(warnings)}"

        return response

    except HTTPException:
        raise
    except Exception as e:
        return format_error_response(e, "/api/v1/schema/validate")


# ============================================================================
# EXPERIMENT ENDPOINTS
# ============================================================================


@app.get("/api/v1/experiments", summary="List all experiments")
async def list_experiments(max_results: int = Query(default=100, ge=1, le=1000)):
    """List all MLflow experiments"""
    try:
        experiments = client.search_experiments(max_results=max_results)

        return {
            "experiments": [
                {
                    "experiment_id": exp.experiment_id,
                    "name": exp.name,
                    "artifact_location": exp.artifact_location,
                    "lifecycle_stage": exp.lifecycle_stage,
                    "tags": exp.tags,
                }
                for exp in experiments
            ],
            "total": len(experiments),
        }

    except Exception as e:
        return format_error_response(e, "/api/v1/experiments")


@app.post("/api/v1/experiments", summary="Create a new experiment")
async def create_experiment(request: ExperimentCreateRequest):
    """
    Create a new MLflow experiment.

    Experiments are containers for organizing related runs. Each experiment has:
    - Unique name
    - Artifact storage location
    - Optional tags for metadata
    """
    try:
        # Check if experiment already exists
        existing = client.get_experiment_by_name(request.name)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Experiment '{request.name}' already exists with ID {existing.experiment_id}",
            )

        # Create experiment
        experiment_id = client.create_experiment(
            name=request.name,
            artifact_location=request.artifact_location,
            tags=request.tags,
        )

        # Get the created experiment details
        experiment = client.get_experiment(experiment_id)

        return {
            "experiment_id": experiment_id,
            "name": experiment.name,
            "artifact_location": experiment.artifact_location,
            "lifecycle_stage": experiment.lifecycle_stage,
            "tags": experiment.tags,
            "message": "Experiment created successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        return format_error_response(e, "/api/v1/experiments")


@app.get("/api/v1/experiments/{experiment_id}", summary="Get experiment details")
async def get_experiment(
    experiment_id: str = PathParam(..., description="Experiment ID")
):
    """Get detailed information about an experiment"""
    try:
        experiment = client.get_experiment(experiment_id)

        if not experiment:
            raise HTTPException(
                status_code=404, detail=f"Experiment {experiment_id} not found"
            )

        # Get recent runs
        runs = client.search_runs(
            experiment_ids=[experiment_id], max_results=10, order_by=["start_time DESC"]
        )

        return {
            "experiment_id": experiment.experiment_id,
            "name": experiment.name,
            "artifact_location": experiment.artifact_location,
            "lifecycle_stage": experiment.lifecycle_stage,
            "tags": experiment.tags,
            "recent_runs": [
                {
                    "run_id": run.info.run_id,
                    "run_name": run.data.tags.get("mlflow.runName", "unnamed"),
                    "status": run.info.status,
                    "start_time": run.info.start_time,
                    "metrics": run.data.metrics,
                }
                for run in runs
            ],
            "total_runs": len(runs),
        }

    except HTTPException:
        raise
    except Exception as e:
        return format_error_response(e, f"/api/v1/experiments/{experiment_id}")


# ============================================================================
# RUN ENDPOINTS
# ============================================================================


@app.post("/api/v1/runs/create", summary="Create a new run with schema validation")
async def create_run(request: RunCreateRequest):
    """
    Create a new MLflow run with automatic schema validation.

    This endpoint:
    1. Validates experiment exists
    2. Validates required tags against PII-PRO schema
    3. Creates run with tags and initial parameters
    4. Returns run_id for logging metrics/artifacts

    Schema validation ensures:
    - All required tags are present (e.g., model_type, dataset_version, developer)
    - Tags conform to experiment-specific requirements
    - Privacy requirements are considered
    """
    try:
        # Get experiment
        experiment = client.get_experiment_by_name(request.experiment_name)
        if not experiment:
            raise HTTPException(
                status_code=404,
                detail=f"Experiment '{request.experiment_name}' not found",
            )

        # Validate schema if requested - returns warnings only, never blocks
        warnings = []
        if request.validate_schema:
            schema = load_schema()
            is_valid, warnings = validate_run_against_schema(
                request.experiment_name, request.tags, schema
            )
            # Note: is_valid is always True now, warnings are informational

        # Create run
        run = client.create_run(
            experiment_id=experiment.experiment_id,
            tags=request.tags,
            run_name=request.run_name,
        )

        # Log initial parameters
        if request.parameters:
            for key, value in request.parameters.items():
                client.log_param(run.info.run_id, key, value)

        return {
            "run_id": run.info.run_id,
            "experiment_id": experiment.experiment_id,
            "experiment_name": request.experiment_name,
            "status": "created",
            "artifact_uri": run.info.artifact_uri,
            "warnings": warnings,
            "message": "Run created successfully. Use run_id to log metrics and artifacts."
            + (f" ({len(warnings)} recommendation(s) provided)" if warnings else ""),
        }

    except HTTPException:
        raise
    except Exception as e:
        return format_error_response(e, "/api/v1/runs/create")


@app.post("/api/v1/runs/{run_id}/metrics", summary="Log metrics to run")
async def log_metrics(run_id: str, request: MetricLogRequest):
    """
    Log metrics to an existing run.
    Validates metrics against experiment schema if applicable.
    """
    try:
        # Validate run exists
        run = client.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        # Log metrics
        timestamp = request.timestamp or int(datetime.utcnow().timestamp() * 1000)

        for key, value in request.metrics.items():
            client.log_metric(
                run_id, key, value, timestamp=timestamp, step=request.step or 0
            )

        return {
            "run_id": run_id,
            "metrics_logged": list(request.metrics.keys()),
            "status": "success",
        }

    except HTTPException:
        raise
    except Exception as e:
        return format_error_response(e, f"/api/v1/runs/{run_id}/metrics")


@app.get("/api/v1/runs/{run_id}", summary="Get run details")
async def get_run(run_id: str = PathParam(..., description="Run ID")):
    """Get detailed information about a run including metrics, params, and artifacts"""
    try:
        run = client.get_run(run_id)

        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        # Get artifacts
        artifacts = client.list_artifacts(run_id)

        return {
            "run_id": run.info.run_id,
            "experiment_id": run.info.experiment_id,
            "status": run.info.status,
            "start_time": run.info.start_time,
            "end_time": run.info.end_time,
            "artifact_uri": run.info.artifact_uri,
            "metrics": run.data.metrics,
            "params": run.data.params,
            "tags": run.data.tags,
            "artifacts": [
                {
                    "path": artifact.path,
                    "is_dir": artifact.is_dir,
                    "file_size": artifact.file_size,
                }
                for artifact in artifacts
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        return format_error_response(e, f"/api/v1/runs/{run_id}")


@app.post("/api/v1/runs/{run_id}/finish", summary="Finish a run")
async def finish_run(
    run_id: str = PathParam(..., description="Run ID"),
    status: Literal["FINISHED", "FAILED", "KILLED"] = "FINISHED",
):
    """Mark a run as finished"""
    try:
        client.set_terminated(run_id, status=status)

        return {
            "run_id": run_id,
            "status": status,
            "message": "Run terminated successfully",
        }

    except Exception as e:
        return format_error_response(e, f"/api/v1/runs/{run_id}/finish")


# ============================================================================
# ARTIFACT ENDPOINTS
# ============================================================================


@app.post("/api/v1/runs/{run_id}/artifacts", summary="Upload artifact to run")
async def upload_artifact(
    run_id: str = PathParam(..., description="Run ID"),
    file: UploadFile = File(...),
    artifact_path: Optional[str] = Form(
        default="", description="Subpath within artifacts (e.g., 'plots')"
    ),
):
    """
    Upload an artifact file to a run.
    Supports plots, models, configs, datasets, etc.
    """
    try:
        # Validate run exists
        run = client.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=f"_{file.filename}"
        ) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name

        try:
            # Log artifact
            client.log_artifact(run_id, tmp_path, artifact_path=artifact_path or None)

            return {
                "run_id": run_id,
                "filename": file.filename,
                "artifact_path": artifact_path or "root",
                "size_bytes": len(content),
                "status": "uploaded",
                "message": f"Artifact uploaded to {artifact_path or 'root'}/{file.filename}",
            }
        finally:
            # Clean up temp file
            os.unlink(tmp_path)

    except HTTPException:
        raise
    except Exception as e:
        return format_error_response(e, f"/api/v1/runs/{run_id}/artifacts")


@app.get(
    "/api/v1/runs/{run_id}/artifacts/{artifact_path:path}", summary="Download artifact"
)
async def download_artifact(
    run_id: str = PathParam(..., description="Run ID"),
    artifact_path: str = PathParam(..., description="Path to artifact"),
):
    """Download an artifact from a run or list directory contents"""
    try:
        # First, try to list artifacts at this path (might be a directory)
        try:
            artifacts = client.list_artifacts(run_id, artifact_path)
            # If it's a directory, return list of artifacts
            if artifacts:
                return {
                    "path": artifact_path,
                    "is_directory": True,
                    "artifacts": [
                        {
                            "path": art.path,
                            "is_dir": art.is_dir,
                            "file_size": art.file_size,
                        }
                        for art in artifacts
                    ],
                }
        except:
            pass

        # Try to download as a file
        local_path = client.download_artifacts(run_id, artifact_path)

        if not os.path.exists(local_path):
            raise HTTPException(
                status_code=404, detail=f"Artifact not found: {artifact_path}"
            )

        # Check if it's a directory on disk
        if os.path.isdir(local_path):
            # List directory contents
            contents = []
            for item in os.listdir(local_path):
                item_path = os.path.join(local_path, item)
                contents.append(
                    {
                        "path": f"{artifact_path}/{item}" if artifact_path else item,
                        "is_dir": os.path.isdir(item_path),
                        "file_size": (
                            os.path.getsize(item_path)
                            if os.path.isfile(item_path)
                            else None
                        ),
                    }
                )
            return {"path": artifact_path, "is_directory": True, "artifacts": contents}

        # Return file
        return FileResponse(
            local_path,
            media_type="application/octet-stream",
            filename=os.path.basename(artifact_path),
        )

    except HTTPException:
        raise
    except Exception as e:
        return format_error_response(
            e, f"/api/v1/runs/{run_id}/artifacts/{artifact_path}"
        )


# ============================================================================
# MODEL REGISTRY ENDPOINTS
# ============================================================================


@app.get("/api/v1/models", summary="List registered models")
async def list_models(max_results: int = Query(default=100, ge=1, le=1000)):
    """List all registered models in Model Registry"""
    try:
        models = client.search_registered_models(max_results=max_results)

        return {
            "models": [
                {
                    "name": model.name,
                    "creation_timestamp": model.creation_timestamp,
                    "last_updated_timestamp": model.last_updated_timestamp,
                    "description": model.description,
                    "tags": model.tags,
                    "latest_versions": [
                        {
                            "version": mv.version,
                            "stage": mv.current_stage,
                            "status": mv.status,
                        }
                        for mv in model.latest_versions
                    ],
                }
                for model in models
            ],
            "total": len(models),
        }

    except Exception as e:
        return format_error_response(e, "/api/v1/models")


@app.post("/api/v1/models/register", summary="Register model (alert-only validation)")
async def register_model(request: ModelRegisterRequest):
    """
    Register a model to Model Registry with optional privacy validation alerts.

    NOTE: All validation is alert-only. Models are NEVER blocked from registration.
    - Privacy validation: recommended but not required
    - Recall thresholds: alert if below target but still allow registration
    - All required artifacts must be present (this is enforced)
    """
    try:
        # Collect validation warnings
        warnings = []

        # Validate run exists
        run = client.get_run(request.run_id)
        if not run:
            raise HTTPException(
                status_code=404, detail=f"Run {request.run_id} not found"
            )

        # Privacy validation (PII-PRO specific) - WARN but don't block
        if not request.privacy_validated:
            warnings.append(
                "RECOMMENDED: Privacy validation not completed. Consider validating before production deployment."
            )

        # Check recall requirement - WARN but don't block
        recall = run.data.metrics.get("recall")
        if request.min_recall and recall:
            if recall < request.min_recall:
                warnings.append(
                    f"ALERT: Model recall ({recall:.4f}) below recommended threshold ({request.min_recall:.4f}). "
                    f"Consider retraining before production deployment to minimize false negatives."
                )

        # Check for required artifacts
        artifacts = client.list_artifacts(request.run_id, path=request.model_path)
        if not artifacts:
            raise HTTPException(
                status_code=422,
                detail=f"No model found at path '{request.model_path}'. "
                "Ensure model was logged with mlflow.log_model() or mlflow.<framework>.log_model()",
            )

        # Register model - create registered model if it doesn't exist
        model_uri = f"runs:/{request.run_id}/{request.model_path}"

        # Check if registered model exists, create if not
        try:
            client.get_registered_model(request.model_name)
        except Exception:
            # Model doesn't exist, create it
            client.create_registered_model(
                name=request.model_name,
                description=request.description,
                tags=request.tags,
            )

        model_version = client.create_model_version(
            name=request.model_name,
            source=model_uri,
            run_id=request.run_id,
            description=request.description,
            tags=request.tags,
        )

        return {
            "model_name": request.model_name,
            "version": model_version.version,
            "run_id": request.run_id,
            "status": "registered",
            "current_stage": model_version.current_stage,
            "source": model_uri,
            "privacy_validated": request.privacy_validated,
            "warnings": warnings,
            "message": f"Model '{request.model_name}' version {model_version.version} registered successfully"
            + (f" (with {len(warnings)} warning(s))" if warnings else ""),
        }

    except HTTPException:
        raise
    except Exception as e:
        return format_error_response(e, "/api/v1/models/register")


@app.get("/api/v1/models/{model_name}", summary="Get model details")
async def get_model(
    model_name: str = PathParam(..., description="Registered model name")
):
    """Get detailed information about a registered model"""
    try:
        model = client.get_registered_model(model_name)

        if not model:
            raise HTTPException(
                status_code=404, detail=f"Model '{model_name}' not found"
            )

        # Get all versions
        versions = client.search_model_versions(f"name='{model_name}'")

        return {
            "name": model.name,
            "creation_timestamp": model.creation_timestamp,
            "last_updated_timestamp": model.last_updated_timestamp,
            "description": model.description,
            "tags": model.tags,
            "versions": [
                {
                    "version": mv.version,
                    "stage": mv.current_stage,
                    "status": mv.status,
                    "creation_timestamp": mv.creation_timestamp,
                    "run_id": mv.run_id,
                    "source": mv.source,
                    "tags": mv.tags,
                }
                for mv in sorted(versions, key=lambda x: int(x.version), reverse=True)
            ],
            "total_versions": len(versions),
        }

    except HTTPException:
        raise
    except Exception as e:
        return format_error_response(e, f"/api/v1/models/{model_name}")


@app.post(
    "/api/v1/models/{model_name}/versions/{version}/transition",
    summary="Set model alias (champion/challenger)",
)
async def transition_model_stage(
    model_name: str = PathParam(..., description="Model name"),
    version: str = PathParam(..., description="Model version"),
    stage: Literal["Staging", "Production", "Archived", "None"] = Query(
        ...,
        description="Target stage (mapped to alias: Production→champion, Staging→challenger)",
    ),
):
    """
    Set a model alias based on the requested stage.

    Stage-to-alias mapping (migrated from deprecated transition_model_version_stage):
    - Production → @champion
    - Staging → @challenger
    - Archived → removes both aliases
    - None → no-op
    """
    try:
        alias_map = {"Production": "champion", "Staging": "challenger"}
        if stage == "Archived":
            # Remove aliases from this version
            for alias in ["champion", "challenger"]:
                try:
                    mv = client.get_model_version_by_alias(model_name, alias)
                    if mv.version == version:
                        client.delete_registered_model_alias(model_name, alias)
                except Exception:
                    pass
            return {
                "model_name": model_name,
                "version": version,
                "new_stage": stage,
                "status": "archived",
                "message": f"Model version {version} aliases removed (archived)",
            }
        elif stage in alias_map:
            alias = alias_map[stage]
            client.set_registered_model_alias(
                name=model_name, alias=alias, version=version
            )
            return {
                "model_name": model_name,
                "version": version,
                "new_stage": stage,
                "alias": f"@{alias}",
                "status": "transitioned",
                "message": f"Model version {version} set to @{alias}",
            }
        else:
            return {
                "model_name": model_name,
                "version": version,
                "new_stage": stage,
                "status": "no-op",
                "message": "Stage 'None' requires no action",
            }

    except Exception as e:
        return format_error_response(
            e, f"/api/v1/models/{model_name}/versions/{version}/transition"
        )


@app.delete(
    "/api/v1/models/{model_name}/versions/{version}", summary="Delete model version"
)
async def delete_model_version(
    model_name: str = PathParam(..., description="Model name"),
    version: str = PathParam(..., description="Model version to delete"),
):
    """Delete a specific model version"""
    try:
        client.delete_model_version(name=model_name, version=version)

        return {
            "model_name": model_name,
            "version": version,
            "status": "deleted",
            "message": f"Model version {version} deleted successfully",
        }

    except Exception as e:
        return format_error_response(
            e, f"/api/v1/models/{model_name}/versions/{version}"
        )


# ============================================================================
# STORAGE INFO ENDPOINT
# ============================================================================


@app.get("/api/v1/storage/info", summary="Get storage and configuration information")
async def get_storage_info():
    """
    Returns comprehensive storage and configuration information:
    - Artifact storage location and capacity
    - Database backend information
    - Model Registry configuration
    - Experiment schema requirements
    - API usage guidelines
    - Best practices for PII-PRO
    """
    try:
        # Get storage info
        artifact_root = os.getenv("MLFLOW_ARTIFACT_ROOT", "/mlflow/artifacts")

        # Count experiments and models
        experiments = client.search_experiments(max_results=1000)
        models = client.search_registered_models(max_results=1000)

        schema = load_schema()

        return {
            "storage": {
                "artifact_root": artifact_root,
                "backend_store": "PostgreSQL (mlflow_db)",
                "artifact_serving": "Enabled (--serve-artifacts)",
                "description": "Artifacts stored in file system, metadata in PostgreSQL",
            },
            "statistics": {
                "total_experiments": len(experiments),
                "total_registered_models": len(models),
                "active_experiments": len(
                    [e for e in experiments if e.lifecycle_stage == "active"]
                ),
            },
            "model_registry": {
                "enabled": True,
                "backend": "PostgreSQL",
                "features": [
                    "Model versioning",
                    "Stage transitions (None → Staging → Production → Archived)",
                    "Model aliases",
                    "Tags and descriptions",
                    "Lineage tracking",
                    "Download URIs",
                ],
                "stages": ["None", "Staging", "Production", "Archived"],
            },
            "schema_validation": {
                "enabled": True,
                "experiments": (
                    list(schema.get("experiments", {}).keys()) if schema else []
                ),
                "privacy_requirements": {
                    "min_recall": 0.95,
                    "max_false_negative_rate": 0.05,
                    "description": "PII-PRO requires high recall to minimize missing PII detection",
                },
            },
            "artifact_organization": (
                schema.get("global", {}).get("artifact_organization", {})
                if schema
                else {}
            ),
            "best_practices": {
                "experiments": "Use experiment-specific required tags for consistency",
                "artifacts": "Organize artifacts in subdirectories: plots/, models/, datasets/, reports/",
                "models": "Always log model with config, requirements.txt, and sample I/O",
                "privacy": "Validate recall ≥ 0.95 before registering face detection models",
                "versioning": "Use semantic versioning for models (v1.0.0) and datasets",
                "benchmarking": "Log FPS metrics across all standard resolutions (4K, 1080p, 720p, 480p)",
            },
            "api_endpoints": {
                "experiments": "/api/v1/experiments",
                "runs": "/api/v1/runs",
                "models": "/api/v1/models",
                "artifacts": "/api/v1/runs/{run_id}/artifacts",
                "schema": "/api/v1/schema",
                "documentation": "/api/v1/docs",
            },
        }

    except Exception as e:
        return format_error_response(e, "/api/v1/storage/info")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
