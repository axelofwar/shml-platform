# OAuth Quick Start - ML Platform

## ✅ Current Status
- All services running and healthy (16/16 tests passed)
- Network tools installed in all containers
- `/ping` endpoints available on all APIs
- Authentik accessible at: http://localhost:9000/
- Admin credentials: `akadmin` / `AiSolutions2350!`

## 🚀 Quick Start (3 Steps)

### Step 1: Configure OAuth Providers in Authentik (Manual - Web UI)

1. **Access Authentik:**
   ```bash
   # Open in browser
   http://localhost:9000/
   # Login: akadmin / AiSolutions2350!
   ```

2. **Create Ray Compute OAuth Provider:**
   - Go to: **Applications** → **Providers** → **Create**
   - Select: **OAuth2/OpenID Provider**
   - **Name**: `Ray Compute OAuth Provider`
   - **Authorization flow**: `default-provider-authorization-implicit-consent`
   - **Client type**: `Confidential`
   - Client ID: `sG9eyyi2xlduwpu1Fo1VMHXdGWGuwcaIdULZuBbK`
   - Client Secret: `***REMOVED***`
   - **Redirect URIs**: (one per line)
     ```
     http://localhost:8002/auth/callback
     http://localhost/ray-api/auth/callback
     http://${TAILSCALE_IP}/ray-api/auth/callback
     ```
   - Click **Create** and **COPY THE CLIENT ID AND SECRET**

3. **Create Ray Compute Application:**
   - Go to: **Applications** → **Applications** → **Create**
   - **Name**: `Ray Compute`
   - **Slug**: `ray-compute`
   - **Provider**: Select `Ray Compute OAuth Provider`
   - Click **Create**

4. **Create MLflow OAuth Provider:**
   - Repeat above steps with:
   - **Name**: `MLflow OAuth Provider`
   - **Redirect URIs**:
   - Client ID: `txarUgT4aVGqYgLZ5UAeUkDQ6bKL8fQ5uuu1KYVH`
   - Client Secret: `***REMOVED***`
     ```
     http://localhost:8001/auth/callback
     http://localhost/api/v1/auth/callback
     http://${TAILSCALE_IP}/api/v1/auth/callback
     ```

5. **Create MLflow Application:**
   - **Name**: `MLflow`
   - **Slug**: `mlflow`
   - **Provider**: Select `MLflow OAuth Provider`

### Step 2: Configure OAuth Credentials (Automated Script)

```bash
cd /home/axelofwar/Desktop/Projects/ml-platform

# Run configuration script
./configure_oauth.sh

# You'll be prompted for:
# - Ray Compute OAuth Client ID
# - Ray Compute OAuth Client Secret
# - MLflow OAuth Client ID
# - MLflow OAuth Client Secret
```

This script will:
- Update `.env` file with OAuth credentials
- Create secret files in `ray_compute/secrets/`
- Create backups of existing configuration

### Step 3: Enable OAuth and Restart Services

```bash
# Enable OAuth in Ray Compute API
./enable_oauth.sh

# Restart all services
./restart_all.sh

# Wait ~2 minutes for services to start
# Run integration tests
./test_integration.sh
```

## 📝 Testing OAuth

### Get OAuth Token
```bash
# For Ray Compute
curl -X POST http://localhost:9000/application/o/token/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=YOUR_RAY_CLIENT_ID" \
  -d "client_secret=YOUR_RAY_CLIENT_SECRET"

# Save the access_token from response
```

### Use Token to Access Protected Endpoint
```bash
# Test Ray Compute API
curl -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  http://localhost/ray-api/jobs

# Test MLflow API
curl -H "Authorization: Bearer YOUR_MLFLOW_TOKEN" \
  http://localhost/api/v1/experiments
```

## 🔄 MLflow Auto-Logging in Ray Jobs

### Automatic (Default Behavior)

All Ray jobs automatically log to MLflow:

```python
import ray
from ray import job_submission

# Job code automatically logs to MLflow
@ray.remote
def train_model(config):
    # Training code here
    # Metrics automatically logged to MLflow
    return {"accuracy": 0.95, "loss": 0.05}

# Submit job - MLflow logging happens automatically
job_id = job_submission.submit_job(
    entrypoint="python train.py",
    runtime_env={
        "env_vars": {
            "MLFLOW_TRACKING_URI": "http://mlflow-server:5000",
            "MLFLOW_EXPERIMENT_NAME": "Development-Training"
        }
    }
)
```

### Using the MLflow Auto-Logger

```python
from api.mlflow_integration import auto_log_mlflow, log_job_metrics

@auto_log_mlflow(experiment_name="MyExperiment", run_name="job-1")
@ray.remote
def my_training_job(config):
    # Job automatically starts MLflow run
    
    # Your training code
    for epoch in range(10):
        loss = train_one_epoch()
        log_job_metrics({"loss": loss}, step=epoch)
    
    # Job automatically ends MLflow run
    return {"final_loss": loss}
```

### Opt-Out of MLflow Logging

```python
# Option 1: Environment variable (per job)
runtime_env={
    "env_vars": {
        "DISABLE_MLFLOW_LOGGING": "true"
    }
}

# Option 2: Check in code
from api.mlflow_integration import is_mlflow_enabled

if is_mlflow_enabled():
    # Log to MLflow
    pass
```

## 📊 Verify Setup

```bash
# Check all services are healthy
docker ps --format "table {{.Names}}\t{{.Status}}" | grep healthy

# Test OAuth endpoints
curl -s http://localhost:9000/.well-known/openid-configuration | jq

# Test API health with OAuth
docker exec ray-compute-api curl -s http://localhost:8000/ping | jq

# View Authentik logs
docker logs authentik-server --tail 50
```

## 🔧 Troubleshooting

### OAuth token fails
```bash
# Check Authentik is accessible
curl -v http://localhost:9000/

# Check OAuth provider configuration
docker exec authentik-server ak list-providers
```

### MLflow auto-logging not working
```bash
# Check Ray job logs
docker logs ray-head --tail 100

# Verify MLflow tracking URI is set
docker exec ray-compute-api env | grep MLFLOW

# Test MLflow connectivity from Ray
docker exec ray-head curl http://mlflow-server:5000/health
```

### Services not starting
```bash
# Check logs
docker-compose logs -f ray-compute-api
docker-compose logs -f authentik-server

# Verify .env file
cat .env | grep OAUTH
```

## 📚 Additional Resources

- Full guide: `OAUTH_SETUP_GUIDE.md`
- Ray Compute API code: `ray_compute/api/server_v2.py`
- OAuth auth module: `ray_compute/api/auth.py`
- MLflow integration: `ray_compute/api/mlflow_integration.py`
- Authentik docs: https://docs.goauthentik.io/

## 🎯 Next Steps

Once OAuth is configured:

1. **Create test users in Authentik**
   - Directory → Users → Create
   - Assign to ml-engineers or ml-admins group

2. **Test user authentication flow**
   - Login to Ray Dashboard with OAuth
   - Submit job with user credentials

3. **Monitor audit logs**
   - Authentik → System → Audit Log
   - Check authentication events

4. **Configure additional permissions**
   - Set up role-based access control
   - Configure resource quotas per user group

## 💡 Pro Tips

- Use client credentials grant for service-to-service authentication
- Use authorization code flow for user-facing applications
- Store secrets in secrets/ directory (gitignored)
- Rotate OAuth secrets regularly (every 90 days)
- Enable audit logging in Authentik for compliance
- Use HTTPS in production (configure Traefik TLS certificates)
