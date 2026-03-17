# Agentic Coding Model Service
# Dual-GPU support: RTX 3090 Ti (primary) + RTX 2070 (fallback)
# Using NVIDIA CUDA devel base for Triton JIT compilation support

FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/models
ENV HOST=0.0.0.0
ENV PORT=8000
ENV DEBIAN_FRONTEND=noninteractive

# Install Python and system dependencies
# gcc/g++ and python3-dev needed for Triton JIT compilation on older GPUs (RTX 2070 etc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    curl \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python

# Create app directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi>=0.104.0 \
    uvicorn[standard]>=0.24.0 \
    httpx>=0.25.0 \
    pydantic>=2.5.0 \
    vllm>=0.6.0 \
    asyncpg>=0.29.0 \
    sentence-transformers>=2.2.0 \
    tiktoken>=0.5.0 \
    numpy \
    torch

# Copy application code
COPY app/ ./app/

# Health check
HEALTHCHECK --interval=60s --timeout=30s --start-period=300s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run the service
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
