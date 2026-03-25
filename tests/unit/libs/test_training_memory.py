from __future__ import annotations

import math
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


_ROOT = Path(__file__).resolve().parents[3]
_TRAINING_ROOT = _ROOT / "libs" / "training"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if str(_TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAINING_ROOT))


class FakeCount:
    def __init__(self, count: int) -> None:
        self.count = count

    def sum(self) -> "FakeCount":
        return self

    def item(self) -> int:
        return self.count


class FakeFlatTensor:
    def __init__(self, rows: list | list[list[int]], *, is_vector: bool = False, dtype: str = "float32") -> None:
        self.rows = rows
        self.is_vector = is_vector
        self.dtype = dtype
        if is_vector:
            self.shape = (len(rows),)
        else:
            width = len(rows[0]) if rows else 0
            self.shape = (len(rows), width)

    def __getitem__(self, key):
        if isinstance(key, slice):
            subset = self.rows[key]
        else:
            subset = self.rows[key]
        if self.is_vector:
            return FakeFlatTensor(list(subset), is_vector=True, dtype=self.dtype)
        return FakeFlatTensor(list(subset), is_vector=False, dtype=self.dtype)

    def __ne__(self, other: int) -> FakeCount:
        assert self.is_vector
        return FakeCount(sum(1 for value in self.rows if value != other))


class FakeTensor3D:
    def __init__(self, rows: list[list[int]], vocab_size: int, dtype: str = "float32") -> None:
        self.rows = rows
        self.dtype = dtype
        self.shape = (len(rows), 1, vocab_size)

    def contiguous(self) -> "FakeTensor3D":
        return self

    def view(self, *shape: int) -> FakeFlatTensor:
        return FakeFlatTensor(self.rows, is_vector=False, dtype=self.dtype)


class FakeTensor2D:
    def __init__(self, values: list[int]) -> None:
        self.values = values
        self.shape = (len(values), 1)

    def contiguous(self) -> "FakeTensor2D":
        return self

    def view(self, *shape: int) -> FakeFlatTensor:
        return FakeFlatTensor(self.values, is_vector=True)


class FakeModuleList:
    pass


class FakeLinear:
    pass



class TestChunkedLossWrapper:
    def test_determine_num_chunks_respects_explicit_setting(self):
        from shml_training.core.memory import ChunkedLossWrapper

        wrapper = ChunkedLossWrapper(num_chunks=4)
        logits = MagicMock(shape=(2, 3, 5), dtype="float32")

        assert wrapper._determine_num_chunks(logits) == 4

    def test_determine_num_chunks_caches_auto_value(self):
        from shml_training.core.memory import ChunkedLossWrapper

        wrapper = ChunkedLossWrapper()
        logits = MagicMock(shape=(4, 8), dtype="float32")

        with patch("shml_training.core.memory.torch.cuda.mem_get_info", return_value=(8 * 1024**3, 16 * 1024**3)) as mock_mem:
            first = wrapper._determine_num_chunks(logits)
            second = wrapper._determine_num_chunks(logits)

        assert first == second
        assert wrapper._auto_num_chunks == first
        assert mock_mem.call_count >= 1

    def test_determine_num_chunks_falls_back_on_error(self):
        from shml_training.core.memory import ChunkedLossWrapper

        wrapper = ChunkedLossWrapper()
        logits = MagicMock(shape=(2, 4), dtype="float32")

        with patch("shml_training.core.memory.torch.cuda.mem_get_info", side_effect=RuntimeError("no cuda")):
            assert wrapper._determine_num_chunks(logits) == 8

    def test_chunked_loss_aggregates_chunk_sums_into_mean(self):
        from shml_training.core.memory import ChunkedLossWrapper

        logits = FakeTensor3D([[1, 2, 3], [4, 5, 6], [7, 8, 9]], vocab_size=3)
        labels = FakeTensor2D([0, 1, -100])

        with patch(
            "shml_training.core.memory.nn.functional.cross_entropy",
            side_effect=[6.0, 0.0],
        ) as cross_entropy:
            chunked = ChunkedLossWrapper(num_chunks=2, reduction="mean")(logits, labels, shift_labels=False)

        assert chunked == 3.0
        assert cross_entropy.call_count == 2

    def test_chunked_loss_rejects_unsupported_reduction(self):
        from shml_training.core.memory import ChunkedLossWrapper

        logits = FakeTensor3D([[1, 2, 3], [4, 5, 6]], vocab_size=3)
        labels = FakeTensor2D([0, 1])

        with patch("shml_training.core.memory.nn.functional.cross_entropy", return_value=1.0), pytest.raises(
            ValueError,
            match="Unsupported reduction",
        ):
            ChunkedLossWrapper(num_chunks=2, reduction="none")(logits, labels, shift_labels=False)


class TestGradientCheckpointer:
    def test_wrap_model_uses_huggingface_hook_when_present(self):
        from shml_training.core.memory import GradientCheckpointer

        model = MagicMock()
        checkpointer = GradientCheckpointer(use_reentrant=True)

        wrapped = checkpointer.wrap_model(model)

        assert wrapped is model
        model.gradient_checkpointing_enable.assert_called_once_with(
            gradient_checkpointing_kwargs={"use_reentrant": True}
        )

    def test_wrap_sequential_replaces_checkpointable_children(self):
        from shml_training.core.memory import GradientCheckpointer

        class ToyModel:
            def __init__(self) -> None:
                self.layers = FakeModuleList()
                self.head = FakeLinear()

            def named_children(self):
                return [("layers", self.layers), ("head", self.head)]

        model = ToyModel()
        checkpoint_module = ModuleType("torch.utils.checkpoint")
        checkpoint_module.checkpoint = MagicMock(name="checkpoint")
        wrapped_layers = object()

        with patch("shml_training.core.memory.nn.ModuleList", FakeModuleList), patch(
            "shml_training.core.memory.nn.TransformerEncoderLayer",
            type("FakeEncoderLayer", (), {}),
        ), patch(
            "shml_training.core.memory.nn.TransformerDecoderLayer",
            type("FakeDecoderLayer", (), {}),
        ), patch(
            "shml_training.core.memory.CheckpointedModule",
            return_value=wrapped_layers,
        ), patch.dict(
            sys.modules,
            {
                "torch.utils": ModuleType("torch.utils"),
                "torch.utils.checkpoint": checkpoint_module,
            },
        ):
            wrapped = GradientCheckpointer(offload_to_cpu=True)._wrap_sequential(model)

        assert wrapped.layers is wrapped_layers
        assert isinstance(wrapped.head, FakeLinear)


class TestMemoryOptimizer:
    def test_from_config_and_loss_function_are_cached(self):
        from shml_training.core.config import MemoryOptimizationConfig, OptimizationLevel
        from shml_training.core.memory import MemoryOptimizer

        config = MemoryOptimizationConfig.for_level(OptimizationLevel.AGGRESSIVE)

        optimizer = MemoryOptimizer.from_config(config)
        first = optimizer.get_loss_function()
        second = optimizer.get_loss_function()

        assert optimizer.gradient_checkpointing is True
        assert optimizer.gradient_checkpointing_offload is True
        assert optimizer.cpu_offload_optimizer is True
        assert first is second

    def test_optimize_model_uses_checkpointer_when_enabled(self):
        from shml_training.core.memory import GradientCheckpointer, MemoryOptimizer

        model = object()
        optimizer = MemoryOptimizer(gradient_checkpointing=True, gradient_checkpointing_offload=True)

        with patch.object(GradientCheckpointer, "wrap_model", return_value="wrapped-model") as mock_wrap:
            result = optimizer.optimize_model(model)

        assert result == "wrapped-model"
        mock_wrap.assert_called_once_with(model)

    def test_optimize_optimizer_returns_original_optimizer(self):
        from shml_training.core.memory import MemoryOptimizer

        model = object()
        optimizer = object()

        result = MemoryOptimizer(cpu_offload_optimizer=True).optimize_optimizer(optimizer, model)

        assert result is optimizer

    def test_memory_efficient_context_cleans_up_cuda(self):
        from shml_training.core.memory import MemoryOptimizer

        optimizer = MemoryOptimizer()

        with patch("shml_training.core.memory.torch.set_grad_enabled") as set_grad_enabled, patch(
            "shml_training.core.memory.torch.backends.cuda.enable_flash_sdp",
            create=True,
        ) as enable_flash, patch(
            "shml_training.core.memory.torch.backends.cuda.enable_mem_efficient_sdp",
            create=True,
        ) as enable_mem, patch(
            "shml_training.core.memory.torch.cuda.is_available",
            return_value=True,
        ), patch("shml_training.core.memory.torch.cuda.empty_cache") as empty_cache:
            with optimizer.memory_efficient_context():
                pass

        set_grad_enabled.assert_called_once_with(True)
        enable_flash.assert_called_once_with(True)
        enable_mem.assert_called_once_with(True)
        empty_cache.assert_called_once_with()

    def test_print_memory_stats_handles_missing_cuda(self, capsys):
        from shml_training.core.memory import MemoryOptimizer

        with patch("shml_training.core.memory.torch.cuda.is_available", return_value=False):
            MemoryOptimizer().print_memory_stats()

        assert "No CUDA device available" in capsys.readouterr().out

    def test_print_memory_stats_renders_each_gpu(self, capsys):
        from shml_training.core.memory import MemoryOptimizer

        props = [
            MagicMock(total_memory=24 * 1024**3),
            MagicMock(total_memory=8 * 1024**3),
        ]

        with patch("shml_training.core.memory.torch.cuda.is_available", return_value=True), patch(
            "shml_training.core.memory.torch.cuda.device_count",
            return_value=2,
        ), patch(
            "shml_training.core.memory.torch.cuda.memory_allocated",
            side_effect=[2 * 1024**3, 1 * 1024**3],
        ), patch(
            "shml_training.core.memory.torch.cuda.memory_reserved",
            side_effect=[3 * 1024**3, 2 * 1024**3],
        ), patch(
            "shml_training.core.memory.torch.cuda.get_device_properties",
            side_effect=props,
        ):
            MemoryOptimizer().print_memory_stats()

        out = capsys.readouterr().out
        assert "GPU 0: 2.00GB allocated, 3.00GB reserved, 24.00GB total" in out
        assert "GPU 1: 1.00GB allocated, 2.00GB reserved, 8.00GB total" in out


class TestEstimateMemoryUsage:
    def test_estimate_memory_usage_counts_params_and_precision(self):
        from shml_training.core.memory import estimate_memory_usage

        class FakeParam:
            def __init__(self, count: int, requires_grad: bool = True) -> None:
                self._count = count
                self.requires_grad = requires_grad

            def numel(self) -> int:
                return self._count

        class FakeModel:
            def parameters(self):
                return [
                    FakeParam(1000, True),
                    FakeParam(500, False),
                    FakeParam(2000, True),
                ]

        usage = estimate_memory_usage(FakeModel(), batch_size=4, seq_length=128, precision="fp32")

        assert usage["num_params"] == 3500
        assert usage["trainable_params"] == 3000
        assert math.isclose(usage["model_gb"], 3500 * 4 / 1024**3)
        assert math.isclose(usage["optimizer_gb"], 3000 * 8 / 1024**3)
        assert math.isclose(usage["gradients_gb"], 3000 * 4 / 1024**3)
        assert usage["activations_gb"] > usage["model_gb"]
        assert usage["total_gb"] > usage["optimizer_gb"]
