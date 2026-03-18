# PII Face Blurring Service - SOTA Models (Jan 2026)
# YOLOv11m-Face (detection) + SegFormer (segmentation) + BoxMOT/BoT-SORT (tracking)
# RF-DETR (fallback detection + license plates)
# Inherits: base-cuda-cudnn (SHML base layer → pytorch/pytorch:2.2.1-cuda12.1-cudnn8-runtime)
ARG BASE_REGISTRY=shml/local
ARG BASE_TAG=latest
FROM ${BASE_REGISTRY}/base-cuda-cudnn:${BASE_TAG}

WORKDIR /app

# Set shell to bash with pipefail for safer piped commands
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# base-cuda-cudnn already provides: pytorch base, uv, curl, DEBIAN_FRONTEND=noninteractive,
# TZ=UTC, HF_HOME=/models/huggingface, TORCH_HOME=/models/torch

# CV system libs specific to pii-blur (ffmpeg, OpenCV deps, libgomp for YOLO)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies with uv
# Install numpy first to avoid NumPy 2.x ABI mismatches with torch/rfdetr deps.
RUN uv pip install --system --no-cache numpy==1.26.4

# Use lowest-direct resolution to reduce unnecessary version upgrades.
COPY requirements.txt .
RUN uv pip install --system --no-cache --compile-bytecode \
    --resolution=lowest-direct \
    -r requirements.txt

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
