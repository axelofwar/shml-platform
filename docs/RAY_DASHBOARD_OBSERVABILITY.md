# Ray Dashboard SOTA Observability - Implementation Guide

**Last Updated:** December 9, 2025
**Status:** Items 1-8 Implemented, 9-10 Documented for Future

---

## ✅ Implemented Features (1-8)

### 1. Enhanced Job Metadata ✅

**Location:** `/ray_compute/data/job_workspaces/submit_face_detection_job.py`

**What It Does:**
- Adds rich metadata to every Ray job submission
- Visible in Ray Dashboard under "Job Details"
- Includes lineage tracking, cost estimates, performance targets

**Metadata Fields:**
```python
{
    # Training Configuration
    "base_model": "yolov8l.pt",
    "total_epochs": 100,
    "curriculum_stages": "4 stages",

    # Lineage & Traceability
    "parent_job_id": "job-abc123",  # For resumed jobs
    "checkpoint_restored_from": "/path/to/checkpoint.pt",
    "dataset_version": "1.2",

    # Performance Targets
    "target_metric": "mAP50 >= 0.90",
    "estimated_runtime_hours": 33.0,

    # Cost Tracking
    "gpu_cost_per_hour": 0.50,
    "estimated_total_cost": 16.50,
    "budget_alert_threshold": 10.0,

    # Output Locations
    "checkpoint_dir_container": "/tmp/ray/checkpoints/face_detection",
    "checkpoint_dir_host": "/home/axelofwar/.../ray_compute/data/ray/checkpoints",

    # Observability
    "mlflow_ui_url": "http://localhost:8080/#/experiments/...",
    "grafana_dashboard_url": "http://localhost/grafana/d/ray-cluster/...",
}
```

**How to Use:**
```bash
# Submit job with enhanced metadata
python submit_face_detection_job.py --epochs 100 --model yolov8l.pt

# View metadata in Ray Dashboard
# → Navigate to http://localhost/ray/#/jobs/{job_id}
# → Click "Job Details" tab
# → Scroll to "Metadata" section
```

---

### 2. Real-Time Training Metrics Stream ✅

**Location:** `/ray_compute/data/job_workspaces/ray_metrics_reporter.py`

**What It Does:**
- Emits live training metrics to Ray's Prometheus endpoint
- Updates every epoch with loss, mAP, GPU usage
- Visualized in Grafana dashboards

**Metrics Emitted:**
- `training_training_loss` - Current loss (Gauge)
- `training_map50` - mAP@0.50 (Gauge)
- `training_map50_95` - mAP@0.50:0.95 (Gauge)
- `training_precision` - Model precision (Gauge)
- `training_recall` - Model recall (Gauge)
- `training_gpu_utilization` - GPU usage % (Gauge)
- `training_gpu_vram_used_gb` - VRAM in GB (Gauge)
- `training_epoch_current` - Current epoch (Gauge)
- `training_cost_usd` - Running cost (Gauge)
- `training_data_load_time_ms` - Data loading time (Histogram)
- `training_epochs_completed_total` - Epochs done (Counter)

**How to Use in Training Script:**
```python
from ray_metrics_reporter import RayMetricsReporter

# Initialize at start of training
reporter = RayMetricsReporter(job_name="face_detection")

# Report metrics after each epoch
reporter.report_training_metrics(
    epoch=epoch,
    loss=results.box.loss,
    mAP50=results.box.map50,
    mAP50_95=results.box.map,
    precision=results.box.mp,
    recall=results.box.mr,
    total_epochs=100,
    phase="phase_1"
)

# Report GPU metrics
reporter.report_gpu_metrics(
    gpu_util=0.95,
    vram_used_gb=18.5,
    temperature=72.0,
    gpu_id="0"
)

# Report cost
gpu_hours = reporter.get_runtime_hours()
cost = gpu_hours * 0.50
reporter.report_cost(gpu_hours=gpu_hours, cost_usd=cost)
```

**Visualization:**
- Grafana Dashboard: `http://localhost/grafana/d/training-resource-heatmaps/`
- Prometheus Metrics: `http://localhost:9090/graph?g0.expr=training_map50`

---

### 3. Automated Checkpoint Snapshotting with Metadata 📝

**Status:** Documented (Not Yet Implemented)

**What It Would Do:**
- Save checkpoint metadata to Ray's metadata store
- Include resume commands, metrics snapshot, storage locations
- Enable one-click resume from Ray Dashboard

**Implementation Plan:**
```python
# In CheckpointManager class
import ray
from ray import serve

class CheckpointManager:
    def save_with_metadata(self, checkpoint_path: str, metrics: dict):
        """Save checkpoint with rich metadata for resumability."""

        # Get Ray context
        ctx = ray.get_runtime_context()
        job_id = ctx.get_job_id()

        # Prepare metadata
        checkpoint_meta = {
            "job_id": job_id,
            "checkpoint_path_container": checkpoint_path,
            "checkpoint_path_host": checkpoint_path.replace("/tmp/ray",
                "/home/axelofwar/.../ray_compute/data/ray"),
            "timestamp": datetime.now().isoformat(),
            "metrics": metrics,  # mAP50, loss, epoch, etc.
            "resume_command": (
                f"python submit_face_detection_job.py "
                f"--resume-weights {checkpoint_path} "
                f"--epochs {100 - metrics['epoch']}"
            ),
            "file_size_mb": os.path.getsize(checkpoint_path) / 1024 / 1024,
        }

        # Save to Ray metadata store (experimental API)
        ray.experimental.state.api.put_object(
            f"checkpoint_meta_{job_id}_{metrics['epoch']}",
            checkpoint_meta
        )

        print(f"✓ Checkpoint metadata saved: {checkpoint_meta['resume_command']}")
        return checkpoint_meta

# Usage in training loop
checkpoint_mgr.save_with_metadata(
    checkpoint_path="/tmp/ray/checkpoints/face_detection/phase_1/weights/best.pt",
    metrics={"epoch": 30, "mAP50": 0.744, "loss": 0.5}
)
```

**Ray Dashboard Integration:**
- Would show list of checkpoints with metrics in Job Details
- "Resume from Checkpoint" button copies command to clipboard
- Checkpoint browser shows file sizes, timestamps, metrics

---

### 4. Cost Tracking Dashboard ✅

**Location:** `/monitoring/grafana/dashboards/training/training-cost-tracking.json`

**What It Does:**
- Real-time cost monitoring per job
- Budget alerts at configurable thresholds
- Cost per epoch analysis

**Panels:**
1. **Total Training Cost** (Gauge) - Sum of all active jobs
2. **Total GPU Hours** (Stat) - Cumulative GPU time
3. **Running Cost per Job** (Time Series) - Live cost trends
4. **Cost Breakdown Table** - Job name, cost, GPU hours
5. **Cost per Epoch** (Bar Chart) - Efficiency comparison
6. **Budget Alert Monitor** - Threshold visualization ($10 default)

**Alert Configuration:**
```yaml
# Alert fires when total cost > $10
alert:
  conditions:
    - query: sum(training_cost_usd)
      threshold: 10
      type: gt
  for: 1m
  notifications: ["email", "slack"]
```

**How to Use:**
```bash
# View dashboard
open http://localhost/grafana/d/training-cost-tracking/

# Check current cost
curl -s http://localhost:9090/api/v1/query?query=sum(training_cost_usd) | jq '.data.result[0].value[1]'

# Set custom budget alert
# → Edit panel "Budget Alert Monitor"
# → Change threshold value from 10 to desired amount
```

---

### 5. Resource Utilization Heatmaps ✅

**Location:** `/monitoring/grafana/dashboards/training/training-resource-heatmaps.json`

**What It Does:**
- Visual heatmaps of GPU VRAM, CPU, object store pressure
- Identify bottlenecks in data loading vs compute
- Multi-job resource comparison

**Panels:**
1. **GPU Utilization Heatmap** (Table) - Per-job GPU usage %
2. **GPU VRAM Usage** (Gauge) - Current VRAM per GPU
3. **Training Velocity** (Bar Chart) - Epochs/minute
4. **Ray Object Store Pressure** (Table) - Memory pressure per node
5. **Data Loading Bottlenecks** (Time Series) - p50/p95 load times

**Key Queries:**
```promql
# GPU utilization by job
training_gpu_utilization * 100

# VRAM usage
training_gpu_vram_used_gb

# Epochs completed per minute
rate(training_epochs_completed_total[5m])

# Object store pressure (0.0-1.0, alert at >0.9)
ray_object_store_memory / ray_object_store_available_memory

# Data loading p95 latency
histogram_quantile(0.95, rate(training_data_load_time_ms_bucket[5m]))
```

---

### 6. Log Aggregation with Loki ✅

**Location:** `/docker-compose.logging.yml`, `/monitoring/loki/`

**What It Does:**
- Centralized log collection from Ray, training jobs, Docker containers
- 90-day retention
- Full-text search in Grafana

**Components:**
- **Loki:** Log aggregation database
- **Promtail:** Log shipper (collects from files + Docker)

**Log Sources:**
- Ray job logs: `/tmp/ray/session_*/logs/job-driver-*.log`
- Ray worker logs: `/tmp/ray/session_*/logs/worker-*.log`
- Application logs: `/app_logs/**/*.log`
- System logs: `/var/log/syslog`
- Docker containers: All containers with `logging=promtail` label

**How to Use:**
```bash
# Start Loki stack
docker-compose -f docker-compose.logging.yml up -d

# Search logs in Grafana
# → Navigate to http://localhost/grafana/explore
# → Select "Loki" datasource
# → Query: {job="ray_jobs"} |= "GPU out of memory"

# View logs for specific job
# → Query: {job="ray_jobs"} | json | job_id="job-e33b9c692c43"

# Tail logs live
# → Enable "Live" mode in top-right corner
```

**Label Filters:**
```logql
# All Ray job logs
{job="ray_jobs"}

# Specific job ID
{job="ray_jobs"} | json | job_id="job-e33b9c692c43"

# Error logs only
{job="ray_jobs"} | json | level="ERROR"

# GPU errors
{job="ray_jobs"} |= "CUDA" |= "error"

# MLflow connection failures
{job="ray_jobs"} |= "MLflowException"
```

---

### 7. Job Auto-Retry with Exponential Backoff 📝

**Location:** `/ray_compute/data/job_workspaces/submit_face_detection_job.py`

**Status:** Partially Implemented (Ray API limitation)

**What It Does:**
- Automatically retries failed jobs
- Exponential backoff: 1min → 2min → 4min → 8min
- Retry on specific exceptions only (MLflow, network, timeout)

**Current Implementation:**
```python
# Ray doesn't support retry_policy in submit_job yet (as of Ray 2.9)
# Added submission_id for manual retry tracking
submission_id = f"face-detection-{timestamp}"

# Desired API (future Ray version):
job_id = client.submit_job(
    entrypoint=entrypoint,
    submission_id=submission_id,
    retry_policy={
        "max_retries": 3,
        "retry_exceptions": ["MLflowException", "ConnectionError", "TimeoutError"],
        "backoff_factor": 2.0,
    }
)
```

**Manual Retry Workaround:**
```python
# In training script, wrap MLflow calls with retry logic
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=60, max=480),
    reraise=True
)
def log_to_mlflow(metrics):
    """Log with retry on connection failures."""
    try:
        mlflow.log_metrics(metrics)
    except Exception as e:
        if "MLflow" in str(e) or "Connection" in str(e):
            print(f"⚠ MLflow error, retrying: {e}")
            raise
        else:
            raise
```

---

### 8. Distributed Tracing with OpenTelemetry ✅

**Location:** `/docker-compose.tracing.yml`, `/monitoring/tempo/`

**What It Does:**
- End-to-end trace visualization of Ray tasks
- Identify task dependencies and bottlenecks
- Correlate traces with metrics in Grafana

**Components:**
- **Tempo:** Trace storage and query
- **OpenTelemetry Collector:** Trace ingestion and processing

**How to Enable in Training Jobs:**
```python
# Add to runtime_env in job submission
runtime_env = {
    "env_vars": {
        "RAY_TRACING_ENABLED": "1",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4317",
        "OTEL_SERVICE_NAME": "face_detection_training",
        "OTEL_TRACES_EXPORTER": "otlp",
    }
}
```

**Start Tracing Stack:**
```bash
docker-compose -f docker-compose.tracing.yml up -d
```

**View Traces:**
```bash
# Grafana → Explore → Select "Tempo" datasource
# Query by trace ID or service name
# Visualize task execution timeline

# Example trace query
# Service: face_detection_training
# Operation: train_epoch
# Duration: > 1s
```

**Trace Attributes:**
- `ray.task.name` - Task function name
- `ray.task.id` - Task ID
- `ray.job.id` - Parent job ID
- `ray.node.id` - Worker node
- `duration_ms` - Task execution time
- `gpu.util` - GPU utilization during task

---

## 📚 Future Features (9-10 - Documented Only)

### 9. Job Dependency Graphs (DAG Visualization)

**What It Would Do:**
- Visual pipeline of dependent jobs
- Auto-submit downstream jobs on completion
- Pause/resume entire pipelines

**API Design:**
```python
from ray.job_submission import JobSubmissionClient

client = JobSubmissionClient("http://ray-head:8265")

# Submit preprocessing job
data_job = client.submit_job(
    entrypoint="python preprocess_widerface.py",
    submission_id="widerface-preprocessing",
)

# Submit training job (depends on preprocessing)
training_job = client.submit_job(
    entrypoint="python face_detection_training.py --epochs 100",
    submission_id="face-detection-training",
    dependencies=[data_job],  # Waits for data_job to succeed
)

# Submit evaluation job (depends on training)
eval_job = client.submit_job(
    entrypoint="python evaluate_model.py",
    submission_id="face-detection-eval",
    dependencies=[training_job],
)

# View DAG in Ray Dashboard
# → Navigate to http://localhost/ray/#/pipelines/{pipeline_id}
# → See visual graph: [Preprocessing] → [Training] → [Evaluation]
```

**Ray Dashboard Integration:**
- New "Pipelines" tab showing DAG visualization
- Click nodes to view job details
- Pause/resume/cancel entire pipeline
- Retry failed stages without restarting entire pipeline

---

### 10. Interactive Jupyter Integration

**What It Would Do:**
- Submit Jupyter notebooks as Ray jobs
- View executed notebooks with outputs in browser
- Re-run with different parameters

**API Design:**
```python
# Submit notebook as job
job_id = client.submit_job(
    entrypoint=(
        "papermill training_notebook.ipynb output.ipynb "
        "-p epochs 100 -p batch_size 8 -p model yolov8l.pt"
    ),
    runtime_env={
        "pip": ["papermill", "jupyter", "ipywidgets"]
    },
    metadata={
        "notebook_url": f"http://localhost:8888/notebooks/output.ipynb",
        "interactive": True,
        "parameters": {
            "epochs": 100,
            "batch_size": 8,
            "model": "yolov8l.pt"
        }
    }
)
```

**Features:**
- Parameterized notebook execution with `papermill`
- Output notebooks saved to `/ray_compute/data/notebooks/`
- Ray Dashboard links to JupyterLab viewer
- Download `.ipynb` with all plots, metrics, logs

**Example Workflow:**
1. Create `training_notebook.ipynb` with parameters cell:
   ```python
   # Parameters
   epochs = 10
   batch_size = 4
   model = "yolov8n.pt"
   ```

2. Submit via Ray:
   ```bash
   python submit_notebook_job.py \
     --notebook training_notebook.ipynb \
     --epochs 100 \
     --batch-size 8 \
     --model yolov8l.pt
   ```

3. View results:
   ```bash
   # Ray Dashboard → Jobs → Click job
   # → "View Executed Notebook" button
   # → Opens JupyterLab with output.ipynb
   ```

---

## 🚀 Quick Start Guide

### Enable All Observability Features:

```bash
cd /home/axelofwar/Projects/shml-platform

# 1. Start logging stack (Loki + Promtail)
docker-compose -f docker-compose.logging.yml up -d

# 2. Start tracing stack (Tempo + OTel)
docker-compose -f docker-compose.tracing.yml up -d

# 3. Import Grafana dashboards
# → Navigate to http://localhost/grafana/
# → Click "+" → "Import"
# → Upload monitoring/grafana/dashboards/training/*.json

# 4. Submit training job with metrics
cd ray_compute/data/job_workspaces
python submit_face_detection_job.py --epochs 100 --model yolov8l.pt

# 5. Monitor in real-time
open http://localhost/ray/#/jobs/  # Ray Dashboard
open http://localhost/grafana/d/training-cost-tracking/  # Cost dashboard
open http://localhost/grafana/d/training-resource-heatmaps/  # Resource heatmaps
open http://localhost/grafana/explore  # Log search (Loki)
```

---

## 📊 Grafana Dashboard URLs

| Dashboard | URL | Description |
|-----------|-----|-------------|
| Training Cost Tracking | `/grafana/d/training-cost-tracking/` | Real-time cost, budget alerts, cost/epoch |
| Resource Heatmaps | `/grafana/d/training-resource-heatmaps/` | GPU/VRAM/CPU utilization, bottlenecks |
| Ray Cluster Metrics | `/grafana/d/ray-cluster/` | Cluster health, tasks, object store |
| Log Explorer | `/grafana/explore` | Full-text log search (Loki) |
| Trace Viewer | `/grafana/explore` | Distributed traces (Tempo) |

---

## 🔧 Troubleshooting

**Metrics not showing up:**
```bash
# Check if metrics are being scraped
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="ray-head")'

# Check if Ray metrics reporter is enabled in training job
docker exec ray-head grep "Ray metrics reporter initialized" /tmp/ray/session_latest/logs/job-driver-*.log
```

**Logs not appearing in Grafana:**
```bash
# Check Promtail status
docker logs promtail --tail 50

# Verify Loki is receiving logs
curl http://localhost:3100/loki/api/v1/label/job/values
# Should return: ["ray_jobs", "ray_workers", "app_logs", ...]
```

**Traces not showing:**
```bash
# Verify OpenTelemetry Collector is running
docker ps | grep otel-collector

# Check if traces are reaching Tempo
curl http://localhost:3200/api/search | jq '.'
```

---

## 📖 Related Documentation

- **Ray Metrics Documentation:** https://docs.ray.io/en/latest/ray-observability/user-guides/configure-logging.html
- **Grafana Loki:** https://grafana.com/docs/loki/latest/
- **Tempo Tracing:** https://grafana.com/docs/tempo/latest/
- **OpenTelemetry:** https://opentelemetry.io/docs/

---

**Last Updated:** December 9, 2025
**Maintainer:** SHML Platform Team
