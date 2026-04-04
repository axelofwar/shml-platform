# Dockerfile for Nemotron-3-Nano with llama-server
# Uses llama.cpp compiled with CUDA support

FROM nvidia/cuda:12.2.0-devel-ubuntu22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    curl \
    libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone and build llama.cpp
WORKDIR /opt
RUN git clone https://github.com/ggerganov/llama.cpp.git
WORKDIR /opt/llama.cpp
RUN cmake -B build \
        -DBUILD_SHARED_LIBS=OFF \
        -DGGML_CUDA=ON \
        -DLLAMA_CURL=ON && \
    cmake --build build --config Release -j "$(nproc)" && \
    cp build/bin/llama-server /usr/local/bin/
WORKDIR /opt
RUN rm -rf llama.cpp

WORKDIR /app

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["llama-server"]
