"""Z-Image configuration - environment-based settings."""
import os
from pathlib import Path

# Model settings
MODEL_ID = os.getenv("MODEL_ID", "Tongyi-MAI/Z-Image-Turbo")
DEVICE = os.getenv("DEVICE", "cuda:1")  # RTX 3090 = cuda:1
DTYPE = os.getenv("DTYPE", "bfloat16")  # bfloat16 optimal for Z-Image
NUM_INFERENCE_STEPS = int(os.getenv("NUM_INFERENCE_STEPS", "8"))  # Turbo needs only 8

# Paths
HF_HOME = Path(os.getenv("HF_HOME", "/models"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/outputs"))
LOG_DIR = Path(os.getenv("LOG_DIR", "/app/logs"))

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Privacy settings
OFFLINE_MODE = os.getenv("TRANSFORMERS_OFFLINE", "1") == "1"

# Resource management - Z-Image yields to training
UNLOAD_TIMEOUT_SECONDS = int(os.getenv("UNLOAD_TIMEOUT_SECONDS", "300"))  # 5 min
YIELD_TO_TRAINING = os.getenv("YIELD_TO_TRAINING", "true").lower() == "true"

# Default image settings
DEFAULT_WIDTH = int(os.getenv("DEFAULT_WIDTH", "1024"))
DEFAULT_HEIGHT = int(os.getenv("DEFAULT_HEIGHT", "1024"))
MAX_WIDTH = int(os.getenv("MAX_WIDTH", "2048"))
MAX_HEIGHT = int(os.getenv("MAX_HEIGHT", "2048"))
