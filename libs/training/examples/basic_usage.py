"""
Example: Using SHML Training Library

Demonstrates the new modular training API with callbacks.
"""

from shml_training.core import (
    Trainer,
    UltralyticsTrainer,
    TrainingConfig,
    TrainingCallback,
)


# =============================================================================
# Example 1: Custom Callback
# =============================================================================


class PrintProgressCallback(TrainingCallback):
    """Simple callback that prints training progress."""

    def on_run_start(self, trainer, config):
        print(f"🚀 Starting training run: {trainer.run_id}")
        print(f"   Epochs: {config['epochs']}")
        print(f"   Batch size: {config['batch_size']}")

    def on_epoch_end(self, trainer, epoch, metrics):
        print(f"📊 Epoch {epoch + 1}: {metrics}")

    def on_run_end(self, trainer, metrics):
        print(f"✅ Training complete!")
        print(f"   Final metrics: {metrics}")


class MLflowCallback(TrainingCallback):
    """Callback that logs metrics to MLflow."""

    def on_run_start(self, trainer, config):
        import mlflow

        mlflow.start_run(run_name=trainer.run_id)
        mlflow.log_params(config)
        print(f"📝 MLflow run started: {mlflow.active_run().info.run_id}")

    def on_epoch_end(self, trainer, epoch, metrics):
        import mlflow

        mlflow.log_metrics(metrics, step=epoch)

    def on_run_end(self, trainer, metrics):
        import mlflow

        mlflow.log_metrics(metrics)
        mlflow.end_run()
        print(f"📝 MLflow run complete")


# =============================================================================
# Example 2: Basic Training with Ultralytics
# =============================================================================


def example_basic_training():
    """Train YOLOv8 with default settings."""

    # Configure training
    config = TrainingConfig(
        epochs=50,
        batch_size=16,
        device="cuda:0",
        checkpoint_dir="./checkpoints/yolov8n",
    )

    # Create trainer
    trainer = UltralyticsTrainer(
        config=config,
        model_name="yolov8n.pt",
        callbacks=[PrintProgressCallback()],
    )

    # Train
    results = trainer.train()
    print(f"Training complete: {results}")


# =============================================================================
# Example 3: Training with Multiple Callbacks
# =============================================================================


def example_training_with_callbacks():
    """Train with progress printing and MLflow logging."""

    config = TrainingConfig.auto_configure(
        model_size_billions=0.003,  # YOLOv8n is ~3M params
        target_batch_size=16,
    )

    # Add custom attributes
    config.epochs = 100
    config.imgsz = 640
    config.lr0 = 0.01
    config.checkpoint_dir = "./checkpoints/yolov8n-auto"

    trainer = UltralyticsTrainer(
        config=config,
        model_name="yolov8n.pt",
        callbacks=[
            PrintProgressCallback(),
            MLflowCallback(),
        ],
    )

    results = trainer.train()
    return results


# =============================================================================
# Example 4: Custom Trainer Subclass
# =============================================================================


class CustomYOLOTrainer(UltralyticsTrainer):
    """Custom trainer with additional functionality."""

    def _setup(self):
        """Override setup for custom initialization."""
        super()._setup()
        print("🔧 Custom setup logic here")
        # Add custom dataset preparation
        # Add custom model modifications
        # etc.

    def _finalize(self):
        """Override finalize for custom export."""
        print("📦 Exporting model to ONNX...")

        # Custom export logic
        if self.model:
            try:
                self.model.export(format="onnx")
                print("✅ ONNX export complete")
            except Exception as e:
                print(f"❌ ONNX export failed: {e}")

        return super()._finalize()


def example_custom_trainer():
    """Use custom trainer subclass."""

    config = TrainingConfig(
        epochs=50,
        batch_size=16,
        device="cuda:0",
    )

    trainer = CustomYOLOTrainer(
        config=config,
        model_name="yolov8n.pt",
    )

    results = trainer.train()
    return results


# =============================================================================
# Example 5: Face Detection Training (Migration Path)
# =============================================================================


def example_face_detection():
    """
    Migrate face_detection_training.py to use new Trainer API.

    This shows the migration path:
    - Old: 4400 lines of monolithic code
    - New: ~100 lines using composable callbacks
    """

    # Configuration (same as before)
    config = TrainingConfig(
        epochs=100,
        batch_size=16,
        device="cuda:1",  # RTX 3090
        imgsz=640,
        lr0=0.01,
        optimizer="AdamW",
        checkpoint_dir="./checkpoints/face-detection",
    )

    # Create callbacks for SOTA features
    from shml_training.integrations import ProgressReporter

    class FaceDetectionCallback(TrainingCallback):
        """Face detection specific callback."""

        def __init__(self):
            self.reporter = ProgressReporter(run_id="face-det", total_epochs=100)

        def on_run_start(self, trainer, config):
            self.reporter.start_run(config=config)

        def on_epoch_end(self, trainer, epoch, metrics):
            self.reporter.log_step(epoch, **metrics)

        def on_run_end(self, trainer, metrics):
            self.reporter.end_run(metrics=metrics)

    # Train with callbacks
    trainer = UltralyticsTrainer(
        config=config,
        model_name="yolov8l.pt",  # Best accuracy for face detection
        callbacks=[
            PrintProgressCallback(),
            MLflowCallback(),
            FaceDetectionCallback(),
        ],
    )

    results = trainer.train()
    return results


# =============================================================================
# Run Examples
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SHML Training Examples")
    parser.add_argument(
        "--example",
        type=str,
        choices=["basic", "callbacks", "custom", "face"],
        default="basic",
        help="Which example to run",
    )

    args = parser.parse_args()

    if args.example == "basic":
        example_basic_training()
    elif args.example == "callbacks":
        example_training_with_callbacks()
    elif args.example == "custom":
        example_custom_trainer()
    elif args.example == "face":
        example_face_detection()
