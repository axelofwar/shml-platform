"""
Automated Retraining Pipeline
End-to-end pipeline: inference → evaluation → curation → retraining
"""

from api.client import RayComputeClient, JobType
import time


def run_retraining_pipeline():
    """
    Automated retraining pipeline:
    1. Run inference on validation set
    2. Evaluate and identify failures
    3. Curate dataset from failure patterns
    4. Retrain model with augmented dataset
    """

    client = RayComputeClient()

    print("=" * 60)
    print("Starting Automated Retraining Pipeline")
    print("=" * 60)

    # Stage 1: Inference
    print("\n[Stage 1/4] Running inference on validation set...")

    inference_code = """
import torch
from ultralytics import YOLO
import mlflow
import json

model = YOLO('models:/yolo-detector/latest')
results = model.val(data='validation.yaml', device=0)

# Export results for analysis
metrics = {
    'map50': float(results.results_dict['metrics/mAP50(B)']),
    'map50_95': float(results.results_dict['metrics/mAP50-95(B)']),
    'precision': float(results.results_dict['metrics/precision(B)']),
    'recall': float(results.results_dict['metrics/recall(B)'])
}

with open('/tmp/validation_metrics.json', 'w') as f:
    json.dump(metrics, f)

mlflow.log_metrics(metrics)
mlflow.log_artifact('/tmp/validation_metrics.json')

print(f"Validation mAP50: {metrics['map50']:.4f}")
"""

    job_id_1 = client.submit_job(
        name="pipeline-1-inference",
        code=inference_code,
        job_type=JobType.INFERENCE,
        cpu=4,
        memory_gb=4,
        gpu=1,
        mlflow_experiment="auto-retraining-pipeline",
    )

    result_1 = client.wait_for_job(job_id_1)
    if result_1["status"] != "SUCCEEDED":
        print(f"✗ Inference failed: {result_1.get('error')}")
        return

    print("✓ Inference complete")

    # Stage 2: Failure Analysis
    print("\n[Stage 2/4] Analyzing failures and identifying patterns...")

    analysis_code = """
import json
import mlflow
import numpy as np

# Load validation results
with open('/tmp/validation_metrics.json', 'r') as f:
    metrics = json.load(f)

# Decision: retrain if mAP50 < 0.75
should_retrain = metrics['map50'] < 0.75

mlflow.log_param('should_retrain', should_retrain)
mlflow.log_param('retrain_threshold', 0.75)

if should_retrain:
    print(f"mAP50 ({metrics['map50']:.4f}) below threshold (0.75)")
    print("Retraining recommended")
else:
    print(f"mAP50 ({metrics['map50']:.4f}) above threshold (0.75)")
    print("No retraining needed")

# Save decision
with open('/tmp/retrain_decision.json', 'w') as f:
    json.dump({'should_retrain': should_retrain}, f)

mlflow.log_artifact('/tmp/retrain_decision.json')
"""

    job_id_2 = client.submit_job(
        name="pipeline-2-analysis",
        code=analysis_code,
        job_type=JobType.CUSTOM,
        cpu=2,
        memory_gb=2,
        gpu=0,
        mlflow_experiment="auto-retraining-pipeline",
    )

    result_2 = client.wait_for_job(job_id_2)
    if result_2["status"] != "SUCCEEDED":
        print(f"✗ Analysis failed: {result_2.get('error')}")
        return

    print("✓ Analysis complete")

    # Check if retraining is needed (in production, read from MLflow)
    # For demo, always proceed
    should_retrain = True

    if not should_retrain:
        print("\n✓ Model performance acceptable. No retraining needed.")
        return

    # Stage 3: Dataset Curation
    print("\n[Stage 3/4] Curating dataset from failure patterns...")

    curation_code = """
import mlflow
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans

# Simulate dataset curation (in production, use actual failure data)
print("Curating additional training samples from failure clusters...")

# Create curated dataset
n_curated = 500
curated_samples = pd.DataFrame({
    'image_id': [f'img_{i:05d}' for i in range(n_curated)],
    'cluster': np.random.randint(0, 5, n_curated),
    'confidence': np.random.uniform(0.3, 0.6, n_curated)
})

curated_samples.to_csv('/tmp/curated_dataset.csv', index=False)
mlflow.log_artifact('/tmp/curated_dataset.csv')
mlflow.log_metric('curated_samples', n_curated)

print(f"Curated {n_curated} samples for retraining")
"""

    job_id_3 = client.submit_job(
        name="pipeline-3-curation",
        code=curation_code,
        job_type=JobType.DATASET_CURATION,
        cpu=8,
        memory_gb=4,
        gpu=0,
        mlflow_experiment="auto-retraining-pipeline",
    )

    result_3 = client.wait_for_job(job_id_3)
    if result_3["status"] != "SUCCEEDED":
        print(f"✗ Curation failed: {result_3.get('error')}")
        return

    print("✓ Dataset curation complete")

    # Stage 4: Retraining
    print("\n[Stage 4/4] Retraining model with curated dataset...")

    retraining_code = """
import torch
from ultralytics import YOLO
import mlflow

print(f"CUDA available: {torch.cuda.is_available()}")

# Load current best model
model = YOLO('models:/yolo-detector/latest')

# Retrain with augmented dataset
results = model.train(
    data='augmented_dataset.yaml',  # Includes curated samples
    epochs=20,
    imgsz=640,
    batch=16,
    device=0,
    project='runs/retrain',
    name='auto_retrain',
    patience=10,
    resume=True
)

# Evaluate retrained model
val_results = model.val(data='validation.yaml')
new_map50 = float(val_results.results_dict['metrics/mAP50(B)'])

mlflow.log_metric('retrained_map50', new_map50)

# Register new version if improved
if new_map50 > 0.75:  # Threshold
    model_path = results.save_dir / 'weights' / 'best.pt'
    mlflow.log_artifact(str(model_path), 'model')

    model_uri = f"runs:/{mlflow.active_run().info.run_id}/model"
    mlflow.register_model(model_uri, "yolo-detector")

    print(f"✓ New model registered! mAP50: {new_map50:.4f}")
else:
    print(f"✗ Retraining did not improve performance: {new_map50:.4f}")
"""

    job_id_4 = client.submit_job(
        name="pipeline-4-retraining",
        code=retraining_code,
        job_type=JobType.TRAINING,
        cpu=8,
        memory_gb=8,
        gpu=1,
        timeout_minutes=360,
        mlflow_experiment="auto-retraining-pipeline",
    )

    result_4 = client.wait_for_job(job_id_4, poll_interval=30)
    if result_4["status"] != "SUCCEEDED":
        print(f"✗ Retraining failed: {result_4.get('error')}")
        return

    print("✓ Retraining complete")

    print("\n" + "=" * 60)
    print("Pipeline Complete!")
    print("=" * 60)
    print("\nCheck MLflow UI for results: http://localhost:8080")
    print(f"Experiment: auto-retraining-pipeline")


if __name__ == "__main__":
    run_retraining_pipeline()
