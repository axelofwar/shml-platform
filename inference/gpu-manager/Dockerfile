# Unified GPU Manager - Coordinates GPU resources for training and inference
# Uses uv for fast dependency installation

FROM python:3.11-slim

WORKDIR /app

ENV PATH="/root/.local/bin:$PATH" \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

RUN uv pip install --system \
    fastapi==0.109.0 \
    "uvicorn[standard]==0.27.0" \
    docker==7.0.0 \
    pydantic==2.5.3

# Copy application
COPY main.py .

# Run as non-root (needs docker socket access via group)
# The docker group GID should match the host's docker group
# Typically 984 on Arch/systemd, 999 on Debian/Ubuntu

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
