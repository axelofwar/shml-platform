# MLflow Governance & Validation: SOTA Research Analysis

**Date:** December 6, 2025  
**Version:** 1.0  
**Purpose:** Comprehensive analysis of state-of-the-art MLflow governance patterns for experiment naming enforcement, model registry governance, and validation mechanisms

---

## Executive Summary

This document analyzes production-grade MLflow governance approaches from major cloud providers (Databricks, AWS SageMaker, Azure ML) and open-source implementations. It provides actionable recommendations for implementing governance in our Ray + MLflow + Traefik + FusionAuth platform.

**Key Finding:** No major provider enforces strict governance at the MLflow API level. Instead, they implement:
1. **Permission-based access control** (who can create experiments)
2. **Naming conventions through UI/client wrappers** (not server-side enforcement)
3. **Post-creation governance** (tags, metadata, cleanup policies)
4. **Workspace-level organization** (experiment namespaces, not validation)

---

## 1. Comparison Table of Governance Approaches

| Provider | Experiment Naming | Model Registry | Dataset Registry | Enforcement Layer | Best For |
|----------|------------------|----------------|------------------|-------------------|----------|
| **Databricks Managed MLflow** | Workspace namespaces `/Users/{email}/` | Unity Catalog integration | Delta Lake + Auto-logging | UI + IAM permissions | Enterprise with Databricks |
| **AWS SageMaker + MLflow** | Tags + Experiment metadata | SageMaker Model Registry fallback | S3 paths + lineage | AWS IAM + Resource tags | AWS-native workflows |
| **Azure ML + MLflow** | Workspace isolation + Tags | AzureML Model Registry | Dataset artifacts + lineage | RBAC + Azure AD | Azure ecosystem |
| **Open Source MLflow** | None (DIY) | Native registry only | Manual artifact logging | Python decorators/wrappers | Self-hosted, custom needs |
| **MLflow Auth Plugin** | Permission checks only | Permission checks only | N/A | Flask middleware + DB | Access control, not validation |

---

## 2. Detailed Analysis by Provider

### 2.1 Databricks Managed MLflow

**Governance Philosophy:** Workspace-based isolation + Unity Catalog governance

**Experiment Naming:**
```python
# Databricks enforces workspace namespacing, NOT naming patterns
experiment_name = f"/Users/{user_email}/my-experiment"  # Auto-prefixed
mlflow.set_experiment(experiment_name)
```

**Pros:**
- ✅ Automatic user/workspace isolation
- ✅ Unity Catalog governance for models (schema enforcement, lineage)
- ✅ Built-in permissions at workspace level
- ✅ Tag-based organization (no regex enforcement)

**Cons:**
- ❌ No server-side naming validation (relies on UI guidance)
- ❌ Cannot prevent ad-hoc experiment creation
- ❌ Naming conventions enforced through documentation, not code

**Code Example:**
```python
# Databricks approach - workspace + tags
import mlflow
from mlflow.entities import Experiment

# Users create experiments in their workspace
mlflow.set_experiment("/Users/john.doe@company.com/churn-model")

# Tags provide governance metadata
mlflow.set_experiment_tags({
    "team": "data-science",
    "project": "customer-retention",
    "environment": "development",
    "cost-center": "engineering"
})
```

### 2.2 AWS SageMaker with MLflow

**Governance Philosophy:** AWS IAM + Resource tagging + SageMaker integration

**Experiment Organization:**
```python
# AWS uses tags for organization, not naming enforcement
import mlflow
import boto3

mlflow.set_tracking_uri("http://mlflow-alb.region.elb.amazonaws.com")

# Create experiment with AWS-style tags
experiment_id = mlflow.create_experiment(
    "customer-churn-prediction",
    tags={
        "aws:project": "churn-prediction",
        "aws:environment": "prod",
        "aws:cost-center": "12345",
        "sagemaker:pipeline-id": "pipeline-xyz"
    }
)
```

**Pros:**
- ✅ IAM-based access control (who can create experiments)
- ✅ CloudTrail audit logging
- ✅ SageMaker Model Registry as fallback
- ✅ Tag-based cost allocation

**Cons:**
- ❌ No naming pattern enforcement
- ❌ MLflow server is self-managed (Fargate/ECS)
- ❌ Requires custom wrapper for governance

**Model Registry Pattern:**
```python
# AWS forces SageMaker Model Registry for production
from sagemaker.model import Model

# Log to MLflow for experiments
mlflow.sklearn.log_model(model, "model")

# Register in SageMaker for production governance
sagemaker_model = Model(
    image_uri=container_uri,
    model_data=model_artifact_s3_uri,
    role=sagemaker_role,
    tags=[
        {"Key": "mlflow-run-id", "Value": run.info.run_id},
        {"Key": "model-type", "Value": "churn-classifier"}
    ]
)
```

### 2.3 Azure ML + MLflow

**Governance Philosophy:** Workspace isolation + RBAC + Azure AD integration

**Experiment Management:**
```python
# Azure ML workspace provides governance boundary
from azureml.core import Workspace, Experiment
import mlflow

# Connect to governed workspace
ws = Workspace.from_config()
mlflow.set_tracking_uri(ws.get_mlflow_tracking_uri())

# Experiments scoped to workspace
experiment = Experiment(workspace=ws, name="churn-prediction")
mlflow.set_experiment("churn-prediction")

# Tags for metadata (not validation)
mlflow.set_experiment_tags({
    "team": "ds-team",
    "compliance": "gdpr-compliant"
})
```

**Pros:**
- ✅ Azure AD integration (SSO + RBAC)
- ✅ Workspace-level isolation
- ✅ AzureML Model Registry integration
- ✅ Dataset lineage tracking

**Cons:**
- ❌ No naming convention enforcement
- ❌ Governance at workspace level, not experiment level
- ❌ Relies on Azure policies, not MLflow features

### 2.4 Open Source MLflow (Self-Hosted)

**Governance Reality:** No built-in governance - DIY required

**Current Capabilities:**
```python
# MLflow provides NO server-side validation
import mlflow

# This succeeds with ANY name (no validation)
mlflow.create_experiment("my random experiment!@#$")
mlflow.create_experiment("test")
mlflow.create_experiment("asdf")
```

**What MLflow DOES provide:**
- ✅ REST API (can be wrapped)
- ✅ Plugin system (request auth, deployment)
- ✅ Postgres backend (can add triggers)
- ✅ Python client (can be wrapped with decorators)

**What MLflow DOES NOT provide:**
- ❌ Naming validation hooks
- ❌ Pre-creation validation plugins
- ❌ Schema enforcement
- ❌ Required fields/tags

---

## 3. MLflow Plugin System Analysis

### 3.1 Available Plugin Types

```python
# MLflow official plugin entry points
PLUGIN_TYPES = {
    "mlflow.app": "Custom UI applications",
    "mlflow.app.client": "Custom client integrations",
    "mlflow.deployments": "Deployment targets",
    "mlflow.model_evaluator": "Custom evaluators",
    "mlflow.artifact_repository": "Artifact storage",
    "mlflow.run_context_provider": "Context providers",
    "mlflow.request_header_provider": "Request headers",
    "mlflow.request_auth_provider": "Authentication",  # THIS ONE
    "mlflow.tracking_store": "Custom tracking backend",
}
```

### 3.2 Request Auth Provider (Closest to Validation)

**Purpose:** Add authentication to MLflow client requests  
**Limitation:** Only handles authentication, NOT validation

```python
# mlflow/tracking/request_auth/abstract_request_auth_provider.py
from mlflow.tracking.request_auth.abstract_request_auth_provider import (
    RequestAuthProvider
)

class CustomAuthProvider(RequestAuthProvider):
    """Can add auth headers, CANNOT validate request body"""

    def get_name(self):
        return "custom_auth"

    def get_auth(self):
        return CustomAuth()

class CustomAuth:
    def __call__(self, request):
        # Can modify headers
        request.headers["Authorization"] = f"Bearer {token}"
        # CANNOT validate request body or prevent request
        return request
```

**Key Limitation:** Request auth plugins run on the CLIENT side, not server side. They cannot prevent requests from reaching the MLflow server.

### 3.3 MLflow Server Auth Plugin (Server-Side)

**File:** `mlflow/server/auth/__init__.py`

**What it provides:**
```python
# Permission-based access control
BEFORE_REQUEST_HANDLERS = {
    GetExperiment: validate_can_read_experiment,
    CreateExperiment: validate_can_update_experiment,  # Permission check
    DeleteExperiment: validate_can_delete_experiment,
    # ... more handlers
}

def validate_can_update_experiment():
    """Checks UPDATE permission on experiment"""
    return _get_permission_from_experiment_id().can_update
```

**What it DOES NOT provide:**
- ❌ Naming pattern validation
- ❌ Required fields enforcement
- ❌ Metadata schema validation
- ❌ Custom business logic hooks

**Architecture:**
```
Client Request → Flask Middleware → Auth Check (Permission) → MLflow Handler → DB
                                          ↑
                                    Only checks: Can user access?
                                    Does NOT check: Is name valid?
```

---

## 4. Implementation Patterns from Industry

### 4.1 Netflix Pattern (Inferred from Open Source Contributions)

**Approach:** Client-side wrappers + Centralized Python library

```python
# netflix_mlflow_wrapper.py (conceptual)
import mlflow
from typing import Optional
import re

class NetflixMLflow:
    """Enforced client-side governance"""

    EXPERIMENT_PATTERN = re.compile(r"^[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+$")
    # Format: team/project/experiment

    @classmethod
    def create_experiment(cls, team: str, project: str, name: str,
                         tags: Optional[dict] = None):
        """Enforced naming: {team}/{project}/{name}"""

        # Validate components
        if not all(c.islower() or c.isdigit() or c == '-' for c in team):
            raise ValueError(f"Invalid team name: {team}")

        experiment_name = f"{team}/{project}/{name}"

        # Enforce required tags
        required_tags = {
            "team": team,
            "project": project,
            "created_by": get_user(),
            "cost_center": get_cost_center(team),
        }
        required_tags.update(tags or {})

        # Create with validation
        return mlflow.create_experiment(
            experiment_name,
            tags=required_tags
        )

# Usage
NetflixMLflow.create_experiment(
    team="recommendations",
    project="personalization",
    name="ranking-model-v2"
)
# Creates: recommendations/personalization/ranking-model-v2
```

**Enforcement:**
- ✅ Company Python package (required dependency)
- ✅ CI/CD checks (fails if raw mlflow used)
- ✅ Documentation + training
- ❌ Can be bypassed by direct API calls

### 4.2 Uber Pattern (Inferred from ML Platform talks)

**Approach:** API Gateway + Validation Layer

```python
# uber_mlflow_gateway.py (conceptual)
from flask import Flask, request, jsonify
import mlflow
import requests

app = Flask(__name__)

# Uber's validation rules
EXPERIMENT_RULES = {
    "pattern": r"^[a-z0-9_-]{3,50}$",
    "required_tags": ["team", "owner", "pagerduty"],
    "forbidden_prefixes": ["test-", "tmp-"],
}

@app.route("/api/2.0/mlflow/experiments/create", methods=["POST"])
def create_experiment_with_validation():
    """Validation gateway in front of MLflow"""

    data = request.get_json()
    experiment_name = data.get("name")
    tags = {tag["key"]: tag["value"] for tag in data.get("tags", [])}

    # Validation 1: Name pattern
    if not re.match(EXPERIMENT_RULES["pattern"], experiment_name):
        return jsonify({
            "error": "Invalid experiment name format",
            "expected": "lowercase, numbers, underscores, hyphens (3-50 chars)"
        }), 400

    # Validation 2: Required tags
    missing_tags = set(EXPERIMENT_RULES["required_tags"]) - set(tags.keys())
    if missing_tags:
        return jsonify({
            "error": f"Missing required tags: {missing_tags}"
        }), 400

    # Validation 3: Forbidden patterns
    for prefix in EXPERIMENT_RULES["forbidden_prefixes"]:
        if experiment_name.startswith(prefix):
            return jsonify({
                "error": f"Experiment names cannot start with {prefix}"
            }), 400

    # Forward to MLflow server
    mlflow_response = requests.post(
        f"{MLFLOW_SERVER}/api/2.0/mlflow/experiments/create",
        json=data
    )

    return jsonify(mlflow_response.json()), mlflow_response.status_code

# Similar validation for other endpoints...
```

**Architecture:**
```
Client → Uber Gateway (Validation) → MLflow Server → Postgres
              ↓
         Validates:
         - Naming patterns
         - Required metadata
         - Business rules
```

**Pros:**
- ✅ Server-side enforcement (cannot be bypassed)
- ✅ Centralized validation logic
- ✅ Works with any MLflow client
- ❌ Requires maintaining gateway code
- ❌ Additional infrastructure

### 4.3 Airbnb Pattern (Inferred from Blog Posts)

**Approach:** Python decorators + Policy-as-Code

```python
# airbnb_mlflow_governance.py (conceptual)
import mlflow
from functools import wraps
import yaml

# Load governance policies
with open("mlflow_policies.yaml") as f:
    POLICIES = yaml.safe_load(f)

def enforce_governance(func):
    """Decorator to enforce governance on MLflow operations"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Extract operation details
        operation = func.__name__

        if operation == "create_experiment":
            name = args[0] if args else kwargs.get("name")
            tags = kwargs.get("tags", {})

            # Policy check
            policy = POLICIES["experiments"]["creation"]

            # Check naming pattern
            if not re.match(policy["name_pattern"], name):
                raise ValueError(
                    f"Experiment name must match: {policy['name_pattern']}"
                )

            # Check required tags
            missing = set(policy["required_tags"]) - set(tags.keys())
            if missing:
                raise ValueError(f"Missing required tags: {missing}")

            # Check team authorization
            user_team = get_user_team()
            if user_team not in policy["allowed_teams"]:
                raise PermissionError(
                    f"Team {user_team} not authorized to create experiments"
                )

        return func(*args, **kwargs)

    return wrapper

# Monkey patch MLflow
mlflow.create_experiment = enforce_governance(mlflow.create_experiment)
mlflow.set_experiment = enforce_governance(mlflow.set_experiment)
```

**Policy File Example:**
```yaml
# mlflow_policies.yaml
experiments:
  creation:
    name_pattern: "^[a-z0-9-]+$"
    max_length: 50
    required_tags:
      - team
      - owner
      - environment
      - cost-center
    allowed_teams:
      - data-science
      - ml-eng
      - research

models:
  registration:
    name_pattern: "^[a-zA-Z][a-zA-Z0-9_-]*$"
    required_tags:
      - model-type
      - training-date
      - validation-metric
```

---

## 5. Database-Level Governance (PostgreSQL)

### 5.1 Experiment Naming Constraints

```sql
-- Add check constraint to experiments table
ALTER TABLE experiments
ADD CONSTRAINT valid_experiment_name
CHECK (name ~ '^[a-z0-9][a-z0-9-_/]{2,99}$');

-- Add trigger for required tags
CREATE OR REPLACE FUNCTION validate_experiment_tags()
RETURNS TRIGGER AS $$
BEGIN
    -- Check if required tags exist
    IF NOT EXISTS (
        SELECT 1 FROM experiment_tags
        WHERE experiment_id = NEW.experiment_id
        AND key IN ('team', 'owner', 'environment')
        GROUP BY experiment_id
        HAVING COUNT(DISTINCT key) = 3
    ) THEN
        RAISE EXCEPTION 'Experiment must have team, owner, and environment tags';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_experiment_tags
AFTER INSERT ON experiments
FOR EACH ROW EXECUTE FUNCTION validate_experiment_tags();
```

**Pros:**
- ✅ Cannot be bypassed (database enforced)
- ✅ Works regardless of client
- ✅ Provides referential integrity

**Cons:**
- ❌ Poor user experience (error after creation attempt)
- ❌ Hard to provide helpful error messages
- ❌ Difficult to maintain/update rules
- ❌ Breaks MLflow schema upgrade path

### 5.2 Model Registry Governance

```sql
-- Force model registry usage
CREATE OR REPLACE FUNCTION prevent_loose_models()
RETURNS TRIGGER AS $$
BEGIN
    -- Check if artifact is a model
    IF NEW.artifact_uri LIKE '%/artifacts/model%' THEN
        -- Check if model is registered
        IF NOT EXISTS (
            SELECT 1 FROM model_versions mv
            JOIN registered_models rm ON mv.name = rm.name
            WHERE mv.run_id = NEW.run_uuid
        ) THEN
            RAISE EXCEPTION 'Models must be registered before saving artifacts';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_model_registry
BEFORE INSERT ON artifacts
FOR EACH ROW EXECUTE FUNCTION prevent_loose_models();
```

---

## 6. Recommendations for Our Platform

### 6.1 Architecture Decision

**Recommended Approach:** Multi-Layer Governance

```
Layer 1: Python Client Wrapper (Optional, user-friendly)
    ↓
Layer 2: Traefik Middleware (Server-side validation)
    ↓
Layer 3: MLflow Server (Permission checks via FusionAuth)
    ↓
Layer 4: PostgreSQL (Constraints for data integrity)
```

### 6.2 Implementation Priority

#### Phase 1: Quick Wins (1-2 weeks)

**1. Python Client Wrapper**
```python
# shml_mlflow/governance.py
import mlflow
import os
import re
from typing import Optional, Dict

class GoverancedMLflow:
    """Governed MLflow client for SHML platform"""

    EXPERIMENT_PATTERN = re.compile(
        r"^[a-z0-9]([a-z0-9-_/]{0,98}[a-z0-9])?$"
    )

    REQUIRED_TAGS = ["team", "owner", "project"]

    @classmethod
    def validate_experiment_name(cls, name: str) -> None:
        """Validate experiment naming convention"""
        if not cls.EXPERIMENT_PATTERN.match(name):
            raise ValueError(
                f"Invalid experiment name: '{name}'\n"
                f"Must match: lowercase alphanumeric, hyphens, underscores, slashes\n"
                f"Length: 1-100 characters\n"
                f"Example: team-ml/churn-prediction/model-v1"
            )

    @classmethod
    def validate_tags(cls, tags: Dict[str, str]) -> None:
        """Validate required tags"""
        missing = set(cls.REQUIRED_TAGS) - set(tags.keys())
        if missing:
            raise ValueError(
                f"Missing required tags: {missing}\n"
                f"Required: {cls.REQUIRED_TAGS}"
            )

    @classmethod
    def create_experiment(
        cls,
        name: str,
        artifact_location: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None
    ) -> str:
        """Create experiment with governance"""

        # Validate name
        cls.validate_experiment_name(name)

        # Auto-add metadata
        governed_tags = {
            "team": tags.get("team", ""),
            "owner": tags.get("owner", os.getenv("USER", "unknown")),
            "project": tags.get("project", ""),
            "created_at": str(datetime.now()),
            "created_by": os.getenv("USER", "unknown"),
        }
        governed_tags.update(tags or {})

        # Validate required tags
        cls.validate_tags(governed_tags)

        # Create experiment
        exp_id = mlflow.create_experiment(
            name=name,
            artifact_location=artifact_location,
            tags=governed_tags
        )

        return exp_id

    @classmethod
    def log_model(cls, *args, **kwargs):
        """Force model registry usage"""
        if "registered_model_name" not in kwargs:
            raise ValueError(
                "Must provide 'registered_model_name' parameter\n"
                "Models must be registered to the model registry"
            )

        return mlflow.log_model(*args, **kwargs)

# Usage
from shml_mlflow import GoverancedMLflow as ml

exp_id = ml.create_experiment(
    name="data-science/churn-prediction/lgbm-v1",
    tags={
        "team": "data-science",
        "owner": "john.doe",
        "project": "customer-retention"
    }
)
```

**2. Environment Setup Script**
```bash
# scripts/setup_mlflow_governance.sh
#!/bin/bash

# Install governed MLflow wrapper
pip install shml-mlflow-governance

# Monkey patch MLflow in environment
export MLFLOW_ENFORCE_GOVERNANCE=true

# Add to ~/.bashrc or ~/.zshrc
cat >> ~/.bashrc << 'EOF'
# SHML MLflow Governance
export MLFLOW_TRACKING_URI=http://localhost:8080
export MLFLOW_ENFORCE_GOVERNANCE=true
alias mlflow='python -m shml_mlflow.cli'
EOF
```

#### Phase 2: Server-Side Validation (2-4 weeks)

**Traefik Middleware for Request Validation**

```go
// traefik-plugins/mlflow-governance/main.go
package mlflow_governance

import (
    "context"
    "encoding/json"
    "fmt"
    "net/http"
    "regexp"
)

// Config for the middleware
type Config struct {
    ExperimentPattern string   `json:"experiment_pattern"`
    RequiredTags      []string `json:"required_tags"`
}

// CreateConfig creates the default config
func CreateConfig() *Config {
    return &Config{
        ExperimentPattern: "^[a-z0-9][a-z0-9-_/]{0,98}[a-z0-9]$",
        RequiredTags:      []string{"team", "owner", "project"},
    }
}

// MLflowGovernance middleware
type MLflowGovernance struct {
    next    http.Handler
    config  *Config
    pattern *regexp.Regexp
}

// New creates a new MLflowGovernance middleware
func New(ctx context.Context, next http.Handler, config *Config, name string) (http.Handler, error) {
    pattern, err := regexp.Compile(config.ExperimentPattern)
    if err != nil {
        return nil, fmt.Errorf("invalid experiment pattern: %w", err)
    }

    return &MLflowGovernance{
        next:    next,
        config:  config,
        pattern: pattern,
    }, nil
}

func (m *MLflowGovernance) ServeHTTP(rw http.ResponseWriter, req *http.Request) {
    // Only validate create experiment requests
    if req.URL.Path == "/api/2.0/mlflow/experiments/create" && req.Method == "POST" {
        if err := m.validateExperiment(req); err != nil {
            http.Error(rw, err.Error(), http.StatusBadRequest)
            return
        }
    }

    m.next.ServeHTTP(rw, req)
}

func (m *MLflowGovernance) validateExperiment(req *http.Request) error {
    var body map[string]interface{}
    if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
        return fmt.Errorf("invalid request body: %w", err)
    }

    // Validate experiment name
    name, ok := body["name"].(string)
    if !ok || name == "" {
        return fmt.Errorf("experiment name is required")
    }

    if !m.pattern.MatchString(name) {
        return fmt.Errorf("invalid experiment name: must match %s", m.config.ExperimentPattern)
    }

    // Validate required tags
    tags, ok := body["tags"].([]interface{})
    if !ok {
        tags = []interface{}{}
    }

    tagKeys := make(map[string]bool)
    for _, tag := range tags {
        tagMap, ok := tag.(map[string]interface{})
        if !ok {
            continue
        }
        key, ok := tagMap["key"].(string)
        if ok {
            tagKeys[key] = true
        }
    }

    for _, required := range m.config.RequiredTags {
        if !tagKeys[required] {
            return fmt.Errorf("missing required tag: %s", required)
        }
    }

    return nil
}
```

**Traefik Configuration:**
```yaml
# traefik/dynamic/mlflow-middleware.yml
http:
  middlewares:
    mlflow-governance:
      plugin:
        mlflow-governance:
          experiment_pattern: "^[a-z0-9][a-z0-9-_/]{0,98}[a-z0-9]$"
          required_tags:
            - team
            - owner
            - project

  routers:
    mlflow-api:
      rule: "PathPrefix(`/api/2.0/mlflow`)"
      service: mlflow-server
      middlewares:
        - mlflow-governance  # Apply governance middleware
        - authentik-auth     # Apply authentication
```

#### Phase 3: Long-Term Solutions (4-8 weeks)

**1. Custom MLflow Request Hook Plugin**

```python
# shml_platform/mlflow_hooks/validation_plugin.py
"""
MLflow request validation plugin
Register via entry point in setup.py
"""

from mlflow.tracking.request_header_provider import RequestHeaderProvider
from mlflow.tracking.context.abstract_context import RunContextProvider
import os

class GovernanceContextProvider(RunContextProvider):
    """Inject governance metadata into runs"""

    def in_context(self):
        return os.getenv("MLFLOW_ENFORCE_GOVERNANCE") == "true"

    def tags(self):
        """Auto-inject governance tags"""
        return {
            "governance.enforced": "true",
            "governance.version": "1.0",
            "created_by": os.getenv("USER", "unknown"),
            "team": os.getenv("MLFLOW_TEAM", ""),
        }

# setup.py entry point
entry_points={
    "mlflow.run_context_provider": [
        "governance=shml_platform.mlflow_hooks.validation_plugin:GovernanceContextProvider"
    ]
}
```

**2. Dataset Registry Enforcement**

```python
# shml_platform/mlflow_hooks/dataset_enforcement.py
import mlflow
from mlflow.entities import Dataset
from functools import wraps

def enforce_dataset_registration(func):
    """Decorator to enforce dataset registration"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Check if dataset parameter exists
        if "X" in kwargs or len(args) > 0:
            # Force dataset registration
            data = kwargs.get("X", args[0] if args else None)

            if data is not None:
                # Create dataset if not already registered
                dataset = mlflow.data.from_numpy(
                    data,
                    source="training_data",
                    name=f"dataset_{mlflow.active_run().info.run_id}"
                )
                mlflow.log_input(dataset, context="training")

        return func(*args, **kwargs)

    return wrapper

# Monkey patch scikit-learn
from sklearn.linear_model import LogisticRegression
LogisticRegression.fit = enforce_dataset_registration(LogisticRegression.fit)
```

### 6.3 Complete Integration Example

```python
# training_script.py with full governance
from shml_mlflow import GoverancedMLflow as ml
import mlflow
from sklearn.ensemble import RandomForestClassifier
import pandas as pd

# 1. Create governed experiment
exp_id = ml.create_experiment(
    name="data-science/churn-prediction/random-forest-v2",
    tags={
        "team": "data-science",
        "owner": "john.doe@company.com",
        "project": "customer-retention",
        "cost-center": "engineering",
        "environment": "development"
    }
)

mlflow.set_experiment(experiment_id=exp_id)

# 2. Start run with governance
with mlflow.start_run(run_name="rf-experiment-001"):

    # 3. Log dataset (enforced registration)
    train_df = pd.read_csv("train.csv")
    dataset = mlflow.data.from_pandas(
        train_df,
        source="s3://data-bucket/churn/train.csv",
        name="churn-training-data-v1"
    )
    mlflow.log_input(dataset, context="training")

    # 4. Train model
    model = RandomForestClassifier(n_estimators=100)
    model.fit(train_df.drop("target", axis=1), train_df["target"])

    # 5. Log model with registry enforcement
    mlflow.sklearn.log_model(
        model,
        artifact_path="model",
        registered_model_name="churn_predictor_rf",  # Required
        signature=mlflow.models.infer_signature(train_df.drop("target", axis=1), model.predict(train_df.drop("target", axis=1))),
        input_example=train_df.drop("target", axis=1).head(3)
    )

    # 6. Log metrics
    mlflow.log_metrics({
        "accuracy": 0.92,
        "precision": 0.89,
        "recall": 0.91
    })
```

---

## 7. Pros/Cons Summary

| Approach | Pros | Cons | Recommended For |
|----------|------|------|-----------------|
| **Python Client Wrapper** | ✅ Easy to implement<br>✅ Good UX<br>✅ No server changes | ❌ Can be bypassed<br>❌ Client-side only | Development environments |
| **Traefik Middleware** | ✅ Server-side<br>✅ Cannot bypass<br>✅ Works with all clients | ❌ Requires Go plugin<br>❌ Maintenance overhead | Production enforcement |
| **MLflow Auth Plugin** | ✅ Native MLflow<br>✅ Permission-based | ❌ No validation support<br>❌ Limited scope | Access control only |
| **Database Constraints** | ✅ Cannot bypass<br>✅ Data integrity | ❌ Poor UX<br>❌ Hard to maintain<br>❌ Breaks upgrades | Last resort / critical constraints |
| **API Gateway** | ✅ Centralized<br>✅ Flexible rules | ❌ Extra infrastructure<br>❌ Latency | Enterprise scale |

---

## 8. Next Steps

1. **Immediate (This Week):**
   - Create Python wrapper package (`shml-mlflow-governance`)
   - Document naming conventions in `INTEGRATION_GUIDE.md`
   - Add environment setup script

2. **Short-Term (2 Weeks):**
   - Develop Traefik middleware plugin
   - Test with FusionAuth integration
   - Create governance policy YAML

3. **Medium-Term (1 Month):**
   - Implement dataset registry enforcement
   - Add model registry required fields
   - Create governance dashboard

4. **Long-Term (3 Months):**
   - Custom MLflow plugin for advanced hooks
   - PostgreSQL triggers for critical constraints
   - Automated compliance reporting

---

## 9. References

- [MLflow Plugins Documentation](https://mlflow.org/docs/latest/plugins.html)
- [Databricks Unity Catalog](https://docs.databricks.com/en/mlflow/index.html)
- [AWS SageMaker + MLflow](https://aws.amazon.com/blogs/machine-learning/managing-your-machine-learning-lifecycle-with-mlflow-and-amazon-sagemaker/)
- [Azure ML MLflow Integration](https://learn.microsoft.com/en-us/azure/machine-learning/concept-mlflow)
- [MLflow Auth Server Code](https://github.com/mlflow/mlflow/blob/master/mlflow/server/auth/__init__.py)
- [Traefik Middleware Development](https://doc.traefik.io/traefik/plugins/overview/)

---

**Document Status:** Complete  
**Last Updated:** December 6, 2025  
**Next Review:** January 6, 2026  
**Owner:** ML Platform Team
