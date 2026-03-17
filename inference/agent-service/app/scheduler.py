"""
ACE Agent Scheduler
====================
Lightweight async cron-style scheduler for platform background tasks.

Runs inside the agent-service process alongside FastAPI — no external celery/cron
required. All jobs are async-safe and non-blocking.

Scheduled jobs:
  - skill_evolution_nightly   02:00 UTC  Run GEPA evolution across all skill dirs
  - playbook_cleanup_weekly   03:00 UTC  Prune low-value playbook bullets (Sunday)
  - session_diary_export      01:00 UTC  Export session logs to data/diary/

Quick integration:
    from .scheduler import scheduler
    # In FastAPI lifespan or startup event:
    await scheduler.start()
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_QWEN_URL = os.getenv("GATEWAY_URL", "http://qwen-coding:8000")
_SKILLS_DIR = Path(__file__).parent.parent / "skills"
_DIARY_DIR = Path(__file__).parent.parent / "data" / "diary"
_DIARY_DIR.mkdir(parents=True, exist_ok=True)

# Obsidian watcher — path to docs/research/ relative to repo root
# Agent-service lives at inference/agent-service/, so ../../docs/research
_RESEARCH_DIR = Path(__file__).resolve().parents[3] / "docs" / "research"
_OBSIDIAN_WATCHER_DEBOUNCE: float = float(
    os.getenv("OBSIDIAN_WATCHER_DEBOUNCE_SECS", "10")
)


# ── Job definition ────────────────────────────────────────────────────────────

class ScheduledJob:
    """A single recurring async job."""

    def __init__(
        self,
        name: str,
        coro_factory: Callable[[], Coroutine],
        hour: int,
        minute: int = 0,
        day_of_week: Optional[int] = None,  # 0=Mon … 6=Sun, None = every day
    ):
        self.name = name
        self.coro_factory = coro_factory
        self.hour = hour
        self.minute = minute
        self.day_of_week = day_of_week
        self.last_run: Optional[datetime] = None
        self.run_count = 0
        self.last_error: Optional[str] = None

    def is_due(self, now: datetime) -> bool:
        """Return True if the job should fire at this moment (checked every minute)."""
        if now.hour != self.hour or now.minute != self.minute:
            return False
        if self.day_of_week is not None and now.weekday() != self.day_of_week:
            return False
        # Avoid double-triggering within the same minute
        if self.last_run and (now - self.last_run) < timedelta(minutes=1):
            return False
        return True

    async def run(self) -> None:
        self.last_run = datetime.now(timezone.utc)
        self.run_count += 1
        logger.info(f"[Scheduler] Running job: {self.name} (run #{self.run_count})")
        try:
            await self.coro_factory()
            logger.info(f"[Scheduler] Job completed: {self.name}")
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"[Scheduler] Job failed: {self.name} — {e}")


# ── Job implementations ────────────────────────────────────────────────────────

async def _job_skill_evolution_nightly() -> None:
    """
    Nightly GEPA evolution scan.

    Reads all playbook curator bullets from PostgreSQL, clusters them,
    and triggers skill create/evolve for high-signal clusters.
    """
    from .skill_evolution import PATTERN_THRESHOLD, get_evolution_engine

    engine = get_evolution_engine(base_url=_QWEN_URL)
    all_lessons = engine.get_all_lessons()

    if len(all_lessons) < PATTERN_THRESHOLD:
        logger.info(
            f"[Scheduler/GEPA] Not enough accumulated lessons ({len(all_lessons)}/{PATTERN_THRESHOLD}), skipping"
        )
        return

    # Use a synthetic session_id for scheduler-triggered runs
    session_id = f"scheduler_{datetime.now().strftime('%Y%m%d')}"

    # Gather any lessons stored in in-memory engine and process
    results = await engine.process_lessons([], session_id=session_id)
    logger.info(
        f"[Scheduler/GEPA] Nightly evolution: {len(results)} skill updates"
    )
    if results:
        summary = engine.summarize_evolution_results(results)
        logger.info(summary)


async def _job_playbook_cleanup_weekly() -> None:
    """
    Weekly playbook pruning.

    Marks playbook bullets with rubric_score importance < 0.3
    as archived so they don't bloat future generator prompts.
    Currently logs what would be pruned (dry-run safe).
    """
    logger.info("[Scheduler/Cleanup] Playbook cleanup starting (weekly)")
    # TODO: wire to PlaybookStore once DB integration is complete
    # For now, log intent as a placeholder
    logger.info(
        "[Scheduler/Cleanup] Would prune bullets: importance < 0.3 AND age > 30 days"
    )


async def _job_obsidian_connection_map_nightly() -> None:
    """
    Nightly connection map refresh.

    Re-runs scripts/generate_connection_map.py so the Obsidian vault
    shows an up-to-date view of all service connections.
    """
    import importlib.util

    logger.info("[Scheduler/ConnectionMap] Refreshing service connection map…")
    map_script = _RESEARCH_DIR.parents[1] / "scripts" / "generate_connection_map.py"
    if not map_script.exists():
        logger.warning(f"[Scheduler/ConnectionMap] Script not found: {map_script}")
        return
    spec = importlib.util.spec_from_file_location("connection_map", map_script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()
    logger.info("[Scheduler/ConnectionMap] Connection map updated in Obsidian vault")


async def _job_session_diary_export() -> None:
    """
    Daily session diary export.

    Writes accumulated session diaries from in-memory state to disk.
    Acts as a cheap audit log and crash recovery baseline.
    """
    export_path = _DIARY_DIR / f"diary_{datetime.now().strftime('%Y%m%d')}.jsonl"
    logger.info(f"[Scheduler/Diary] Export path: {export_path}")
    # The actual diary content is managed per-session in agent state.
    # This job creates a sentinel file so we know the scheduler ran.
    with open(export_path, "a") as f:
        f.write(
            '{"event": "scheduler_diary_export", "timestamp": "'
            + datetime.now().isoformat()
            + '"}\n'
        )
    logger.info("[Scheduler/Diary] Export sentinel written")


# ── Scheduler class ────────────────────────────────────────────────────────────

class AgentScheduler:
    """
    Minimal async cron scheduler.

    All jobs are registered at class instantiation and checked every 60 seconds.
    Also manages the Obsidian research watcher daemon thread.
    """

    def __init__(self):
        self._jobs: List[ScheduledJob] = []
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._watcher_thread: Optional[threading.Thread] = None

        # ── Register built-in jobs ─────────────────────────────────────────
        self.register(ScheduledJob(
            name="skill_evolution_nightly",
            coro_factory=_job_skill_evolution_nightly,
            hour=2, minute=0,
        ))
        self.register(ScheduledJob(
            name="playbook_cleanup_weekly",
            coro_factory=_job_playbook_cleanup_weekly,
            hour=3, minute=0,
            day_of_week=6,  # Sunday
        ))
        self.register(ScheduledJob(
            name="session_diary_export",
            coro_factory=_job_session_diary_export,
            hour=1, minute=0,
        ))
        self.register(ScheduledJob(
            name="obsidian_connection_map_nightly",
            coro_factory=_job_obsidian_connection_map_nightly,
            hour=0, minute=30,  # 00:30 UTC — before GEPA at 02:00
        ))

    def register(self, job: ScheduledJob) -> None:
        self._jobs.append(job)
        logger.info(
            f"[Scheduler] Registered: {job.name} @ "
            f"{job.hour:02d}:{job.minute:02d} UTC"
            + (f" (day_of_week={job.day_of_week})" if job.day_of_week is not None else "")
        )

    def _start_obsidian_watcher(self) -> None:
        """Start the Obsidian research watcher in a daemon thread."""
        try:
            import importlib.util
            watcher_path = _RESEARCH_DIR.parents[1] / "scripts" / "obsidian_watcher.py"
            if not watcher_path.exists():
                logger.warning(f"[Scheduler/Obsidian] Watcher script not found: {watcher_path}")
                return
            spec = importlib.util.spec_from_file_location("obsidian_watcher", watcher_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self._watcher_thread = mod.start_watcher_thread(
                debounce_secs=_OBSIDIAN_WATCHER_DEBOUNCE
            )
            logger.info(
                f"[Scheduler/Obsidian] Watcher thread started "
                f"(watching {_RESEARCH_DIR}, debounce={_OBSIDIAN_WATCHER_DEBOUNCE}s)"
            )
        except RuntimeError as e:
            # watchdog not installed — log and continue, don't crash service
            logger.warning(f"[Scheduler/Obsidian] Watcher disabled: {e}")
        except Exception as e:
            logger.error(f"[Scheduler/Obsidian] Failed to start watcher: {e}", exc_info=True)

    async def start(self) -> None:
        """Start the background scheduler loop and Obsidian file watcher."""
        if self._running:
            logger.warning("[Scheduler] Already running, ignoring start()")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="agent-scheduler")
        # Start Obsidian watcher in background thread (daemon — dies with process)
        self._start_obsidian_watcher()
        logger.info(f"[Scheduler] Started with {len(self._jobs)} jobs")

    async def stop(self) -> None:
        """Cancel the scheduler loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Scheduler] Stopped")

    async def _loop(self) -> None:
        """Main loop: wake every 60 seconds, check/fire due jobs."""
        while self._running:
            now = datetime.now(timezone.utc)
            for job in self._jobs:
                if job.is_due(now):
                    # Fire and forget — jobs don't block the loop
                    asyncio.create_task(job.run(), name=f"scheduler-{job.name}")
            await asyncio.sleep(60)

    def status(self) -> Dict[str, Any]:
        """Return scheduler status for /health or admin endpoint."""
        watcher_alive = (
            self._watcher_thread is not None and self._watcher_thread.is_alive()
        )
        return {
            "running": self._running,
            "obsidian_watcher": {
                "active": watcher_alive,
                "watching": str(_RESEARCH_DIR),
                "debounce_secs": _OBSIDIAN_WATCHER_DEBOUNCE,
            },
            "jobs": [
                {
                    "name": j.name,
                    "schedule": f"{j.hour:02d}:{j.minute:02d} UTC"
                    + (f" day={j.day_of_week}" if j.day_of_week is not None else ""),
                    "last_run": j.last_run.isoformat() if j.last_run else None,
                    "run_count": j.run_count,
                    "last_error": j.last_error,
                }
                for j in self._jobs
            ],
        }


# ── Singleton ─────────────────────────────────────────────────────────────────
scheduler = AgentScheduler()
