"""
Distributed training utilities for SHML Training Library.

Supports:
- PyTorch FSDP (Fully Sharded Data Parallel)
- DeepSpeed ZeRO (Stages 1-3)
- DDP (Distributed Data Parallel)
- Multi-GPU single-node training
"""

import os
from typing import Optional, Dict, Any, List, Callable, Union
from dataclasses import dataclass, field
from enum import Enum

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, DistributedSampler


class DistributedStrategy(Enum):
    """Distributed training strategies."""

    NONE = "none"
    DDP = "ddp"
    FSDP = "fsdp"
    DEEPSPEED_ZERO1 = "deepspeed_zero1"
    DEEPSPEED_ZERO2 = "deepspeed_zero2"
    DEEPSPEED_ZERO3 = "deepspeed_zero3"


@dataclass
class DistributedConfig:
    """Configuration for distributed training."""

    strategy: DistributedStrategy = DistributedStrategy.NONE

    # DDP settings
    find_unused_parameters: bool = False
    gradient_as_bucket_view: bool = True

    # FSDP settings
    fsdp_sharding_strategy: str = "FULL_SHARD"  # FULL_SHARD, SHARD_GRAD_OP, NO_SHARD
    fsdp_cpu_offload: bool = False
    fsdp_backward_prefetch: str = "BACKWARD_PRE"  # BACKWARD_PRE, BACKWARD_POST
    fsdp_state_dict_type: str = "FULL_STATE_DICT"  # FULL_STATE_DICT, SHARDED_STATE_DICT
    fsdp_auto_wrap_policy: str = "size_based"  # size_based, transformer_based
    fsdp_min_params: int = 1_000_000  # Min params for size-based wrapping

    # DeepSpeed settings
    deepspeed_config: Optional[Dict[str, Any]] = None
    deepspeed_offload_optimizer: bool = False
    deepspeed_offload_params: bool = False

    # Multi-GPU settings
    device_ids: Optional[List[int]] = None

    @classmethod
    def auto_select(
        cls,
        model_params: int,
        available_vram_gb: float,
        num_gpus: int = 1,
    ) -> "DistributedConfig":
        """
        Auto-select distributed strategy based on model and hardware.

        Args:
            model_params: Number of model parameters
            available_vram_gb: Available VRAM per GPU
            num_gpus: Number of GPUs available

        Returns:
            Appropriate DistributedConfig
        """
        # Estimate model memory (4 bytes per param for fp32, x2 for gradients, x2 for optimizer)
        model_memory_gb = (model_params * 4 * 4) / 1e9

        if num_gpus == 1:
            # Single GPU - no distribution needed
            if model_memory_gb < available_vram_gb * 0.8:
                return cls(strategy=DistributedStrategy.NONE)
            else:
                # Model too big for single GPU - enable CPU offload
                return cls(
                    strategy=DistributedStrategy.FSDP,
                    fsdp_cpu_offload=True,
                )

        # Multi-GPU
        total_vram = available_vram_gb * num_gpus

        if model_memory_gb < available_vram_gb * 0.5:
            # Model fits easily - use DDP for simplicity
            return cls(strategy=DistributedStrategy.DDP)

        elif model_memory_gb < total_vram * 0.5:
            # Model fits with sharding - use FSDP
            return cls(
                strategy=DistributedStrategy.FSDP,
                fsdp_sharding_strategy="SHARD_GRAD_OP",
            )

        elif model_memory_gb < total_vram:
            # Tight fit - use FSDP with full sharding
            return cls(
                strategy=DistributedStrategy.FSDP,
                fsdp_sharding_strategy="FULL_SHARD",
            )

        else:
            # Need CPU offload
            return cls(
                strategy=DistributedStrategy.DEEPSPEED_ZERO3,
                deepspeed_offload_optimizer=True,
                deepspeed_offload_params=True,
            )


def init_distributed() -> Dict[str, Any]:
    """
    Initialize distributed training environment.

    Returns:
        Dict with rank, world_size, local_rank, is_main_process
    """
    # Check for distributed environment variables
    world_size = int(os.environ.get("WORLD_SIZE", 1))
    rank = int(os.environ.get("RANK", 0))
    local_rank = int(os.environ.get("LOCAL_RANK", 0))

    info = {
        "world_size": world_size,
        "rank": rank,
        "local_rank": local_rank,
        "is_main_process": rank == 0,
        "is_distributed": world_size > 1,
    }

    if world_size > 1 and not torch.distributed.is_initialized():
        # Initialize process group
        backend = "nccl" if torch.cuda.is_available() else "gloo"
        torch.distributed.init_process_group(backend=backend)

        # Set device
        if torch.cuda.is_available():
            torch.cuda.set_device(local_rank)

    return info


def cleanup_distributed() -> None:
    """Cleanup distributed training."""
    if torch.distributed.is_initialized():
        torch.distributed.destroy_process_group()


class DistributedWrapper:
    """
    Wrapper for distributed training.

    Usage:
        wrapper = DistributedWrapper(config)
        model = wrapper.wrap_model(model)
        optimizer = wrapper.wrap_optimizer(model, optimizer)
        dataloader = wrapper.wrap_dataloader(dataloader)

        for batch in dataloader:
            loss = model(batch)
            wrapper.backward(loss)
            wrapper.step(optimizer)
    """

    def __init__(self, config: DistributedConfig):
        """
        Args:
            config: Distributed training configuration
        """
        self.config = config
        self._dist_info = init_distributed()
        self._deepspeed_engine = None

    @property
    def rank(self) -> int:
        return self._dist_info["rank"]

    @property
    def world_size(self) -> int:
        return self._dist_info["world_size"]

    @property
    def is_main_process(self) -> bool:
        return self._dist_info["is_main_process"]

    @property
    def device(self) -> torch.device:
        if torch.cuda.is_available():
            return torch.device(f"cuda:{self._dist_info['local_rank']}")
        return torch.device("cpu")

    def wrap_model(
        self,
        model: nn.Module,
        optimizer: Optional[torch.optim.Optimizer] = None,
    ) -> nn.Module:
        """
        Wrap model for distributed training.

        Args:
            model: PyTorch model
            optimizer: Optimizer (required for DeepSpeed)

        Returns:
            Wrapped model
        """
        model = model.to(self.device)

        if self.config.strategy == DistributedStrategy.NONE:
            return model

        elif self.config.strategy == DistributedStrategy.DDP:
            return self._wrap_ddp(model)

        elif self.config.strategy == DistributedStrategy.FSDP:
            return self._wrap_fsdp(model)

        elif self.config.strategy.name.startswith("DEEPSPEED"):
            if optimizer is None:
                raise ValueError("Optimizer required for DeepSpeed")
            return self._wrap_deepspeed(model, optimizer)

        return model

    def _wrap_ddp(self, model: nn.Module) -> nn.Module:
        """Wrap model with DDP."""
        from torch.nn.parallel import DistributedDataParallel as DDP

        return DDP(
            model,
            device_ids=[self._dist_info["local_rank"]],
            find_unused_parameters=self.config.find_unused_parameters,
            gradient_as_bucket_view=self.config.gradient_as_bucket_view,
        )

    def _wrap_fsdp(self, model: nn.Module) -> nn.Module:
        """Wrap model with FSDP."""
        from torch.distributed.fsdp import (
            FullyShardedDataParallel as FSDP,
            ShardingStrategy,
            CPUOffload,
            BackwardPrefetch,
            MixedPrecision,
        )
        from torch.distributed.fsdp.wrap import size_based_auto_wrap_policy
        import functools

        # Sharding strategy
        sharding_map = {
            "FULL_SHARD": ShardingStrategy.FULL_SHARD,
            "SHARD_GRAD_OP": ShardingStrategy.SHARD_GRAD_OP,
            "NO_SHARD": ShardingStrategy.NO_SHARD,
        }
        sharding_strategy = sharding_map.get(
            self.config.fsdp_sharding_strategy,
            ShardingStrategy.FULL_SHARD,
        )

        # Backward prefetch
        prefetch_map = {
            "BACKWARD_PRE": BackwardPrefetch.BACKWARD_PRE,
            "BACKWARD_POST": BackwardPrefetch.BACKWARD_POST,
        }
        backward_prefetch = prefetch_map.get(
            self.config.fsdp_backward_prefetch,
            BackwardPrefetch.BACKWARD_PRE,
        )

        # CPU offload
        cpu_offload = (
            CPUOffload(offload_params=True) if self.config.fsdp_cpu_offload else None
        )

        # Auto wrap policy
        auto_wrap_policy = functools.partial(
            size_based_auto_wrap_policy,
            min_num_params=self.config.fsdp_min_params,
        )

        # Mixed precision
        mixed_precision = (
            MixedPrecision(
                param_dtype=torch.float16,
                reduce_dtype=torch.float16,
                buffer_dtype=torch.float16,
            )
            if torch.cuda.is_available()
            else None
        )

        return FSDP(
            model,
            sharding_strategy=sharding_strategy,
            cpu_offload=cpu_offload,
            backward_prefetch=backward_prefetch,
            mixed_precision=mixed_precision,
            auto_wrap_policy=auto_wrap_policy,
            device_id=self._dist_info["local_rank"],
        )

    def _wrap_deepspeed(
        self,
        model: nn.Module,
        optimizer: torch.optim.Optimizer,
    ) -> nn.Module:
        """Wrap model with DeepSpeed."""
        try:
            import deepspeed
        except ImportError:
            raise ImportError("DeepSpeed not installed. Run: pip install deepspeed")

        # Build config
        ds_config = self.config.deepspeed_config or self._build_deepspeed_config()

        # Initialize DeepSpeed
        self._deepspeed_engine, optimizer, _, _ = deepspeed.initialize(
            model=model,
            optimizer=optimizer,
            config=ds_config,
        )

        return self._deepspeed_engine

    def _build_deepspeed_config(self) -> Dict[str, Any]:
        """Build DeepSpeed config from settings."""
        stage = {
            DistributedStrategy.DEEPSPEED_ZERO1: 1,
            DistributedStrategy.DEEPSPEED_ZERO2: 2,
            DistributedStrategy.DEEPSPEED_ZERO3: 3,
        }.get(self.config.strategy, 2)

        config = {
            "train_batch_size": "auto",
            "train_micro_batch_size_per_gpu": "auto",
            "gradient_accumulation_steps": "auto",
            "fp16": {
                "enabled": True,
                "auto_cast": True,
            },
            "zero_optimization": {
                "stage": stage,
                "allgather_partitions": True,
                "allgather_bucket_size": 2e8,
                "overlap_comm": True,
                "reduce_scatter": True,
                "reduce_bucket_size": 2e8,
                "contiguous_gradients": True,
            },
        }

        # CPU offload
        if self.config.deepspeed_offload_optimizer:
            config["zero_optimization"]["offload_optimizer"] = {
                "device": "cpu",
                "pin_memory": True,
            }

        if self.config.deepspeed_offload_params:
            config["zero_optimization"]["offload_param"] = {
                "device": "cpu",
                "pin_memory": True,
            }

        return config

    def wrap_dataloader(
        self,
        dataloader: DataLoader,
        shuffle: bool = True,
    ) -> DataLoader:
        """
        Wrap dataloader for distributed training.

        Args:
            dataloader: Original DataLoader
            shuffle: Whether to shuffle (handled by sampler)

        Returns:
            Distributed DataLoader
        """
        if not self._dist_info["is_distributed"]:
            return dataloader

        # Create distributed sampler
        sampler = DistributedSampler(
            dataloader.dataset,
            num_replicas=self.world_size,
            rank=self.rank,
            shuffle=shuffle,
        )

        # Recreate dataloader with distributed sampler
        return DataLoader(
            dataloader.dataset,
            batch_size=dataloader.batch_size,
            sampler=sampler,
            num_workers=dataloader.num_workers,
            pin_memory=dataloader.pin_memory,
            drop_last=dataloader.drop_last,
            collate_fn=dataloader.collate_fn,
        )

    def backward(self, loss: torch.Tensor) -> None:
        """Backward pass."""
        if self._deepspeed_engine:
            self._deepspeed_engine.backward(loss)
        else:
            loss.backward()

    def step(self, optimizer: torch.optim.Optimizer) -> None:
        """Optimizer step."""
        if self._deepspeed_engine:
            self._deepspeed_engine.step()
        else:
            optimizer.step()

    def save_checkpoint(
        self,
        model: nn.Module,
        optimizer: torch.optim.Optimizer,
        path: str,
        **kwargs,
    ) -> None:
        """Save checkpoint (only on main process)."""
        if not self.is_main_process:
            return

        if self.config.strategy == DistributedStrategy.FSDP:
            self._save_fsdp_checkpoint(model, optimizer, path, **kwargs)
        elif self._deepspeed_engine:
            self._deepspeed_engine.save_checkpoint(path, **kwargs)
        else:
            # Standard save
            state = {
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                **kwargs,
            }
            torch.save(state, path)

    def _save_fsdp_checkpoint(
        self,
        model: nn.Module,
        optimizer: torch.optim.Optimizer,
        path: str,
        **kwargs,
    ) -> None:
        """Save FSDP checkpoint."""
        from torch.distributed.fsdp import FullStateDictConfig, StateDictType
        from torch.distributed.fsdp import FullyShardedDataParallel as FSDP

        save_policy = FullStateDictConfig(offload_to_cpu=True, rank0_only=True)

        with FSDP.state_dict_type(model, StateDictType.FULL_STATE_DICT, save_policy):
            state = {
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                **kwargs,
            }
            torch.save(state, path)

    def barrier(self) -> None:
        """Synchronization barrier."""
        if torch.distributed.is_initialized():
            torch.distributed.barrier()

    def all_reduce(
        self,
        tensor: torch.Tensor,
        op: str = "sum",
    ) -> torch.Tensor:
        """All-reduce tensor across processes."""
        if not torch.distributed.is_initialized():
            return tensor

        ops = {
            "sum": torch.distributed.ReduceOp.SUM,
            "avg": torch.distributed.ReduceOp.AVG,
            "max": torch.distributed.ReduceOp.MAX,
            "min": torch.distributed.ReduceOp.MIN,
        }

        torch.distributed.all_reduce(
            tensor, op=ops.get(op, torch.distributed.ReduceOp.SUM)
        )
        return tensor

    def cleanup(self) -> None:
        """Cleanup distributed training."""
        cleanup_distributed()


def get_model_params(model: nn.Module) -> int:
    """Get total number of model parameters."""
    return sum(p.numel() for p in model.parameters())


def get_trainable_params(model: nn.Module) -> int:
    """Get number of trainable parameters."""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def print_model_size(model: nn.Module) -> None:
    """Print model size information."""
    total = get_model_params(model)
    trainable = get_trainable_params(model)

    print(f"Model Parameters:")
    print(f"  Total: {total:,} ({total/1e6:.1f}M)")
    print(f"  Trainable: {trainable:,} ({trainable/1e6:.1f}M)")
    print(f"  Frozen: {total - trainable:,}")

    # Memory estimate
    mem_fp32 = total * 4 / 1e9  # 4 bytes per param
    mem_fp16 = total * 2 / 1e9  # 2 bytes per param
    print(f"  Memory (weights only): {mem_fp32:.2f}GB (fp32), {mem_fp16:.2f}GB (fp16)")
