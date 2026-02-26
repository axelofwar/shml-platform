# PII Face Blurring Service - SOTA Models (Jan 2026)
# YOLOv11m-Face (detection) + SegFormer (segmentation) + BoxMOT/BoT-SORT (tracking)
# RF-DETR (fallback detection + license plates)
FROM pytorch/pytorch:2.2.1-cuda12.1-cudnn8-runtime

WORKDIR /app

# Set shell to bash with pipefail for safer piped commands
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Prevent interactive prompts during apt-get
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Model cache environment - persist across rebuilds
ENV HF_HOME=/models/huggingface
ENV TORCH_HOME=/models/torch

# Install system dependencies + uv for fast dependency resolution
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv - 10-100x faster than pip
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/

# Install Python dependencies with uv
# Use --link-mode=copy to avoid symlink issues, let UV resolve versions
COPY requirements.txt .
RUN uv pip install --system --no-cache --compile-bytecode -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/

# Create models directory structure
RUN mkdir -p /models/yolo-face /models/yolo-seg /models/segformer /models/reid \
    /models/rfdetr /models/huggingface /models/torch /models/license-plate

# =============================================================================
# PRE-DOWNLOAD MODELS AT BUILD TIME
# This ensures first run is instant and works offline
# =============================================================================

# Download RF-DETR models (base COCO model for face fallback)
# Use || true so build doesn't fail if rfdetr package has import issues
RUN python -c "\
from rfdetr import RFDETRBase; \
print('Downloading RF-DETR Base...'); \
model = RFDETRBase(); \
print('RF-DETR Base downloaded successfully')" || echo "RF-DETR Base download skipped (will download on first use)"

# Download RF-DETR Medium for license plate detection (better accuracy)
RUN python -c "\
from rfdetr import RFDETRMedium; \
print('Downloading RF-DETR Medium...'); \
model = RFDETRMedium(); \
print('RF-DETR Medium downloaded successfully')" || echo "RF-DETR Medium download skipped (will download on first use)"

# Download YOLOv11m-face model
RUN python -c "\
from ultralytics import YOLO; \
import os; \
os.makedirs('/models/yolo-face', exist_ok=True); \
print('Note: YOLOv11m-face will be downloaded on first use from HuggingFace')"

# Download SegFormer for face segmentation
RUN python -c "\
from transformers import SegformerImageProcessor, SegformerForSemanticSegmentation; \
print('Downloading SegFormer nvidia/segformer-b0-finetuned-ade-512-512...'); \
processor = SegformerImageProcessor.from_pretrained('nvidia/segformer-b0-finetuned-ade-512-512'); \
model = SegformerForSemanticSegmentation.from_pretrained('nvidia/segformer-b0-finetuned-ade-512-512'); \
print('SegFormer downloaded successfully')" || echo "SegFormer download skipped (will download on first use)"

# Copy license plate detection config (uses RF-DETR fine-tuned on Roboflow dataset)
COPY scripts/download_plate_model.py ./scripts/
RUN python ./scripts/download_plate_model.py || echo "License plate model will download on first use"

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run FastAPI app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
