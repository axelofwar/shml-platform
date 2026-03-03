import os

"""Embedding Service - CPU-based sentence-transformers for codebase indexing.

This service provides:
- /embed - Generate embeddings for text
- /embed/batch - Batch embedding generation
- /embed/code - Optimized for code snippets
"""

import time
import logging
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global model
model: Optional[SentenceTransformer] = None
MODEL_NAME = (
    "sentence-transformers/all-MiniLM-L6-v2"  # 384 dimensions, fast, good quality
)
EMBEDDING_DIM = 384
START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model on startup."""
    global model
    logger.info(f"Loading embedding model: {MODEL_NAME}")
    start = time.time()
    model = SentenceTransformer(MODEL_NAME)
    logger.info(f"Model loaded in {time.time() - start:.2f}s")
    yield
    logger.info("Shutting down embedding service")


app = FastAPI(
    title="SHML Embedding Service",
    description="CPU-based embedding generation for codebase indexing and RAG",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS",
        "https://shml-platform.tail38b60a.ts.net,http://localhost:3000,http://localhost:8080",
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Schemas
# =============================================================================


class EmbedRequest(BaseModel):
    """Single text embedding request."""

    text: str = Field(..., min_length=1, max_length=10000)
    normalize: bool = True


class EmbedBatchRequest(BaseModel):
    """Batch embedding request."""

    texts: List[str] = Field(..., min_items=1, max_items=100)
    normalize: bool = True


class CodeEmbedRequest(BaseModel):
    """Code embedding request with language hint."""

    code: str = Field(..., min_length=1, max_length=50000)
    language: Optional[str] = None
    file_path: Optional[str] = None
    normalize: bool = True


class EmbedResponse(BaseModel):
    """Single embedding response."""

    embedding: List[float]
    dimensions: int
    model: str
    latency_ms: int


class EmbedBatchResponse(BaseModel):
    """Batch embedding response."""

    embeddings: List[List[float]]
    dimensions: int
    count: int
    model: str
    latency_ms: int


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    model: str
    dimensions: int
    uptime_seconds: float


# =============================================================================
# Endpoints
# =============================================================================


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy" if model is not None else "unhealthy",
        model=MODEL_NAME,
        dimensions=EMBEDDING_DIM,
        uptime_seconds=time.time() - START_TIME,
    )


@app.post("/embed", response_model=EmbedResponse)
async def embed_text(request: EmbedRequest):
    """Generate embedding for a single text."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    start = time.time()
    embedding = model.encode(
        request.text,
        normalize_embeddings=request.normalize,
    )
    latency_ms = int((time.time() - start) * 1000)

    return EmbedResponse(
        embedding=embedding.tolist(),
        dimensions=len(embedding),
        model=MODEL_NAME,
        latency_ms=latency_ms,
    )


@app.post("/embed/batch", response_model=EmbedBatchResponse)
async def embed_batch(request: EmbedBatchRequest):
    """Generate embeddings for multiple texts."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    start = time.time()
    embeddings = model.encode(
        request.texts,
        normalize_embeddings=request.normalize,
        batch_size=32,
        show_progress_bar=False,
    )
    latency_ms = int((time.time() - start) * 1000)

    return EmbedBatchResponse(
        embeddings=embeddings.tolist(),
        dimensions=embeddings.shape[1],
        count=len(embeddings),
        model=MODEL_NAME,
        latency_ms=latency_ms,
    )


@app.post("/embed/code", response_model=EmbedResponse)
async def embed_code(request: CodeEmbedRequest):
    """Generate embedding optimized for code.

    Prepends language/file info to improve embedding quality for code.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    # Prepare text with code context
    prefix = ""
    if request.language:
        prefix += f"Language: {request.language}\n"
    if request.file_path:
        prefix += f"File: {request.file_path}\n"

    text = f"{prefix}\n{request.code}" if prefix else request.code

    start = time.time()
    embedding = model.encode(
        text,
        normalize_embeddings=request.normalize,
    )
    latency_ms = int((time.time() - start) * 1000)

    return EmbedResponse(
        embedding=embedding.tolist(),
        dimensions=len(embedding),
        model=MODEL_NAME,
        latency_ms=latency_ms,
    )


@app.get("/model-info")
async def model_info():
    """Get model information."""
    return {
        "model_name": MODEL_NAME,
        "dimensions": EMBEDDING_DIM,
        "max_sequence_length": 256,  # MiniLM default
        "device": "cpu",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
