"""
Deterministic Hybrid Router - P1

Routes requests by intent + attachments with structured logging.
Wraps model_router.ModelRouter with:
- Deterministic rules (attachment-first, then intent keywords)
- Clear fallback behavior
- Structured JSON logs for every routing decision
"""

import logging
import json
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from .model_router import ModelRouter, ModelSelection, ModelType, TrainingStatus

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    """Structured log entry for a routing decision."""

    request_id: str
    timestamp: float
    intent: str  # "coding" | "vision" | "image_gen" | "general"
    has_attachments: bool
    attachment_types: List[str]
    selected_model: str
    model_type: str
    gpu: str
    confidence: float
    reasoning: str
    training_active: bool
    fallback_used: bool
    decision_time_ms: float


class HybridRouter:
    """Deterministic hybrid router with structured logging.

    Routing priority (strict order):
    1. Image attachments present → vision model (always)
    2. Vision keywords + no attachments → vision model
    3. Image generation keywords → z-image (or fallback if training)
    4. Code keywords → coding model (or fallback if training)
    5. Default → coding model (most capable for general)

    Fallback behavior:
    - If RTX 3090 training active: all GPU-1 tasks → Qwen3-VL on GPU-0
    - If model unreachable: return error with clear message
    - If ambiguous intent: use coding model (highest general capability)
    """

    def __init__(self):
        self._router = ModelRouter()
        self._request_counter = 0

    def _classify_intent(
        self,
        prompt: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Classify request intent deterministically.

        Returns one of: "vision", "coding", "image_gen", "general"
        """
        task = self._router.detect_task_type(prompt, attachments)

        # Strict priority: attachments beat keywords
        if task["has_image_attachment"]:
            return "vision"

        # Then score-based with thresholds (aligned with model_router)
        if task["vision_score"] > 0.5:
            return "vision"
        if task["image_gen_score"] > 0.3:
            return "image_gen"
        if task["code_score"] > 0.3:
            return "coding"

        return "general"

    def _extract_attachment_types(
        self, attachments: Optional[List[Dict[str, Any]]]
    ) -> List[str]:
        """Extract MIME types from attachments."""
        if not attachments:
            return []
        return [a.get("mime_type", a.get("type", "unknown")) for a in attachments]

    def route(
        self,
        prompt: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
        request_id: Optional[str] = None,
    ) -> ModelSelection:
        """Route a request to the appropriate model.

        Args:
            prompt: User's text prompt
            attachments: Optional list of attachments
            request_id: Optional request ID for log correlation

        Returns:
            ModelSelection with model details
        """
        start = time.monotonic()
        self._request_counter += 1

        if not request_id:
            request_id = f"route-{self._request_counter}"

        # Step 1: Classify intent
        intent = self._classify_intent(prompt, attachments)

        # Step 2: Check training status
        training_active = TrainingStatus.is_training_active()

        # Step 3: Route via underlying router (it handles training fallback)
        selection = self._router.select_model(prompt, attachments, check_training=True)

        # Step 4: Determine if fallback was used
        fallback_used = bool(
            selection.parameters.get("_training_fallback")
            or selection.parameters.get("_training_blocked")
        )

        # Step 5: Build structured log
        decision_time_ms = (time.monotonic() - start) * 1000
        decision = RoutingDecision(
            request_id=request_id,
            timestamp=time.time(),
            intent=intent,
            has_attachments=bool(attachments),
            attachment_types=self._extract_attachment_types(attachments),
            selected_model=selection.model_name,
            model_type=selection.model_type.value,
            gpu=selection.gpu,
            confidence=selection.confidence,
            reasoning=selection.reasoning,
            training_active=training_active,
            fallback_used=fallback_used,
            decision_time_ms=round(decision_time_ms, 2),
        )

        # Structured JSON log
        logger.info(
            "routing_decision",
            extra={"routing": asdict(decision)},
        )

        # Also log human-readable summary
        logger.info(
            f"🔀 Route [{request_id}]: intent={intent} → "
            f"{selection.model_type.value} (gpu={selection.gpu}, "
            f"conf={selection.confidence:.2f}, "
            f"fallback={fallback_used}, "
            f"time={decision_time_ms:.1f}ms)"
        )

        return selection

    def route_with_plan(
        self,
        prompt: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Route with optional multi-model plan.

        Returns:
            {
                "primary": ModelSelection,
                "multi_model_plan": Optional[MultiModelPlan],
                "intent": str,
                "training_active": bool,
            }
        """
        primary = self.route(prompt, attachments, request_id)
        plan = self._router.plan_multi_model(prompt, attachments)

        return {
            "primary": primary,
            "multi_model_plan": plan,
            "intent": self._classify_intent(prompt, attachments),
            "training_active": TrainingStatus.is_training_active(),
        }


# Global singleton
_hybrid_router = None


def get_hybrid_router() -> HybridRouter:
    """Get or create the global hybrid router."""
    global _hybrid_router
    if _hybrid_router is None:
        _hybrid_router = HybridRouter()
    return _hybrid_router
