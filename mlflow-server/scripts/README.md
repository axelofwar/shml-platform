# MLflow Server Scripts

Utility scripts for server management and operations.

## Server Management

### check_status.sh
Complete server health check - MLflow, Nginx, PostgreSQL, firewall, and disk space.

```bash
./check_status.sh
```

### check_http_artifacts.sh
Test artifact upload functionality and HTTP endpoints.

```bash
./check_http_artifacts.sh
```

### db_info.sh
Quick database overview - record counts, recent experiments/runs, models, and backup status.

```bash
./db_info.sh
```

## Configuration & Maintenance

### update_password.sh
Interactive password update for PostgreSQL - updates all affected configurations automatically.

```bash
./update_password.sh
# Follow prompts
# Training machine requires NO changes after update
```

### sync_from_dev.sh
Sync project files from development machine (if using remote development).

```bash
./sync_from_dev.sh
```

## Model Registration

### register_model_v2.py
Register trained models to MLflow Model Registry with metadata, metrics, and artifacts.

```bash
# Basic usage
python register_model_v2.py \
  --model-path /path/to/model \
  --model-name my-model \
  --version-name v1.0 \
  --description "Model description"

# Full options
python register_model_v2.py --help
```

### register_model_versions.py
Register multiple versions of a model at once.

```bash
python register_model_versions.py --help
```

### register_historical_models.py
Bulk register historical models from filesystem.

```bash
python register_historical_models.py --help
```

### update_training_scripts.py
Update training scripts to use remote MLflow tracking.

```bash
python update_training_scripts.py --help
```

## Usage Examples

### Daily Health Check
```bash
./check_status.sh && ./db_info.sh
```

### Test Artifact Upload
```bash
./check_http_artifacts.sh
```

### Register Model After Training
```bash
# From training machine
export MLFLOW_TRACKING_URI="http://<SERVER_IP>:8080"
python scripts/register_model_v2.py \
  --model-path ./models/trained_model \
  --model-name production-model \
  --version-name v2.1 \
  --stage Staging
```

### Update Database Password
```bash
./update_password.sh
# Enter new password when prompted
# Script updates all configurations automatically
```

## Configuration

Scripts use these environment configurations:

- **MLFLOW_TRACKING_URI**: Server URL (default: http://<SERVER_IP>:8080)
- **PGPASSWORD**: Read from `/opt/mlflow/.mlflow_db_pass`
- **DB_HOST**: localhost
- **DB_NAME**: mlflow_db
- **DB_USER**: mlflow

## Requirements

All scripts assume:
- Tailscale VPN connection active
- MLflow server running on <SERVER_IP>
- PostgreSQL credentials in `/opt/mlflow/.mlflow_db_pass`
- Python 3.8+ with mlflow package (for Python scripts)

## Support

For detailed documentation, see:
- **[../docs/](../docs/)** - Complete system documentation
- **[../QUICKSTART.md](../QUICKSTART.md)** - Quick start guide
- **[../QUICK_REFERENCE.md](../QUICK_REFERENCE.md)** - Command reference
