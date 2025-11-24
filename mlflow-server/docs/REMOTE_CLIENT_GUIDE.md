# MLflow Remote Client Usage Guide

## Overview

This guide shows how to use MLflow from remote machines to log experiments, upload artifacts, and register models to the centralized MLflow server.

## Server Information

- **MLflow Tracking URI**: `http://localhost/mlflow`
- **Backend Store**: PostgreSQL (centralized, server-managed)
- **Artifact Store**: Server filesystem with HTTP proxy (no client configuration needed)
- **Model Registry**: Native MLflow Model Registry (PostgreSQL-backed)

## Quick Start

### Installation

```bash
pip install mlflow
```

### Basic Configuration

```python
import mlflow

# Set tracking URI to your MLflow server
mlflow.set_tracking_uri("http://localhost/mlflow")
```

## Logging Experiments

### Simple Experiment Run

```python
import mlflow
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split

# Configure MLflow
mlflow.set_tracking_uri("http://localhost/mlflow")
mlflow.set_experiment("my-experiment")

# Load data
X, y = load_iris(return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

# Start MLflow run
with mlflow.start_run(run_name="logistic-regression-baseline"):
    # Log parameters
    mlflow.log_param("model_type", "logistic_regression")
    mlflow.log_param("test_size", 0.2)
    mlflow.log_param("solver", "lbfgs")
    
    # Train model
    model = LogisticRegression(solver="lbfgs", max_iter=200)
    model.fit(X_train, y_train)
    
    # Log metrics
    train_score = model.score(X_train, y_train)
    test_score = model.score(X_test, y_test)
    mlflow.log_metric("train_accuracy", train_score)
    mlflow.log_metric("test_accuracy", test_score)
    
    # Log model
    mlflow.sklearn.log_model(model, "model")
    
    print(f"Run ID: {mlflow.active_run().info.run_id}")
    print(f"Experiment ID: {mlflow.active_run().info.experiment_id}")
```

### Logging Additional Artifacts

```python
import mlflow
import matplotlib.pyplot as plt
import pandas as pd
import json

mlflow.set_tracking_uri("http://localhost/mlflow")

with mlflow.start_run():
    # Log a plot
    plt.figure(figsize=(10, 6))
    plt.plot([1, 2, 3, 4], [1, 4, 9, 16])
    plt.title("Training Progress")
    plt.savefig("plot.png")
    mlflow.log_artifact("plot.png")
    
    # Log a dataframe
    df = pd.DataFrame({"feature": ["A", "B", "C"], "importance": [0.5, 0.3, 0.2]})
    df.to_csv("feature_importance.csv", index=False)
    mlflow.log_artifact("feature_importance.csv")
    
    # Log a JSON config
    config = {"learning_rate": 0.01, "batch_size": 32}
    with open("config.json", "w") as f:
        json.dump(config, f)
    mlflow.log_artifact("config.json")
    
    # Log entire directory
    # mlflow.log_artifacts("output_dir/")
```

### Using Tags for Organization

```python
import mlflow

mlflow.set_tracking_uri("http://localhost/mlflow")

with mlflow.start_run():
    # Set run tags
    mlflow.set_tag("environment", "production")
    mlflow.set_tag("team", "data-science")
    mlflow.set_tag("project", "customer-churn")
    mlflow.set_tag("version", "v2.1.0")
    mlflow.set_tag("jira_ticket", "DS-1234")
    
    # Your training code here
    mlflow.log_param("epochs", 100)
    mlflow.log_metric("loss", 0.25)
```

## Using the Model Registry

### Registering a Model

#### Option 1: Register During Training

```python
import mlflow
import mlflow.sklearn
from sklearn.ensemble import RandomForestClassifier

mlflow.set_tracking_uri("http://localhost/mlflow")
mlflow.set_experiment("production-training")

with mlflow.start_run():
    # Train model
    model = RandomForestClassifier(n_estimators=100)
    model.fit(X_train, y_train)
    
    # Log metrics
    mlflow.log_metric("accuracy", 0.95)
    
    # Log and register model in one step
    mlflow.sklearn.log_model(
        model,
        "model",
        registered_model_name="customer-churn-classifier"
    )
```

#### Option 2: Register After Training

```python
import mlflow

mlflow.set_tracking_uri("http://localhost/mlflow")

# After a run is complete, register the model
run_id = "abc123def456"  # Your run ID
model_uri = f"runs:/{run_id}/model"

result = mlflow.register_model(
    model_uri,
    "customer-churn-classifier",
    tags={"framework": "sklearn", "task": "classification"}
)

print(f"Model registered: {result.name} version {result.version}")
```

### Managing Model Stages

```python
from mlflow.tracking import MlflowClient

client = MlflowClient("http://localhost/mlflow")

# Transition to Staging
client.transition_model_version_stage(
    name="customer-churn-classifier",
    version=1,
    stage="Staging"
)

# After validation, promote to Production
client.transition_model_version_stage(
    name="customer-churn-classifier",
    version=1,
    stage="Production",
    archive_existing_versions=True  # Archive old production versions
)

# Archive deprecated models
client.transition_model_version_stage(
    name="customer-churn-classifier",
    version=1,
    stage="Archived"
)
```

### Loading Models from Registry

```python
import mlflow.pyfunc

mlflow.set_tracking_uri("http://localhost/mlflow")

# Load latest production model
model = mlflow.pyfunc.load_model("models:/customer-churn-classifier/Production")

# Make predictions
predictions = model.predict(X_new)

# Load specific version
model_v2 = mlflow.pyfunc.load_model("models:/customer-churn-classifier/2")
```

### Searching the Model Registry

```python
from mlflow.tracking import MlflowClient

client = MlflowClient("http://localhost/mlflow")

# List all registered models
models = client.search_registered_models()
for model in models:
    print(f"Model: {model.name}")
    print(f"  Description: {model.description}")
    print(f"  Latest versions: {model.latest_versions}")

# Search for specific models
models = client.search_registered_models(
    filter_string="name LIKE 'customer-%'"
)

# Get all versions of a model
versions = client.search_model_versions("name='customer-churn-classifier'")
for v in versions:
    print(f"Version {v.version}: {v.current_stage} (run: {v.run_id})")

# Get production models only
prod_models = client.search_model_versions(
    "current_stage='Production'"
)
```

### Adding Model Metadata

```python
from mlflow.tracking import MlflowClient

client = MlflowClient("http://localhost/mlflow")

# Update model description
client.update_registered_model(
    name="customer-churn-classifier",
    description="Random Forest classifier for predicting customer churn. Trained on 2024-11 dataset."
)

# Add tags to registered model
client.set_registered_model_tag(
    name="customer-churn-classifier",
    key="owner",
    value="data-science-team"
)

# Add tags to specific version
client.set_model_version_tag(
    name="customer-churn-classifier",
    version="1",
    key="validation_score",
    value="0.95"
)

# Update version description
client.update_model_version(
    name="customer-churn-classifier",
    version="1",
    description="Baseline model with 95% accuracy on test set"
)
```

## Complete Example: Training to Production

```python
import mlflow
import mlflow.sklearn
from mlflow.tracking import MlflowClient
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
import pandas as pd
import numpy as np

# Configure MLflow
mlflow.set_tracking_uri("http://localhost/mlflow")
mlflow.set_experiment("churn-prediction-training")

# Load your data
# X, y = load_your_data()
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Start training run
with mlflow.start_run(run_name="rf-production-candidate") as run:
    # Set tags
    mlflow.set_tag("environment", "production")
    mlflow.set_tag("model_type", "random_forest")
    mlflow.set_tag("dataset_version", "2024-11")
    
    # Log parameters
    params = {
        "n_estimators": 100,
        "max_depth": 10,
        "min_samples_split": 5,
        "random_state": 42
    }
    mlflow.log_params(params)
    
    # Train model
    model = RandomForestClassifier(**params)
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    metrics = {
        "accuracy": accuracy_score(y_test, y_pred),
        "f1_score": f1_score(y_test, y_pred, average='weighted'),
        "precision": precision_score(y_test, y_pred, average='weighted'),
        "recall": recall_score(y_test, y_pred, average='weighted')
    }
    mlflow.log_metrics(metrics)
    
    # Log feature importance
    feature_importance = pd.DataFrame({
        'feature': X_train.columns,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    
    feature_importance.to_csv("feature_importance.csv", index=False)
    mlflow.log_artifact("feature_importance.csv")
    
    # Log model and register
    mlflow.sklearn.log_model(
        model,
        "model",
        registered_model_name="customer-churn-classifier"
    )
    
    run_id = run.info.run_id
    print(f"Training completed. Run ID: {run_id}")
    print(f"Metrics: {metrics}")

# Promote to staging
client = MlflowClient("http://localhost/mlflow")

# Get latest version
latest_version = client.get_latest_versions("customer-churn-classifier", stages=["None"])[0]

print(f"Registered model version: {latest_version.version}")

# Transition to Staging for validation
client.transition_model_version_stage(
    name="customer-churn-classifier",
    version=latest_version.version,
    stage="Staging"
)

print("Model promoted to Staging. Run validation tests...")

# After validation passes, promote to Production
# client.transition_model_version_stage(
#     name="customer-churn-classifier",
#     version=latest_version.version,
#     stage="Production",
#     archive_existing_versions=True
# )
```

## Using Models in Production

### Simple Prediction Service

```python
import mlflow.pyfunc
import pandas as pd
from flask import Flask, request, jsonify

app = Flask(__name__)

# Load production model on startup
mlflow.set_tracking_uri("http://localhost/mlflow")
model = mlflow.pyfunc.load_model("models:/customer-churn-classifier/Production")

@app.route('/predict', methods=['POST'])
def predict():
    data = request.get_json()
    df = pd.DataFrame(data)
    predictions = model.predict(df)
    return jsonify(predictions.tolist())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
```

### Batch Prediction Script

```python
import mlflow.pyfunc
import pandas as pd

mlflow.set_tracking_uri("http://localhost/mlflow")

# Load production model
model = mlflow.pyfunc.load_model("models:/customer-churn-classifier/Production")

# Load data to score
data = pd.read_csv("customers_to_score.csv")

# Make predictions
predictions = model.predict(data)

# Save results
results = data.copy()
results['churn_probability'] = predictions
results.to_csv("predictions.csv", index=False)

print(f"Scored {len(results)} customers")
```

## Environment Variables (Alternative Configuration)

Instead of setting the tracking URI in code, you can use environment variables:

```bash
# In your shell or .bashrc / .zshrc
export MLFLOW_TRACKING_URI="http://localhost/mlflow"
```

Then in Python:

```python
import mlflow

# No need to set tracking URI - uses MLFLOW_TRACKING_URI env var
mlflow.set_experiment("my-experiment")

with mlflow.start_run():
    mlflow.log_param("alpha", 0.5)
```

## Troubleshooting

### Connection Issues

```python
import mlflow
import requests

# Test connection
tracking_uri = "http://localhost/mlflow"

try:
    response = requests.get(f"{tracking_uri}/api/2.0/mlflow/experiments/list")
    print(f"✓ Connected to MLflow server")
    print(f"Status: {response.status_code}")
except Exception as e:
    print(f"✗ Connection failed: {e}")
```

### Verify Artifact Upload

```python
import mlflow
import tempfile
import os

mlflow.set_tracking_uri("http://localhost/mlflow")

with mlflow.start_run():
    # Create test file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Test artifact")
        temp_path = f.name
    
    try:
        # Upload artifact
        mlflow.log_artifact(temp_path, "test_artifacts")
        print("✓ Artifact uploaded successfully")
    except Exception as e:
        print(f"✗ Artifact upload failed: {e}")
    finally:
        os.unlink(temp_path)
```

### Check Model Registry Access

```python
from mlflow.tracking import MlflowClient

client = MlflowClient("http://localhost/mlflow")

try:
    models = client.search_registered_models(max_results=1)
    print("✓ Model Registry accessible")
    print(f"Found {len(models)} registered model(s)")
except Exception as e:
    print(f"✗ Model Registry error: {e}")
```

## Best Practices

### 1. Experiment Organization

```python
# Use descriptive experiment names
mlflow.set_experiment("fraud-detection-v2")  # Good
# mlflow.set_experiment("test")  # Bad

# Use nested experiments for related work
mlflow.set_experiment("fraud-detection/feature-engineering")
mlflow.set_experiment("fraud-detection/model-selection")
mlflow.set_experiment("fraud-detection/hyperparameter-tuning")
```

### 2. Run Naming

```python
# Descriptive run names
with mlflow.start_run(run_name="xgboost-10k-samples-balanced"):
    pass

# Include key parameters in name for easy identification
with mlflow.start_run(run_name=f"rf-trees-{n_estimators}-depth-{max_depth}"):
    pass
```

### 3. Comprehensive Logging

```python
with mlflow.start_run():
    # Log everything relevant
    mlflow.log_params({
        "model": "xgboost",
        "n_estimators": 100,
        "learning_rate": 0.1,
        "dataset_size": len(X_train),
        "features": X_train.shape[1],
        "preprocessing": "standard_scaler"
    })
    
    mlflow.log_metrics({
        "train_accuracy": train_acc,
        "test_accuracy": test_acc,
        "train_time_seconds": train_time,
        "inference_time_ms": inference_time
    })
    
    mlflow.set_tags({
        "developer": "john.doe",
        "purpose": "baseline_model",
        "data_version": "v2024.11"
    })
```

### 4. Model Registry Workflow

```python
# Development → Staging → Production workflow
# 1. Train and register
with mlflow.start_run():
    mlflow.sklearn.log_model(model, "model", registered_model_name="my-model")

# 2. Test in staging
client.transition_model_version_stage("my-model", version=1, stage="Staging")
# Run validation tests...

# 3. Deploy to production
client.transition_model_version_stage(
    "my-model", 
    version=1, 
    stage="Production",
    archive_existing_versions=True
)
```

### 5. Error Handling

```python
import mlflow

mlflow.set_tracking_uri("http://localhost/mlflow")

try:
    with mlflow.start_run():
        # Your training code
        model = train_model()
        mlflow.sklearn.log_model(model, "model")
        
except Exception as e:
    # Log the error
    mlflow.log_param("error", str(e))
    mlflow.set_tag("status", "failed")
    raise
else:
    mlflow.set_tag("status", "success")
```

## CLI Usage

MLflow also provides a command-line interface:

```bash
# Set tracking URI
export MLFLOW_TRACKING_URI="http://localhost/mlflow"

# List experiments
mlflow experiments list

# Search runs
mlflow runs list --experiment-id 1

# Download artifacts
mlflow artifacts download --run-id abc123 --artifact-path model

# Serve a model locally
mlflow models serve -m "models:/customer-churn-classifier/Production" -p 5002
```

## API Reference

For complete API documentation, see:
- Python API: https://mlflow.org/docs/latest/python_api/index.html
- REST API: https://mlflow.org/docs/latest/rest-api.html
- Model Registry: https://mlflow.org/docs/latest/model-registry.html

## Support

If you encounter issues:
1. Check server status: `curl http://localhost/mlflow/health`
2. Review server logs: Contact your MLOps team
3. Verify network connectivity: `ping ${SERVER_IP}`
4. Check MLflow version compatibility: `pip show mlflow`
