# Agentic Coding Model Service
# Dual-GPU support: RTX 3090 Ti (primary) + RTX 2070 (fallback)
# Inherits: base-cuda-devel (SHML base layer → cuda:12.4.1-devel — required for Triton JIT)
ARG BASE_REGISTRY=shml/local
ARG BASE_TAG=latest
FROM ${BASE_REGISTRY}/base-cuda-devel:${BASE_TAG}

# base-cuda-devel already provides: cuda:12.4.1-devel, Python 3.11 + dev headers,
# gcc/g++, curl, PYTHONUNBUFFERED, HF_HOME=/models, HOST, PORT, non-root inference user

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
