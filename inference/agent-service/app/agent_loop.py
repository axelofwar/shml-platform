"""
Autonomous Agent Issue Loop — core state machine daemon.

State machine:
  IDLE → PICKING → PLANNING → BUILDING → TESTING → REVIEWING → AWAITING_HUMAN → LEARNING → IDLE

Design constraints:
  - One issue at a time (GPU safety: single RTX 3090)
  - Exponential backoff on failure (5→10→20→60 min max)
  - Circuit breaker: 3 consecutive failures → pause + alert issue on GitLab
  - Complexity graduation: threshold starts at 0.4, +0.1 after 5 consecutive successes (max 0.8)
  - GPU contention detection: pauses loop when RTX 3090 training is active
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional

from prometheus_client import Counter, Gauge, Histogram

from .gitlab_client import Issue, close_issue, list_agent_queue

logger = logging.getLogger(__name__)

# ── Prometheus metrics ────────────────────────────────────────────────────────

_ISSUES_COMPLETED = Counter(
    "agent_loop_issues_completed_total",
    "Total issues successfully completed by the autonomous agent loop",
)
_ISSUES_FAILED = Counter(
    "agent_loop_issues_failed_total",
    "Total issues that failed during agent loop processing",
)
_GAPS_DETECTED = Counter(
    "agent_loop_gaps_detected_total",
    "Total integration gaps detected by the gap detector after merge",
)
_GAP_ISSUES_CREATED = Counter(
    "agent_loop_gap_issues_created_total",
    "Total GitLab issues created by gap detector",
)
_REVIEW_BLOCKING = Counter(
    "agent_loop_review_blocking_total",
    "Total blocking issues found in Copilot/ACE code reviews",
)
_REVIEW_SUGGESTIONS = Counter(
    "agent_loop_review_suggestions_total",
    "Total suggestion-level comments found in code reviews",
)
_REVIEW_QUALITY = Gauge(
    "agent_loop_review_quality_score",
    "Latest review quality score (0–1) from the Copilot/ACE review",
)
_COMPLEXITY_THRESHOLD = Gauge(
    "agent_loop_complexity_threshold",
    "Current complexity graduation threshold (0–1)",
)
_CONSECUTIVE_FAILURES = Gauge(
    "agent_loop_consecutive_failures_total",
    "Current count of consecutive agent loop failures",
)
_CYCLE_DURATION = Histogram(
    "agent_loop_cycle_duration_seconds",
    "Time spent processing a single issue end-to-end",
    buckets=[30, 60, 120, 300, 600, 900, 1800, 3600],
)


# ── Configuration ─────────────────────────────────────────────────────────────

class LoopConfig:
    """Read-only snapshot of environment configuration."""

    def __init__(self) -> None:
        self.enabled: bool = os.getenv("AGENT_LOOP_ENABLED", "false").lower() == "true"
        self.poll_interval: int = int(os.getenv("AGENT_LOOP_POLL_INTERVAL", "300"))
        self.max_complexity: float = float(os.getenv("AGENT_LOOP_MAX_COMPLEXITY", "0.4"))
        self.circuit_breaker_threshold: int = int(
            os.getenv("AGENT_LOOP_CIRCUIT_BREAKER", "3")
        )
        self.max_review_iterations: int = int(
            os.getenv("AGENT_LOOP_MAX_REVIEW_CYCLES", "3")
        )
        self.max_fix_retries: int = int(os.getenv("AGENT_LOOP_MAX_FIX_RETRIES", "3"))
        # Types that auto-merge on passing review (comma-separated)
        _auto_types = os.getenv("AGENT_LOOP_AUTO_MERGE_TYPES", "chore,docs")
        self.auto_merge_types: set[str] = {t.strip() for t in _auto_types.split(",")}


# ── State machine ─────────────────────────────────────────────────────────────

class LoopState(Enum):
    IDLE = auto()
    PICKING = auto()
    PLANNING = auto()
    BUILDING = auto()
    TESTING = auto()
    REVIEWING = auto()
    AWAITING_HUMAN = auto()
    LEARNING = auto()
    PAUSED = auto()   # circuit breaker tripped
    ERROR = auto()


@dataclass
class LoopStatus:
    state: LoopState = LoopState.IDLE
    current_issue_iid: Optional[int] = None
    current_issue_title: str = ""
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    complexity_threshold: float = 0.4
    total_completed: int = 0
    total_failed: int = 0
    consecutive_denials: int = 0  # Pattern 38: blocked/review-rejection tracking
    total_denials: int = 0
    last_completed_at: Optional[float] = None
    last_error: str = ""
    started_at: Optional[float] = None
    paused_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.name,
            "current_issue_iid": self.current_issue_iid,
            "current_issue_title": self.current_issue_title,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "complexity_threshold": self.complexity_threshold,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "consecutive_denials": self.consecutive_denials,
            "total_denials": self.total_denials,
            "last_completed_at": self.last_completed_at,
            "last_error": self.last_error,
            "uptime_seconds": (time.time() - self.started_at) if self.started_at else 0,
            "paused_reason": self.paused_reason,
        }


# ── Complexity estimator ──────────────────────────────────────────────────────

_HIGH_COMPLEXITY_PATTERNS = re.compile(
    r"\b(architect|refactor|redesign|cross.service|multi.stack|migrate|auth|security"
    r"|database schema|breaking change|gpu|cuda|training pipeline)\b",
    re.IGNORECASE,
)
_MEDIUM_COMPLEXITY_PATTERNS = re.compile(
    r"\b(endpoint|api|route|integration|docker.compose|traefik|env|config|ci|deploy)\b",
    re.IGNORECASE,
)
_SCOPE_MARKERS = re.compile(
    r"\b(files?|services?|containers?|stacks?)\b.*?\b(\d+)\b",
    re.IGNORECASE,
)


def estimate_complexity(issue: Issue) -> float:
    """
    Heuristic complexity scorer 0.0–1.0 based on issue content.

    Bands:
      0.0–0.15  docs / comment / label changes
      0.15–0.30 single-file fix, typo, test-only
      0.30–0.50 multi-file feature, new endpoint, config change
      0.50–0.70 cross-service integration, new docker-compose service
      0.70–0.90 architecture change, auth/security, training pipeline
      0.90–1.00 breaking change, database migration
    """
    text = f"{issue.title} {issue.description}".lower()
    labels_str = " ".join(issue.labels).lower()

    # Label-based fast-path
    if "type::docs" in labels_str:
        return 0.10
    if "type::chore" in labels_str:
        return 0.20
    if "type::security" in labels_str or "type::training" in labels_str:
        return 0.80
    if "type::bug" in labels_str:
        base = 0.30
    elif "type::feature" in labels_str:
        base = 0.45
    else:
        base = 0.30

    # Boost from high-complexity keywords
    high_matches = len(_HIGH_COMPLEXITY_PATTERNS.findall(text))
    medium_matches = len(_MEDIUM_COMPLEXITY_PATTERNS.findall(text))
    boost = min(0.40, high_matches * 0.12 + medium_matches * 0.05)

    # Boost from explicit scope (e.g. "3 services", "5 files")
    scope_match = _SCOPE_MARKERS.search(text)
    if scope_match:
        n = int(scope_match.group(2))
        boost += min(0.20, n * 0.03)

    return min(0.95, base + boost)


# ── GPU contention detection ──────────────────────────────────────────────────

async def _is_gpu_training_active() -> bool:
    """Check if RTX 3090 (cuda:0) is busy with training via model_router."""
    try:
        from .model_router import check_training_active
        return await check_training_active()
    except Exception:
        # Fallback: check nvidia-smi utilization > 80% on GPU 0
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
                "--id=0",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            util = int(stdout.decode().strip().split("\n")[0])
            return util > 80
        except Exception:
            return False


# ── Priority sorting ──────────────────────────────────────────────────────────

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _priority_score(issue: Issue) -> int:
    for lbl in issue.labels:
        stripped = lbl.replace("priority::", "")
        if stripped in _PRIORITY_ORDER:
            return _PRIORITY_ORDER[stripped]
    return 99


# ── Core daemon ───────────────────────────────────────────────────────────────


class AgentLoop:
    """Autonomous development loop daemon."""

    def __init__(self, config: Optional[LoopConfig] = None) -> None:
        self._config = config or LoopConfig()
        self._status = LoopStatus(
            complexity_threshold=self._config.max_complexity
        )
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        # Backoff state
        self._backoff_seconds = self._config.poll_interval

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task and not self._task.done():
            logger.warning("AgentLoop already running")
            return
        self._stop_event.clear()
        self._status.started_at = time.time()
        self._status.state = LoopState.IDLE
        self._task = asyncio.create_task(self._run(), name="agent-loop")
        logger.info("AgentLoop started (enabled=%s)", self._config.enabled)

    def pause(self, reason: str = "manual") -> None:
        self._status.state = LoopState.PAUSED
        self._status.paused_reason = reason
        logger.info("AgentLoop paused: %s", reason)

    def resume(self) -> None:
        if self._status.state == LoopState.PAUSED:
            self._status.state = LoopState.IDLE
            self._status.paused_reason = ""
            self._status.consecutive_failures = 0
            logger.info("AgentLoop resumed")

    def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
        logger.info("AgentLoop stop requested")

    def status(self) -> dict[str, Any]:
        return self._status.to_dict()

    def update_config(self, **kwargs: Any) -> None:
        """Hot-update config without restart (only safe subset)."""
        for k, v in kwargs.items():
            if k == "enabled":
                self._config.enabled = bool(v)
            elif k == "max_complexity":
                self._status.complexity_threshold = float(v)
            elif k == "poll_interval":
                self._config.poll_interval = int(v)

    # ── Main run loop ─────────────────────────────────────────────────────────

    async def _run(self) -> None:
        logger.info("AgentLoop run() entered")
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("AgentLoop tick unhandled exception: %s", exc)
                self._handle_failure(str(exc))

            # Wait for next poll (respects stop signal)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._backoff_seconds
                )
            except asyncio.TimeoutError:
                pass  # Normal: poll interval elapsed

        self._status.state = LoopState.IDLE
        logger.info("AgentLoop run() exited cleanly")

    async def _tick(self) -> None:
        """Single loop tick. No-ops when disabled, paused, or GPU busy."""
        if not self._config.enabled:
            return
        if self._status.state == LoopState.PAUSED:
            return
        if await _is_gpu_training_active():
            logger.info("GPU training active — loop waiting")
            return

        # ── 1. PICK ───────────────────────────────────────────────────────────
        self._status.state = LoopState.PICKING
        issue = await self._pick_issue()
        if issue is None:
            self._status.state = LoopState.IDLE
            self._backoff_seconds = self._config.poll_interval
            return

        self._status.current_issue_iid = issue.iid
        self._status.current_issue_title = issue.title
        logger.info("Loop picked issue #%d: %s", issue.iid, issue.title)

        try:
            await self._process_issue(issue)
        except Exception as exc:
            logger.exception("Issue #%d processing failed: %s", issue.iid, exc)
            self._handle_failure(str(exc), issue=issue)
            await self._post_failure_comment(issue, str(exc))

    async def _pick_issue(self) -> Optional[Issue]:
        """Pick the highest-priority eligible issue from the agent queue."""
        try:
            issues = await list_agent_queue(limit=20)
        except Exception as exc:
            logger.error("Failed to fetch agent queue: %s", exc)
            return None

        eligible = [
            i for i in issues
            if estimate_complexity(i) <= self._status.complexity_threshold
            and "status::blocked" not in i.labels
            and "assignee::human" not in i.labels
        ]

        if not eligible:
            logger.debug("No eligible issues (threshold=%.1f)", self._status.complexity_threshold)
            return None

        eligible.sort(key=_priority_score)
        return eligible[0]

    # ── Issue processing pipeline ─────────────────────────────────────────────

    async def _process_issue(self, issue: Issue) -> None:
        """Full processing pipeline for one issue."""
        from .code_worker import CodeWorker
        from .gap_detector import GapDetector
        from .learning_worker import LearningWorker
        from .review_client import ReviewClient
        from .test_worker import TestWorker

        # ── 2. PLAN ───────────────────────────────────────────────────────────
        self._status.state = LoopState.PLANNING
        worker = CodeWorker(issue)
        plan = await worker.plan()
        logger.info("Issue #%d plan ready (%d files)", issue.iid, len(plan.files_to_touch))

        # Pattern 31: verification nudge — warn if large plan has no test files
        test_files = [f for f in plan.files_to_touch if "test" in f.lower()]
        if len(plan.files_to_touch) >= 3 and not test_files:
            logger.warning(
                "Pattern 31 nudge: %d files planned for issue #%d with no test coverage — consider adding tests",
                len(plan.files_to_touch),
                issue.iid,
            )

        # ── 3. BUILD ──────────────────────────────────────────────────────────
        self._status.state = LoopState.BUILDING
        build_result = await worker.build(plan)
        logger.info("Issue #%d build complete: branch=%s", issue.iid, build_result.branch_name)

        # ── 4. TEST ───────────────────────────────────────────────────────────
        self._status.state = LoopState.TESTING
        test_worker = TestWorker(issue, build_result)
        test_result = await test_worker.run(
            max_fix_retries=self._config.max_fix_retries
        )
        if not test_result.passed:
            raise RuntimeError(
                f"Tests failed after {self._config.max_fix_retries} retries: "
                f"{test_result.summary}"
            )
        logger.info("Issue #%d tests passed (%d tests)", issue.iid, test_result.test_count)

        # ── 5. REVIEW ─────────────────────────────────────────────────────────
        self._status.state = LoopState.REVIEWING
        reviewer = ReviewClient(issue, build_result)
        review_result = await reviewer.review(
            max_cycles=self._config.max_review_iterations
        )
        logger.info(
            "Issue #%d review done: blocking=%d, suggestions=%d, score=%.2f",
            issue.iid, review_result.blocking_count,
            review_result.suggestion_count, review_result.quality_score,
        )
        _REVIEW_QUALITY.set(review_result.quality_score)
        if review_result.blocking_count:
            _REVIEW_BLOCKING.inc(review_result.blocking_count)
        if review_result.suggestion_count:
            _REVIEW_SUGGESTIONS.inc(review_result.suggestion_count)

        # ── 6. GATE ───────────────────────────────────────────────────────────
        issue_type = self._get_issue_type(issue)
        if issue_type in self._config.auto_merge_types:
            await worker.merge_mr(build_result)
            logger.info("Issue #%d auto-merged (%s)", issue.iid, issue_type)
        else:
            await worker.set_ready_for_review(build_result)
            self._status.state = LoopState.AWAITING_HUMAN
            logger.info("Issue #%d moved to in-review (human gate)", issue.iid)

        # ── 7. LEARN ──────────────────────────────────────────────────────────
        self._status.state = LoopState.LEARNING
        learner = LearningWorker(issue, build_result, test_result, review_result)
        await learner.run()

        gap_detector = GapDetector()
        gap_list = await gap_detector.scan_after_merge(build_result.changed_files)
        if gap_list:
            _GAPS_DETECTED.inc(len(gap_list))
            _GAP_ISSUES_CREATED.inc(len(gap_list))

        # ── SUCCESS ───────────────────────────────────────────────────────────
        self._handle_success()
        self._status.state = LoopState.IDLE
        self._status.current_issue_iid = None
        self._status.current_issue_title = ""
        logger.info("Issue #%d complete ✓", issue.iid)

    # ── Failure / circuit breaker ─────────────────────────────────────────────

    def _handle_failure(self, error: str, issue: Optional[Issue] = None) -> None:
        self._status.consecutive_failures += 1
        self._status.consecutive_successes = 0
        self._status.total_failed += 1
        self._status.last_error = error
        self._status.state = LoopState.IDLE
        _ISSUES_FAILED.inc()
        _CONSECUTIVE_FAILURES.set(self._status.consecutive_failures)

        # Exponential backoff: 5→10→20→60 min
        self._backoff_seconds = min(
            3600,
            self._config.poll_interval * (2 ** (self._status.consecutive_failures - 1)),
        )
        logger.warning(
            "Failure #%d (backoff=%ds): %s",
            self._status.consecutive_failures,
            self._backoff_seconds,
            error,
        )

        if self._status.consecutive_failures >= self._config.circuit_breaker_threshold:
            self.pause(reason=f"Circuit breaker: {self._status.consecutive_failures} consecutive failures")
            asyncio.create_task(self._create_alert_issue())

        # Pattern 38: track review/permission denials separately
        if any(kw in error.lower() for kw in ("review", "blocked", "denied", "rejected")):
            self._status.consecutive_denials += 1
            self._status.total_denials += 1
            logger.warning(
                "Denial #%d detected — transitioning to AWAITING_HUMAN if >= 3",
                self._status.consecutive_denials,
            )
            if self._status.consecutive_denials >= 3:
                self._status.state = LoopState.AWAITING_HUMAN
                logger.warning("3 consecutive denials — entering AWAITING_HUMAN state")
        else:
            self._status.consecutive_denials = 0

    def _handle_success(self) -> None:
        self._status.consecutive_successes += 1
        self._status.consecutive_failures = 0
        self._status.total_completed += 1
        self._status.last_completed_at = time.time()
        self._backoff_seconds = self._config.poll_interval
        _ISSUES_COMPLETED.inc()
        _CONSECUTIVE_FAILURES.set(0)

        # Graduation: +0.1 every 5 consecutive successes, max 0.8
        if self._status.consecutive_successes % 5 == 0:
            new_threshold = min(0.8, self._status.complexity_threshold + 0.1)
            if new_threshold > self._status.complexity_threshold:
                logger.info(
                    "Complexity threshold graduated: %.1f → %.1f",
                    self._status.complexity_threshold,
                    new_threshold,
                )
                self._status.complexity_threshold = new_threshold
                _COMPLEXITY_THRESHOLD.set(new_threshold)

    async def _post_failure_comment(self, issue: Issue, error: str) -> None:
        """Post a failure comment on the GitLab issue."""
        try:
            from .gitlab_client import add_comment
            await add_comment(
                issue.iid,
                f"⚠️ **Agent loop failed** on this issue.\n\n"
                f"**Error:** `{error[:500]}`\n\n"
                f"The issue has been returned to `status::backlog` for retry "
                f"or manual intervention.",
            )
        except Exception as exc:
            logger.warning("Could not post failure comment: %s", exc)

    async def _create_alert_issue(self) -> None:
        """Create a GitLab issue alerting that the circuit breaker tripped."""
        try:
            from .gitlab_client import create_issue
            await create_issue(
                title=f"🚨 Agent loop circuit breaker triggered ({self._status.consecutive_failures} failures)",
                description=(
                    f"The autonomous agent loop has paused after **{self._status.consecutive_failures} "
                    f"consecutive failures**.\n\n"
                    f"**Last error:** `{self._status.last_error[:1000]}`\n\n"
                    "To resume: fix the underlying issue and call `POST /api/agent/loop/resume`."
                ),
                labels="type::bug,priority::high,component::agent-service,source::agent,assignee::human",
            )
        except Exception as exc:
            logger.error("Failed to create alert issue: %s", exc)

    @staticmethod
    def _get_issue_type(issue: Issue) -> str:
        """Return the type:: label value, e.g. 'chore', 'bug', 'feature'."""
        for lbl in issue.labels:
            if lbl.startswith("type::"):
                return lbl[len("type::"):]
        return "feature"  # default to gated


# ── Module-level singleton ────────────────────────────────────────────────────

_loop: Optional[AgentLoop] = None


def get_agent_loop() -> AgentLoop:
    global _loop
    if _loop is None:
        _loop = AgentLoop()
    return _loop
