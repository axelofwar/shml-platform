# Quick Start: Using MLflow from Remote Machine

## Installation

```bash
pip install mlflow
```

## Basic Usage

### 1. Log an Experiment

```python
import mlflow
from sklearn.ensemble import RandomForestClassifier
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split

# Configure MLflow server
mlflow.set_tracking_uri("http://localhost/mlflow")
mlflow.set_experiment("iris-classification")

# Load data
X, y = load_iris(return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

# Start run
with mlflow.start_run():
    # Train model
    model = RandomForestClassifier(n_estimators=100)
    model.fit(X_train, y_train)

    # Log parameters
    mlflow.log_param("n_estimators", 100)
    mlflow.log_param("model_type", "RandomForest")

    # Log metrics
    mlflow.log_metric("accuracy", model.score(X_test, y_test))

    # Log model
    mlflow.sklearn.log_model(model, "model")

    print(f"✓ Run logged: {mlflow.active_run().info.run_id}")
```

### 2. Register a Model

```python
import mlflow

mlflow.set_tracking_uri("http://localhost/mlflow")

# Option 1: Register during training
with mlflow.start_run():
    mlflow.sklearn.log_model(
        model,
        "model",
        registered_model_name="iris-classifier"
    )

# Option 2: Register existing run
run_id = "your-run-id-here"
model_uri = f"runs:/{run_id}/model"
mlflow.register_model(model_uri, "iris-classifier")
```

### 3. Load and Use a Model

```python
import mlflow.pyfunc

mlflow.set_tracking_uri("http://localhost/mlflow")

# Load latest production model
model = mlflow.pyfunc.load_model("models:/iris-classifier/Production")

# Make predictions
predictions = model.predict(new_data)
```

### 4. Manage Model Stages

```python
from mlflow.tracking import MlflowClient

client = MlflowClient("http://localhost/mlflow")

# Promote to staging
client.transition_model_version_stage(
    name="iris-classifier",
    version=1,
    stage="Staging"
)

# Promote to production
client.transition_model_version_stage(
    name="iris-classifier",
    version=1,
    stage="Production",
    archive_existing_versions=True
)
```

## Complete Example

```python
import mlflow
import mlflow.sklearn
from mlflow.tracking import MlflowClient
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score
from sklearn.datasets import load_iris

# Setup
mlflow.set_tracking_uri("http://localhost/mlflow")
mlflow.set_experiment("iris-production")

# Data
X, y = load_iris(return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Train and log
with mlflow.start_run(run_name="rf-baseline") as run:
    # Train
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    # Predict
    y_pred = model.predict(X_test)

    # Log
    mlflow.log_params({
        "n_estimators": 100,
        "random_state": 42,
        "test_size": 0.2
    })

    mlflow.log_metrics({
        "accuracy": accuracy_score(y_test, y_pred),
        "f1_score": f1_score(y_test, y_pred, average='weighted')
    })

    mlflow.set_tags({
        "model_type": "RandomForest",
        "dataset": "iris",
        "developer": "data-team"
    })

    # Register model
    mlflow.sklearn.log_model(
        model,
        "model",
        registered_model_name="iris-classifier"
    )

    print(f"✓ Model trained and registered")
    print(f"  Run ID: {run.info.run_id}")

# Promote model
client = MlflowClient("http://localhost/mlflow")
latest = client.get_latest_versions("iris-classifier", stages=["None"])[0]

client.transition_model_version_stage(
    name="iris-classifier",
    version=latest.version,
    stage="Production"
)

print(f"✓ Model version {latest.version} promoted to Production")

# Use model
model = mlflow.pyfunc.load_model("models:/iris-classifier/Production")
predictions = model.predict(X_test)
print(f"✓ Made {len(predictions)} predictions")
```

## Environment Variable Setup

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
export MLFLOW_TRACKING_URI="http://localhost/mlflow"
```

Then you don't need to call `mlflow.set_tracking_uri()` in your code.

## Verify Connection

```python
import mlflow
import requests

tracking_uri = "http://localhost/mlflow"

# Test connection
try:
    response = requests.get(f"{tracking_uri}/api/2.0/mlflow/experiments/list")
    print(f"✓ Connected to MLflow server (status: {response.status_code})")
except Exception as e:
    print(f"✗ Connection failed: {e}")

# Test Model Registry
from mlflow.tracking import MlflowClient
client = MlflowClient(tracking_uri)

try:
    models = client.search_registered_models(max_results=5)
    print(f"✓ Model Registry accessible ({len(models)} models found)")
except Exception as e:
    print(f"✗ Model Registry error: {e}")
```

## Documentation

- **Complete Guide:** [REMOTE_CLIENT_GUIDE.md](docs/REMOTE_CLIENT_GUIDE.md)
- **Model Registry:** [MODEL_REGISTRY_GUIDE.md](docs/MODEL_REGISTRY_GUIDE.md)
- **MLflow Docs:** https://mlflow.org/docs/latest/

## Support

- Server URL: http://localhost/mlflow
- Health check: http://localhost/mlflow/health
- API docs: https://mlflow.org/docs/latest/rest-api.html
