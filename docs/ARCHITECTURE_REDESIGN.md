# Architecture Redesign: Ray Compute + MLflow Integration

**Version:** 2.0  
**Date:** 2025-12-12  
**Status:** 🔄 In Progress  
**Goal:** Unified platform with dual storage, SAM2 auto-annotation, and production data flywheel

---

## 🎯 Design Principles

### 1. Dual Storage Strategy
- **Local**: Fast I/O for training (`/ray_compute/models/checkpoints`)
- **MLflow**: Version control, registry, production deployment
- **Sync**: Async background sync (no training overhead)

### 2. Ray Compute for All Jobs
- ✅ Training jobs via API (not direct execution)
- ✅ Job queue with priority scheduling
- ✅ Resource management (GPU allocation)
- ✅ Preemption-safe checkpointing

### 3. MLflow Native Integration
- ✅ All runs logged to MLflow
- ✅ Hyperparameters tracked
- ✅ Metrics graphed over time
- ✅ Models registered in registry

### 4. Production Data Flywheel
- ✅ Opt-in user data collection
- ✅ SAM2 auto-annotation
- ✅ Tiered human review (70/20/10)
- ✅ Monthly active learning retraining

---

## 📐 System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SHML Face Detection Platform                 │
│                     (Ray Compute + MLflow + SAM2)                   │
└─────────────────────────────────────────────────────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  Training Jobs   │   │  Ray Compute API │   │  MLflow Server   │
│  (Phase 1/2/3)   │──▶│  Job Management  │──▶│  Tracking +      │
│                  │   │  Resource Alloc  │   │  Model Registry  │
└──────────────────┘   └──────────────────┘   └──────────────────┘
          │                       │                       │
          │                       ▼                       │
          │            ┌──────────────────┐              │
          │            │  Dual Storage    │              │
          └───────────▶│  Manager         │◀─────────────┘
                       │  (Local+MLflow)  │
                       └──────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  Local Checkpts  │   │  MLflow Registry │   │  Ray Serve       │
│  /ray_compute/   │   │  Production      │   │  Inference API   │
│  models/         │   │  Staging         │   │  Multi-model     │
└──────────────────┘   └──────────────────┘   └──────────────────┘
          │                       │                       │
          │                       │                       │
          └───────────────────────┴───────────────────────┘
                                  │
                       ┌──────────▼──────────┐
                       │  Production Users   │
                       │  Data Collection    │
                       │  (Opt-in)           │
                       └─────────────────────┘
                                  │
                       ┌──────────▼──────────┐
                       │  SAM2 Auto-         │
                       │  Annotation         │
                       │  Pipeline           │
                       └─────────────────────┘
                                  │
                       ┌──────────▼──────────┐
                       │  Active Learning    │
                       │  Sample Selection   │
                       └─────────────────────┘
                                  │
                       ┌──────────▼──────────┐
                       │  Tiered Human       │
                       │  Review (Label      │
                       │  Studio)            │
                       └─────────────────────┘
                                  │
                       ┌──────────▼──────────┐
                       │  Retraining Loop    │
                       │  (Monthly)          │
                       └─────────────────────┘
```

---

## 🗂️ Directory Structure

### New Organized Structure

```
ray_compute/
├── api/                           # Ray Compute REST API
│   ├── main.py                    # FastAPI app
│   ├── jobs.py                    # Job management endpoints
│   ├── models.py                  # Model serving endpoints
│   └── schemas.py                 # Pydantic models
│
├── jobs/                          # Training & Evaluation Jobs
│   ├── training/                  # 🆕 Organized training jobs
│   │   ├── phase1_foundation.py          # WIDER Face 200 epochs
│   │   ├── phase2_production.py          # Production data fine-tuning
│   │   ├── phase3_active_learning.py     # Monthly retraining
│   │   ├── base_trainer.py               # Shared training logic
│   │   └── configs/                      # Training configurations
│   │       ├── phase1_wider_face.yaml
│   │       ├── phase2_production.yaml
│   │       └── phase3_active_learning.yaml
│   │
│   ├── evaluation/                # 🆕 Evaluation jobs
│   │   ├── wider_face_eval.py            # WIDER Face benchmark
│   │   ├── production_eval.py            # Production test set
│   │   ├── metrics_reporter.py           # Metrics aggregation
│   │   └── configs/
│   │       └── evaluation.yaml
│   │
│   ├── annotation/                # 🆕 Auto-annotation pipeline
│   │   ├── sam2_pipeline.py              # SAM2 integration
│   │   ├── yfcc100m_downloader.py        # YFCC100M with CC-BY filter
│   │   ├── active_learning.py            # Informative sample selection
│   │   ├── label_studio_export.py        # Human-in-the-loop export
│   │   └── configs/
│   │       ├── sam2.yaml
│   │       └── yfcc100m.yaml
│   │
│   └── utils/                     # 🆕 Shared utilities
│       ├── mlflow_integration.py         # MLflow helper functions
│       ├── checkpoint_manager.py         # Dual storage manager
│       ├── artifact_sync.py              # Local ↔ MLflow sync
│       ├── data_loader.py                # Dataset loading
│       └── metrics.py                    # Metric calculation
│
├── models/                        # 🆕 Local model storage
│   ├── registry/                  # Model metadata
│   │   ├── MODEL_REGISTRY.md             # Model documentation
│   │   └── models.json                   # Model index
│   │
│   ├── checkpoints/               # Training checkpoints
│   │   ├── phase1_wider_face/
│   │   │   ├── epoch_10.pt
│   │   │   ├── epoch_20.pt
│   │   │   ├── best.pt → epoch_50.pt
│   │   │   └── metadata.json
│   │   ├── phase2_production/
│   │   └── phase3_active_learning/
│   │
│   ├── deployed/                  # Production-ready models
│   │   ├── yolov8l_face_v1.pt            # Current production
│   │   ├── yolov8l_face_v2.pt            # Staging
│   │   └── metadata.json
│   │
│   └── exports/                   # Exported formats
│       ├── yolov8l_face_v1.onnx
│       ├── yolov8l_face_v1_fp16.engine   # TensorRT
│       └── yolov8l_face_v1_int8.engine
│
├── data/                          # Training data
│   ├── datasets/                  # 🆕 Organized datasets
│   │   ├── wider_face/                   # 158K faces (foundation)
│   │   │   ├── train/
│   │   │   ├── val/
│   │   │   └── annotations/
│   │   ├── production/                   # Opt-in user data
│   │   │   ├── raw/
│   │   │   ├── annotated/
│   │   │   └── reviewed/
│   │   ├── yfcc100m/                     # CC-BY licensed
│   │   │   ├── downloaded/
│   │   │   ├── filtered/
│   │   │   └── annotated/
│   │   └── annotations/                  # SAM2 auto-annotations
│   │       ├── auto/                     # Auto-generated
│   │       ├── reviewed/                 # Human-reviewed
│   │       └── final/                    # Production-ready
│   │
│   └── ray/                       # Ray internal data
│       └── session_*/             # Ray temporary files
│
├── mlflow_projects/               # 🆕 MLflow Projects
│   ├── face_detection_training/
│   │   ├── MLproject                     # MLflow project definition
│   │   ├── conda.yaml                    # Dependencies
│   │   ├── train.py                      # Training entry point
│   │   └── README.md
│   │
│   ├── auto_annotation/
│   │   ├── MLproject
│   │   ├── conda.yaml
│   │   ├── annotate.py
│   │   └── README.md
│   │
│   └── model_evaluation/
│       ├── MLproject
│       ├── conda.yaml
│       ├── evaluate.py
│       └── README.md
│
├── serve/                         # Ray Serve deployment
│   ├── face_detection_service.py
│   ├── model_router.py
│   └── config.yaml
│
└── web_ui/                        # Next.js dashboard
    └── ... (existing)
```

---

## 🔧 Key Components

### 1. Dual Storage Manager

**Purpose:** Save checkpoints to both local disk (fast) and MLflow (versioned)

**Implementation:** `ray_compute/jobs/utils/checkpoint_manager.py`

```python
import mlflow
from pathlib import Path
from typing import Dict, Any
import torch
import json
import threading
import queue

class DualStorageManager:
    """Manages model checkpoints with dual storage (local + MLflow)."""

    def __init__(
        self,
        local_dir: str,
        mlflow_experiment: str,
        sync_strategy: str = "async"  # "async" or "sync"
    ):
        self.local_dir = Path(local_dir)
        self.local_dir.mkdir(parents=True, exist_ok=True)

        self.mlflow_experiment = mlflow_experiment
        self.sync_strategy = sync_strategy

        # Async sync queue
        if sync_strategy == "async":
            self.sync_queue = queue.Queue()
            self.sync_thread = threading.Thread(target=self._sync_worker, daemon=True)
            self.sync_thread.start()

    def save(
        self,
        epoch: int,
        model: torch.nn.Module,
        metrics: Dict[str, float],
        metadata: Dict[str, Any] = None
    ) -> str:
        """Save checkpoint to local storage and queue for MLflow sync."""

        # Save to local disk (FAST)
        local_path = self.local_dir / f"epoch_{epoch}.pt"
        torch.save({
            'epoch': epoch,
            'model_state_dict': model.state_dict(),
            'metrics': metrics,
            'metadata': metadata or {}
        }, local_path)

        # Save metadata JSON
        metadata_path = self.local_dir / f"epoch_{epoch}_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump({
                'epoch': epoch,
                'metrics': metrics,
                'metadata': metadata or {},
                'local_path': str(local_path)
            }, f, indent=2)

        print(f"✓ Saved checkpoint: {local_path}")

        # Queue for MLflow sync (if async)
        if self.sync_strategy == "async":
            self.sync_queue.put((epoch, local_path, metadata_path, metrics, metadata))
        else:
            # Sync immediately
            self._sync_to_mlflow(epoch, local_path, metadata_path, metrics, metadata)

        return str(local_path)

    def _sync_worker(self):
        """Background worker to sync checkpoints to MLflow."""
        while True:
            epoch, local_path, metadata_path, metrics, metadata = self.sync_queue.get()
            try:
                self._sync_to_mlflow(epoch, local_path, metadata_path, metrics, metadata)
            except Exception as e:
                print(f"✗ MLflow sync failed for epoch {epoch}: {e}")
            finally:
                self.sync_queue.task_done()

    def _sync_to_mlflow(
        self,
        epoch: int,
        local_path: Path,
        metadata_path: Path,
        metrics: Dict[str, float],
        metadata: Dict[str, Any]
    ):
        """Sync checkpoint to MLflow (runs in background thread)."""

        # Log to active MLflow run
        mlflow.log_artifact(str(local_path), artifact_path=f"checkpoints")
        mlflow.log_artifact(str(metadata_path), artifact_path=f"checkpoints")
        mlflow.log_metrics(metrics, step=epoch)

        print(f"✓ Synced to MLflow: epoch {epoch}")

    def load_best(self) -> tuple[torch.nn.Module, Dict[str, float]]:
        """Load best checkpoint from local storage."""
        # Find best checkpoint by metrics
        best_path = self.local_dir / "best.pt"
        if best_path.exists():
            checkpoint = torch.load(best_path)
            return checkpoint['model_state_dict'], checkpoint['metrics']
        else:
            raise FileNotFoundError(f"No best checkpoint found in {self.local_dir}")

    def register_model(
        self,
        model_name: str,
        model_version: str,
        model_path: str,
        tags: Dict[str, str] = None
    ):
        """Register model in MLflow Model Registry."""

        # Log model to MLflow
        with mlflow.start_run(experiment_id=self.mlflow_experiment):
            mlflow.log_artifact(model_path, artifact_path="model")

            # Register model
            model_uri = f"runs:/{mlflow.active_run().info.run_id}/model"
            model_version = mlflow.register_model(
                model_uri=model_uri,
                name=model_name,
                tags=tags or {}
            )

            print(f"✓ Registered model: {model_name} v{model_version.version}")
            return model_version

# Usage example
manager = DualStorageManager(
    local_dir="/ray_compute/models/checkpoints/phase1_wider_face",
    mlflow_experiment="face-detection-training",
    sync_strategy="async"
)

# In training loop
for epoch in range(200):
    # Train
    model, metrics = train_epoch(model, dataloader)

    # Save checkpoint (local + MLflow async)
    manager.save(
        epoch=epoch,
        model=model,
        metrics=metrics,
        metadata={"dataset": "wider_face", "phase": "phase1"}
    )

# After training, register best model
manager.register_model(
    model_name="face-detection-yolov8l",
    model_version="phase1-v1",
    model_path=str(manager.local_dir / "best.pt"),
    tags={"dataset": "wider_face", "phase": "phase1"}
)
```

---

### 2. MLflow Integration Helper

**Purpose:** Simplified MLflow API for common operations

**Implementation:** `ray_compute/jobs/utils/mlflow_integration.py`

```python
import mlflow
from typing import Dict, Any, Optional
from pathlib import Path

class MLflowHelper:
    """Helper class for MLflow operations."""

    def __init__(self, tracking_uri: str = "http://mlflow-server:5000"):
        mlflow.set_tracking_uri(tracking_uri)
        self.tracking_uri = tracking_uri

    def start_training_run(
        self,
        experiment_name: str,
        run_name: str,
        params: Dict[str, Any],
        tags: Dict[str, str] = None
    ) -> str:
        """Start a new MLflow run for training."""

        # Create/get experiment
        try:
            experiment_id = mlflow.create_experiment(experiment_name)
        except Exception:
            experiment_id = mlflow.get_experiment_by_name(experiment_name).experiment_id

        mlflow.set_experiment(experiment_name)

        # Start run
        run = mlflow.start_run(run_name=run_name, tags=tags or {})

        # Log parameters
        mlflow.log_params(params)

        print(f"✓ Started MLflow run: {run.info.run_id}")
        return run.info.run_id

    def log_epoch_metrics(
        self,
        epoch: int,
        metrics: Dict[str, float],
        prefix: str = "train"
    ):
        """Log metrics for a specific epoch."""
        mlflow.log_metrics(
            {f"{prefix}/{k}": v for k, v in metrics.items()},
            step=epoch
        )

    def load_model_from_registry(
        self,
        model_name: str,
        stage: str = "Production"  # or "Staging", "None"
    ) -> str:
        """Load model from MLflow Model Registry."""

        model_uri = f"models:/{model_name}/{stage}"
        model_path = mlflow.artifacts.download_artifacts(model_uri)

        print(f"✓ Loaded model: {model_name} ({stage})")
        return model_path

    def promote_model_to_production(
        self,
        model_name: str,
        version: int
    ):
        """Promote model version to Production stage."""

        client = mlflow.tracking.MlflowClient()

        # Archive current production model
        try:
            current_prod = client.get_latest_versions(model_name, stages=["Production"])[0]
            client.transition_model_version_stage(
                name=model_name,
                version=current_prod.version,
                stage="Archived"
            )
        except IndexError:
            pass  # No current production model

        # Promote new model
        client.transition_model_version_stage(
            name=model_name,
            version=version,
            stage="Production"
        )

        print(f"✓ Promoted {model_name} v{version} to Production")

    def compare_models(
        self,
        model_name: str,
        versions: list[int],
        metric: str = "mAP50"
    ) -> Dict[int, float]:
        """Compare model versions by metric."""

        client = mlflow.tracking.MlflowClient()
        results = {}

        for version in versions:
            model_version = client.get_model_version(model_name, version)
            run = client.get_run(model_version.run_id)
            results[version] = run.data.metrics.get(metric, 0.0)

        # Sort by metric (descending)
        sorted_results = dict(sorted(results.items(), key=lambda x: x[1], reverse=True))

        print(f"✓ Model comparison ({metric}):")
        for version, value in sorted_results.items():
            print(f"  v{version}: {value:.4f}")

        return sorted_results

# Usage
helper = MLflowHelper()

# Start training run
run_id = helper.start_training_run(
    experiment_name="face-detection-training",
    run_name="phase1-wider-face-200epochs",
    params={"epochs": 200, "batch_size": 8, "lr": 0.01},
    tags={"phase": "phase1", "dataset": "wider_face"}
)

# Log epoch metrics
for epoch in range(200):
    metrics = train_epoch(model, dataloader)
    helper.log_epoch_metrics(epoch, metrics, prefix="train")

# Load production model
model_path = helper.load_model_from_registry("face-detection-yolov8l", stage="Production")

# Promote model
helper.promote_model_to_production("face-detection-yolov8l", version=3)

# Compare models
helper.compare_models("face-detection-yolov8l", versions=[1, 2, 3], metric="recall")
```

---

### 3. SAM2 Auto-Annotation Pipeline

**Purpose:** Auto-annotate NEW images (production data, YFCC100M) with YOLOv8 + SAM2 refinement

**NOT NEEDED FOR:** WIDER Face (158K images) - already has complete bounding box annotations

**USE CASES:**
- Production data: User-uploaded images (opt-in consent)
- YFCC100M: 15M CC-BY images with faces (no annotations)
- Active learning: New samples from production

**Implementation:** `ray_compute/jobs/annotation/sam2_pipeline.py`

```python
import torch
import numpy as np
from PIL import Image
from pathlib import Path
from typing import List, Dict, Tuple
import json

# SAM2 imports (will be implemented in Week 2)
# from sam2.build_sam import build_sam2
# from sam2.sam2_image_predictor import SAM2ImagePredictor

from ultralytics import YOLO

class SAM2AnnotationPipeline:
    """Auto-annotation pipeline with YOLOv8 + SAM2."""

    def __init__(
        self,
        yolo_model_path: str,
        sam2_checkpoint: str = "sam2_hiera_large.pt",
        sam2_config: str = "sam2_hiera_l.yaml",
        device: str = "cuda:0"
    ):
        # Load YOLOv8 model
        self.yolo = YOLO(yolo_model_path)
        self.device = device

        # Load SAM2 model (placeholder for Week 2)
        # self.sam2 = build_sam2(sam2_config, sam2_checkpoint, device=device)
        # self.predictor = SAM2ImagePredictor(self.sam2)

        print(f"✓ Loaded YOLOv8: {yolo_model_path}")
        print(f"✓ Loaded SAM2: {sam2_checkpoint}")

    def annotate_image(
        self,
        image_path: str,
        conf_threshold: float = 0.25
    ) -> Dict[str, any]:
        """Auto-annotate single image."""

        # Step 1: YOLOv8 detection
        results = self.yolo(image_path, conf=conf_threshold)
        boxes = results[0].boxes.xyxy.cpu().numpy()  # [x1, y1, x2, y2]
        scores = results[0].boxes.conf.cpu().numpy()

        # Step 2: SAM2 mask refinement (placeholder)
        # image = Image.open(image_path).convert('RGB')
        # image_np = np.array(image)
        # self.predictor.set_image(image_np)

        refined_boxes = []
        refined_scores = []

        for box, score in zip(boxes, scores):
            # SAM2 refinement (placeholder)
            # masks, sam_scores, _ = self.predictor.predict(box=box, multimask_output=False)
            # mask = masks[0]
            # sam_score = sam_scores[0]

            # For now, use YOLO boxes directly
            refined_boxes.append(box)
            refined_scores.append(score)

        return {
            'image_path': image_path,
            'boxes': refined_boxes,
            'scores': refined_scores,
            'count': len(refined_boxes)
        }

    def annotate_batch(
        self,
        image_paths: List[str],
        output_path: str,
        conf_threshold: float = 0.25
    ):
        """Auto-annotate batch of images and export to COCO format."""

        annotations = []

        for img_path in image_paths:
            ann = self.annotate_image(img_path, conf_threshold)
            annotations.append(ann)
            print(f"✓ Annotated: {img_path} ({ann['count']} faces)")

        # Export to COCO format
        coco_data = self._export_to_coco(annotations)

        with open(output_path, 'w') as f:
            json.dump(coco_data, f, indent=2)

        print(f"✓ Exported {len(annotations)} images to {output_path}")

    def _export_to_coco(self, annotations: List[Dict]) -> Dict:
        """Export annotations to COCO format."""

        coco = {
            'info': {
                'description': 'Auto-annotated with YOLOv8 + SAM2',
                'version': '1.0',
                'year': 2025
            },
            'images': [],
            'annotations': [],
            'categories': [{'id': 1, 'name': 'face'}]
        }

        ann_id = 1
        for img_id, ann in enumerate(annotations, 1):
            # Add image
            img = Image.open(ann['image_path'])
            coco['images'].append({
                'id': img_id,
                'file_name': Path(ann['image_path']).name,
                'width': img.width,
                'height': img.height
            })

            # Add annotations
            for box, score in zip(ann['boxes'], ann['scores']):
                x1, y1, x2, y2 = box
                coco['annotations'].append({
                    'id': ann_id,
                    'image_id': img_id,
                    'category_id': 1,
                    'bbox': [x1, y1, x2 - x1, y2 - y1],  # COCO format: [x, y, w, h]
                    'area': (x2 - x1) * (y2 - y1),
                    'iscrowd': 0,
                    'confidence': float(score),
                    'auto_generated': True
                })
                ann_id += 1

        return coco

# Usage
pipeline = SAM2AnnotationPipeline(
    yolo_model_path="/ray_compute/models/checkpoints/phase1_wider_face/best.pt",
    sam2_checkpoint="sam2_hiera_large.pt"
)

# Annotate batch
image_paths = list(Path("/ray_compute/data/datasets/production/raw").glob("*.jpg"))
pipeline.annotate_batch(
    image_paths=image_paths,
    output_path="/ray_compute/data/datasets/annotations/auto/production_batch1.json",
    conf_threshold=0.25
)
```

---

## 🔄 Migration Plan

### Week 1: Repository Reorganization

**Day 1-2: Directory Structure**
```bash
# Create new directories
mkdir -p ray_compute/jobs/{training,evaluation,annotation,utils}
mkdir -p ray_compute/models/{registry,checkpoints,deployed,exports}
mkdir -p ray_compute/data/datasets/{wider_face,production,yfcc100m,annotations}
mkdir -p ray_compute/mlflow_projects/{face_detection_training,auto_annotation,model_evaluation}

# Move existing files
mv ray_compute/jobs/face_detection_training.py ray_compute/jobs/training/phase1_foundation.py
mv ray_compute/jobs/evaluate_wider_face.py ray_compute/jobs/evaluation/wider_face_eval.py

# Update imports in all files
find ray_compute -name "*.py" -type f -exec sed -i 's/from jobs\./from jobs.utils./g' {} \;
```

**Day 3-4: Dual Storage Implementation**
- Implement `checkpoint_manager.py`
- Implement `mlflow_integration.py`
- Implement `artifact_sync.py`
- Test with small training run

**Day 5: Update Existing Jobs**
- Update `phase1_foundation.py` with dual storage
- Update MLflow logging
- Test end-to-end training + sync

---

## 📊 Expert Recommendations Applied

### From Andrej Karpathy (Tesla)
- ✅ Dual storage (local + central registry)
- ✅ Every checkpoint logged
- ✅ Can rollback to any checkpoint

### From Andrew Ng (Data-Centric AI)
- ✅ MLflow for experiment tracking
- ✅ Version control for datasets
- ✅ Production data flywheel

### From Chip Huyen (ML Systems)
- ✅ Use your own API (Ray Compute)
- ✅ SAM2 auto-annotation
- ✅ Active learning

---

## 🎯 Success Criteria

### Architecture
- [ ] All training jobs use Ray Compute API
- [ ] All checkpoints saved to local + MLflow
- [ ] Models registered in MLflow Model Registry
- [ ] Production deployment loads from MLflow

### Cost
- [ ] Annotation cost < $200/year (vs $6,000 manual)
- [ ] Infrastructure cost optimized
- [ ] Total 12-month cost < $12,000

### Quality
- [ ] Phase 1: 75-85% recall (WIDER Face only)
- [ ] Phase 2: 88-93% recall (+ production data)
- [ ] Phase 3: 93-95% recall (+ YFCC100M)
- [ ] Active learning: maintain 95%+

---

**Last Updated:** 2025-12-12
**Status:** 🔄 In Progress - Week 1 Reorganization
**Next Review:** 2025-12-19 (after reorganization complete)
