# DCGM Exporter with healthcheck support
# Extends official NVIDIA image with curl for healthchecks

FROM nvcr.io/nvidia/k8s/dcgm-exporter:3.3.5-3.4.0-ubuntu22.04

# Install curl for healthchecks (minimal footprint)
USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Return to default user if applicable
USER nobody
