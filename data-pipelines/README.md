# Data Pipelines

Central home for all data pipeline code on the SHML Platform.

## Directory Structure

```
data-pipelines/
├── definitions/      # Pipeline YAML configs (training stages, job graphs)
│   └── face_detection.yml   # 3-stage face detection curriculum
├── loaders/          # Data loading utilities
│   └── streaming_loader.py  # IterableDataset for large-scale training
└── scripts/          # Standalone data pipeline scripts
```

## Planned Consolidations

The following files are logically part of the data pipeline but remain in their
original locations due to import or coupling constraints. They will be migrated here:

| Current Location | Planned Destination | Blocker |
|-----------------|--------------------|-|
| `libs/shml_features.py` | `data-pipelines/` | PYTHONPATH dependency |
| `libs/shml_spark.py` | `data-pipelines/` | PYTHONPATH dependency |
| `scripts/benchmarking/` | `data-pipelines/benchmarking/` | manual task |
| `ray_compute/jobs/annotation/` | `data-pipelines/annotation/` | Ray container coupling |
| `ray_compute/jobs/features/` | `data-pipelines/features/` | Ray feature API coupling |

## Usage

### Pipeline Definitions

Pipeline configs are read by `scripts/training/training_pipeline.py`:

```bash
python scripts/training/training_pipeline.py \
  --config data-pipelines/definitions/face_detection.yml
```

### Streaming Data Loader

```python
from data_pipelines.loaders.streaming_loader import ShmlStreamingDataset
```

## Conventions

- YAML configs: `definitions/<name>.yml`
- Python utilities: `loaders/` or `scripts/`
- No circular imports: data-pipelines should not import from ray_compute or inference
