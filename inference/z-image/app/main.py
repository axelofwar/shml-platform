import os

"""Z-Image FastAPI service - Photorealistic image generation."""

import uuid
import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from .config import MODEL_ID, DEVICE, HOST, PORT, OUTPUT_DIR
from .schemas import (
    ImageGenerationRequest,
    ImageGenerationResponse,
    HealthResponse,
    ModelStatusResponse,
)
from .model import model_instance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Optionally pre-load model on startup."""
    logger.info("Starting Z-Image service...")
    # Don't pre-load - let RTX 3090 stay free for training
    # Model loads on first request
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yield
    logger.info("Shutting down, unloading model...")
    model_instance.unload()


app = FastAPI(
    title="Z-Image API",
    description="Photorealistic image generation with Z-Image-Turbo",
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
        uptime_seconds=model_instance.get_uptime(),
    )


@app.get("/status", response_model=ModelStatusResponse)
async def status():
    """Detailed model status."""
    return ModelStatusResponse(
        loaded=model_instance.loaded,
        loading=model_instance.loading,
        last_used=model_instance.last_used,
        images_generated=model_instance.images_generated,
        average_generation_time_seconds=model_instance.get_average_generation_time(),
        yielded_to_training=model_instance.yielded_to_training,
    )


@app.post("/v1/generate", response_model=ImageGenerationResponse)
async def generate_image(request: ImageGenerationRequest):
    """Generate photorealistic image from prompt."""
    try:
        image, seed, gen_time = model_instance.generate(
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            width=request.width,
            height=request.height,
            num_inference_steps=request.num_inference_steps,
            guidance_scale=request.guidance_scale,
            seed=request.seed,
        )

        # Convert to base64
        image_base64 = model_instance.image_to_base64(image)

        # Generate ID
        image_id = f"img-{uuid.uuid4().hex[:12]}"

        return ImageGenerationResponse(
            id=image_id,
            created=int(time.time()),
            prompt=f"[{len(request.prompt)} chars]",  # Metadata only, privacy
            width=request.width,
            height=request.height,
            seed=seed,
            inference_time_seconds=gen_time,
            image_base64=image_base64,
        )

    except Exception as e:
        logger.error(f"Image generation failed: {e}")
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
    """Manually unload model (frees RTX 3090 for training)."""
    if not model_instance.loaded:
        return {"status": "already_unloaded"}

    success = model_instance.unload(reason="manual")
    return {"status": "unloaded" if success else "error"}


@app.post("/yield-to-training")
async def yield_to_training():
    """Signal that training is starting - unload to free GPU."""
    success = model_instance.yield_to_training()
    return {
        "status": "yielded" if success else "not_loaded",
        "vram_freed_gb": model_instance.get_vram_total() if success else 0,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
