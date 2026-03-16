# MLflow API Wrapper

Professional FastAPI layer for MLflow with schema validation, error handling, and Model Registry support.

## Features

- ✅ **Schema Validation**: Enforces PII-PRO experiment requirements
- ✅ **Error Traces**: Detailed error messages with full stack traces
- ✅ **Privacy Validation**: Minimum recall enforcement for face detection models
- ✅ **Artifact Management**: Easy upload/download with validation
- ✅ **Model Registry**: Complete model lifecycle management
- ✅ **Storage Info**: Comprehensive configuration and best practices
- ✅ **Interactive Docs**: Auto-generated Swagger UI and ReDoc

## Quick Start

### Build and Run

```bash
cd /opt
docker-compose up -d mlflow-api
```

### Access API

- **Base URL**: http://localhost/api/v1
- **Swagger UI**: http://localhost/api/v1/docs
- **ReDoc**: http://localhost/api/v1/redoc

## API Endpoints

### Schema
- `GET /api/v1/schema` - Get complete schema
- `GET /api/v1/schema/experiment/{name}` - Get experiment-specific schema
- `POST /api/v1/schema/validate` - Validate tags/metrics

### Experiments
- `GET /api/v1/experiments` - List experiments
- `GET /api/v1/experiments/{id}` - Get experiment details

### Runs
- `POST /api/v1/runs/create` - Create run with validation
- `GET /api/v1/runs/{id}` - Get run details
- `POST /api/v1/runs/{id}/metrics` - Log metrics
- `POST /api/v1/runs/{id}/finish` - Finish run

### Artifacts
- `POST /api/v1/runs/{id}/artifacts` - Upload artifact
- `GET /api/v1/runs/{id}/artifacts/{path}` - Download artifact

### Models
- `GET /api/v1/models` - List registered models
- `POST /api/v1/models/register` - Register model with privacy validation
- `GET /api/v1/models/{name}` - Get model details
- `POST /api/v1/models/{name}/versions/{version}/transition` - Transition stage
- `DELETE /api/v1/models/{name}/versions/{version}` - Delete version

### Info
- `GET /api/v1/storage/info` - Storage and configuration info

## Documentation

See [API_GUIDE.md](../docs/API_GUIDE.md) for complete documentation with examples.

## Development

### Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment
export MLFLOW_TRACKING_URI=http://localhost:5000

# Run locally
uvicorn main:app --reload --port 8000
```

### Docker Build

```bash
docker build -t mlflow-api:latest .
```

## Environment Variables

- `MLFLOW_TRACKING_URI` - MLflow tracking server URL (default: http://localhost:5000)
- `MLFLOW_ARTIFACT_ROOT` - Artifact storage location (default: /mlflow/artifacts)

## Health Check

```bash
curl http://localhost/api/v1/health
```

## Error Handling

All errors return structured responses with:
- Error type and detail
- Full stack trace
- Timestamp
- Request path

Example error response:
```json
{
  "error": "HTTPException",
  "detail": "Experiment 'NonExistent' not found",
  "trace": "Traceback (most recent call last): ...",
  "timestamp": "2025-11-22T22:30:00.000000",
  "request_path": "/api/v1/runs/create"
}
```

## Privacy Validation

For face detection models (PII-PRO):
- Minimum recall: 0.95
- Maximum false negative rate: 0.05
- Privacy validation required before model registration

## Contributing

1. Test changes locally
2. Update documentation
3. Rebuild Docker image
4. Deploy with docker-compose
