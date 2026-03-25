"""Unit tests for libs/training — torch-free pure-Python logic.

Covers:
- shml_training/core/config.py: dataclasses, enums, MemoryOptimizationConfig levels,
  TrainingConfig defaults, from_dict/to_dict round-trip
- shml_training/techniques/trajectory_filter.py: filter_batch, get_stats
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Stub torch and CUDA dependencies, then insert training package path
# ---------------------------------------------------------------------------

_TORCH_ATTRS = [
    "cuda", "nn", "optim", "Tensor", "FloatTensor", "BoolTensor", "device",
    "tensor", "zeros", "ones", "float32", "float16", "bfloat16", "sigmoid",
    "load", "save", "no_grad", "amp",
]

def _make_torch_stub() -> MagicMock:
    t = MagicMock(name="torch")
    for attr in _TORCH_ATTRS:
        setattr(t, attr, MagicMock())
    t.cuda.is_available = MagicMock(return_value=False)
    t.cuda.device_count = MagicMock(return_value=0)
    return t


for _mod_name in [
    "torch", "torch.nn", "torch.optim", "torch.amp", "torch.cuda",
    "torch.utils", "torch.utils.data", "torch.distributed",
    "torch.nn.functional", "torch.nn.parallel",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _make_torch_stub()

# Other heavy deps that config.py or techniques may indirectly pull in
# NOTE: yaml (PyYAML) is installed — do NOT stub it; stubbing breaks mlflow's importlib.find_spec
for _dep in ["peft", "transformers", "unsloth", "accelerate", "deepspeed"]:
    if _dep not in sys.modules:
        sys.modules[_dep] = MagicMock()

_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

_training_root = os.path.join(_root, "libs", "training")
if _training_root not in sys.path:
    sys.path.insert(0, _training_root)


# ===========================================================================
# TestTrainingConfig
# ===========================================================================


class TestTrainingConfig:
    """Tests for TrainingConfig and related dataclasses."""

    def test_default_values(self):
        from shml_training.core.config import TrainingConfig, TrainingMode, OptimizationLevel

        cfg = TrainingConfig()
        assert cfg.mode == TrainingMode.LOCAL
        assert cfg.epochs == 100
        assert cfg.batch_size == 8
        assert cfg.learning_rate == 1e-4
        assert cfg.device == "auto"

    def test_custom_values(self):
        from shml_training.core.config import TrainingConfig, TrainingMode

        cfg = TrainingConfig(mode=TrainingMode.RAY, epochs=50, batch_size=16)
        assert cfg.mode == TrainingMode.RAY
        assert cfg.epochs == 50
        assert cfg.batch_size == 16

    def test_to_dict_round_trip(self):
        from shml_training.core.config import TrainingConfig, TrainingMode, TrainingConfig

        cfg = TrainingConfig(mode=TrainingMode.LOCAL, epochs=42, batch_size=4)
        d = cfg.to_dict()
        assert d["epochs"] == 42
        assert d["batch_size"] == 4

    def test_from_dict_basic(self):
        from shml_training.core.config import TrainingConfig

        data = {"epochs": 25, "batch_size": 32, "learning_rate": 3e-4}
        cfg = TrainingConfig.from_dict(data)
        assert cfg.epochs == 25
        assert cfg.batch_size == 32

    def test_training_mode_enum_values(self):
        from shml_training.core.config import TrainingMode

        assert TrainingMode.LOCAL.value == "local"
        assert TrainingMode.RAY.value == "ray"
        assert TrainingMode.FSDP.value == "fsdp"
        assert TrainingMode.DEEPSPEED.value == "deepspeed"

    def test_optimization_level_enum_values(self):
        from shml_training.core.config import OptimizationLevel

        assert OptimizationLevel.NONE.value == "none"
        assert OptimizationLevel.MAXIMUM.value == "maximum"

    def test_memory_budget_to_dict(self):
        from shml_training.core.config import MemoryBudget

        mb = MemoryBudget(
            model_memory_gb=7.0, optimizer_memory_gb=14.0, gradient_memory_gb=7.0,
            activation_memory_gb=2.0, total_required_gb=30.0,
            available_gpu_gb=24.0, available_cpu_gb=64.0,
            can_fit_on_gpu=False, requires_cpu_offload=True,
            requires_gradient_checkpointing=True,
        )
        d = mb.to_dict()
        assert d["total_required_gb"] == 30.0
        assert d["requires_cpu_offload"] is True

    def test_memory_optimization_config_conservative(self):
        from shml_training.core.config import MemoryOptimizationConfig, OptimizationLevel

        cfg = MemoryOptimizationConfig.for_level(OptimizationLevel.CONSERVATIVE)
        assert cfg.chunked_loss is True
        assert cfg.gradient_checkpointing is True
        assert cfg.tiled_mlp is False

    def test_memory_optimization_config_maximum(self):
        from shml_training.core.config import MemoryOptimizationConfig, OptimizationLevel

        cfg = MemoryOptimizationConfig.for_level(OptimizationLevel.MAXIMUM)
        assert cfg.tiled_mlp is True
        assert cfg.gradient_checkpointing is True

    def test_memory_optimization_config_none(self):
        from shml_training.core.config import MemoryOptimizationConfig, OptimizationLevel

        cfg = MemoryOptimizationConfig.for_level(OptimizationLevel.NONE)
        assert cfg.chunked_loss is False
        assert cfg.gradient_checkpointing is False

    def test_memory_optimization_config_aggressive(self):
        from shml_training.core.config import MemoryOptimizationConfig, OptimizationLevel

        cfg = MemoryOptimizationConfig.for_level(OptimizationLevel.AGGRESSIVE)
        assert cfg.chunked_loss is True
        assert cfg.gradient_checkpointing_offload_to_cpu is True
        assert cfg.cpu_offload_optimizer is True

    def test_from_dict_builds_nested_configs_and_mode(self):
        from shml_training.core.config import TrainingConfig, TrainingMode

        cfg = TrainingConfig.from_dict(
            {
                "mode": "ray",
                "epochs": 12,
                "memory": {"gradient_accumulation_steps": 3},
                "checkpoint": {"checkpoint_dir": "/tmp/ckpts", "keep_last_n": 5},
                "progress": {"enable_agui_events": False, "log_to_console": False},
            }
        )

        assert cfg.mode == TrainingMode.RAY
        assert cfg.memory.gradient_accumulation_steps == 3
        assert cfg.checkpoint.checkpoint_dir == "/tmp/ckpts"
        assert cfg.checkpoint.keep_last_n == 5
        assert cfg.progress.enable_agui_events is False
        assert cfg.progress.log_to_console is False

    def test_to_yaml_and_from_yaml_round_trip(self, tmp_path: Path):
        from shml_training.core.config import TrainingConfig, TrainingMode

        cfg = TrainingConfig(mode=TrainingMode.FSDP, epochs=7, batch_size=2)
        path = tmp_path / "training.yml"

        cfg.to_yaml(str(path))
        loaded = TrainingConfig.from_yaml(str(path))

        assert loaded.mode == TrainingMode.FSDP
        assert loaded.epochs == 7
        assert loaded.batch_size == 2

    def test_print_summary_includes_memory_budget(self, capsys):
        from shml_training.core.config import MemoryBudget, TrainingConfig

        cfg = TrainingConfig()
        cfg._memory_budget = MemoryBudget(
            model_memory_gb=1.0,
            optimizer_memory_gb=2.0,
            gradient_memory_gb=1.0,
            activation_memory_gb=0.5,
            total_required_gb=4.5,
            available_gpu_gb=8.0,
            available_cpu_gb=32.0,
            can_fit_on_gpu=True,
            requires_cpu_offload=False,
            requires_gradient_checkpointing=False,
        )

        cfg.print_summary()
        captured = capsys.readouterr()
        assert "SHML Training Configuration" in captured.out
        assert "Memory Budget:" in captured.out
        assert "Required: 4.5 GB" in captured.out

    def test_auto_configure_raises_optimization_level_for_cpu_offload(self):
        from shml_training.core.config import OptimizationLevel, TrainingConfig, TrainingMode

        memory_budget = MagicMock(
            requires_cpu_offload=True,
            can_fit_on_gpu=True,
        )
        profile = MagicMock(
            is_multi_gpu=False,
            recommended_precision="bf16",
            gpus=[object()],
            system=MagicMock(cpu_cores=10),
        )
        profile.get_memory_budget.return_value = memory_budget

        with patch("shml_training.core.hardware.HardwareDetector.detect", return_value=profile):
            cfg = TrainingConfig.auto_configure(
                optimization_level=OptimizationLevel.NONE,
                mode=TrainingMode.LOCAL,
            )

        assert cfg.memory.cpu_offload_optimizer is True
        assert cfg.memory.gradient_checkpointing_offload_to_cpu is True
        assert cfg.num_workers == 8

    def test_auto_configure_uses_fsdp_for_multi_gpu(self):
        from shml_training.core.config import OptimizationLevel, TrainingConfig, TrainingMode

        memory_budget = MagicMock(
            requires_cpu_offload=False,
            can_fit_on_gpu=True,
        )
        profile = MagicMock(
            is_multi_gpu=True,
            recommended_precision="fp16",
            gpus=[object(), object()],
            system=MagicMock(cpu_cores=6),
        )
        profile.get_memory_budget.return_value = memory_budget

        with patch("shml_training.core.hardware.HardwareDetector.detect", return_value=profile):
            cfg = TrainingConfig.auto_configure(
                optimization_level=OptimizationLevel.CONSERVATIVE,
                mode=None,
            )

        assert cfg.mode == TrainingMode.FSDP
        assert cfg.num_gpus == 2
        assert cfg.precision == "fp16"
        assert cfg.num_workers == 4

    def test_auto_configure_reduces_batch_and_adds_accumulation(self):
        from shml_training.core.config import OptimizationLevel, TrainingConfig, TrainingMode

        memory_budget = MagicMock(
            requires_cpu_offload=False,
            can_fit_on_gpu=False,
        )
        profile = MagicMock(
            is_multi_gpu=False,
            recommended_precision="bf16",
            gpus=[object()],
            system=MagicMock(cpu_cores=4),
        )
        profile.get_memory_budget.return_value = memory_budget

        with patch("shml_training.core.hardware.HardwareDetector.detect", return_value=profile):
            cfg = TrainingConfig.auto_configure(
                target_batch_size=8,
                optimization_level=OptimizationLevel.NONE,
                mode=TrainingMode.LOCAL,
            )

        assert cfg.batch_size == 2
        assert cfg.memory.gradient_accumulation_steps == 4

    def test_auto_configure_clamps_worker_count_at_zero(self):
        from shml_training.core.config import TrainingConfig, TrainingMode

        memory_budget = MagicMock(
            requires_cpu_offload=False,
            can_fit_on_gpu=True,
        )
        profile = MagicMock(
            is_multi_gpu=False,
            recommended_precision="fp32",
            gpus=[],
            system=MagicMock(cpu_cores=1),
        )
        profile.get_memory_budget.return_value = memory_budget

        with patch("shml_training.core.hardware.HardwareDetector.detect", return_value=profile):
            cfg = TrainingConfig.auto_configure(mode=TrainingMode.LOCAL)

        assert cfg.num_workers == 0


# ===========================================================================
# TestTrajectoryFilter
# ===========================================================================


class TestTrajectoryFilter:
    """Tests for TrajectorySegmentFilter — uses numpy, no torch."""

    def _make_filter(self, seg_len=4, tmin=0.5, tmax=3.0):
        from shml_training.techniques.trajectory_filter import TrajectorySegmentFilter
        return TrajectorySegmentFilter(segment_length=seg_len, threshold_min=tmin, threshold_max=tmax)

    def test_keeps_medium_advantage_segments(self):
        """Segments with |sum(advantages)| in [threshold_min, threshold_max] are kept."""
        tsf = self._make_filter(seg_len=4, tmin=0.5, tmax=3.0)
        # 4 samples, sum = 1.0*4 = 4 > tmax -> filtered_hard
        # Use value that keeps the segment: sum = 1.0
        advantages = np.array([0.25, 0.25, 0.25, 0.25])  # sum = 1.0, in [0.5, 3.0]
        indices = np.arange(4)
        kept = tsf.filter_batch(advantages, indices)
        assert len(kept) == 4

    def test_filters_easy_segments(self):
        """Segments with very low advantage sum are dropped."""
        tsf = self._make_filter(seg_len=4, tmin=0.5, tmax=3.0)
        advantages = np.array([0.01, 0.01, 0.01, 0.01])  # sum = 0.04, < tmin
        indices = np.arange(4)
        kept = tsf.filter_batch(advantages, indices)
        assert len(kept) == 0

    def test_filters_hard_segments(self):
        """Segments with very high advantage sum are dropped."""
        tsf = self._make_filter(seg_len=4, tmin=0.5, tmax=3.0)
        advantages = np.array([2.0, 2.0, 2.0, 2.0])  # sum = 8.0, > tmax
        indices = np.arange(4)
        kept = tsf.filter_batch(advantages, indices)
        assert len(kept) == 0

    def test_returns_all_when_shorter_than_segment_length(self):
        """If batch < segment_length, all indices are returned unfiltered."""
        tsf = self._make_filter(seg_len=64)
        advantages = np.array([1.0, 2.0])
        indices = np.array([10, 11])
        kept = tsf.filter_batch(advantages, indices)
        np.testing.assert_array_equal(kept, indices)

    def test_get_stats_accumulates(self):
        """get_stats reflects cumulative filter decisions."""
        tsf = self._make_filter(seg_len=4, tmin=0.5, tmax=3.0)
        # Easy batch
        tsf.filter_batch(np.zeros(4), np.arange(4))
        # Medium batch
        tsf.filter_batch(np.array([0.25, 0.25, 0.25, 0.25]), np.arange(4))
        stats = tsf.get_stats()
        assert stats["filtered_easy"] > 0
        assert stats["kept"] > 0


# ===========================================================================
# TestSDKClientMock — training SDK endpoint logic (HTTP mocked)
# ===========================================================================


class TestSDKClientMock:
    """Tests for ray_compute SDK client wrappers against mocked HTTP."""

    @pytest.fixture
    def client(self):
        try:
            from libs.client.training import TrainingClient
            return TrainingClient(base_url="http://ray-compute-api:8000", api_key="test-key")
        except ImportError:
            pytest.skip("libs.client.training not available")

    def test_submit_job_sends_post(self, client):
        with patch("httpx.Client.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 202
            mock_resp.json.return_value = {"job_id": "job-001", "status": "PENDING"}
            mock_resp.raise_for_status = MagicMock()
            mock_post.return_value = mock_resp
            result = client.submit_job({"technique": "curriculum", "epochs": 10})
        assert result["job_id"] == "job-001"

    def test_get_status_sends_get(self, client):
        with patch("httpx.Client.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"job_id": "job-001", "status": "RUNNING"}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp
            result = client.get_status("job-001")
        assert result["status"] == "RUNNING"

    def test_list_jobs_returns_list(self, client):
        with patch("httpx.Client.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"jobs": []}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp
            result = client.list_jobs()
        assert isinstance(result, (list, dict))

    def test_cancel_sends_delete(self, client):
        with patch("httpx.Client.delete") as mock_del:
            mock_resp = MagicMock()
            mock_resp.status_code = 204
            mock_resp.raise_for_status = MagicMock()
            mock_del.return_value = mock_resp
            # Should not raise
            client.cancel("job-001")

    def test_models_returns_list(self, client):
        with patch("httpx.Client.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"models": ["yolov8l", "rfdetr"]}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp
            result = client.list_models()
        assert result is not None

    def test_quota_returns_dict(self, client):
        with patch("httpx.Client.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"gpu_slots_available": 1, "max_concurrent": 3}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp
            result = client.get_quota()
        assert result is not None
