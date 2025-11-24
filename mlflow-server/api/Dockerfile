FROM python:3.11-slim

LABEL maintainer="PII-PRO MLflow API"
LABEL description="FastAPI wrapper for MLflow with schema validation and error handling"

# Install network tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    iputils-ping \
    netcat-openbsd \
    telnet \
    dnsutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for faster package management
RUN pip install --no-cache-dir uv

# Install dependencies using uv
RUN uv pip install --system --no-cache \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    pydantic==2.5.0 \
    mlflow==2.9.2 \
    pyyaml==6.0.1 \
    python-multipart==0.0.6 \
    prometheus-client==0.19.0 \
    authlib==1.3.0 \
    httpx==0.25.2 \
    python-jose[cryptography]==3.3.0

# Copy API code
COPY main.py /app/main.py

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run API with single worker for debugging
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "debug", "--access-log"]
