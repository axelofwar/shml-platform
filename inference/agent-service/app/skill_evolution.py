"""
GEPA Skill Evolution Engine
============================
Inspired by hermes-agent-self-evolution (GEPA pattern):
  Generate → Evaluate → Prioritize → Archive

This module handles:
  1. Pattern detection  - find recurring lesson themes across curator sessions
  2. Skill generation   - use Qwen3.5 (thinking mode) to auto-create new SKILL.md
  3. Skill evolution    - improve existing SKILL.md files with accumulated lessons
  4. Versioning         - snapshot old versions before overwriting

The trigger model:
  - ≥ PATTERN_THRESHOLD similar lessons across ≥ MIN_SESSIONS → auto-create skill
  - Existing skills evolve after EVOLUTION_THRESHOLD new lessons touch the same domain
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
PATTERN_THRESHOLD = 3       # min occurrences before skill auto-creation fires
MIN_SESSIONS = 2            # must span at least this many curator sessions
EVOLUTION_THRESHOLD = 5     # new on-topic lessons to trigger evolution of existing skill
SIMILARITY_CUTOFF = 0.60    # difflib SequenceMatcher threshold for "same topic"

# ── Memory caps ───────────────────────────────────────────────────────────────
MAX_LESSON_LOG_SESSIONS = 200   # max sessions kept in _lesson_log (oldest evicted)
MAX_LESSONS_PER_SESSION = 50    # max lessons stored per session

# ── Skill directory ───────────────────────────────────────────────────────────
_SKILLS_DIR = Path(__file__).parent.parent / "skills"


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class LessonCluster:
    """A group of semantically similar lessons from curator sessions."""
    representative: str
    members: List[str] = field(default_factory=list)
    session_ids: List[str] = field(default_factory=list)
    domain: str = "general"
    count: int = 0

    @property
    def ready_for_skill(self) -> bool:
        return (
            self.count >= PATTERN_THRESHOLD
            and len(set(self.session_ids)) >= MIN_SESSIONS
        )


@dataclass
class EvolutionResult:
    """Result of a skill create/evolve operation."""
    action: str          # "created" | "evolved" | "skipped" | "error"
    skill_name: str
    skill_path: Optional[Path] = None
    version: Optional[str] = None
    diff_lines: int = 0
    message: str = ""


# ── Similarity helpers ────────────────────────────────────────────────────────

def _similarity(a: str, b: str) -> float:
    """Return 0–1 similarity between two lesson strings."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _cluster_lessons(
    lessons: List[Tuple[str, str]],  # (lesson_text, session_id)
) -> List[LessonCluster]:
    """
    Greedily cluster lessons by textual similarity.

    Returns clusters sorted by count descending.
    """
    clusters: List[LessonCluster] = []

    for text, session_id in lessons:
        # Try to find a matching cluster
        matched = None
        for cluster in clusters:
            if _similarity(text, cluster.representative) >= SIMILARITY_CUTOFF:
                matched = cluster
                break

        if matched:
            matched.members.append(text)
            matched.session_ids.append(session_id)
            matched.count += 1
        else:
            clusters.append(
                LessonCluster(
                    representative=text,
                    members=[text],
                    session_ids=[session_id],
                    count=1,
                )
            )

    return sorted(clusters, key=lambda c: c.count, reverse=True)


def _infer_domain(cluster: LessonCluster) -> str:
    """Infer a slug domain name from the lesson cluster content."""
    combined = " ".join(cluster.members).lower()
    domain_map = {
        "gpu": "gpu-monitoring",
        "vram": "gpu-monitoring",
        "cuda": "gpu-monitoring",
        "docker": "shell-execution",
        "container": "shell-execution",
        "code": "coding-assistant",
        "function": "coding-assistant",
        "python": "coding-assistant",
        "javascript": "coding-assistant",
        "typescript": "coding-assistant",
        "test": "coding-assistant",
        "git": "github-integration",
        "github": "github-integration",
        "pull request": "github-integration",
        "web": "web-search",
        "search": "web-search",
        "ray": "ray-compute",
        "training": "ray-compute",
        "model": "ray-compute",
        "skill": "skill-evolution",
        "evolv": "skill-evolution",
        "lesson": "skill-evolution",
    }
    for keyword, domain in domain_map.items():
        if keyword in combined:
            return domain
    # Default: derive from most common words
    words = re.findall(r"\b[a-z]{4,}\b", combined)
    if words:
        freq = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        top = sorted(freq, key=lambda k: freq[k], reverse=True)[:2]
        return "-".join(top)
    return "general"


# ── Prompt builders ───────────────────────────────────────────────────────────

def _build_create_skill_prompt(cluster: LessonCluster, domain: str) -> str:
    lessons_block = "\n".join(f"- {m}" for m in cluster.members)
    return f"""You are a technical documentation expert for an AI coding assistant platform.

Based on the following repeating lessons extracted by our AI curator, create a new SKILL.md file
for the agent skill system. The skill should capture the patterns in these lessons so future
agent sessions automatically apply them.

## Recurring Lessons (domain: {domain})
{lessons_block}

## Required Output Format

Return ONLY the full SKILL.md content with this exact structure:

```skill
---
name: {domain}
description: <one-sentence description — used for skill activation matching>
license: MIT
compatibility: <runtime requirements if any, else "None">
metadata:
  author: gepa-evolution
  version: "1.0"
  generated_from_lessons: {cluster.count}
  generated_at: {datetime.now().isoformat()}
allowed-tools: <comma-separated Bash(cmd:*) entries, or empty>
---

# <Skill Title>

## When to use this skill
<bullet list of activation conditions>

## How to apply this skill
<concrete step-by-step guidance derived from the lessons>

## Patterns to avoid
<anti-patterns inferred from failure lessons, if any>

## Examples
<short illustrative examples>
```

The skill MUST be actionable, concise, and directly encode the lessons above.
"""


def _build_evolve_skill_prompt(
    existing_content: str,
    new_lessons: List[str],
    skill_name: str,
) -> str:
    lessons_block = "\n".join(f"- {l}" for l in new_lessons)
    return f"""You are improving an existing AI agent skill based on newly observed lessons.

## Existing Skill: {skill_name}

{existing_content}

## New Lessons to Incorporate
{lessons_block}

## Task
Produce an improved version of this SKILL.md that:
1. Preserves all existing useful content
2. Incorporates the new lessons (add to "How to apply", expand "Patterns to avoid", etc.)
3. Increments the version number (e.g., "1.0" → "1.1")
4. Adds a `changelog` metadata key listing: "v<N>: <one-line change summary>"

Return ONLY the complete updated SKILL.md content inside the ```skill ... ``` block.
No preamble or explanation — raw SKILL.md content only.
"""


# ── LLM call helper ───────────────────────────────────────────────────────────

async def _call_qwen(
    prompt: str,
    base_url: str = "http://qwen-coding:8000",
    temperature: float = 0.3,
) -> str:
    """POST to Qwen3.5 OpenAI-compatible endpoint and return content string."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": "qwen-coding",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": 4096,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def _extract_skill_block(raw: str) -> str:
    """Extract content between ```skill and ``` markers."""
    match = re.search(r"```skill\s*(.*?)```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: strip outer ``` if present
    cleaned = re.sub(r"^```[a-z]*\n?", "", raw.strip())
    cleaned = re.sub(r"```$", "", cleaned.strip())
    return cleaned.strip()


# ── Versioning helpers ────────────────────────────────────────────────────────

def _version_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _backup_skill(skill_path: Path) -> Path:
    """Save existing SKILL.md to a versioned backup before overwriting."""
    backup_dir = skill_path.parent / ".evolution_history"
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / f"SKILL_{_version_tag()}.md"
    shutil.copy2(skill_path, backup_path)
    logger.info(f"Backed up {skill_path} → {backup_path}")
    return backup_path


def _diff_line_count(old: str, new: str) -> int:
    diffs = list(
        difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="")
    )
    return sum(1 for line in diffs if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))


# ── Public API ────────────────────────────────────────────────────────────────

class SkillEvolutionEngine:
    """
    GEPA engine: Generate, Evaluate, Prioritize, Archive skills.

    Usage (from curator_node or scheduler):
        engine = SkillEvolutionEngine()
        results = await engine.process_lessons(lessons, session_id)
    """

    def __init__(
        self,
        skills_dir: Path = _SKILLS_DIR,
        base_url: str = "http://qwen-coding:8000",
    ):
        self.skills_dir = skills_dir
        self.base_url = base_url
        self._lesson_log: Dict[str, List[Tuple[str, str]]] = {}  # session → lessons

    def record_lessons(self, lessons: List[str], session_id: str) -> None:
        """Record lessons from a curator session for pattern analysis.

        Memory-bounded: max MAX_LESSONS_PER_SESSION entries per session,
        and max MAX_LESSON_LOG_SESSIONS sessions total (oldest evicted).
        """
        session_entries = self._lesson_log.setdefault(session_id, [])
        for lesson in lessons:
            if lesson and len(lesson) > 20:
                if len(session_entries) < MAX_LESSONS_PER_SESSION:
                    session_entries.append((lesson, session_id))

        # Evict oldest sessions when log exceeds cap (Python 3.7+ dicts are ordered)
        while len(self._lesson_log) > MAX_LESSON_LOG_SESSIONS:
            oldest_session = next(iter(self._lesson_log))
            del self._lesson_log[oldest_session]
            logger.debug(
                f"SkillEvolutionEngine: evicted oldest session from lesson_log "
                f"(log size was {MAX_LESSON_LOG_SESSIONS + 1})"
            )

    def get_all_lessons(self) -> List[Tuple[str, str]]:
        """Return flattened (lesson, session_id) list across all sessions."""
        result = []
        for session_id, entries in self._lesson_log.items():
            result.extend(entries)
        return result

    async def process_lessons(
        self,
        lessons: List[str],
        session_id: str,
    ) -> List[EvolutionResult]:
        """
        Main entry point called after each curator_node run.

        1. Record the new lessons
        2. Cluster all accumulated lessons
        3. For each cluster with enough signal:
           - If matching skill exists → evolve it
           - Otherwise → create new skill
        """
        self.record_lessons(lessons, session_id)
        all_lessons = self.get_all_lessons()

        if len(all_lessons) < PATTERN_THRESHOLD:
            # Not enough data yet
            return []

        clusters = _cluster_lessons(all_lessons)
        results: List[EvolutionResult] = []

        for cluster in clusters:
            if not cluster.ready_for_skill:
                continue

            cluster.domain = _infer_domain(cluster)
            skill_dir = self.skills_dir / cluster.domain
            skill_path = skill_dir / "SKILL.md"

            if skill_path.exists():
                result = await self._evolve_skill(skill_path, cluster)
            else:
                result = await self._create_skill(skill_dir, skill_path, cluster)

            results.append(result)

        return results

    async def _create_skill(
        self,
        skill_dir: Path,
        skill_path: Path,
        cluster: LessonCluster,
    ) -> EvolutionResult:
        """Generate a new SKILL.md from Qwen and write to disk."""
        logger.info(
            f"[GEPA] Creating new skill: {cluster.domain} "
            f"({cluster.count} pattern occurrences across {len(set(cluster.session_ids))} sessions)"
        )

        try:
            prompt = _build_create_skill_prompt(cluster, cluster.domain)
            raw = await _call_qwen(prompt, self.base_url, temperature=0.3)
            skill_content = _extract_skill_block(raw)

            if len(skill_content) < 200:
                return EvolutionResult(
                    action="error",
                    skill_name=cluster.domain,
                    message=f"Generated content too short ({len(skill_content)} chars), skipping",
                )

            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_path.write_text(skill_content, encoding="utf-8")
            logger.info(f"[GEPA] Created skill: {skill_path}")

            return EvolutionResult(
                action="created",
                skill_name=cluster.domain,
                skill_path=skill_path,
                version="1.0",
                diff_lines=len(skill_content.splitlines()),
                message=f"New skill '{cluster.domain}' created from {cluster.count} recurring lessons",
            )

        except Exception as e:
            logger.error(f"[GEPA] Failed to create skill {cluster.domain}: {e}")
            return EvolutionResult(
                action="error",
                skill_name=cluster.domain,
                message=str(e),
            )

    async def _evolve_skill(
        self,
        skill_path: Path,
        cluster: LessonCluster,
    ) -> EvolutionResult:
        """Improve an existing SKILL.md using accumulated lessons."""
        skill_name = cluster.domain
        logger.info(f"[GEPA] Evolving skill: {skill_name}")

        try:
            existing_content = skill_path.read_text(encoding="utf-8")
            # Only run evolution if we have enough new lessons to warrant it
            if cluster.count < EVOLUTION_THRESHOLD:
                return EvolutionResult(
                    action="skipped",
                    skill_name=skill_name,
                    message=(
                        f"Only {cluster.count}/{EVOLUTION_THRESHOLD} lessons "
                        "accumulated; deferring evolution"
                    ),
                )

            prompt = _build_evolve_skill_prompt(
                existing_content, cluster.members, skill_name
            )
            raw = await _call_qwen(prompt, self.base_url, temperature=0.2)
            new_content = _extract_skill_block(raw)

            if len(new_content) < 200:
                return EvolutionResult(
                    action="error",
                    skill_name=skill_name,
                    message=f"Evolved content too short ({len(new_content)} chars), skipping",
                )

            diff_lines = _diff_line_count(existing_content, new_content)
            if diff_lines < 3:
                return EvolutionResult(
                    action="skipped",
                    skill_name=skill_name,
                    message="Evolved version has <3 changed lines — no meaningful improvement",
                )

            # Backup + write
            backup_path = _backup_skill(skill_path)
            skill_path.write_text(new_content, encoding="utf-8")
            logger.info(
                f"[GEPA] Evolved {skill_name}: {diff_lines} lines changed (backup: {backup_path})"
            )

            # Extract new version number
            version_match = re.search(r'version:\s*"([^"]+)"', new_content)
            version = version_match.group(1) if version_match else "evolved"

            return EvolutionResult(
                action="evolved",
                skill_name=skill_name,
                skill_path=skill_path,
                version=version,
                diff_lines=diff_lines,
                message=f"Evolved '{skill_name}' to v{version}: {diff_lines} lines changed",
            )

        except Exception as e:
            logger.error(f"[GEPA] Failed to evolve skill {skill_name}: {e}")
            return EvolutionResult(
                action="error",
                skill_name=skill_name,
                message=str(e),
            )

    def summarize_evolution_results(self, results: List[EvolutionResult]) -> str:
        """Return human-readable summary for session diary."""
        if not results:
            return ""
        lines = ["[GEPA] Skill evolution results:"]
        for r in results:
            icon = {"created": "✨", "evolved": "⬆", "skipped": "·", "error": "✗"}.get(r.action, "?")
            lines.append(f"  {icon} [{r.action}] {r.skill_name}: {r.message}")
        return "\n".join(lines)


# ── Singleton (import once from agent.py) ─────────────────────────────────────
_evolution_engine: Optional[SkillEvolutionEngine] = None


def get_evolution_engine(base_url: str = "http://qwen-coding:8000") -> SkillEvolutionEngine:
    """Get or create the singleton SkillEvolutionEngine."""
    global _evolution_engine
    if _evolution_engine is None:
        _evolution_engine = SkillEvolutionEngine(base_url=base_url)
    return _evolution_engine
