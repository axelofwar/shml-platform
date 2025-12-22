"""
Dual Storage Manager for model checkpoints.
Saves to both local disk (fast I/O) and MLflow (versioned).

Usage:
    manager = DualStorageManager(
        local_dir="/ray_compute/models/checkpoints/phase1_wider_face",
        mlflow_experiment="face-detection-training",
        sync_strategy="async"
    )

    # In training loop
    manager.save(epoch=10, model=model, metrics=results.results_dict)

    # After training
    manager.register_model(
        model_name="face-detection-yolov8l",
        model_version="phase1-v1",
        model_path=str(manager.local_dir / "best.pt")
    )
"""

import mlflow
from pathlib import Path
from typing import Dict, Any, Optional
import torch
import json
import threading
import queue
import os


class DualStorageManager:
    """Manages model checkpoints with dual storage (local + MLflow)."""

    def __init__(
        self,
        local_dir: str,
        mlflow_experiment: str,
        sync_strategy: str = "async",  # "async" or "sync"
        mlflow_tracking_uri: str = None,
    ):
        self.local_dir = Path(local_dir)
        self.local_dir.mkdir(parents=True, exist_ok=True)

        self.mlflow_experiment = mlflow_experiment
        self.sync_strategy = sync_strategy

        # Set MLflow tracking URI
        if mlflow_tracking_uri:
            mlflow.set_tracking_uri(mlflow_tracking_uri)

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
        metadata: Dict[str, Any] = None,
    ) -> str:
        """Save checkpoint to local storage and queue for MLflow sync."""

        # Save to local disk (FAST)
        local_path = self.local_dir / f"epoch_{epoch}.pt"
        torch.save(
            {
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "metrics": metrics,
                "metadata": metadata or {},
            },
            local_path,
        )

        # Save metadata JSON
        metadata_path = self.local_dir / f"epoch_{epoch}_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(
                {
                    "epoch": epoch,
                    "metrics": metrics,
                    "metadata": metadata or {},
                    "local_path": str(local_path),
                },
                f,
                indent=2,
            )

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
                self._sync_to_mlflow(
                    epoch, local_path, metadata_path, metrics, metadata
                )
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
        metadata: Dict[str, Any],
    ):
        """Sync checkpoint to MLflow (runs in background thread)."""

        try:
            # Log to active MLflow run (must be within active run context)
            if mlflow.active_run():
                mlflow.log_artifact(str(local_path), artifact_path="checkpoints")
                mlflow.log_artifact(str(metadata_path), artifact_path="checkpoints")
                mlflow.log_metrics(metrics, step=epoch)
                print(f"✓ Synced to MLflow: epoch {epoch}")
            else:
                print(f"⚠ No active MLflow run, skipping sync for epoch {epoch}")
        except Exception as e:
            print(f"✗ MLflow sync error for epoch {epoch}: {e}")

    def load_best(self) -> tuple:
        """Load best checkpoint from local storage."""
        # Find best checkpoint by metrics
        best_path = self.local_dir / "best.pt"
        if best_path.exists():
            checkpoint = torch.load(best_path)
            return checkpoint["model_state_dict"], checkpoint["metrics"]
        else:
            raise FileNotFoundError(f"No best checkpoint found in {self.local_dir}")

    def load_epoch(self, epoch: int) -> tuple:
        """Load specific epoch checkpoint."""
        epoch_path = self.local_dir / f"epoch_{epoch}.pt"
        if epoch_path.exists():
            checkpoint = torch.load(epoch_path)
            return checkpoint["model_state_dict"], checkpoint["metrics"]
        else:
            raise FileNotFoundError(f"Checkpoint for epoch {epoch} not found")

    def register_model(
        self,
        model_name: str,
        model_version: str,
        model_path: str,
        tags: Dict[str, str] = None,
    ):
        """Register model in MLflow Model Registry."""

        try:
            # Log model to MLflow
            with mlflow.start_run(experiment_id=self.mlflow_experiment):
                mlflow.log_artifact(model_path, artifact_path="model")

                # Register model
                model_uri = f"runs:/{mlflow.active_run().info.run_id}/model"
                registered_model = mlflow.register_model(
                    model_uri=model_uri, name=model_name, tags=tags or {}
                )

                print(f"✓ Registered model: {model_name} v{registered_model.version}")
                return registered_model
        except Exception as e:
            print(f"✗ Model registration failed: {e}")
            return None

    def wait_for_sync(self, timeout: int = 30):
        """Wait for all pending syncs to complete."""
        if self.sync_strategy == "async":
            self.sync_queue.join()
            print("✓ All checkpoints synced to MLflow")
