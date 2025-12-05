"""Pydantic schemas for Chat API."""

from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from enum import Enum
from pydantic import BaseModel, Field


# =============================================================================
# Roles and Permissions
# =============================================================================


class UserRole(str, Enum):
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class User(BaseModel):
    """Authenticated user from OAuth or API key."""

    id: str
    email: Optional[str] = None
    name: Optional[str] = None
    role: UserRole = UserRole.VIEWER
    groups: List[str] = []
    # Source of authentication
    auth_method: Literal["oauth", "api_key"] = "oauth"
    api_key_id: Optional[str] = None  # If authenticated via API key


# =============================================================================
# API Keys
# =============================================================================


class APIKeyCreate(BaseModel):
    """Request to create an API key."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    expires_at: Optional[datetime] = None
    # For admin creating keys for viewers
    target_user_id: Optional[str] = None
    target_role: Optional[UserRole] = None


class APIKey(BaseModel):
    """API key response (key shown only on creation)."""

    id: str
    name: str
    description: Optional[str] = None
    user_id: str
    role: UserRole
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    is_active: bool = True
    # Only returned on creation
    key: Optional[str] = None


class APIKeyList(BaseModel):
    """List of API keys (without the actual key values)."""

    keys: List[APIKey]
    total: int


# =============================================================================
# User Instructions
# =============================================================================


class InstructionScope(str, Enum):
    USER = "user"  # Per-user instructions
    PLATFORM = "platform"  # Platform-wide (admin only)


class UserInstruction(BaseModel):
    """Persistent instructions for a user."""

    id: str
    user_id: str
    scope: InstructionScope = InstructionScope.USER
    name: str
    content: str
    is_active: bool = True
    priority: int = 0  # Higher = applied first
    created_at: datetime
    updated_at: datetime


class InstructionCreate(BaseModel):
    """Request to create/update instructions."""

    name: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1, max_length=10000)
    scope: InstructionScope = InstructionScope.USER
    is_active: bool = True
    priority: int = 0


class InstructionList(BaseModel):
    """List of instructions."""

    instructions: List[UserInstruction]
    total: int


# =============================================================================
# Model Selection
# =============================================================================


class ModelSelection(str, Enum):
    AUTO = "auto"  # Auto-select based on query complexity
    PRIMARY = "primary"  # Force 30B model
    FALLBACK = "fallback"  # Force 3B model
    QUALITY = "quality"  # Alias for primary
    FAST = "fast"  # Alias for fallback


class ModelInfo(BaseModel):
    """Information about an available model."""

    id: str
    name: str
    description: str
    context_length: int
    is_available: bool
    gpu: str
    vram_gb: int
    recommended_for: List[str]


class ModelsResponse(BaseModel):
    """List of available models."""

    object: str = "list"
    data: List[ModelInfo]


# =============================================================================
# OpenAI-Compatible Chat
# =============================================================================


class ChatMessage(BaseModel):
    """A single chat message."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class RequestSource(str, Enum):
    """Source of the chat request for applying appropriate constraints."""

    WEB = "web"  # Web chat UI - ask-only mode
    API = "api"  # API/editor integration - full capabilities


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request with extensions."""

    messages: List[ChatMessage]
    model: str = "auto"  # auto, primary, fallback, or specific model ID
    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=0.9, ge=0, le=1)
    max_tokens: Optional[int] = Field(default=4096, ge=1, le=32768)
    stream: bool = False
    stop: Optional[List[str]] = None
    # SHML extensions
    conversation_id: Optional[str] = None  # For history sync
    include_instructions: bool = True  # Include user instructions in context
    source: RequestSource = RequestSource.API  # Request source for mode constraints


class ChatCompletionChoice(BaseModel):
    """A single completion choice."""

    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


class ChatCompletionUsage(BaseModel):
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
    usage: ChatCompletionUsage
    # SHML extensions
    conversation_id: Optional[str] = None
    model_selection: str = "auto"  # Which model was actually used


# =============================================================================
# Conversation History
# =============================================================================


class Conversation(BaseModel):
    """A conversation with message history."""

    id: str
    user_id: str
    title: Optional[str] = None
    model: str
    messages: List[ChatMessage] = []
    created_at: datetime
    updated_at: datetime
    metadata: Optional[Dict[str, Any]] = None


class ConversationSummary(BaseModel):
    """Conversation without full messages (for listing)."""

    id: str
    title: Optional[str] = None
    model: str
    message_count: int
    created_at: datetime
    updated_at: datetime
    preview: Optional[str] = None  # First user message preview


class ConversationList(BaseModel):
    """List of conversations."""

    conversations: List[ConversationSummary]
    total: int
    has_more: bool


# =============================================================================
# Rate Limiting
# =============================================================================


class RateLimitStatus(BaseModel):
    """Rate limit status for a user."""

    requests_remaining: int
    requests_limit: int  # 0 = unlimited
    reset_at: datetime
    is_limited: bool
    role: UserRole


# =============================================================================
# Platform Metrics (Aggregate only)
# =============================================================================


class PlatformMetrics(BaseModel):
    """Aggregate platform metrics (visible to developers)."""

    total_requests_24h: int
    total_tokens_24h: int
    avg_latency_ms: float
    primary_model_available: bool
    fallback_model_available: bool
    active_users_24h: int
    queue_length: int
    gpu_utilization: Dict[str, float]  # {"gpu_0": 0.75, "gpu_1": 0.45}


# =============================================================================
# Health
# =============================================================================


class ServiceHealth(BaseModel):
    """Health of a backend service."""

    name: str
    status: Literal["healthy", "unhealthy", "degraded", "unknown"]
    latency_ms: Optional[float] = None
    details: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    """Overall API health."""

    status: Literal["healthy", "unhealthy", "degraded"]
    version: str
    services: List[ServiceHealth]
    uptime_seconds: float
