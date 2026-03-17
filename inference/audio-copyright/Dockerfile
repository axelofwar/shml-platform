# Audio Copyright Detection & AI Replacement Service
FROM python:3.11-slim

WORKDIR /app

# Set shell to bash with pipefail for safer piped commands
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install system dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    portaudio19-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv - 10-100x faster than pip
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/

# Install Python dependencies with uv
# Install numpy first (required by many packages at install time)
RUN uv pip install --system --no-cache numpy==1.26.4

COPY requirements.txt .
RUN uv pip install --system --no-cache --compile-bytecode \
    --resolution=lowest-direct \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

# Clone audio fingerprinting library (dejavu or audfprint)
RUN git clone https://github.com/worldveil/dejavu.git /opt/dejavu || echo "Using installed package"

# Copy application code
COPY app/ ./app/

# Create music database directory (will be mounted as volume)
RUN mkdir -p ./music_database

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run FastAPI app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
