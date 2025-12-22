# Face Detection Training (MLflow Project)

## Usage

```bash
# Run via MLflow CLI
mlflow run . -P epochs=200 -P batch_size=8

# Run via Python API
import mlflow
mlflow.run(".", parameters={"epochs": 200, "batch_size": 8})
```

## Parameters

- `epochs`: Training epochs (default: 200)
- `batch_size`: Batch size (default: 8)
- `learning_rate`: Learning rate (default: 0.01)
- `dataset`: Dataset name (default: "wider_face")
- `phase`: Training phase (default: "phase1")

## See Also

- `docs/ARCHITECTURE_REDESIGN.md` - Full architecture
- `ray_compute/jobs/training/phase1_foundation.py` - Implementation
