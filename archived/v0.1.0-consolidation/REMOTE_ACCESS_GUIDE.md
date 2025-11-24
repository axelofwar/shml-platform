# Remote ML Training Platform Access Guide
**OAuth-Secured Ray Compute & MLflow Platform**

Last Updated: November 23, 2025

---

## Overview

This guide enables remote training machines to submit ML jobs to your Ray Compute Platform via OAuth authentication. All API requests are secured using OAuth 2.0 tokens from Authentik.

## ✅ Verified Working Components

1. **OAuth Token Acquisition** ✅
   - Ray Compute OAuth tokens working
   - MLflow OAuth tokens working
   - Token expiry: 5 minutes (300 seconds)

2. **MLflow API Access** ✅
   - Authenticated requests working
   - Experiments listing successful
   - Full MLflow tracking API available

3. **Ray Compute API** ⚠️
   - OAuth authentication working
   - Database schema needs initialization (see Database Setup section)

---

## Quick Start for Remote Machines

### 1. Prerequisites

Install required tools on your remote training machine:

```bash
# Python 3.8+ with requests
pip install requests ray[default] mlflow

# Or use curl for simple requests
# (already available on most systems)
```

### 2. Save OAuth Credentials

Create a credentials file on your remote machine:

```bash
# Create .ray-oauth file
cat > ~/.ray-oauth << 'EOF'
RAY_OAUTH_CLIENT_ID="sG9eyyi2xlduwpu1Fo1VMHXdGWGuwcaIdULZuBbK"
RAY_OAUTH_CLIENT_SECRET="JsDs6mClPCWKqEqCppfBSz0AlfBIq3UDZVDO8rNM6b2TragJJaOLsO8ahM8LAzghKACPJL2xURZidRxku4ESRtNf9vBQgh5Tq3MMtp62EgEQe31ShXRGTphg8KdxcnfY"
MLFLOW_OAUTH_CLIENT_ID="txarUgT4aVGqYgLZ5UAeUkDQ6bKL8fQ5uuu1KYVH"
MLFLOW_OAUTH_CLIENT_SECRET="du7TezhxO2O61I65H5gfdpMyGCqNqJD3SFI32FG6ePYTp7MCGbC8IoY5kTXXKXPoCyscuYKRQZZarzSaT8hH11EHhQyxNk5gD7L4arGph9bjmhE9WBtL0ImMgX2pSbfq"
EOF

chmod 600 ~/.ray-oauth
```

### 3. Access URLs (From Remote Machine)

Use these URLs from your remote training machine:

| Service | URL | Purpose |
|---------|-----|---------|
| **Authentik OAuth** | `http://localhost:9000` | Get OAuth tokens |
| **Ray Compute API** | `http://localhost/api/ray/api/v1/` | Submit/manage jobs |
| **Ray Dashboard** | `http://localhost/ray/` | Monitor cluster |
| **MLflow API** | `http://localhost/api/v1/` | Track experiments |
| **MLflow UI** | `http://localhost/mlflow/` | View runs/models |

**VPN Access** (if configured):
- Replace `${SERVER_IP}` with `${TAILSCALE_IP}`

---

## Python Client Library

### Complete Ray + MLflow Client

Save this as `ray_client.py` on your remote machine:

```python
#!/usr/bin/env python3
"""
Remote Ray Compute Client with OAuth and MLflow Integration
"""
import os
import requests
import time
from typing import Dict, Optional
import mlflow


class RayComputeClient:
    """Client for submitting jobs to OAuth-secured Ray Compute Platform"""
    
    def __init__(
        self,
        platform_host: str = "${SERVER_IP}",
        ray_client_id: str = None,
        ray_client_secret: str = None,
        mlflow_client_id: str = None,
        mlflow_client_secret: str = None
    ):
        self.platform_host = platform_host
        self.oauth_url = f"http://{platform_host}:9000/application/o/token/"
        self.ray_api_url = f"http://{platform_host}/api/ray/api/v1"
        self.mlflow_url = f"http://{platform_host}/api/v1"
        
        # Load credentials
        self.ray_client_id = ray_client_id or os.getenv("RAY_OAUTH_CLIENT_ID")
        self.ray_client_secret = ray_client_secret or os.getenv("RAY_OAUTH_CLIENT_SECRET")
        self.mlflow_client_id = mlflow_client_id or os.getenv("MLFLOW_OAUTH_CLIENT_ID")
        self.mlflow_client_secret = mlflow_client_secret or os.getenv("MLFLOW_OAUTH_CLIENT_SECRET")
        
        # Tokens
        self._ray_token = None
        self._mlflow_token = None
        self._ray_token_expires = 0
        self._mlflow_token_expires = 0
    
    def get_ray_token(self) -> str:
        """Get or refresh Ray OAuth token"""
        if self._ray_token and time.time() < self._ray_token_expires:
            return self._ray_token
        
        response = requests.post(
            self.oauth_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": self.ray_client_id,
                "client_secret": self.ray_client_secret
            }
        )
        response.raise_for_status()
        
        data = response.json()
        self._ray_token = data["access_token"]
        # Token expires in 5 minutes, refresh 30 seconds before
        self._ray_token_expires = time.time() + data.get("expires_in", 300) - 30
        
        return self._ray_token
    
    def get_mlflow_token(self) -> str:
        """Get or refresh MLflow OAuth token"""
        if self._mlflow_token and time.time() < self._mlflow_token_expires:
            return self._mlflow_token
        
        response = requests.post(
            self.oauth_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": self.mlflow_client_id,
                "client_secret": self.mlflow_client_secret
            }
        )
        response.raise_for_status()
        
        data = response.json()
        self._mlflow_token = data["access_token"]
        self._mlflow_token_expires = time.time() + data.get("expires_in", 300) - 30
        
        return self._mlflow_token
    
    def submit_job(
        self,
        entrypoint: str,
        runtime_env: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
        experiment_name: str = "Development-Training"
    ) -> Dict:
        """
        Submit a Ray job with automatic MLflow logging
        
        Args:
            entrypoint: Command to run (e.g., "python train.py")
            runtime_env: Ray runtime environment config
            metadata: Job metadata
            experiment_name: MLflow experiment name for auto-logging
        
        Returns:
            Job submission response with job_id
        """
        token = self.get_ray_token()
        
        # Add MLflow environment variables for auto-logging
        if runtime_env is None:
            runtime_env = {}
        
        if "env_vars" not in runtime_env:
            runtime_env["env_vars"] = {}
        
        runtime_env["env_vars"].update({
            "MLFLOW_TRACKING_URI": f"http://{self.platform_host}/mlflow",
            "MLFLOW_EXPERIMENT_NAME": experiment_name
        })
        
        payload = {
            "entrypoint": entrypoint,
            "runtime_env": runtime_env,
            "metadata": metadata or {}
        }
        
        response = requests.post(
            f"{self.ray_api_url}/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json=payload
        )
        response.raise_for_status()
        
        return response.json()
    
    def get_job_status(self, job_id: str) -> Dict:
        """Get job status and details"""
        token = self.get_ray_token()
        
        response = requests.get(
            f"{self.ray_api_url}/jobs/{job_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        
        return response.json()
    
    def list_jobs(self) -> Dict:
        """List all jobs for current user"""
        token = self.get_ray_token()
        
        response = requests.get(
            f"{self.ray_api_url}/jobs",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        
        return response.json()
    
    def get_mlflow_experiments(self) -> Dict:
        """List MLflow experiments"""
        token = self.get_mlflow_token()
        
        response = requests.get(
            f"{self.mlflow_url}/experiments",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        
        return response.json()
    
    def setup_mlflow_tracking(self, experiment_name: str = "Development-Training"):
        """Configure MLflow tracking for local script"""
        mlflow.set_tracking_uri(f"http://{self.platform_host}/mlflow")
        mlflow.set_experiment(experiment_name)
        
        print(f"✅ MLflow tracking configured:")
        print(f"   URI: http://{self.platform_host}/mlflow")
        print(f"   Experiment: {experiment_name}")


# Example usage
if __name__ == "__main__":
    # Initialize client
    client = RayComputeClient()
    
    # Test connection
    print("Testing Ray Compute Platform access...")
    
    try:
        # Get OAuth token
        token = client.get_ray_token()
        print(f"✅ OAuth token acquired: {token[:30]}...")
        
        # List experiments
        experiments = client.get_mlflow_experiments()
        print(f"✅ MLflow accessible: {len(experiments['experiments'])} experiments found")
        
        # List jobs
        jobs = client.list_jobs()
        print(f"✅ Ray Compute accessible: {len(jobs.get('jobs', []))} jobs found")
        
        print("\n🎉 Platform access verified!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
```

### Usage Examples

#### 1. Submit a Simple Training Job

```python
from ray_client import RayComputeClient

# Initialize client
client = RayComputeClient()

# Submit job
job = client.submit_job(
    entrypoint="python train.py --epochs 100",
    runtime_env={
        "working_dir": "./my_project",
        "pip": ["torch==2.0.0", "transformers"]
    },
    metadata={
        "project": "pii-detection",
        "model": "bert-base"
    },
    experiment_name="Production-Candidates"
)

print(f"Job submitted: {job['job_id']}")

# Monitor job
import time
while True:
    status = client.get_job_status(job['job_id'])
    print(f"Status: {status['status']}")
    
    if status['status'] in ['SUCCEEDED', 'FAILED']:
        break
    
    time.sleep(10)
```

#### 2. Track Experiments with MLflow

```python
from ray_client import RayComputeClient
import mlflow

# Initialize and configure MLflow
client = RayComputeClient()
client.setup_mlflow_tracking(experiment_name="Development-Training")

# Run training with MLflow tracking
with mlflow.start_run():
    mlflow.log_param("learning_rate", 0.001)
    mlflow.log_param("batch_size", 32)
    
    # Your training code here
    accuracy = train_model()
    
    mlflow.log_metric("accuracy", accuracy)
    mlflow.log_artifact("model.pkl")
```

#### 3. Submit GPU Job

```python
job = client.submit_job(
    entrypoint="python train_gpu.py",
    runtime_env={
        "working_dir": "./",
        "pip": ["torch", "torchvision"],
        "env_vars": {
            "CUDA_VISIBLE_DEVICES": "0"
        }
    },
    metadata={
        "gpu_requested": 1,
        "memory_gb": 16
    }
)
```

---

## Bash/cURL Examples

### Get OAuth Token

```bash
# Source credentials
source ~/.ray-oauth

# Get Ray token
RAY_TOKEN=$(curl -s -X POST http://localhost:9000/application/o/token/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=${RAY_OAUTH_CLIENT_ID}" \
  -d "client_secret=${RAY_OAUTH_CLIENT_SECRET}" \
  | jq -r '.access_token')

echo "Token: $RAY_TOKEN"
```

### Submit Job via cURL

```bash
curl -X POST http://localhost/api/ray/api/v1/jobs \
  -H "Authorization: Bearer $RAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "entrypoint": "python train.py",
    "runtime_env": {
      "working_dir": "./my_project",
      "pip": ["scikit-learn", "pandas"]
    },
    "metadata": {
      "project": "ml-experiment"
    }
  }'
```

### Check Job Status

```bash
JOB_ID="raysubmit_xxxxx"

curl -H "Authorization: Bearer $RAY_TOKEN" \
  http://localhost/api/ray/api/v1/jobs/$JOB_ID | jq
```

### List MLflow Experiments

```bash
# Get MLflow token
MLFLOW_TOKEN=$(curl -s -X POST http://localhost:9000/application/o/token/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=${MLFLOW_OAUTH_CLIENT_ID}" \
  -d "client_secret=${MLFLOW_OAUTH_CLIENT_SECRET}" \
  | jq -r '.access_token')

# List experiments
curl -H "Authorization: Bearer $MLFLOW_TOKEN" \
  http://localhost/api/v1/experiments | jq
```

---

## Database Setup (Platform Admin Only)

**Note:** This step should be completed by the platform administrator before remote users can submit jobs.

```bash
# On the ML platform server
docker exec -i ray-compute-db psql -U ray_compute -d ray_compute < schema.sql
```

See `ray_compute/schemas/schema.sql` for the complete database schema.

---

## Automatic MLflow Logging

All Ray jobs automatically log to MLflow when `MLFLOW_TRACKING_URI` is set in the runtime environment. The Ray Compute Platform includes automatic logging for:

- **Job metadata**: Start time, end time, duration, status
- **Resource usage**: CPU hours, GPU hours, memory peak
- **Job parameters**: All runtime_env settings logged as params
- **Job tags**: Automatic tagging with user, project, job type

### Disable Auto-Logging

To opt-out of automatic MLflow logging:

```python
runtime_env = {
    "env_vars": {
        "DISABLE_MLFLOW_LOGGING": "true"
    }
}
```

---

## Security Best Practices

### 1. Protect Credentials

```bash
# Use environment variables
export RAY_OAUTH_CLIENT_ID="your_client_id"
export RAY_OAUTH_CLIENT_SECRET="your_client_secret"

# Or use credential files with restrictive permissions
chmod 600 ~/.ray-oauth
```

### 2. Token Management

- Tokens expire after **5 minutes**
- Client library automatically refreshes tokens
- For long-running scripts, use the provided `RayComputeClient` class

### 3. Network Security

- Use VPN (`${TAILSCALE_IP}`) for external access
- LAN access (`${SERVER_IP}`) for internal network only
- Consider TLS/HTTPS for production deployments

### 4. Rotate Secrets Regularly

OAuth secrets should be rotated every 90 days:

1. Create new OAuth provider in Authentik
2. Update client credentials on remote machines
3. Revoke old OAuth provider

---

## Troubleshooting

### Token Acquisition Fails

```bash
# Test Authentik connectivity
curl -v http://localhost:9000/

# Verify credentials
echo "Client ID: $RAY_OAUTH_CLIENT_ID"
# (secret should not be echoed)

# Check token endpoint
curl -X POST http://localhost:9000/application/o/token/ \
  -d "grant_type=client_credentials" \
  -d "client_id=$RAY_OAUTH_CLIENT_ID" \
  -d "client_secret=$RAY_OAUTH_CLIENT_SECRET"
```

### API Returns 401 Unauthorized

- Token may have expired (5 min lifetime)
- Refresh token and retry
- Verify token is included in Authorization header

### Job Submission Fails

```bash
# Check Ray cluster status
curl -H "Authorization: Bearer $RAY_TOKEN" \
  http://localhost/api/ray/health | jq

# View Ray dashboard
open http://localhost/ray/
```

### MLflow Connection Issues

```bash
# Test MLflow API
curl -H "Authorization: Bearer $MLFLOW_TOKEN" \
  http://localhost/api/v1/health | jq

# Check MLflow UI
open http://localhost/mlflow/
```

---

## Platform Architecture

```
Remote Training Machine
    │
    ├─> Get OAuth Token (Authentik:9000)
    │   └─> Returns: access_token (5 min TTL)
    │
    ├─> Submit Job (Ray API + Token)
    │   └─> Ray Cluster executes job
    │   └─> Auto-logs to MLflow
    │
    └─> Track Experiment (MLflow API + Token)
        └─> View metrics, artifacts, models
```

---

## API Endpoints Reference

### Ray Compute API (`/api/ray/api/v1/`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/jobs` | POST | Submit new job |
| `/jobs` | GET | List user's jobs |
| `/jobs/{id}` | GET | Get job details |
| `/jobs/{id}` | DELETE | Cancel job |
| `/user/me` | GET | Get user info & quotas |
| `/user/quota` | GET | Get resource quotas |
| `/health` | GET | API health check |

### MLflow API (`/api/v1/`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/experiments` | GET | List experiments |
| `/runs/search` | POST | Search runs |
| `/runs/get` | GET | Get run details |
| `/artifacts/list` | GET | List run artifacts |
| `/health` | GET | API health check |

Full API documentation:
- Ray: http://localhost/api/ray/docs
- MLflow: http://localhost/api/v1/docs

---

## Support & Documentation

- **Platform Admin**: Contact system administrator for:
  - OAuth credential resets
  - Quota increases
  - Database issues
  
- **Local Documentation**:
  - Setup Guide: `OAUTH_SETUP_COMPLETE.md`
  - Quick Start: `OAUTH_QUICKSTART.md`
  - Architecture: `ARCHITECTURE.md`

- **MLflow UI**: http://localhost/mlflow/
- **Ray Dashboard**: http://localhost/ray/

---

**Platform Version**: 2.0.0 (OAuth-enabled)  
**Last Verified**: November 23, 2025
