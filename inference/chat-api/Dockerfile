# Chat API Dockerfile
# Inherits: base-python-cpu (SHML base layer)
ARG BASE_REGISTRY=shml/local
ARG BASE_TAG=latest
FROM ${BASE_REGISTRY}/base-python-cpu:${BASE_TAG}

# base-python-cpu already provides: python:3.11-slim, curl, uv, non-root inference user (uid 1000)
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

RUN chown -R inference:inference /app
USER inference

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
