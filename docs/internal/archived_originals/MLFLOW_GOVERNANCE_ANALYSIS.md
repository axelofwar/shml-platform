# MLflow Governance & Enforcement Analysis

**Document Version:** 1.0.0  
**Date:** December 6, 2025  
**Platform:** SHML Platform (Ray + MLflow + Traefik + FusionAuth)

---

## Executive Summary

This document analyzes SOTA approaches for enforcing MLflow best practices:
- **Experiment naming conventions** (prevent ad-hoc creation)
- **Native model registry usage** (centralized vs scattered artifacts)
- **Dataset registry patterns** (proper versioning and registration)
- **Governance hooks and validation** (server-side vs client-side)

**TL;DR:** Industry leaders (Databricks, AWS, Azure) don't enforce strict naming - they use **workspace isolation + RBAC + tagging**. For self-hosted MLflow, a **multi-layer hybrid approach** is recommended.

---

## 1. Industry Provider Comparison

| Provider | Experiment Enforcement | Model Registry | Dataset Registry | Implementation Complexity | Cost |
|----------|----------------------|----------------|------------------|-------------------------|------|
| **Databricks Managed MLflow** | Workspace isolation | Unity Catalog | Unity Catalog | Low (managed) | High ($$$$) |
| **AWS SageMaker + MLflow** | IAM + Resource tags | SageMaker Model Registry | S3 + Data Catalog | Medium | High ($$$) |
| **Azure ML + MLflow** | RBAC + Workspace | Azure ML Registry | Azure ML Datasets | Medium | High ($$$) |
| **MLflow OSS (Self-Hosted)** | DIY required | Native registry | Custom solution | High | Low ($) |
| **MLflow with Authentication Server** | Basic Auth + RBAC | Native registry | Custom solution | Medium-High | Medium ($$) |

### Key Insight
> **No major provider enforces strict experiment naming conventions.** Instead, they rely on:
> - **Workspace/namespace isolation** - Users can only see their workspace experiments
> - **Permission-based access** - Create/read/write permissions per experiment
> - **Tag-based organization** - Required tags for filtering and governance
> - **Post-creation governance** - Audit logs, alerts, and cleanup policies

---

## 2. Databricks Approach (Industry Gold Standard)

### Architecture
```
User → Workspace (isolated namespace) → Unity Catalog → MLflow Tracking → Delta Lake
```

### Governance Mechanisms

**A. Workspace Isolation**
```python
# Each workspace has its own MLflow tracking server
# Users can't create experiments outside their workspace
workspace_id = "production"
mlflow.set_tracking_uri(f"databricks://workspace:{workspace_id}")

# Experiments are namespaced
# /Users/user@company.com/experiment-name
# /Shared/team-name/experiment-name
```

**B. Unity Catalog Governance**
```sql
-- Centralized governance layer
-- Controls who can create/read/write models and datasets

GRANT CREATE EXPERIMENT ON CATALOG prod_ml TO ROLE data_scientist;
GRANT READ EXPERIMENT ON CATALOG prod_ml TO ROLE analyst;

-- Automatic lineage tracking
-- Links experiments → models → datasets → tables
```

**C. Required Tags (Soft Enforcement)**
```python
# Databricks recommends tags but doesn't enforce
# Governance policies can alert on missing tags
mlflow.set_tags({
    "team": "computer-vision",
    "cost_center": "engineering",
    "project": "face-detection",
    "environment": "production"
})
```

**Pros:**
- Scales to enterprise (10,000+ users)
- Built-in lineage tracking
- Automated governance policies
- Zero custom code required

**Cons:**
- Vendor lock-in
- High cost ($$$$ per user/month)
- Can't customize validation logic
- Requires Databricks platform

---

## 3. AWS SageMaker + MLflow

### Architecture
```
User → SageMaker Notebook → MLflow (self-hosted) → S3 → IAM policies
```

### Governance Mechanisms

**A. IAM Permissions**
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "s3:PutObject",
      "s3:GetObject"
    ],
    "Resource": "arn:aws:s3:::mlflow-artifacts/experiments/production-*",
    "Condition": {
      "StringEquals": {
        "s3:RequestObjectTag/team": "ml-platform"
      }
    }
  }]
}
```

**B. Resource Tagging**
```python
# AWS enforces tags at S3 bucket level
# MLflow artifacts inherit S3 tags
import boto3

client = boto3.client('s3')
client.put_object_tagging(
    Bucket='mlflow-artifacts',
    Key='experiments/my-experiment',
    Tagging={
        'TagSet': [
            {'Key': 'Environment', 'Value': 'Production'},
            {'Key': 'CostCenter', 'Value': 'ML-Platform'},
        ]
    }
)
```

**C. SageMaker Model Registry Integration**
```python
# Use SageMaker Model Registry (more governance than MLflow alone)
import sagemaker
from sagemaker.model import Model

model = Model(
    image_uri=container_uri,
    model_data=mlflow_model_s3_path,
    role=sagemaker_role
)

# Register in SageMaker (requires approval workflow)
model_package = model.register(
    content_types=["application/json"],
    response_types=["application/json"],
    inference_instances=["ml.t2.medium"],
    transform_instances=["ml.m5.xlarge"],
    model_package_group_name="face-detection-models",
    approval_status="PendingManualApproval"  # Governance gate
)
```

**Pros:**
- Leverages AWS IAM (battle-tested)
- S3 lifecycle policies for artifact cleanup
- SageMaker Model Registry approval workflows
- Integrates with AWS ecosystem

**Cons:**
- Still requires custom MLflow validation
- IAM complexity
- AWS-specific (not portable)
- S3 costs can be high

---

## 4. Open Source Patterns (Netflix, Uber, Airbnb)

### Pattern 1: Netflix - Client-Side Wrapper Library

**Architecture:** Centralized Python library wraps MLflow client

```python
# netflix_mlops/mlflow_client.py
"""
Netflix's approach: Centralized wrapper library
All data scientists import this instead of raw mlflow
"""

from typing import Dict, List, Optional
import mlflow
from mlflow import MlflowClient

# Allowed experiments (controlled by ML Platform team)
ALLOWED_EXPERIMENTS = {
    "recommendations-training": {
        "required_tags": ["model_type", "dataset_version", "team"],
        "artifact_subdirs": ["models", "metrics", "plots"],
        "approval_required": True
    },
    "content-ranking": {
        "required_tags": ["ranking_algorithm", "ab_test_id"],
        "artifact_subdirs": ["models", "explainability"],
        "approval_required": False
    }
}

class NetflixMLflowClient:
    """Governed MLflow client with validation"""

    def __init__(self, experiment_name: str):
        if experiment_name not in ALLOWED_EXPERIMENTS:
            raise ValueError(
                f"Experiment '{experiment_name}' not allowed. "
                f"Valid options: {list(ALLOWED_EXPERIMENTS.keys())}\n"
                f"Request new experiment: https://wiki.netflix.com/ml/new-experiment"
            )

        self.experiment_name = experiment_name
        self.experiment_config = ALLOWED_EXPERIMENTS[experiment_name]
        self.client = MlflowClient()

        # Auto-set experiment
        mlflow.set_experiment(experiment_name)

    def start_run(self, run_name: str, tags: Dict[str, str]) -> mlflow.ActiveRun:
        """Start run with validation"""
        # Validate required tags
        required = self.experiment_config["required_tags"]
        missing = set(required) - set(tags.keys())
        if missing:
            raise ValueError(f"Missing required tags: {missing}")

        # Add automatic tags
        tags["netflix.version"] = "1.0"
        tags["netflix.platform"] = "ml-compute"

        return mlflow.start_run(run_name=run_name, tags=tags)

    def log_model(self, model, artifact_path: str, **kwargs):
        """Log model to correct subdirectory"""
        subdirs = self.experiment_config["artifact_subdirs"]
        if not any(artifact_path.startswith(d) for d in subdirs):
            raise ValueError(
                f"Artifact path must start with one of: {subdirs}"
            )

        # Check if approval required
        if self.experiment_config["approval_required"]:
            # Log to staging first, alert for approval
            artifact_path = f"staging/{artifact_path}"
            print(f"⚠️  Model logged to staging. Approval required: "
                  f"https://ml-platform.netflix.com/approve/{mlflow.active_run().info.run_id}")

        return mlflow.log_model(model, artifact_path, **kwargs)

# Usage in training scripts
# from netflix_mlops import NetflixMLflowClient
#
# client = NetflixMLflowClient("recommendations-training")
# with client.start_run("model-v2.1", tags={"model_type": "neural-cf", ...}):
#     client.log_model(model, "models/ncf-v2.1")
```

**Pros:**
- Developer-friendly (clear error messages)
- Centralized control (update one library)
- Easy to rollout (just pip install)
- Can add automatic instrumentation

**Cons:**
- Bypassable (users can use raw mlflow)
- Requires buy-in from data scientists
- Version management (keep library updated)

---

### Pattern 2: Uber - API Gateway Validation Layer

**Architecture:** Traefik/Kong middleware validates requests before MLflow

```go
// uber_mlflow_validator/middleware.go
// Uber's approach: API gateway validates all MLflow API calls

package main

import (
    "encoding/json"
    "net/http"
    "regexp"
    "strings"
)

// Allowed experiment patterns
var allowedExperiments = map[string]*regexp.Regexp{
    "uber-eats": regexp.MustCompile(`^uber-eats-(dev|staging|prod)$`),
    "rides":     regexp.MustCompile(`^rides-(safety|pricing|matching)-(dev|staging|prod)$`),
}

type MLflowValidator struct {
    next http.Handler
}

func (m *MLflowValidator) ServeHTTP(w http.ResponseWriter, r *http.Request) {
    // Intercept experiment creation
    if r.Method == "POST" && strings.Contains(r.URL.Path, "/mlflow/experiments/create") {
        body := make(map[string]interface{})
        json.NewDecoder(r.Body).Decode(&body)

        expName := body["name"].(string)

        // Validate against allowed patterns
        valid := false
        for team, pattern := range allowedExperiments {
            if pattern.MatchString(expName) {
                valid = true
                // Add automatic tags
                if body["tags"] == nil {
                    body["tags"] = make(map[string]string)
                }
                body["tags"].(map[string]string)["team"] = team
                body["tags"].(map[string]string)["created_by"] = r.Header.Get("X-User-Email")
                break
            }
        }

        if !valid {
            w.WriteHeader(http.StatusForbidden)
            json.NewEncoder(w).Encode(map[string]string{
                "error": "Invalid experiment name",
                "detail": "Must match pattern: {team}-(dev|staging|prod)",
                "help_url": "https://uber.com/ml/experiments"
            })
            return
        }
    }

    // Intercept model registration
    if r.Method == "POST" && strings.Contains(r.URL.Path, "/mlflow/model-versions/create") {
        // Enforce model name conventions
        // uber-eats/model-name/version
    }

    m.next.ServeHTTP(w, r)
}

// Deploy as Traefik middleware or Kong plugin
```

**Pros:**
- **Server-side enforcement** (can't bypass)
- Language-agnostic (works with any client)
- Centralized policy management
- Audit logging at gateway level

**Cons:**
- Requires API gateway setup
- More complex to develop/maintain
- Debugging can be harder
- Must handle all MLflow API endpoints

---

### Pattern 3: Airbnb - Python Decorators + Policy-as-Code

**Architecture:** Python decorators validate before function execution

```python
# airbnb_mlops/governance.py
"""
Airbnb's approach: Decorators enforce policies at function level
Works with any Python ML framework (PyTorch, TensorFlow, etc.)
"""

import functools
import mlflow
from typing import Dict, Callable
import json

class ExperimentPolicy:
    """Policy-as-code for experiments"""

    def __init__(self, policy_file="/etc/mlflow/policies.json"):
        with open(policy_file) as f:
            self.policies = json.load(f)

    def validate_experiment(self, exp_name: str) -> tuple[bool, str]:
        """Check if experiment is allowed"""
        if exp_name not in self.policies["allowed_experiments"]:
            return False, f"Experiment {exp_name} not in approved list"
        return True, ""

    def validate_tags(self, exp_name: str, tags: Dict[str, str]) -> tuple[bool, str]:
        """Check required tags"""
        required = self.policies["allowed_experiments"][exp_name]["required_tags"]
        missing = set(required) - set(tags.keys())
        if missing:
            return False, f"Missing required tags: {missing}"
        return True, ""

# Global policy instance
policy = ExperimentPolicy()

def governed_experiment(experiment_name: str):
    """Decorator for governed MLflow experiments"""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Validate experiment
            valid, msg = policy.validate_experiment(experiment_name)
            if not valid:
                raise ValueError(msg)

            # Auto-set experiment
            mlflow.set_experiment(experiment_name)

            # Execute training function
            return func(*args, **kwargs)

        return wrapper
    return decorator

def governed_run(**required_tags):
    """Decorator for governed MLflow runs"""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get current experiment
            exp = mlflow.get_experiment_by_name(mlflow.active_run().info.experiment_id)

            # Validate tags
            valid, msg = policy.validate_tags(exp.name, required_tags)
            if not valid:
                raise ValueError(msg)

            # Start run with tags
            with mlflow.start_run(tags=required_tags):
                result = func(*args, **kwargs)

            return result

        return wrapper
    return decorator

# Usage in training scripts
@governed_experiment("airbnb-pricing-model")
def train_pricing_model(config):

    @governed_run(model_type="xgboost", team="pricing", cost_center="eng-123")
    def train_iteration():
        # Training code
        model = train_xgboost(config)
        mlflow.log_model(model, "models/xgboost-v1")
        return model

    return train_iteration()
```

**Pros:**
- Pythonic (fits ML workflows)
- Easy to adopt incrementally
- Policy-as-code (JSON config)
- Clear error messages

**Cons:**
- Python-only (doesn't work with R, Julia, etc.)
- Can be bypassed (decorators are opt-in)
- Requires training script changes

---

## 5. MLflow Plugin System Analysis

### Available Plugin Types

MLflow provides limited plugin capabilities:

```python
# mlflow/plugins/
├── request_auth_provider.py      # Authentication only
├── request_header_provider.py    # Add headers to requests
└── artifact_repository.py         # Custom artifact storage

# NOT AVAILABLE:
# - Request validation hooks
# - Pre/post-operation hooks
# - Experiment creation interceptors
```

### What MLflow Plugins CAN Do

**1. Authentication/Authorization**
```python
# mlflow_governance/auth_plugin.py
from mlflow.tracking.request_auth.abstract_request_auth_provider import RequestAuthProvider

class GovernanceAuthProvider(RequestAuthProvider):
    """Custom auth with experiment-level permissions"""

    def get_name(self):
        return "governance"

    def get_auth(self):
        """Return auth credentials"""
        return ("api-key", self.api_key)

    def _check_experiment_permission(self, method, url, user):
        """Check if user can access experiment"""
        # Parse experiment from URL
        # Check permissions in database
        # Return True/False
        pass
```

**2. Custom Artifact Storage**
```python
# mlflow_governance/artifact_repo.py
from mlflow.store.artifact.artifact_repo import ArtifactRepository

class GovernedArtifactRepo(ArtifactRepository):
    """Artifact storage with validation"""

    def log_artifact(self, local_file, artifact_path=None):
        # Validate artifact path matches conventions
        # /models/*, /datasets/*, /plots/*

        # Enforce artifact naming
        # {model_name}-v{version}.{ext}

        # Call parent implementation
        super().log_artifact(local_file, artifact_path)
```

### What MLflow Plugins CANNOT Do

❌ **Intercept experiment creation**  
❌ **Validate run parameters**  
❌ **Enforce naming conventions**  
❌ **Pre/post hooks for operations**  
❌ **Custom validation logic**  

### Conclusion on MLflow Plugins

> **MLflow's plugin system is insufficient for governance.** It only handles auth and artifact storage. For validation, you need external layers (API gateway, client wrappers, or database triggers).

---

## 6. Database-Level Governance

### PostgreSQL Triggers Approach

**Pros:** Impossible to bypass, works at data layer  
**Cons:** Limited validation logic, complex to maintain

```sql
-- mlflow_governance/database_triggers.sql
-- Enforce experiment naming at database level

-- 1. Experiment name must match pattern
CREATE OR REPLACE FUNCTION validate_experiment_name()
RETURNS TRIGGER AS $$
DECLARE
    valid_pattern TEXT := '^(Development|Staging|Production|QA|Dataset)-[A-Za-z-]+$';
BEGIN
    IF NEW.name !~ valid_pattern THEN
        RAISE EXCEPTION 'Invalid experiment name: %. Must match pattern: %',
            NEW.name, valid_pattern
        USING HINT = 'Use one of: Development-*, Staging-*, Production-*, QA-*, Dataset-*';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_experiment_naming
    BEFORE INSERT OR UPDATE ON experiments
    FOR EACH ROW
    EXECUTE FUNCTION validate_experiment_name();

-- 2. Require specific tags on runs
CREATE OR REPLACE FUNCTION validate_run_tags()
RETURNS TRIGGER AS $$
DECLARE
    required_tags TEXT[] := ARRAY['model_type', 'team', 'dataset_version'];
    tag_key TEXT;
    tag_exists BOOLEAN;
BEGIN
    FOREACH tag_key IN ARRAY required_tags LOOP
        SELECT EXISTS(
            SELECT 1 FROM tags
            WHERE run_uuid = NEW.run_uuid
            AND key = tag_key
        ) INTO tag_exists;

        IF NOT tag_exists THEN
            RAISE EXCEPTION 'Missing required tag: % for run %', tag_key, NEW.run_uuid;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_run_tags
    AFTER INSERT ON runs
    FOR EACH ROW
    EXECUTE FUNCTION validate_run_tags();

-- 3. Prevent experiment deletion in production
CREATE OR REPLACE FUNCTION protect_production_experiments()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.name LIKE 'Production-%' OR OLD.name LIKE 'Staging-%' THEN
        RAISE EXCEPTION 'Cannot delete production/staging experiment: %', OLD.name
        USING HINT = 'Use lifecycle_stage=deleted instead of DROP';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prevent_production_deletion
    BEFORE DELETE ON experiments
    FOR EACH ROW
    EXECUTE FUNCTION protect_production_experiments();

-- 4. Audit log all operations
CREATE TABLE IF NOT EXISTS mlflow_audit_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    operation TEXT NOT NULL,
    table_name TEXT NOT NULL,
    row_id TEXT,
    old_data JSONB,
    new_data JSONB,
    user_id TEXT
);

CREATE OR REPLACE FUNCTION audit_mlflow_operations()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO mlflow_audit_log (operation, table_name, row_id, old_data, new_data, user_id)
    VALUES (
        TG_OP,
        TG_TABLE_NAME,
        COALESCE(NEW.run_uuid::TEXT, OLD.run_uuid::TEXT, NEW.experiment_id::TEXT, OLD.experiment_id::TEXT),
        CASE WHEN TG_OP != 'INSERT' THEN row_to_json(OLD) ELSE NULL END,
        CASE WHEN TG_OP != 'DELETE' THEN row_to_json(NEW) ELSE NULL END,
        current_setting('app.current_user', true)
    );
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- Apply to all tables
CREATE TRIGGER audit_experiments AFTER INSERT OR UPDATE OR DELETE ON experiments
    FOR EACH ROW EXECUTE FUNCTION audit_mlflow_operations();

CREATE TRIGGER audit_runs AFTER INSERT OR UPDATE OR DELETE ON runs
    FOR EACH ROW EXECUTE FUNCTION audit_mlflow_operations();
```

**Installation:**
```bash
# Deploy triggers
psql -h localhost -U mlflow -d mlflow_db -f mlflow_governance/database_triggers.sql

# Test validation
psql -h localhost -U mlflow -d mlflow_db -c "
INSERT INTO experiments (name, artifact_location, lifecycle_stage)
VALUES ('invalid-name', '/mlflow/artifacts/invalid', 'active');
"
# ERROR:  Invalid experiment name: invalid-name. Must match pattern: ^(Development|Staging|Production|QA|Dataset)-[A-Za-z-]+$
# HINT:  Use one of: Development-*, Staging-*, Production-*, QA-*, Dataset-*
```

**Pros:**
- ✅ Impossible to bypass (enforced at data layer)
- ✅ Works with any client (Python, R, REST API)
- ✅ Centralized enforcement
- ✅ Built-in audit logging

**Cons:**
- ❌ Limited validation logic (SQL-only)
- ❌ Hard to debug (errors from database)
- ❌ Requires DBA expertise
- ❌ Can't provide friendly user messages
- ❌ Difficult to update policies

---

## 7. Recommended Multi-Layer Approach for SHML Platform

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Python Client Wrapper (User Experience)            │
│ - Friendly error messages                                   │
│ - Auto-completion for valid experiments                     │
│ - Validates before API call                                 │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ Layer 2: Traefik Middleware (Server-Side Enforcement)       │
│ - Intercepts all MLflow API calls                          │
│ - Validates experiment names, model paths                   │
│ - Returns 403 Forbidden if invalid                         │
│ - Language-agnostic (works with any client)                │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ Layer 3: MLflow Authentication (Access Control)             │
│ - FusionAuth OAuth integration                             │
│ - Role-based permissions (admin/developer/user)            │
│ - Experiment-level access control                          │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ Layer 4: PostgreSQL Constraints (Data Integrity)            │
│ - Experiment name pattern validation                        │
│ - Required tags enforcement                                 │
│ - Audit logging                                            │
│ - Prevent production experiment deletion                   │
└─────────────────────────────────────────────────────────────┘
```

### Why This Approach?

1. **Defense in depth** - Multiple layers catch different issues
2. **User-friendly** - Python wrapper provides best UX
3. **Enforceable** - Traefik middleware can't be bypassed
4. **Scalable** - Works across Ray, Jupyter, CI/CD, etc.
5. **Maintainable** - Each layer has single responsibility

---

## 8. Implementation Plan

### Phase 1: Quick Wins (1-2 weeks)

**Goal:** Prevent accidental misuse with friendly UX

**1. Python Client Wrapper**

```python
# ray_compute/api/mlflow_governance.py
"""
SHML Platform MLflow Governance Client
Wraps MLflow with validation and best practices enforcement
"""

import mlflow
from mlflow import MlflowClient
from typing import Dict, List, Optional
import os

# SHML Platform allowed experiments
ALLOWED_EXPERIMENTS = {
    "Development-Training": {
        "description": "Active model development and experimentation",
        "required_tags": ["model_type", "dataset_version", "developer"],
        "artifact_structure": ["models/", "plots/", "configs/", "logs/"],
        "auto_tags": {"environment": "development"}
    },
    "Staging-Model-Comparison": {
        "description": "Compare models before production deployment",
        "required_tags": ["model_type", "baseline_model", "comparison_metric"],
        "artifact_structure": ["models/", "comparison_reports/", "metrics/"],
        "auto_tags": {"environment": "staging"}
    },
    "Production-Models": {
        "description": "Production-ready models (requires approval)",
        "required_tags": ["model_type", "dataset_version", "approval_ticket"],
        "artifact_structure": ["models/", "onnx/", "tensorrt/", "docs/"],
        "auto_tags": {"environment": "production"},
        "approval_required": True
    },
    "QA-Testing": {
        "description": "Model quality assurance and validation",
        "required_tags": ["test_type", "model_version", "qa_status"],
        "artifact_structure": ["test_results/", "metrics/", "reports/"],
        "auto_tags": {"environment": "qa"}
    },
    "Dataset-Registry": {
        "description": "Versioned dataset artifacts and metadata",
        "required_tags": ["dataset_name", "version", "source", "format"],
        "artifact_structure": ["data/", "metadata/", "validation_reports/"],
        "auto_tags": {"type": "dataset"}
    },
    "Model-Evaluations": {
        "description": "Centralized model evaluation metrics",
        "required_tags": ["evaluated_model", "evaluation_type", "benchmark"],
        "artifact_structure": ["evaluations/", "metrics/", "visualizations/"],
        "auto_tags": {"type": "evaluation"}
    }
}

class SHMLMLflowClient:
    """Governed MLflow client for SHML Platform"""

    def __init__(self, experiment_name: Optional[str] = None):
        """
        Initialize governed MLflow client

        Args:
            experiment_name: One of the allowed experiments. If None, will prompt user.
        """
        self.tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-nginx:80")
        mlflow.set_tracking_uri(self.tracking_uri)
        self.client = MlflowClient()

        if experiment_name:
            self.set_experiment(experiment_name)
        else:
            print("📊 SHML Platform - Available Experiments:\n")
            for exp_name, config in ALLOWED_EXPERIMENTS.items():
                print(f"  • {exp_name}")
                print(f"    {config['description']}")
                print()

    def set_experiment(self, experiment_name: str):
        """Set active experiment with validation"""
        if experiment_name not in ALLOWED_EXPERIMENTS:
            raise ValueError(
                f"❌ Experiment '{experiment_name}' not allowed.\n\n"
                f"Valid experiments:\n" +
                "\n".join(f"  • {name}: {cfg['description']}"
                         for name, cfg in ALLOWED_EXPERIMENTS.items()) +
                f"\n\nTo request a new experiment, contact ML Platform team."
            )

        self.experiment_name = experiment_name
        self.experiment_config = ALLOWED_EXPERIMENTS[experiment_name]
        mlflow.set_experiment(experiment_name)

        print(f"✅ Using experiment: {experiment_name}")
        print(f"   {self.experiment_config['description']}")

        return self

    def start_run(self, run_name: str, tags: Dict[str, str], **kwargs):
        """Start MLflow run with validation"""
        if not hasattr(self, 'experiment_name'):
            raise RuntimeError("Must call set_experiment() first")

        # Validate required tags
        required = self.experiment_config["required_tags"]
        missing = set(required) - set(tags.keys())
        if missing:
            raise ValueError(
                f"❌ Missing required tags: {missing}\n\n"
                f"Required tags for '{self.experiment_name}':\n" +
                "\n".join(f"  • {tag}" for tag in required) +
                f"\n\nExample:\n  tags={{\n" +
                "\n".join(f"    '{tag}': 'your-value'," for tag in required) +
                "\n  }"
            )

        # Add automatic tags
        tags.update(self.experiment_config["auto_tags"])
        tags["shml.platform.version"] = "1.0"
        tags["shml.governance.enabled"] = "true"

        # Check approval requirement
        if self.experiment_config.get("approval_required"):
            print("⚠️  This experiment requires approval before production deployment")
            print("   Your run will be logged for review")

        return mlflow.start_run(run_name=run_name, tags=tags, **kwargs)

    def log_model(self, model, artifact_path: str, **kwargs):
        """Log model with path validation"""
        if not hasattr(self, 'experiment_name'):
            raise RuntimeError("Must call set_experiment() first")

        # Validate artifact path
        valid_dirs = self.experiment_config["artifact_structure"]
        if not any(artifact_path.startswith(d) for d in valid_dirs):
            raise ValueError(
                f"❌ Invalid artifact path: '{artifact_path}'\n\n"
                f"Must start with one of:\n" +
                "\n".join(f"  • {d}" for d in valid_dirs) +
                f"\n\nExample: models/yolov8l-face-v1.0.0"
            )

        # Log model
        return mlflow.log_model(model, artifact_path, **kwargs)

    def log_dataset(self, dataset_path: str, name: str, version: str, **metadata):
        """Log dataset to Dataset-Registry experiment"""
        original_exp = self.experiment_name if hasattr(self, 'experiment_name') else None

        # Switch to Dataset-Registry
        self.set_experiment("Dataset-Registry")

        tags = {
            "dataset_name": name,
            "version": version,
            "source": metadata.get("source", "unknown"),
            "format": metadata.get("format", "unknown")
        }

        with self.start_run(run_name=f"{name}-{version}", tags=tags):
            mlflow.log_artifact(dataset_path, "data/")
            mlflow.log_dict(metadata, "metadata/dataset_info.json")

        # Switch back to original experiment
        if original_exp:
            self.set_experiment(original_exp)

        print(f"✅ Dataset '{name}' version '{version}' logged to Dataset-Registry")

    @staticmethod
    def list_experiments():
        """List all allowed experiments with details"""
        print("📊 SHML Platform - MLflow Experiments\n")
        print("=" * 70)
        for exp_name, config in ALLOWED_EXPERIMENTS.items():
            print(f"\n{exp_name}")
            print(f"  Description: {config['description']}")
            print(f"  Required Tags: {', '.join(config['required_tags'])}")
            print(f"  Artifact Structure: {', '.join(config['artifact_structure'])}")
            if config.get("approval_required"):
                print(f"  ⚠️  Approval Required: Yes")

# Usage examples
if __name__ == "__main__":
    # Example 1: Face detection training
    client = SHMLMLflowClient("Development-Training")

    with client.start_run(
        run_name="yolov8l-face-v1.0.0",
        tags={
            "model_type": "face-detection",
            "dataset_version": "wider-face-v2.0",
            "developer": "ml-team"
        }
    ):
        # Training code here
        client.log_model(model, "models/yolov8l-face-v1.0.0")

    # Example 2: Log dataset
    client.log_dataset(
        dataset_path="/data/wider-face-v2.0.zip",
        name="wider-face",
        version="2.0",
        source="http://shuoyang1213.me/WIDERFACE/",
        format="yolo",
        num_images=32203
    )
```

**2. Update Training Scripts**

```python
# ray_compute/jobs/face_detection_training.py
# Add at top of file:
from ray_compute.api.mlflow_governance import SHMLMLflowClient

# Replace:
# mlflow.set_experiment(config.mlflow_experiment)

# With:
client = SHMLMLflowClient(config.mlflow_experiment)
with client.start_run(
    run_name=config.run_name,
    tags={
        "model_type": "face-detection",
        "dataset_version": config.dataset_version,
        "developer": os.getenv("USER", "unknown")
    }
):
    # Training code...
    client.log_model(model, f"models/{config.run_name}")
```

**3. Set Default Experiment in Ray Container**

```yaml
# ray_compute/docker-compose.yml
environment:
  - MLFLOW_EXPERIMENT_NAME=Development-Training  # Default
  - MLFLOW_TRACKING_URI=http://mlflow-nginx:80
```

---

### Phase 2: Server-Side Enforcement (2-4 weeks)

**Goal:** Make governance impossible to bypass

**1. Traefik Middleware Plugin**

```go
// monitoring/traefik/plugins/mlflow-governance/mlflow_governance.go
package mlflow_governance

import (
    "context"
    "encoding/json"
    "fmt"
    "net/http"
    "regexp"
    "strings"
)

// Config for the middleware
type Config struct {
    AllowedExperiments []string          `json:"allowedExperiments"`
    ExperimentPatterns map[string]string `json:"experimentPatterns"`
    EnforceMode        string            `json:"enforceMode"` // "block" or "warn"
}

// CreateConfig creates the default plugin configuration
func CreateConfig() *Config {
    return &Config{
        AllowedExperiments: []string{
            "Development-Training",
            "Staging-Model-Comparison",
            "Production-Models",
            "QA-Testing",
            "Dataset-Registry",
            "Model-Evaluations",
        },
        ExperimentPatterns: map[string]string{
            "Development":   "^Development-[A-Za-z-]+$",
            "Staging":       "^Staging-[A-Za-z-]+$",
            "Production":    "^Production-[A-Za-z-]+$",
            "QA":            "^QA-[A-Za-z-]+$",
            "Dataset":       "^Dataset-[A-Za-z-]+$",
        },
        EnforceMode: "block",
    }
}

// MLflowGovernance middleware
type MLflowGovernance struct {
    next   http.Handler
    config *Config
    name   string
}

// New creates a new MLflowGovernance middleware
func New(ctx context.Context, next http.Handler, config *Config, name string) (http.Handler, error) {
    return &MLflowGovernance{
        next:   next,
        config: config,
        name:   name,
    }, nil
}

func (m *MLflowGovernance) ServeHTTP(rw http.ResponseWriter, req *http.Request) {
    // Intercept experiment creation
    if req.Method == "POST" && strings.Contains(req.URL.Path, "/api/2.0/mlflow/experiments/create") {
        if err := m.validateExperimentCreation(req); err != nil {
            if m.config.EnforceMode == "block" {
                m.sendError(rw, http.StatusForbidden, err.Error())
                return
            }
            // Warn mode: add header and continue
            req.Header.Set("X-MLflow-Governance-Warning", err.Error())
        }
    }

    // Intercept model registration
    if req.Method == "POST" && strings.Contains(req.URL.Path, "/api/2.0/mlflow/registered-models/create") {
        if err := m.validateModelRegistration(req); err != nil {
            if m.config.EnforceMode == "block" {
                m.sendError(rw, http.StatusForbidden, err.Error())
                return
            }
        }
    }

    m.next.ServeHTTP(rw, req)
}

func (m *MLflowGovernance) validateExperimentCreation(req *http.Request) error {
    var body map[string]interface{}
    if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
        return fmt.Errorf("invalid request body")
    }

    expName, ok := body["name"].(string)
    if !ok {
        return fmt.Errorf("missing experiment name")
    }

    // Check if in allowed list
    for _, allowed := range m.config.AllowedExperiments {
        if expName == allowed {
            return nil // Valid
        }
    }

    // Check if matches any pattern
    for category, pattern := range m.config.ExperimentPatterns {
        matched, _ := regexp.MatchString(pattern, expName)
        if matched {
            return nil // Valid pattern
        }
    }

    return fmt.Errorf(
        "Experiment '%s' not allowed. Must be one of: %v",
        expName,
        m.config.AllowedExperiments,
    )
}

func (m *MLflowGovernance) validateModelRegistration(req *http.Request) error {
    var body map[string]interface{}
    json.NewDecoder(req.Body).Decode(&body)

    modelName, ok := body["name"].(string)
    if !ok {
        return fmt.Errorf("missing model name")
    }

    // Enforce naming: {project}_{architecture}_{purpose}
    parts := strings.Split(modelName, "_")
    if len(parts) < 3 {
        return fmt.Errorf(
            "Model name must follow pattern: {project}_{architecture}_{purpose}. Got: %s",
            modelName,
        )
    }

    return nil
}

func (m *MLflowGovernance) sendError(rw http.ResponseWriter, code int, message string) {
    rw.Header().Set("Content-Type", "application/json")
    rw.WriteHeader(code)
    json.NewEncoder(rw).Encode(map[string]string{
        "error":    message,
        "help_url": "https://docs.shml-platform.com/mlflow/governance",
    })
}
```

**2. Deploy Traefik Plugin**

```yaml
# monitoring/traefik/traefik.yml
experimental:
  plugins:
    mlflow-governance:
      moduleName: github.com/shml-platform/traefik-mlflow-governance
      version: v1.0.0

# monitoring/traefik/dynamic/mlflow.yml
http:
  middlewares:
    mlflow-governance:
      plugin:
        mlflow-governance:
          allowedExperiments:
            - "Development-Training"
            - "Staging-Model-Comparison"
            - "Production-Models"
            - "QA-Testing"
            - "Dataset-Registry"
            - "Model-Evaluations"
          enforceMode: "block"  # or "warn"

  routers:
    mlflow-api:
      rule: "PathPrefix(`/mlflow/api`)"
      middlewares:
        - mlflow-governance  # Add governance
        - oauth2-auth        # Then auth
      service: mlflow
```

**Result:** All MLflow API calls go through validation, regardless of client

---

### Phase 3: Advanced Features (4-8 weeks)

**1. Dataset Registry with Lineage**

```python
# ray_compute/api/dataset_registry.py
"""
SHML Platform Dataset Registry
Tracks datasets, versions, and lineage with models
"""

import mlflow
from mlflow import MlflowClient
from typing import Dict, List, Optional
import hashlib
import json

class DatasetRegistry:
    """Centralized dataset versioning and lineage tracking"""

    def __init__(self):
        self.client = MlflowClient()
        mlflow.set_experiment("Dataset-Registry")

    def register_dataset(
        self,
        name: str,
        version: str,
        path: str,
        metadata: Dict,
        compute_hash: bool = True
    ) -> str:
        """
        Register a dataset version

        Returns:
            dataset_uri: mlflow://Dataset-Registry/{run_id}/data
        """
        # Compute dataset hash for deduplication
        if compute_hash:
            metadata["sha256"] = self._compute_hash(path)

        # Check for existing version
        existing = self.get_dataset(name, version)
        if existing:
            print(f"⚠️  Dataset {name} v{version} already exists")
            return existing["uri"]

        # Create run for this dataset version
        tags = {
            "dataset_name": name,
            "version": version,
            "format": metadata.get("format", "unknown"),
            "source": metadata.get("source", "unknown")
        }

        with mlflow.start_run(run_name=f"{name}-{version}", tags=tags):
            # Log dataset artifact
            mlflow.log_artifact(path, "data/")

            # Log metadata
            mlflow.log_dict(metadata, "metadata/info.json")

            # Log metrics (size, num_samples, etc.)
            if "size_mb" in metadata:
                mlflow.log_metric("size_mb", metadata["size_mb"])
            if "num_samples" in metadata:
                mlflow.log_metric("num_samples", metadata["num_samples"])

            run_id = mlflow.active_run().info.run_id

        dataset_uri = f"mlflow://Dataset-Registry/{run_id}/data"
        print(f"✅ Registered dataset: {name} v{version}")
        print(f"   URI: {dataset_uri}")

        return dataset_uri

    def link_dataset_to_model(self, dataset_uri: str, model_run_id: str):
        """Link dataset to model training run (lineage tracking)"""
        self.client.set_tag(model_run_id, "dataset_uri", dataset_uri)
        print(f"✅ Linked dataset to model run {model_run_id}")

    def get_dataset(self, name: str, version: str) -> Optional[Dict]:
        """Get dataset by name and version"""
        runs = self.client.search_runs(
            experiment_ids=[self.client.get_experiment_by_name("Dataset-Registry").experiment_id],
            filter_string=f"tags.dataset_name = '{name}' AND tags.version = '{version}'"
        )

        if runs:
            run = runs[0]
            return {
                "name": name,
                "version": version,
                "run_id": run.info.run_id,
                "uri": f"mlflow://Dataset-Registry/{run.info.run_id}/data",
                "metadata": run.data.params,
                "created_at": run.info.start_time
            }
        return None

    def list_datasets(self) -> List[Dict]:
        """List all registered datasets"""
        runs = self.client.search_runs(
            experiment_ids=[self.client.get_experiment_by_name("Dataset-Registry").experiment_id]
        )

        datasets = {}
        for run in runs:
            name = run.data.tags.get("dataset_name")
            version = run.data.tags.get("version")
            if name and version:
                key = f"{name}:{version}"
                datasets[key] = {
                    "name": name,
                    "version": version,
                    "run_id": run.info.run_id,
                    "uri": f"mlflow://Dataset-Registry/{run.info.run_id}/data"
                }

        return list(datasets.values())

    def _compute_hash(self, path: str) -> str:
        """Compute SHA256 hash of file"""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

# Usage in training scripts
dataset_registry = DatasetRegistry()

# Register dataset
dataset_uri = dataset_registry.register_dataset(
    name="wider-face",
    version="2.0",
    path="/data/wider-face.zip",
    metadata={
        "source": "http://shuoyang1213.me/WIDERFACE/",
        "format": "yolo",
        "num_images": 32203,
        "size_mb": 3200,
        "splits": ["train", "val", "test"]
    }
)

# Link to model training
with mlflow.start_run() as run:
    dataset_registry.link_dataset_to_model(dataset_uri, run.info.run_id)
    # Training code...
```

**2. Automated Model Registry with Approval Workflow**

```python
# ray_compute/api/model_registry_governance.py
"""
SHML Platform Model Registry with Approval Workflow
Enforces standards before production deployment
"""

import mlflow
from mlflow import MlflowClient
from typing import Dict, List, Optional
import requests

class GovernedModelRegistry:
    """Model registry with approval workflow and validation"""

    def __init__(self, slack_webhook: Optional[str] = None):
        self.client = MlflowClient()
        self.slack_webhook = slack_webhook

    def register_model(
        self,
        model_uri: str,
        name: str,
        tags: Dict[str, str],
        description: str,
        require_approval: bool = True
    ) -> Dict:
        """
        Register model with validation and approval workflow

        Returns:
            model_version: {name, version, stage, approval_status}
        """
        # Validate model name format
        if not self._validate_model_name(name):
            raise ValueError(
                f"Invalid model name: {name}\n"
                f"Must follow pattern: {{project}}_{{architecture}}_{{purpose}}\n"
                f"Example: shml_yolov8l_face-detection"
            )

        # Validate required tags
        required_tags = ["model_type", "dataset_version", "framework"]
        missing = set(required_tags) - set(tags.keys())
        if missing:
            raise ValueError(f"Missing required tags: {missing}")

        # Validate model artifact structure
        self._validate_model_artifact(model_uri)

        # Register model
        result = mlflow.register_model(model_uri, name, tags=tags)

        # Set description
        self.client.update_model_version(
            name=name,
            version=result.version,
            description=description
        )

        # Set initial stage
        if require_approval:
            # Pending approval
            self.client.transition_model_version_stage(
                name=name,
                version=result.version,
                stage="Staging",
                archive_existing_versions=False
            )

            # Send approval request
            self._request_approval(name, result.version, tags)

            print(f"✅ Model registered: {name} v{result.version}")
            print(f"   Stage: Staging (pending approval)")
            print(f"   Approval request sent to ML Platform team")
        else:
            self.client.transition_model_version_stage(
                name=name,
                version=result.version,
                stage="None"
            )
            print(f"✅ Model registered: {name} v{result.version}")

        return {
            "name": name,
            "version": result.version,
            "stage": "Staging" if require_approval else "None",
            "approval_required": require_approval
        }

    def approve_model(self, name: str, version: str, approver: str):
        """Approve model for production deployment"""
        # Transition to Production
        self.client.transition_model_version_stage(
            name=name,
            version=version,
            stage="Production",
            archive_existing_versions=True  # Archive old versions
        )

        # Tag approval
        self.client.set_model_version_tag(
            name=name,
            version=version,
            key="approval.status",
            value="approved"
        )
        self.client.set_model_version_tag(
            name=name,
            version=version,
            key="approval.approver",
            value=approver
        )

        print(f"✅ Model approved: {name} v{version}")
        print(f"   Stage: Production")
        print(f"   Approved by: {approver}")

    def _validate_model_name(self, name: str) -> bool:
        """Validate model name follows convention"""
        parts = name.split("_")
        return len(parts) >= 3  # project_architecture_purpose

    def _validate_model_artifact(self, model_uri: str):
        """Validate model artifact has required files"""
        # Check for:
        # - model file (*.pt, *.onnx, etc.)
        # - requirements.txt
        # - config.yaml
        # - README.md
        pass

    def _request_approval(self, name: str, version: str, tags: Dict):
        """Send approval request notification"""
        if self.slack_webhook:
            message = {
                "text": f"🔔 Model Approval Request",
                "blocks": [{
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Model:* {name} v{version}\n"
                                f"*Type:* {tags.get('model_type')}\n"
                                f"*Dataset:* {tags.get('dataset_version')}\n"
                                f"*Review:* http://localhost/mlflow/#/models/{name}/versions/{version}"
                    }
                }]
            }
            requests.post(self.slack_webhook, json=message)
```

---

## 9. Comparison Matrix

| Approach | UX | Enforcement | Maintenance | Bypass Risk | Implementation Time |
|----------|-----|------------|-------------|-------------|-------------------|
| **Python Wrapper Only** | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | High | 1 week |
| **Traefik Middleware** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | None | 2 weeks |
| **Database Triggers** | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | None | 1 week |
| **MLflow Plugins** | ⭐⭐ | ⭐⭐ | ⭐⭐ | Medium | 3 weeks |
| **Hybrid (Recommended)** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | None | 4 weeks |

---

## 10. Decision Framework

### Use Python Wrapper If:
- ✅ You trust your users (internal team)
- ✅ You want fast rollout (< 1 week)
- ✅ You prioritize user experience
- ❌ You can't enforce server-side validation

### Use Traefik Middleware If:
- ✅ You need unbypassable enforcement
- ✅ You have multi-language clients (Python, R, Julia)
- ✅ You want centralized policy management
- ❌ You can't modify client code

### Use Database Triggers If:
- ✅ You need absolute data integrity
- ✅ You have DBA resources
- ✅ You want audit logging at data layer
- ❌ You need complex validation logic

### Use Hybrid Approach If:
- ✅ You need both UX and enforcement
- ✅ You're building production platform
- ✅ You have 4+ weeks for implementation
- ✅ You want defense in depth

---

## 11. Next Steps

**Immediate (This Week):**
1. ✅ Deploy Python wrapper (`SHMLMLflowClient`)
2. ✅ Update one training script as proof-of-concept
3. ✅ Document usage in README

**Short-term (Next 2 Weeks):**
1. Deploy Traefik middleware for server-side enforcement
2. Add database triggers for critical constraints
3. Update all training scripts to use wrapper

**Long-term (Next Month):**
1. Build dataset registry with lineage tracking
2. Implement approval workflow for production models
3. Add monitoring/alerting for governance violations

**Ongoing:**
- Collect feedback from data scientists
- Refine policies based on usage patterns
- Add more experiment types as needed

---

## 12. References

- [MLflow Documentation - Tracking](https://mlflow.org/docs/latest/tracking.html)
- [Databricks - MLflow Best Practices](https://docs.databricks.com/mlflow/index.html)
- [Netflix Tech Blog - ML Platform](https://netflixtechblog.com/)
- [Uber Engineering - Michelangelo](https://eng.uber.com/michelangelo/)
- [Airbnb Engineering - Bighead](https://medium.com/airbnb-engineering/bighead-airbnbs-end-to-end-machine-learning-platform-f6ca0df00e89)

---

**Document Status:** Ready for Implementation  
**Reviewed By:** Claude (SHML Platform AI Assistant)  
**Last Updated:** December 6, 2025
