"""
Learning Worker — extracts lessons from a completed agent cycle and updates:
  - LESSONS_LEARNED.md (project-level lessons log)
  - CHANGELOG.md ([Unreleased] section)
  - The relevant SKILL.md (via GEPA SkillEvolutionEngine)
  - SessionDiary (for cross-session pattern analysis)

Uses ACE Curator pattern: Qwen3.5 extracts structured lessons from the
issue context + test/review results, then GEPA decides whether to evolve
an existing skill or create a new one.
"""
from __future__ import annotations

import logging
import os
import re
import textwrap
from datetime import datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_CODING_URL = os.getenv("QWEN_CODING_URL", "http://qwen-coding:8000/v1")
_CODING_MODEL = os.getenv("CODING_MODEL_NAME", "qwen3.5-coder")
_WORKSPACE_ROOT = os.getenv("AGENT_WORKSPACE_ROOT", "/workspace")


# ── LLM helper ────────────────────────────────────────────────────────────────

async def _chat(messages: list[dict], max_tokens: int = 1024) -> str:
    payload = {
        "model": _CODING_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{_CODING_URL}/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# ── LearningWorker ────────────────────────────────────────────────────────────

class LearningWorker:
    """Updates learning artefacts after a completed issue cycle."""

    def __init__(
        self,
        issue: Any,
        build_result: Any,
        test_result: Any,
        review_result: Any,
    ) -> None:
        self.issue = issue
        self.build_result = build_result
        self.test_result = test_result
        self.review_result = review_result

    async def run(self) -> None:
        """Extract lessons and write to learning artefacts."""
        logger.info("Running learning worker for issue #%d", self.issue.iid)

        lessons = await self._extract_lessons()
        if not lessons:
            return

        await self._update_lessons_learned(lessons)
        await self._update_changelog()
        await self._feed_gepa(lessons)

    # ── Curator: extract lessons ──────────────────────────────────────────────

    async def _extract_lessons(self) -> list[str]:
        """Use Qwen3.5 to curate lessons from this cycle."""
        changed = getattr(self.build_result, "changed_files", [])
        test_summary = getattr(self.test_result, "summary", "") if self.test_result else ""
        review_score = getattr(self.review_result, "quality_score", None)
        blocking = getattr(self.review_result, "blocking_count", 0) if self.review_result else 0

        system = textwrap.dedent("""
            You are the Curator node in an ACE (Agent Control Engine) pipeline.

            Your job: extract actionable, concise lessons from a completed code-generation cycle.
            Return a JSON array of strings — each string is one lesson (max 2 sentences).
            Focus on: what worked, what didn't, technical patterns, security insights,
            test strategies, or architectural observations.

            Return ONLY the JSON array. No prose, no markdown.
            Example: ["Lesson one.", "Lesson two about testing async code."]
        """).strip()

        user = textwrap.dedent(f"""
            ## Issue #{self.issue.iid}: {self.issue.title}
            Labels: {', '.join(self.issue.labels)}
            Description: {(self.issue.description or '')[:500]}

            ## Build outcome:
            - Changed files: {', '.join(changed) or 'none'}
            - Tests: {test_summary}
            - Review score: {f'{review_score:.0%}' if review_score is not None else 'N/A'}
            - Blocking issues: {blocking}
        """).strip()

        raw = await _chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw.strip())
        try:
            import json
            lessons = json.loads(raw)
            if isinstance(lessons, list):
                return [str(l) for l in lessons if str(l).strip()][:8]
        except Exception:
            # Fallback: split on newlines
            return [ln.strip("- •").strip() for ln in raw.split("\n") if ln.strip()][:8]
        return []

    # ── LESSONS_LEARNED.md ────────────────────────────────────────────────────

    async def _update_lessons_learned(self, lessons: list[str]) -> None:
        """Append a new entry to LESSONS_LEARNED.md."""
        path = os.path.join(_WORKSPACE_ROOT, "LESSONS_LEARNED.md")
        if not os.path.exists(path):
            logger.warning("LESSONS_LEARNED.md not found at %s; skipping", path)
            return

        issue_type = _extract_type_label(self.issue.labels)
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        changed = getattr(self.build_result, "changed_files", [])
        mr_url = getattr(self.build_result, "mr_url", "") or self.issue.web_url

        bullet_list = "\n".join(f"- {l}" for l in lessons)
        files_list = ", ".join(f"`{f}`" for f in changed) or "_none_"

        entry = textwrap.dedent(f"""

            ### [{date_str}] #{self.issue.iid} — {self.issue.title}
            **Type:** {issue_type} | **Files:** {files_list} | **MR:** {mr_url}

            {bullet_list}
        """).rstrip()

        # Find the right section and append
        with open(path) as f:
            content = f.read()

        type_section_map = {
            "bug": "## Bug Fixes", "fix": "## Bug Fixes",
            "feature": "## Features & Patterns", "feat": "## Features & Patterns",
            "chore": "## Chores & Maintenance", "docs": "## Chores & Maintenance",
            "security": "## Security", "training": "## ML & Training",
        }
        section_header = type_section_map.get(issue_type, "## Agent Loop Cycles")

        if section_header in content:
            # Insert right after the section header
            content = content.replace(
                section_header,
                f"{section_header}\n{entry}",
                1,
            )
        else:
            # Append new section
            content += f"\n\n{section_header}\n{entry}\n"

        with open(path, "w") as f:
            f.write(content)
        logger.info("Updated LESSONS_LEARNED.md for issue #%d", self.issue.iid)

    # ── CHANGELOG.md ─────────────────────────────────────────────────────────

    async def _update_changelog(self) -> None:
        """Append a changelog entry under [Unreleased]."""
        path = os.path.join(_WORKSPACE_ROOT, "CHANGELOG.md")
        if not os.path.exists(path):
            return

        issue_type = _extract_type_label(self.issue.labels)
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        prefix = {
            "feat": "Added", "feature": "Added", "fix": "Fixed", "bug": "Fixed",
            "docs": "Changed", "chore": "Changed", "security": "Security",
            "training": "Added",
        }.get(issue_type, "Changed")

        mr_url = getattr(self.build_result, "mr_url", "") or ""
        mr_ref = f" ([MR]({mr_url}))" if mr_url else ""
        entry = f"- [{prefix}] #{self.issue.iid} {self.issue.title}{mr_ref} ({date_str})"

        with open(path) as f:
            content = f.read()

        unreleased_match = re.search(r"(## \[Unreleased\][^\n]*\n)", content, re.IGNORECASE)
        if unreleased_match:
            insert_pos = unreleased_match.end()
            content = content[:insert_pos] + f"\n{entry}\n" + content[insert_pos:]
        else:
            content = f"## [Unreleased]\n\n{entry}\n\n" + content

        with open(path, "w") as f:
            f.write(content)

    # ── GEPA feed ─────────────────────────────────────────────────────────────

    async def _feed_gepa(self, lessons: list[str]) -> None:
        """Feed lessons into the GEPA SkillEvolutionEngine."""
        try:
            from .skill_evolution import SkillEvolutionEngine
        except ImportError:
            logger.debug("SkillEvolutionEngine not available; skipping GEPA feed")
            return

        session_id = f"agent-loop-issue-{self.issue.iid}"
        engine = SkillEvolutionEngine()
        try:
            results = await engine.process_lessons(lessons, session_id)
            if results:
                logger.info(
                    "GEPA produced %d skill evolution result(s) for issue #%d",
                    len(results), self.issue.iid,
                )
        except Exception as exc:
            logger.warning("GEPA feed failed for issue #%d: %s", self.issue.iid, exc)


# ── Utility ────────────────────────────────────────────────────────────────────

def _extract_type_label(labels: list[str]) -> str:
    for lbl in labels:
        if lbl.startswith("type::"):
            return lbl[len("type::"):]
    return "feat"
