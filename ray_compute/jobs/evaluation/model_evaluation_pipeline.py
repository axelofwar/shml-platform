#!/usr/bin/env python3
"""
Model Evaluation Pipeline for Face Detection
=============================================

This script:
1. Registers models in MLflow model registry
2. Evaluates models against WIDER Face validation set
3. Pushes metrics to Prometheus for Grafana visualization
4. Compares models against PII KPI targets

Usage:
    python model_evaluation_pipeline.py --register-only    # Just register models
    python model_evaluation_pipeline.py --evaluate-only    # Just run evaluation
    python model_evaluation_pipeline.py                    # Full pipeline

PII KPI Targets:
    - mAP50: > 94%
    - Recall: > 95%
    - Precision: > 90%
"""

import os
import sys
import json
import time
import hashlib
import argparse
import urllib.request
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any, Tuple
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================


@dataclass
class ModelConfig:
    """Configuration for a model to evaluate"""

    model_id: str
    name: str
    description: str
    path: str
    mlflow_tags: Dict[str, str]


@dataclass
class PIITargets:
    """PII KPI target thresholds"""

    mAP50: float = 0.94
    recall: float = 0.95
    precision: float = 0.90


@dataclass
class EvaluationResult:
    """Results from model evaluation"""

    model_id: str
    model_name: str
    mAP50: float
    mAP50_95: float
    precision: float
    recall: float
    f1_score: float
    inference_time_ms: float
    total_images: int
    total_detections: int
    timestamp: str

    # Gap analysis vs PII targets
    mAP50_gap: float = 0.0
    recall_gap: float = 0.0
    precision_gap: float = 0.0
    meets_targets: bool = False


# Models to evaluate
MODELS = [
    ModelConfig(
        model_id="base-yolov8l-face",
        name="YOLOv8L-Face Base",
        description="Pre-trained YOLOv8L face detection model from HuggingFace",
        path="/tmp/ray/models/base-yolov8l-face.pt",
        mlflow_tags={
            "model_type": "yolov8l-face",
            "training_status": "pretrained",
            "source": "huggingface",
            "dataset": "various",
        },
    ),
    ModelConfig(
        model_id="phase1-wider-face-v1",
        name="Phase 1 WIDER Face Training",
        description="Phase 1 training on WIDER Face (640px, 35 epochs, batch=8)",
        path="/tmp/ray/models/phase1-wider-face-v1.pt",
        mlflow_tags={
            "model_type": "yolov8l-face",
            "training_status": "phase1_complete",
            "source": "local_training",
            "dataset": "wider_face",
            "image_size": "640",
            "epochs": "35",
            "batch_size": "8",
        },
    ),
    ModelConfig(
        model_id="phase3-wider-face-v1",
        name="Phase 3 WIDER Face Training (OOM)",
        description="Phase 3 training on WIDER Face (1280px, epoch 14/100, OOM crash)",
        path="/tmp/ray/models/phase3-wider-face-v1.pt",
        mlflow_tags={
            "model_type": "yolov8l-face",
            "training_status": "phase3_interrupted",
            "source": "local_training",
            "dataset": "wider_face",
            "image_size": "1280",
            "epochs_completed": "14",
            "epochs_target": "100",
            "interruption_reason": "OOM",
        },
    ),
]

# Environment config
_mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-nginx:80")
# Ensure /mlflow path is included for nginx proxy
if not _mlflow_uri.endswith("/mlflow") and "mlflow-nginx" in _mlflow_uri:
    _mlflow_uri = _mlflow_uri.rstrip("/") + "/mlflow"
MLFLOW_BASE_URL = _mlflow_uri
PUSHGATEWAY_URL = os.getenv("PUSHGATEWAY_URL", "http://shml-pushgateway:9091")
VALIDATION_DATA_PATH = os.getenv(
    "VALIDATION_DATA_PATH", "/tmp/ray/data/wider_face_yolo/images/val"
)
PII_TARGETS = PIITargets()

# =============================================================================
# MLflow Integration
# =============================================================================


class MLflowClient:
    """Simple MLflow REST API client"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        # MLflow uses ajax-api for REST endpoints when behind nginx proxy
        self.ajax_api = f"{self.base_url}/ajax-api/2.0/mlflow"
        logger.info(f"MLflow client initialized with base: {self.ajax_api}")

    def _request(self, endpoint: str, method: str = "GET", data: dict = None) -> dict:
        """Make HTTP request to MLflow API"""
        # Ensure endpoint doesn't have leading slash
        endpoint = endpoint.lstrip("/")
        url = f"{self.ajax_api}/{endpoint}"
        headers = {"Content-Type": "application/json"}

        if data:
            body = json.dumps(data).encode("utf-8")
        else:
            body = b"{}" if method == "POST" else None

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            logger.error(f"MLflow API error {e.code}: {error_body}")
            raise

    def get_or_create_experiment(self, name: str) -> str:
        """Get experiment ID or create if doesn't exist"""
        # Search for existing
        try:
            result = self._request(
                "experiments/search",
                "POST",
                {"filter": f"name = '{name}'", "max_results": 1},
            )
            experiments = result.get("experiments", [])
            if experiments:
                return experiments[0]["experiment_id"]
        except Exception as e:
            logger.warning(f"Error searching experiments: {e}")

        # Create new
        result = self._request("experiments/create", "POST", {"name": name})
        return result["experiment_id"]

    def create_run(
        self, experiment_id: str, run_name: str, tags: Dict[str, str] = None
    ) -> str:
        """Create a new MLflow run"""
        data = {
            "experiment_id": experiment_id,
            "run_name": run_name,
            "start_time": int(time.time() * 1000),
            "tags": [{"key": k, "value": v} for k, v in (tags or {}).items()],
        }
        result = self._request("runs/create", "POST", data)
        return result["run"]["info"]["run_id"]

    def log_metrics(self, run_id: str, metrics: Dict[str, float], step: int = 0):
        """Log metrics to a run"""
        timestamp = int(time.time() * 1000)
        data = {
            "run_id": run_id,
            "metrics": [
                {"key": k, "value": v, "timestamp": timestamp, "step": step}
                for k, v in metrics.items()
            ],
        }
        self._request("runs/log-batch", "POST", data)

    def log_params(self, run_id: str, params: Dict[str, str]):
        """Log parameters to a run"""
        data = {
            "run_id": run_id,
            "params": [{"key": k, "value": str(v)} for k, v in params.items()],
        }
        self._request("runs/log-batch", "POST", data)

    def set_tag(self, run_id: str, key: str, value: str):
        """Set a tag on a run"""
        self._request(
            "runs/set-tag", "POST", {"run_id": run_id, "key": key, "value": value}
        )

    def end_run(self, run_id: str, status: str = "FINISHED"):
        """End a run"""
        self._request(
            "runs/update",
            "POST",
            {"run_id": run_id, "status": status, "end_time": int(time.time() * 1000)},
        )

    def get_or_create_registered_model(self, name: str) -> str:
        """Get or create a registered model"""
        try:
            result = self._request("registered-models/get", "GET")
        except:
            pass

        try:
            self._request("registered-models/create", "POST", {"name": name})
            logger.info(f"Created registered model: {name}")
        except urllib.error.HTTPError as e:
            if e.code == 400:  # Already exists
                logger.info(f"Registered model already exists: {name}")
            else:
                raise
        return name

    def create_model_version(
        self,
        model_name: str,
        run_id: str,
        source: str,
        description: str = None,
        tags: Dict[str, str] = None,
    ) -> str:
        """Create a new model version"""
        data = {
            "name": model_name,
            "source": source,
            "run_id": run_id,
        }
        if description:
            data["description"] = description
        if tags:
            data["tags"] = [{"key": k, "value": v} for k, v in tags.items()]

        result = self._request("model-versions/create", "POST", data)
        return result["model_version"]["version"]


# =============================================================================
# Prometheus Push Gateway Integration
# =============================================================================


class PrometheusMetrics:
    """Push metrics to Prometheus Push Gateway"""

    def __init__(
        self, pushgateway_url: str, job_name: str = "face_detection_evaluation"
    ):
        self.pushgateway_url = pushgateway_url.rstrip("/")
        self.job_name = job_name

    def push_evaluation_metrics(self, result: EvaluationResult):
        """Push evaluation metrics to Prometheus"""
        metrics = self._format_metrics(result)
        url = f"{self.pushgateway_url}/metrics/job/{self.job_name}/model/{result.model_id}"

        req = urllib.request.Request(
            url,
            data=metrics.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "text/plain"},
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info(f"Pushed metrics for {result.model_id} to Prometheus")
        except Exception as e:
            logger.warning(f"Failed to push metrics: {e}")

    def _format_metrics(self, result: EvaluationResult) -> str:
        """Format metrics in Prometheus exposition format"""
        timestamp_ms = int(
            datetime.fromisoformat(result.timestamp.replace("Z", "+00:00")).timestamp()
            * 1000
        )

        lines = [
            f"# HELP face_detection_map50 Mean Average Precision at IoU 0.50",
            f"# TYPE face_detection_map50 gauge",
            f'face_detection_map50{{model="{result.model_id}",model_name="{result.model_name}"}} {result.mAP50}',
            f"",
            f"# HELP face_detection_map50_95 Mean Average Precision at IoU 0.50-0.95",
            f"# TYPE face_detection_map50_95 gauge",
            f'face_detection_map50_95{{model="{result.model_id}",model_name="{result.model_name}"}} {result.mAP50_95}',
            f"",
            f"# HELP face_detection_precision Precision score",
            f"# TYPE face_detection_precision gauge",
            f'face_detection_precision{{model="{result.model_id}",model_name="{result.model_name}"}} {result.precision}',
            f"",
            f"# HELP face_detection_recall Recall score",
            f"# TYPE face_detection_recall gauge",
            f'face_detection_recall{{model="{result.model_id}",model_name="{result.model_name}"}} {result.recall}',
            f"",
            f"# HELP face_detection_f1 F1 score",
            f"# TYPE face_detection_f1 gauge",
            f'face_detection_f1{{model="{result.model_id}",model_name="{result.model_name}"}} {result.f1_score}',
            f"",
            f"# HELP face_detection_inference_time_ms Inference time in milliseconds",
            f"# TYPE face_detection_inference_time_ms gauge",
            f'face_detection_inference_time_ms{{model="{result.model_id}",model_name="{result.model_name}"}} {result.inference_time_ms}',
            f"",
            f"# HELP face_detection_map50_gap Gap to PII target (positive = below target)",
            f"# TYPE face_detection_map50_gap gauge",
            f'face_detection_map50_gap{{model="{result.model_id}",target="0.94"}} {result.mAP50_gap}',
            f"",
            f"# HELP face_detection_recall_gap Gap to PII target (positive = below target)",
            f"# TYPE face_detection_recall_gap gauge",
            f'face_detection_recall_gap{{model="{result.model_id}",target="0.95"}} {result.recall_gap}',
            f"",
            f"# HELP face_detection_precision_gap Gap to PII target (positive = below target)",
            f"# TYPE face_detection_precision_gap gauge",
            f'face_detection_precision_gap{{model="{result.model_id}",target="0.90"}} {result.precision_gap}',
            f"",
            f"# HELP face_detection_meets_targets Whether model meets all PII targets (1=yes, 0=no)",
            f"# TYPE face_detection_meets_targets gauge",
            f'face_detection_meets_targets{{model="{result.model_id}"}} {1 if result.meets_targets else 0}',
        ]

        return "\n".join(lines)


# =============================================================================
# Model Evaluation
# =============================================================================


def evaluate_model(
    model_path: str,
    data_path: str,
    model_id: str,
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
) -> EvaluationResult:
    """
    Evaluate a model on WIDER Face validation set using YOLO's built-in validation

    Args:
        model_path: Path to the model weights
        data_path: Path to validation data (YOLO format)
        model_id: Model identifier for tracking
        conf_threshold: Confidence threshold for detections
        iou_threshold: IoU threshold for NMS

    Returns:
        EvaluationResult with all metrics
    """
    try:
        # Use upgraded ultralytics from user install
        import sys

        sys.path.insert(0, "/home/ray/.local/lib/python3.11/site-packages")
        from ultralytics import YOLO
        import torch
    except ImportError:
        logger.error("ultralytics not installed. Run: pip install ultralytics")
        raise

    logger.info(f"Loading model: {model_path}")
    model = YOLO(model_path)

    # Use the existing data.yaml at the dataset root
    data_yaml = Path("/tmp/ray/data/wider_face_yolo/data.yaml")
    if not data_yaml.exists():
        raise FileNotFoundError(f"data.yaml not found at {data_yaml}")

    logger.info(f"Running validation on: {data_path}")
    start_time = time.time()

    # Run validation
    results = model.val(
        data=str(data_yaml),
        split="val",
        batch=16,
        imgsz=640,
        conf=conf_threshold,
        iou=iou_threshold,
        device=0 if torch.cuda.is_available() else "cpu",
        verbose=True,
        save_json=True,
    )

    inference_time = (time.time() - start_time) * 1000  # ms total

    # Extract metrics
    # YOLO returns metrics as numpy arrays
    box_metrics = results.box

    mAP50 = float(box_metrics.map50) if hasattr(box_metrics, "map50") else 0.0
    mAP50_95 = float(box_metrics.map) if hasattr(box_metrics, "map") else 0.0

    # Get precision and recall at optimal threshold
    # These are arrays over IoU thresholds, we take mean or specific value
    precision = (
        float(box_metrics.mp) if hasattr(box_metrics, "mp") else 0.0
    )  # mean precision
    recall = float(box_metrics.mr) if hasattr(box_metrics, "mr") else 0.0  # mean recall

    # Calculate F1
    if precision + recall > 0:
        f1_score = 2 * (precision * recall) / (precision + recall)
    else:
        f1_score = 0.0

    # Get total images processed
    total_images = len(results.speed) if hasattr(results, "speed") else 0

    # Calculate gaps
    mAP50_gap = max(0, PII_TARGETS.mAP50 - mAP50)
    recall_gap = max(0, PII_TARGETS.recall - recall)
    precision_gap = max(0, PII_TARGETS.precision - precision)

    meets_targets = (
        mAP50 >= PII_TARGETS.mAP50
        and recall >= PII_TARGETS.recall
        and precision >= PII_TARGETS.precision
    )

    # Calculate average inference time per image
    avg_inference_ms = inference_time / max(total_images, 1)

    result = EvaluationResult(
        model_id=model_id,
        model_name=model_id,
        mAP50=mAP50,
        mAP50_95=mAP50_95,
        precision=precision,
        recall=recall,
        f1_score=f1_score,
        inference_time_ms=avg_inference_ms,
        total_images=total_images,
        total_detections=0,  # Would need additional counting
        timestamp=datetime.utcnow().isoformat() + "Z",
        mAP50_gap=mAP50_gap,
        recall_gap=recall_gap,
        precision_gap=precision_gap,
        meets_targets=meets_targets,
    )

    return result


# =============================================================================
# Main Pipeline
# =============================================================================


def register_models_in_mlflow(
    mlflow_client: MLflowClient, models: List[ModelConfig]
) -> Dict[str, str]:
    """Register all models in MLflow model registry"""

    logger.info("=" * 60)
    logger.info("Registering models in MLflow")
    logger.info("=" * 60)

    # Create/get experiment
    experiment_id = mlflow_client.get_or_create_experiment(
        "Face-Detection-Model-Registry"
    )
    logger.info(f"Using experiment ID: {experiment_id}")

    # Create registered model
    registered_model_name = "face-detection-pii"
    mlflow_client.get_or_create_registered_model(registered_model_name)

    run_ids = {}

    for model in models:
        logger.info(f"\nRegistering: {model.name}")

        # Check if model file exists
        if not Path(model.path).exists():
            logger.warning(f"  Model file not found: {model.path}")
            continue

        # Create run for this model
        run_id = mlflow_client.create_run(
            experiment_id=experiment_id,
            run_name=f"register_{model.model_id}",
            tags={
                "model_id": model.model_id,
                "registration_type": "model_registry",
                **model.mlflow_tags,
            },
        )
        run_ids[model.model_id] = run_id

        # Log model parameters
        mlflow_client.log_params(
            run_id,
            {
                "model_id": model.model_id,
                "model_name": model.name,
                "model_path": model.path,
                **{f"tag_{k}": v for k, v in model.mlflow_tags.items()},
            },
        )

        # Log file hash for reproducibility
        with open(model.path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        mlflow_client.log_params(run_id, {"file_md5": file_hash})

        # Create model version
        try:
            version = mlflow_client.create_model_version(
                model_name=registered_model_name,
                run_id=run_id,
                source=f"file://{model.path}",
                description=model.description,
                tags=model.mlflow_tags,
            )
            logger.info(f"  Created model version: {version}")
        except Exception as e:
            logger.warning(f"  Could not create model version: {e}")

        # End the registration run
        mlflow_client.end_run(run_id)
        logger.info(f"  Registered successfully")

    return run_ids


def run_evaluations(
    mlflow_client: MLflowClient,
    prometheus: PrometheusMetrics,
    models: List[ModelConfig],
    data_path: str,
) -> List[EvaluationResult]:
    """Run evaluation on all models"""

    logger.info("=" * 60)
    logger.info("Running Model Evaluations")
    logger.info("=" * 60)

    # Create experiment for evaluations
    experiment_id = mlflow_client.get_or_create_experiment("Face-Detection-Evaluation")

    results = []

    for model in models:
        logger.info(f"\nEvaluating: {model.name}")

        if not Path(model.path).exists():
            logger.warning(f"  Model file not found: {model.path}")
            continue

        # Create run for evaluation
        run_id = mlflow_client.create_run(
            experiment_id=experiment_id,
            run_name=f"eval_{model.model_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            tags={
                "model_id": model.model_id,
                "evaluation_type": "wider_face_validation",
                "pii_target_map50": str(PII_TARGETS.mAP50),
                "pii_target_recall": str(PII_TARGETS.recall),
                "pii_target_precision": str(PII_TARGETS.precision),
            },
        )

        try:
            # Run evaluation
            result = evaluate_model(
                model_path=model.path, data_path=data_path, model_id=model.model_id
            )
            result.model_name = model.name
            results.append(result)

            # Log metrics to MLflow
            mlflow_client.log_metrics(
                run_id,
                {
                    "mAP50": result.mAP50,
                    "mAP50_95": result.mAP50_95,
                    "precision": result.precision,
                    "recall": result.recall,
                    "f1_score": result.f1_score,
                    "inference_time_ms": result.inference_time_ms,
                    "mAP50_gap": result.mAP50_gap,
                    "recall_gap": result.recall_gap,
                    "precision_gap": result.precision_gap,
                    "meets_targets": 1.0 if result.meets_targets else 0.0,
                },
            )

            # Push to Prometheus
            prometheus.push_evaluation_metrics(result)

            # Log summary
            logger.info(
                f"  mAP50: {result.mAP50:.4f} (target: {PII_TARGETS.mAP50}, gap: {result.mAP50_gap:.4f})"
            )
            logger.info(
                f"  Recall: {result.recall:.4f} (target: {PII_TARGETS.recall}, gap: {result.recall_gap:.4f})"
            )
            logger.info(
                f"  Precision: {result.precision:.4f} (target: {PII_TARGETS.precision}, gap: {result.precision_gap:.4f})"
            )
            logger.info(f"  F1: {result.f1_score:.4f}")
            logger.info(
                f"  Meets PII Targets: {'✓ YES' if result.meets_targets else '✗ NO'}"
            )

            mlflow_client.end_run(run_id, "FINISHED")

        except Exception as e:
            logger.error(f"  Evaluation failed: {e}")
            mlflow_client.end_run(run_id, "FAILED")

    return results


def print_comparison_table(results: List[EvaluationResult]):
    """Print a comparison table of all evaluation results"""

    logger.info("\n" + "=" * 80)
    logger.info("MODEL COMPARISON - PII KPI EVALUATION")
    logger.info("=" * 80)

    # Header
    print(
        f"\n{'Model':<35} {'mAP50':<12} {'Recall':<12} {'Precision':<12} {'F1':<10} {'Targets'}"
    )
    print(f"{'─' * 35} {'─' * 12} {'─' * 12} {'─' * 12} {'─' * 10} {'─' * 8}")

    # Targets row
    print(
        f"{'PII TARGETS':<35} {PII_TARGETS.mAP50:<12.2%} {PII_TARGETS.recall:<12.2%} {PII_TARGETS.precision:<12.2%} {'─':<10} {'─'}"
    )
    print(f"{'─' * 35} {'─' * 12} {'─' * 12} {'─' * 12} {'─' * 10} {'─' * 8}")

    # Results
    for r in results:
        meets = "✓ PASS" if r.meets_targets else "✗ FAIL"
        print(
            f"{r.model_name[:34]:<35} {r.mAP50:<12.2%} {r.recall:<12.2%} {r.precision:<12.2%} {r.f1_score:<10.2%} {meets}"
        )

    print()

    # Gap analysis
    logger.info("\nGAP ANALYSIS (vs PII Targets):")
    print(f"\n{'Model':<35} {'mAP50 Gap':<15} {'Recall Gap':<15} {'Precision Gap':<15}")
    print(f"{'─' * 35} {'─' * 15} {'─' * 15} {'─' * 15}")

    for r in results:
        map_status = f"-{r.mAP50_gap:.2%}" if r.mAP50_gap > 0 else "✓ OK"
        recall_status = f"-{r.recall_gap:.2%}" if r.recall_gap > 0 else "✓ OK"
        prec_status = f"-{r.precision_gap:.2%}" if r.precision_gap > 0 else "✓ OK"
        print(
            f"{r.model_name[:34]:<35} {map_status:<15} {recall_status:<15} {prec_status:<15}"
        )

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Face Detection Model Evaluation Pipeline"
    )
    parser.add_argument(
        "--register-only", action="store_true", help="Only register models in MLflow"
    )
    parser.add_argument(
        "--evaluate-only", action="store_true", help="Only run evaluations"
    )
    parser.add_argument("--model", type=str, help="Evaluate specific model by ID")
    parser.add_argument(
        "--data-path",
        type=str,
        default=VALIDATION_DATA_PATH,
        help="Path to validation data",
    )
    parser.add_argument(
        "--mlflow-url", type=str, default=MLFLOW_BASE_URL, help="MLflow tracking URI"
    )
    parser.add_argument(
        "--pushgateway-url",
        type=str,
        default=PUSHGATEWAY_URL,
        help="Prometheus push gateway URL",
    )

    args = parser.parse_args()

    # Initialize clients
    mlflow_client = MLflowClient(args.mlflow_url)
    prometheus = PrometheusMetrics(args.pushgateway_url)

    # Filter models if specific one requested
    models_to_process = MODELS
    if args.model:
        models_to_process = [m for m in MODELS if m.model_id == args.model]
        if not models_to_process:
            logger.error(f"Model not found: {args.model}")
            logger.info(f"Available models: {[m.model_id for m in MODELS]}")
            sys.exit(1)

    results = []

    # Step 1: Register models
    if not args.evaluate_only:
        register_models_in_mlflow(mlflow_client, models_to_process)

    # Step 2: Run evaluations
    if not args.register_only:
        results = run_evaluations(
            mlflow_client, prometheus, models_to_process, args.data_path
        )

        # Print comparison
        if results:
            print_comparison_table(results)

    logger.info("Pipeline complete!")

    # Return exit code based on whether any model meets targets
    if results and any(r.meets_targets for r in results):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
