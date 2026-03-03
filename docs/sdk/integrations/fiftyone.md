# FiftyOne Integration

The `FiftyOneClient` manages dataset visualization and evaluation through [FiftyOne](https://docs.voxel51.com/), with automatic MongoDB configuration for the platform environment.

!!! warning "Import Order Matters"
    `FIFTYONE_DATABASE_URI` **must** be set before the first `import fiftyone`.
    The client handles this automatically — avoid importing `fiftyone` directly
    before constructing the client.

---

## Class Reference

```python
class FiftyOneClient:
    def __init__(self, config: PlatformConfig | None = None)
```

| Property | Type | Description |
|---|---|---|
| `available` | `bool` | `True` if the `fiftyone` package is installed |

### Health & Discovery

```python
def healthy(self) -> bool
def list_datasets(self) -> list[str]
```

`healthy()` verifies the MongoDB connection by calling `fo.list_datasets()`.

### Dataset Management

```python
def create_dataset(
    self,
    name: str,
    overwrite: bool = False,
    persistent: bool = True,
) -> Any  # fiftyone.Dataset

def load_dataset(self, name: str) -> Any
def delete_dataset(self, name: str) -> bool
```

| Parameter | Default | Description |
|---|---|---|
| `name` | — | Dataset name |
| `overwrite` | `False` | Delete existing dataset with the same name first |
| `persistent` | `True` | Persist dataset in MongoDB |

!!! info
    If a dataset with the given name already exists and `overwrite` is `False`,
    the existing dataset is loaded and returned.

### Adding Samples

```python
def add_samples_from_predictions(
    self,
    dataset_name: str,
    image_paths: list[str],
    predictions: list[dict[str, Any]] | None = None,
    ground_truth: list[dict[str, Any]] | None = None,
    tags: list[str] | None = None,
) -> int
```

Each prediction/ground-truth dict should contain:

| Key | Type | Description |
|---|---|---|
| `boxes` | `list[list[float]]` | Bounding boxes in `[x, y, w, h]` normalized format |
| `labels` | `list[str]` | Class labels |
| `scores` | `list[float]` | Confidence scores (predictions only) |

Returns the number of samples added.

### Evaluation

```python
def evaluate_detections(
    self,
    dataset_name: str,
    pred_field: str = "predictions",
    gt_field: str = "ground_truth",
    eval_key: str = "eval",
) -> dict[str, Any]
```

Runs FiftyOne's built-in detection evaluation and returns:

```python
{"mAP": 0.72, "eval_key": "eval", "dataset": "my-dataset"}
```

---

## MongoDB Auto-Configuration

On construction, the client calls:

```python
os.environ.setdefault("FIFTYONE_DATABASE_URI", config.fiftyone_mongodb_uri)
```

This points FiftyOne at the platform's dedicated MongoDB instance
(`fiftyone-mongodb` service) instead of launching a local `mongod`.

---

## Usage Examples

### Create a Dataset and Add Predictions

```python
from shml import SHMLClient

client = SHMLClient()
fo = client.fiftyone

dataset = fo.create_dataset("yolo-eval-run-001")

count = fo.add_samples_from_predictions(
    dataset_name="yolo-eval-run-001",
    image_paths=["img_001.jpg", "img_002.jpg"],
    predictions=[
        {"boxes": [[0.1, 0.2, 0.3, 0.4]], "labels": ["cat"], "scores": [0.95]},
        {"boxes": [[0.5, 0.1, 0.2, 0.3]], "labels": ["dog"], "scores": [0.88]},
    ],
    tags=["val", "epoch-50"],
)
print(f"Added {count} samples")
```

### Evaluate Detections

```python
results = fo.evaluate_detections("yolo-eval-run-001")
print(f"mAP: {results['mAP']}")
```

### Cleanup

```python
fo.delete_dataset("yolo-eval-run-001")
```

---

## Error Handling

All methods raise `shml.exceptions.FiftyOneError`. The `available` property
lets you skip FiftyOne calls gracefully when the package is not installed.
