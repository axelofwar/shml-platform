"""
Pydantic schemas for the conversation memory system.
Supports: auto-tagging, summarization, multi-modal, project scoping, encryption.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import uuid


class MemoryTagType(str, Enum):
    """Auto-tagging categories for conversation classification."""

    BUG = "bug"
    LESSON = "lesson"
    GOAL = "goal"
    STRATEGY = "strategy"
    RESEARCH = "research"
    IMPLEMENTATION = "implementation"
    KNOWN_ISSUE = "known_issue"
    DESIGN_DECISION = "design_decision"
    PLATFORM_CHOICE = "platform_choice"
    TOOL_CHOICE = "tool_choice"
    REPEATABLE_PATTERN = "repeatable_pattern"
    EDGE_CASE_SOLVED = "edge_case_solved"
    CONFIGURATION = "configuration"
    DEBUG_SESSION = "debug_session"
    CODE_REVIEW = "code_review"
    PERFORMANCE = "performance"
    SECURITY = "security"


class MemoryTier(str, Enum):
    """Storage tier based on access patterns and importance."""

    HOT = "hot"  # In vector index, fast retrieval
    WARM = "warm"  # In postgres, not indexed
    ARCHIVE = "archive"  # Compressed, explicit search only


class ContentType(str, Enum):
    """Content types for multi-modal memory."""

    TEXT = "text"
    CODE = "code"
    IMAGE = "image"
    ERROR_LOG = "error_log"
    TERMINAL_OUTPUT = "terminal_output"
    FILE_DIFF = "file_diff"
    SCHEMA = "schema"


class MemoryTag(BaseModel):
    """Tag with confidence score from auto-classification."""

    tag: MemoryTagType
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = "auto"  # "auto" or "user"

    class Config:
        use_enum_values = True


class MemoryChunk(BaseModel):
    """Individual chunk of a conversation for vector storage."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    memory_id: str
    user_id: str
    project_id: Optional[str] = None
    workspace_path: Optional[str] = None

    # Content
    content: str
    content_type: ContentType = ContentType.TEXT
    embedding: Optional[List[float]] = None

    # Metadata
    role: str  # "user", "assistant", "system"
    turn_index: int
    token_count: int = 0

    # Multi-modal references (store paths, not content)
    attachments: List[Dict[str, Any]] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class Memory(BaseModel):
    """Full conversation memory with metadata."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    project_id: Optional[str] = None
    workspace_path: Optional[str] = None
    session_id: Optional[str] = None

    # Content summary
    title: str  # Auto-generated from first message
    summary: Optional[str] = None  # LLM-generated summary

    # Tags and classification
    tags: List[MemoryTag] = Field(default_factory=list)
    primary_tag: Optional[MemoryTagType] = None

    # Metrics for decay/importance
    importance_score: float = 1.0
    access_count: int = 0
    last_accessed: datetime = Field(default_factory=datetime.utcnow)

    # Storage tier
    tier: MemoryTier = MemoryTier.HOT

    # Links to related memories
    related_memory_ids: List[str] = Field(default_factory=list)
    parent_summary_id: Optional[str] = None  # For consolidated memories
    source_memory_ids: List[str] = Field(default_factory=list)  # If this is a summary

    # Context
    files_referenced: List[str] = Field(default_factory=list)
    errors_encountered: List[str] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Soft delete
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None

    class Config:
        use_enum_values = True


class SessionSummary(BaseModel):
    """Daily/weekly session summary for consolidation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    project_id: Optional[str] = None

    # Time range
    start_date: datetime
    end_date: datetime

    # Aggregated content
    summary: str
    key_decisions: List[str] = Field(default_factory=list)
    problems_solved: List[str] = Field(default_factory=list)
    patterns_learned: List[str] = Field(default_factory=list)

    # Source memories
    source_memory_ids: List[str] = Field(default_factory=list)
    memory_count: int = 0

    # Tags (aggregated from source memories)
    tags: List[MemoryTag] = Field(default_factory=list)

    # Embedding for summary search
    embedding: Optional[List[float]] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectContext(BaseModel):
    """Project-level persistent context."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    project_id: str
    workspace_path: str

    # Project understanding
    description: Optional[str] = None
    tech_stack: List[str] = Field(default_factory=list)
    key_files: List[str] = Field(default_factory=list)
    architecture_notes: Optional[str] = None

    # Persistent patterns
    coding_conventions: List[str] = Field(default_factory=list)
    common_issues: List[str] = Field(default_factory=list)
    preferred_solutions: Dict[str, str] = Field(default_factory=dict)

    # Embedding
    embedding: Optional[List[float]] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryQuery(BaseModel):
    """Query parameters for memory search."""

    query: str
    user_id: str
    project_id: Optional[str] = None
    workspace_path: Optional[str] = None

    # Search options
    top_k: int = 10
    use_hybrid: bool = True
    use_rerank: bool = True
    rerank_top_n: int = 5

    # Filters
    tags: Optional[List[MemoryTagType]] = None
    min_importance: Optional[float] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    tiers: List[MemoryTier] = Field(default_factory=lambda: [MemoryTier.HOT])

    # Boost recent
    recency_weight: float = 0.3

    class Config:
        use_enum_values = True


class MemorySearchResult(BaseModel):
    """Search result with relevance scoring."""

    memory: Memory
    chunks: List[MemoryChunk] = Field(default_factory=list)

    # Scores
    vector_score: float = 0.0
    bm25_score: float = 0.0
    hybrid_score: float = 0.0
    rerank_score: Optional[float] = None
    final_score: float = 0.0

    # Context
    matched_keywords: List[str] = Field(default_factory=list)
    relevance_explanation: Optional[str] = None


class ConversationContext(BaseModel):
    """Full context package for injection into coding model."""

    # Retrieved memories
    relevant_memories: List[MemorySearchResult] = Field(default_factory=list)

    # Project context
    project_context: Optional[ProjectContext] = None

    # Recent session context
    session_summary: Optional[SessionSummary] = None

    # Code context
    recent_files: List[str] = Field(default_factory=list)
    git_diff: Optional[str] = None
    current_errors: List[str] = Field(default_factory=list)

    # Formatted for injection
    formatted_context: str = ""
    token_count: int = 0
    max_tokens: int = 4000

    # Metadata
    retrieval_time_ms: float = 0.0
    memories_searched: int = 0


# ============= Change Staging Schemas =============


class ChangeStatus(str, Enum):
    """Status of a staged change."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    REVERTED = "reverted"


class StagedChange(BaseModel):
    """A staged code change awaiting approval."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    session_id: str

    # File info
    file_path: str
    original_content: Optional[str] = None
    new_content: str

    # Change details
    change_type: str  # "create", "modify", "delete"
    diff: Optional[str] = None
    description: str

    # Context
    conversation_id: Optional[str] = None
    related_memory_id: Optional[str] = None

    # Status
    status: ChangeStatus = ChangeStatus.PENDING

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None

    # Audit
    review_comment: Optional[str] = None

    class Config:
        use_enum_values = True


class ChangeSet(BaseModel):
    """Group of related changes from a single conversation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    session_id: str

    # Changes
    changes: List[StagedChange] = Field(default_factory=list)

    # Context
    description: str
    conversation_summary: Optional[str] = None

    # Status
    status: ChangeStatus = ChangeStatus.PENDING

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def file_count(self) -> int:
        return len(set(c.file_path for c in self.changes))

    @property
    def pending_count(self) -> int:
        return len([c for c in self.changes if c.status == ChangeStatus.PENDING])
