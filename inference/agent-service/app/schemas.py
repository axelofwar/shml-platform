"""Pydantic schemas for Agent Service."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    """User roles matching FusionAuth configuration."""

    VIEWER = "viewer"
    DEVELOPER = "developer"
    ELEVATED_DEVELOPER = "elevated-developer"
    ADMIN = "admin"


class ContentPart(BaseModel):
    """Content part for multimodal messages."""

    type: Literal["text", "image_url"]
    text: Optional[str] = None
    image_url: Optional[Dict[str, str]] = None


class AgentMessage(BaseModel):
    """Message in agent conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | List[ContentPart]
    name: Optional[str] = None  # Tool name if role=tool
    tool_call_id: Optional[str] = None


class ToolCall(BaseModel):
    """Tool invocation by agent."""

    id: str
    tool_name: str
    arguments: Dict[str, Any]
    status: Literal[
        "pending", "approved", "rejected", "executing", "completed", "failed"
    ]
    result: Optional[Any] = None
    error: Optional[str] = None
    requires_approval: bool = True
    approved_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class AgentState(BaseModel):
    """Current state of agent workflow."""

    session_id: str
    user_id: str
    user_roles: List[UserRole]
    messages: List[AgentMessage]
    tool_calls: List[ToolCall] = Field(default_factory=list)
    iteration: int = 0
    status: Literal["thinking", "awaiting_approval", "executing", "completed", "failed"]
    current_step: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ApprovalRequest(BaseModel):
    """User approval/rejection of tool call."""

    session_id: str
    tool_call_id: str
    approved: bool
    user_id: str


class InterruptRequest(BaseModel):
    """Request to interrupt agent execution."""

    session_id: str
    user_id: str


# New schemas for ACE pattern


class AgentRequest(BaseModel):
    """Request for agent execution."""

    user_id: str
    session_id: str
    task: str
    category: Optional[str] = None  # coding, debugging, analysis, etc.


class AgentResponse(BaseModel):
    """Response from agent execution."""

    session_id: str
    final_answer: Optional[str] = None  # The actual synthesized response to the user
    generator_output: Optional[str] = None  # Raw generator analysis/planning
    reflector_output: Optional[str] = None
    rubric_scores: Optional[Dict[str, float]] = None
    curator_lessons: List[str] = []
    tool_results: List[Dict[str, Any]] = []
    success: bool
    execution_time_ms: int
    error_messages: Optional[List[str]] = None
    iterations: int = 1  # How many generator iterations were needed
    quality_score: Optional[float] = None  # Final quality score

    # Interactive prompting - next actions for user
    next_actions: List[Dict[str, str]] = []  # List of suggested next steps
    task_complete: bool = True  # Whether the task is fully complete
    continue_prompt: Optional[str] = None  # Prompt for user to continue


class ReflectionRequest(BaseModel):
    """Request for reflection analysis."""

    user_id: str
    last_n: Optional[int] = 10
    update_playbook: bool = False
    reason: str = "User requested stop"


class AuditLog(BaseModel):
    """Audit log entry for agent actions."""

    id: Optional[int] = None
    session_id: str
    user_id: str
    user_roles: List[str]
    action_type: Literal["tool_call", "approval", "rejection", "interrupt", "error"]
    tool_name: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    approved_by: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class HealthResponse(BaseModel):
    """Agent service health check."""

    status: Literal["healthy", "degraded", "unhealthy"]
    active_sessions: int
    total_sandboxes: int
    available_sandboxes: int
    redis_connected: bool
    postgres_connected: bool
    kata_available: bool
