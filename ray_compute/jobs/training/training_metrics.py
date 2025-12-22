"""
Training Metrics Module - Push metrics to Prometheus Pushgateway

This module provides real-time training observability by pushing metrics
to Prometheus Pushgateway, which are then scraped by global-prometheus
and visualized in Grafana.

Usage:
    from training_metrics import TrainingMetrics

    metrics = TrainingMetrics(
        job_name="face_detection_training",
        run_id="face-det-20251208-123456",
        pushgateway_url="http://shml-pushgateway:9091"
    )

    # Push metrics after each epoch
    metrics.push_epoch_metrics(
        epoch=1,
        mAP50=0.85,
        recall=0.92,
        precision=0.88,
        loss=0.45,
        lr=0.001
    )

    # Push curriculum stage info
    metrics.push_curriculum_stage(
        stage_name="occlusion_handling",
        stage_number=3,
        epochs_in_stage=5
    )

    # Push final metrics
    metrics.push_final_metrics(
        mAP50=0.94,
        recall=0.96,
        precision=0.91,
        training_hours=4.5
    )

Metrics exposed:
    - face_detection_mAP50 (gauge): Current mAP@0.5 IoU
    - face_detection_recall (gauge): Current recall
    - face_detection_precision (gauge): Current precision
    - face_detection_loss (gauge): Training loss
    - face_detection_lr (gauge): Learning rate
    - face_detection_epoch (gauge): Current epoch number
    - face_detection_curriculum_stage (info): Current curriculum stage
    - face_detection_advantage_filter_skip_rate (gauge): % of batches skipped
    - face_detection_training_duration_seconds (gauge): Training time
    - face_detection_gpu_memory_used_bytes (gauge): GPU memory usage
"""

import os
import time
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import urllib.request
import urllib.error
import json


@dataclass
class TrainingMetrics:
    """
    Push training metrics to Prometheus Pushgateway.

    Designed to work within Ray jobs where the pushgateway is accessible
    via the Docker network (shml-pushgateway:9091) or externally via
    Traefik (/pushgateway).
    """

    job_name: str
    run_id: str
    pushgateway_url: str = "http://shml-pushgateway:9091"

    # Internal state
    _start_time: float = field(default_factory=time.time)
    _last_push_time: float = 0
    _push_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # Labels that identify this training run
    _labels: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize labels and test connection."""
        self._labels = {
            "job": self.job_name,
            "run_id": self.run_id,
            "model": "yolov8l",  # Can be overridden
            "dataset": "wider_face",  # Can be overridden
        }
        self._start_time = time.time()

        # Test pushgateway connectivity
        self._test_connection()

    def set_model_info(self, model: str, dataset: str):
        """Set model and dataset labels."""
        self._labels["model"] = model
        self._labels["dataset"] = dataset

    def _test_connection(self) -> bool:
        """Test pushgateway connectivity."""
        try:
            req = urllib.request.Request(
                f"{self.pushgateway_url}/-/healthy", method="GET"
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    print(
                        f"  ✓ Connected to Prometheus Pushgateway at {self.pushgateway_url}"
                    )
                    return True
        except Exception as e:
            print(f"  ⚠ Pushgateway not available ({e}), metrics will not be pushed")
            print(f"    URL: {self.pushgateway_url}")
            print(f"    Ensure pushgateway service is running")
        return False

    def _format_labels(self, extra_labels: Optional[Dict[str, str]] = None) -> str:
        """Format labels for Prometheus text format."""
        labels = {**self._labels}
        if extra_labels:
            labels.update(extra_labels)

        label_pairs = [f'{k}="{v}"' for k, v in labels.items()]
        return "{" + ",".join(label_pairs) + "}"

    def _push_metrics(
        self, metrics_text: str, grouping_key: Optional[Dict[str, str]] = None
    ):
        """Push metrics to pushgateway."""
        with self._lock:
            try:
                # Build URL with grouping key
                url = f"{self.pushgateway_url}/metrics/job/{self.job_name}"
                if grouping_key:
                    for key, value in grouping_key.items():
                        url += f"/{key}/{value}"
                else:
                    url += f"/run_id/{self.run_id}"

                # Push metrics
                data = metrics_text.encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    method="POST",
                    headers={"Content-Type": "text/plain"},
                )

                with urllib.request.urlopen(req, timeout=10) as response:
                    if response.status in (200, 202):
                        self._push_count += 1
                        self._last_push_time = time.time()
                        return True
            except Exception as e:
                # Don't spam logs, just silently fail
                if self._push_count == 0:
                    print(f"  ⚠ Failed to push metrics: {e}")
                return False
        return False

    def push_epoch_metrics(
        self,
        epoch: int,
        mAP50: float,
        recall: float,
        precision: float,
        loss: float = 0.0,
        lr: float = 0.0,
        box_loss: float = 0.0,
        cls_loss: float = 0.0,
        dfl_loss: float = 0.0,
        skip_rate: float = 0.0,
        gpu_memory_mb: float = 0.0,
        extra_labels: Optional[Dict[str, str]] = None,
    ):
        """
        Push epoch-level training metrics.

        Args:
            epoch: Current epoch number
            mAP50: Mean Average Precision at IoU 0.5
            recall: Detection recall
            precision: Detection precision
            loss: Total training loss
            lr: Current learning rate
            box_loss: Bounding box regression loss
            cls_loss: Classification loss
            dfl_loss: Distribution focal loss
            skip_rate: OnlineAdvantageFilter skip rate (0-1)
            gpu_memory_mb: GPU memory usage in MB
            extra_labels: Additional labels for this push
        """
        labels = self._format_labels(extra_labels)

        training_duration = time.time() - self._start_time

        metrics = f"""# HELP face_detection_mAP50 Mean Average Precision at IoU 0.5
# TYPE face_detection_mAP50 gauge
face_detection_mAP50{labels} {mAP50}

# HELP face_detection_recall Detection recall
# TYPE face_detection_recall gauge
face_detection_recall{labels} {recall}

# HELP face_detection_precision Detection precision
# TYPE face_detection_precision gauge
face_detection_precision{labels} {precision}

# HELP face_detection_loss Training loss
# TYPE face_detection_loss gauge
face_detection_loss{labels} {loss}

# HELP face_detection_lr Learning rate
# TYPE face_detection_lr gauge
face_detection_lr{labels} {lr}

# HELP face_detection_epoch Current epoch number
# TYPE face_detection_epoch gauge
face_detection_epoch{labels} {epoch}

# HELP face_detection_box_loss Bounding box regression loss
# TYPE face_detection_box_loss gauge
face_detection_box_loss{labels} {box_loss}

# HELP face_detection_cls_loss Classification loss
# TYPE face_detection_cls_loss gauge
face_detection_cls_loss{labels} {cls_loss}

# HELP face_detection_dfl_loss Distribution focal loss
# TYPE face_detection_dfl_loss gauge
face_detection_dfl_loss{labels} {dfl_loss}

# HELP face_detection_advantage_filter_skip_rate Batch skip rate from OnlineAdvantageFilter
# TYPE face_detection_advantage_filter_skip_rate gauge
face_detection_advantage_filter_skip_rate{labels} {skip_rate}

# HELP face_detection_training_duration_seconds Total training duration
# TYPE face_detection_training_duration_seconds gauge
face_detection_training_duration_seconds{labels} {training_duration}

# HELP face_detection_gpu_memory_used_mb GPU memory used in MB
# TYPE face_detection_gpu_memory_used_mb gauge
face_detection_gpu_memory_used_mb{labels} {gpu_memory_mb}
"""

        self._push_metrics(metrics)

    def push_curriculum_stage(
        self,
        stage_name: str,
        stage_number: int,
        epochs_in_stage: int = 0,
        best_mAP50: float = 0.0,
        best_recall: float = 0.0,
        extra_labels: Optional[Dict[str, str]] = None,
    ):
        """
        Push curriculum learning stage information.

        Args:
            stage_name: Name of current stage (e.g., "presence_detection")
            stage_number: Stage number (1-4)
            epochs_in_stage: Epochs completed in current stage
            best_mAP50: Best mAP50 achieved in this stage
            best_recall: Best recall achieved in this stage
        """
        stage_labels = {**(extra_labels or {}), "stage_name": stage_name}
        labels = self._format_labels(stage_labels)

        metrics = f"""# HELP face_detection_curriculum_stage Current curriculum stage number
# TYPE face_detection_curriculum_stage gauge
face_detection_curriculum_stage{labels} {stage_number}

# HELP face_detection_curriculum_epochs_in_stage Epochs completed in current stage
# TYPE face_detection_curriculum_epochs_in_stage gauge
face_detection_curriculum_epochs_in_stage{labels} {epochs_in_stage}

# HELP face_detection_curriculum_best_mAP50 Best mAP50 in current stage
# TYPE face_detection_curriculum_best_mAP50 gauge
face_detection_curriculum_best_mAP50{labels} {best_mAP50}

# HELP face_detection_curriculum_best_recall Best recall in current stage
# TYPE face_detection_curriculum_best_recall gauge
face_detection_curriculum_best_recall{labels} {best_recall}
"""

        self._push_metrics(metrics)

    def push_multiscale_phase(
        self,
        phase_name: str,
        phase_number: int,
        imgsz: int,
        epochs_in_phase: int = 0,
        mAP50: float = 0.0,
        extra_labels: Optional[Dict[str, str]] = None,
    ):
        """
        Push multi-scale training phase information.

        Args:
            phase_name: Name of phase (e.g., "640px", "960px", "1280px")
            phase_number: Phase number (1-3)
            imgsz: Image size for this phase
            epochs_in_phase: Epochs completed in current phase
            mAP50: Current mAP50 in this phase
        """
        phase_labels = {
            **(extra_labels or {}),
            "phase_name": phase_name,
            "imgsz": str(imgsz),
        }
        labels = self._format_labels(phase_labels)

        metrics = f"""# HELP face_detection_multiscale_phase Current multi-scale phase number
# TYPE face_detection_multiscale_phase gauge
face_detection_multiscale_phase{labels} {phase_number}

# HELP face_detection_multiscale_epochs_in_phase Epochs in current phase
# TYPE face_detection_multiscale_epochs_in_phase gauge
face_detection_multiscale_epochs_in_phase{labels} {epochs_in_phase}

# HELP face_detection_multiscale_imgsz Image size for current phase
# TYPE face_detection_multiscale_imgsz gauge
face_detection_multiscale_imgsz{labels} {imgsz}

# HELP face_detection_multiscale_mAP50 mAP50 in current phase
# TYPE face_detection_multiscale_mAP50 gauge
face_detection_multiscale_mAP50{labels} {mAP50}
"""

        self._push_metrics(metrics)

    def push_final_metrics(
        self,
        mAP50: float,
        mAP50_95: float = 0.0,
        recall: float = 0.0,
        precision: float = 0.0,
        training_hours: float = 0.0,
        total_epochs: int = 0,
        status: str = "completed",
        extra_labels: Optional[Dict[str, str]] = None,
    ):
        """
        Push final training metrics when training completes.

        Args:
            mAP50: Final mAP@0.5
            mAP50_95: Final mAP@0.5:0.95
            recall: Final recall
            precision: Final precision
            training_hours: Total training time in hours
            total_epochs: Total epochs trained
            status: Training status (completed, failed, cancelled)
        """
        status_labels = {**(extra_labels or {}), "status": status}
        labels = self._format_labels(status_labels)

        metrics = f"""# HELP face_detection_final_mAP50 Final mAP@0.5
# TYPE face_detection_final_mAP50 gauge
face_detection_final_mAP50{labels} {mAP50}

# HELP face_detection_final_mAP50_95 Final mAP@0.5:0.95
# TYPE face_detection_final_mAP50_95 gauge
face_detection_final_mAP50_95{labels} {mAP50_95}

# HELP face_detection_final_recall Final recall
# TYPE face_detection_final_recall gauge
face_detection_final_recall{labels} {recall}

# HELP face_detection_final_precision Final precision
# TYPE face_detection_final_precision gauge
face_detection_final_precision{labels} {precision}

# HELP face_detection_training_hours Total training time in hours
# TYPE face_detection_training_hours gauge
face_detection_training_hours{labels} {training_hours}

# HELP face_detection_total_epochs Total epochs trained
# TYPE face_detection_total_epochs gauge
face_detection_total_epochs{labels} {total_epochs}

# HELP face_detection_training_complete Training completion flag (1=complete)
# TYPE face_detection_training_complete gauge
face_detection_training_complete{labels} 1
"""

        self._push_metrics(metrics)
        print(
            f"  ✓ Pushed final metrics to Prometheus (mAP50={mAP50:.4f}, recall={recall:.4f})"
        )

    def push_failure(
        self,
        error_type: str,
        error_message: str,
        epoch: int = 0,
        extra_labels: Optional[Dict[str, str]] = None,
    ):
        """
        Push failure information when training fails.

        Args:
            error_type: Type of error (e.g., "OOM", "CUDA", "DataLoader")
            error_message: Error message (truncated to 100 chars)
            epoch: Epoch at which failure occurred
        """
        error_labels = {
            **(extra_labels or {}),
            "error_type": error_type,
            "error_message": error_message[:100].replace('"', "'"),
        }
        labels = self._format_labels(error_labels)

        training_duration = time.time() - self._start_time

        metrics = f"""# HELP face_detection_training_failed Training failure flag
# TYPE face_detection_training_failed gauge
face_detection_training_failed{labels} 1

# HELP face_detection_failure_epoch Epoch at which training failed
# TYPE face_detection_failure_epoch gauge
face_detection_failure_epoch{labels} {epoch}

# HELP face_detection_training_duration_at_failure Training duration at failure
# TYPE face_detection_training_duration_at_failure gauge
face_detection_training_duration_at_failure{labels} {training_duration}
"""

        self._push_metrics(metrics)
        print(f"  ⚠ Pushed failure metrics (type={error_type}, epoch={epoch})")

    def delete_metrics(self):
        """Delete all metrics for this run from pushgateway."""
        try:
            url = f"{self.pushgateway_url}/metrics/job/{self.job_name}/run_id/{self.run_id}"
            req = urllib.request.Request(url, method="DELETE")
            with urllib.request.urlopen(req, timeout=10):
                print(f"  ✓ Deleted metrics for run {self.run_id}")
        except Exception as e:
            print(f"  ⚠ Failed to delete metrics: {e}")


# =============================================================================
# Convenience function for quick setup
# =============================================================================


def setup_training_metrics(
    run_id: str,
    job_name: str = "face_detection_training",
    pushgateway_url: Optional[str] = None,
) -> TrainingMetrics:
    """
    Create TrainingMetrics instance with auto-detected pushgateway URL.

    Tries in order:
    1. Provided pushgateway_url
    2. PUSHGATEWAY_URL environment variable
    3. Docker network default: http://shml-pushgateway:9091
    4. Local fallback: http://localhost:9091
    """
    if pushgateway_url is None:
        pushgateway_url = os.environ.get(
            "PUSHGATEWAY_URL", "http://shml-pushgateway:9091"
        )

    return TrainingMetrics(
        job_name=job_name, run_id=run_id, pushgateway_url=pushgateway_url
    )


# =============================================================================
# Example usage (for testing)
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test training metrics push")
    parser.add_argument("--pushgateway", default="http://localhost:9091")
    parser.add_argument("--job-name", default="test_training")
    parser.add_argument(
        "--run-id", default=f"test-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    args = parser.parse_args()

    print(f"Testing TrainingMetrics push to {args.pushgateway}")

    metrics = TrainingMetrics(
        job_name=args.job_name, run_id=args.run_id, pushgateway_url=args.pushgateway
    )

    # Simulate training epochs
    for epoch in range(1, 6):
        mAP50 = 0.5 + epoch * 0.08
        recall = 0.6 + epoch * 0.07
        precision = 0.55 + epoch * 0.08

        print(
            f"Epoch {epoch}: mAP50={mAP50:.3f}, recall={recall:.3f}, precision={precision:.3f}"
        )

        metrics.push_epoch_metrics(
            epoch=epoch,
            mAP50=mAP50,
            recall=recall,
            precision=precision,
            loss=1.0 - epoch * 0.1,
            lr=0.01 * (0.9**epoch),
        )

        time.sleep(0.5)

    # Push final metrics
    metrics.push_final_metrics(
        mAP50=0.90, recall=0.95, precision=0.87, training_hours=0.01, total_epochs=5
    )

    print("\n✓ Test complete. Check Prometheus/Grafana for metrics.")
