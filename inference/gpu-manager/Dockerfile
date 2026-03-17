# Unified GPU Manager - Coordinates GPU resources for training and inference

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    fastapi==0.109.0 \
    uvicorn[standard]==0.27.0 \
    docker==7.0.0 \
    pydantic==2.5.3

# Copy application
COPY main.py .

# Run as non-root (needs docker socket access via group)
# The docker group GID should match the host's docker group
# Typically 984 on Arch/systemd, 999 on Debian/Ubuntu

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
