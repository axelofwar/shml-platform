# Qwen3-VL Dockerfile - Optimized for RTX 2070 (8GB VRAM)
# Inherits: base-python-gpu (SHML base layer → base-cuda-runtime → cuda:12.1.0-runtime)
ARG BASE_REGISTRY=shml/local
ARG BASE_TAG=latest
FROM ${BASE_REGISTRY}/base-python-gpu:${BASE_TAG}

# base-python-gpu already provides: CUDA 12.1 runtime, Python 3.11, curl, uv,
# non-root inference user (uid 1000), PYTHONUNBUFFERED, HF_HOME, TRANSFORMERS_OFFLINE
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

# Set ownership
RUN chown -R inference:inference /app

# Switch to non-root user
USER inference

# base-python-gpu already sets: PYTHONUNBUFFERED, PYTHONDONTWRITEBYTECODE,
# HF_HOME=/models, TRANSFORMERS_OFFLINE=1, HF_HUB_OFFLINE=1

# Health check
HEALTHCHECK --interval=60s --timeout=30s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
