from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


_TORCH_ATTRS = [
    "cuda", "nn", "optim", "Tensor", "FloatTensor", "BoolTensor", "device",
    "tensor", "zeros", "ones", "float32", "float16", "bfloat16", "sigmoid",
    "load", "save", "no_grad", "amp",
]


def _make_torch_stub() -> MagicMock:
    stub = MagicMock(name="torch")
    for attr in _TORCH_ATTRS:
        setattr(stub, attr, MagicMock())
    stub.cuda.is_available = MagicMock(return_value=False)
    stub.cuda.device_count = MagicMock(return_value=0)
    return stub


for _mod_name in [
    "torch", "torch.nn", "torch.optim", "torch.amp", "torch.cuda",
    "torch.utils", "torch.utils.data", "torch.distributed",
    "torch.nn.functional", "torch.nn.parallel", "torch.cuda.amp",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _make_torch_stub()

for _dep in ["peft", "transformers", "unsloth", "accelerate", "deepspeed", "nvidia_smi"]:
    if _dep not in sys.modules:
        sys.modules[_dep] = MagicMock()

_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _root not in sys.path:
    sys.path.insert(0, _root)
_training_root = os.path.join(_root, "libs", "training")
if _training_root not in sys.path:
    sys.path.insert(0, _training_root)

from shml_training.core.config import CheckpointConfig, TrainingConfig
from shml_training.integrations.mlflow_callback import MLflowCallback
from shml_training.integrations.prometheus_callback import PrometheusCallback


class FakeTrainer:
    def __init__(self, checkpoint_dir: str = "/tmp/model-artifacts"):
        self.run_id = "run-123"
        self.model = object()
        self.config = TrainingConfig(
            checkpoint=CheckpointConfig(checkpoint_dir=checkpoint_dir)
        )


class FakeMetricHandle:
    def __init__(self):
        self.values = []
        self._value = SimpleNamespace(set=self._set_value)

    def _set_value(self, value):
        self.values.append(value)

    def set(self, value):
        self.values.append(value)

    def inc(self, value: int = 1):
        self.values.append(("inc", value))


class FakeMetric:
    def __init__(self, *args, **kwargs):
        self.handles = []

    def labels(self, **labels):
        handle = FakeMetricHandle()
        handle.labels = labels
        self.handles.append(handle)
        return handle


class TestMLflowCallback:
    def test_init_configures_tracking_and_experiment(self):
        fake_mlflow = MagicMock()
        with patch("shml_training.integrations.mlflow_callback.mlflow", fake_mlflow):
            callback = MLflowCallback(
                tracking_uri="http://mlflow:8080",
                experiment_name="vision",
                run_name="demo",
                tags={"team": "ml"},
            )

        assert callback.tracking_uri == "http://mlflow:8080"
        fake_mlflow.set_tracking_uri.assert_called_once_with("http://mlflow:8080")
        fake_mlflow.set_experiment.assert_called_once_with("vision")

    def test_on_run_start_logs_only_scalar_params(self):
        fake_mlflow = MagicMock()
        fake_mlflow.start_run.return_value = SimpleNamespace(info=SimpleNamespace(run_id="ml-1"))
        trainer = FakeTrainer()

        with patch("shml_training.integrations.mlflow_callback.mlflow", fake_mlflow):
            callback = MLflowCallback(run_name="explicit")
            callback.on_run_start(
                trainer,
                {"epochs": 3, "precision": "bf16", "nested": {"skip": True}, "flag": True},
            )

        fake_mlflow.start_run.assert_called_once_with(run_name="explicit", tags={})
        fake_mlflow.log_params.assert_called_once_with(
            {"epochs": 3, "precision": "bf16", "flag": True}
        )
        assert callback.run.info.run_id == "ml-1"

    def test_on_epoch_and_validation_end_skip_without_run(self):
        fake_mlflow = MagicMock()
        with patch("shml_training.integrations.mlflow_callback.mlflow", fake_mlflow):
            callback = MLflowCallback()
            callback.on_epoch_end(FakeTrainer(), 1, {"loss": 0.4})
            callback.on_validation_end(FakeTrainer(), 1, {"accuracy": 0.9})

        fake_mlflow.log_metrics.assert_not_called()

    def test_on_epoch_and_validation_end_log_numeric_metrics(self):
        fake_mlflow = MagicMock()
        with patch("shml_training.integrations.mlflow_callback.mlflow", fake_mlflow):
            callback = MLflowCallback()
            callback.run = SimpleNamespace(info=SimpleNamespace(run_id="ml-2"))
            callback.on_epoch_end(FakeTrainer(), 2, {"loss": 0.4, "note": "skip"})
            callback.on_validation_end(FakeTrainer(), 2, {"accuracy": 0.9, "status": "ok"})

        assert fake_mlflow.log_metrics.call_args_list[0].args == ({"loss": 0.4},)
        assert fake_mlflow.log_metrics.call_args_list[0].kwargs == {"step": 2}
        assert fake_mlflow.log_metrics.call_args_list[1].args == ({"val_accuracy": 0.9},)
        assert fake_mlflow.log_metrics.call_args_list[1].kwargs == {"step": 2}

    def test_checkpoint_and_run_end_use_nested_checkpoint_directory(self, tmp_path: Path):
        fake_mlflow = MagicMock()
        fake_mlflow.start_run.return_value = SimpleNamespace(info=SimpleNamespace(run_id="ml-3"))
        checkpoint_dir = tmp_path / "nested-checkpoints"
        checkpoint_dir.mkdir()
        checkpoint_file = checkpoint_dir / "epoch_1.pt"
        checkpoint_file.write_text("weights")
        trainer = FakeTrainer(str(checkpoint_dir))

        with patch("shml_training.integrations.mlflow_callback.mlflow", fake_mlflow):
            callback = MLflowCallback()
            callback.run = SimpleNamespace(info=SimpleNamespace(run_id="ml-3"))
            callback.on_checkpoint_saved(trainer, str(checkpoint_file), {})
            callback.on_run_end(trainer, {"score": 0.88, "status": "done"})

        fake_mlflow.log_artifact.assert_called_once_with(str(checkpoint_file), "checkpoints")
        fake_mlflow.log_artifacts.assert_called_once_with(str(checkpoint_dir), "model")
        fake_mlflow.log_metrics.assert_called_with({"final_score": 0.88})
        fake_mlflow.end_run.assert_called_once_with()

    def test_on_error_marks_run_failed(self):
        fake_mlflow = MagicMock()
        with patch("shml_training.integrations.mlflow_callback.mlflow", fake_mlflow):
            callback = MLflowCallback()
            callback.run = SimpleNamespace(info=SimpleNamespace(run_id="ml-4"))
            callback.on_error(FakeTrainer(), RuntimeError("boom"))

        fake_mlflow.log_param.assert_called_once_with("error", "boom")
        fake_mlflow.end_run.assert_called_once_with(status="FAILED")
        assert callback.run is None


class TestPrometheusCallback:
    def test_init_raises_without_prometheus(self):
        with patch("shml_training.integrations.prometheus_callback.PROMETHEUS_AVAILABLE", False):
            with pytest.raises(ImportError, match="prometheus_client is not installed"):
                PrometheusCallback()

    def test_run_start_and_epoch_end_push_metrics(self):
        trainer = FakeTrainer()

        with patch("shml_training.integrations.prometheus_callback.PROMETHEUS_AVAILABLE", True), \
             patch("shml_training.integrations.prometheus_callback.CollectorRegistry", return_value=object(), create=True), \
             patch("shml_training.integrations.prometheus_callback.Gauge", side_effect=FakeMetric, create=True), \
             patch("shml_training.integrations.prometheus_callback.Counter", side_effect=FakeMetric, create=True), \
             patch("shml_training.integrations.prometheus_callback.push_to_gateway", create=True) as push_mock:
            callback = PrometheusCallback(push_interval=1)
            callback.on_run_start(trainer, {"model": "yolov8"})
            callback.on_epoch_end(
                trainer,
                0,
                {
                    "loss": 0.2,
                    "lr": 1e-4,
                    "mAP50": 0.9,
                    "recall": 0.91,
                    "precision": 0.89,
                    "soft_weight": 0.5,
                    "temperature": 0.7,
                    "skip_rate": 0.1,
                    "hard_batch_rate": 0.2,
                    "compute_savings": "15.2%",
                    "batches_skipped": 7,
                    "curriculum_stage": "occlusion_handling",
                },
            )

        assert callback.model_name == "yolov8"
        assert callback.metrics["epoch"].handles[-1].values == [0]
        assert callback.metrics["compute_savings"].handles[-1].values == [15.2]
        assert callback.metrics["curriculum_stage"].handles[-1].values == [3]
        assert callback.metrics["gap_to_target_map50"].handles[-1].values == [pytest.approx(0.04)]
        assert callback.metrics["gap_to_target_recall"].handles[-1].values == [pytest.approx(0.04)]
        assert callback.counters["epochs_completed"].handles[-1].values == [("inc", 1)]
        assert callback.counters["batches_skipped"].handles[-1].values == [7]
        push_mock.assert_called_once()
        assert callback.last_push_epoch == 0

    def test_epoch_end_respects_push_interval_and_handles_push_failure(self):
        trainer = FakeTrainer()

        with patch("shml_training.integrations.prometheus_callback.PROMETHEUS_AVAILABLE", True), \
             patch("shml_training.integrations.prometheus_callback.CollectorRegistry", return_value=object(), create=True), \
             patch("shml_training.integrations.prometheus_callback.Gauge", side_effect=FakeMetric, create=True), \
             patch("shml_training.integrations.prometheus_callback.Counter", side_effect=FakeMetric, create=True), \
             patch("shml_training.integrations.prometheus_callback.push_to_gateway", side_effect=RuntimeError("gateway down"), create=True) as push_mock:
            callback = PrometheusCallback(push_interval=2)
            callback.on_run_start(trainer, {})
            callback.on_epoch_end(trainer, 0, {"loss": 0.5})
            callback.on_epoch_end(trainer, 1, {"loss": 0.4})

        assert push_mock.call_count == 1
        assert callback.last_push_epoch == -1

    def test_run_end_pushes_final_metrics_and_ignores_failures(self):
        trainer = FakeTrainer()

        with patch("shml_training.integrations.prometheus_callback.PROMETHEUS_AVAILABLE", True), \
             patch("shml_training.integrations.prometheus_callback.CollectorRegistry", return_value=object(), create=True), \
             patch("shml_training.integrations.prometheus_callback.Gauge", side_effect=FakeMetric, create=True), \
             patch("shml_training.integrations.prometheus_callback.Counter", side_effect=FakeMetric, create=True), \
             patch("shml_training.integrations.prometheus_callback.push_to_gateway", side_effect=[None, RuntimeError("final fail")], create=True) as push_mock:
            callback = PrometheusCallback()
            callback.on_run_start(trainer, {"model": "detector"})
            callback.on_run_end(trainer, {"mAP50": 0.92, "recall": 0.93, "precision": 0.94})
            callback.on_run_end(trainer, {"mAP50": 0.91})

        assert callback.metrics["mAP50"].handles[0].values == [0.92]
        assert callback.metrics["recall"].handles[0].values == [0.93]
        assert callback.metrics["precision"].handles[0].values == [0.94]
        assert push_mock.call_count == 2
