# Production MLflow Server with Schema Validation
FROM python:3.11-slim

LABEL maintainer="MLflow Server"
LABEL description="Privacy-focused MLflow server with automatic compression and schema validation"

# Install system dependencies and diagnostic tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build tools
    gcc \
    g++ \
    libpq-dev \
    # Network tools
    curl \
    wget \
    netcat-openbsd \
    iputils-ping \
    dnsutils \
    telnet \
    traceroute \
    net-tools \
    iproute2 \
    # Database clients
    postgresql-client \
    redis-tools \
    # Compression
    zstd \
    gzip \
    bzip2 \
    # Process/system tools
    procps \
    htop \
    strace \
    lsof \
    # Text editors and viewers
    vim \
    nano \
    less \
    # Other utilities
    tree \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Create mlflow user
RUN useradd -m -u 1000 -s /bin/bash mlflow

# Set working directory
WORKDIR /mlflow

# Install uv for faster package management
RUN pip install --no-cache-dir uv

# Install Python dependencies using uv
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy MLflow plugins and initialization scripts
COPY plugins/ /mlflow/plugins/
COPY scripts/ /mlflow/scripts/
COPY entrypoint.sh /mlflow/

# Set permissions
RUN chown -R mlflow:mlflow /mlflow && \
    chmod +x /mlflow/entrypoint.sh /mlflow/scripts/*.py

# Switch to mlflow user
USER mlflow

# Create necessary directories
RUN mkdir -p /mlflow/artifacts /mlflow/mlruns /mlflow/logs

# Expose MLflow port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Entry point
ENTRYPOINT ["/mlflow/entrypoint.sh"]
