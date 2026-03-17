"""Configuration for Agentic Coding Model service.

Supports dynamic GPU allocation:
- RTX 3090 Ti: Best quality (FP8/FP16) when training is idle
- RTX 2070: Fallback (AWQ/INT4) when training is active
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# =============================================================================
# GPU Configuration
# =============================================================================


@dataclass
class GPUConfig:
    """Configuration for a single GPU."""

    device_id: int
    device: str  # e.g., "cuda:0"
    name: str
    vram_gb: float
    model_id: str
    quantization: Optional[str]  # awq, gptq, fp8, or None
    max_model_len: int
    gpu_memory_utilization: float
    priority: int  # Lower = higher priority


# Primary GPU (RTX 3090 Ti) - Best quality
# Note: vLLM defaults to GPU 0 which is the 3090 Ti in this system
PRIMARY_GPU = GPUConfig(
    device_id=0,  # RTX 3090 Ti is cuda:0 in this system
    device="cuda:0",
    name="RTX 3090 Ti",
    vram_gb=24.0,
    model_id=os.getenv(
        "PRIMARY_MODEL_ID", "cpatonn/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"
    ),
    quantization=None,  # Let vLLM auto-detect (model uses compressed-tensors format)
    max_model_len=16384,  # 16K context (safe for 24GB with 30B AWQ model)
    gpu_memory_utilization=0.85,
    priority=1,
)

# Fallback GPU (RTX 2070) - For when primary is yielded to training
# NOTE: Due to vLLM limitations with multi-GPU in same process,
# fallback mode will restart the service with CUDA_VISIBLE_DEVICES=1
FALLBACK_GPU = GPUConfig(
    device_id=1,  # RTX 2070 is cuda:1 in this system
    device="cuda:1",
    name="RTX 2070",
    vram_gb=8.0,
    model_id=os.getenv("FALLBACK_MODEL_ID", "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"),
    quantization="awq",  # AWQ 4-bit to fit in 8GB
    max_model_len=4096,  # Reduced context to fit in 8GB VRAM with KV cache
    gpu_memory_utilization=0.70,  # Conservative to leave room for CUDA graphs
    priority=2,
)

# =============================================================================
# Ray Integration (for training status checks)
# =============================================================================

RAY_ADDRESS = os.getenv("RAY_ADDRESS", "http://ray-head:8265")
RAY_CHECK_INTERVAL_SECONDS = int(os.getenv("RAY_CHECK_INTERVAL_SECONDS", "10"))

# =============================================================================
# Model Loading Behavior
# =============================================================================

# When training starts, unload primary model after this delay
YIELD_DELAY_SECONDS = int(os.getenv("YIELD_DELAY_SECONDS", "30"))

# When training stops, wait this long before loading primary model
RECLAIM_DELAY_SECONDS = int(os.getenv("RECLAIM_DELAY_SECONDS", "60"))

# Unload model after idle timeout (0 = never unload)
IDLE_TIMEOUT_SECONDS = int(os.getenv("IDLE_TIMEOUT_SECONDS", "600"))  # 10 min

# =============================================================================
# HuggingFace / Model Cache
# =============================================================================

HF_HOME = Path(os.getenv("HF_HOME", "/models"))
HF_TOKEN = os.getenv("HF_TOKEN", None)
TRANSFORMERS_OFFLINE = os.getenv("TRANSFORMERS_OFFLINE", "0") == "1"

# =============================================================================
# API Settings
# =============================================================================

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
API_PREFIX = os.getenv("API_PREFIX", "/v1")

# Default generation parameters
DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.7"))
DEFAULT_TOP_P = float(os.getenv("DEFAULT_TOP_P", "0.8"))
DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", "4096"))
