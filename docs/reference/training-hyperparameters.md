# Training Hyperparameters

Complete reference for YOLO training configuration in the SHML Platform SDK.

---

## TrainingConfig

Defined in `sdk/shml/config.py`. All fields have sensible defaults for fine-tuning on an RTX 3090 Ti.

### Core Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `epochs` | `int` | `10` | Total training epochs |
| `batch` | `int` | `4` | Batch size per GPU |
| `imgsz` | `int` | `1280` | Input image size (px) |
| `device` | `str` | `cuda:0` | CUDA device (`cuda:0` = RTX 3090 Ti) |
| `optimizer` | `str` | `AdamW` | Optimizer (`SGD`, `Adam`, `AdamW`) |
| `model` | `str` | `yolo11x.pt` | Base model weights |
| `checkpoint` | `str \| None` | `None` | Resume from this checkpoint path |
| `data_yaml` | `str` | `/tmp/ray/data/wider_face_yolo/data.yaml` | Dataset config |

### Learning Rate

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lr0` | `float` | `0.0001` | Initial learning rate |
| `lrf` | `float` | `0.01` | Final LR as fraction of `lr0` (cosine annealing target) |
| `warmup_epochs` | `float` | `1.0` | Number of warmup epochs |
| `warmup_momentum` | `float` | `0.8` | Warmup initial momentum |
| `warmup_bias_lr` | `float` | `0.01` | Warmup bias learning rate |
| `momentum` | `float` | `0.937` | SGD momentum / Adam beta1 |
| `weight_decay` | `float` | `0.0005` | L2 regularization |

### Loss Weights

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `box` | `float` | `7.5` | Box loss weight |
| `cls` | `float` | `0.5` | Classification loss weight |
| `dfl` | `float` | `1.5` | Distribution focal loss weight |

!!! info "Single-Class Detection"
    For face detection, `single_cls=True` is the default. The `cls` loss weight has minimal effect with a single class, but `box` and `dfl` are critical.

### Runtime

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `workers` | `int` | `4` | DataLoader worker threads |
| `patience` | `int` | `0` | Early stopping patience (0 = disabled) |
| `save_period` | `int` | `1` | Save checkpoint every N epochs |
| `nbs` | `int` | `64` | Nominal batch size for LR scaling |
| `single_cls` | `bool` | `True` | Treat all classes as one |
| `exist_ok` | `bool` | `True` | Overwrite existing experiment |
| `verbose` | `bool` | `True` | Verbose logging |
| `val` | `bool` | `True` | Run validation after each epoch |
| `plots` | `bool` | `True` | Generate training plots |
| `deterministic` | `bool` | `True` | Deterministic training |
| `amp` | `bool` | `True` | Automatic mixed precision (30% memory savings) |
| `cache` | `bool` | `False` | Cache images in RAM (disabled to save ~4-6 GB) |
| `rect` | `bool` | `False` | Rectangular training |
| `cos_lr` | `bool` | `False` | Cosine learning rate scheduler |
| `close_mosaic` | `int` | `10` | Disable mosaic augmentation for last N epochs |
| `pretrained` | `bool` | `True` | Use pretrained backbone weights |

### Platform Integrations

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `integrations` | `list[str]` | `["mlflow", "nessie", "fiftyone", "features", "prometheus"]` | Platform features to enable |
| `gpu_yield` | `bool` | `True` | Yield/reclaim GPU from inference services |
| `mlflow_experiment` | `str` | `Face-Detection` | MLflow experiment name |
| `nessie_branch_prefix` | `str` | `experiment` | Nessie branch prefix for data versioning |

---

## AugmentationConfig

Data augmentation hyperparameters, nested inside `TrainingConfig.augmentation`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mosaic` | `float` | `1.0` | Mosaic augmentation probability |
| `mixup` | `float` | `0.15` | MixUp augmentation probability |
| `copy_paste` | `float` | `0.1` | Copy-paste augmentation probability |
| `degrees` | `float` | `10.0` | Random rotation range (±degrees) |
| `translate` | `float` | `0.2` | Random translation range (fraction) |
| `scale` | `float` | `0.9` | Random scale range (±fraction) |
| `shear` | `float` | `0.0` | Shear angle (degrees) |
| `perspective` | `float` | `0.0` | Perspective distortion |
| `flipud` | `float` | `0.0` | Vertical flip probability |
| `fliplr` | `float` | `0.5` | Horizontal flip probability |
| `hsv_h` | `float` | `0.015` | HSV hue augmentation range |
| `hsv_s` | `float` | `0.7` | HSV saturation augmentation range |
| `hsv_v` | `float` | `0.4` | HSV value (brightness) augmentation range |
| `erasing` | `float` | `0.0` | Random erasing probability |
| `crop_fraction` | `float` | `1.0` | Crop fraction (1.0 = full image) |

!!! tip "Face Detection Augmentation"
    The defaults are tuned for face detection. Vertical flip (`flipud`) is disabled because faces don't appear upside-down in typical scenarios. Mosaic is set to `1.0` for maximum spatial diversity.

---

## YAML Profile Example

Profiles live in `config/profiles/`. Example `balanced.yaml`:

```yaml
epochs: 200
batch: 4
imgsz: 1280
optimizer: AdamW
lr0: 0.0001
lrf: 0.01
patience: 0
model: yolo11x.pt
data_yaml: /tmp/ray/data/wider_face_yolo/data.yaml

augmentation:
  mosaic: 1.0
  mixup: 0.15
  copy_paste: 0.1
  close_mosaic: 10

integrations:
  - mlflow
  - prometheus
```

Load via SDK:

```python
from shml import TrainingConfig

cfg = TrainingConfig.from_yaml("config/profiles/balanced.yaml")
cfg = TrainingConfig.from_yaml("config/profiles/balanced.yaml", epochs=5, batch=2)
```

---

## Memory Budget (RTX 3090 Ti, 24 GB)

| Component | Estimated VRAM |
|-----------|---------------|
| YOLOv8-L model | ~2.5 GB |
| Batch data (1280px, batch=2) | ~12 GB |
| Optimizer state (AdamW) | ~5 GB |
| PyTorch overhead | ~1.5 GB |
| Multi-scale buffer | ~1 GB |
| Safety margin | ~2 GB |
| **Total** | **~24 GB** |

!!! warning "OOM Prevention"
    - `amp=True` reduces memory ~30%
    - `cache=False` saves 4-6 GB system RAM
    - `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512` prevents fragmentation
    - Gradient accumulation (via `nbs=64`) gives effective batch size of 16
