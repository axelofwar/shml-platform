from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


_ROOT = Path(__file__).resolve().parents[3]
_TRAINING_ROOT = _ROOT / "libs" / "training"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if str(_TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAINING_ROOT))


class FakeParam:
    def __init__(self, count: int, requires_grad: bool = True) -> None:
        self._count = count
        self.requires_grad = requires_grad

    def numel(self) -> int:
        return self._count


class FakeModel:
    def __init__(self) -> None:
        self.to_calls: list[object] = []
        self.state_dict = MagicMock(return_value={"model": "state"})

    def to(self, device: object) -> "FakeModel":
        self.to_calls.append(device)
        return self

    def parameters(self):
        return [FakeParam(10, True), FakeParam(5, False), FakeParam(20, True)]


class FakeLoss:
    def __init__(self) -> None:
        self.backward = MagicMock()


class FakeOptimizer:
    def __init__(self) -> None:
        self.step = MagicMock()
        self.state_dict = MagicMock(return_value={"optimizer": "state"})


class FakeDataLoader:
    def __init__(self) -> None:
        self.dataset = [1, 2, 3]
        self.batch_size = 4
        self.num_workers = 2
        self.pin_memory = True
        self.drop_last = False
        self.collate_fn = lambda batch: batch


def _make_torch_stub(*, cuda_available: bool = False, distributed_initialized: bool = False) -> ModuleType:
    module = ModuleType("torch")
    module.float16 = "float16"
    module.Tensor = object
    module.device = lambda value: value
    module.save = MagicMock()

    cuda = SimpleNamespace(
        is_available=lambda: cuda_available,
        set_device=MagicMock(),
    )
    module.cuda = cuda

    reduce_op = SimpleNamespace(SUM="sum", AVG="avg", MAX="max", MIN="min")
    distributed = SimpleNamespace(
        is_initialized=lambda: distributed_initialized,
        init_process_group=MagicMock(),
        destroy_process_group=MagicMock(),
        barrier=MagicMock(),
        all_reduce=MagicMock(),
        ReduceOp=reduce_op,
    )
    module.distributed = distributed

    module.optim = SimpleNamespace(Optimizer=object)
    return module


class TestDistributedConfig:
    def test_auto_select_prefers_none_on_single_gpu_when_model_fits(self):
        from shml_training.core.distributed import DistributedConfig, DistributedStrategy

        config = DistributedConfig.auto_select(model_params=100_000_000, available_vram_gb=8.0, num_gpus=1)

        assert config.strategy == DistributedStrategy.NONE

    def test_auto_select_uses_fsdp_cpu_offload_when_single_gpu_is_tight(self):
        from shml_training.core.distributed import DistributedConfig, DistributedStrategy

        config = DistributedConfig.auto_select(model_params=500_000_000, available_vram_gb=2.0, num_gpus=1)

        assert config.strategy == DistributedStrategy.FSDP
        assert config.fsdp_cpu_offload is True

    def test_auto_select_covers_multi_gpu_branches(self):
        from shml_training.core.distributed import DistributedConfig, DistributedStrategy

        ddp = DistributedConfig.auto_select(model_params=200_000_000, available_vram_gb=8.0, num_gpus=4)
        fsdp_shard = DistributedConfig.auto_select(model_params=800_000_000, available_vram_gb=8.0, num_gpus=4)
        fsdp_full = DistributedConfig.auto_select(model_params=1_500_000_000, available_vram_gb=8.0, num_gpus=4)
        zero3 = DistributedConfig.auto_select(model_params=3_000_000_000, available_vram_gb=8.0, num_gpus=2)

        assert ddp.strategy == DistributedStrategy.DDP
        assert fsdp_shard.strategy == DistributedStrategy.FSDP
        assert fsdp_shard.fsdp_sharding_strategy == "SHARD_GRAD_OP"
        assert fsdp_full.strategy == DistributedStrategy.FSDP
        assert fsdp_full.fsdp_sharding_strategy == "FULL_SHARD"
        assert zero3.strategy == DistributedStrategy.DEEPSPEED_ZERO3
        assert zero3.deepspeed_offload_optimizer is True
        assert zero3.deepspeed_offload_params is True


class TestDistributedEnvironment:
    def test_init_distributed_returns_standalone_info(self):
        from shml_training.core.distributed import init_distributed

        torch_stub = _make_torch_stub(cuda_available=False, distributed_initialized=False)
        with patch("shml_training.core.distributed.torch", torch_stub), patch.dict(
            "os.environ",
            {},
            clear=True,
        ):
            info = init_distributed()

        assert info == {
            "world_size": 1,
            "rank": 0,
            "local_rank": 0,
            "is_main_process": True,
            "is_distributed": False,
        }
        assert torch_stub.distributed.init_process_group.call_count == 0

    def test_init_distributed_initializes_process_group_and_sets_device(self):
        from shml_training.core.distributed import init_distributed

        torch_stub = _make_torch_stub(cuda_available=True, distributed_initialized=False)
        with patch("shml_training.core.distributed.torch", torch_stub), patch.dict(
            "os.environ",
            {"WORLD_SIZE": "2", "RANK": "1", "LOCAL_RANK": "3"},
            clear=True,
        ):
            info = init_distributed()

        assert info["is_distributed"] is True
        torch_stub.distributed.init_process_group.assert_called_once_with(backend="nccl")
        torch_stub.cuda.set_device.assert_called_once_with(3)

    def test_cleanup_distributed_destroys_process_group(self):
        from shml_training.core.distributed import cleanup_distributed

        torch_stub = _make_torch_stub(distributed_initialized=True)
        with patch("shml_training.core.distributed.torch", torch_stub):
            cleanup_distributed()

        torch_stub.distributed.destroy_process_group.assert_called_once_with()


class TestDistributedWrapper:
    def test_device_uses_cpu_when_cuda_unavailable(self):
        from shml_training.core.distributed import DistributedConfig, DistributedWrapper

        torch_stub = _make_torch_stub(cuda_available=False)
        with patch("shml_training.core.distributed.torch", torch_stub), patch(
            "shml_training.core.distributed.init_distributed",
            return_value={"rank": 0, "world_size": 1, "local_rank": 0, "is_main_process": True, "is_distributed": False},
        ):
            wrapper = DistributedWrapper(DistributedConfig())
            assert wrapper.device == "cpu"

    def test_wrap_model_dispatches_by_strategy_and_requires_optimizer_for_deepspeed(self):
        from shml_training.core.distributed import DistributedConfig, DistributedStrategy, DistributedWrapper

        torch_stub = _make_torch_stub(cuda_available=False)
        with patch("shml_training.core.distributed.torch", torch_stub), patch(
            "shml_training.core.distributed.init_distributed",
            return_value={"rank": 0, "world_size": 1, "local_rank": 0, "is_main_process": True, "is_distributed": False},
        ):
            model = FakeModel()
            none_wrapper = DistributedWrapper(DistributedConfig(strategy=DistributedStrategy.NONE))
            assert none_wrapper.wrap_model(model) is model

            ddp_wrapper = DistributedWrapper(DistributedConfig(strategy=DistributedStrategy.DDP))
            ddp_wrapper._wrap_ddp = MagicMock(return_value="ddp-model")
            assert ddp_wrapper.wrap_model(FakeModel()) == "ddp-model"

            fsdp_wrapper = DistributedWrapper(DistributedConfig(strategy=DistributedStrategy.FSDP))
            fsdp_wrapper._wrap_fsdp = MagicMock(return_value="fsdp-model")
            assert fsdp_wrapper.wrap_model(FakeModel()) == "fsdp-model"

            ds_wrapper = DistributedWrapper(DistributedConfig(strategy=DistributedStrategy.DEEPSPEED_ZERO2))
            with pytest.raises(ValueError, match="Optimizer required"):
                ds_wrapper.wrap_model(FakeModel())

    def test_wrap_ddp_omits_device_ids_on_cpu(self):
        from shml_training.core.distributed import DistributedConfig, DistributedWrapper

        torch_stub = _make_torch_stub(cuda_available=False)
        ddp_module = ModuleType("torch.nn.parallel")
        ddp_ctor = MagicMock(return_value="wrapped")
        ddp_module.DistributedDataParallel = ddp_ctor

        with patch("shml_training.core.distributed.torch", torch_stub), patch.dict(sys.modules, {"torch.nn.parallel": ddp_module}), patch(
            "shml_training.core.distributed.init_distributed",
            return_value={"rank": 0, "world_size": 2, "local_rank": 1, "is_main_process": True, "is_distributed": True},
        ):
            wrapper = DistributedWrapper(DistributedConfig())
            model = FakeModel()
            wrapped = wrapper._wrap_ddp(model)

        assert wrapped == "wrapped"
        assert ddp_ctor.call_args.kwargs["device_ids"] is None

    def test_wrap_dataloader_uses_distributed_sampler_when_needed(self):
        from shml_training.core.distributed import DistributedConfig, DistributedWrapper

        sampler_cls = MagicMock(return_value="sampler")
        dataloader_cls = MagicMock(return_value="dist-loader")
        with patch("shml_training.core.distributed.DistributedSampler", sampler_cls), patch(
            "shml_training.core.distributed.DataLoader",
            dataloader_cls,
        ), patch("shml_training.core.distributed.init_distributed", return_value={
            "rank": 1,
            "world_size": 2,
            "local_rank": 1,
            "is_main_process": False,
            "is_distributed": True,
        }):
            wrapper = DistributedWrapper(DistributedConfig())
            dataloader = FakeDataLoader()
            result = wrapper.wrap_dataloader(dataloader, shuffle=False)

        assert result == "dist-loader"
        sampler_cls.assert_called_once_with(dataloader.dataset, num_replicas=2, rank=1, shuffle=False)
        dataloader_cls.assert_called_once()

    def test_backward_and_step_delegate_correctly(self):
        from shml_training.core.distributed import DistributedConfig, DistributedWrapper

        with patch("shml_training.core.distributed.init_distributed", return_value={
            "rank": 0,
            "world_size": 1,
            "local_rank": 0,
            "is_main_process": True,
            "is_distributed": False,
        }):
            wrapper = DistributedWrapper(DistributedConfig())
            loss = FakeLoss()
            optimizer = FakeOptimizer()

            wrapper.backward(loss)
            wrapper.step(optimizer)

            wrapper._deepspeed_engine = MagicMock()
            wrapper.backward(loss)
            wrapper.step(optimizer)

        loss.backward.assert_called_once_with()
        optimizer.step.assert_called_once_with()
        wrapper._deepspeed_engine.backward.assert_called_once_with(loss)
        wrapper._deepspeed_engine.step.assert_called_once_with()

    def test_save_checkpoint_handles_standard_and_deepspeed_paths(self, tmp_path: Path):
        from shml_training.core.distributed import DistributedConfig, DistributedStrategy, DistributedWrapper

        torch_stub = _make_torch_stub(cuda_available=False)
        with patch("shml_training.core.distributed.torch", torch_stub), patch(
            "shml_training.core.distributed.init_distributed",
            return_value={"rank": 0, "world_size": 1, "local_rank": 0, "is_main_process": True, "is_distributed": False},
        ):
            wrapper = DistributedWrapper(DistributedConfig(strategy=DistributedStrategy.NONE))
            wrapper.save_checkpoint(FakeModel(), FakeOptimizer(), str(tmp_path / "model.pt"), epoch=3)

            wrapper._deepspeed_engine = MagicMock()
            wrapper.save_checkpoint(FakeModel(), FakeOptimizer(), str(tmp_path / "engine"), epoch=4)

            fsdp_wrapper = DistributedWrapper(DistributedConfig(strategy=DistributedStrategy.FSDP))
            fsdp_wrapper._save_fsdp_checkpoint = MagicMock()
            fsdp_wrapper.save_checkpoint(FakeModel(), FakeOptimizer(), str(tmp_path / "fsdp"), step=5)

        torch_stub.save.assert_called_once()
        wrapper._deepspeed_engine.save_checkpoint.assert_called_once_with(str(tmp_path / "engine"), epoch=4)
        fsdp_wrapper._save_fsdp_checkpoint.assert_called_once()

    def test_save_checkpoint_skips_non_main_process(self, tmp_path: Path):
        from shml_training.core.distributed import DistributedConfig, DistributedWrapper

        torch_stub = _make_torch_stub(cuda_available=False)
        with patch("shml_training.core.distributed.torch", torch_stub), patch(
            "shml_training.core.distributed.init_distributed",
            return_value={"rank": 1, "world_size": 2, "local_rank": 1, "is_main_process": False, "is_distributed": True},
        ):
            wrapper = DistributedWrapper(DistributedConfig())
            wrapper.save_checkpoint(FakeModel(), FakeOptimizer(), str(tmp_path / "skip.pt"))

        torch_stub.save.assert_not_called()

    def test_barrier_all_reduce_and_cleanup_delegate_to_torch(self):
        from shml_training.core.distributed import DistributedConfig, DistributedWrapper

        torch_stub = _make_torch_stub(cuda_available=False, distributed_initialized=True)
        with patch("shml_training.core.distributed.torch", torch_stub), patch(
            "shml_training.core.distributed.init_distributed",
            return_value={"rank": 0, "world_size": 2, "local_rank": 0, "is_main_process": True, "is_distributed": True},
        ), patch("shml_training.core.distributed.cleanup_distributed") as cleanup_distributed:
            wrapper = DistributedWrapper(DistributedConfig())
            tensor = object()
            assert wrapper.all_reduce(tensor, op="avg") is tensor
            wrapper.barrier()
            wrapper.cleanup()

        torch_stub.distributed.all_reduce.assert_called_once_with(tensor, op="avg")
        torch_stub.distributed.barrier.assert_called_once_with()
        cleanup_distributed.assert_called_once_with()


class TestDistributedUtilities:
    def test_build_deepspeed_config_and_param_helpers(self, capsys):
        from shml_training.core.distributed import (
            DistributedConfig,
            DistributedStrategy,
            DistributedWrapper,
            get_model_params,
            get_trainable_params,
            print_model_size,
        )

        with patch("shml_training.core.distributed.init_distributed", return_value={
            "rank": 0,
            "world_size": 1,
            "local_rank": 0,
            "is_main_process": True,
            "is_distributed": False,
        }):
            wrapper = DistributedWrapper(
                DistributedConfig(
                    strategy=DistributedStrategy.DEEPSPEED_ZERO3,
                    deepspeed_offload_optimizer=True,
                    deepspeed_offload_params=True,
                )
            )

        config = wrapper._build_deepspeed_config()
        model = FakeModel()

        assert config["zero_optimization"]["stage"] == 3
        assert config["zero_optimization"]["offload_optimizer"]["device"] == "cpu"
        assert config["zero_optimization"]["offload_param"]["pin_memory"] is True

        assert get_model_params(model) == 35
        assert get_trainable_params(model) == 30

        print_model_size(model)
        out = capsys.readouterr().out
        assert "Total: 35" in out
        assert "Trainable: 30" in out
        assert "Frozen: 5" in out
