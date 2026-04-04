import os

"""Inference Gateway - Unified API with queue, history, and rate limiting."""

import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from .config import QWEN3_VL_URL, Z_IMAGE_URL, CODING_MODEL_URL, HOST, PORT
from .schemas import (
    GatewayHealth,
    ServiceHealth,
    QueueStatus,
    RateLimitStatus,
    Conversation,
    ConversationSummary,
    BackupInfo,
)
from .vision_schemas import OrchestrationRequest, OrchestrationResponse
from .orchestrator import orchestrator
from .queue import request_queue
from .history import chat_history
from .rate_limit import rate_limiter
from .backup import create_backup, list_backups, cleanup_old_backups
from .training_router import router as training_router
from .feedback_router import router as feedback_router
from .audio_router import router as audio_router
from .gemini_router import router as gemini_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize connections on startup."""
    logger.info("Starting Inference Gateway...")
    await request_queue.connect()
    await chat_history.connect()
    await rate_limiter.connect()
    await orchestrator.initialize()
    yield
    logger.info("Shutting down...")
    await orchestrator.close()
    await request_queue.close()
    await chat_history.close()
    await rate_limiter.close()


app = FastAPI(
    title="Inference Gateway",
    description="Unified API for local LLM, Image Generation, and Audio Processing",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:8080",
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(training_router)
app.include_router(feedback_router)
app.include_router(audio_router)  # DMCA-safe audio workflow
app.include_router(gemini_router)  # Gemini proxy for SBA Resource Portal


def get_user_id(x_user_id: Optional[str] = Header(default=None)) -> str:
    """Get user ID from header (set by Authentik/Traefik)."""
    return x_user_id or "anonymous"


# ===== Health Endpoints =====


@app.get("/health", response_model=GatewayHealth)
async def health():
    """Gateway health check."""
    from .config import SAM_AUDIO_URL, AUDIO_COPYRIGHT_URL

    services = []

    # Check backend services (core + audio)
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in [
            ("qwen3-vl", QWEN3_VL_URL),
            ("z-image", Z_IMAGE_URL),
            ("coding-model", CODING_MODEL_URL),
            ("sam-audio", SAM_AUDIO_URL),
            ("audio-copyright", AUDIO_COPYRIGHT_URL),
        ]:
            try:
                start = time.time()
                resp = await client.get(f"{url}/health")
                latency = (time.time() - start) * 1000

                if resp.status_code == 200:
                    data = resp.json()
                    services.append(
                        ServiceHealth(
                            name=name,
                            status=data.get("status", "healthy"),
                            latency_ms=latency,
                        )
                    )
                else:
                    services.append(ServiceHealth(name=name, status="unhealthy"))
            except Exception:
                services.append(ServiceHealth(name=name, status="unknown"))

    # Determine overall status
    statuses = [s.status for s in services]
    if all(s == "healthy" for s in statuses):
        overall = "healthy"
    elif any(s == "healthy" for s in statuses):
        overall = "degraded"
    else:
        overall = "unhealthy"

    queue_status = await request_queue.get_status()

    return GatewayHealth(
        status=overall,
        services=services,
        queue_length=queue_status.llm_queue_length + queue_status.image_queue_length,
        uptime_seconds=time.time() - START_TIME,
    )


# ===== Queue Endpoints =====


@app.get("/queue/status", response_model=QueueStatus)
async def queue_status(x_user_id: Optional[str] = Header(default=None)):
    """Get queue status."""
    user_id = get_user_id(x_user_id)
    return await request_queue.get_status(user_id)


@app.delete("/queue/{request_id}")
async def cancel_request(
    request_id: str,
    x_user_id: Optional[str] = Header(default=None),
):
    """Cancel a queued request."""
    user_id = get_user_id(x_user_id)
    success = await request_queue.cancel(request_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Request not found or not yours")
    return {"status": "cancelled"}


# ===== Rate Limit Endpoints =====


@app.get("/rate-limit", response_model=RateLimitStatus)
async def rate_limit_status(x_user_id: Optional[str] = Header(default=None)):
    """Get rate limit status."""
    user_id = get_user_id(x_user_id)
    return await rate_limiter.check(user_id)


# ===== Chat History Endpoints =====


@app.post("/conversations", response_model=dict)
async def create_conversation(
    model: str = "qwen3-vl-8b",
    title: Optional[str] = None,
    x_user_id: Optional[str] = Header(default=None),
):
    """Create new conversation."""
    user_id = get_user_id(x_user_id)
    conv_id = await chat_history.create_conversation(user_id, model, title)
    return {"id": conv_id}


@app.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    limit: int = 50,
    offset: int = 0,
    x_user_id: Optional[str] = Header(default=None),
):
    """List user's conversations."""
    user_id = get_user_id(x_user_id)
    return await chat_history.list_conversations(user_id, limit, offset)


@app.get("/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: str,
    x_user_id: Optional[str] = Header(default=None),
):
    """Get full conversation."""
    user_id = get_user_id(x_user_id)
    conv = await chat_history.get_conversation(conversation_id, user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    x_user_id: Optional[str] = Header(default=None),
):
    """Delete conversation."""
    user_id = get_user_id(x_user_id)
    success = await chat_history.delete_conversation(conversation_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}


# ===== Backup Endpoints =====


@app.post("/backups", response_model=BackupInfo)
async def create_backup_endpoint(
    background_tasks: BackgroundTasks,
    x_user_id: Optional[str] = Header(default=None),
):
    """Create compressed backup of chat history."""
    user_id = get_user_id(x_user_id)
    backup = await create_backup(user_id)
    background_tasks.add_task(cleanup_old_backups)
    return backup


@app.get("/backups", response_model=list[BackupInfo])
async def list_backups_endpoint(x_user_id: Optional[str] = Header(default=None)):
    """List available backups."""
    user_id = get_user_id(x_user_id)
    return await list_backups(user_id)


# ===== Proxy Endpoints (pass through to backend services) =====


@app.api_route("/llm/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_llm(
    path: str,
    x_user_id: Optional[str] = Header(default=None),
):
    """Proxy requests to Qwen3-VL service."""
    user_id = get_user_id(x_user_id)

    # Check rate limit
    if not await rate_limiter.record(user_id):
        status = await rate_limiter.check(user_id)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limited. Resets at {status.reset_at.isoformat()}",
        )

    # Forward to backend
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            resp = await client.request(
                method="POST",  # Simplify for now
                url=f"{QWEN3_VL_URL}/{path}",
                headers={"X-User-ID": user_id},
            )
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))


@app.api_route("/image/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_image(
    path: str,
    x_user_id: Optional[str] = Header(default=None),
):
    """Proxy requests to Z-Image service."""
    user_id = get_user_id(x_user_id)

    # Check rate limit
    if not await rate_limiter.record(user_id):
        status = await rate_limiter.check(user_id)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limited. Resets at {status.reset_at.isoformat()}",
        )

    # Forward to backend
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            resp = await client.request(
                method="POST",
                url=f"{Z_IMAGE_URL}/{path}",
                headers={"X-User-ID": user_id},
            )
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))


# ===== Coding Model Endpoints (OpenAI-compatible) =====


@app.api_route("/coding/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_coding(
    path: str,
    x_user_id: Optional[str] = Header(default=None),
):
    """Proxy requests to Coding Model service (OpenAI-compatible).

    Routes to the best available GPU:
    - RTX 3090 Ti (FP8) when training is idle
    - RTX 2070 (AWQ) when training is active
    """
    from fastapi import Request

    user_id = get_user_id(x_user_id)

    # Check rate limit
    if not await rate_limiter.record(user_id):
        status = await rate_limiter.check(user_id)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limited. Resets at {status.reset_at.isoformat()}",
        )

    # Forward to coding model backend
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            resp = await client.request(
                method="POST",
                url=f"{CODING_MODEL_URL}/{path}",
                headers={"X-User-ID": user_id},
            )
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))


@app.get("/coding/status")
async def coding_model_status():
    """Get coding model GPU allocation status."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{CODING_MODEL_URL}/status")
            return resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))


# ===== Orchestration Endpoint =====


@app.post("/v1/orchestrate/chat", response_model=OrchestrationResponse)
async def orchestrate_chat(
    request: OrchestrationRequest,
    user_id: str = Header(default="anonymous", alias="X-User-Id"),
):
    """
    Orchestrated chat endpoint that automatically routes to vision + coding models.

    - If request contains images: vision model first, then coding model with vision context
    - If no images: coding model directly

    This provides a seamless multimodal experience without client-side orchestration logic.
    """
    try:
        logger.info(f"Orchestration request from user {user_id}")
        response = await orchestrator.process_request(request)
        logger.info(f"Orchestration complete: {response.orchestration_path}")
        return response
    except Exception as e:
        logger.error(f"Orchestration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
