"""
GPU Allocator - Tracks GPU resource allocation across training and inference.

This module provides high-level GPU allocation management, tracking which
processes are using which GPUs and coordinating transitions between
inference and training modes.
"""

import asyncio
import subprocess
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json

logger = logging.getLogger(__name__)


class GPUAllocationMode(Enum):
    """GPU allocation modes."""

    IDLE = "idle"  # No process allocated
    MPS_INFERENCE = "mps_inference"  # Shared inference via MPS
    EXCLUSIVE_INFERENCE = "exclusive_inference"  # Single inference process
    TRAINING = "training"  # Training job (exclusive)
    RESERVED = "reserved"  # Reserved for upcoming allocation


@dataclass
class GPUInfo:
    """Static GPU information."""

    index: int
    name: str
    memory_total_mb: int
    compute_capability: str
    uuid: str


@dataclass
class GPUAllocation:
    """Current GPU allocation state."""

    gpu_id: int
    mode: GPUAllocationMode
    process_name: Optional[str] = None
    process_pid: Optional[int] = None
    job_id: Optional[str] = None
    memory_used_mb: int = 0
    memory_total_mb: int = 0
    mps_enabled: bool = False
    allocated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def memory_utilization(self) -> float:
        """Memory utilization as percentage."""
        if self.memory_total_mb == 0:
            return 0.0
        return (self.memory_used_mb / self.memory_total_mb) * 100


@dataclass
class AllocationRequest:
    """Request to allocate a GPU."""

    requester: str  # "training", "inference-primary", "inference-fallback"
    gpu_preference: List[int]  # Preferred GPU IDs in order
    exclusive: bool  # Whether exclusive access is required
    memory_required_mb: int  # Minimum memory required
    priority: int = 5  # 1-10, higher = more important
    job_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class GPUAllocator:
    """
    Tracks and manages GPU allocation across training and inference.

    This class maintains the allocation state for all GPUs and coordinates
    transitions between inference and training modes.

    Hardware configuration (example):
        GPU 0: RTX 3090 Ti (24GB) - Primary inference / Training
        GPU 1: RTX 2070 (8GB)     - Fallback inference only

    Usage:
        allocator = GPUAllocator()
        await allocator.initialize()

        # Check if training can start
        if await allocator.can_allocate_training(gpu_id=0):
            await allocator.allocate_to_training(0, "pii-pro-001")

        # Release back to inference
        await allocator.release_from_training(0)
    """

    def __init__(self):
        self._gpu_info: Dict[int, GPUInfo] = {}
        self._allocations: Dict[int, GPUAllocation] = {}
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> bool:
        """Initialize GPU allocator by detecting GPUs."""
        try:
            # Query GPU information
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total,compute_cap,uuid",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                logger.error(f"nvidia-smi failed: {result.stderr}")
                return False

            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    gpu_id = int(parts[0])
                    self._gpu_info[gpu_id] = GPUInfo(
                        index=gpu_id,
                        name=parts[1],
                        memory_total_mb=int(parts[2]),
                        compute_capability=parts[3],
                        uuid=parts[4],
                    )
                    # Initialize allocation state
                    self._allocations[gpu_id] = GPUAllocation(
                        gpu_id=gpu_id,
                        mode=GPUAllocationMode.IDLE,
                        memory_total_mb=int(parts[2]),
                    )

            logger.info(f"GPUAllocator initialized with {len(self._gpu_info)} GPUs")
            for gpu_id, info in self._gpu_info.items():
                logger.info(f"  GPU {gpu_id}: {info.name} ({info.memory_total_mb}MB)")

            self._initialized = True
            return True

        except Exception as e:
            logger.error(f"Failed to initialize GPUAllocator: {e}")
            return False

    async def refresh_memory_usage(self) -> None:
        """Refresh memory usage for all GPUs."""
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 2:
                        gpu_id = int(parts[0])
                        if gpu_id in self._allocations:
                            self._allocations[gpu_id].memory_used_mb = int(parts[1])

        except Exception as e:
            logger.warning(f"Failed to refresh memory usage: {e}")

    def get_gpu_info(self, gpu_id: int) -> Optional[GPUInfo]:
        """Get static GPU information."""
        return self._gpu_info.get(gpu_id)

    def get_allocation(self, gpu_id: int) -> Optional[GPUAllocation]:
        """Get current allocation for a GPU."""
        return self._allocations.get(gpu_id)

    def get_all_allocations(self) -> Dict[int, GPUAllocation]:
        """Get all GPU allocations."""
        return dict(self._allocations)

    async def can_allocate_training(self, gpu_id: int) -> bool:
        """
        Check if a GPU can be allocated to training.

        Training requires exclusive access, so this checks:
        1. GPU exists
        2. Current mode is not already TRAINING
        3. MPS can be stopped (or is already stopped)
        """
        if gpu_id not in self._allocations:
            return False

        alloc = self._allocations[gpu_id]

        # Can't allocate if already training
        if alloc.mode == GPUAllocationMode.TRAINING:
            return False

        # Can allocate from IDLE or inference modes
        return alloc.mode in (
            GPUAllocationMode.IDLE,
            GPUAllocationMode.MPS_INFERENCE,
            GPUAllocationMode.EXCLUSIVE_INFERENCE,
        )

    async def allocate_to_training(
        self,
        gpu_id: int,
        job_id: str,
        process_name: str = "ray-training",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Allocate GPU to training (exclusive access).

        This should be called AFTER:
        1. Inference model has yielded/unloaded
        2. MPS has been stopped

        Args:
            gpu_id: GPU to allocate
            job_id: Training job identifier
            process_name: Name of the training process
            metadata: Additional metadata

        Returns:
            True if allocation successful
        """
        async with self._lock:
            if not await self.can_allocate_training(gpu_id):
                logger.error(f"Cannot allocate GPU {gpu_id} to training")
                return False

            self._allocations[gpu_id] = GPUAllocation(
                gpu_id=gpu_id,
                mode=GPUAllocationMode.TRAINING,
                process_name=process_name,
                job_id=job_id,
                memory_total_mb=self._gpu_info[gpu_id].memory_total_mb,
                mps_enabled=False,
                metadata=metadata or {},
            )

            logger.info(f"GPU {gpu_id} allocated to training job {job_id}")
            return True

    async def release_from_training(self, gpu_id: int) -> bool:
        """
        Release GPU from training back to available pool.

        This should be called when:
        1. Training job completes
        2. Training job is paused for inference

        Args:
            gpu_id: GPU to release

        Returns:
            True if release successful
        """
        async with self._lock:
            if gpu_id not in self._allocations:
                return False

            alloc = self._allocations[gpu_id]

            if alloc.mode != GPUAllocationMode.TRAINING:
                logger.warning(
                    f"GPU {gpu_id} not in training mode, current: {alloc.mode}"
                )
                return False

            self._allocations[gpu_id] = GPUAllocation(
                gpu_id=gpu_id,
                mode=GPUAllocationMode.IDLE,
                memory_total_mb=self._gpu_info[gpu_id].memory_total_mb,
                mps_enabled=False,
            )

            logger.info(f"GPU {gpu_id} released from training")
            return True

    async def allocate_to_inference(
        self,
        gpu_id: int,
        process_name: str,
        process_pid: Optional[int] = None,
        mps_enabled: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Allocate GPU to inference.

        Args:
            gpu_id: GPU to allocate
            process_name: Name of inference process (e.g., "vllm-primary")
            process_pid: PID of the process
            mps_enabled: Whether MPS is enabled
            metadata: Additional metadata

        Returns:
            True if allocation successful
        """
        async with self._lock:
            if gpu_id not in self._allocations:
                return False

            alloc = self._allocations[gpu_id]

            # Can't allocate if in training mode
            if alloc.mode == GPUAllocationMode.TRAINING:
                logger.error(
                    f"GPU {gpu_id} is in training mode, cannot allocate to inference"
                )
                return False

            mode = (
                GPUAllocationMode.MPS_INFERENCE
                if mps_enabled
                else GPUAllocationMode.EXCLUSIVE_INFERENCE
            )

            self._allocations[gpu_id] = GPUAllocation(
                gpu_id=gpu_id,
                mode=mode,
                process_name=process_name,
                process_pid=process_pid,
                memory_total_mb=self._gpu_info[gpu_id].memory_total_mb,
                mps_enabled=mps_enabled,
                metadata=metadata or {},
            )

            logger.info(f"GPU {gpu_id} allocated to inference ({process_name})")
            return True

    async def release_from_inference(self, gpu_id: int) -> bool:
        """Release GPU from inference."""
        async with self._lock:
            if gpu_id not in self._allocations:
                return False

            alloc = self._allocations[gpu_id]

            if alloc.mode not in (
                GPUAllocationMode.MPS_INFERENCE,
                GPUAllocationMode.EXCLUSIVE_INFERENCE,
            ):
                logger.warning(
                    f"GPU {gpu_id} not in inference mode, current: {alloc.mode}"
                )
                return False

            self._allocations[gpu_id] = GPUAllocation(
                gpu_id=gpu_id,
                mode=GPUAllocationMode.IDLE,
                memory_total_mb=self._gpu_info[gpu_id].memory_total_mb,
                mps_enabled=False,
            )

            logger.info(f"GPU {gpu_id} released from inference")
            return True

    async def find_available_gpu(self, request: AllocationRequest) -> Optional[int]:
        """
        Find a GPU that can satisfy the allocation request.

        Args:
            request: Allocation request with requirements

        Returns:
            GPU ID if found, None otherwise
        """
        await self.refresh_memory_usage()

        # Check preferred GPUs first
        for gpu_id in request.gpu_preference:
            if gpu_id in self._allocations:
                alloc = self._allocations[gpu_id]
                info = self._gpu_info[gpu_id]

                # Check if available
                if request.exclusive:
                    if alloc.mode not in (
                        GPUAllocationMode.IDLE,
                        GPUAllocationMode.MPS_INFERENCE,
                    ):
                        continue
                else:
                    if alloc.mode == GPUAllocationMode.TRAINING:
                        continue

                # Check memory
                available_memory = info.memory_total_mb - alloc.memory_used_mb
                if available_memory >= request.memory_required_mb:
                    return gpu_id

        # Check all GPUs if preferred not available
        for gpu_id, alloc in self._allocations.items():
            if gpu_id in request.gpu_preference:
                continue  # Already checked

            info = self._gpu_info[gpu_id]

            if request.exclusive:
                if alloc.mode not in (
                    GPUAllocationMode.IDLE,
                    GPUAllocationMode.MPS_INFERENCE,
                ):
                    continue
            else:
                if alloc.mode == GPUAllocationMode.TRAINING:
                    continue

            available_memory = info.memory_total_mb - alloc.memory_used_mb
            if available_memory >= request.memory_required_mb:
                return gpu_id

        return None

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive allocator status."""
        return {
            "initialized": self._initialized,
            "gpu_count": len(self._gpu_info),
            "gpus": {
                gpu_id: {
                    "info": {
                        "name": info.name,
                        "memory_total_mb": info.memory_total_mb,
                        "compute_capability": info.compute_capability,
                    },
                    "allocation": {
                        "mode": self._allocations[gpu_id].mode.value,
                        "process_name": self._allocations[gpu_id].process_name,
                        "job_id": self._allocations[gpu_id].job_id,
                        "memory_used_mb": self._allocations[gpu_id].memory_used_mb,
                        "memory_utilization": f"{self._allocations[gpu_id].memory_utilization:.1f}%",
                        "mps_enabled": self._allocations[gpu_id].mps_enabled,
                        "allocated_at": self._allocations[
                            gpu_id
                        ].allocated_at.isoformat(),
                    },
                }
                for gpu_id, info in self._gpu_info.items()
            },
        }

    def to_json(self) -> str:
        """Serialize status to JSON."""
        return json.dumps(self.get_status(), indent=2)
