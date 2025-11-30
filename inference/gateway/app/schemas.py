"""Pydantic schemas for Inference Gateway."""
from typing import Optional, List, Literal, Any
from pydantic import BaseModel, Field
from datetime import datetime


# ===== Chat History =====

class ChatMessage(BaseModel):
    """Single chat message."""
    role: Literal["system", "user", "assistant"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)


class Conversation(BaseModel):
    """Full conversation with metadata."""
    id: str
    user_id: str
    title: Optional[str] = None
    messages: List[ChatMessage]
    model: str
    created_at: datetime
    updated_at: datetime
    metadata: Optional[dict] = None


class ConversationSummary(BaseModel):
    """Lightweight conversation list item."""
    id: str
    title: Optional[str]
    message_count: int
    model: str
    created_at: datetime
    updated_at: datetime


# ===== Queue Status =====

class QueuedRequest(BaseModel):
    """Request in queue."""
    id: str
    user_id: str
    service: Literal["llm", "image"]
    position: int
    queued_at: datetime
    estimated_wait_seconds: Optional[int] = None


class QueueStatus(BaseModel):
    """Queue status response."""
    llm_queue_length: int
    image_queue_length: int
    active_requests: int
    max_concurrent: int
    your_requests: List[QueuedRequest]


# ===== Rate Limiting =====

class RateLimitStatus(BaseModel):
    """Rate limit status for user."""
    requests_remaining: int
    requests_limit: int
    reset_at: datetime
    is_limited: bool


# ===== Health =====

class ServiceHealth(BaseModel):
    """Single service health."""
    name: str
    status: Literal["healthy", "unhealthy", "loading", "unknown"]
    latency_ms: Optional[float] = None


class GatewayHealth(BaseModel):
    """Gateway health response."""
    status: Literal["healthy", "degraded", "unhealthy"]
    services: List[ServiceHealth]
    queue_length: int
    uptime_seconds: float


# ===== Backup =====

class BackupInfo(BaseModel):
    """Backup file info."""
    filename: str
    size_bytes: int
    created_at: datetime
    compression: str
    conversations_count: int
