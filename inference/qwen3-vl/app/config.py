"""Qwen3-VL configuration - environment-based settings."""
import os
from pathlib import Path

# Model settings
MODEL_ID = os.getenv("MODEL_ID", "Qwen/Qwen3-VL-8B-Instruct")
QUANTIZATION = os.getenv("QUANTIZATION", "int4")  # none, int4, int8
DEVICE = os.getenv("DEVICE", "cuda:0")  # RTX 2070 = cuda:0
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "4096"))
CONTEXT_LENGTH = int(os.getenv("CONTEXT_LENGTH", "32768"))

# Paths
HF_HOME = Path(os.getenv("HF_HOME", "/models"))
LOG_DIR = Path(os.getenv("LOG_DIR", "/app/logs"))

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Privacy settings
OFFLINE_MODE = os.getenv("TRANSFORMERS_OFFLINE", "1") == "1"

# Resource management
UNLOAD_TIMEOUT_SECONDS = int(os.getenv("UNLOAD_TIMEOUT_SECONDS", "600"))  # 10 min
YIELD_TO_TRAINING = os.getenv("YIELD_TO_TRAINING", "true").lower() == "true"
