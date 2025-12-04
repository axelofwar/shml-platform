# ML Platform - Remote Access Guide
**Updated:** 2025-11-24  
**Host Machine:** axelofwar-server  
**Status:** ✅ FULLY OPERATIONAL - All services running with dual GPU support

---

## 🌐 Network Configuration

```bash
# Local Network
LAN_IP=10.0.0.163
HOSTNAME=axelofwar-server

# Tailscale VPN (Recommended for remote access)
TAILSCALE_IP=<TAILSCALE_IP>
```

---

## 🔗 Service Access URLs

### Via Tailscale VPN (Recommended)
| Service | URL | Purpose |
|---------|-----|---------|
| **MLflow UI** | `http://<TAILSCALE_IP>/mlflow/` | Experiment tracking dashboard |
| **MLflow API** | `http://<TAILSCALE_IP>/api/2.0/mlflow/` | Standard MLflow REST API |
| **Ray Dashboard** | `http://<TAILSCALE_IP>/ray/` | Job monitoring & cluster status |
| **Traefik Dashboard** | `http://<TAILSCALE_IP>:8090/` | Gateway routing & health |
| **FusionAuth** | `http://<TAILSCALE_IP>:9011/admin/` | OAuth authentication |

### Via Local Network
Replace `<TAILSCALE_IP>` with `10.0.0.163` in the URLs above.

---

## 🔐 Credentials

### MLflow Database
- **Host:** <TAILSCALE_IP>:5432
- **Database:** mlflow_db
- **User:** mlflow
- **Password:** `gNz8APgrUF8Q3hMe2sQXQK8DPGHs3CGcVhoPLbcqvi4=`

### MLflow Grafana
- **URL:** http://<TAILSCALE_IP>/grafana/
- **User:** admin
- **Password:** `<your-password-from-.env>`

### Ray Database
- **Host:** <TAILSCALE_IP>:5433
- **Database:** ray_compute
- **User:** ray_compute
- **Password:** `VlzT9Rg374pYWpjUGGV3QSUTWg7JVdhl`

### Ray Grafana
- **URL:** http://<TAILSCALE_IP>/ray-grafana/
- **User:** admin
- **Password:** `oVkbwOk7AtELl2xz`

### FusionAuth OAuth
- **URL:** http://<TAILSCALE_IP>:9011/admin/
- **Public URL:** https://shml-platform.tail38b60a.ts.net/auth/admin/
- **Admin Login:** Email-based (configured during setup)
- **Social Logins:** Google, GitHub, Twitter supported
- **Client ID:** ray-compute-api (or configured application ID)
- **OAuth Endpoints:** `/oauth2/authorize`, `/oauth2/token`

---

## 🔒 Role-Based Access Control

All services are protected by OAuth2 authentication. Access is controlled via roles.

### Access Tiers

| Role | Default | Can Access |
|------|---------|------------|
| `viewer` | ✅ Auto-assigned | Homer dashboard, Grafana |
| `developer` | ❌ Admin grants | + MLflow, Ray Dashboard/API, Dozzle logs |
| `admin` | ❌ Admin grants | + Traefik dashboard, Prometheus, System admin |

### Service Access Matrix

| Service | URL | Required Role |
|---------|-----|---------------|
| **Homer Dashboard** | `/` | `viewer` ✅ |
| **Grafana** | `/grafana/` | `viewer` ✅ |
| **MLflow UI** | `/mlflow/` | `developer` |
| **MLflow API** | `/api/2.0/mlflow/` | `developer` |
| **Ray Dashboard** | `/ray/` | `developer` |
| **Ray API** | `/api/ray/` | `developer` |
| **Dozzle Logs** | `/logs/` | `developer` |
| **Traefik Dashboard** | `/traefik/` | `admin` |
| **Prometheus** | `/prometheus/` | `admin` |

### New User Workflow

1. **Sign in with Google/GitHub** at https://shml-platform.tail38b60a.ts.net/
2. **Auto-registered** with `viewer` role → Can see Homer dashboard and Grafana
3. **Request elevated access** from platform admin
4. **Admin grants role** via FusionAuth Admin UI → User gets full access

### Requesting Developer/Admin Access

Contact platform admin with:
- Your email address (used for Google/GitHub login)
- Requested role (`developer` or `admin`)
- Reason for access

Admin will update your role in FusionAuth → Users → [Your Account] → Registrations → OAuth2-Proxy

---

## 🎮 GPU Configuration

**Hardware:**
- **GPU 0:** NVIDIA GeForce RTX 3090 Ti (24GB VRAM)
- **GPU 1:** NVIDIA GeForce RTX 2070 (8GB VRAM)

**Ray Cluster Resources:**
- **CPUs:** 8 cores allocated
- **GPUs:** 2 GPUs available for job scheduling
- **Object Store:** 512MB
- **GPU Sharing:** NVIDIA MPS enabled for multi-process access

---

## ⚡ Quick Start

### 1. Install Client Packages

```bash
pip install mlflow==2.9.2 ray[default]==2.9.0 requests pandas numpy scikit-learn torch
```

### 2. Set Environment Variables

```bash
# Add to ~/.bashrc or ~/.zshrc
export MLFLOW_TRACKING_URI="http://<TAILSCALE_IP>/mlflow"
export RAY_ADDRESS="http://<TAILSCALE_IP>:8265"

# Apply changes
source ~/.bashrc
```

### 3. Test Connection

```python
import requests
import mlflow

# Test MLflow
response = requests.get("http://<TAILSCALE_IP>/api/2.0/mlflow/experiments/search",
                       headers={"Content-Type": "application/json"},
                       json={"max_results": 1})
print(f"MLflow Status: {response.status_code}")
print(f"Experiments: {len(response.json().get('experiments', []))}")

# Test Ray
response = requests.get("http://<TAILSCALE_IP>:8265/api/version")
print(f"Ray Version: {response.json()}")
```

---

## 📊 MLflow Usage Examples

### Basic Experiment Tracking

```python
import mlflow
from sklearn.ensemble import RandomForestClassifier
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split

# Configure tracking
mlflow.set_tracking_uri("http://<TAILSCALE_IP>/mlflow")
mlflow.set_experiment("my-experiment")

# Load data
iris = load_iris()
X_train, X_test, y_train, y_test = train_test_split(iris.data, iris.target)

# Train and log
with mlflow.start_run(run_name="rf-model"):
    model = RandomForestClassifier(n_estimators=100, max_depth=5)
    model.fit(X_train, y_train)

    accuracy = model.score(X_test, y_test)

    mlflow.log_param("n_estimators", 100)
    mlflow.log_param("max_depth", 5)
    mlflow.log_metric("accuracy", accuracy)
    mlflow.sklearn.log_model(model, "model")

    print(f"✅ Logged with accuracy: {accuracy:.4f}")
```

### Model Registry

```python
import mlflow
from mlflow.tracking import MlflowClient

mlflow.set_tracking_uri("http://<TAILSCALE_IP>/mlflow")
client = MlflowClient()

# Register model
model_name = "iris-classifier"
run_id = "your-run-id"  # Get from UI or previous run
model_uri = f"runs:/{run_id}/model"

result = mlflow.register_model(model_uri, model_name)
print(f"Registered: {model_name} version {result.version}")

# Promote to production
client.transition_model_version_stage(
    name=model_name,
    version=result.version,
    stage="Production"
)

# Load production model
model = mlflow.pyfunc.load_model(f"models:/{model_name}/Production")
predictions = model.predict(X_test)
```

---

## 🚀 Ray Job Submission

### Simple Job Submission

```python
from ray.job_submission import JobSubmissionClient

# Connect to cluster
client = JobSubmissionClient("http://<TAILSCALE_IP>:8265")

# Submit job
job_id = client.submit_job(
    entrypoint="python train.py",
    runtime_env={
        "working_dir": "./",
        "pip": ["mlflow==2.9.2", "scikit-learn", "pandas"]
    }
)

print(f"Job ID: {job_id}")
print(f"Monitor: http://<TAILSCALE_IP>/ray/#/jobs/{job_id}")

# Wait for completion
import time
while True:
    status = client.get_job_status(job_id)
    print(f"Status: {status}")
    if status in ["SUCCEEDED", "FAILED", "STOPPED"]:
        break
    time.sleep(5)

# Get logs
logs = client.get_job_logs(job_id)
print(logs)
```

### GPU Job with MLflow Tracking

```python
# Save as: gpu_train.py
import ray
import mlflow
import torch
import torch.nn as nn

@ray.remote(num_gpus=1)  # Request 1 GPU
def train_on_gpu(epochs=10):
    # Set MLflow tracking (use internal DNS)
    mlflow.set_tracking_uri("http://mlflow-server:5000")
    mlflow.set_experiment("gpu-training")

    with mlflow.start_run():
        # Check GPU availability
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {device}")

        if torch.cuda.is_available():
            print(f"GPU: {torch.cuda.get_device_name(0)}")
            mlflow.log_param("gpu", torch.cuda.get_device_name(0))

        # Your training code here
        model = nn.Linear(10, 1).to(device)

        mlflow.log_param("epochs", epochs)
        mlflow.log_param("device", str(device))

        print("✅ Training complete")
        return "Success"

if __name__ == "__main__":
    ray.init()
    result = ray.get(train_on_gpu.remote(epochs=10))
    print(result)
```

Submit from remote machine:

```python
from ray.job_submission import JobSubmissionClient

client = JobSubmissionClient("http://<TAILSCALE_IP>:8265")

job_id = client.submit_job(
    entrypoint="python gpu_train.py",
    runtime_env={
        "working_dir": "./",
        "pip": ["mlflow==2.9.2", "torch"],
        "env_vars": {
            "CUDA_VISIBLE_DEVICES": "0"  # Use GPU 0 (RTX 3090 Ti)
        }
    }
)

print(f"GPU Job submitted: {job_id}")
```

---

## 🔍 System Status Commands

### Check Platform Health

```bash
# On the host machine
cd /home/axelofwar/Projects/shml-platform

# View all containers
sudo docker compose ps

# Check specific service logs
sudo docker compose logs -f mlflow-server
sudo docker compose logs -f ray-head

# Check GPU usage
sudo docker exec ray-head nvidia-smi
```

### Ray Cluster Info

```bash
# On host machine
sudo docker exec ray-head ray status

# From remote Python client
from ray.job_submission import JobSubmissionClient
client = JobSubmissionClient("http://<TAILSCALE_IP>:8265")
print(client.get_version())
```

---

## 🛠️ Management Commands

### Start/Stop Services

```bash
# Start all services
cd /home/axelofwar/Projects/shml-platform
sudo bash ./start_all_safe.sh

# Stop all services
sudo docker compose down

# Restart specific service
sudo docker compose restart mlflow-server

# View logs
sudo docker compose logs -f [service-name]
```

### Update Configuration

```bash
# After changing docker-compose.yml
sudo docker compose up -d --force-recreate [service-name]

# Rebuild specific service
sudo docker compose build [service-name]
sudo docker compose up -d [service-name]
```

---

## 🔧 Troubleshooting

### Can't Connect

1. **Check Tailscale:**
   ```bash
   tailscale status
   ping <TAILSCALE_IP>
   ```

2. **Test Basic Connectivity:**
   ```bash
   curl -I http://<TAILSCALE_IP>/mlflow/
   ```

3. **Check Service Status:**
   ```bash
   sudo docker compose ps
   ```

### MLflow Issues

```bash
# Check MLflow logs
sudo docker compose logs mlflow-server

# Test API directly
curl -X POST http://<TAILSCALE_IP>/api/2.0/mlflow/experiments/search \
  -H "Content-Type: application/json" \
  -d '{"max_results": 1}'
```

### Ray Job Issues

```bash
# Check Ray logs
sudo docker compose logs ray-head

# View job logs via Python
from ray.job_submission import JobSubmissionClient
client = JobSubmissionClient("http://<TAILSCALE_IP>:8265")
print(client.get_job_logs("your-job-id"))
```

### GPU Not Available

```bash
# Check GPUs are visible
sudo docker exec ray-head nvidia-smi

# Check Ray sees GPUs
sudo docker exec ray-head ray status

# Restart NVIDIA MPS if needed
sudo systemctl restart nvidia-mps
```

---

## 📈 Performance Notes

- **CPU:** Ryzen 9 3900X (24 threads) - 8 cores allocated to Ray
- **RAM:** 16GB total - Services optimized via resource manager
- **Network:** Gigabit LAN, Tailscale VPN adds ~5-10ms latency
- **Storage:** Local NVMe for artifacts - very fast I/O

**Bottleneck Analysis:**
- **Memory** is the primary constraint (16GB shared across all services)
- **GPU Memory:** RTX 3090 Ti (24GB) can handle large models, RTX 2070 (8GB) for smaller workloads
- **Network:** Tailscale VPN is fast for most ML workloads

---

## 📚 Additional Documentation

- **Architecture:** `/home/axelofwar/Projects/shml-platform/ARCHITECTURE.md`
- **API Reference:** `/home/axelofwar/Projects/shml-platform/API_REFERENCE.md`
- **Troubleshooting:** `/home/axelofwar/Projects/shml-platform/TROUBLESHOOTING.md`
- **GPU Setup:** `/home/axelofwar/Projects/shml-platform/NEW_GPU_SETUP.md`

---

## ✅ Verified Working

- ✅ MLflow tracking and model registry
- ✅ Ray job submission with GPU support
- ✅ Dual GPU allocation (RTX 3090 Ti + RTX 2070)
- ✅ Traefik unified routing
- ✅ Tailscale VPN access
- ✅ All monitoring dashboards (Grafana, Prometheus)
- ✅ FusionAuth OAuth with social logins (Google, GitHub, Twitter)

**Platform Version:** 2.0  
**Last Tested:** 2025-11-24  
**All Systems:** Operational ✅
