"""
Hardware detection and GPU information for SHML Training Library.

Provides hardware-aware configuration for optimal training performance.
"""

import os
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum


class GPUTier(Enum):
    """GPU capability tiers for resource allocation."""

    CONSUMER = "consumer"  # GTX series, older RTX
    PROSUMER = "prosumer"  # RTX 3090, 4090
    DATACENTER = "datacenter"  # A100, H100, etc.


@dataclass
class GPUInfo:
    """Information about a single GPU."""

    index: int
    name: str
    memory_gb: float
    compute_capability: Tuple[int, int]
    is_available: bool = True
    current_memory_used_gb: float = 0.0
    mps_enabled: bool = False
    mps_memory_limit_gb: Optional[float] = None

    @property
    def available_memory_gb(self) -> float:
        """Get available VRAM after current usage."""
        return self.memory_gb - self.current_memory_used_gb

    @property
    def tier(self) -> GPUTier:
        """Determine GPU tier based on name and memory."""
        name_lower = self.name.lower()
        if any(x in name_lower for x in ["a100", "h100", "v100", "a6000", "a40"]):
            return GPUTier.DATACENTER
        elif any(x in name_lower for x in ["3090", "4090", "titan", "a5000"]):
            return GPUTier.PROSUMER
        else:
            return GPUTier.CONSUMER

    @property
    def supports_bf16(self) -> bool:
        """Check if GPU supports bfloat16."""
        # Ampere (8.x) and newer support bf16
        return self.compute_capability[0] >= 8

    @property
    def supports_fp8(self) -> bool:
        """Check if GPU supports FP8 (Hopper+)."""
        return self.compute_capability[0] >= 9


@dataclass
class SystemInfo:
    """System-wide hardware information."""

    cpu_cores: int
    ram_gb: float
    available_ram_gb: float
    swap_gb: float
    has_nvme: bool = False
    nvme_speed_gbps: float = 0.0


@dataclass
class HardwareProfile:
    """Complete hardware profile for training configuration."""

    gpus: List[GPUInfo]
    system: SystemInfo

    # Computed properties
    total_vram_gb: float = field(init=False)
    effective_vram_gb: float = field(init=False)  # With CPU offload potential
    is_multi_gpu: bool = field(init=False)
    is_heterogeneous: bool = field(init=False)

    def __post_init__(self):
        self.total_vram_gb = sum(gpu.memory_gb for gpu in self.gpus)
        # Effective VRAM includes CPU offload potential (50% of available RAM)
        cpu_offload_potential = min(self.system.available_ram_gb * 0.5, 64)
        self.effective_vram_gb = self.total_vram_gb + cpu_offload_potential
        self.is_multi_gpu = len(self.gpus) > 1
        # Heterogeneous if GPU memory differs by >20%
        if self.is_multi_gpu:
            memories = [gpu.memory_gb for gpu in self.gpus]
            self.is_heterogeneous = (max(memories) - min(memories)) / max(
                memories
            ) > 0.2
        else:
            self.is_heterogeneous = False

    @property
    def primary_gpu(self) -> Optional[GPUInfo]:
        """Get the primary (largest) GPU."""
        if not self.gpus:
            return None
        return max(self.gpus, key=lambda g: g.memory_gb)

    @property
    def recommended_precision(self) -> str:
        """Get recommended training precision."""
        if self.gpus and self.gpus[0].supports_bf16:
            return "bf16"
        return "fp16"

    def get_memory_budget(self, model_size_billions: float) -> "MemoryBudget":
        """Calculate memory budget for a given model size."""
        from .config import MemoryBudget

        # Rough estimates for transformer models
        # Model weights: ~2 bytes per param (fp16/bf16)
        # Optimizer states: ~8 bytes per param (AdamW)
        # Gradients: ~2 bytes per param
        # Activations: variable, ~2-4x model size for batch=1

        model_memory_gb = model_size_billions * 2  # fp16 weights
        optimizer_memory_gb = model_size_billions * 8  # AdamW states
        gradient_memory_gb = model_size_billions * 2

        base_memory = model_memory_gb + optimizer_memory_gb + gradient_memory_gb

        return MemoryBudget(
            model_memory_gb=model_memory_gb,
            optimizer_memory_gb=optimizer_memory_gb,
            gradient_memory_gb=gradient_memory_gb,
            activation_memory_gb=model_memory_gb * 2,  # Conservative estimate
            total_required_gb=base_memory * 1.2,  # 20% overhead
            available_gpu_gb=self.total_vram_gb,
            available_cpu_gb=self.system.available_ram_gb,
            can_fit_on_gpu=base_memory * 1.2 <= self.total_vram_gb,
            requires_cpu_offload=base_memory * 1.2 > self.total_vram_gb,
            requires_gradient_checkpointing=model_size_billions > 7,
        )


class HardwareDetector:
    """Detect and profile system hardware."""

    _cached_profile: Optional[HardwareProfile] = None

    @classmethod
    def detect(cls, force_refresh: bool = False) -> HardwareProfile:
        """Detect hardware and return profile.

        Args:
            force_refresh: Force re-detection even if cached

        Returns:
            HardwareProfile with detected hardware info
        """
        if cls._cached_profile is not None and not force_refresh:
            return cls._cached_profile

        gpus = cls._detect_gpus()
        system = cls._detect_system()

        cls._cached_profile = HardwareProfile(gpus=gpus, system=system)
        return cls._cached_profile

    @classmethod
    def _detect_gpus(cls) -> List[GPUInfo]:
        """Detect NVIDIA GPUs."""
        gpus = []

        try:
            import torch

            if not torch.cuda.is_available():
                return gpus

            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)

                # Get current memory usage
                try:
                    free_mem, total_mem = torch.cuda.mem_get_info(i)
                    used_gb = (total_mem - free_mem) / 1024**3
                except Exception:
                    used_gb = 0.0

                gpus.append(
                    GPUInfo(
                        index=i,
                        name=props.name,
                        memory_gb=props.total_memory / 1024**3,
                        compute_capability=(props.major, props.minor),
                        current_memory_used_gb=used_gb,
                        mps_enabled=cls._check_mps_enabled(i),
                    )
                )

        except ImportError:
            # PyTorch not available, try nvidia-smi
            gpus = cls._detect_gpus_nvidia_smi()

        return gpus

    @classmethod
    def _detect_gpus_nvidia_smi(cls) -> List[GPUInfo]:
        """Fallback GPU detection using nvidia-smi."""
        gpus = []

        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 4:
                        gpus.append(
                            GPUInfo(
                                index=int(parts[0]),
                                name=parts[1],
                                memory_gb=float(parts[2]) / 1024,  # MiB to GB
                                compute_capability=(0, 0),  # Unknown without PyTorch
                                current_memory_used_gb=float(parts[3]) / 1024,
                            )
                        )
        except Exception:
            pass

        return gpus

    @classmethod
    def _check_mps_enabled(cls, gpu_index: int) -> bool:
        """Check if MPS is enabled for a GPU."""
        mps_pipe = f"/tmp/nvidia-mps-{gpu_index}/control"
        return os.path.exists(mps_pipe)

    @classmethod
    def _detect_system(cls) -> SystemInfo:
        """Detect system (CPU/RAM) information."""
        import os

        # CPU cores
        cpu_cores = os.cpu_count() or 1

        # RAM
        try:
            with open("/proc/meminfo", "r") as f:
                meminfo = f.read()

            total_kb = int(
                [l for l in meminfo.split("\n") if "MemTotal" in l][0].split()[1]
            )
            available_kb = int(
                [l for l in meminfo.split("\n") if "MemAvailable" in l][0].split()[1]
            )
            swap_kb = int(
                [l for l in meminfo.split("\n") if "SwapTotal" in l][0].split()[1]
            )

            ram_gb = total_kb / 1024 / 1024
            available_ram_gb = available_kb / 1024 / 1024
            swap_gb = swap_kb / 1024 / 1024
        except Exception:
            # Fallback
            ram_gb = 16.0
            available_ram_gb = 8.0
            swap_gb = 0.0

        return SystemInfo(
            cpu_cores=cpu_cores,
            ram_gb=ram_gb,
            available_ram_gb=available_ram_gb,
            swap_gb=swap_gb,
        )

    @classmethod
    def print_summary(cls) -> None:
        """Print hardware summary to console."""
        profile = cls.detect()

        print("\n" + "=" * 60)
        print("SHML Hardware Profile")
        print("=" * 60)

        print(f"\nSystem:")
        print(f"  CPU Cores: {profile.system.cpu_cores}")
        print(
            f"  RAM: {profile.system.ram_gb:.1f} GB ({profile.system.available_ram_gb:.1f} GB available)"
        )

        print(f"\nGPUs ({len(profile.gpus)} detected):")
        for gpu in profile.gpus:
            mps_status = (
                f" [MPS: {gpu.mps_memory_limit_gb}GB]" if gpu.mps_enabled else ""
            )
            print(
                f"  [{gpu.index}] {gpu.name}: {gpu.memory_gb:.1f} GB "
                f"(cc {gpu.compute_capability[0]}.{gpu.compute_capability[1]}){mps_status}"
            )

        print(f"\nCapabilities:")
        print(f"  Total VRAM: {profile.total_vram_gb:.1f} GB")
        print(f"  Effective VRAM (with offload): {profile.effective_vram_gb:.1f} GB")
        print(f"  Multi-GPU: {profile.is_multi_gpu}")
        print(f"  Heterogeneous: {profile.is_heterogeneous}")
        print(f"  Recommended Precision: {profile.recommended_precision}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    HardwareDetector.print_summary()
