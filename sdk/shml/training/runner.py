"""
Training Runner
================

Declarative training execution — wires integrations, manages GPU lifecycle,
and runs YOLO training with proper MLflow/Nessie/FiftyOne/Prometheus hooks.

Replaces the 850+ line train_phase8_integrated.py with a composable runner.

Usage:
    from shml.training.runner import TrainingRunner
    from shml.config import TrainingConfig

    cfg = TrainingConfig.from_yaml("config/profiles/balanced.yaml")
    runner = TrainingRunner(cfg)
    runner.run()
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

from shml.config import PlatformConfig, TrainingConfig
from shml.exceptions import SHMLError


class TrainingRunner:
    """Declarative training runner with integration lifecycle management."""

    def __init__(
        self,
        config: TrainingConfig,
        platform: PlatformConfig | None = None,
        experiment_name: str | None = None,
    ):
        self.config = config
        self.platform = platform or PlatformConfig.from_env()
        self.experiment_name = experiment_name or self._gen_experiment_name()

        # Integration clients — initialized lazily based on config.integrations
        self._mlflow = None
        self._nessie = None
        self._fiftyone = None
        self._features = None
        self._prometheus = None

        # State
        self._run_id: str | None = None
        self._branch_name: str | None = None
        self._start_time: float = 0.0

    def _gen_experiment_name(self) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_short = self.config.model.replace(".pt", "").replace("/", "-")
        return f"{model_short}_{ts}"

    # ── Integration Setup ────────────────────────────────────────────────

    def _setup_integrations(self) -> dict[str, bool]:
        """Initialize requested integrations. Returns health status."""
        results: dict[str, bool] = {}
        enabled = set(self.config.integrations)

        if "mlflow" in enabled:
            try:
                from shml.integrations.mlflow import MLflowClient

                self._mlflow = MLflowClient(self.platform)
                exp_name = self.config.mlflow_experiment or self.experiment_name
                self._run_id = self._mlflow.setup_experiment(exp_name)
                results["mlflow"] = True
                print(f"  [MLflow] Experiment: {exp_name}, run: {self._run_id}")
            except Exception as e:
                results["mlflow"] = False
                print(f"  [MLflow] FAILED: {e}")

        if "nessie" in enabled:
            try:
                from shml.integrations.nessie import NessieClient

                self._nessie = NessieClient(self.platform)
                prefix = self.config.nessie_branch_prefix or "experiment"
                self._branch_name = self._nessie.create_experiment_branch(
                    self.experiment_name, prefix=prefix
                )
                results["nessie"] = True
                print(f"  [Nessie] Branch: {self._branch_name}")
            except Exception as e:
                results["nessie"] = False
                print(f"  [Nessie] FAILED: {e}")

        if "fiftyone" in enabled:
            try:
                from shml.integrations.fiftyone import FiftyOneClient

                self._fiftyone = FiftyOneClient(self.platform)
                results["fiftyone"] = self._fiftyone.available
                if self._fiftyone.available:
                    print(f"  [FiftyOne] Available, MongoDB connected")
                else:
                    print(f"  [FiftyOne] Not installed (non-fatal)")
            except Exception as e:
                results["fiftyone"] = False
                print(f"  [FiftyOne] FAILED: {e}")

        if "features" in enabled:
            try:
                from shml.integrations.features import FeatureClient

                self._features = FeatureClient(self.platform)
                results["features"] = self._features.available
                print(
                    f"  [Features] {'Available' if self._features.available else 'Not available (non-fatal)'}"
                )
            except Exception as e:
                results["features"] = False
                print(f"  [Features] FAILED: {e}")

        if "prometheus" in enabled:
            try:
                from shml.integrations.prometheus import PrometheusReporter

                self._prometheus = PrometheusReporter(
                    self.platform,
                    job_name="training",
                    grouping_key={"experiment": self.experiment_name},
                )
                results["prometheus"] = self._prometheus.available
                print(
                    f"  [Prometheus] {'Available' if self._prometheus.available else 'Not available (non-fatal)'}"
                )
            except Exception as e:
                results["prometheus"] = False
                print(f"  [Prometheus] FAILED: {e}")

        return results

    # ── Training Execution ───────────────────────────────────────────────

    def run(self, dry_run: bool = False) -> dict[str, Any]:
        """Execute the full training pipeline.

        Returns a dict with results: metrics, run_id, branch, etc.
        """
        print(f"=" * 60)
        print(f"SHML Training Runner — {self.experiment_name}")
        print(f"=" * 60)
        print(f"Model: {self.config.model}")
        print(f"Data:  {self.config.data_yaml}")
        print(
            f"Epochs: {self.config.epochs}, Batch: {self.config.batch}, "
            f"ImgSz: {self.config.imgsz}"
        )
        print(f"Integrations: {', '.join(self.config.integrations)}")
        print()

        # Phase 1: Setup integrations
        print("Setting up integrations...")
        health = self._setup_integrations()
        print()

        if dry_run:
            print("DRY RUN — stopping before training.")
            return {
                "dry_run": True,
                "health": health,
                "config": self.config.to_ultralytics_dict(),
            }

        # Phase 2: Log parameters
        self._log_params()

        # Phase 3: Report training start
        if self._prometheus:
            self._prometheus.report_training_start(
                experiment_name=self.experiment_name,
                total_epochs=self.config.epochs,
                batch_size=self.config.batch,
                model=self.config.model,
            )

        # Phase 4: Train
        self._start_time = time.time()
        results = self._train()

        # Phase 5: Post-training
        self._post_training(results)

        return results

    def _log_params(self) -> None:
        """Log training parameters to MLflow."""
        if self._mlflow is None:
            return

        params = {
            "model": self.config.model,
            "data_yaml": self.config.data_yaml,
            "epochs": self.config.epochs,
            "batch_size": self.config.batch,
            "imgsz": self.config.imgsz,
            "optimizer": self.config.optimizer,
            "lr0": self.config.lr0,
            "lrf": self.config.lrf,
            "weight_decay": self.config.weight_decay,
            "experiment": self.experiment_name,
        }
        if self._branch_name:
            params["nessie_branch"] = self._branch_name

        self._mlflow.log_params(params)

    def _train(self) -> dict[str, Any]:
        """Execute YOLO training with Ultralytics."""
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise SHMLError(f"Ultralytics not installed: {e}")

        model = YOLO(self.config.model)
        train_args = self.config.to_ultralytics_dict()

        # Remove keys YOLO.train() doesn't accept
        for key in [
            "model",
            "integrations",
            "mlflow_experiment",
            "nessie_branch_prefix",
            "gpu_yield",
        ]:
            train_args.pop(key, None)

        # Suppress MLflow URI to avoid Ultralytics conflict
        if self._mlflow:
            self._mlflow.suppress_for_ultralytics()

        print(f"\nStarting training: {self.config.epochs} epochs...")
        epoch_times: list[float] = []

        try:
            results = model.train(**train_args)
        finally:
            if self._mlflow:
                self._mlflow.restore_after_ultralytics()

        duration = time.time() - self._start_time
        print(f"\nTraining complete in {duration/60:.1f} minutes")

        # Extract metrics
        metrics: dict[str, Any] = {}
        if hasattr(results, "results_dict"):
            metrics = dict(results.results_dict)
        elif hasattr(results, "box"):
            box = results.box
            if hasattr(box, "map50"):
                metrics["mAP50"] = float(box.map50)
            if hasattr(box, "map"):
                metrics["mAP50-95"] = float(box.map)

        metrics["duration_minutes"] = round(duration / 60, 2)
        metrics["experiment"] = self.experiment_name

        return {
            "metrics": metrics,
            "model_path": str(getattr(results, "save_dir", "")),
            "run_id": self._run_id,
            "branch": self._branch_name,
            "duration_seconds": duration,
        }

    def _post_training(self, results: dict[str, Any]) -> None:
        """Post-training: log metrics, tag, register model."""
        metrics = results.get("metrics", {})
        duration = results.get("duration_seconds", 0)

        # MLflow: log final metrics + register model
        if self._mlflow:
            try:
                self._mlflow.log_metrics(
                    {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
                )
                model_path = results.get("model_path", "")
                if model_path:
                    self._mlflow.log_artifact(model_path)

                # Register best model
                best_pt = (
                    os.path.join(model_path, "weights", "best.pt") if model_path else ""
                )
                if best_pt and os.path.exists(best_pt):
                    model_name = self.config.model.replace(".pt", "").replace("/", "-")
                    self._mlflow.register_model(
                        f"{model_name}-finetuned",
                        f"runs:/{self._run_id}/model",
                    )
                self._mlflow.end_run()
                print(f"  [MLflow] Metrics logged, run ended")
            except Exception as e:
                print(f"  [MLflow] Post-training failed: {e}")

        # Nessie: tag experiment
        if self._nessie:
            try:
                tag_name = self._nessie.tag_experiment(self.experiment_name, metrics)
                print(f"  [Nessie] Tag created: {tag_name}")
            except Exception as e:
                print(f"  [Nessie] Tagging failed: {e}")

        # Features: log final metrics
        if self._features and self._features.available:
            try:
                self._features.log_model_metrics(
                    self.experiment_name,
                    {k: v for k, v in metrics.items() if isinstance(v, (int, float))},
                    epoch=self.config.epochs,
                )
                print(f"  [Features] Final metrics logged")
            except Exception as e:
                print(f"  [Features] Failed: {e}")

        # Prometheus: report training end
        if self._prometheus:
            try:
                self._prometheus.report_training_end(
                    success=True,
                    final_metrics={
                        k: v for k, v in metrics.items() if isinstance(v, (int, float))
                    },
                )
                print(f"  [Prometheus] Training end reported")
            except Exception as e:
                print(f"  [Prometheus] Failed: {e}")

        # Summary
        print(f"\n{'=' * 60}")
        print(f"Training Summary — {self.experiment_name}")
        print(f"{'=' * 60}")
        print(f"Duration: {duration/60:.1f} minutes")
        if "mAP50" in metrics:
            print(f"mAP@50:   {metrics['mAP50']:.4f}")
        if "mAP50-95" in metrics:
            print(f"mAP@50-95: {metrics['mAP50-95']:.4f}")
        if self._run_id:
            print(f"MLflow:   {self._run_id}")
        if self._branch_name:
            print(f"Nessie:   {self._branch_name}")
        print(f"{'=' * 60}")
