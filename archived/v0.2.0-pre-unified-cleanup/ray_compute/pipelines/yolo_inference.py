"""
YOLO Inference Pipeline
Batch inference on images using trained YOLO model
"""

from api.client import RayComputeClient, JobType

# Inference code
inference_code = """
import torch
from ultralytics import YOLO
import mlflow
import glob
import os
from pathlib import Path

# Check GPU
print(f"CUDA available: {torch.cuda.is_available()}")

# Load trained model from MLflow
model_uri = "models:/yolo-detector/latest"
model_path = mlflow.artifacts.download_artifacts(model_uri)
model = YOLO(model_path)

# Input images directory
input_dir = "/data/images"  # Replace with your image directory
output_dir = "/output/detections"

# Create output directory
os.makedirs(output_dir, exist_ok=True)

# Get all images
image_files = glob.glob(f"{input_dir}/*.jpg") + glob.glob(f"{input_dir}/*.png")
print(f"Found {len(image_files)} images")

# Run batch inference
results = model.predict(
    source=image_files,
    save=True,
    save_txt=True,
    save_conf=True,
    project=output_dir,
    name='batch_inference',
    device=0,  # GPU
    batch=16,
    conf=0.25,
    iou=0.45
)

# Log results to MLflow
total_detections = sum(len(r.boxes) for r in results)
mlflow.log_metric("total_images", len(image_files))
mlflow.log_metric("total_detections", total_detections)
mlflow.log_metric("avg_detections_per_image", total_detections / len(image_files))

# Log detection outputs
mlflow.log_artifacts(output_dir, "inference_results")

print(f"\\nInference complete!")
print(f"Total images: {len(image_files)}")
print(f"Total detections: {total_detections}")
print(f"Results saved to: {output_dir}")
"""

# Submit job
client = RayComputeClient()

job_id = client.submit_job(
    name="yolo-batch-inference",
    code=inference_code,
    job_type=JobType.INFERENCE,
    cpu=4,
    memory_gb=4,
    gpu=1,
    timeout_minutes=60,
    mlflow_experiment="yolo-inference",
    mlflow_tags={
        "model": "yolo-detector",
        "task": "batch-inference",
        "pipeline": "inference",
    },
)

print(f"✓ Job submitted: {job_id}")
print(f"Monitor at: http://localhost:8265")
print(f"MLflow UI: http://localhost:8080")
