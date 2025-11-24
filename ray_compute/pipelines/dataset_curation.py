"""
Dataset Curation Pipeline
Analyze failure patterns and curate datasets using clustering
"""

from api.client import RayComputeClient, JobType

# Dataset curation code
curation_code = """
import pandas as pd
import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.preprocessing import StandardScaler
import mlflow
import pickle

# Load inference results and ground truth
inference_df = pd.read_csv('/data/inference_results.csv')
ground_truth_df = pd.read_csv('/data/ground_truth.csv')

# Merge on image_id
merged = inference_df.merge(ground_truth_df, on='image_id', suffixes=('_pred', '_gt'))

# Calculate per-image metrics
def calculate_iou(box1, box2):
    # IoU calculation (simplified)
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - intersection
    
    return intersection / union if union > 0 else 0

# Extract features for clustering
features = []
failed_samples = []

for idx, row in merged.iterrows():
    iou = calculate_iou(
        row[['x1_pred', 'y1_pred', 'x2_pred', 'y2_pred']].values,
        row[['x1_gt', 'y1_gt', 'x2_gt', 'y2_gt']].values
    )
    
    # Consider failures (low IoU)
    if iou < 0.5:
        features.append([
            row['confidence'],
            row['image_brightness'],
            row['image_contrast'],
            row['object_size'],
            row['occlusion_level'],
            iou
        ])
        failed_samples.append({
            'image_id': row['image_id'],
            'iou': iou,
            'confidence': row['confidence']
        })

features = np.array(features)
print(f"Found {len(features)} failed samples")

# Standardize features
scaler = StandardScaler()
features_scaled = scaler.fit_transform(features)

# Cluster failed samples to identify patterns
clusterer = HDBSCAN(min_cluster_size=10, min_samples=5)
cluster_labels = clusterer.fit_predict(features_scaled)

# Analyze clusters
n_clusters = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
print(f"Identified {n_clusters} failure pattern clusters")

# Log cluster information
cluster_info = {}
for cluster_id in range(n_clusters):
    cluster_mask = cluster_labels == cluster_id
    cluster_samples = np.array(failed_samples)[cluster_mask]
    
    cluster_info[f"cluster_{cluster_id}"] = {
        "size": int(cluster_mask.sum()),
        "avg_iou": float(features[cluster_mask, -1].mean()),
        "avg_confidence": float(features[cluster_mask, 0].mean())
    }
    
    mlflow.log_metric(f"cluster_{cluster_id}_size", cluster_mask.sum())

# Save cluster analysis
mlflow.log_dict(cluster_info, "cluster_analysis.json")

# Create curated dataset: images from identified failure clusters
curated_image_ids = [s['image_id'] for i, s in enumerate(failed_samples) 
                     if cluster_labels[i] != -1]

curated_df = merged[merged['image_id'].isin(curated_image_ids)]
curated_df.to_csv('/output/curated_dataset.csv', index=False)

# Log curated dataset
mlflow.log_artifact('/output/curated_dataset.csv', 'curated_dataset')
mlflow.log_metric("curated_samples", len(curated_image_ids))
mlflow.log_metric("failure_clusters", n_clusters)

print(f"\\nDataset curation complete!")
print(f"Curated samples: {len(curated_image_ids)}")
print(f"Failure patterns identified: {n_clusters}")
"""

# Submit job
client = RayComputeClient()

job_id = client.submit_job(
    name="dataset-curation-clustering",
    code=curation_code,
    job_type=JobType.DATASET_CURATION,
    cpu=12,
    memory_gb=6,
    gpu=0,  # CPU-only
    timeout_minutes=120,
    mlflow_experiment="dataset-curation",
    mlflow_tags={
        "method": "hdbscan-clustering",
        "task": "failure-analysis",
        "pipeline": "curation"
    }
)

print(f"✓ Job submitted: {job_id}")
print(f"Monitor at: http://localhost:8265")
print(f"MLflow UI: http://localhost:8080")
