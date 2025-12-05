"""OpenAI-compatible FastAPI service for Agentic Coding.

Provides:
- /v1/chat/completions - OpenAI-compatible chat endpoint
- /v1/models - List available models
- /health - Health check
- /status - Detailed GPU and model status
- /memory/* - Conversation memory with RAG retrieval
- /changes/* - Change staging system (approve/reject)
"""

import os
import uuid
import time
import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Union, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import HOST, PORT, DEFAULT_TEMPERATURE, DEFAULT_TOP_P, DEFAULT_MAX_TOKENS

# Use simple model manager (one model per container)
from .model_manager_simple import SimpleModelManager
from .schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    Message,
    Usage,
    HealthResponse,
    ModelStatusResponse,
)
from .memory import (
    MemoryManager,
    MemoryQuery,
    Memory,
    MemorySearchResult,
    ConversationContext,
    ChangeStaging,
    StagedChange,
)
from .memory.schemas import MemoryTagType, MemoryTier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global instances
model_manager: Optional[SimpleModelManager] = None
memory_manager: Optional[MemoryManager] = None
change_staging: Optional[ChangeStaging] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize model manager and memory system on startup."""
    global model_manager, memory_manager, change_staging

    logger.info("Starting Agentic Coding service...")
    logger.info(f"  Mode: {os.getenv('MODEL_MODE', 'fallback')}")
    logger.info(f"  Model: {os.getenv('MODEL_ID', 'unknown')}")

    try:
        model_manager = SimpleModelManager()
        await model_manager.initialize()
        logger.info("Model manager initialized successfully")

        # Initialize memory system (optional - service works without database)
        try:
            memory_manager = MemoryManager()
            await memory_manager.initialize()
            logger.info("Memory manager initialized successfully")

            # Initialize change staging
            from .memory.memory_manager import MemoryConfig

            change_staging = ChangeStaging(MemoryConfig.DATABASE_URL)
            await change_staging.initialize()
            logger.info("Change staging initialized successfully")
        except Exception as db_err:
            logger.warning(f"Memory system unavailable (database error): {db_err}")
            logger.warning("Service will run without conversation memory features")
            memory_manager = None
            change_staging = None

    except Exception as e:
        logger.error(f"Failed to initialize: {e}")
        raise
    yield
    logger.info("Shutting down...")
    if model_manager:
        await model_manager.shutdown()
    if memory_manager:
        await memory_manager.close()
    if change_staging:
        await change_staging.close()


app = FastAPI(
    title="Agentic Coding API",
    description="OpenAI-compatible API for code generation with dynamic GPU allocation",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# OpenAI-Compatible Endpoints
# =============================================================================


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(request: ChatCompletionRequest):
    """OpenAI-compatible chat completion endpoint.

    Automatically routes to the best available GPU:
    - RTX 3090 Ti (FP8) when training is idle
    - RTX 2070 (AWQ) when training is active
    """
    try:
        start_time = time.time()

        # Convert messages to dict format
        messages = [msg.model_dump() for msg in request.messages]
        tools = [tool.model_dump() for tool in request.tools] if request.tools else None

        # Generate completion
        result = await model_manager.generate(
            messages=messages,
            temperature=request.temperature,
            top_p=request.top_p,
            max_tokens=request.max_tokens or DEFAULT_MAX_TOKENS,
            tools=tools,
            stop=request.stop,
        )

        # Format response
        response = ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
            created=int(time.time()),
            model=result["model"],
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=Message(role="assistant", content=result["content"]),
                    finish_reason=result["finish_reason"],
                )
            ],
            usage=Usage(
                prompt_tokens=result["prompt_tokens"],
                completion_tokens=result["completion_tokens"],
                total_tokens=result["prompt_tokens"] + result["completion_tokens"],
            ),
        )

        latency_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Generated {result['completion_tokens']} tokens ({result['mode']} mode) "
            f"in {latency_ms:.0f}ms"
        )

        return response

    except Exception as e:
        logger.error(f"Error generating completion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "local"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: List[ModelInfo]


@app.get("/v1/models", response_model=ModelsResponse)
async def list_models():
    """List available models."""
    status = model_manager.get_status()

    models = []

    # Add this container's model if loaded
    if status["is_loaded"]:
        models.append(
            ModelInfo(
                id=status["model_id"],
                owned_by=f"local-{status['mode']}",
            )
        )

    return ModelsResponse(data=models)


# =============================================================================
# Health and Status Endpoints
# =============================================================================


@app.get("/health")
async def health_check(response: Response):
    """Health check endpoint - returns 503 if unhealthy (for Traefik routing)."""
    health = model_manager.get_health()

    if health["status"] != "healthy":
        response.status_code = 503

    return health


@app.get("/status")
async def detailed_status():
    """Get detailed status of model and GPU."""
    return model_manager.get_status()


@app.post("/admin/yield")
async def force_yield():
    """Force unload the model (admin endpoint)."""
    await model_manager._unload_model()
    model_manager.is_yielded = True
    return {"status": "model unloaded", "mode": model_manager.model_mode}


@app.post("/admin/reclaim")
async def force_reclaim():
    """Force load the model (admin endpoint)."""
    await model_manager._load_model()
    model_manager.is_yielded = False
    return {"status": "model loaded", "mode": model_manager.model_mode}


# =============================================================================
# Memory System Endpoints
# =============================================================================


class StoreConversationRequest(BaseModel):
    """Request to store a conversation."""

    user_id: str
    messages: List[Dict[str, Any]]
    project_id: Optional[str] = None
    workspace_path: Optional[str] = None
    session_id: Optional[str] = None
    auto_tag: bool = True


class SearchMemoryRequest(BaseModel):
    """Request to search memories."""

    query: str
    user_id: str
    project_id: Optional[str] = None
    top_k: int = 10
    use_hybrid: bool = True
    use_rerank: bool = True
    tags: Optional[List[str]] = None
    tiers: List[str] = ["hot"]


class GetContextRequest(BaseModel):
    """Request to get context for injection."""

    query: str
    user_id: str
    project_id: Optional[str] = None
    workspace_path: Optional[str] = None
    max_tokens: int = 4000


@app.post("/memory/store")
async def store_conversation(request: StoreConversationRequest):
    """Store a conversation as searchable memory."""
    if not memory_manager:
        raise HTTPException(status_code=503, detail="Memory system not initialized")

    try:
        memory = await memory_manager.store_conversation(
            user_id=request.user_id,
            messages=request.messages,
            project_id=request.project_id,
            workspace_path=request.workspace_path,
            session_id=request.session_id,
            auto_tag=request.auto_tag,
        )
        return {
            "status": "stored",
            "memory_id": memory.id,
            "tags": [t.model_dump() for t in memory.tags],
        }
    except Exception as e:
        logger.error(f"Failed to store conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/memory/search")
async def search_memories(request: SearchMemoryRequest):
    """Search memories using hybrid search + reranking."""
    if not memory_manager:
        raise HTTPException(status_code=503, detail="Memory system not initialized")

    try:
        query = MemoryQuery(
            query=request.query,
            user_id=request.user_id,
            project_id=request.project_id,
            top_k=request.top_k,
            use_hybrid=request.use_hybrid,
            use_rerank=request.use_rerank,
            tags=[MemoryTagType(t) for t in request.tags] if request.tags else None,
            tiers=[MemoryTier(t) for t in request.tiers],
        )

        results = await memory_manager.search(query)

        return {
            "results": [
                {
                    "memory": r.memory.model_dump(),
                    "chunks": [c.model_dump(exclude={"embedding"}) for c in r.chunks],
                    "scores": {
                        "vector": r.vector_score,
                        "bm25": r.bm25_score,
                        "hybrid": r.hybrid_score,
                        "rerank": r.rerank_score,
                        "final": r.final_score,
                    },
                }
                for r in results
            ],
            "count": len(results),
        }
    except Exception as e:
        logger.error(f"Failed to search memories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/memory/context")
async def get_context(request: GetContextRequest):
    """Get formatted context for injection into prompts."""
    if not memory_manager:
        raise HTTPException(status_code=503, detail="Memory system not initialized")

    try:
        context = await memory_manager.get_context_for_query(
            query=request.query,
            user_id=request.user_id,
            project_id=request.project_id,
            workspace_path=request.workspace_path,
            max_tokens=request.max_tokens,
        )

        return {
            "formatted_context": context.formatted_context,
            "token_count": context.token_count,
            "retrieval_time_ms": context.retrieval_time_ms,
            "memories_count": len(context.relevant_memories),
            "has_project_context": context.project_context is not None,
        }
    except Exception as e:
        logger.error(f"Failed to get context: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str, user_id: str, hard_delete: bool = False):
    """Delete a memory (soft by default, hard if specified)."""
    if not memory_manager:
        raise HTTPException(status_code=503, detail="Memory system not initialized")

    try:
        await memory_manager.delete_memory(memory_id, user_id, hard_delete)
        return {"status": "deleted", "memory_id": memory_id, "hard_delete": hard_delete}
    except Exception as e:
        logger.error(f"Failed to delete memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/memory/decay")
async def apply_decay():
    """Apply importance decay to all memories (admin endpoint)."""
    if not memory_manager:
        raise HTTPException(status_code=503, detail="Memory system not initialized")

    await memory_manager.apply_decay()
    return {"status": "decay applied"}


# =============================================================================
# Change Staging Endpoints
# =============================================================================


class StageChangeRequest(BaseModel):
    """Request to stage a code change."""

    user_id: str
    session_id: str
    file_path: str
    new_content: str
    description: str
    original_content: Optional[str] = None


class StageMultipleRequest(BaseModel):
    """Request to stage multiple changes."""

    user_id: str
    session_id: str
    changes: List[Dict[str, Any]]
    description: str
    conversation_summary: Optional[str] = None


@app.post("/changes/stage")
async def stage_change(request: StageChangeRequest):
    """Stage a code change for review."""
    if not change_staging:
        raise HTTPException(status_code=503, detail="Change staging not initialized")

    try:
        change = await change_staging.stage_change(
            user_id=request.user_id,
            session_id=request.session_id,
            file_path=request.file_path,
            new_content=request.new_content,
            description=request.description,
            original_content=request.original_content,
        )
        return {
            "status": "staged",
            "change_id": change.id,
            "file_path": change.file_path,
            "diff": change.diff,
        }
    except Exception as e:
        logger.error(f"Failed to stage change: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/changes/stage-multiple")
async def stage_multiple_changes(request: StageMultipleRequest):
    """Stage multiple changes as a set."""
    if not change_staging:
        raise HTTPException(status_code=503, detail="Change staging not initialized")

    try:
        changeset = await change_staging.stage_multiple(
            user_id=request.user_id,
            session_id=request.session_id,
            changes=request.changes,
            description=request.description,
            conversation_summary=request.conversation_summary,
        )
        return {
            "status": "staged",
            "changeset_id": changeset.id,
            "change_count": len(changeset.changes),
            "changes": [
                {"id": c.id, "file_path": c.file_path, "type": c.change_type}
                for c in changeset.changes
            ],
        }
    except Exception as e:
        logger.error(f"Failed to stage changes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/changes/pending")
async def get_pending_changes(user_id: str, session_id: Optional[str] = None):
    """Get all pending changes for a user/session."""
    if not change_staging:
        raise HTTPException(status_code=503, detail="Change staging not initialized")

    changes = await change_staging.get_pending_changes(user_id, session_id)
    return {
        "changes": [
            {
                "id": c.id,
                "file_path": c.file_path,
                "change_type": c.change_type,
                "description": c.description,
                "diff": c.diff,
                "created_at": c.created_at.isoformat(),
            }
            for c in changes
        ],
        "count": len(changes),
    }


@app.post("/changes/{change_id}/approve")
async def approve_change(change_id: str, user_id: str, comment: Optional[str] = None):
    """Approve a staged change."""
    if not change_staging:
        raise HTTPException(status_code=503, detail="Change staging not initialized")

    try:
        change = await change_staging.approve_change(change_id, user_id, comment)
        return {"status": "approved", "change_id": change.id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/changes/{change_id}/reject")
async def reject_change(change_id: str, user_id: str, comment: Optional[str] = None):
    """Reject a staged change."""
    if not change_staging:
        raise HTTPException(status_code=503, detail="Change staging not initialized")

    try:
        change = await change_staging.reject_change(change_id, user_id, comment)
        return {"status": "rejected", "change_id": change.id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/changes/{change_id}/apply")
async def apply_change(change_id: str, user_id: str, workspace_path: str):
    """Apply an approved change to the filesystem."""
    if not change_staging:
        raise HTTPException(status_code=503, detail="Change staging not initialized")

    try:
        change = await change_staging.apply_change(change_id, user_id, workspace_path)
        return {
            "status": "applied",
            "change_id": change.id,
            "file_path": change.file_path,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/changes/{change_id}/revert")
async def revert_change(change_id: str, user_id: str, workspace_path: str):
    """Revert an applied change."""
    if not change_staging:
        raise HTTPException(status_code=503, detail="Change staging not initialized")

    try:
        change = await change_staging.revert_change(change_id, user_id, workspace_path)
        return {"status": "reverted", "change_id": change.id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/changes/approve-all")
async def approve_all_changes(user_id: str, session_id: str, workspace_path: str):
    """Approve and apply all pending changes for a session."""
    if not change_staging:
        raise HTTPException(status_code=503, detail="Change staging not initialized")

    try:
        changes = await change_staging.approve_and_apply_all(
            user_id, session_id, workspace_path
        )
        return {
            "status": "applied",
            "count": len(changes),
            "files": [c.file_path for c in changes],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/changes/reject-all")
async def reject_all_changes(
    user_id: str, session_id: str, comment: Optional[str] = None
):
    """Reject all pending changes for a session."""
    if not change_staging:
        raise HTTPException(status_code=503, detail="Change staging not initialized")

    changes = await change_staging.reject_all(user_id, session_id, comment)
    return {"status": "rejected", "count": len(changes)}


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
