"""
T8.4 — shl-nano OpenAI-compatible inference server.

Wraps nanochat's engine in a FastAPI app that speaks the OpenAI
/v1/chat/completions protocol.

Designed to run on GPU 1 (RTX 2070, 8 GB).

Usage (inside inference/shl-nano after training):
    CUDA_VISIBLE_DEVICES=1 \\
    MODEL_RUN=shl-nano-sft \\
    uvicorn shl_nano_server:app --host 0.0.0.0 --port 8021

Environment variables:
    CUDA_VISIBLE_DEVICES   Override GPU selection (default: 1)
    MODEL_RUN              nanochat run tag to load (default: shl-nano-sft)
    MAX_NEW_TOKENS         Max tokens per response (default: 512)
    NANO_CONFIDENCE_THRESHOLD  Min token confidence to avoid tier-0 bailout (0.0–1.0)
    VRAM_FLOOR_MIB         Refuse requests if GPU free VRAM drops below this (default: 512)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import AsyncIterator, List, Optional

import psutil
import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Force GPU assignment BEFORE any torch loading
_GPU = os.environ.get("CUDA_VISIBLE_DEVICES", "1")
os.environ["CUDA_VISIBLE_DEVICES"] = _GPU

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("shl-nano-server")

# ── Config ────────────────────────────────────────────────────────────────────
MODEL_RUN   = os.environ.get("MODEL_RUN", "shl-nano-sft")
MAX_TOKENS  = int(os.environ.get("MAX_NEW_TOKENS", "512"))
CONFIDENCE_THRESHOLD = float(
    os.environ.get("NANO_CONFIDENCE_THRESHOLD", "0.55")
)
VRAM_FLOOR_MIB = int(os.environ.get("VRAM_FLOOR_MIB", "512"))

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="shl-nano inference",
    description="OpenAI-compatible wrapper for nanochat shl-nano model",
    version="1.0.0",
)

# ── nanochat engine (lazy-loaded) ─────────────────────────────────────────────
_engine = None
_tokenizer = None


def _load_engine():
    """Lazy-load the nanochat engine once CUDA_VISIBLE_DEVICES is set."""
    global _engine, _tokenizer
    if _engine is not None:
        return _engine

    try:
        from nanochat.engine import NanoChatEngine  # type: ignore
        log.info(f"Loading nanochat engine for run='{MODEL_RUN}' …")
        _engine = NanoChatEngine.from_run(MODEL_RUN)
        _tokenizer = _engine.tokenizer
        log.info("Engine loaded.")
        return _engine
    except ImportError:
        log.error(
            "nanochat package not found. Make sure you're running inside "
            "the shl-nano venv (inference/shl-nano/.venv) and the model "
            "has been trained."
        )
        raise


# ── Pydantic models (OpenAI API shape) ───────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "shl-nano"
    messages: List[ChatMessage]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"cmpl-shlnano-{uuid.uuid4().hex[:8]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = "shl-nano"
    choices: List[ChatChoice]
    usage: ChatUsage
    # Extension: confidence score so hybrid_router can decide tier escalation
    nano_confidence: float = 1.0


# ── VRAM guard ────────────────────────────────────────────────────────────────
def _check_vram() -> None:
    """Raise 503 if GPU free VRAM is below the floor threshold."""
    if not torch.cuda.is_available():
        return
    try:
        device = torch.cuda.current_device()
        free_mib = (
            torch.cuda.mem_get_info(device)[0] // (1024 * 1024)
        )
        if free_mib < VRAM_FLOOR_MIB:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"GPU {_GPU} has only {free_mib} MiB free "
                    f"(floor={VRAM_FLOOR_MIB} MiB). Service temporarily unavailable."
                ),
            )
    except HTTPException:
        raise
    except Exception:
        pass  # Don't block on VRAM check failures


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Health check — used by hybrid_router before routing to nano."""
    try:
        eng = _load_engine()
        gpu_free = -1
        if torch.cuda.is_available():
            gpu_free = torch.cuda.mem_get_info()[0] // (1024 * 1024)
        return {
            "status": "healthy",
            "model": MODEL_RUN,
            "gpu": _GPU,
            "gpu_free_mib": gpu_free,
        }
    except Exception as exc:
        return {"status": "unhealthy", "reason": str(exc)}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{"id": "shl-nano", "object": "model", "owned_by": "shml"}],
    }


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(req: ChatCompletionRequest):
    _check_vram()

    engine = _load_engine()
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    max_new = req.max_tokens or MAX_TOKENS
    temperature = req.temperature or 0.7

    t0 = time.perf_counter()
    try:
        result = engine.generate(
            messages=messages,
            max_new_tokens=max_new,
            temperature=temperature,
        )
    except Exception as exc:
        log.error(f"nanochat generate failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    latency_ms = (time.perf_counter() - t0) * 1000

    # nanochat engine.generate() returns dict with:
    #   "text": str, "confidence": float (mean top-1 prob), "tokens": int
    # Fall back gracefully if the interface differs.
    if isinstance(result, str):
        text = result
        confidence = 1.0
        tokens = len(text.split())
    else:
        text       = result.get("text", "")
        confidence = float(result.get("confidence", 1.0))
        tokens     = int(result.get("tokens", len(text.split())))

    log.info(
        f"shl-nano generate: conf={confidence:.3f} lat={latency_ms:.0f}ms "
        f"tok={tokens}"
    )

    # If confidence below threshold the hybrid router's _try_nano() will
    # fall through to the next tier automatically via the response field.
    return ChatCompletionResponse(
        choices=[
            ChatChoice(
                message=ChatMessage(role="assistant", content=text),
                finish_reason="stop" if confidence >= CONFIDENCE_THRESHOLD else "low_confidence",
            )
        ],
        usage=ChatUsage(
            completion_tokens=tokens,
            total_tokens=tokens,
        ),
        nano_confidence=confidence,
    )


# ── Streaming endpoint (thin wrapper — nanochat may not support streaming) ────
@app.post("/v1/chat/completions/stream")
async def chat_completions_stream(req: ChatCompletionRequest):
    """SSE streaming path (falls back to non-streaming if engine can't stream)."""
    req.stream = True
    response = await chat_completions(req)

    async def _sse() -> AsyncIterator[str]:
        chunk_id = f"cmpl-shlnano-{uuid.uuid4().hex[:8]}"
        ts = int(time.time())
        content = response.choices[0].message.content
        # Stream word-by-word (nanochat doesn't native-stream yet)
        for word in content.split(" "):
            chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": ts,
                "model": "shl-nano",
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": word + " "},
                    "finish_reason": None,
                }],
            }
            import json
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_sse(), media_type="text/event-stream")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8021"))
    log.info(f"Starting shl-nano server on GPU {_GPU}, port {port}, model={MODEL_RUN}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
