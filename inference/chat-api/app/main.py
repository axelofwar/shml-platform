"""Chat API - OpenAI-compatible API with authentication, rate limiting, and history sync.

This service provides:
- OpenAI-compatible /v1/chat/completions endpoint
- API key management for Cursor/editor integration
- Role-based rate limiting (100/min dev, 20/min viewer, unlimited admin)
- Conversation history synced across devices
- User instructions that persist across sessions
- Model auto-selection based on query complexity
"""

import time
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config import HOST, PORT, LOG_LEVEL
from .schemas import (
    User,
    UserRole,
    APIKey,
    APIKeyCreate,
    APIKeyList,
    UserInstruction,
    InstructionCreate,
    InstructionList,
    ModelInfo,
    ModelsResponse,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Conversation,
    ConversationSummary,
    ConversationList,
    RateLimitStatus,
    PlatformMetrics,
    HealthResponse,
    ServiceHealth,
)
from .database import db
from .rate_limit import rate_limiter
from .model_router import model_router
from .auth import (
    get_current_user,
    require_admin,
    require_developer_or_admin,
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger(__name__)

START_TIME = time.time()
VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup."""
    logger.info("Starting Chat API...")

    # Connect to services
    await db.connect()
    await rate_limiter.connect()
    await model_router.connect()

    logger.info("Chat API ready")
    yield

    # Cleanup
    logger.info("Shutting down Chat API...")
    await model_router.close()
    await rate_limiter.close()
    await db.close()


app = FastAPI(
    title="SHML Chat API",
    description="""
OpenAI-compatible Chat API with authentication, rate limiting, and history sync.

## Features
- **OpenAI-compatible**: Use with Cursor, Continue.dev, or any OpenAI SDK
- **API Keys**: Generate keys for editor integration
- **Rate Limiting**: Role-based limits (Admin: unlimited, Developer: 100/min, Viewer: 20/min)
- **History Sync**: Conversations sync across devices
- **Instructions**: Persistent system instructions across sessions
- **Model Selection**: Auto, Quality (30B), or Fast (3B)

## Authentication
- **OAuth2**: Via FusionAuth (automatic in browser)
- **API Key**: `Authorization: Bearer shml_...` header

## Quick Start with Cursor
1. Generate an API key at `/api-keys`
2. Configure Cursor: Settings > Models > Add Custom Model
3. Set base URL to `https://shml-platform.tail38b60a.ts.net/chat/v1`
4. Use your API key
    """,
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Health Endpoints
# =============================================================================


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    services = []

    # Check model backends
    model_status = await model_router.get_model_status()
    for key, info in model_status.items():
        services.append(
            ServiceHealth(
                name=f"model-{key}",
                status="healthy" if info.is_available else "unhealthy",
                details={"model": info.id, "gpu": info.gpu},
            )
        )

    # Determine overall status
    statuses = [s.status for s in services]
    if all(s == "healthy" for s in statuses):
        overall = "healthy"
    elif any(s == "healthy" for s in statuses):
        overall = "degraded"
    else:
        overall = "unhealthy"

    return HealthResponse(
        status=overall,
        version=VERSION,
        services=services,
        uptime_seconds=time.time() - START_TIME,
    )


# =============================================================================
# OpenAI-Compatible Endpoints
# =============================================================================


@app.get("/v1/models", response_model=ModelsResponse)
async def list_models(user: User = Depends(get_current_user)):
    """List available models (OpenAI-compatible)."""
    model_status = await model_router.get_model_status()

    models = [
        ModelInfo(
            id="auto",
            name="Auto Select",
            description="Automatically select model based on query complexity",
            context_length=16384,
            is_available=any(m.is_available for m in model_status.values()),
            gpu="Auto",
            vram_gb=0,
            recommended_for=["general use"],
        ),
    ]
    models.extend(model_status.values())

    return ModelsResponse(data=models)


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    user: User = Depends(get_current_user),
):
    """OpenAI-compatible chat completion endpoint."""
    # Check rate limit
    if not await rate_limiter.record(user.id, user.role):
        status = await rate_limiter.check(user.id, user.role)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limited. Resets at {status.reset_at.isoformat()}",
            headers={
                "Retry-After": str(
                    int((status.reset_at - status.reset_at.utcnow()).total_seconds())
                )
            },
        )

    # Get user instructions
    instructions = None
    if request.include_instructions:
        active_instructions = await db.get_active_instructions(user.id)
        if active_instructions:
            instructions = "\n\n".join(
                [f"# {inst.name}\n{inst.content}" for inst in active_instructions]
            )

    # Handle streaming
    if request.stream:

        async def stream_response():
            async for chunk in model_router.generate_stream(request, instructions):
                yield chunk

        return StreamingResponse(
            stream_response(),
            media_type="text/event-stream",
        )

    # Generate completion
    response, model_used, latency_ms = await model_router.generate(
        request, instructions
    )

    # Log usage
    await db.log_usage(
        user_id=user.id,
        model=model_used,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        latency_ms=latency_ms,
        api_key_id=user.api_key_id,
    )

    # Save to conversation history if conversation_id provided
    if request.conversation_id:
        # Add user message
        if request.messages:
            last_user_msg = next(
                (m for m in reversed(request.messages) if m.role == "user"), None
            )
            if last_user_msg:
                await db.add_message(request.conversation_id, last_user_msg)

        # Add assistant response
        if response.choices:
            await db.add_message(request.conversation_id, response.choices[0].message)

        response.conversation_id = request.conversation_id

    return response


# =============================================================================
# API Key Management
# =============================================================================


@app.post("/api-keys", response_model=APIKey)
async def create_api_key(
    request: APIKeyCreate,
    user: User = Depends(require_developer_or_admin),
):
    """Create a new API key. Developers can create for themselves, admins for anyone."""
    try:
        return await db.create_api_key(user, request)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.get("/api-keys", response_model=APIKeyList)
async def list_api_keys(
    target_user_id: Optional[str] = Query(
        None, description="Filter by user (admin only)"
    ),
    user: User = Depends(require_developer_or_admin),
):
    """List API keys. Admins see all, others see their own."""
    keys = await db.list_api_keys(user, target_user_id)
    return APIKeyList(keys=keys, total=len(keys))


@app.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    user: User = Depends(require_developer_or_admin),
):
    """Revoke an API key."""
    success = await db.revoke_api_key(user, key_id)
    if not success:
        raise HTTPException(
            status_code=404, detail="API key not found or access denied"
        )
    return {"status": "revoked"}


# =============================================================================
# User Instructions
# =============================================================================


@app.post("/instructions", response_model=UserInstruction)
async def create_instruction(
    request: InstructionCreate,
    user: User = Depends(require_developer_or_admin),
):
    """Create a new instruction. Platform-wide instructions require admin role."""
    try:
        return await db.create_instruction(user, request)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.get("/instructions", response_model=InstructionList)
async def list_instructions(user: User = Depends(get_current_user)):
    """List instructions (own + platform-wide)."""
    instructions = await db.list_instructions(user)
    return InstructionList(instructions=instructions, total=len(instructions))


@app.put("/instructions/{instruction_id}", response_model=UserInstruction)
async def update_instruction(
    instruction_id: str,
    request: InstructionCreate,
    user: User = Depends(require_developer_or_admin),
):
    """Update an instruction."""
    try:
        result = await db.update_instruction(user, instruction_id, request)
        if not result:
            raise HTTPException(status_code=404, detail="Instruction not found")
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.delete("/instructions/{instruction_id}")
async def delete_instruction(
    instruction_id: str,
    user: User = Depends(require_developer_or_admin),
):
    """Delete an instruction."""
    success = await db.delete_instruction(user, instruction_id)
    if not success:
        raise HTTPException(
            status_code=404, detail="Instruction not found or access denied"
        )
    return {"status": "deleted"}


# =============================================================================
# Conversation History
# =============================================================================


@app.post("/conversations", response_model=dict)
async def create_conversation(
    model: str = "auto",
    title: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    """Create a new conversation."""
    conv_id = await db.create_conversation(user.id, model, title)
    return {"id": conv_id}


@app.get("/conversations", response_model=ConversationList)
async def list_conversations(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
):
    """List conversations for the current user."""
    conversations, total = await db.list_conversations(user.id, limit, offset)
    return ConversationList(
        conversations=conversations,
        total=total,
        has_more=offset + limit < total,
    )


@app.get("/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
):
    """Get a conversation with all messages."""
    conv = await db.get_conversation(conversation_id, user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
):
    """Delete a conversation."""
    success = await db.delete_conversation(user.id, conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}


# =============================================================================
# Rate Limit Status
# =============================================================================


@app.get("/rate-limit", response_model=RateLimitStatus)
async def get_rate_limit(user: User = Depends(get_current_user)):
    """Get current rate limit status."""
    return await rate_limiter.check(user.id, user.role)


# =============================================================================
# Platform Metrics (Aggregate only - visible to developers)
# =============================================================================


@app.get("/metrics", response_model=PlatformMetrics)
async def get_platform_metrics(user: User = Depends(require_developer_or_admin)):
    """Get aggregate platform metrics."""
    db_metrics = await db.get_aggregate_metrics()
    model_status = await model_router.get_model_status()

    return PlatformMetrics(
        total_requests_24h=db_metrics["total_requests_24h"],
        total_tokens_24h=db_metrics["total_tokens_24h"],
        avg_latency_ms=db_metrics["avg_latency_ms"],
        primary_model_available=model_status["primary"].is_available,
        fallback_model_available=model_status["fallback"].is_available,
        active_users_24h=db_metrics["active_users_24h"],
        queue_length=0,  # TODO: Implement queue tracking
        gpu_utilization={},  # TODO: Get from DCGM exporter
    )


# =============================================================================
# Admin Endpoints
# =============================================================================


@app.get("/admin/users", response_model=List[dict])
async def list_users(
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(require_admin),
):
    """List users with usage stats (admin only)."""
    # TODO: Implement user listing from usage_logs
    return []


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
