"""Pydantic schemas for OpenAI-compatible API."""

from typing import List, Optional, Literal, Union
from pydantic import BaseModel, Field


class Message(BaseModel):
    """Chat message."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[dict]] = None
    tool_call_id: Optional[str] = None


class FunctionDefinition(BaseModel):
    """Function definition for tool calling."""

    name: str
    description: Optional[str] = None
    parameters: Optional[dict] = None


class Tool(BaseModel):
    """Tool definition."""

    type: Literal["function"] = "function"
    function: FunctionDefinition


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: str = "qwen2.5-coder-7b"
    messages: List[Message]
    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=0.8, ge=0, le=1)
    max_tokens: Optional[int] = Field(default=4096, ge=1)
    stream: bool = False
    tools: Optional[List[Tool]] = None
    tool_choice: Optional[Union[str, dict]] = None
    stop: Optional[Union[str, List[str]]] = None


class ChatCompletionChoice(BaseModel):
    """Single choice in completion response."""

    index: int
    message: Message
    finish_reason: Optional[str] = None


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

    status: str
    model_loaded: bool
    model_id: str
    device: str
    vram_used_gb: Optional[float] = None


class ModelStatusResponse(BaseModel):
    """Detailed model status."""

    loaded: bool
    model_id: str
    device: str
    quantization: str
    vram_used_gb: float
    requests_served: int
    uptime_seconds: float
    last_used: Optional[str] = None
