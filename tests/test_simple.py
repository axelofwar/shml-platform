"""
Simple FastAPI test to verify the application starts
"""

from fastapi import FastAPI
import os

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
