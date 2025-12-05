# Test Suite

All test scripts and files for the ML Platform.

## Test Files

### Service Tests
- **test_all_services.sh** - Comprehensive health checks for all platform services
  - Tests infrastructure (Traefik, PostgreSQL, Redis)
  - Tests monitoring (Prometheus, Grafana, DCGM)
  - Tests MLflow stack
  - Tests Ray cluster
  - Tests Authentik OAuth

### Ray Compute Tests
- **test_job_submission.py** - Tests Ray job submission API
- **test_remote_compute.py** - Tests remote Ray compute functionality
- **test_jobs.sh** - Shell script for Ray job testing

### MLflow Tests
- **test_simple.py** - Basic MLflow API tests
- **test_persistence.sh** - Tests MLflow data persistence

### Integration Tests
- **integration/test_api_endpoints.py** - API endpoint integration tests
- **integration/test_inference_stack.py** - Inference stack integration tests

### Unit Tests
- **unit/inference/test_config.py** - Configuration unit tests
- **unit/inference/test_schemas.py** - Schema validation tests
- **unit/inference/test_utils.py** - Utility function tests

## Running Tests

### All Services Health Check
```bash
cd $PROJECT_ROOT  # Your shml-platform directory
./tests/test_all_services.sh
```

### Ray Job Submission
```bash
cd tests
python test_job_submission.py
```

### Remote Compute
```bash
cd tests
python test_remote_compute.py
```

### Integration Tests
```bash
cd tests
pytest integration/
```

### Unit Tests
```bash
cd tests
pytest unit/
```

### All Tests (via runner)
```bash
./run_tests.sh
```

## Test Requirements

Install test dependencies:
```bash
cd tests
pip install -r requirements.txt
```

## Test Coverage

- **Infrastructure**: Network, databases, cache
- **Monitoring**: Metrics collection, dashboards
- **MLflow**: Tracking, model registry, API
- **Ray**: Cluster health, job submission, GPU access
- **Security**: OAuth/SSO (Authentik)
- **APIs**: REST endpoints, authentication
- **Inference**: Model serving, schemas, config

## Writing New Tests

### Shell Script Tests
Place in `tests/` root with naming: `test_*.sh`

### Python Tests
- Unit tests: `tests/unit/<component>/test_*.py`
- Integration tests: `tests/integration/test_*.py`

Use pytest fixtures from `conftest.py` for common setup.
