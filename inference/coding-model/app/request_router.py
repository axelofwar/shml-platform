"""
Request Router - Intelligent routing of inference requests.

Routes requests to the appropriate model (primary vs fallback) based on:
- Training state (fallback-only during training)
- Request complexity (context length, max tokens, keywords)
- User role (admin can force primary with warning)
- RAG/history availability (can we address with existing context?)
- Skill/tool count required for agentic tasks
- Explicit model selection (primary hidden during training)
- Queue state with wait time estimation

Design Philosophy (from SOTA research):
- ToolOrchestra pattern: Small orchestrator makes smart routing decisions
- Cost-aware routing: Prefer fallback when quality is sufficient
- AG-UI protocol: Show queue status and wait times to user
"""

import re
import logging
import hashlib
from typing import Optional, Dict, Any, Tuple, List, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class RoutingDecision(Enum):
    """Routing decision types."""

    PRIMARY = "primary"
    FALLBACK = "fallback"
    QUEUED_FOR_PRIMARY = "queued_for_primary"
    REJECTED = "rejected"


class RoutingReason(Enum):
    """Reasons for routing decisions."""

    # Route to Primary
    EXPLICIT_SELECTION = "explicit_selection"
    CONTEXT_TOO_LONG = "context_too_long"
    MAX_TOKENS_HIGH = "max_tokens_high"
    COMPLEXITY_DETECTED = "complexity_detected"
    MULTI_SKILL_TASK = "multi_skill_task"
    ADMIN_FORCE = "admin_force"
    NO_RAG_AVAILABLE = "no_rag_available"

    # Route to Fallback
    TRAINING_ACTIVE = "training_active"
    AUTO_DURING_TRAINING = "auto_during_training"
    SIMPLE_REQUEST = "simple_request"
    DEFAULT_FALLBACK = "default_fallback"
    RAG_SUFFICIENT = "rag_sufficient"
    COMPRESSED_FITS = "compressed_fits"

    # Queue
    QUEUE_FOR_QUALITY = "queue_for_quality"
    AUTO_SELECTED_PRIMARY = "auto_selected_primary"

    # Reject
    CONTEXT_EXCEEDS_ALL = "context_exceeds_all_models"
    QUEUE_FULL = "queue_full"
    USER_TIMEOUT = "user_timeout"


class UserRole(Enum):
    """User roles for routing decisions."""

    VIEWER = "viewer"
    DEVELOPER = "developer"
    ELEVATED = "elevated"
    ADMIN = "admin"


@dataclass
class RoutingConfig:
    """Configuration for request routing."""

    # Context thresholds (tokens)
    context_threshold: int = 4096  # Above this, prefer primary
    max_tokens_threshold: int = 2048  # Above this, prefer primary

    # Fallback model limits
    fallback_max_context: int = 8192
    fallback_max_tokens: int = 4096

    # Primary model limits
    primary_max_context: int = 4096  # Due to VRAM constraints on 32B model
    primary_max_tokens: int = 4096

    # Complexity detection
    complexity_keywords: List[str] = field(
        default_factory=lambda: [
            "refactor",
            "restructure",
            "migrate",
            "convert entire",
            "rewrite all",
            "full codebase",
            "entire project",
            "architecture",
            "design pattern",
        ]
    )

    # Training mode behavior
    auto_during_training: str = "fallback"  # or "queue"
    allow_explicit_primary_during_training: bool = True

    # Queue settings
    queue_enabled: bool = True
    queue_timeout_seconds: float = 30.0  # Updated: 30s default per requirements

    # Skill/tool detection for agentic tasks
    agentic_skills: List[str] = field(
        default_factory=lambda: [
            "file_read",
            "file_write",
            "file_search",
            "grep_search",
            "run_terminal",
            "git_operations",
            "database_query",
            "web_search",
            "code_analysis",
            "refactoring",
            "test_generation",
            "documentation",
            "deployment",
        ]
    )

    # Thresholds for primary requirement
    multi_skill_threshold: int = 3  # >= 3 skills detected -> prefer primary

    # RAG/history settings
    check_rag_availability: bool = True
    check_history_relevance: bool = True
    rag_similarity_threshold: float = 0.75  # If RAG finds good match, use fallback

    # User role settings
    admin_can_force_primary: bool = True
    elevated_priority_boost: float = 0.2  # Add to complexity score


@dataclass
class RoutingResult:
    """Result of routing decision."""

    decision: RoutingDecision
    reason: RoutingReason
    target_model: Optional[str] = None  # "primary", "fallback"
    queue_position: Optional[int] = None
    estimated_wait_seconds: Optional[float] = None
    complexity_score: float = 0.0
    skills_detected: List[str] = field(default_factory=list)
    rag_available: bool = False
    history_relevant: bool = False
    user_role: Optional[str] = None
    requires_confirmation: bool = False  # For admin force during training
    analysis: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason": self.reason.value,
            "target_model": self.target_model,
            "queue_position": self.queue_position,
            "estimated_wait_seconds": self.estimated_wait_seconds,
            "complexity_score": self.complexity_score,
            "skills_detected": self.skills_detected,
            "rag_available": self.rag_available,
            "history_relevant": self.history_relevant,
            "user_role": self.user_role,
            "requires_confirmation": self.requires_confirmation,
            "analysis": self.analysis,
        }

    def to_ui_response(self) -> Dict[str, Any]:
        """Format for UI display (AG-UI compatible)."""
        response = {"model": self.target_model, "reason": self.reason.value}

        if self.decision == RoutingDecision.QUEUED_FOR_PRIMARY:
            response["queued"] = True
            response["queue_position"] = self.queue_position
            response["estimated_wait_seconds"] = self.estimated_wait_seconds
            response["display"] = (
                f"primary (queued #{self.queue_position}, ~{int(self.estimated_wait_seconds or 0)}s wait)"
            )

        if self.requires_confirmation:
            response["requires_confirmation"] = True
            response["warning"] = (
                "Training is active. Using primary will pause training. Confirm?"
            )

        return response


class RequestRouter:
    """
    Routes inference requests to appropriate model based on context and state.

    Implements sophisticated complexity detection:
    1. Context length analysis
    2. Skill/tool detection for agentic tasks
    3. RAG/history availability check
    4. User role consideration
    5. Prompt compression potential

    During training:
    - Primary is HIDDEN from UI (not selectable)
    - Auto goes through rigorous filtering
    - If auto determines primary needed -> show "primary (queued)" with wait time
    - Admins can force primary with warning and re-auth requirement
    """

    def __init__(
        self,
        config: Optional[RoutingConfig] = None,
        rag_checker: Optional[Any] = None,  # Callback for RAG availability
        history_checker: Optional[Any] = None,  # Callback for history check
    ):
        self.config = config or RoutingConfig()
        self._training_active = False
        self._queue_length = 0
        self._avg_request_time = 15.0  # seconds, updated dynamically

        # External checkers
        self._rag_checker = rag_checker
        self._history_checker = history_checker

        # Compile patterns
        self._complexity_pattern = re.compile(
            "|".join(re.escape(kw) for kw in self.config.complexity_keywords),
            re.IGNORECASE,
        )
        self._skill_patterns = self._build_skill_patterns()

    def _build_skill_patterns(self) -> Dict[str, re.Pattern]:
        """Build regex patterns for skill detection."""
        skill_indicators = {
            "file_read": r"read\s+(file|content)|cat\s+|view\s+file|show\s+me\s+the\s+(file|code)",
            "file_write": r"(write|create|edit|modify|update)\s+(file|code)|save\s+to",
            "file_search": r"(find|search|locate)\s+(file|files)|where\s+is",
            "grep_search": r"(grep|search\s+for|find\s+all|look\s+for).*(in\s+(file|code|project))?",
            "run_terminal": r"(run|execute|terminal|shell|command|bash|script)",
            "git_operations": r"(git|commit|push|pull|branch|merge|rebase|diff)",
            "database_query": r"(database|sql|query|table|select|insert|postgres|redis)",
            "web_search": r"(search\s+(online|web)|browse|fetch\s+url|http)",
            "code_analysis": r"(analyze|review|explain|understand|debug)\s+(code|this|the)",
            "refactoring": r"(refactor|restructure|reorganize|clean\s+up|improve)\s+(code|this)?",
            "test_generation": r"(test|unit\s+test|integration\s+test|write\s+tests)",
            "documentation": r"(document|docstring|readme|comment|explain\s+how)",
            "deployment": r"(deploy|docker|container|kubernetes|k8s|ci.?cd)",
        }
        return {
            skill: re.compile(pattern, re.IGNORECASE)
            for skill, pattern in skill_indicators.items()
        }

    def set_training_active(self, active: bool):
        """Update training state."""
        self._training_active = active
        logger.info(f"RequestRouter: training_active = {active}")

    def set_queue_length(self, length: int):
        """Update queue length for decision making."""
        self._queue_length = length

    def update_avg_request_time(self, new_time: float):
        """Update rolling average request time."""
        self._avg_request_time = (self._avg_request_time * 0.9) + (new_time * 0.1)

    def estimate_wait_time(self, queue_position: int) -> float:
        """Estimate wait time based on queue position."""
        return queue_position * self._avg_request_time

    def analyze_request(
        self,
        messages: list,
        max_tokens: Optional[int] = None,
        model_selection: Optional[str] = None,
        user_role: UserRole = UserRole.DEVELOPER,
        conversation_id: Optional[str] = None,
        force_primary: bool = False,  # Admin override
    ) -> RoutingResult:
        """
        Analyze a request and determine routing with sophisticated filtering.

        Args:
            messages: Chat messages
            max_tokens: Requested max tokens
            model_selection: Explicit model selection ("primary", "fallback", "auto", None)
            user_role: User's role for permissions
            conversation_id: For checking history relevance
            force_primary: Admin force override (requires confirmation)

        Returns:
            RoutingResult with decision, analysis, and UI display info
        """
        # Estimate token counts
        input_tokens = self._estimate_tokens(messages)
        requested_tokens = max_tokens or 1024

        # Extract content for analysis
        content = self._extract_content(messages)

        # Detect skills required
        skills_detected = self._detect_skills(content)

        # Check RAG availability
        rag_available, rag_score = self._check_rag(content, conversation_id)

        # Check history relevance
        history_relevant = self._check_history(conversation_id, content)

        # Calculate comprehensive complexity score
        complexity_score = self._calculate_complexity_v2(
            content=content,
            token_count=input_tokens,
            skills_detected=skills_detected,
            rag_available=rag_available,
            rag_score=rag_score,
            user_role=user_role,
        )

        # Check if prompt can be compressed to fit fallback
        can_compress = self._can_compress_to_fit(content, input_tokens)

        analysis = {
            "input_tokens_estimated": input_tokens,
            "max_tokens_requested": requested_tokens,
            "complexity_score": complexity_score,
            "skills_detected": skills_detected,
            "skills_count": len(skills_detected),
            "rag_available": rag_available,
            "rag_score": rag_score,
            "history_relevant": history_relevant,
            "can_compress": can_compress,
            "training_active": self._training_active,
            "model_selection": model_selection,
            "user_role": user_role.value,
            "queue_length": self._queue_length,
        }

        # === Routing Logic ===

        # Check if context exceeds all models
        if input_tokens > max(
            self.config.primary_max_context, self.config.fallback_max_context
        ):
            if not can_compress:
                return RoutingResult(
                    decision=RoutingDecision.REJECTED,
                    reason=RoutingReason.CONTEXT_EXCEEDS_ALL,
                    complexity_score=complexity_score,
                    skills_detected=skills_detected,
                    user_role=user_role.value,
                    analysis=analysis,
                )

        # Admin force override (with warning during training)
        if force_primary and user_role == UserRole.ADMIN:
            return self._route_admin_force(
                complexity_score, skills_detected, analysis, user_role
            )

        # During training: primary selection is NOT allowed (hidden from UI)
        if self._training_active:
            if model_selection == "primary":
                # This shouldn't happen if UI is correct, but handle it
                return RoutingResult(
                    decision=RoutingDecision.REJECTED,
                    reason=RoutingReason.TRAINING_ACTIVE,
                    target_model="fallback",
                    complexity_score=complexity_score,
                    skills_detected=skills_detected,
                    user_role=user_role.value,
                    analysis={
                        **analysis,
                        "note": "Primary selection disabled during training",
                    },
                )

        # Handle explicit fallback selection
        if model_selection == "fallback":
            return RoutingResult(
                decision=RoutingDecision.FALLBACK,
                reason=RoutingReason.EXPLICIT_SELECTION,
                target_model="fallback",
                complexity_score=complexity_score,
                skills_detected=skills_detected,
                rag_available=rag_available,
                history_relevant=history_relevant,
                user_role=user_role.value,
                analysis=analysis,
            )

        # Handle explicit primary selection (only when NOT training)
        if model_selection == "primary" and not self._training_active:
            return self._route_explicit_primary(
                input_tokens,
                complexity_score,
                skills_detected,
                rag_available,
                history_relevant,
                user_role,
                analysis,
            )

        # Auto-selection with rigorous filtering
        return self._route_auto_rigorous(
            input_tokens,
            requested_tokens,
            complexity_score,
            skills_detected,
            rag_available,
            rag_score,
            history_relevant,
            can_compress,
            user_role,
            analysis,
        )

    def _route_admin_force(
        self,
        complexity_score: float,
        skills_detected: List[str],
        analysis: Dict,
        user_role: UserRole,
    ) -> RoutingResult:
        """Handle admin force primary request."""
        if self._training_active:
            # Require confirmation during training
            queue_position = self._queue_length + 1
            return RoutingResult(
                decision=RoutingDecision.QUEUED_FOR_PRIMARY,
                reason=RoutingReason.ADMIN_FORCE,
                target_model="primary",
                queue_position=queue_position,
                estimated_wait_seconds=self.estimate_wait_time(queue_position),
                complexity_score=complexity_score,
                skills_detected=skills_detected,
                user_role=user_role.value,
                requires_confirmation=True,
                analysis={
                    **analysis,
                    "note": "Admin force - requires confirmation, will pause training",
                },
            )
        else:
            return RoutingResult(
                decision=RoutingDecision.PRIMARY,
                reason=RoutingReason.ADMIN_FORCE,
                target_model="primary",
                complexity_score=complexity_score,
                skills_detected=skills_detected,
                user_role=user_role.value,
                analysis=analysis,
            )

    def _route_explicit_primary(
        self,
        input_tokens: int,
        complexity_score: float,
        skills_detected: List[str],
        rag_available: bool,
        history_relevant: bool,
        user_role: UserRole,
        analysis: Dict,
    ) -> RoutingResult:
        """Handle explicit primary model selection (only when not training)."""
        # Check if primary can handle this
        if input_tokens > self.config.primary_max_context:
            return RoutingResult(
                decision=RoutingDecision.FALLBACK,
                reason=RoutingReason.CONTEXT_TOO_LONG,
                target_model="fallback",
                complexity_score=complexity_score,
                skills_detected=skills_detected,
                rag_available=rag_available,
                history_relevant=history_relevant,
                user_role=user_role.value,
                analysis={
                    **analysis,
                    "note": "Context too long for primary, using fallback",
                },
            )

        # Route to primary (not training)
        return RoutingResult(
            decision=RoutingDecision.PRIMARY,
            reason=RoutingReason.EXPLICIT_SELECTION,
            target_model="primary",
            complexity_score=complexity_score,
            skills_detected=skills_detected,
            rag_available=rag_available,
            history_relevant=history_relevant,
            user_role=user_role.value,
            analysis=analysis,
        )

    def _route_auto_rigorous(
        self,
        input_tokens: int,
        requested_tokens: int,
        complexity_score: float,
        skills_detected: List[str],
        rag_available: bool,
        rag_score: float,
        history_relevant: bool,
        can_compress: bool,
        user_role: UserRole,
        analysis: Dict,
    ) -> RoutingResult:
        """
        Rigorous auto-selection with multiple filtering stages.

        Filtering stages:
        1. Can RAG/history address this? -> Fallback
        2. Can we compress to fit fallback? -> Fallback
        3. Is it simple (low complexity, few skills)? -> Fallback
        4. Context exceeds fallback? -> Queue for primary
        5. High complexity or multi-skill? -> Queue for primary (during training)
        """

        # Stage 1: RAG/History can address this
        if rag_available and rag_score >= self.config.rag_similarity_threshold:
            return RoutingResult(
                decision=RoutingDecision.FALLBACK,
                reason=RoutingReason.RAG_SUFFICIENT,
                target_model="fallback",
                complexity_score=complexity_score,
                skills_detected=skills_detected,
                rag_available=rag_available,
                history_relevant=history_relevant,
                user_role=user_role.value,
                analysis={
                    **analysis,
                    "note": f"RAG found relevant context (score: {rag_score:.2f})",
                },
            )

        # Stage 2: History relevance (user might have poor context management)
        if history_relevant and complexity_score < 0.5:
            return RoutingResult(
                decision=RoutingDecision.FALLBACK,
                reason=RoutingReason.RAG_SUFFICIENT,
                target_model="fallback",
                complexity_score=complexity_score,
                skills_detected=skills_detected,
                rag_available=rag_available,
                history_relevant=history_relevant,
                user_role=user_role.value,
                analysis={
                    **analysis,
                    "note": "Relevant history found, fallback sufficient",
                },
            )

        # Stage 3: Check if fallback can handle with compression
        if input_tokens > self.config.fallback_max_context and can_compress:
            return RoutingResult(
                decision=RoutingDecision.FALLBACK,
                reason=RoutingReason.COMPRESSED_FITS,
                target_model="fallback",
                complexity_score=complexity_score,
                skills_detected=skills_detected,
                rag_available=rag_available,
                history_relevant=history_relevant,
                user_role=user_role.value,
                analysis={
                    **analysis,
                    "note": "Context can be compressed to fit fallback",
                },
            )

        # Stage 4: Simple request detection
        is_simple = (
            complexity_score < 0.4
            and len(skills_detected) < self.config.multi_skill_threshold
            and input_tokens <= self.config.context_threshold
            and requested_tokens <= self.config.max_tokens_threshold
        )

        if is_simple:
            return RoutingResult(
                decision=RoutingDecision.FALLBACK,
                reason=RoutingReason.SIMPLE_REQUEST,
                target_model="fallback",
                complexity_score=complexity_score,
                skills_detected=skills_detected,
                rag_available=rag_available,
                history_relevant=history_relevant,
                user_role=user_role.value,
                analysis=analysis,
            )

        # === Beyond this point, request likely needs primary ===

        # Determine why primary is needed
        needs_primary_reason = self._determine_primary_reason(
            input_tokens, requested_tokens, complexity_score, skills_detected
        )

        # During training: queue for primary with wait time
        if self._training_active:
            queue_position = self._queue_length + 1
            return RoutingResult(
                decision=RoutingDecision.QUEUED_FOR_PRIMARY,
                reason=RoutingReason.AUTO_SELECTED_PRIMARY,
                target_model="primary",
                queue_position=queue_position,
                estimated_wait_seconds=self.estimate_wait_time(queue_position),
                complexity_score=complexity_score,
                skills_detected=skills_detected,
                rag_available=rag_available,
                history_relevant=history_relevant,
                user_role=user_role.value,
                analysis={
                    **analysis,
                    "primary_reason": needs_primary_reason.value,
                    "note": "Auto-routing determined primary needed, queuing",
                },
            )

        # Not training: route directly to primary
        return RoutingResult(
            decision=RoutingDecision.PRIMARY,
            reason=needs_primary_reason,
            target_model="primary",
            complexity_score=complexity_score,
            skills_detected=skills_detected,
            rag_available=rag_available,
            history_relevant=history_relevant,
            user_role=user_role.value,
            analysis=analysis,
        )

    def _determine_primary_reason(
        self,
        input_tokens: int,
        requested_tokens: int,
        complexity_score: float,
        skills_detected: List[str],
    ) -> RoutingReason:
        """Determine the main reason primary is needed."""
        if input_tokens > self.config.fallback_max_context:
            return RoutingReason.CONTEXT_TOO_LONG
        if len(skills_detected) >= self.config.multi_skill_threshold:
            return RoutingReason.MULTI_SKILL_TASK
        if complexity_score >= 0.6:
            return RoutingReason.COMPLEXITY_DETECTED
        if requested_tokens >= self.config.max_tokens_threshold:
            return RoutingReason.MAX_TOKENS_HIGH
        return RoutingReason.COMPLEXITY_DETECTED

    def _estimate_tokens(self, messages: list) -> int:
        """Estimate token count from messages."""
        total_chars = 0
        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if isinstance(content, str):
                    total_chars += len(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and "text" in part:
                            total_chars += len(part["text"])
            elif hasattr(msg, "content"):
                total_chars += len(str(msg.content))

        # Rough estimate: ~4 chars per token
        return total_chars // 4

    def _extract_content(self, messages: list) -> str:
        """Extract text content from messages."""
        parts = []
        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and "text" in part:
                            parts.append(part["text"])
            elif hasattr(msg, "content"):
                parts.append(str(msg.content))
        return " ".join(parts)

    def _detect_skills(self, content: str) -> List[str]:
        """Detect agentic skills/tools required for the task."""
        detected = []
        for skill, pattern in self._skill_patterns.items():
            if pattern.search(content):
                detected.append(skill)
        return detected

    def _check_rag(
        self, content: str, conversation_id: Optional[str]
    ) -> Tuple[bool, float]:
        """
        Check if RAG can provide relevant context.

        Returns:
            Tuple of (has_relevant_content, similarity_score)
        """
        if not self._rag_checker or not self.config.check_rag_availability:
            return False, 0.0

        try:
            # This would call the actual RAG system
            # For now, we return placeholder
            # In production: result = await self._rag_checker(content, conversation_id)
            return False, 0.0
        except Exception as e:
            logger.warning(f"RAG check failed: {e}")
            return False, 0.0

    def _check_history(self, conversation_id: Optional[str], content: str) -> bool:
        """
        Check if conversation history has relevant context.

        This helps detect users with poor context management who might
        be re-asking questions already answered in their chat history.
        """
        if not self._history_checker or not self.config.check_history_relevance:
            return False
        if not conversation_id:
            return False

        try:
            # This would call the actual history system
            # For now, we return placeholder
            # In production: result = await self._history_checker(conversation_id, content)
            return False
        except Exception as e:
            logger.warning(f"History check failed: {e}")
            return False

    def _can_compress_to_fit(self, content: str, current_tokens: int) -> bool:
        """
        Check if the prompt can be compressed/vectorized to fit fallback model.

        Compression techniques:
        - Remove redundant whitespace
        - Summarize repeated patterns
        - Extract key code snippets only
        - Use references to RAG instead of full content
        """
        if current_tokens <= self.config.fallback_max_context:
            return True  # Already fits

        # Estimate compression potential
        # Look for patterns that compress well
        compression_indicators = [
            len(re.findall(r"\n\s*\n", content)),  # Multiple blank lines
            len(re.findall(r"```[\s\S]*?```", content)),  # Code blocks (can summarize)
            content.count("    "),  # Indentation (can normalize)
            len(re.findall(r"(.{20,})\1+", content)),  # Repeated strings
        ]

        # Rough estimate: each indicator suggests ~10% compression possible
        compression_potential = min(0.5, sum(compression_indicators) * 0.05)
        compressed_tokens = int(current_tokens * (1 - compression_potential))

        return compressed_tokens <= self.config.fallback_max_context

    def _calculate_complexity_v2(
        self,
        content: str,
        token_count: int,
        skills_detected: List[str],
        rag_available: bool,
        rag_score: float,
        user_role: UserRole,
    ) -> float:
        """
        Calculate comprehensive complexity score (0-1).

        Factors:
        - Keyword matches (refactor, migrate, etc.)
        - Token count
        - Number of skills/tools required
        - Multi-file indicators
        - RAG availability (reduces complexity if available)
        - User role (elevated users get slight boost)
        """
        score = 0.0

        # Keyword matches (max 0.3)
        matches = self._complexity_pattern.findall(content)
        if matches:
            score += min(0.3, len(matches) * 0.1)

        # Token count contribution (max 0.2)
        if token_count > 3000:
            score += 0.2
        elif token_count > 2000:
            score += 0.15
        elif token_count > 1000:
            score += 0.1

        # Skill count contribution (max 0.3)
        skill_count = len(skills_detected)
        if skill_count >= 5:
            score += 0.3
        elif skill_count >= 3:
            score += 0.2
        elif skill_count >= 2:
            score += 0.1

        # Multi-file indicators (max 0.15)
        file_patterns = re.findall(
            r"[\w/]+\.(py|js|ts|go|rs|java|cpp|c|h)[\b\s]", content
        )
        if len(file_patterns) >= 5:
            score += 0.15
        elif len(file_patterns) >= 3:
            score += 0.1

        # Code block count (max 0.05)
        code_blocks = content.count("```")
        if code_blocks >= 6:
            score += 0.05

        # RAG availability REDUCES complexity (we can offload to RAG)
        if rag_available and rag_score > 0.5:
            score -= min(0.2, rag_score * 0.25)

        # User role adjustment
        if user_role in (UserRole.ELEVATED, UserRole.ADMIN):
            score += self.config.elevated_priority_boost

        return max(0.0, min(1.0, score))

    def _calculate_complexity(self, content: str, token_count: int) -> float:
        """Legacy complexity calculation for backward compatibility."""
        return self._calculate_complexity_v2(
            content=content,
            token_count=token_count,
            skills_detected=[],
            rag_available=False,
            rag_score=0.0,
            user_role=UserRole.DEVELOPER,
        )

    def get_available_models(self) -> Dict[str, Any]:
        """
        Get models available for selection in current state.

        During training:
        - Primary is HIDDEN
        - Auto and Fallback are selectable
        - Auto may show "primary (queued)" after analysis
        """
        if self._training_active:
            return {
                "available": ["auto", "fallback"],
                "hidden": ["primary"],
                "default": "auto",
                "note": "Training active. Primary model temporarily unavailable.",
                "auto_behavior": "Routes through rigorous filtering. May queue for primary if necessary.",
            }
        else:
            return {
                "available": ["auto", "primary", "fallback"],
                "hidden": [],
                "default": "auto",
                "note": None,
                "auto_behavior": "Intelligent routing based on request complexity.",
            }

    def get_config(self) -> Dict[str, Any]:
        """Get current routing configuration."""
        return {
            "context_threshold": self.config.context_threshold,
            "max_tokens_threshold": self.config.max_tokens_threshold,
            "fallback_max_context": self.config.fallback_max_context,
            "primary_max_context": self.config.primary_max_context,
            "complexity_keywords": self.config.complexity_keywords,
            "agentic_skills": self.config.agentic_skills,
            "multi_skill_threshold": self.config.multi_skill_threshold,
            "auto_during_training": self.config.auto_during_training,
            "admin_can_force_primary": self.config.admin_can_force_primary,
            "queue_enabled": self.config.queue_enabled,
            "queue_timeout_seconds": self.config.queue_timeout_seconds,
            "training_active": self._training_active,
            "current_queue_length": self._queue_length,
            "avg_request_time": self._avg_request_time,
        }

    def update_config(self, updates: Dict[str, Any]) -> None:
        """Update routing configuration."""
        for key, value in updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info(f"RequestRouter config updated: {key} = {value}")

        # Rebuild patterns if keywords changed
        if "complexity_keywords" in updates:
            self._complexity_pattern = re.compile(
                "|".join(re.escape(kw) for kw in self.config.complexity_keywords),
                re.IGNORECASE,
            )
