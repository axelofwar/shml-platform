"""
Memory Store — two-tier cross-session memory (Pattern 36).

Tier 1 — session memory: in-process list, cleared on service restart.
Tier 2 — long-term memory: JSONL file persisted at AGENT_MEMORY_FILE.
  Default: {WORKSPACE_ROOT}/.agent-memory.jsonl

Including recent long-term memory in the planning prompt prevents the agent
re-learning already-solved patterns across restarts (~30-50% re-learning
reduction per the free-code audit, Pattern 36).

Usage:
    store = get_memory_store()
    store.record(
        issue_iid=12,
        branch="agent/issue-12-fix-bug",
        outcome="success",
        learnings="Fixed race in _collect_context by using asyncio.gather().",
        files_changed=["app/code_worker.py"],
    )
    ctx = store.get_recent_context(n=5)  # inject into planning prompt
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = os.getenv("AGENT_WORKSPACE_ROOT", "/workspace")
_MEMORY_FILE = os.getenv(
    "AGENT_MEMORY_FILE",
    os.path.join(_WORKSPACE_ROOT, ".agent-memory.jsonl"),
)
_MAX_SESSION_ENTRIES = int(os.getenv("AGENT_MEMORY_SESSION_SIZE", "50"))
_MAX_LONGTERM_ENTRIES = int(os.getenv("AGENT_MEMORY_LONGTERM_SIZE", "200"))


# ── Domain model ──────────────────────────────────────────────────────────────


@dataclass
class MemoryEntry:
    issue_iid: int
    branch: str
    outcome: str           # "success" | "failure" | "partial"
    learnings: str
    files_changed: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "issue_iid": self.issue_iid,
            "branch": self.branch,
            "outcome": self.outcome,
            "learnings": self.learnings,
            "files_changed": self.files_changed,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        return cls(
            issue_iid=d.get("issue_iid", 0),
            branch=d.get("branch", ""),
            outcome=d.get("outcome", "unknown"),
            learnings=d.get("learnings", ""),
            files_changed=d.get("files_changed", []),
            timestamp=d.get("timestamp", 0.0),
        )


# ── MemoryStore ───────────────────────────────────────────────────────────────


class MemoryStore:
    """Two-tier memory store for cross-session agent context (Pattern 36).

    session: in-process list (restart-ephemeral, ~50 entries)
    longterm: JSONL file (persists indefinitely, capped at 200 tail entries)
    """

    def __init__(self, memory_file: str = _MEMORY_FILE) -> None:
        self._file = memory_file
        self._session: list[MemoryEntry] = []
        self._longterm: list[MemoryEntry] = self._load_longterm()

    # ── Write ──────────────────────────────────────────────────────────────

    def record(
        self,
        issue_iid: int,
        branch: str,
        outcome: str,
        learnings: str,
        files_changed: Optional[list[str]] = None,
    ) -> None:
        """Record a completed issue cycle into both memory tiers."""
        entry = MemoryEntry(
            issue_iid=issue_iid,
            branch=branch,
            outcome=outcome,
            learnings=learnings,
            files_changed=files_changed or [],
        )
        # Tier 1: session (in-process, ephemeral)
        self._session.append(entry)
        if len(self._session) > _MAX_SESSION_ENTRIES:
            self._session = self._session[-_MAX_SESSION_ENTRIES:]
        # Tier 2: long-term (persisted JSONL)
        self._longterm.append(entry)
        if len(self._longterm) > _MAX_LONGTERM_ENTRIES:
            self._longterm = self._longterm[-_MAX_LONGTERM_ENTRIES:]
        self._persist(entry)

    # ── Read ───────────────────────────────────────────────────────────────

    def get_recent_context(self, n: int = 5) -> str:
        """Return a formatted context string from the most recent n long-term entries.

        Included in the planning prompt to give the LLM cross-session awareness
        of past patterns, reducing re-learning (~30-50% per Pattern 36 audit).
        """
        recent = self._longterm[-n:]
        if not recent:
            return ""
        lines = ["## Recent Agent Memory (cross-session context)"]
        for e in reversed(recent):
            outcome_icon = "✓" if e.outcome == "success" else "✗"
            lines.append(
                f"- [{outcome_icon}] Issue #{e.issue_iid} ({e.branch}): "
                f"{e.learnings[:200]}"
            )
        return "\n".join(lines)

    def get_session_summary(self) -> str:
        """Return a one-line summary of this session's completed issues."""
        if not self._session:
            return "(No issues completed this session)"
        successes = sum(1 for e in self._session if e.outcome == "success")
        return (
            f"This session: {len(self._session)} issues processed, "
            f"{successes} succeeded."
        )

    # ── Persistence ────────────────────────────────────────────────────────

    def _persist(self, entry: MemoryEntry) -> None:
        try:
            parent = os.path.dirname(self._file)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self._file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry.to_dict()) + "\n")
        except OSError as exc:
            logger.warning("Could not write to memory file %s: %s", self._file, exc)

    def _load_longterm(self) -> list[MemoryEntry]:
        """Load the tail of the JSONL long-term memory file on startup."""
        if not os.path.exists(self._file):
            return []
        entries: list[MemoryEntry] = []
        try:
            with open(self._file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(MemoryEntry.from_dict(json.loads(line)))
                        except (json.JSONDecodeError, KeyError):
                            pass
        except OSError as exc:
            logger.warning("Could not read memory file %s: %s", self._file, exc)
        return entries[-_MAX_LONGTERM_ENTRIES:]


# ── Module-level singleton ────────────────────────────────────────────────────

_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
