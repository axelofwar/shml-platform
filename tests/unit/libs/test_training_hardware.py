from __future__ import annotations

import io
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch


_ROOT = Path(__file__).resolve().parents[3]
_TRAINING_ROOT = _ROOT / "libs" / "training"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if str(_TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAINING_ROOT))


def _make_torch_module(*, is_available: bool = False, device_specs: list[dict] | None = None) -> ModuleType:
    module = ModuleType("torch")
    cuda = SimpleNamespace()
    specs = device_specs or []

    cuda.is_available = lambda: is_available
    cuda.device_count = lambda: len(specs)

    def get_device_properties(index: int) -> SimpleNamespace:
        spec = specs[index]
        return SimpleNamespace(
            name=spec["name"],
            total_memory=spec["total_memory"],
            major=spec["major"],
            minor=spec["minor"],
        )

    def mem_get_info(index: int = 0) -> tuple[int, int]:
        spec = specs[index]
        return (spec["free_memory"], spec["total_memory"])

    cuda.get_device_properties = get_device_properties
    cuda.mem_get_info = mem_get_info
    module.cuda = cuda
    return module


class TestGPUInfo:
    def test_properties_cover_tiers_and_capabilities(self):
        from shml_training.core.hardware import GPUInfo, GPUTier

        datacenter = GPUInfo(
            index=0,
            name="NVIDIA A100",
            memory_gb=80.0,
            compute_capability=(9, 0),
            current_memory_used_gb=12.5,
        )
        prosumer = GPUInfo(
            index=1,
            name="RTX 4090",
            memory_gb=24.0,
            compute_capability=(8, 9),
        )
        consumer = GPUInfo(
            index=2,
            name="RTX 2070",
            memory_gb=8.0,
            compute_capability=(7, 5),
        )

        assert datacenter.available_memory_gb == 67.5
        assert datacenter.tier == GPUTier.DATACENTER
        assert datacenter.supports_bf16 is True
        assert datacenter.supports_fp8 is True

        assert prosumer.tier == GPUTier.PROSUMER
        assert prosumer.supports_bf16 is True
        assert prosumer.supports_fp8 is False

        assert consumer.tier == GPUTier.CONSUMER
        assert consumer.supports_bf16 is False


class TestHardwareProfile:
    def test_profile_computes_aggregate_fields_and_budget(self):
        from shml_training.core.hardware import GPUInfo, HardwareProfile, SystemInfo

        profile = HardwareProfile(
            gpus=[
                GPUInfo(index=0, name="RTX 3090", memory_gb=24.0, compute_capability=(8, 6)),
                GPUInfo(index=1, name="RTX 2070", memory_gb=8.0, compute_capability=(7, 5)),
            ],
            system=SystemInfo(
                cpu_cores=16,
                ram_gb=128.0,
                available_ram_gb=96.0,
                swap_gb=8.0,
            ),
        )

        budget = profile.get_memory_budget(10)

        assert profile.total_vram_gb == 32.0
        assert profile.effective_vram_gb == 80.0
        assert profile.is_multi_gpu is True
        assert profile.is_heterogeneous is True
        assert profile.primary_gpu.name == "RTX 3090"
        assert profile.recommended_precision == "bf16"

        assert budget.model_memory_gb == 20
        assert budget.optimizer_memory_gb == 80
        assert budget.gradient_memory_gb == 20
        assert budget.available_gpu_gb == 32.0
        assert budget.available_cpu_gb == 96.0
        assert budget.can_fit_on_gpu is False
        assert budget.requires_cpu_offload is True
        assert budget.requires_gradient_checkpointing is True

    def test_profile_marks_homogeneous_single_gpu_correctly(self):
        from shml_training.core.hardware import GPUInfo, HardwareProfile, SystemInfo

        profile = HardwareProfile(
            gpus=[GPUInfo(index=0, name="RTX 2070", memory_gb=8.0, compute_capability=(7, 5))],
            system=SystemInfo(cpu_cores=4, ram_gb=16.0, available_ram_gb=8.0, swap_gb=0.0),
        )

        assert profile.is_multi_gpu is False
        assert profile.is_heterogeneous is False
        assert profile.primary_gpu.name == "RTX 2070"
        assert profile.recommended_precision == "fp16"


class TestHardwareDetector:
    def teardown_method(self):
        from shml_training.core.hardware import HardwareDetector

        HardwareDetector._cached_profile = None

    def test_detect_caches_and_force_refreshes(self):
        from shml_training.core.hardware import HardwareDetector, SystemInfo

        system_a = SystemInfo(cpu_cores=4, ram_gb=16.0, available_ram_gb=8.0, swap_gb=0.0)
        system_b = SystemInfo(cpu_cores=8, ram_gb=32.0, available_ram_gb=24.0, swap_gb=2.0)

        with patch.object(HardwareDetector, "_detect_gpus", return_value=[]), patch.object(
            HardwareDetector,
            "_detect_system",
            side_effect=[system_a, system_b],
        ):
            first = HardwareDetector.detect()
            second = HardwareDetector.detect()
            third = HardwareDetector.detect(force_refresh=True)

        assert first is second
        assert third is not first
        assert first.system.cpu_cores == 4
        assert third.system.cpu_cores == 8

    def test_detect_gpus_uses_torch_properties_when_available(self):
        from shml_training.core.hardware import HardwareDetector

        torch_module = _make_torch_module(
            is_available=True,
            device_specs=[
                {
                    "name": "RTX 3090",
                    "total_memory": 24 * 1024**3,
                    "free_memory": 18 * 1024**3,
                    "major": 8,
                    "minor": 6,
                }
            ],
        )

        with patch.dict(sys.modules, {"torch": torch_module}), patch.object(
            HardwareDetector, "_check_mps_enabled", return_value=True
        ):
            gpus = HardwareDetector._detect_gpus()

        assert len(gpus) == 1
        assert gpus[0].name == "RTX 3090"
        assert round(gpus[0].memory_gb, 1) == 24.0
        assert round(gpus[0].current_memory_used_gb, 1) == 6.0
        assert gpus[0].compute_capability == (8, 6)
        assert gpus[0].mps_enabled is True

    def test_detect_gpus_falls_back_to_nvidia_smi_when_torch_missing(self):
        from shml_training.core.hardware import HardwareDetector

        real_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "torch":
                raise ImportError("torch unavailable")
            return real_import(name, globals, locals, fromlist, level)

        fallback_gpus = [MagicMock(name="gpu")]
        with patch("builtins.__import__", side_effect=fake_import), patch.object(
            HardwareDetector, "_detect_gpus_nvidia_smi", return_value=fallback_gpus
        ):
            detected = HardwareDetector._detect_gpus()

        assert detected == fallback_gpus

    def test_detect_gpus_nvidia_smi_parses_output(self):
        from shml_training.core.hardware import HardwareDetector

        completed = MagicMock(
            returncode=0,
            stdout="0, NVIDIA A100, 81920, 10240\n1, RTX 2070, 8192, 1024\n",
        )

        with patch("subprocess.run", return_value=completed):
            gpus = HardwareDetector._detect_gpus_nvidia_smi()

        assert len(gpus) == 2
        assert gpus[0].name == "NVIDIA A100"
        assert gpus[0].compute_capability == (0, 0)
        assert round(gpus[0].memory_gb, 1) == 80.0
        assert round(gpus[1].current_memory_used_gb, 1) == 1.0

    def test_detect_system_parses_proc_meminfo(self):
        from shml_training.core.hardware import HardwareDetector

        meminfo = """MemTotal:       33554432 kB\nMemAvailable:   16777216 kB\nSwapTotal:       8388608 kB\n"""

        with patch("os.cpu_count", return_value=12), patch("builtins.open", return_value=io.StringIO(meminfo)):
            system = HardwareDetector._detect_system()

        assert system.cpu_cores == 12
        assert system.ram_gb == 32.0
        assert system.available_ram_gb == 16.0
        assert system.swap_gb == 8.0

    def test_detect_system_uses_fallback_values_on_error(self):
        from shml_training.core.hardware import HardwareDetector

        with patch("os.cpu_count", return_value=None), patch("builtins.open", side_effect=OSError):
            system = HardwareDetector._detect_system()

        assert system.cpu_cores == 1
        assert system.ram_gb == 16.0
        assert system.available_ram_gb == 8.0
        assert system.swap_gb == 0.0

    def test_print_summary_renders_profile(self, capsys):
        from shml_training.core.hardware import GPUInfo, HardwareDetector, HardwareProfile, SystemInfo

        profile = HardwareProfile(
            gpus=[GPUInfo(index=0, name="RTX 3090", memory_gb=24.0, compute_capability=(8, 6))],
            system=SystemInfo(cpu_cores=16, ram_gb=64.0, available_ram_gb=48.0, swap_gb=4.0),
        )

        with patch.object(HardwareDetector, "detect", return_value=profile):
            HardwareDetector.print_summary()

        out = capsys.readouterr().out
        assert "SHML Hardware Profile" in out
        assert "CPU Cores: 16" in out
        assert "RTX 3090: 24.0 GB" in out
        assert "Recommended Precision: bf16" in out
