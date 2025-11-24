# MLflow API Quick Reference

## Base URL
```
http://localhost/api/v1
```

## Documentation
```
http://localhost/api/v1/docs  (Swagger UI)
```

---

## 🔑 Key Endpoints

### Schema & Validation
```bash
# Get complete schema
GET /api/v1/schema

# Get experiment schema
GET /api/v1/schema/experiment/Development-Training

# Validate before creating
POST /api/v1/schema/validate
```

### Experiments
```bash
# List all
GET /api/v1/experiments

# Get details
GET /api/v1/experiments/{id}
```

### Runs
```bash
# Create with validation
POST /api/v1/runs/create

# Get details
GET /api/v1/runs/{id}

# Log metrics
POST /api/v1/runs/{id}/metrics

# Finish run
POST /api/v1/runs/{id}/finish
```

### Artifacts
```bash
# Upload
POST /api/v1/runs/{id}/artifacts

# Download
GET /api/v1/runs/{id}/artifacts/{path}
```

### Model Registry
```bash
# List models
GET /api/v1/models

# Register (with privacy check)
POST /api/v1/models/register

# Get model
GET /api/v1/models/{name}

# Change stage
POST /api/v1/models/{name}/versions/{v}/transition?stage=Production

# Delete version
DELETE /api/v1/models/{name}/versions/{v}
```

### Info
```bash
# Storage & best practices
GET /api/v1/storage/info

# Health check
GET /api/v1/health
```

---

## 📝 Quick Examples

### Create Run (curl)
```bash
curl -X POST http://localhost/api/v1/runs/create \
  -H "Content-Type: application/json" \
  -d '{
    "experiment_name": "Development-Training",
    "run_name": "yolov8-v1",
    "tags": {
      "model_type": "yolov8n",
      "dataset_version": "wider-faces-v1.2",
      "developer": "john"
    },
    "validate_schema": true
  }'
```

### Log Metrics (curl)
```bash
curl -X POST http://localhost/api/v1/runs/RUN_ID/metrics \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "RUN_ID",
    "metrics": {
      "recall": 0.96,
      "precision": 0.94,
      "fps_1080p": 58.3
    }
  }'
```

### Upload Artifact (curl)
```bash
curl -X POST http://localhost/api/v1/runs/RUN_ID/artifacts \
  -F "file=@confusion_matrix.png" \
  -F "artifact_path=plots"
```

### Register Model (curl)
```bash
curl -X POST http://localhost/api/v1/models/register \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "RUN_ID",
    "model_name": "face-detection-yolov8",
    "privacy_validated": true,
    "min_recall": 0.96
  }'
```

### Python Example
```python
import requests

BASE = "http://localhost/api/v1"

# Create run
r = requests.post(f"{BASE}/runs/create", json={
    "experiment_name": "Development-Training",
    "tags": {
        "model_type": "yolov8n",
        "dataset_version": "wider-faces-v1.2",
        "developer": "john"
    }
})
run_id = r.json()["run_id"]

# Log metrics
requests.post(f"{BASE}/runs/{run_id}/metrics", json={
    "run_id": run_id,
    "metrics": {"recall": 0.96, "fps_1080p": 58.3}
})

# Upload artifact
with open("plot.png", "rb") as f:
    requests.post(
        f"{BASE}/runs/{run_id}/artifacts",
        files={"file": f},
        data={"artifact_path": "plots"}
    )

# Register model
requests.post(f"{BASE}/models/register", json={
    "run_id": run_id,
    "model_name": "my-model",
    "privacy_validated": True,
    "min_recall": 0.96
})
```

---

## ⚠️ Privacy Requirements

Face detection models must have:
- **Recall ≥ 0.95** (minimize false negatives)
- **False negative rate ≤ 0.05**
- **privacy_validated = true** flag

Models below threshold will be **rejected**.

---

## 🔍 Error Responses

All errors include:
```json
{
  "error": "HTTPException",
  "detail": "Detailed error message",
  "trace": "Full stack trace...",
  "timestamp": "2025-11-22T22:30:00Z",
  "request_path": "/api/v1/runs/create"
}
```

---

## 📖 Full Documentation
See `mlflow-server/docs/API_GUIDE.md` for complete guide.
