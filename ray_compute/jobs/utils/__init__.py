"""
Utility modules for Ray training jobs.

Reorganized structure (v2.0):
- checkpoint_manager: DualStorageManager for local + MLflow storage
- mlflow_integration: MLflowHelper for simplified MLflow operations
- tiny_face_augmentation: Data augmentation utilities
- test_cuda: GPU testing utilities
- test_threshold_comparison: Threshold analysis
- validate_yolov8l_face: Model validation
"""

# Core utilities available for import
from .checkpoint_manager import DualStorageManager
from .mlflow_integration import MLflowHelper

__all__ = ["DualStorageManager", "MLflowHelper"]
