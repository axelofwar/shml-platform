# MLflow Native Model Registry Guide

## Overview

This MLflow deployment uses the **native MLflow Model Registry** backed by PostgreSQL. Custom experiments have been removed in favor of MLflow's built-in model lifecycle management.

## What Changed

### Before (Custom Experiments)
- ❌ Custom experiments: `production-models`, `staging-models`, `development-models`
- ❌ Custom experiment: `model-registry-experiments` for tracking
- ❌ Custom experiment: `dataset-registry` for data versioning
- ❌ Manual experiment management and schema enforcement

### After (Native Model Registry)
- ✅ Native MLflow Model Registry with PostgreSQL backend
- ✅ Built-in model stages: None → Staging → Production → Archived
- ✅ Automatic model versioning and lineage tracking
- ✅ Webhook support for stage transitions
- ✅ UI-based model management
- ✅ API-driven model registration and promotion

## Model Registry Features

### Model Stages
1. **None** - Initial state when model is registered
2. **Staging** - Model under evaluation/testing
3. **Production** - Model deployed to production
4. **Archived** - Deprecated/retired model

### Core Capabilities
- **Versioning**: Automatic version increments for each model registration
- **Lineage**: Track which experiment runs produced each model version
- **Metadata**: Tags, descriptions, and custom attributes
- **Stage Transitions**: Promote models through lifecycle stages
- **Annotations**: Add notes and comments to model versions
- **Webhooks**: Trigger external systems on stage changes

## Usage Examples

### Python API

#### Register a Model
```python
import mlflow

# After logging a model in an experiment
mlflow.set_tracking_uri("http://localhost/mlflow")

with mlflow.start_run():
    # Train your model
    model = train_model()

    # Log the model
    mlflow.sklearn.log_model(model, "model")

    # Register to Model Registry
    model_uri = f"runs:/{mlflow.active_run().info.run_id}/model"
    mlflow.register_model(model_uri, "my-classifier")
```

#### Transition Model Stage
```python
from mlflow.tracking import MlflowClient

client = MlflowClient("http://localhost/mlflow")

# Promote to staging
client.transition_model_version_stage(
    name="my-classifier",
    version=1,
    stage="Staging"
)

# After testing, promote to production
client.transition_model_version_stage(
    name="my-classifier",
    version=1,
    stage="Production",
    archive_existing_versions=True  # Archive old production versions
)
```

#### Load Model from Registry
```python
import mlflow.pyfunc

# Load latest production model
model = mlflow.pyfunc.load_model("models:/my-classifier/Production")

# Load specific version
model = mlflow.pyfunc.load_model("models:/my-classifier/3")
```

#### Search and Filter Models
```python
from mlflow.tracking import MlflowClient

client = MlflowClient("http://localhost/mlflow")

# Get all models
models = client.search_registered_models()

# Filter by name
models = client.search_registered_models(filter_string="name='my-classifier'")

# Get model versions
versions = client.search_model_versions("name='my-classifier'")

# Get production models
prod_models = client.search_model_versions("run_id != '' AND current_stage='Production'")
```

### REST API

#### List Registered Models
```bash
curl "http://localhost/api/2.0/mlflow/registered-models/search"
```

#### Create Registered Model
```bash
curl -X POST "http://localhost/api/2.0/mlflow/registered-models/create" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-model",
    "tags": [
      {"key": "task", "value": "classification"},
      {"key": "framework", "value": "sklearn"}
    ],
    "description": "My production model"
  }'
```

#### Create Model Version
```bash
curl -X POST "http://localhost/api/2.0/mlflow/model-versions/create" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-model",
    "source": "s3://my-bucket/path/to/model",
    "run_id": "abc123",
    "tags": [{"key": "env", "value": "prod"}]
  }'
```

#### Transition Model Stage
```bash
curl -X POST "http://localhost/api/2.0/mlflow/model-versions/transition-stage" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-model",
    "version": "1",
    "stage": "Production",
    "archive_existing_versions": true
  }'
```

### Web UI

Access the Model Registry UI at: `http://localhost/mlflow`

1. **View Models**: Click "Models" in the top navigation
2. **Register Model**:
   - Go to an experiment run
   - Click on a logged model artifact
   - Click "Register Model"
   - Choose existing model or create new one
3. **Manage Stages**:
   - Open a registered model
   - Select a version
   - Click "Stage" dropdown
   - Choose new stage
4. **Add Metadata**:
   - Add tags, descriptions, and notes
   - Link to external documentation

## Best Practices

### Naming Conventions
```
✅ Good:
- fraud-detector-v2
- recommendation-engine
- customer-churn-predictor

❌ Avoid:
- model_1
- test-model-final-v2-really-final
- my_model
```

### Tagging Strategy
```python
tags = {
    "task": "classification",           # Task type
    "framework": "tensorflow",          # Framework used
    "dataset_version": "2024-11",       # Training data version
    "author": "data-science-team",      # Owner
    "jira_ticket": "DS-1234",          # Tracking reference
    "performance_metric": "f1=0.92"     # Key metrics
}
```

### Stage Transition Workflow
1. **Development**: Train model in experiment → Register as new version (Stage: None)
2. **Testing**: Transition to Staging → Run validation tests
3. **Production**: Transition to Production → Deploy via CI/CD
4. **Retirement**: Transition to Archived when deprecated

### Version Management
- Keep 3-5 recent versions per model
- Archive old production versions when promoting new ones
- Document major changes in version descriptions
- Use semantic versioning in tags (v1.2.3)

## Artifact Serving

### Configuration
The MLflow server is configured with `--serve-artifacts` to enable remote artifact uploads:

```bash
mlflow server \
  --backend-store-uri postgresql://... \
  --default-artifact-root /mlflow/artifacts \
  --serve-artifacts \
  --artifacts-destination /mlflow/artifacts
```

### Benefits
- ✅ Remote clients can upload artifacts via HTTP
- ✅ No need for shared filesystem or S3 credentials on clients
- ✅ Centralized artifact storage
- ✅ Works across network boundaries

### Artifact Types
- Model files (pickle, SavedModel, ONNX, etc.)
- Training plots and visualizations
- Feature importance charts
- Confusion matrices
- Model cards and documentation
- Dataset samples

## Database Schema

The Model Registry uses these PostgreSQL tables:

```sql
-- Registered models
registered_models (
  name VARCHAR(256) PRIMARY KEY,
  creation_time BIGINT,
  last_updated_time BIGINT,
  description VARCHAR(5000)
)

-- Model versions
model_versions (
  name VARCHAR(256),
  version INT,
  creation_time BIGINT,
  last_updated_time BIGINT,
  description VARCHAR(5000),
  user_id VARCHAR(256),
  current_stage VARCHAR(20),
  source VARCHAR(500),
  run_id VARCHAR(32),
  status VARCHAR(20),
  status_message VARCHAR(500),
  PRIMARY KEY (name, version)
)

-- Model version tags
model_version_tags (
  name VARCHAR(256),
  version INT,
  key VARCHAR(250),
  value VARCHAR(5000),
  PRIMARY KEY (name, version, key)
)

-- Registered model tags
registered_model_tags (
  name VARCHAR(256),
  key VARCHAR(250),
  value VARCHAR(5000),
  PRIMARY KEY (name, key)
)

-- Registered model aliases
registered_model_aliases (
  name VARCHAR(256),
  alias VARCHAR(256),
  version INT,
  PRIMARY KEY (name, alias)
)
```

## Migration from Custom Experiments

If you have existing models in the old custom experiments:

1. **Export Runs**: Use MLflow API to list all runs from old experiments
2. **Re-register Models**: Register important models to the Model Registry
3. **Preserve Metadata**: Copy tags, parameters, and metrics
4. **Archive Old Experiments**: Keep for historical reference but mark as deprecated

Example migration script:
```python
from mlflow.tracking import MlflowClient

client = MlflowClient()

# Get runs from old experiment
old_experiment = "production-models"
runs = client.search_runs(
    experiment_ids=[client.get_experiment_by_name(old_experiment).experiment_id]
)

# Re-register important models
for run in runs:
    if run.data.tags.get("important") == "true":
        model_uri = f"runs:/{run.info.run_id}/model"
        mlflow.register_model(
            model_uri,
            name=run.data.tags.get("model_name", "migrated-model")
        )
```

## Troubleshooting

### Model Registration Fails
```bash
# Check Model Registry tables exist
docker exec mlflow-postgres psql -U mlflow -d mlflow_db -c "\dt registered_*"

# Check server logs
docker logs mlflow-server | grep -i "model registry"
```

### Artifact Upload Fails
```bash
# Verify --serve-artifacts flag
docker exec mlflow-server ps aux | grep "serve-artifacts"

# Test artifact API
curl "http://localhost/api/2.0/mlflow-artifacts/artifacts"
```

### Stage Transition Fails
```bash
# Check current stage
curl "http://localhost/api/2.0/mlflow/model-versions/get?name=my-model&version=1"

# Verify no duplicate production versions (if archive_existing_versions not set)
```

## API Reference

Full API documentation: https://mlflow.org/docs/latest/rest-api.html#mlflow-model-registry

Key endpoints:
- `POST /api/2.0/mlflow/registered-models/create`
- `GET /api/2.0/mlflow/registered-models/search`
- `POST /api/2.0/mlflow/model-versions/create`
- `POST /api/2.0/mlflow/model-versions/transition-stage`
- `GET /api/2.0/mlflow/model-versions/get-download-uri`

## Additional Resources

- [MLflow Model Registry Documentation](https://mlflow.org/docs/latest/model-registry.html)
- [MLflow Python API](https://mlflow.org/docs/latest/python_api/index.html)
- [Model Registry REST API](https://mlflow.org/docs/latest/rest-api.html#mlflow-model-registry)
- [MLflow Webhooks](https://mlflow.org/docs/latest/registry-webhooks.html)
