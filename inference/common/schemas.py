"""Common schemas shared across inference services."""

from pydantic import BaseModel
from typing import Optional


class HealthResponse(BaseModel):
    """Standard health check response."""

    status: str = "healthy"
    service: str
    version: str = "1.0.0"
    model_loaded: Optional[bool] = None
    gpu_available: Optional[bool] = None


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: Optional[str] = None
    code: Optional[str] = None


class ChatMessage(BaseModel):
    """Standard chat message format (OpenAI compatible)."""

    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """Standard chat completion request (OpenAI compatible)."""

    model: str
    messages: list[ChatMessage]
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.95
    max_tokens: Optional[int] = 4096
    stream: Optional[bool] = False
    stop: Optional[list[str]] = None


class ChatCompletionChoice(BaseModel):
    """Single completion choice."""

    index: int
    message: ChatMessage
    finish_reason: str


class Usage(BaseModel):
    """Token usage information."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """Standard chat completion response (OpenAI compatible)."""

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: Usage
