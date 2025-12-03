# MLflow 3.x Development Server
# For testing upgrade from 2.17.2 to 3.x before production

FROM python:3.11-slim

LABEL maintainer="MLflow Dev Server"
LABEL description="Development environment for testing MLflow 3.x upgrade"
LABEL mlflow.version="3.6.0-dev"

# Install system dependencies
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
    # Utilities
    tree \
    jq \
    vim \
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

# Print installed versions for verification
RUN python -c "import mlflow; print(f'MLflow version: {mlflow.__version__}')" && \
    python -c "import sqlalchemy; print(f'SQLAlchemy version: {sqlalchemy.__version__}')"

# Copy entrypoint
COPY entrypoint.sh /mlflow/

# Set permissions
RUN chown -R mlflow:mlflow /mlflow && \
    chmod +x /mlflow/entrypoint.sh

# Switch to mlflow user
USER mlflow

# Create necessary directories
RUN mkdir -p /mlflow/artifacts /mlflow/mlruns /mlflow/logs

# Expose MLflow port (use different port to avoid conflict)
EXPOSE 5001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

# Entry point
ENTRYPOINT ["/mlflow/entrypoint.sh"]
