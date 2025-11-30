"""Pydantic schemas for Qwen3-VL API - OpenAI compatible."""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class Message(BaseModel):
    """Chat message format."""
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""
    model: str = "qwen3-vl-8b"
    messages: List[Message]
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    top_p: float = Field(default=0.9, ge=0, le=1)
    stream: bool = False  # Streaming not implemented yet


class ChatCompletionChoice(BaseModel):
    """Single completion choice."""
    index: int
    message: Message
    finish_reason: Literal["stop", "length", "error"]


class Usage(BaseModel):
    """Token usage statistics."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: Usage


class HealthResponse(BaseModel):
    """Health check response."""
    status: Literal["healthy", "loading", "unloaded", "error"]
    model: str
    device: str
    vram_used_gb: Optional[float] = None
    vram_total_gb: Optional[float] = None
    quantization: str
    uptime_seconds: float


class ModelStatusResponse(BaseModel):
    """Detailed model status."""
    loaded: bool
    loading: bool
    last_used: Optional[datetime] = None
    requests_served: int
    average_latency_ms: float
