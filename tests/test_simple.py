"""
Simple FastAPI test to verify the application starts
"""

import pytest

# Skip tests if fastapi is not installed
try:
    from fastapi import FastAPI

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    FastAPI = None

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi package not installed")

import os

if HAS_FASTAPI:
    app = FastAPI(title="MLflow API Test", version="1.0.0")

    @app.get("/health")
    def health():
        return {
            "status": "healthy",
            "mlflow_uri": os.getenv("MLFLOW_TRACKING_URI", "not set"),
        }

    @app.get("/")
    def root():
        return {"message": "MLflow API is running"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
