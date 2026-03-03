# GPU API

Query and manage GPU resources on the platform. The yield/reclaim
workflow lets training jobs temporarily take over GPUs used by
inference containers.

All endpoints use the prefix `/api/ray/gpu` and require authentication.

---

## GPU Status

**`GET /api/ray/gpu/status`**

Returns current state of every GPU visible to the platform.

```bash
curl http://localhost/api/ray/gpu/status \
  -H "X-API-Key: $SHML_API_KEY"
```

### Response

```json
{
  "gpus": [
    {
      "id": 0,
      "name": "NVIDIA GeForce RTX 3090 Ti",
      "memory_total_mb": 24576,
      "memory_used_mb": 1024,
      "utilization_pct": 12,
      "state": "idle"
    },
    {
      "id": 1,
      "name": "NVIDIA GeForce RTX 2070",
      "memory_total_mb": 8192,
      "memory_used_mb": 512,
      "utilization_pct": 5,
      "state": "idle"
    }
  ]
}
```

GPU `state` values: `idle`, `training`, `inference`, `cooldown`.

---

## Yield GPU

**`POST /api/ray/gpu/yield`**

Release GPU resources from inference to make them available for
training. This gracefully stops inference containers on the target GPUs.

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `gpu_ids` | list[int] | no | Specific GPUs to yield (default: all) |

```bash
curl -X POST http://localhost/api/ray/gpu/yield \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SHML_API_KEY" \
  -d '{"gpu_ids": [0]}'
```

### Response

```json
{
  "status": "ok",
  "yielded": [0],
  "message": "GPU 0 released for training"
}
```

!!! warning "Inference downtime"
    Yielding a GPU stops any inference workload running on it. Clients
    relying on real-time inference will receive errors until the GPU is
    reclaimed.

---

## Reclaim GPU

**`POST /api/ray/gpu/reclaim`**

Reclaim GPUs and restart inference containers after training completes.

```bash
curl -X POST http://localhost/api/ray/gpu/reclaim \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SHML_API_KEY" \
  -d '{}'
```

### Response

```json
{
  "status": "ok",
  "reclaimed": [0, 1],
  "message": "Inference containers restarted"
}
```

!!! tip "Automatic reclaim"
    The platform can automatically reclaim GPUs when a training job
    finishes. Enable this by setting the `auto_reclaim` flag in
    `config/platform.env` or via the SDK:
    ```python
    client.gpu_reclaim()
    ```
