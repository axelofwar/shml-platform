# PII Face Blurring Service - YOLOv8l-P2 + SAM3 + ByteTrack
FROM pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime

WORKDIR /app

# Set shell to bash with pipefail for safer piped commands
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install system dependencies + uv for fast dependency resolution
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv - 10-100x faster than pip
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/

# Install Python dependencies with uv
# Install numpy first (required by lap and others at install time)
RUN uv pip install --system --no-cache numpy==1.26.4

COPY requirements.txt .
RUN uv pip install --system --no-cache --compile-bytecode \
    --resolution=lowest-direct \
    -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create models directory (models will be downloaded at runtime or mounted)
RUN mkdir -p /models

# Download YOLOv8l model at build time
RUN python -c "from ultralytics import YOLO; YOLO('yolov8l.pt')" || echo "YOLOv8l will download at runtime"

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run FastAPI app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
