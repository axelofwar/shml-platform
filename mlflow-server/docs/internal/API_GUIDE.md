# PII-PRO MLflow API Documentation

Professional API wrapper for MLflow with schema validation, error handling, and comprehensive Model Registry support.

## 🚀 Quick Start

### Base URL
```
http://localhost/api/v1          # LAN access
http://${TAILSCALE_IP}/api/v1       # Tailscale VPN
```

### Interactive Documentation
- **Swagger UI**: http://localhost/api/v1/docs
- **ReDoc**: http://localhost/api/v1/redoc
- **OpenAPI Spec**: http://localhost/api/v1/openapi.json

---

## 📋 Table of Contents

1. [Schema Endpoints](#schema-endpoints) - Get experiment schemas and validation rules
2. [Experiment Endpoints](#experiment-endpoints) - Manage experiments
3. [Run Endpoints](#run-endpoints) - Create runs, log metrics
4. [Artifact Endpoints](#artifact-endpoints) - Upload/download artifacts
5. [Model Registry Endpoints](#model-registry-endpoints) - Register and manage models
6. [Storage Info](#storage-info) - Configuration and best practices
7. [Error Handling](#error-handling) - Understanding error responses

---

## 🔑 Key Features

✅ **Schema Validation** - Enforces PII-PRO experiment requirements  
✅ **Error Traces** - Detailed error messages with full stack traces  
✅ **Privacy Validation** - Minimum recall enforcement for face detection models  
✅ **Artifact Management** - Easy upload/download with validation  
✅ **Model Registry** - Complete model lifecycle management  
✅ **Storage Info** - Comprehensive configuration and best practices

---

## Schema Endpoints

### Get Complete Schema

```bash
curl http://localhost/api/v1/schema
```

**Response:**
```json
{
  "experiments": {
    "Development-Training": {
      "required_tags": ["model_type", "dataset_version", "developer"],
      "required_metrics": ["recall", "accuracy", "precision", "f1_score"]
    }
  },
  "privacy_requirements": {
    "min_recall": 0.95,
    "max_false_negative_rate": 0.05
  },
  "usage": { ... }
}
```

### Get Experiment-Specific Schema

```bash
curl http://localhost/api/v1/schema/experiment/Development-Training
```

**Response:**
```json
{
  "experiment_name": "Development-Training",
  "schema": {
    "required_tags": ["model_type", "dataset_version", "developer"],
    "recommended_tags": ["hardware", "input_resolution"],
    "required_metrics": ["recall", "accuracy", "precision", "f1_score"]
  },
  "validation_example": {
    "valid_tags": {
      "model_type": "<model_type_value>",
      "dataset_version": "<dataset_version_value>",
      "developer": "<developer_value>"
    }
  }
}
```

### Validate Tags Against Schema

```bash
curl -X POST http://localhost/api/v1/schema/validate \
  -F "experiment_name=Development-Training" \
  -F 'tags={"model_type":"yolov8n","dataset_version":"wider-faces-v1.2","developer":"john"}' \
  -F 'metrics={"recall":0.96,"accuracy":0.94}'
```

**Response (Valid):**
```json
{
  "valid": true,
  "experiment_name": "Development-Training",
  "validation_errors": [],
  "tags_validated": {
    "model_type": "yolov8n",
    "dataset_version": "wider-faces-v1.2",
    "developer": "john"
  }
}
```

**Response (Invalid):**
```json
{
  "valid": false,
  "experiment_name": "Development-Training",
  "validation_errors": [
    "Missing required tag: 'developer'"
  ],
  "recommendation": "Add missing required tags: ['Missing required tag: \\'developer\\'']"
}
```

---

## Experiment Endpoints

### List All Experiments

```bash
curl http://localhost/api/v1/experiments?max_results=100
```

**Response:**
```json
{
  "experiments": [
    {
      "experiment_id": "1",
      "name": "Development-Training",
      "artifact_location": "/mlflow/artifacts/1",
      "lifecycle_stage": "active",
      "tags": {"environment": "development"}
    }
  ],
  "total": 5
}
```

### Get Experiment Details

```bash
curl http://localhost/api/v1/experiments/1
```

**Response:**
```json
{
  "experiment_id": "1",
  "name": "Development-Training",
  "artifact_location": "/mlflow/artifacts/1",
  "lifecycle_stage": "active",
  "tags": {},
  "recent_runs": [
    {
      "run_id": "abc123...",
      "run_name": "yolov8-face-v1",
      "status": "FINISHED",
      "start_time": 1700000000000,
      "metrics": {"recall": 0.96}
    }
  ],
  "total_runs": 10
}
```

---

## Run Endpoints

### Create New Run (with Schema Validation)

```bash
curl -X POST http://localhost/api/v1/runs/create \
  -H "Content-Type: application/json" \
  -d '{
    "experiment_name": "Development-Training",
    "run_name": "yolov8-face-detection-v1",
    "tags": {
      "model_type": "yolov8n",
      "dataset_version": "wider-faces-v1.2",
      "developer": "john",
      "hardware": "rtx3090"
    },
    "parameters": {
      "learning_rate": 0.001,
      "batch_size": 32
    },
    "validate_schema": true
  }'
```

**Success Response:**
```json
{
  "run_id": "a1b2c3d4...",
  "experiment_id": "1",
  "experiment_name": "Development-Training",
  "status": "created",
  "artifact_uri": "mlflow-artifacts:/1/a1b2c3d4.../artifacts",
  "message": "Run created successfully. Use run_id to log metrics and artifacts."
}
```

**Error Response (Missing Required Tags):**
```json
{
  "error": "HTTPException",
  "detail": {
    "error": "Schema validation failed",
    "validation_errors": [
      "Missing required tag: 'developer'"
    ],
    "experiment_name": "Development-Training",
    "provided_tags": {"model_type": "yolov8n", "dataset_version": "wider-faces-v1.2"},
    "hint": "Check /api/v1/schema/experiment/Development-Training for requirements"
  },
  "trace": "Traceback (most recent call last): ...",
  "timestamp": "2025-11-22T22:30:00.000000"
}
```

### Log Metrics to Run

```bash
curl -X POST http://localhost/api/v1/runs/a1b2c3d4.../metrics \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "a1b2c3d4...",
    "metrics": {
      "recall": 0.96,
      "precision": 0.94,
      "f1_score": 0.95,
      "fps_1080p": 58.3,
      "false_negative_rate": 0.04
    },
    "step": 100
  }'
```

**Response:**
```json
{
  "run_id": "a1b2c3d4...",
  "metrics_logged": ["recall", "precision", "f1_score", "fps_1080p", "false_negative_rate"],
  "status": "success"
}
```

### Get Run Details

```bash
curl http://localhost/api/v1/runs/a1b2c3d4...
```

**Response:**
```json
{
  "run_id": "a1b2c3d4...",
  "experiment_id": "1",
  "status": "RUNNING",
  "start_time": 1700000000000,
  "end_time": null,
  "artifact_uri": "mlflow-artifacts:/1/a1b2c3d4.../artifacts",
  "metrics": {
    "recall": 0.96,
    "precision": 0.94,
    "fps_1080p": 58.3
  },
  "params": {
    "learning_rate": "0.001",
    "batch_size": "32"
  },
  "tags": {
    "model_type": "yolov8n",
    "developer": "john"
  },
  "artifacts": [
    {
      "path": "model",
      "is_dir": true,
      "file_size": null
    },
    {
      "path": "plots/confusion_matrix.png",
      "is_dir": false,
      "file_size": 152340
    }
  ]
}
```

### Finish Run

```bash
curl -X POST http://localhost/api/v1/runs/a1b2c3d4.../finish \
  -H "Content-Type: application/json" \
  -d '{"status": "FINISHED"}'
```

**Response:**
```json
{
  "run_id": "a1b2c3d4...",
  "status": "FINISHED",
  "message": "Run terminated successfully"
}
```

---

## Artifact Endpoints

### Upload Artifact

```bash
# Upload a plot
curl -X POST http://localhost/api/v1/runs/a1b2c3d4.../artifacts \
  -F "file=@confusion_matrix.png" \
  -F "artifact_path=plots"

# Upload model config
curl -X POST http://localhost/api/v1/runs/a1b2c3d4.../artifacts \
  -F "file=@model_config.yaml" \
  -F "artifact_path=models"
```

**Response:**
```json
{
  "run_id": "a1b2c3d4...",
  "filename": "confusion_matrix.png",
  "artifact_path": "plots",
  "size_bytes": 152340,
  "status": "uploaded",
  "message": "Artifact uploaded to plots/confusion_matrix.png"
}
```

### Download Artifact

```bash
curl -O http://localhost/api/v1/runs/a1b2c3d4.../artifacts/plots/confusion_matrix.png
```

Downloads the file directly.

---

## Model Registry Endpoints

### List Registered Models

```bash
curl http://localhost/api/v1/models?max_results=100
```

**Response:**
```json
{
  "models": [
    {
      "name": "face-detection-yolov8l-p2",
      "creation_timestamp": 1700000000000,
      "last_updated_timestamp": 1700100000000,
      "description": "YOLOv8 face detection optimized for privacy",
      "tags": {
        "model_family": "face-detection",
        "privacy_validated": "true"
      },
      "latest_versions": [
        {
          "version": "2",
          "stage": "Production",
          "status": "READY"
        },
        {
          "version": "1",
          "stage": "Archived",
          "status": "READY"
        }
      ]
    }
  ],
  "total": 3
}
```

### Register Model (with Privacy Validation)

```bash
curl -X POST http://localhost/api/v1/models/register \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "a1b2c3d4...",
    "model_name": "face-detection-yolov8l-p2",
    "model_path": "model",
    "description": "YOLOv8 face detection optimized for privacy",
    "tags": {
      "model_family": "face-detection",
      "privacy_validated": "true",
      "technical_owner": "john"
    },
    "privacy_validated": true,
    "min_recall": 0.96
  }'
```

**Success Response:**
```json
{
  "model_name": "face-detection-yolov8l-p2",
  "version": "1",
  "run_id": "a1b2c3d4...",
  "status": "registered",
  "current_stage": "None",
  "source": "runs:/a1b2c3d4.../model",
  "privacy_validated": true,
  "message": "Model 'face-detection-yolov8l-p2' version 1 registered successfully"
}
```

**Error Response (Low Recall):**
```json
{
  "error": "HTTPException",
  "detail": "Model recall (0.9200) below minimum required (0.9600). PII-PRO requires high recall to minimize false negatives.",
  "trace": "...",
  "timestamp": "2025-11-22T22:30:00.000000"
}
```

**Error Response (Privacy Not Validated):**
```json
{
  "error": "HTTPException",
  "detail": "Privacy validation required for PII-PRO models. Set privacy_validated=true after validation.",
  "trace": "...",
  "timestamp": "2025-11-22T22:30:00.000000"
}
```

### Get Model Details

```bash
curl http://localhost/api/v1/models/face-detection-yolov8l-p2
```

**Response:**
```json
{
  "name": "face-detection-yolov8l-p2",
  "creation_timestamp": 1700000000000,
  "last_updated_timestamp": 1700100000000,
  "description": "YOLOv8 face detection optimized for privacy",
  "tags": {
    "model_family": "face-detection",
    "privacy_validated": "true"
  },
  "versions": [
    {
      "version": "2",
      "stage": "Production",
      "status": "READY",
      "creation_timestamp": 1700100000000,
      "run_id": "xyz789...",
      "source": "runs:/xyz789.../model",
      "tags": {}
    },
    {
      "version": "1",
      "stage": "Archived",
      "status": "READY",
      "creation_timestamp": 1700000000000,
      "run_id": "a1b2c3d4...",
      "source": "runs:/a1b2c3d4.../model",
      "tags": {}
    }
  ],
  "total_versions": 2
}
```

### Transition Model Stage

```bash
# Move to Staging
curl -X POST "http://localhost/api/v1/models/face-detection-yolov8l-p2/versions/1/transition?stage=Staging"

# Move to Production
curl -X POST "http://localhost/api/v1/models/face-detection-yolov8l-p2/versions/1/transition?stage=Production"

# Archive
curl -X POST "http://localhost/api/v1/models/face-detection-yolov8l-p2/versions/1/transition?stage=Archived"
```

**Response:**
```json
{
  "model_name": "face-detection-yolov8l-p2",
  "version": "1",
  "new_stage": "Production",
  "status": "transitioned",
  "message": "Model version 1 transitioned to Production"
}
```

### Delete Model Version

```bash
curl -X DELETE http://localhost/api/v1/models/face-detection-yolov8l-p2/versions/1
```

**Response:**
```json
{
  "model_name": "face-detection-yolov8l-p2",
  "version": "1",
  "status": "deleted",
  "message": "Model version 1 deleted successfully"
}
```

---

## Storage Info

### Get Storage and Configuration Information

```bash
curl http://localhost/api/v1/storage/info
```

**Response:**
```json
{
  "storage": {
    "artifact_root": "/mlflow/artifacts",
    "backend_store": "PostgreSQL (mlflow_db)",
    "artifact_serving": "Enabled (--serve-artifacts)",
    "description": "Artifacts stored in file system, metadata in PostgreSQL"
  },
  "statistics": {
    "total_experiments": 5,
    "total_registered_models": 3,
    "active_experiments": 5
  },
  "model_registry": {
    "enabled": true,
    "backend": "PostgreSQL",
    "features": [
      "Model versioning",
      "Stage transitions (None → Staging → Production → Archived)",
      "Model aliases",
      "Tags and descriptions",
      "Lineage tracking",
      "Download URIs"
    ],
    "stages": ["None", "Staging", "Production", "Archived"]
  },
  "schema_validation": {
    "enabled": true,
    "experiments": [
      "Development-Training",
      "Staging-Model-Comparison",
      "Performance-Benchmarking",
      "Production-Candidates",
      "Dataset-Registry"
    ],
    "privacy_requirements": {
      "min_recall": 0.95,
      "max_false_negative_rate": 0.05,
      "description": "PII-PRO requires high recall to minimize missing PII detection"
    }
  },
  "artifact_organization": {
    "plots": ["confusion_matrix.png", "precision_recall_curve.png", "fps_by_resolution.png"],
    "datasets": ["train_sample.zip", "val_sample.zip", "labels_statistics.json"],
    "reports": ["model_card.md", "privacy_assessment.md", "benchmark_report.html"],
    "models": ["model.pt", "model.onnx", "model_config.yaml", "requirements.txt"]
  },
  "best_practices": {
    "experiments": "Use experiment-specific required tags for consistency",
    "artifacts": "Organize artifacts in subdirectories: plots/, models/, datasets/, reports/",
    "models": "Always log model with config, requirements.txt, and sample I/O",
    "privacy": "Validate recall ≥ 0.95 before registering face detection models",
    "versioning": "Use semantic versioning for models (v1.0.0) and datasets",
    "benchmarking": "Log FPS metrics across all standard resolutions (4K, 1080p, 720p, 480p)"
  },
  "api_endpoints": {
    "experiments": "/api/v1/experiments",
    "runs": "/api/v1/runs",
    "models": "/api/v1/models",
    "artifacts": "/api/v1/runs/{run_id}/artifacts",
    "schema": "/api/v1/schema",
    "documentation": "/api/v1/docs"
  }
}
```

---

## Error Handling

All errors return detailed responses with stack traces for debugging:

```json
{
  "error": "HTTPException",
  "detail": "Experiment 'NonExistent' not found",
  "trace": "Traceback (most recent call last):\n  File \"/app/main.py\", line 234, in create_run\n    ...",
  "timestamp": "2025-11-22T22:30:00.000000",
  "request_path": "/api/v1/runs/create"
}
```

### Common Error Codes

- **400** - Bad Request (invalid parameters)
- **404** - Not Found (experiment, run, or model doesn't exist)
- **422** - Unprocessable Entity (schema validation failed)
- **500** - Internal Server Error (unexpected error)
- **503** - Service Unavailable (MLflow connection issue)

---

## Python Client Examples

### Complete Workflow Example

```python
import requests
import json

BASE_URL = "http://localhost/api/v1"

# 1. Create a new run with schema validation
response = requests.post(f"{BASE_URL}/runs/create", json={
    "experiment_name": "Development-Training",
    "run_name": "yolov8-face-v1",
    "tags": {
        "model_type": "yolov8n",
        "dataset_version": "wider-faces-v1.2",
        "developer": "john",
        "hardware": "rtx3090"
    },
    "parameters": {
        "learning_rate": 0.001,
        "batch_size": 32
    },
    "validate_schema": True
})

run_data = response.json()
run_id = run_data["run_id"]
print(f"Created run: {run_id}")

# 2. Log metrics
requests.post(f"{BASE_URL}/runs/{run_id}/metrics", json={
    "run_id": run_id,
    "metrics": {
        "recall": 0.96,
        "precision": 0.94,
        "f1_score": 0.95,
        "fps_1080p": 58.3,
        "false_negative_rate": 0.04
    },
    "step": 100
})

# 3. Upload artifacts
with open("confusion_matrix.png", "rb") as f:
    files = {"file": f}
    data = {"artifact_path": "plots"}
    requests.post(f"{BASE_URL}/runs/{run_id}/artifacts", files=files, data=data)

# 4. Finish run
requests.post(f"{BASE_URL}/runs/{run_id}/finish", json={"status": "FINISHED"})

# 5. Register model
response = requests.post(f"{BASE_URL}/models/register", json={
    "run_id": run_id,
    "model_name": "face-detection-yolov8l-p2",
    "model_path": "model",
    "description": "YOLOv8 face detection",
    "tags": {
        "model_family": "face-detection",
        "privacy_validated": "true",
        "technical_owner": "john"
    },
    "privacy_validated": True,
    "min_recall": 0.96
})

model_data = response.json()
print(f"Registered model: {model_data['model_name']} v{model_data['version']}")

# 6. Transition to Production
requests.post(
    f"{BASE_URL}/models/face-detection-yolov8l-p2/versions/{model_data['version']}/transition",
    params={"stage": "Production"}
)
```

### Validate Before Creating Run

```python
import requests
import json

BASE_URL = "http://localhost/api/v1"

# Check schema requirements
schema = requests.get(f"{BASE_URL}/schema/experiment/Development-Training").json()
print("Required tags:", schema["schema"]["required_tags"])
print("Required metrics:", schema["schema"]["required_metrics"])

# Validate tags before creating run
tags = {
    "model_type": "yolov8n",
    "dataset_version": "wider-faces-v1.2",
    "developer": "john"
}

response = requests.post(f"{BASE_URL}/schema/validate", data={
    "experiment_name": "Development-Training",
    "tags": json.dumps(tags),
    "metrics": json.dumps({})
})

validation = response.json()
if validation["valid"]:
    print("✓ Tags are valid, creating run...")
    # Create run...
else:
    print("✗ Validation failed:")
    for error in validation["validation_errors"]:
        print(f"  - {error}")
```

---

## 🎉 Summary

The PII-PRO MLflow API provides:

✅ **Professional API layer** with FastAPI and Pydantic validation  
✅ **Schema enforcement** for all 5 PII-PRO experiments  
✅ **Privacy validation** with recall requirements  
✅ **Detailed error traces** for easy debugging  
✅ **Complete Model Registry** management  
✅ **Easy artifact upload/download**  
✅ **Interactive documentation** at `/api/v1/docs`  
✅ **Storage information** and best practices

**Access the interactive docs**: http://localhost/api/v1/docs
