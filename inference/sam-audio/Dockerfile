# SAM Audio - Meta's Multimodal Audio Separation
# Uses Demucs as fallback until SAM Audio HuggingFace release is stable

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for audio processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    libsox-fmt-all \
    sox \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .

# Install PyTorch with CUDA support first
RUN pip install --no-cache-dir \
    torch==2.1.0 \
    torchaudio==2.1.0 \
    --index-url https://download.pytorch.org/whl/cu121

# Install remaining dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create directories
RUN mkdir -p /tmp/sam-audio /app/outputs

# Set environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default to auto device selection
ENV SAM_AUDIO_DEVICE=auto
ENV SAM_AUDIO_USE_FP16=true

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
