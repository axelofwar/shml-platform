# Data Management

How datasets are organized, referenced, and secured on the SHML
Platform.

---

## Dataset Format

Training jobs use the **YOLO `data.yaml`** format. A minimal file looks
like:

```yaml
# data.yaml
path: /tmp/ray/data/my-dataset
train: images/train
val: images/val

names:
  0: face
```

The directory structure on disk:

```
my-dataset/
├── data.yaml
├── images/
│   ├── train/
│   └── val/
└── labels/
    ├── train/
    └── val/
```

!!! info "Label format"
    Each `.txt` label file contains one line per object:
    `<class> <x_center> <y_center> <width> <height>` (normalized 0–1).

---

## Data Locations

On the Ray cluster, datasets live under:

```
/tmp/ray/data/
```

This path is mounted into every Ray worker. When you specify
`data='data.yaml'` in your training config, the platform resolves it
relative to this directory.

| Path | Contents |
|------|----------|
| `/tmp/ray/data/` | Root for all datasets |
| `/tmp/ray/data/<name>/data.yaml` | Dataset config |
| `/tmp/ray/data/<name>/images/` | Image files |
| `/tmp/ray/data/<name>/labels/` | YOLO-format labels |

---

## Using Existing Data (Zero-Copy)

If your dataset already exists on the host machine, bind-mount it into
the Ray worker container to avoid duplication:

```yaml
# docker-compose override
services:
  ray-worker:
    volumes:
      - /data/my-dataset:/tmp/ray/data/my-dataset:ro
```

Then reference it normally:

```python
from shml import Client, TrainingConfig

with Client() as c:
    job = c.submit_training(
        config=TrainingConfig(
            data_yaml="/tmp/ray/data/my-dataset/data.yaml",
            epochs=50,
        )
    )
```

!!! tip "Read-only mount"
    Use `:ro` to prevent training from modifying source data.

---

## HuggingFace Datasets

Download a dataset from HuggingFace and convert it to YOLO format
before training:

```python
from datasets import load_dataset

ds = load_dataset("wider_face", split="train")
# Convert to YOLO format and save under /tmp/ray/data/wider-face/
```

Or use the CLI helper:

```bash
shml data pull huggingface wider_face --format yolo
```

The dataset is cached locally so subsequent runs skip the download.

---

## S3 / Remote References

For datasets stored in S3-compatible storage (MinIO, AWS S3):

```yaml
# data.yaml
path: s3://datasets/my-dataset
train: images/train
val: images/val

names:
  0: face
```

!!! note "Credentials"
    Set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in the Ray worker
    environment, or configure them in `config/platform.env`.

The platform downloads the dataset to local storage before training
starts, so GPU I/O is not bottlenecked by network speed.

---

## Privacy Controls

For proprietary or sensitive data:

1. **Never commit data to Git.** Use volume mounts or remote storage.
2. **Restrict access** by setting file permissions on the host:
   ```bash
   chmod 700 /data/proprietary-dataset
   ```
3. **Network isolation** — the Ray cluster does not expose data ports
   externally. Traefik only routes API traffic.
4. **Encryption at rest** — enable LUKS or dm-crypt on the data volume.
5. **Audit logging** — all data access events are recorded in Loki.

!!! warning "PII data"
    If your dataset contains personally identifiable information, ensure
    you have consent and comply with applicable regulations. Consider
    using the companion `pii-pro` toolkit for detection and redaction.

---

## Custom Datasets

To add a new dataset:

1. **Prepare** images and labels in YOLO format.
2. **Copy** or mount them under `/tmp/ray/data/<name>/`.
3. **Create** a `data.yaml` pointing to the correct paths.
4. **Validate** the layout:
   ```bash
   shml data validate /tmp/ray/data/my-new-dataset/data.yaml
   ```
5. **Submit** a training job referencing the new dataset:
   ```bash
   shml train submit --profile balanced \
     --data /tmp/ray/data/my-new-dataset/data.yaml
   ```
