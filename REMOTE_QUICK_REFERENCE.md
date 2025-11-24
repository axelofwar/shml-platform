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

| Service | URL | Purpose |
|---------|-----|---------|
| **MLflow UI** | `http://${TAILSCALE_IP}/mlflow/` | Experiment tracking UI |
| **MLflow API** | `http://${TAILSCALE_IP}/api/2.0/mlflow/` | Standard REST API |
| **Custom API** | `http://${TAILSCALE_IP}/api/v1/` | Enhanced API endpoints |
| **Ray Dashboard** | `http://${TAILSCALE_IP}/ray/` | Job monitoring |
| **Ray Jobs** | `http://${TAILSCALE_IP}:8265` | Job submission endpoint |
| **Traefik** | `http://${TAILSCALE_IP}:8090` | Gateway dashboard |

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

```python
from ray.job_submission import JobSubmissionClient

client = JobSubmissionClient("http://${TAILSCALE_IP}:8265")

# Submit job
job_id = client.submit_job(
    entrypoint="python train.py",
    runtime_env={
        "working_dir": "./",
        "pip": ["mlflow==2.9.2", "scikit-learn"],
        "env_vars": {
            "MLFLOW_TRACKING_URI": "http://mlflow-server:5000"  # Internal DNS
        }
    }
)

print(f"Job submitted: {job_id}")
print(f"Monitor at: http://${TAILSCALE_IP}/ray/#/jobs/{job_id}")

# Check status
status = client.get_job_status(job_id)
print(f"Status: {status}")

# Get logs
logs = client.get_job_logs(job_id)
print(logs)
```

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

### Ray API

```bash
# List jobs
curl http://${TAILSCALE_IP}:8265/api/jobs

# Get job status
curl http://${TAILSCALE_IP}:8265/api/jobs/<job-id>

# Cluster info
curl http://${TAILSCALE_IP}:8265/api/version
```

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
