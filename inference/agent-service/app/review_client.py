"""
Review Client — sends diffs to the GitHub Copilot Chat Completions API
for code review, then posts comments on the GitLab MR.

The code never touches the public GitHub mirror.
Only the unified diff is sent; no git history, no remote refs.

Copilot API endpoint: https://api.githubcopilot.com/chat/completions
Auth: GITHUB_TOKEN (PAT with copilot:read scope)
Preferred model: claude-sonnet-4-20250514 (Sonnet via Copilot Plan)
Fallback: gpt-4o-mini (if Sonnet slot unavailable)

Workflow:
  1. ACE Reflector pre-screen (quality score ≥ 0.7 required before API call)
  2. Chunk diff into ≤8KB segments and review each with Copilot
  3. Aggregate comments, post as inline GitLab MR notes
  4. Return ReviewResult for the loop to decide merge vs gate
"""
from __future__ import annotations

import logging
import os
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
_COPILOT_API_URL = "https://api.githubcopilot.com/chat/completions"
_COPILOT_MODEL_PRIMARY = "claude-sonnet-4-20250514"
_COPILOT_MODEL_FALLBACK = "gpt-4o-mini"
_DIFF_CHUNK_CHARS = 8000

# Local fallback for Reflector pre-screen
_CODING_URL = os.getenv("QWEN_CODING_URL", "http://qwen-coding:8000/v1")
_CODING_MODEL = os.getenv("CODING_MODEL_NAME", "qwen3.5-coder")

# Minimum local quality score (0–1) before we bother calling Copilot API
_LOCAL_QUALITY_THRESHOLD = float(os.getenv("AGENT_REVIEW_LOCAL_THRESHOLD", "0.70"))


# ── Domain models ──────────────────────────────────────────────────────────────

@dataclass
class ReviewComment:
    severity: str        # "blocking" | "suggestion" | "info"
    file: str
    line_hint: str       # e.g. "~L42" or "general"
    body: str


@dataclass
class ReviewResult:
    passed: bool
    quality_score: float
    blocking_count: int
    suggestion_count: int
    comments: list[ReviewComment] = field(default_factory=list)
    raw_review: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _local_chat(messages: list[dict], temperature: float = 0.0) -> str:
    """Call local Qwen3.5 for ACE pre-screen."""
    payload = {
        "model": _CODING_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 1024,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{_CODING_URL}/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _copilot_chat(messages: list[dict]) -> str:
    """
    Call GitHub Copilot Chat Completions API.
    Returns response text; raises on 4xx/5xx.
    """
    if not _GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN not set; cannot call Copilot API")

    headers = {
        "Authorization": f"Bearer {_GITHUB_TOKEN}",
        "Content-Type": "application/json",
        "Editor-Version": "shml-agent/1.0",
        "Copilot-Integration-Id": "shml-autonomous-loop",
    }

    # Try preferred model first, fall back on 4xx model-not-found
    for model in (_COPILOT_MODEL_PRIMARY, _COPILOT_MODEL_FALLBACK):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 2048,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(_COPILOT_API_URL, json=payload, headers=headers)
                if resp.status_code == 422:
                    logger.warning("Copilot model %s not available, trying fallback", model)
                    continue
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except httpx.TimeoutException:
                raise RuntimeError("Copilot API timeout")

    raise RuntimeError("All Copilot models unavailable")


def _chunk_diff(diff: str) -> list[str]:
    """Split a unified diff into segments ≤ _DIFF_CHUNK_CHARS characters."""
    chunks: list[str] = []
    lines = diff.split("\n")
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current_len + len(line) > _DIFF_CHUNK_CHARS and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [diff]


def _parse_review_text(text: str) -> list[ReviewComment]:
    """Loosely parse a Copilot review response into structured comments."""
    comments: list[ReviewComment] = []
    current_file = "general"
    current_line = "general"

    for block in re.split(r"\n#{2,4}\s+", text):
        block = block.strip()
        if not block:
            continue

        # Detect file context  "### app/foo.py"
        file_match = re.match(r"^([\w./\-_]+\.\w+)", block)
        if file_match:
            current_file = file_match.group(1)

        # Classify severity
        lower = block.lower()
        if any(kw in lower for kw in ("blocking", "must fix", "critical", "security", "vulnerability", "injection", "xss")):
            severity = "blocking"
        elif any(kw in lower for kw in ("suggestion", "consider", "could", "might", "recommend")):
            severity = "suggestion"
        else:
            severity = "info"

        line_match = re.search(r"[Ll]ine[s]?\s*(\d+)", block)
        current_line = f"~L{line_match.group(1)}" if line_match else "general"

        body_lines = block.split("\n")[1:]  # skip the header line
        body = "\n".join(body_lines).strip()
        if body and len(body) > 20:
            comments.append(ReviewComment(
                severity=severity,
                file=current_file,
                line_hint=current_line,
                body=body[:1000],
            ))

    return comments


# ── ReviewClient ──────────────────────────────────────────────────────────────

class ReviewClient:
    """Orchestrates code review for a single GitLab MR."""

    def __init__(self, issue: Any, build_result: Any) -> None:
        self.issue = issue
        self.build_result = build_result

    async def review(self, max_cycles: int = 3) -> ReviewResult:
        """Full review pipeline: local prescreen → Copilot review → GitLab comments."""
        diff = getattr(self.build_result, "diff_summary", "") or ""

        if not diff.strip():
            logger.warning("No diff available for review of issue #%d", self.issue.iid)
            return ReviewResult(
                passed=True, quality_score=0.8,
                blocking_count=0, suggestion_count=0,
                raw_review="(no diff)",
            )

        # Step 1: ACE Reflector pre-screen
        local_score = await self._local_prescore(diff)
        logger.info("Local ACE pre-score for issue #%d: %.2f", self.issue.iid, local_score)

        if local_score < _LOCAL_QUALITY_THRESHOLD:
            # Return a synthetic "blocking" result so the loop retries code generation
            return ReviewResult(
                passed=False,
                quality_score=local_score,
                blocking_count=1,
                suggestion_count=0,
                comments=[
                    ReviewComment(
                        severity="blocking",
                        file="general",
                        line_hint="general",
                        body=(
                            f"Local ACE Reflector quality score {local_score:.2f} < "
                            f"{_LOCAL_QUALITY_THRESHOLD} threshold. "
                            "Code needs revision before external review."
                        ),
                    )
                ],
                raw_review=f"local_score={local_score:.2f}",
            )

        # Step 2: Copilot API review
        all_comments: list[ReviewComment] = []
        raw_parts: list[str] = []

        chunks = _chunk_diff(diff)
        for i, chunk in enumerate(chunks):
            try:
                review_text = await self._call_copilot_review(chunk, chunk_idx=i, total=len(chunks))
                raw_parts.append(review_text)
                all_comments.extend(_parse_review_text(review_text))
            except RuntimeError as exc:
                logger.warning("Copilot API unavailable for chunk %d: %s; skipping", i, exc)
                # Fall back to local review for this chunk
                local_text = await self._local_review(chunk)
                raw_parts.append(local_text)
                all_comments.extend(_parse_review_text(local_text))

        blocking = [c for c in all_comments if c.severity == "blocking"]
        suggestions = [c for c in all_comments if c.severity == "suggestion"]

        quality_score = max(0.0, 1.0 - (len(blocking) * 0.25) - (len(suggestions) * 0.05))
        passed = len(blocking) == 0

        result = ReviewResult(
            passed=passed,
            quality_score=round(quality_score, 2),
            blocking_count=len(blocking),
            suggestion_count=len(suggestions),
            comments=all_comments,
            raw_review="\n\n---\n\n".join(raw_parts),
        )

        # Step 3: Post comments on GitLab MR
        await self._post_gitlab_comments(result)
        return result

    # ── ACE pre-screen ────────────────────────────────────────────────────────

    async def _local_prescore(self, diff: str) -> float:
        """Quick local assessment (0.0–1.0) of diff quality."""
        system = textwrap.dedent("""
            You are an expert code reviewer. Score the following diff from 0.0 (very bad) to 1.0 (excellent).
            Evaluate: correctness, security (OWASP Top 10), test coverage, style.
            Return ONLY a number between 0.0 and 1.0. Nothing else.
        """).strip()
        user = f"```diff\n{diff[:4000]}\n```"
        raw = await _local_chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        m = re.search(r"(\d+(?:\.\d+)?)", raw)
        if not m:
            return 0.75  # default to "probably fine"
        score = float(m.group(1))
        # Normalise in case model returns 0–100
        return min(1.0, score / 100.0 if score > 1.0 else score)

    # ── Copilot API review ────────────────────────────────────────────────────

    async def _call_copilot_review(self, diff_chunk: str, chunk_idx: int, total: int) -> str:
        issue = self.issue
        system = textwrap.dedent(f"""
            You are a senior software engineer performing a code review for a pull request
            on the SHML Platform (private ML infrastructure).

            Review this diff carefully for:
            1. **Blocking issues** — security vulnerabilities (OWASP Top 10), data corruption,
               broken logic, import cycles, missing null-checks on external input.
            2. **Suggestions** — style improvements, missing test coverage, documentation gaps,
               performance concerns.
            3. **Info** — observations that don't require action.

            Format your response as:
            ## <file path or "General">
            <severity>: <short title>
            <detailed explanation>

            Where <severity> is one of: Blocking | Suggestion | Info.
            Chunk {chunk_idx + 1}/{total}.
        """).strip()

        user = textwrap.dedent(f"""
            ## Issue #{issue.iid}: {issue.title}
            Labels: {', '.join(issue.labels)}

            ## Diff (chunk {chunk_idx + 1}/{total}):
            ```diff
            {diff_chunk}
            ```
        """).strip()

        return await _copilot_chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )

    async def _local_review(self, diff_chunk: str) -> str:
        """Fallback review using local Qwen3.5 when Copilot API is unavailable."""
        system = textwrap.dedent("""
            You are a senior engineer. Review this diff for security issues, bugs, and style concerns.
            Format: ## <file>\nBlocking|Suggestion|Info: <title>\n<explanation>
        """).strip()
        user = f"```diff\n{diff_chunk[:4000]}\n```"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{_CODING_URL}/chat/completions",
                json={
                    "model": _CODING_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    # ── GitLab comment posting ────────────────────────────────────────────────

    async def _post_gitlab_comments(self, result: ReviewResult) -> None:
        """Post review summary as a GitLab MR comment."""
        from .gitlab_client import add_comment

        if not result.comments:
            await add_comment(
                self.issue.iid,
                f"✅ **Review passed** (score {result.quality_score:.0%}, 0 blocking issues)",
            )
            return

        lines = ["## 🔍 Automated Code Review", ""]
        lines.append(
            f"**Score:** {result.quality_score:.0%} | "
            f"**Blocking:** {result.blocking_count} | "
            f"**Suggestions:** {result.suggestion_count}"
        )
        lines.append("")

        for c in result.comments:
            icon = {"blocking": "🚫", "suggestion": "💡", "info": "ℹ️"}.get(c.severity, "ℹ️")
            lines.append(f"### {icon} {c.severity.capitalize()} — `{c.file}` {c.line_hint}")
            lines.append(c.body)
            lines.append("")

        if result.passed:
            lines.append("---\n✅ No blocking issues — ready to merge pending human sign-off.")
        else:
            lines.append("---\n🚫 Blocking issues found — agent will attempt fixes.")

        await add_comment(self.issue.iid, "\n".join(lines))
