"""
Sub-Agent Delegation System
=============================
Allows a parent ACE workflow to spawn isolated child agent calls for
complex sub-tasks that shouldn't pollute the parent's context window.

This is the ACE equivalent of Hermes "delegation node" — a higher-order
pattern where the generator can offload a decomposed task chunk to a
dedicated agent call, collect the result, and resume its main workflow.

Design principles:
  - Each delegated call is fully isolated (own httpx client, own timeout)
  - Parent receives a concise summary result, not the full conversation
  - Failures are gracefully returned as error strings (never crash parent)
  - Rate-limited to prevent runaway delegation chains (max 3 concurrent)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_DEFAULT_TIMEOUT = 120.0        # seconds per delegated call
_MAX_CONCURRENT = 3             # simultaneous subagent calls
_MAX_TOKENS = 2048              # response token cap for sub-tasks
_COMPLEXITY_THRESHOLD = 0.6     # score above which delegation is triggered
_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(_MAX_CONCURRENT)
    return _SEMAPHORE


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class DelegationTask:
    """A sub-task to be delegated to a child agent call."""
    task: str
    context: str = ""
    objective: str = ""         # What success looks like
    max_tokens: int = _MAX_TOKENS
    timeout: float = _DEFAULT_TIMEOUT
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DelegationResult:
    """Result of a delegated sub-task."""
    task: str
    result: str
    success: bool
    elapsed_ms: float
    tokens_used: int = 0
    error: Optional[str] = None


# ── Complexity scoring ────────────────────────────────────────────────────────

def score_complexity(task: str) -> float:
    """
    Heuristic complexity score 0–1 for a task string.

    High complexity tasks benefit from isolated delegation.
    """
    score = 0.0
    task_lower = task.lower()

    # Length signal
    words = len(task.split())
    if words > 50:
        score += 0.2
    elif words > 25:
        score += 0.1

    # Multi-step signal
    multi_step_markers = [
        "then", "after that", "next", "finally", "also", "and then",
        "step 1", "step 2", "first", "second", "third", "additionally",
    ]
    score += 0.1 * sum(1 for m in multi_step_markers if m in task_lower)

    # Technical keywords implying depth
    depth_keywords = [
        "implement", "refactor", "architect", "design", "optimize",
        "debug", "analyze", "evaluate", "compare", "integrate",
        "migrate", "deploy", "test", "benchmark",
    ]
    score += 0.05 * sum(1 for kw in depth_keywords if kw in task_lower)

    return min(score, 1.0)


# ── Core delegation logic ─────────────────────────────────────────────────────

class SubAgentDelegator:
    """
    Delegates sub-tasks to isolated Qwen3.5 calls without spawning a full
    ACE LangGraph workflow (too heavy for simple sub-queries).

    For true parallel sub-workflows, use `delegate_parallel()`.
    """

    def __init__(self, base_url: str = "http://qwen-coding:8000"):
        self.base_url = base_url

    def _build_system_prompt(self, task: DelegationTask) -> str:
        parts = [
            "You are a focused sub-agent. Your ONLY job is to complete the specific task given.",
            "Be concise. Return actionable results. Do NOT engage in meta-discussion.",
        ]
        if task.objective:
            parts.append(f"\nSuccess criteria: {task.objective}")
        if task.context:
            parts.append(f"\nContext provided by parent agent:\n{task.context}")
        return "\n".join(parts)

    async def delegate(self, task: DelegationTask) -> DelegationResult:
        """
        Execute a single delegated sub-task via direct Qwen API call.

        Respects the concurrency semaphore to avoid overwhelming the model.
        """
        should_delegate = score_complexity(task.task) >= _COMPLEXITY_THRESHOLD
        if not should_delegate:
            logger.debug(
                f"[SubAgent] Complexity below threshold for: {task.task[:60]}..."
            )

        start_ms = time.monotonic() * 1000
        sem = _get_semaphore()

        async with sem:
            logger.info(f"[SubAgent] Delegating: {task.task[:80]}...")
            try:
                async with httpx.AsyncClient(timeout=task.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/v1/chat/completions",
                        json={
                            "model": "qwen-coding",
                            "messages": [
                                {
                                    "role": "system",
                                    "content": self._build_system_prompt(task),
                                },
                                {"role": "user", "content": task.task},
                            ],
                            "temperature": 0.2,
                            "max_tokens": task.max_tokens,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    content = data["choices"][0]["message"]["content"] or ""
                    tokens = data.get("usage", {}).get("completion_tokens", 0)
                    elapsed = time.monotonic() * 1000 - start_ms
                    logger.info(
                        f"[SubAgent] Completed in {elapsed:.0f}ms, {tokens} tokens"
                    )
                    return DelegationResult(
                        task=task.task,
                        result=content,
                        success=True,
                        elapsed_ms=elapsed,
                        tokens_used=tokens,
                    )

            except httpx.TimeoutException:
                elapsed = time.monotonic() * 1000 - start_ms
                error = f"Sub-agent timed out after {task.timeout}s"
                logger.warning(f"[SubAgent] {error}")
                return DelegationResult(
                    task=task.task, result="", success=False,
                    elapsed_ms=elapsed, error=error,
                )
            except Exception as e:
                elapsed = time.monotonic() * 1000 - start_ms
                logger.error(f"[SubAgent] Error: {e}")
                return DelegationResult(
                    task=task.task, result="", success=False,
                    elapsed_ms=elapsed, error=str(e),
                )

    async def delegate_parallel(
        self, tasks: List[DelegationTask]
    ) -> List[DelegationResult]:
        """
        Execute multiple sub-tasks concurrently (respects max concurrency).

        Useful when the generator identifies independent parallel work items.
        """
        logger.info(f"[SubAgent] Parallel delegation: {len(tasks)} tasks")
        return await asyncio.gather(*[self.delegate(t) for t in tasks])

    def summarize_results(self, results: List[DelegationResult]) -> str:
        """
        Produce a compact summary for inclusion in the parent agent's context.
        """
        lines = [f"## Sub-Agent Results ({len(results)} tasks)\n"]
        for i, r in enumerate(results, 1):
            status = "✓" if r.success else "✗"
            lines.append(f"### Task {i} [{status}] ({r.elapsed_ms:.0f}ms)")
            lines.append(f"**Task**: {r.task[:120]}")
            if r.success and r.result:
                lines.append(f"**Result**:\n{r.result[:1000]}")
            elif r.error:
                lines.append(f"**Error**: {r.error}")
            lines.append("")
        return "\n".join(lines)


# ── Generator helper: should_delegate() ───────────────────────────────────────

def should_delegate(task: str, threshold: float = _COMPLEXITY_THRESHOLD) -> bool:
    """
    Quick check used by generator_node to decide whether to spawn a sub-agent.

    Usage in generator_node:
        if should_delegate(subtask):
            delegator = get_delegator()
            result = await delegator.delegate(DelegationTask(task=subtask))
    """
    return score_complexity(task) >= threshold


# ── Singleton ─────────────────────────────────────────────────────────────────
_delegator: Optional[SubAgentDelegator] = None


def get_delegator(base_url: str = "http://qwen-coding:8000") -> SubAgentDelegator:
    """Get or create the singleton SubAgentDelegator."""
    global _delegator
    if _delegator is None:
        _delegator = SubAgentDelegator(base_url=base_url)
    return _delegator
