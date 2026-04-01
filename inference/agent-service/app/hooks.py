"""
Lifecycle Hook Bus — Pattern 41 (free-code hooks.ts).

25 event types spanning the full agent lifecycle. Hooks are async-capable
callables registered per event type. A hook that raises HookBlocked halts
the current operation (analogous to free-code's process.exit(2) pattern).
A hook that returns immediately without raising is treated as "background"
(analogous to free-code's {"async":true} first-line annotation).

Usage:
    from .hooks import get_hook_bus, HookEventType, HookBlocked

    bus = get_hook_bus()

    # Register a blocking hook
    async def on_plan_ready(event: HookEvent) -> None:
        if event.data.get("file_count", 0) > 20:
            raise HookBlocked("Plan exceeds 20-file safety limit")
    bus.register(HookEventType.PLAN_READY, on_plan_ready)

    # Emit (propagates HookBlocked if any handler raises it)
    await bus.emit(HookEventType.PLAN_READY, issue_iid=12, file_count=5)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Union

logger = logging.getLogger(__name__)


# ── Event types ────────────────────────────────────────────────────────────────


class HookEventType(str, Enum):
    # Session lifecycle (2)
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    # Issue lifecycle (5)
    ISSUE_PICKED = "issue_picked"
    ISSUE_SKIPPED = "issue_skipped"
    ISSUE_COMPLETE = "issue_complete"
    ISSUE_FAILED = "issue_failed"
    ISSUE_NO_QUEUE = "issue_no_queue"
    # Planning (3)
    PLAN_START = "plan_start"
    PLAN_READY = "plan_ready"
    PLAN_NUDGE = "plan_nudge"          # Pattern 31: missing tests warning
    # Build (5)
    BUILD_START = "build_start"
    BUILD_COMPLETE = "build_complete"
    BUILD_FAILED = "build_failed"
    BRANCH_LOCKED = "branch_locked"    # Pattern 33: lock acquired
    BRANCH_LOCK_CONFLICT = "branch_lock_conflict"  # Pattern 33: blocked by another agent
    # Test (3)
    TEST_START = "test_start"
    TEST_PASSED = "test_passed"
    TEST_FAILED = "test_failed"
    # Review (4)
    REVIEW_START = "review_start"
    REVIEW_PASSED = "review_passed"
    REVIEW_BLOCKED = "review_blocked"
    REVIEW_DENIAL = "review_denial"    # Pattern 38: consecutive denial counter
    # Gate (2)
    AUTO_MERGE = "auto_merge"
    READY_FOR_REVIEW = "ready_for_review"
    # Control flow (5)
    AWAITING_HUMAN = "awaiting_human"         # Pattern 38: 3+ consecutive denials
    CIRCUIT_BREAKER = "circuit_breaker"       # circuit breaker tripped
    COMPLEXITY_GRADUATED = "complexity_graduated"
    BACKOFF_STARTED = "backoff_started"
    GPU_CONTENTION = "gpu_contention"
    # Learning (2)
    LEARNING_COMPLETE = "learning_complete"
    MEMORY_RECORDED = "memory_recorded"       # Pattern 36: entry written to memory store


# ── Domain types ───────────────────────────────────────────────────────────────


HookCallback = Callable[["HookEvent"], Union[None, Awaitable[None]]]


@dataclass
class HookEvent:
    event_type: HookEventType
    data: dict[str, Any] = field(default_factory=dict)


class HookBlocked(Exception):
    """Raised by a hook callback to block the current agent operation.

    Analogous to exiting with code 2 in free-code hooks.ts — signals that
    the operation must not continue.  AgentLoop catches this and transitions
    to AWAITING_HUMAN or logs the block as a non-fatal refusal.
    """


# ── HookBus ────────────────────────────────────────────────────────────────────


class HookBus:
    """Event bus for agent lifecycle hooks (Pattern 41).

    Hooks are registered per event type and called on emit().
    Async callbacks are awaited. Sync callbacks are called directly.
    Exceptions from hooks are swallowed and logged *unless* they are
    HookBlocked, which propagates to the caller.
    """

    def __init__(self) -> None:
        self._hooks: dict[HookEventType, list[HookCallback]] = {}

    def register(self, event_type: HookEventType, callback: HookCallback) -> None:
        """Register a callback for a lifecycle event type."""
        self._hooks.setdefault(event_type, []).append(callback)

    def unregister(self, event_type: HookEventType, callback: HookCallback) -> None:
        """Deregister a previously registered callback."""
        handlers = self._hooks.get(event_type, [])
        try:
            handlers.remove(callback)
        except ValueError:
            pass

    async def emit(self, event_type: HookEventType, **data: Any) -> None:
        """Emit a lifecycle event to all registered handlers.

        Propagates HookBlocked immediately if any handler raises it.
        All other handler exceptions are logged and suppressed so that a
        broken hook never crashes the main agent loop.
        """
        event = HookEvent(event_type=event_type, data=data)
        handlers = list(self._hooks.get(event_type, []))
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except HookBlocked:
                logger.warning(
                    "HookBlocked raised for event %s — blocking operation",
                    event_type.value,
                )
                raise
            except Exception as exc:
                logger.warning(
                    "Hook error on %s (handler=%s): %s",
                    event_type.value,
                    getattr(handler, "__name__", repr(handler)),
                    exc,
                )

    def listener_count(self, event_type: HookEventType) -> int:
        """Return the number of registered listeners for an event type."""
        return len(self._hooks.get(event_type, []))


# ── Module-level singleton ─────────────────────────────────────────────────────

_bus: Optional[HookBus] = None


def get_hook_bus() -> HookBus:
    global _bus
    if _bus is None:
        _bus = HookBus()
    return _bus
