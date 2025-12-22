"""
YOLO Training Pipeline
Submits a YOLO model training job to Ray Compute
"""

from api.client import RayComputeClient, JobType

# Training code
training_code = """
import torch
from ultralytics import YOLO
import mlflow
import os

# Check GPU availability
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")

# Load YOLO model (or create new)
model = YOLO('yolov8n.pt')  # Start with pretrained nano model

# Configure training
data_config = 'coco128.yaml'  # Replace with your dataset config

# Train model
results = model.train(
    data=data_config,
    epochs=10,
    imgsz=640,
    batch=16,
    device=0,  # Use GPU 0
    project='runs/train',
    name='yolo_training',
    save=True,
    save_period=5,  # Save every 5 epochs
    patience=10,
    verbose=True
)

# Log metrics to MLflow
for epoch, metrics in enumerate(results.results_dict.items()):
    mlflow.log_metrics({f"train/{k}": v for k, v in metrics}, step=epoch)

# Save final model
model_path = results.save_dir / 'weights' / 'best.pt'
mlflow.log_artifact(str(model_path), 'model')

# Register model in MLflow
model_uri = f"runs:/{mlflow.active_run().info.run_id}/model"
mlflow.register_model(model_uri, "yolo-detector")

print(f"Training complete! Model saved to {model_path}")
"""

# Submit job
client = RayComputeClient()

job_id = client.submit_job(
    name="yolo-training-run",
    code=training_code,
    job_type=JobType.TRAINING,
    cpu=8,
    memory_gb=8,
    gpu=1,
    timeout_minutes=240,
    mlflow_experiment="yolo-training",
    mlflow_tags={
        "model": "yolov8n",
        "task": "object-detection",
        "pipeline": "training",
    },
)

print(f"✓ Job submitted: {job_id}")
print(f"Monitor at: http://localhost:8265")
print(f"MLflow UI: http://localhost:8080")

# Wait for completion (optional)
print("\nWaiting for job to complete...")
result = client.wait_for_job(job_id, poll_interval=10)
print(f"\nJob status: {result['status']}")

if result["status"] == "SUCCEEDED":
    print("✓ Training completed successfully!")
else:
    print(f"✗ Training failed: {result.get('error', 'Unknown error')}")
