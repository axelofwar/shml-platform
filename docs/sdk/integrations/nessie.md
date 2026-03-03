# Nessie Integration

The `NessieClient` provides Git-like data catalog versioning through the [Nessie](https://projectnessie.org/) REST API. Each experiment gets its own branch; completed experiments are tagged for reproducibility.

!!! note "API Version"
    This client targets the **Nessie v1 REST API**. The v2 API uses an
    incompatible branch-creation format and is not currently supported.

---

## Class Reference

```python
class NessieClient:
    def __init__(self, config: PlatformConfig | None = None)
```

| Property | Type | Description |
|---|---|---|
| `base_url` | `str` | Nessie server base URL |

### Health Check

```python
def healthy(self) -> bool
```

Returns `True` if the Nessie server responds on `/api/v1/trees`.

### Branch Operations

```python
def get_main_hash(self) -> str
def create_branch(self, name: str, from_hash: str | None = None) -> dict[str, Any]
def list_branches(self) -> list[dict[str, Any]]
def delete_branch(self, name: str) -> bool
```

| Method | Description |
|---|---|
| `get_main_hash` | Current commit hash of the `main` branch |
| `create_branch` | Create a branch from `main` HEAD or a specific hash. Returns the ref dict; 409 conflicts are handled gracefully (`existed: True`). |
| `list_branches` | All references of type `BRANCH` |
| `delete_branch` | Delete by name; returns `True` on success, `False` if not found |

### Tag Operations

```python
def create_tag(self, name: str, from_hash: str | None = None) -> dict[str, Any]
def list_tags(self) -> list[dict[str, Any]]
```

Tags are immutable pointers to a specific hash. Duplicate tag names return a
dict with `existed: True` instead of raising.

---

## Experiment Lifecycle Helpers

Two convenience methods enforce the platform's naming conventions:

```python
def create_experiment_branch(
    self,
    experiment_name: str,
    prefix: str = "experiment",
) -> str

def tag_experiment(
    self,
    experiment_name: str,
    metrics: dict[str, float] | None = None,
) -> str
```

| Helper | Convention | Example |
|---|---|---|
| `create_experiment_branch` | `{prefix}-{experiment_name}` | `experiment-yolo-v8-coco` |
| `tag_experiment` | `training-{experiment_name}` | `training-yolo-v8-coco` |

!!! info "Branch Naming"
    The default prefix is `experiment`. Override it with the `prefix` parameter
    when you need branches for other purposes (e.g., `hotfix`, `feature`).

---

## Usage Examples

### Create an Experiment Branch

```python
from shml import SHMLClient

client = SHMLClient()
nessie = client.nessie

# Create a branch for this experiment
branch = nessie.create_experiment_branch("yolo-v8-coco")
print(f"Working on branch: {branch}")
# → "Working on branch: experiment-yolo-v8-coco"
```

### Tag a Completed Experiment

```python
tag = nessie.tag_experiment("yolo-v8-coco", metrics={"mAP50": 0.85})
print(f"Tagged as: {tag}")
# → "Tagged as: training-yolo-v8-coco"
```

### Low-Level Branch and Tag Management

```python
# List all branches
for b in nessie.list_branches():
    print(b["name"], b["hash"][:8])

# Create a branch from a specific hash
nessie.create_branch("rollback-point", from_hash="abc123de")

# Cleanup
nessie.delete_branch("experiment-old-run")
```

---

## Error Handling

All methods raise `shml.exceptions.NessieError` on unexpected HTTP responses
or connectivity failures. Branch/tag creation on a 409 Conflict is treated
as a no-op and does **not** raise.
