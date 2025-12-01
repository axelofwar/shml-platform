"""Qwen3-VL FastAPI service - OpenAI-compatible LLM API."""

import uuid
import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from .config import MODEL_ID, QUANTIZATION, DEVICE, HOST, PORT
from .schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    Message,
    Usage,
    HealthResponse,
    ModelStatusResponse,
)
from .model import model_instance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model on startup."""
    logger.info("Starting Qwen3-VL service...")
    try:
        model_instance.load()
    except Exception as e:
        logger.warning(f"Model not pre-loaded (will load on first request): {e}")
    yield
    logger.info("Shutting down, unloading model...")
    model_instance.unload()


app = FastAPI(
    title="Qwen3-VL API",
    description="Local LLM for planning, architecture, and code scaffolding",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Traefik handles auth
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    status = "healthy" if model_instance.loaded else "unloaded"
    if model_instance.loading:
        status = "loading"

    return HealthResponse(
        status=status,
        model=MODEL_ID,
        device=DEVICE,
        vram_used_gb=model_instance.get_vram_usage() if model_instance.loaded else None,
        vram_total_gb=model_instance.get_vram_total(),
        quantization=QUANTIZATION,
        uptime_seconds=model_instance.get_uptime(),
    )


@app.get("/status", response_model=ModelStatusResponse)
async def status():
    """Detailed model status."""
    return ModelStatusResponse(
        loaded=model_instance.loaded,
        loading=model_instance.loading,
        last_used=model_instance.last_used,
        requests_served=model_instance.requests_served,
        average_latency_ms=model_instance.get_average_latency(),
    )


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completions endpoint."""
    try:
        # Generate response
        response_text, prompt_tokens, completion_tokens = model_instance.generate(
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            top_p=request.top_p,
        )

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=Message(role="assistant", content=response_text),
                    finish_reason="stop",
                )
            ],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    except Exception as e:
        logger.error(f"Chat completion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/load")
async def load_model(background_tasks: BackgroundTasks):
    """Manually trigger model loading."""
    if model_instance.loaded:
        return {"status": "already_loaded"}

    if model_instance.loading:
        return {"status": "loading"}

    background_tasks.add_task(model_instance.load)
    return {"status": "loading_started"}


@app.post("/unload")
async def unload_model():
    """Manually trigger model unloading (frees GPU memory)."""
    if not model_instance.loaded:
        return {"status": "already_unloaded"}

    success = model_instance.unload()
    return {"status": "unloaded" if success else "error"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
