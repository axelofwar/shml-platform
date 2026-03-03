# Training Walkthrough

An end-to-end guide: choose a profile, submit a training job, monitor
progress, and evaluate results — via the SDK, CLI, and raw API.

---

## 1. Choose a Training Profile

Profiles bundle sensible defaults for common scenarios.

| Profile | Epochs | Batch | Image Size | Use Case |
|---------|--------|-------|------------|----------|
| `quick-test` | 5 | 16 | 640 | Smoke test on a small slice |
| `balanced` | 50 | 8 | 640 | Good quality / time trade-off |
| `full` | 100 | 4 | 1280 | Maximum accuracy |

!!! tip "Custom overrides"
    Any profile field can be overridden at submission time. For example,
    use the `balanced` profile but change the epoch count.

---

## 2. Submit the Job

### SDK

```python
from shml import Client

with Client() as c:
    job = c.submit_training("balanced", epochs=50)
    print(job)  # Job(id='raysubmit_abc123', ...)
```

### CLI

```bash
shml train submit --profile balanced --epochs 50
```

### API

```bash
curl -X POST http://localhost/api/ray/jobs \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SHML_API_KEY" \
  -d '{
    "name": "train-yolov8l-p2-20260228",
    "job_type": "training",
    "cpu": 4,
    "memory_gb": 16,
    "gpu": 1.0,
    "timeout_hours": 50,
    "entrypoint": "python -c \"from ultralytics import YOLO; m = YOLO('yolov8l-p2.pt'); m.train(data='data.yaml', epochs=50, batch=8, imgsz=640)\""
  }'
```

---

## 3. What Happens During Training

Jobs move through a defined lifecycle:

```
PENDING → RUNNING → SUCCEEDED | FAILED | CANCELLED
```

### Lifecycle Phases

1. **PENDING** — Job queued; resources being allocated on the Ray cluster.
2. **RUNNING** — Ultralytics training loop active. Metrics are emitted
   each epoch.
3. **SUCCEEDED** — Training completed. Model weights, logs, and metrics
   are persisted.
4. **FAILED** — An error occurred. Check logs for details.
5. **CANCELLED** — User or timeout cancelled the job.

### Integration Hooks

During the RUNNING phase the platform triggers integrations automatically:

| Integration | What Happens |
|-------------|-------------|
| **MLflow** | Experiment created; per-epoch metrics logged; best model registered |
| **Nessie** | A catalog branch is created for the run; committed on success |
| **Prometheus** | GPU utilization, loss, and throughput pushed to Pushgateway |
| **FiftyOne** | Post-training evaluation on the validation split (if enabled) |

---

## 4. Monitor Progress

### SDK

```python
from shml import Client

with Client() as c:
    status = c.job_status("raysubmit_abc123")
    print(status.status)  # RUNNING

    logs = c.job_logs("raysubmit_abc123")
    print(logs[-500:])     # tail
```

### CLI

```bash
shml train status raysubmit_abc123
shml train logs raysubmit_abc123 --follow
```

### API

```bash
# Status
curl http://localhost/api/ray/jobs/raysubmit_abc123 \
  -H "X-API-Key: $SHML_API_KEY"

# Logs
curl http://localhost/api/ray/jobs/raysubmit_abc123/logs \
  -H "X-API-Key: $SHML_API_KEY"
```

### Grafana

Open the **Training Jobs** dashboard at
`http://localhost:3000/d/training-jobs` to see GPU utilization, loss
curves, and throughput in real time.

---

## 5. Wait for Completion

The SDK provides a blocking helper:

```python
with Client() as c:
    job = c.submit_training("balanced", epochs=50)
    final = c.wait_for_job(job.job_id, poll_interval=10, timeout=7200)
    print(final.status)  # SUCCEEDED
```

!!! warning "Timeout"
    `wait_for_job` raises `JobTimeoutError` if the job does not finish
    within the specified timeout (default 3 600 s).

---

## 6. Evaluate Results

### FiftyOne (Visual)

```python
with Client() as c:
    fo = c.fiftyone
    dataset = fo.load_evaluation("raysubmit_abc123")
    # Opens the FiftyOne App with predictions overlaid on images
```

### MLflow (Metrics)

Navigate to `http://localhost/mlflow` → select the experiment →
click the run to view per-epoch metrics and the registered model.

---

## 7. Interpreting Metrics

After training completes, the following metrics are stored in MLflow:

| Metric | Description | Good Target |
|--------|-------------|-------------|
| **mAP50** | Mean average precision @ IoU 0.50 | ≥ 0.80 |
| **mAP50-95** | Mean AP averaged over IoU 0.50–0.95 | ≥ 0.40 |
| **Precision** | True positives / (TP + FP) | ≥ 0.85 |
| **Recall** | True positives / (TP + FN) | ≥ 0.70 |

### Latest Results

The most recent production run achieved:

| Metric | Value |
|--------|-------|
| mAP50 | **0.812** |
| mAP50-95 | **0.413** |
| Precision | **0.891** |
| Recall | **0.738** |

!!! success "Above target"
    All four metrics exceed the minimum targets, confirming the model is
    ready for deployment.

---

## Quick Reference

```bash
# Full flow in one script
shml train submit --profile balanced --epochs 50 --wait
shml train metrics raysubmit_abc123
```
