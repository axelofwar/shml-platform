# Remote Access & Job Submission

Connect to the SHML platform from any machine with Tailscale VPN access. This guide covers
network setup, MLflow experiment tracking, Ray job submission, and monitoring.

---

## Prerequisites

- **Tailscale VPN** installed and connected to the tailnet
- **Python 3.8+** with pip
- **Git** (optional, to clone the repo)

---

## Setup

### 1. Install Client Packages

```bash
pip install mlflow==2.9.2 ray[default]==2.9.0 requests pandas numpy scikit-learn torch
```

Or install the SHML SDK, which bundles these dependencies:

```bash
pip install shml-sdk
```

### 2. Verify Tailscale Connection

```bash
tailscale status
ping <TAILSCALE_IP>
curl http://<TAILSCALE_IP>/api/v1/health
```

### 3. Set Environment Variables

Add to `~/.bashrc` or `~/.zshrc`:

```bash
export MLFLOW_TRACKING_URI="http://<TAILSCALE_IP>/mlflow"
export RAY_ADDRESS="http://<TAILSCALE_IP>:8265"
```

```bash
source ~/.bashrc
```

### 4. Test Connection

```python
import requests

# MLflow
r = requests.get("http://<TAILSCALE_IP>/api/v1/health")
print(r.json())  # {'status': 'healthy', ...}

# Ray
r = requests.get("http://<TAILSCALE_IP>/ray/api/version")
print(r.json())  # {'version': '2.9.0', ...}
```

---

## Service Access

### URL Reference

| Service | URL | Purpose |
|---------|-----|---------|
| **MLflow UI** | `http://<TAILSCALE_IP>/mlflow/` | Experiment tracking dashboard |
| **MLflow API** | `http://<TAILSCALE_IP>/api/2.0/mlflow/` | Standard MLflow REST API |
| **Custom API** | `http://<TAILSCALE_IP>/api/v1/` | Enhanced API endpoints |
| **Ray Dashboard** | `http://<TAILSCALE_IP>/ray/` | Job monitoring & cluster status |
| **Ray Jobs API** | `http://<TAILSCALE_IP>/ray/api/jobs/` | Job submission (via Traefik) |
| **Traefik** | `http://<TAILSCALE_IP>:8090/` | Gateway routing & health |
| **FusionAuth** | `http://<TAILSCALE_IP>:9011/admin/` | OAuth authentication admin |
| **Grafana** | `http://<TAILSCALE_IP>/grafana/` | Metrics dashboards |

!!! warning "Port 8265"
    Ray port 8265 is **not exposed externally**. Always use the Traefik-proxied
    endpoint at `/ray/api/jobs/` for job submission.

### Role-Based Access Control

All services are protected by OAuth2. New users sign in with Google/GitHub and
receive the `viewer` role automatically. Request elevated access from the platform admin.

| Role | Auto-Granted | Can Access |
|------|:---:|------------|
| `viewer` | Yes | Homer dashboard, Grafana |
| `developer` | No | + MLflow, Ray Dashboard/API, Dozzle logs |
| `admin` | No | + Traefik dashboard, Prometheus, system admin |

To request `developer` or `admin` access, contact the platform admin with your
login email and the requested role.

---

## MLflow Usage

### Experiment Tracking

```python
import mlflow
from sklearn.ensemble import RandomForestClassifier
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split

mlflow.set_tracking_uri("http://<TAILSCALE_IP>/mlflow")
mlflow.set_experiment("my-experiment")

iris = load_iris()
X_train, X_test, y_train, y_test = train_test_split(iris.data, iris.target)

with mlflow.start_run(run_name="rf-model"):
    model = RandomForestClassifier(n_estimators=100, max_depth=5)
    model.fit(X_train, y_train)
    accuracy = model.score(X_test, y_test)

    mlflow.log_param("n_estimators", 100)
    mlflow.log_param("max_depth", 5)
    mlflow.log_metric("accuracy", accuracy)
    mlflow.sklearn.log_model(model, "model")
```

### Model Registry

```python
from mlflow.tracking import MlflowClient

client = MlflowClient()
run_id = "your-run-id"

result = mlflow.register_model(f"runs:/{run_id}/model", "iris-classifier")
client.transition_model_version_stage(
    name="iris-classifier", version=result.version, stage="Production"
)

# Load production model
model = mlflow.pyfunc.load_model("models:/iris-classifier/Production")
```

---

## Ray Job Submission

### Via REST API (Recommended)

```python
import requests, time

RAY_URL = "http://<TAILSCALE_IP>/ray"

job_data = {
    "entrypoint": "python train.py",
    "submission_id": f"my-job-{int(time.time())}",
    "runtime_env": {
        "pip": ["mlflow==2.9.2", "scikit-learn"],
        "env_vars": {
            "MLFLOW_TRACKING_URI": "http://mlflow-server:5000"  # internal DNS
        }
    },
    "metadata": {"project": "my-project"}
}

r = requests.post(f"{RAY_URL}/api/jobs/", json=job_data, timeout=10)
job_id = r.json().get("submission_id")
print(f"Submitted: {job_id}")

# Poll for completion
while True:
    status = requests.get(f"{RAY_URL}/api/jobs/{job_id}", timeout=5).json()
    print(f"Status: {status.get('status')}")
    if status.get("status") in ("SUCCEEDED", "FAILED", "STOPPED"):
        break
    time.sleep(5)

# Retrieve logs
logs = requests.get(f"{RAY_URL}/api/jobs/{job_id}/logs", timeout=5).json()
print(logs.get("logs", ""))
```

### Via Python Client

```python
from ray.job_submission import JobSubmissionClient
import time

client = JobSubmissionClient("http://<TAILSCALE_IP>/ray/api")

job_id = client.submit_job(
    entrypoint="python train.py",
    runtime_env={
        "working_dir": "/path/to/local/scripts",
        "pip": ["torch", "numpy", "pandas"],
    },
    submission_id=f"training_{int(time.time())}",
    entrypoint_num_gpus=1,
    entrypoint_num_cpus=4,
    metadata={"project": "my-project"},
)
print(f"Dashboard: http://<TAILSCALE_IP>/ray/#/jobs/{job_id}")
```

### Via Ray CLI

```bash
ray job submit \
  --address http://<TAILSCALE_IP>/ray/api \
  --working-dir /path/to/local/scripts \
  --runtime-env-json '{"pip": ["torch"]}' \
  --num-gpus 1 \
  -- python training_script.py

ray job list   --address http://<TAILSCALE_IP>/ray/api
ray job status <job-id> --address http://<TAILSCALE_IP>/ray/api
ray job logs   <job-id> --address http://<TAILSCALE_IP>/ray/api
```

### Via SHML SDK CLI

```bash
# Submit a training job with a resource profile
shml train --profile balanced

# Submit with explicit resource requests
shml train --gpus 1 --cpus 4 --script train.py

# Check job status
shml jobs list
shml jobs status <job-id>
shml jobs logs <job-id>
```

!!! tip "Internal DNS for MLflow"
    When your training code runs **inside** the Ray cluster, use the internal
    Docker DNS name for MLflow:

    ```python
    mlflow.set_tracking_uri("http://mlflow-server:5000")   # correct inside Ray
    # mlflow.set_tracking_uri("http://<TAILSCALE_IP>/mlflow")  # wrong inside Ray
    ```

### GPU Training Example

```python
# gpu_train.py — submit via any method above
import ray, mlflow, torch, torch.nn as nn

@ray.remote(num_gpus=1)
def train_on_gpu(epochs=10):
    mlflow.set_tracking_uri("http://mlflow-server:5000")
    mlflow.set_experiment("gpu-training")

    with mlflow.start_run():
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        mlflow.log_param("device", str(device))
        mlflow.log_param("epochs", epochs)

        if torch.cuda.is_available():
            mlflow.log_param("gpu", torch.cuda.get_device_name(0))

        model = nn.Linear(10, 1).to(device)
        # ... training loop ...

        mlflow.log_metric("loss", 0.05)
    return "done"

if __name__ == "__main__":
    ray.init()
    print(ray.get(train_on_gpu.remote(epochs=10)))
```

---

## Uploading Training Data

### Option 1 — Bundle in `working_dir`

The entire directory is uploaded to the cluster automatically:

```python
job_id = client.submit_job(
    entrypoint="python train.py",
    runtime_env={"working_dir": "/path/to/my_training"},
    entrypoint_num_gpus=1,
)
```

### Option 2 — SCP Transfer (Large Datasets)

```bash
scp -r ./my_dataset/ axelofwar@<TAILSCALE_IP>:/path/to/shared/storage/
```

Then reference the server-side path in your job's `entrypoint`.

---

## Monitoring

| Dashboard | URL | Shows |
|-----------|-----|-------|
| Ray Dashboard | `http://<TAILSCALE_IP>/ray/#/jobs` | Job status, GPU utilization, logs |
| Ray Grafana | `http://<TAILSCALE_IP>/ray-grafana/` | GPU/CPU/memory over time |
| MLflow UI | `http://<TAILSCALE_IP>/mlflow/` | Experiments, runs, model registry |
| Prometheus | `http://<TAILSCALE_IP>/prometheus/` | Raw metrics (admin only) |

---

## Hardware & Resources

| Component | Spec |
|-----------|------|
| CPU | AMD Ryzen 9 3900X (24 threads) — 8 cores allocated to Ray |
| RAM | 16 GB (shared across all services) |
| GPU 0 | NVIDIA RTX 3090 Ti (24 GB VRAM) — primary training |
| GPU 1 | NVIDIA RTX 2070 (8 GB VRAM) — secondary / fallback |
| Storage | Local NVMe |
| Network | Gigabit LAN; Tailscale adds ~5–10 ms latency |

!!! warning "Memory is the primary bottleneck"
    16 GB of RAM is shared across all platform services. Monitor usage in Grafana
    and avoid scheduling jobs that exceed available headroom.

---

## Administration (Host Only)

```bash
cd /home/axelofwar/Projects/shml-platform
sudo bash ./start_all_safe.sh          # start
sudo docker compose down               # stop
sudo docker compose restart mlflow-server  # restart one service
sudo docker compose logs -f ray-head   # tail logs
sudo docker exec ray-head nvidia-smi   # GPU status
sudo docker exec ray-head ray status   # cluster status
```

---

## Troubleshooting

### Cannot Connect

```bash
tailscale status                              # VPN up?
ping <TAILSCALE_IP>                           # host reachable?
curl -I http://<TAILSCALE_IP>/api/v1/health   # services responding?
```

If services are down, SSH into the host and check containers:

```bash
sudo docker compose ps
```

### MLflow Issues

```bash
python -c "import mlflow; print(mlflow.get_tracking_uri())"

curl -X POST http://<TAILSCALE_IP>/api/2.0/mlflow/experiments/search \
  -H "Content-Type: application/json" -d '{"max_results": 1}'
```

### Ray Job Failures

1. Check the Ray dashboard for error details.
2. Retrieve logs:

    ```bash
    ray job logs <job-id> --address http://<TAILSCALE_IP>/ray/api
    ```

3. Verify all pip dependencies are listed in `runtime_env["pip"]`.

### GPU Not Available

```bash
sudo docker exec ray-head nvidia-smi
sudo docker exec ray-head ray status
```

!!! tip
    Ensure `entrypoint_num_gpus=1` is set when submitting GPU jobs. If all GPUs
    are occupied, the job will queue until one is released.

---

## Credentials

Sensitive credentials (database passwords, Grafana logins, OAuth secrets) are
stored in `REMOTE_ACCESS_COMPLETE.sh` on the host machine. This file is
**git-ignored** and should never be committed.

---

## Further Reading

- [Architecture](../architecture/index.md)
- [API Reference](../api/index.md)
- [SDK Reference](../sdk/index.md)
- [Troubleshooting](troubleshooting.md)
