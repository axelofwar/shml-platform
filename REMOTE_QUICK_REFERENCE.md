# ML Platform - Remote Access Quick Reference

**Last Updated:** 2025-11-23  
**Status:** ✅ FULLY OPERATIONAL

> **⚠️ IMPORTANT:** For complete details with credentials, see `REMOTE_ACCESS_COMPLETE.sh` (git-ignored)

---

## 🌐 Access Points

```bash
# Recommended: Tailscale VPN
PLATFORM_HOST="${TAILSCALE_IP}"

# Alternative: Local Network
PLATFORM_HOST="${SERVER_IP}"
```

---

## 🔗 Service URLs

| Service           | URL                                      | Purpose                          |
| ----------------- | ---------------------------------------- | -------------------------------- |
| **MLflow UI**     | `http://${TAILSCALE_IP}/mlflow/`         | Experiment tracking UI           |
| **MLflow API**    | `http://${TAILSCALE_IP}/api/2.0/mlflow/` | Standard REST API                |
| **Custom API**    | `http://${TAILSCALE_IP}/api/v1/`         | Enhanced API endpoints           |
| **Ray Dashboard** | `http://${TAILSCALE_IP}/ray/`            | Job monitoring                   |
| **Ray Jobs API**  | `http://${TAILSCALE_IP}/ray/api/jobs/`   | Job submission (**via Traefik**) |
| **Traefik**       | `http://${TAILSCALE_IP}:8090`            | Gateway dashboard                |

> **Note:** Port 8265 is NOT exposed. Use the Traefik-proxied endpoint at `/ray/api/jobs/`.

---

## ⚡ Quick Start

### 1. Install Packages

```bash
pip install mlflow==2.9.2 ray[default]==2.9.0 requests pandas numpy scikit-learn
```

### 2. Set Environment

```bash
export MLFLOW_TRACKING_URI="http://${TAILSCALE_IP}/mlflow"
export RAY_ADDRESS="http://${TAILSCALE_IP}:8265"
```

### 3. Test Connection

```python
import requests

# Test MLflow
response = requests.get("http://${TAILSCALE_IP}/api/v1/health")
print(response.json())  # {'status': 'healthy', ...}

# Test Ray
response = requests.get("http://${TAILSCALE_IP}:8265/api/version")
print(response.json())  # {'version': '2.9.0', ...}
```

---

## 📊 MLflow Example

```python
import mlflow
from sklearn.ensemble import RandomForestClassifier
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split

# Configure
mlflow.set_tracking_uri("http://${TAILSCALE_IP}/mlflow")
mlflow.set_experiment("my-experiment")

# Train and log
iris = load_iris()
X_train, X_test, y_train, y_test = train_test_split(iris.data, iris.target)

with mlflow.start_run():
    model = RandomForestClassifier(n_estimators=100)
    model.fit(X_train, y_train)

    accuracy = model.score(X_test, y_test)

    mlflow.log_param("n_estimators", 100)
    mlflow.log_metric("accuracy", accuracy)
    mlflow.sklearn.log_model(model, "model")

print(f"✓ Logged to http://${TAILSCALE_IP}/mlflow/")
```

---

## 🚀 Ray Job Submission

### Via REST API (Recommended)

Port 8265 is not exposed externally. Use the Traefik-proxied Jobs API:

```python
import requests
import time

RAY_URL = "http://${TAILSCALE_IP}/ray"

# Submit a job
job_id = f"my-job-{int(time.time())}"
job_data = {
    "entrypoint": "python train.py",
    "submission_id": job_id,
    "runtime_env": {
        "pip": ["mlflow==2.9.2", "scikit-learn"],
        "env_vars": {
            "MLFLOW_TRACKING_URI": "http://mlflow-server:5000"  # Internal DNS
        }
    },
    "metadata": {"project": "my-project"}
}

response = requests.post(f"{RAY_URL}/api/jobs/", json=job_data, timeout=10)
result = response.json()
print(f"Submitted: {result.get('submission_id')}")

# Check status
time.sleep(2)
status = requests.get(f"{RAY_URL}/api/jobs/{job_id}", timeout=5).json()
print(f"Status: {status.get('status')}")

# Get logs
logs = requests.get(f"{RAY_URL}/api/jobs/{job_id}/logs", timeout=5).json()
print(f"Logs: {logs.get('logs', '')}")
```

### Via Ray JobSubmissionClient (Requires Port 8265)

> **Note:** This method does NOT work currently as port 8265 is not exposed.

```python
# This will NOT work without port 8265 access:
from ray.job_submission import JobSubmissionClient
client = JobSubmissionClient("http://${TAILSCALE_IP}:8265")  # ❌ Port not exposed
```

### ⚠️ Known Issue: GPU Access in Job Containers

Ray job containers currently **don't have GPU passthrough**:

- Main Ray container: Has GPU access ✅
- Job containers: No CUDA available ❌

Until this is fixed on the server, GPU training jobs will fail.

---

## 🔍 Key Endpoints

### MLflow REST API

```bash
# Create experiment
curl -X POST http://${TAILSCALE_IP}/api/2.0/mlflow/experiments/create \
  -H "Content-Type: application/json" \
  -d '{"name": "my-experiment"}'

# Search runs
curl -X POST http://${TAILSCALE_IP}/api/2.0/mlflow/runs/search \
  -H "Content-Type: application/json" \
  -d '{"max_results": 10}'
```

### Custom API

```bash
# Health check
curl http://${TAILSCALE_IP}/api/v1/health

# List experiments
curl http://${TAILSCALE_IP}/api/v1/experiments

# Get experiment details
curl http://${TAILSCALE_IP}/api/v1/experiments/1
```

### Ray API (via Traefik)

```bash
# List jobs
curl http://${TAILSCALE_IP}/ray/api/jobs/

# Submit job
curl -X POST http://${TAILSCALE_IP}/ray/api/jobs/ \
  -H "Content-Type: application/json" \
  -d '{"entrypoint": "echo hello", "submission_id": "test-123"}'

# Get job status
curl http://${TAILSCALE_IP}/ray/api/jobs/<job-id>

# Get job logs
curl http://${TAILSCALE_IP}/ray/api/jobs/<job-id>/logs

# Cluster version
curl http://${TAILSCALE_IP}/ray/api/version

# Cluster status
curl http://${TAILSCALE_IP}/ray/api/cluster_status
```

> **Note:** Direct port 8265 access (e.g., `http://${TAILSCALE_IP}:8265/api/jobs`) is NOT available.
> Always use the Traefik-proxied endpoint at `/ray/api/`.

---

## 💡 Important Notes

### For Ray Jobs (running on cluster):

Use **internal Docker DNS** for MLflow:

```python
MLFLOW_TRACKING_URI = "http://mlflow-server:5000"  # ✅ Correct
```

NOT external URL:

```python
MLFLOW_TRACKING_URI = "http://${TAILSCALE_IP}/mlflow"  # ❌ Wrong from inside Ray
```

### GPU Jobs

```python
import ray

@ray.remote(num_gpus=1)  # Request 1 GPU
def train_on_gpu():
    # Your GPU code here
    pass
```

System has: **1x NVIDIA RTX 2070 (8GB VRAM)**

### Resource Limits

- Ray Head: 4 CPUs, 4GB RAM, 1GB object store
- Host: Ryzen 9 3900X (24 threads), 16GB RAM, RTX 2070

---

## 🔐 Credentials

**See `REMOTE_ACCESS_COMPLETE.sh` for:**

- Database passwords
- Grafana credentials
- OAuth secrets
- All sensitive information

**File is git-ignored and contains ALL credentials needed for remote access.**

---

## 📚 Documentation

On platform host machine:

- `ARCHITECTURE.md` - System design
- `API_REFERENCE.md` - Complete API docs
- `RAY_JOB_SUBMISSION_GUIDE.md` - Ray usage
- `TROUBLESHOOTING.md` - Common issues
- `LESSONS_LEARNED.md` - Best practices
- `REMOTE_ACCESS_COMPLETE.sh` - **Complete reference with credentials**

---

## ❓ Troubleshooting

### Can't connect?

1. Check Tailscale: `tailscale status`
2. Test basic connectivity: `ping ${TAILSCALE_IP}`
3. Try curl: `curl http://${TAILSCALE_IP}/api/v1/health`

### MLflow not working?

```bash
# Verify tracking URI
python -c "import mlflow; print(mlflow.get_tracking_uri())"

# Test API
curl -X POST http://${TAILSCALE_IP}/api/2.0/mlflow/experiments/search \
  -H "Content-Type: application/json" -d '{"max_results": 1}'
```

### Ray job stuck?

1. Check Ray dashboard: http://${TAILSCALE_IP}/ray/
2. View job logs in dashboard or via API
3. Check resource availability (may be exhausted)

---

## 🎯 Next Steps

1. **Install packages:** `pip install mlflow ray[default] requests`
2. **Set environment:** Add exports to `~/.bashrc`
3. **Run test:** Use connection test from `REMOTE_ACCESS_COMPLETE.sh`
4. **Start experimenting:** Use examples above
5. **Read full docs:** See `REMOTE_ACCESS_COMPLETE.sh` for everything

---

**Platform Status:** ✅ All 16 services healthy  
**Response Time:** MLflow API ~10ms, Ray submission instant  
**Uptime:** Stable, auto-restart enabled

**For complete reference including all credentials:**

```bash
cat REMOTE_ACCESS_COMPLETE.sh | less
```
