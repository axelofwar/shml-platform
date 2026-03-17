"""Deterministic Hybrid Router — T5.1 + T5.2 + T8.4

Four-tier routing with cloud failover and Postgres handoff logging.

Tier 0 (Nano):     Fast domain-specialized shl-nano model (T8.4) — optional
Tier 1 (Local):    All requests go here first → local Qwen/Nemotron
Tier 2 (Failover): Escalate when local model exceeds failure/latency threshold
Tier 3 (Evolution): Every handoff logged to Postgres for skill evolution signal

Routing intent priority (strict order):
1. Image attachments present → vision model (always)
2. Vision keywords + no attachments → vision model
3. Image generation keywords → z-image (or fallback if training)
4. Code keywords → coding model (or fallback if training)
5. Default → coding model (most capable for general)
"""

import asyncio
import collections
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

import urllib.request
import urllib.error
import json as _json

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .config import settings
from .model_router import ModelRouter, ModelSelection, TrainingStatus

logger = logging.getLogger(__name__)


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class RoutingDecision:
    """Structured log entry for a routing decision."""

    request_id: str
    timestamp: float
    intent: str          # "coding" | "vision" | "image_gen" | "general"
    has_attachments: bool
    attachment_types: List[str]
    selected_model: str
    model_type: str
    gpu: str
    confidence: float
    reasoning: str
    training_active: bool
    fallback_used: bool      # local training fallback (GPU contention)
    cloud_handoff: bool      # escalated to cloud tier
    nano_used: bool          # served by tier-0 shl-nano (T8.4)
    handoff_reason: str      # "" | "failure_threshold" | "latency_threshold"
    consecutive_failures: int
    observed_latency_ms: float
    decision_time_ms: float


@dataclass
class HandoffEvent:
    """Postgres row for a cloud handoff event — T5.2."""

    request_id: str
    timestamp: datetime
    model_name: str
    reason: str           # "failure_threshold" | "latency_threshold"
    consecutive_failures: int
    observed_latency_ms: float
    cloud_model: str
    intent: str


# ============================================================================
# Failover Policy — T5.1
# ============================================================================

_LATENCY_WINDOW = 20  # rolling window size for latency mean


class FailoverPolicy:
    """Per-model failure and latency tracking with cloud escalation.

    Rules:
    - After CLOUD_FAILOVER_THRESHOLD consecutive failures → hand off to cloud
    - When rolling mean latency > CLOUD_LATENCY_THRESHOLD_SECONDS → hand off
    - Failure count resets on next successful response (caller calls record_success)
    - Silently returns None (stays local) when CLOUD_API_KEY not configured
    """

    def __init__(self):
        self._failures: Dict[str, int] = collections.defaultdict(int)
        self._latencies: Dict[str, Deque[float]] = collections.defaultdict(
            lambda: collections.deque(maxlen=_LATENCY_WINDOW)
        )

    def record_failure(self, model_name: str) -> int:
        self._failures[model_name] += 1
        return self._failures[model_name]

    def record_success(self, model_name: str, latency_ms: float) -> None:
        self._failures[model_name] = 0
        self._latencies[model_name].append(latency_ms)

    def consecutive_failures(self, model_name: str) -> int:
        return self._failures[model_name]

    def mean_latency_ms(self, model_name: str) -> float:
        samples = self._latencies[model_name]
        return sum(samples) / len(samples) if samples else 0.0

    def should_escalate(self, model_name: str) -> tuple[bool, str]:
        """Return (escalate: bool, reason: str)."""
        n_failures = self._failures[model_name]
        if n_failures >= settings.CLOUD_FAILOVER_THRESHOLD:
            return True, "failure_threshold"
        mean_ms = self.mean_latency_ms(model_name)
        threshold_ms = settings.CLOUD_LATENCY_THRESHOLD_SECONDS * 1000
        if mean_ms > threshold_ms:
            return True, "latency_threshold"
        return False, ""

    def cloud_selection(self, original: ModelSelection) -> Optional[ModelSelection]:
        """Return cloud-routed ModelSelection, or None if cloud not configured.

        When NemoClaw cloud profile is enabled, routes calls through OpenShell gateway
        so every cloud inference call is policy-governed and audited (nimcloud profile).
        Falls back to direct cloud endpoint when NemoClaw is not available.
        """
        # Tier 2a: NemoClaw-mediated cloud escalation (preferred)
        # OpenShell intercepts the call, audits it, routes to NVIDIA cloud
        if settings.NEMOCLAW_CLOUD_PROFILE_ENABLED and settings.NEMOCLAW_GATEWAY_URL:
            return ModelSelection(
                model_name=settings.CLOUD_FALLBACK_MODEL,
                model_type=original.model_type,
                gpu="cloud-nemoclaw",
                confidence=0.75,
                reasoning=f"NemoClaw cloud failover (nimcloud profile) from {original.model_name}",
                parameters={
                    "_cloud_fallback": True,
                    "_nemoclaw_profile": "nimcloud",
                    # OpenShell gateway intercepts at /v1/chat/completions and routes to NVIDIA cloud
                    "api_base": f"{settings.NEMOCLAW_GATEWAY_URL}/v1",
                    "api_key": settings.CLOUD_API_KEY or "nemoclaw-routed",
                },
            )

        # Tier 2b: Direct cloud endpoint (NemoClaw not available / not configured)
        if not settings.CLOUD_API_KEY or not settings.CLOUD_FALLBACK_URL:
            return None
        return ModelSelection(
            model_name=settings.CLOUD_FALLBACK_MODEL,
            model_type=original.model_type,
            gpu="cloud",
            confidence=0.75,
            reasoning=f"Cloud failover from {original.model_name}",
            parameters={
                "_cloud_fallback": True,
                "api_base": settings.CLOUD_FALLBACK_URL,
                "api_key": settings.CLOUD_API_KEY,
            },
        )


# ============================================================================
# Postgres Handoff Logger — T5.2
# ============================================================================

_CREATE_HANDOFF_TABLE = """
CREATE TABLE IF NOT EXISTS handoff_log (
    id          BIGSERIAL PRIMARY KEY,
    request_id  TEXT        NOT NULL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_name  TEXT        NOT NULL,
    reason      TEXT        NOT NULL,
    consec_fail INT         NOT NULL DEFAULT 0,
    latency_ms  REAL        NOT NULL DEFAULT 0,
    cloud_model TEXT        NOT NULL,
    intent      TEXT        NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_handoff_ts ON handoff_log (ts);
"""

_INSERT_HANDOFF = text("""
    INSERT INTO handoff_log
        (request_id, ts, model_name, reason, consec_fail, latency_ms, cloud_model, intent)
    VALUES
        (:request_id, :ts, :model_name, :reason, :consec_fail, :latency_ms, :cloud_model, :intent)
""")


async def _ensure_handoff_table(session) -> None:
    for stmt in _CREATE_HANDOFF_TABLE.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            await session.execute(text(stmt))
    await session.commit()


async def log_handoff_to_db(event: HandoffEvent, session) -> None:
    """Write a handoff event to Postgres. Silently swallows errors."""
    try:
        await _ensure_handoff_table(session)
        await session.execute(
            _INSERT_HANDOFF,
            {
                "request_id": event.request_id,
                "ts": event.timestamp,
                "model_name": event.model_name,
                "reason": event.reason,
                "consec_fail": event.consecutive_failures,
                "latency_ms": event.observed_latency_ms,
                "cloud_model": event.cloud_model,
                "intent": event.intent,
            },
        )
        await session.commit()
    except SQLAlchemyError as exc:
        logger.warning(f"[handoff_log] Postgres write failed (non-fatal): {exc}")


class HybridRouter:
    """Deterministic hybrid router with cloud failover and handoff logging.

    Three-tier routing (T5.1):
    - Tier 1 Local:    All requests → local Qwen/Nemotron (normal path)
    - Tier 2 Cloud:    Escalated after N failures OR latency > threshold
    - Tier 3 Evolution: Every handoff logged to Postgres (T5.2)

    Call record_outcome() after each model response to keep failure/latency
    state accurate.
    """

    def __init__(self):
        self._router = ModelRouter()
        self._failover = FailoverPolicy()
        self._request_counter = 0

    # ── intent classification ──────────────────────────────────────────────

    def _classify_intent(
        self,
        prompt: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        task = self._router.detect_task_type(prompt, attachments)
        if task["has_image_attachment"]:
            return "vision"
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
        if not attachments:
            return []
        return [a.get("mime_type", a.get("type", "unknown")) for a in attachments]

    # ── Tier 0: shl-nano (T8.4) ───────────────────────────────────────────

    def _try_nano(
        self,
        prompt: str,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        """Attempt Tier-0 response from the shl-nano endpoint.

        Returns:
            The assistant's reply string when nano fires confidently,
            or None to fall through to Tier-1.

        Rules:
        - Skipped silently when NANO_ENDPOINT is not configured.
        - Skipped for vision/image_gen intents (nano is text-only).
        - Falls through if latency > NANO_LATENCY_THRESHOLD_MS.
        - Falls through if response confidence < NANO_CONFIDENCE_THRESHOLD.
        - All errors are non-fatal — caller continues to Tier-1.
        """
        endpoint = settings.NANO_ENDPOINT
        if not endpoint:
            return None

        payload = {
            "model": "shl-nano",
            "messages": messages or [{"role": "user", "content": prompt}],
            "max_tokens": 512,
            "temperature": 0.3,
        }

        t0 = time.monotonic()
        try:
            req = urllib.request.Request(
                f"{endpoint}/v1/chat/completions",
                data=_json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            timeout_s = settings.NANO_LATENCY_THRESHOLD_MS / 1000 + 0.5
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = _json.loads(resp.read())
        except (urllib.error.URLError, OSError) as exc:
            logger.debug(f"[nano] endpoint unreachable ({exc}) — skipping")
            return None
        except Exception as exc:
            logger.debug(f"[nano] unexpected error ({exc}) — skipping")
            return None

        latency_ms = (time.monotonic() - t0) * 1000
        if latency_ms > settings.NANO_LATENCY_THRESHOLD_MS:
            logger.info(
                f"[nano] latency {latency_ms:.0f}ms > "
                f"{settings.NANO_LATENCY_THRESHOLD_MS:.0f}ms threshold — fallthrough"
            )
            return None

        # Check confidence extension field
        confidence = float(data.get("nano_confidence", 1.0))
        if confidence < settings.NANO_CONFIDENCE_THRESHOLD:
            logger.info(
                f"[nano] confidence {confidence:.3f} < "
                f"{settings.NANO_CONFIDENCE_THRESHOLD:.3f} — fallthrough"
            )
            return None

        choices = data.get("choices", [])
        if not choices:
            return None

        finish_reason = choices[0].get("finish_reason", "stop")
        if finish_reason == "low_confidence":
            logger.info("[nano] server signalled low_confidence — fallthrough")
            return None

        content = choices[0].get("message", {}).get("content", "")
        if not content:
            return None

        logger.info(
            f"⚡ Nano Tier-0: conf={confidence:.3f} "
            f"lat={latency_ms:.0f}ms len={len(content)}"
        )
        return content

    # ── outcome feedback (call after model responds) ───────────────────────

    def record_outcome(
        self,
        model_name: str,
        success: bool,
        latency_ms: float = 0.0,
    ) -> None:
        """Update failure/latency state. Call after every model response."""
        if success:
            self._failover.record_success(model_name, latency_ms)
        else:
            self._failover.record_failure(model_name)

    # ── routing ───────────────────────────────────────────────────────────

    def route(
        self,
        prompt: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
        request_id: Optional[str] = None,
        db_session=None,
    ) -> ModelSelection:
        """Route through the three-tier policy.

        Args:
            prompt: User's text prompt.
            attachments: Optional file attachments.
            request_id: Optional ID for log correlation.
            db_session: Optional async SQLAlchemy session — enables T5.2
                        Postgres handoff logging when cloud escalation fires.

        Returns:
            ModelSelection (may point to cloud if local escalated).
        """
        start = time.monotonic()
        self._request_counter += 1
        if not request_id:
            request_id = f"route-{self._request_counter}"

        # ── Tier 0: shl-nano (T8.4) — fast domain nano-model ──────────────
        intent = self._classify_intent(prompt, attachments)
        # Only attempt nano for text-only general/coding — skip vision/image_gen
        if intent not in ("vision", "image_gen") and not attachments:
            nano_reply = self._try_nano(prompt)
            if nano_reply is not None:
                # nano handled it — build a synthetic ModelSelection and return
                # Use a temporary local ModelRouter selection to get a valid model_type
                _tmp_sel = self._router.select_model(prompt, attachments, check_training=False)
                nano_selection = ModelSelection(
                    model_name="shl-nano",
                    model_type=_tmp_sel.model_type,
                    gpu="1",
                    confidence=0.98,
                    reasoning="Tier-0 shl-nano fast path (T8.4)",
                    parameters={"_nano_reply": nano_reply},
                )
                decision_time_ms = (time.monotonic() - start) * 1000
                decision = RoutingDecision(
                    request_id=request_id,
                    timestamp=time.time(),
                    intent=intent,
                    has_attachments=bool(attachments),
                    attachment_types=self._extract_attachment_types(attachments),
                    selected_model="shl-nano",
                    model_type=_tmp_sel.model_type.value,
                    gpu="1",
                    confidence=0.98,
                    reasoning="Tier-0 shl-nano fast path",
                    training_active=TrainingStatus.is_training_active(),
                    fallback_used=False,
                    cloud_handoff=False,
                    nano_used=True,
                    handoff_reason="",
                    consecutive_failures=0,
                    observed_latency_ms=0.0,
                    decision_time_ms=round(decision_time_ms, 2),
                )
                logger.info("routing_decision", extra={"routing": asdict(decision)})
                return nano_selection

        # ── Tier 1: local routing ──────────────────────────────────────────
        training_active = TrainingStatus.is_training_active()
        selection = self._router.select_model(prompt, attachments, check_training=True)

        local_fallback = bool(
            selection.parameters.get("_training_fallback")
            or selection.parameters.get("_training_blocked")
        )

        # ── Tier 2: cloud escalation check ────────────────────────────────
        should_escalate, handoff_reason = self._failover.should_escalate(
            selection.model_name
        )
        cloud_handoff = False

        if should_escalate:
            cloud_sel = self._failover.cloud_selection(selection)
            if cloud_sel:
                cloud_handoff = True
                logger.warning(
                    f"☁️  Cloud escalation [{request_id}]: "
                    f"model={selection.model_name}, reason={handoff_reason}, "
                    f"failures={self._failover.consecutive_failures(selection.model_name)}, "
                    f"latency_mean={self._failover.mean_latency_ms(selection.model_name):.0f}ms"
                )
                # ── Tier 3: log to Postgres ────────────────────────────────
                if db_session is not None:
                    event = HandoffEvent(
                        request_id=request_id,
                        timestamp=datetime.utcnow(),
                        model_name=selection.model_name,
                        reason=handoff_reason,
                        consecutive_failures=self._failover.consecutive_failures(
                            selection.model_name
                        ),
                        observed_latency_ms=self._failover.mean_latency_ms(
                            selection.model_name
                        ),
                        cloud_model=settings.CLOUD_FALLBACK_MODEL,
                        intent=intent,
                    )
                    try:
                        loop = asyncio.get_event_loop()
                        loop.create_task(log_handoff_to_db(event, db_session))
                    except RuntimeError:
                        pass  # No event loop in sync context
                selection = cloud_sel
            else:
                logger.info(
                    f"[T5.1] Escalation triggered but CLOUD_API_KEY not set — "
                    f"staying local (model={selection.model_name}, reason={handoff_reason})"
                )

        # ── Build structured log ───────────────────────────────────────────
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
            fallback_used=local_fallback,
            cloud_handoff=cloud_handoff,
            nano_used=False,
            handoff_reason=handoff_reason if cloud_handoff else "",
            consecutive_failures=self._failover.consecutive_failures(
                selection.model_name
            ),
            observed_latency_ms=round(
                self._failover.mean_latency_ms(selection.model_name), 1
            ),
            decision_time_ms=round(decision_time_ms, 2),
        )

        logger.info("routing_decision", extra={"routing": asdict(decision)})
        logger.info(
            f"🔀 Route [{request_id}]: intent={intent} → "
            f"{selection.model_type.value} (gpu={selection.gpu}, "
            f"conf={selection.confidence:.2f}, "
            f"local_fallback={local_fallback}, cloud_handoff={cloud_handoff}, "
            f"time={decision_time_ms:.1f}ms)"
        )

        return selection

    def route_with_plan(
        self,
        prompt: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
        request_id: Optional[str] = None,
        db_session=None,
    ) -> Dict[str, Any]:
        """Route with optional multi-model plan."""
        primary = self.route(prompt, attachments, request_id, db_session)
        plan = self._router.plan_multi_model(prompt, attachments)
        return {
            "primary": primary,
            "multi_model_plan": plan,
            "intent": self._classify_intent(prompt, attachments),
            "training_active": TrainingStatus.is_training_active(),
        }

    def emit_metrics(self, decision: RoutingDecision) -> None:
        """Emit routing metrics to Prometheus if available."""
        try:
            from prometheus_client import Counter
            _route_total = Counter(
                "agent_routing_decisions_total",
                "Routing decisions by intent and tier",
                ["intent", "tier"],
            )
            tier = (
                "nano"           if decision.nano_used
                else "cloud"     if decision.cloud_handoff
                else "local_fallback" if decision.fallback_used
                else "local"
            )
            _route_total.labels(intent=decision.intent, tier=tier).inc()
        except Exception:
            pass


# ============================================================================
# Global singleton
# ============================================================================

_hybrid_router: Optional[HybridRouter] = None


def get_hybrid_router() -> HybridRouter:
    """Get or create the global hybrid router."""
    global _hybrid_router
    if _hybrid_router is None:
        _hybrid_router = HybridRouter()
    return _hybrid_router
