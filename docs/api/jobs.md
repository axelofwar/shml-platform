# Jobs API

Submit, monitor, and manage training and script jobs on the Ray cluster.

All endpoints use the prefix `/api/ray/jobs` and require authentication
via `X-API-Key` or `Authorization: Bearer <token>`.

---

## Submit a Job

**`POST /api/ray/jobs`**

Create a new job on the platform. The gateway validates the payload,
allocates resources, and forwards the job to the Ray head node.

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Human-readable job name |
| `job_type` | string | yes | `training` or `script` |
| `cpu` | int | no | CPU cores (default `4`) |
| `memory_gb` | int | no | RAM in GB (default `16`) |
| `gpu` | float | no | GPU fraction (default `1.0`) |
| `timeout_hours` | int | no | Max runtime (default `4`) |
| `priority` | string | no | `low`, `normal`, `high` |
| `entrypoint` | string | yes* | Command to run |
| `script_content` | string | yes* | Base64-encoded script |
| `script_name` | string | no | Filename for the script |
| `entrypoint_args` | list | no | CLI arguments |
| `requirements` | list | no | pip packages to install |
| `mlflow_experiment` | string | no | MLflow experiment name |

!!! note
    Provide **either** `entrypoint` (inline command) **or** `script_content`
    (uploaded script), not both.

### Example — Training Job

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
    "timeout_hours": 8,
    "entrypoint": "python -c \"from ultralytics import YOLO; m = YOLO('yolov8l-p2.pt'); m.train(data='data.yaml', epochs=50, batch=8, imgsz=640)\""
  }'
```

### Response `200`

```json
{
  "job_id": "raysubmit_abc123",
  "name": "train-yolov8l-p2-20260228",
  "status": "PENDING"
}
```

---

## Job Status

**`GET /api/ray/jobs/{id}`**

Returns the current state of a job.

```bash
curl http://localhost/api/ray/jobs/raysubmit_abc123 \
  -H "X-API-Key: $SHML_API_KEY"
```

### Response

```json
{
  "job_id": "raysubmit_abc123",
  "name": "train-yolov8l-p2-20260228",
  "status": "RUNNING"
}
```

Possible `status` values: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`,
`STOPPED`, `CANCELLED`.

---

## Job Logs

**`GET /api/ray/jobs/{id}/logs`**

Stream or fetch the stdout/stderr log output for a job.

```bash
curl http://localhost/api/ray/jobs/raysubmit_abc123/logs \
  -H "X-API-Key: $SHML_API_KEY"
```

### Response

```json
{
  "logs": "Epoch 1/50 ... loss=0.042 ..."
}
```

---

## Cancel a Job

**`POST /api/ray/jobs/{id}/cancel`**

Stop a running or pending job. Optionally include a cancellation reason.

```bash
curl -X POST http://localhost/api/ray/jobs/raysubmit_abc123/cancel \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SHML_API_KEY" \
  -d '{"reason": "Incorrect dataset"}'
```

### Response

```json
{
  "job_id": "raysubmit_abc123",
  "name": "train-yolov8l-p2-20260228",
  "status": "CANCELLED"
}
```

---

## List Jobs

**`GET /api/ray/jobs`**

Paginated list of all jobs visible to the authenticated user.

### Query Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | `1` | Page number |
| `page_size` | int | `20` | Results per page |
| `status` | string | — | Filter by status |

```bash
curl "http://localhost/api/ray/jobs?page=1&page_size=5&status=RUNNING" \
  -H "X-API-Key: $SHML_API_KEY"
```

### Response

```json
{
  "jobs": [
    {
      "job_id": "raysubmit_abc123",
      "name": "train-yolov8l-p2-20260228",
      "status": "RUNNING"
    }
  ]
}
```
