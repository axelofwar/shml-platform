# Feature Store

The `FeatureClient` wraps the platform's Spark-backed feature extraction and storage layer (`shml_features` library) for experiment-scoped feature logging and retrieval.

---

## Class Reference

```python
class FeatureClient:
    def __init__(self, config: PlatformConfig | None = None)
```

| Property | Type | Description |
|---|---|---|
| `available` | `bool` | `True` if the `shml_features` backend is importable |

### Health Check

```python
def healthy(self) -> bool
```

Delegates to the underlying `shml_features.FeatureClient.healthy()`.

### Logging Features

```python
def log_features(
    self,
    experiment_name: str,
    features: dict[str, Any],
    epoch: int | None = None,
    step: int | None = None,
) -> None

def log_model_metrics(
    self,
    experiment_name: str,
    metrics: dict[str, float],
    epoch: int,
) -> None

def log_dataset_stats(
    self,
    experiment_name: str,
    stats: dict[str, Any],
) -> None
```

| Method | Description |
|---|---|
| `log_features` | Store arbitrary feature vectors keyed by experiment, epoch, and step |
| `log_model_metrics` | Convenience wrapper — prefixes each key with `metric_` and includes the epoch |
| `log_dataset_stats` | Convenience wrapper — prefixes each key with `dataset_` |

### Retrieving Features

```python
def get_features(
    self,
    experiment_name: str,
    epoch: int | None = None,
) -> list[dict[str, Any]]
```

Returns a list of feature records. Pass `epoch` to filter to a single epoch.

---

## Usage Examples

### Log Training Metrics

```python
from shml import SHMLClient

client = SHMLClient()
fs = client.features

fs.log_model_metrics(
    experiment_name="yolo-v8-coco",
    metrics={"loss": 0.32, "mAP50": 0.81, "precision": 0.79},
    epoch=10,
)
```

### Log Dataset Statistics

```python
fs.log_dataset_stats(
    experiment_name="yolo-v8-coco",
    stats={"num_images": 5000, "num_classes": 80, "avg_width": 640},
)
```

### Retrieve Features

```python
records = fs.get_features("yolo-v8-coco", epoch=10)
for r in records:
    print(r)
```

!!! tip
    Use `available` to guard feature-store calls in environments where the
    Spark backend is not deployed:

    ```python
    if client.features.available:
        client.features.log_model_metrics(...)
    ```

---

## Error Handling

All methods raise `shml.exceptions.FeatureStoreError` when the backend is
unreachable or a write/read fails.
