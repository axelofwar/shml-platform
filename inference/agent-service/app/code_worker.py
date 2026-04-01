"""
Code Worker — Qwen3.5 code generation + Git operations.

Workflow per issue:
  1. plan()  → analyse issue, identify files, produce an implementation plan
  2. build() → generate unified diffs, apply in NemoClaw sandbox, validate syntax
  3. Git ops → branch, commit, push, create GitLab MR
  4. merge_mr() / set_ready_for_review() → post-review board transitions
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import re
import tempfile
import textwrap
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Config helpers ─────────────────────────────────────────────────────────────

_CODING_URL = os.getenv("QWEN_CODING_URL", "http://qwen-coding:8000/v1")
_CODING_MODEL = os.getenv("CODING_MODEL_NAME", "qwen3.5-coder")
_GIT_AUTHOR_NAME = os.getenv("AGENT_GIT_AUTHOR_NAME", "Qwen3.5 Agent")
_GIT_AUTHOR_EMAIL = os.getenv("AGENT_GIT_AUTHOR_EMAIL", "agent@shml-platform.local")
_GITLAB_REMOTE = os.getenv("GITLAB_REMOTE_URL", "http://shml-gitlab:8929/gitlab/shml/platform.git")
_WORKSPACE_ROOT = os.getenv("AGENT_WORKSPACE_ROOT", "/workspace")

# Max tokens to include from source files in the planning prompt
_PLAN_CTX_TOKEN_BUDGET = 40_000
# Characters used as rough token proxy (1 token ≈ 4 chars)
_PLAN_CTX_CHAR_BUDGET = _PLAN_CTX_TOKEN_BUDGET * 4

# Lock directory for multi-agent branch serialisation (Pattern 33)
_LOCK_DIR = os.getenv("AGENT_LOCK_DIR", "/tmp/agent_locks")


# Pattern 34 — context-aware token budget for code generation
def _context_aware_max_tokens(file_count: int) -> int:
    """Return a generation token budget scaled to the number of files in the plan.

    Thresholds (from free-code thinking.ts Pattern 34):
      <=2 files  → 4 096  (typical small fix)
       3-5 files → 6 144  (medium change)
       6-9 files → 8 192  (large change)
      >=10 files → 12 288 (wide refactor — cap before OOM)
    """
    if file_count >= 10:
        return 12_288
    if file_count >= 6:
        return 8_192
    if file_count >= 3:
        return 6_144
    return 4_096


# ── Domain models ──────────────────────────────────────────────────────────────

@dataclass
class IssuePlan:
    files_to_touch: list[str]
    implementation_steps: list[str]
    test_strategy: str
    estimated_file_count: int
    risk_notes: str = ""
    raw_plan: str = ""


@dataclass
class BuildResult:
    branch_name: str
    mr_iid: Optional[int]
    mr_url: str
    changed_files: list[str]
    commit_sha: str = ""
    diff_summary: str = ""


# ── Qwen3.5 chat helper ────────────────────────────────────────────────────────

async def _chat(messages: list[dict], temperature: float = 0.0, max_tokens: int = 4096) -> str:
    """Single non-streaming call to the coding LLM."""
    payload = {
        "model": _CODING_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(f"{_CODING_URL}/chat/completions", json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            raise RuntimeError("LLM timeout: code generation exceeded 120s")
        except httpx.ConnectError:
            raise RuntimeError(f"LLM unavailable at {_CODING_URL}")


# ── Sandbox shell execution ────────────────────────────────────────────────────

async def _shell(cmd: str, cwd: Optional[str] = None, timeout: int = 60) -> tuple[int, str, str]:
    """Run a shell command in the workspace and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd or _WORKSPACE_ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "", f"Command timed out after {timeout}s: {cmd}"
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


# ── File reading helper ────────────────────────────────────────────────────────

async def _read_file_safe(path: str) -> str:
    """Read file content, return empty string on error."""
    try:
        rc, out, err = await _shell(f"cat {path!r}")
        return out if rc == 0 else ""
    except Exception:
        return ""


# ── Convention loader ──────────────────────────────────────────────────────────

def _load_conventions() -> str:
    """Load project coding conventions from .claude/rules/ for inclusion in prompts."""
    rules_dir = os.path.join(_WORKSPACE_ROOT, ".claude", "rules")
    snippets: list[str] = []
    for name in ("code-style.md", "api-conventions.md", "security.md"):
        path = os.path.join(rules_dir, name)
        try:
            with open(path) as f:
                content = f.read(3000)  # cap at 3KB per rule file
                snippets.append(f"### {name}\n{content}")
        except FileNotFoundError:
            pass
    return "\n\n".join(snippets)


_CONVENTIONS_CACHE: Optional[str] = None


def _conventions() -> str:
    global _CONVENTIONS_CACHE
    if _CONVENTIONS_CACHE is None:
        _CONVENTIONS_CACHE = _load_conventions()
    return _CONVENTIONS_CACHE


# ── CodeWorker ────────────────────────────────────────────────────────────────

class CodeWorker:
    """Orchestrates code generation and git operations for a single GitLab issue."""

    def __init__(self, issue: Any, memory_context: str = "") -> None:
        # issue is inference.agent_service.app.gitlab_client.Issue
        self.issue = issue
        self._slug = re.sub(r"[^\w-]", "-", issue.title.lower())[:40].strip("-")
        self._branch = f"agent/issue-{issue.iid}-{self._slug}"
        # Pattern 36: cross-session memory context injected by AgentLoop
        self._memory_context = memory_context

    # ── Plan ──────────────────────────────────────────────────────────────────

    async def plan(self) -> IssuePlan:
        """Ask Qwen3.5 to analyse the issue and produce a structured plan."""
        logger.info("Planning issue #%d", self.issue.iid)

        # Collect relevant code context (up to char budget)
        context_snippets = await self._collect_context()

        system_prompt = textwrap.dedent(f"""
            You are an expert software engineer working on the SHML Platform.
            Your task is to analyse a GitLab issue and produce a concise implementation plan.

            ## Project Conventions
            {_conventions()[:5000]}

            ## Your response MUST be valid JSON matching this schema:
            {{
              "files_to_touch": ["list", "of", "relative", "file", "paths"],
              "implementation_steps": ["step 1", "step 2", ...],
              "test_strategy": "one paragraph describing how to test this",
              "estimated_file_count": 3,
              "risk_notes": "brief risk notes or empty string"
            }}

            Return ONLY the JSON object. No prose, no markdown fences.
        """).strip()

        # Pattern 36: include prior agent memory when available
        memory_section = (
            f"\n\n            ### Prior Agent Memory\n            {self._memory_context}"
            if self._memory_context
            else ""
        )

        user_prompt = textwrap.dedent(f"""
            ## Issue #{self.issue.iid}: {self.issue.title}
            Labels: {', '.join(self.issue.labels)}

            ### Description
            {self.issue.description or '(no description)'}

            ### Relevant code context
            {context_snippets}{memory_section}
        """).strip()

        raw = await _chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=2048,
        )

        # Parse JSON response (strip any accidental markdown fences)
        raw_clean = re.sub(r"```[a-z]*\n?", "", raw).strip()
        try:
            data = json.loads(raw_clean)
        except json.JSONDecodeError:
            # Fallback: extract JSON from response
            m = re.search(r"\{.*\}", raw_clean, re.DOTALL)
            if not m:
                raise ValueError(f"LLM returned non-JSON plan: {raw[:300]}")
            data = json.loads(m.group(0))

        plan = IssuePlan(
            files_to_touch=data.get("files_to_touch", []),
            implementation_steps=data.get("implementation_steps", []),
            test_strategy=data.get("test_strategy", ""),
            estimated_file_count=data.get("estimated_file_count", len(data.get("files_to_touch", []))),
            risk_notes=data.get("risk_notes", ""),
            raw_plan=raw,
        )

        # Post the plan to GitLab
        await self._post_plan_comment(plan)
        return plan

    async def _collect_context(self) -> str:
        """Gather relevant file snippets for the planning prompt.

        Pattern 28: reads all candidate files concurrently with asyncio.gather()
        instead of sequentially to reduce wall-clock latency on multi-file issues.
        """
        # Simple keyword-based file discovery
        keywords = re.findall(r"\b[\w/]+\.py\b|\b[\w/]+\.ts\b|\b[\w/]+\.yml\b", self.issue.description or "")
        paths = keywords[:10]  # cap file hints from description
        if not paths:
            return "(No specific files identified in issue description)"

        # P28: concurrent reads — gather all candidate files in parallel
        full_paths = [os.path.join(_WORKSPACE_ROOT, p) for p in paths]
        contents = await asyncio.gather(*[_read_file_safe(fp) for fp in full_paths])

        snippets: list[str] = []
        char_used = 0
        for path, content in zip(paths, contents):
            if char_used >= _PLAN_CTX_CHAR_BUDGET:
                break
            if content:
                excerpt = content[: min(3000, _PLAN_CTX_CHAR_BUDGET - char_used)]
                snippets.append(f"### {path}\n```\n{excerpt}\n```")
                char_used += len(excerpt)

        return "\n\n".join(snippets) or "(No specific files identified in issue description)"

    async def _post_plan_comment(self, plan: IssuePlan) -> None:
        from .gitlab_client import claim_issue
        steps = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(plan.implementation_steps))
        files = "\n".join(f"  - `{f}`" for f in plan.files_to_touch)
        plan_md = textwrap.dedent(f"""
            ## 🤖 Agent Implementation Plan

            **Files to touch ({plan.estimated_file_count}):**
            {files or '  _(to be determined during build)_'}

            **Steps:**
            {steps}

            **Test strategy:** {plan.test_strategy}

            **Risk notes:** {plan.risk_notes or 'None identified'}

            ---
            _Claiming this issue. Branch will be: `{self._branch}`_
        """).strip()
        await claim_issue(self.issue.iid, plan=plan_md)

    # ── Build ─────────────────────────────────────────────────────────────────

    async def build(self, plan: IssuePlan) -> BuildResult:
        """Generate and apply code changes on a feature branch.

        Uses a per-branch fcntl lock (Pattern 33) so two concurrent agents
        cannot write to the same branch simultaneously.
        """
        logger.info("Building issue #%d on branch %s", self.issue.iid, self._branch)

        # Pattern 33 — acquire exclusive branch lock
        os.makedirs(_LOCK_DIR, exist_ok=True)
        lock_path = os.path.join(_LOCK_DIR, re.sub(r"[^\w-]", "_", self._branch) + ".lock")
        lock_fh = open(lock_path, "w")  # noqa: WPS515 (file handle held for lock duration)
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_fh.close()
            raise RuntimeError(
                f"Branch {self._branch!r} is already being built by another agent (lock: {lock_path})"
            )
        try:
            return await self._build_locked(plan)
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()

    async def _build_locked(self, plan: IssuePlan) -> BuildResult:
        """Inner build logic executed while holding the branch lock."""
        # Pattern 34 — scale generation budget to scope of change
        gen_tokens = _context_aware_max_tokens(len(plan.files_to_touch))
        logger.info(
            "Issue #%d: %d files planned → gen_tokens=%d",
            self.issue.iid, len(plan.files_to_touch), gen_tokens,
        )

        # Set git identity + create branch
        await self._setup_git()
        rc, _, err = await _shell(f"git checkout -b {self._branch}")
        if rc != 0:
            # Branch might exist from a prior run — reset it
            await _shell(f"git checkout {self._branch}")
            await _shell(f"git reset --hard origin/main")

        changed_files: list[str] = []
        diff_parts: list[str] = []

        for file_path in plan.files_to_touch:
            existing = await _read_file_safe(os.path.join(_WORKSPACE_ROOT, file_path))
            new_content = await self._generate_file_change(file_path, existing, plan, gen_tokens)
            if new_content is None:
                continue

            # Write file
            full_path = os.path.join(_WORKSPACE_ROOT, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as fh:
                fh.write(new_content)

            # Syntax validation
            syntax_ok = await self._validate_syntax(file_path, new_content)
            if not syntax_ok:
                # Attempt one auto-correction
                new_content = await self._fix_syntax(file_path, new_content)
                with open(full_path, "w") as fh:
                    fh.write(new_content)

            changed_files.append(file_path)
            await _shell(f"git add {full_path!r}")

        if not changed_files:
            raise RuntimeError("Build produced no changed files")

        # Commit
        commit_msg = self._build_commit_message(plan)
        rc, out, err = await _shell(f'git commit -m {json.dumps(commit_msg)}')
        if rc != 0:
            raise RuntimeError(f"git commit failed: {err}")

        # Get commit sha
        _, sha, _ = await _shell("git rev-parse HEAD")
        sha = sha.strip()

        # Get unified diff for review
        _, diff_text, _ = await _shell("git diff HEAD~1 HEAD")
        diff_parts.append(diff_text)

        return BuildResult(
            branch_name=self._branch,
            mr_iid=None,  # filled by push + create MR
            mr_url="",
            changed_files=changed_files,
            commit_sha=sha,
            diff_summary="\n".join(diff_parts),
        )

    async def _generate_file_change(
        self, file_path: str, existing_content: str, plan: IssuePlan,
        max_tokens: int = 6144,
    ) -> Optional[str]:
        """Ask Qwen3.5 to generate the full new content for a single file."""
        steps_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(plan.implementation_steps))

        system = textwrap.dedent(f"""
            You are an expert software engineer. Generate the complete, updated content
            of a source file to implement the requested changes.

            Rules:
            - Return ONLY the file content, no explanation, no markdown fences.
            - Follow these conventions strictly:
            {_conventions()[:4000]}
            - Preserve all existing functionality unless the change requires removing it.
            - Add type annotations to all new Python functions.
            - No hardcoded secrets or credentials.
        """).strip()

        existing_block = (
            f"### Existing content of `{file_path}`:\n```\n{existing_content[:8000]}\n```"
            if existing_content
            else f"### `{file_path}` does not exist yet — create it from scratch."
        )

        user = textwrap.dedent(f"""
            ## Issue #{self.issue.iid}: {self.issue.title}

            {self.issue.description or ''}

            ## Implementation steps:
            {steps_text}

            ## File to modify: `{file_path}`

            {existing_block}

            Generate the complete new content of `{file_path}`.
        """).strip()

        result = await _chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.05,
            max_tokens=max_tokens,
        )

        # Strip any accidental markdown code fences the model may have added
        result = re.sub(r"^```[a-z]*\n", "", result.strip())
        result = re.sub(r"\n```$", "", result.strip())
        return result if result.strip() else None

    async def _validate_syntax(self, file_path: str, content: str) -> bool:
        if file_path.endswith(".py"):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
                f.write(content)
                tmp = f.name
            rc, _, _ = await _shell(f"python3 -m py_compile {tmp!r}")
            os.unlink(tmp)
            return rc == 0
        if file_path.endswith(".sh"):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".sh", mode="w", delete=False) as f:
                f.write(content)
                tmp = f.name
            rc, _, _ = await _shell(f"bash -n {tmp!r}")
            os.unlink(tmp)
            return rc == 0
        return True  # no validator for yml/ts/json — handled by CI

    async def _fix_syntax(self, file_path: str, broken_content: str) -> str:
        """Ask the LLM to fix a syntax error in a generated file."""
        result = await _chat(
            [
                {
                    "role": "system",
                    "content": "Fix the Python syntax errors in this code. Return ONLY the corrected code, no explanations.",
                },
                {
                    "role": "user",
                    "content": f"```python\n{broken_content[:6000]}\n```",
                },
            ],
            temperature=0.0,
            max_tokens=6144,
        )
        result = re.sub(r"^```[a-z]*\n", "", result.strip())
        result = re.sub(r"\n```$", "", result.strip())
        return result

    def _build_commit_message(self, plan: IssuePlan) -> str:
        issue_type = "feat"
        for lbl in self.issue.labels:
            if lbl.startswith("type::"):
                t = lbl[len("type::"):]
                # Conventional commits mapping
                issue_type = {
                    "bug": "fix", "feature": "feat", "chore": "chore",
                    "docs": "docs", "security": "fix", "refactor": "refactor",
                    "training": "feat",
                }.get(t, "feat")
                break
        slug = self._slug[:60]
        steps = "\n".join(f"- {s}" for s in plan.implementation_steps[:5])
        return (
            f"{issue_type}({slug}): close #{self.issue.iid}\n\n"
            f"{steps}\n\n"
            f"Generated by Qwen3.5 agent loop.\n"
            f"GitLab: {self.issue.web_url}"
        )

    async def _setup_git(self) -> None:
        await _shell(f'git config user.name {json.dumps(_GIT_AUTHOR_NAME)}')
        await _shell(f'git config user.email {json.dumps(_GIT_AUTHOR_EMAIL)}')
        await _shell("git fetch origin main --quiet")
        await _shell("git checkout main --quiet")
        await _shell("git reset --hard origin/main --quiet")

    # ── Push + MR ─────────────────────────────────────────────────────────────

    async def push_and_create_mr(self, build_result: BuildResult) -> BuildResult:
        """Push branch to GitLab and create a Merge Request."""
        from .gitlab_client import add_comment

        token = os.getenv("GITLAB_API_TOKEN") or os.getenv(
            "GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN", ""
        )
        # Inject token into remote URL for push
        remote_with_token = _GITLAB_REMOTE.replace(
            "http://", f"http://oauth2:{token}@"
        )
        rc, _, err = await _shell(
            f"git push {remote_with_token!r} {self._branch}:refs/heads/{self._branch} --force-with-lease"
        )
        if rc != 0:
            raise RuntimeError(f"git push failed: {err}")

        # Create MR via GitLab API
        mr = await self._create_mr(build_result)
        build_result.mr_iid = mr.get("iid")
        build_result.mr_url = mr.get("web_url", "")

        await add_comment(
            self.issue.iid,
            f"🔀 Merge Request created: {build_result.mr_url}",
        )
        return build_result

    async def _create_mr(self, build_result: BuildResult) -> dict:
        from .gitlab_client import _base_url, _headers, _project_id
        steps = "\n".join(f"- {f}" for f in build_result.changed_files)
        body = {
            "source_branch": self._branch,
            "target_branch": "main",
            "title": f"Agent: close #{self.issue.iid} — {self.issue.title}",
            "description": (
                f"Closes #{self.issue.iid}\n\n"
                f"**Changed files:**\n{steps}\n\n"
                f"**Commit:** `{build_result.commit_sha}`\n\n"
                f"Generated by Qwen3.5 autonomous agent loop."
            ),
            "remove_source_branch": True,
            "squash": False,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_base_url()}/api/v4/projects/{_project_id()}/merge_requests",
                json=body,
                headers=_headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def merge_mr(self, build_result: BuildResult) -> None:
        """Auto-merge the MR (for chore/docs issue types)."""
        from .gitlab_client import _base_url, _headers, _project_id, complete_issue
        if not build_result.mr_iid:
            return
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(
                f"{_base_url()}/api/v4/projects/{_project_id()}/merge_requests/{build_result.mr_iid}/merge",
                headers=_headers(),
                json={"squash": False, "should_remove_source_branch": True},
            )
            if resp.status_code not in (200, 201, 405):
                logger.warning("MR merge returned %d: %s", resp.status_code, resp.text[:200])

        await complete_issue(
            self.issue.iid,
            summary=(
                f"✅ Auto-merged MR {build_result.mr_url}\n\n"
                f"Changed files: {', '.join(build_result.changed_files)}"
            ),
        )

    async def set_ready_for_review(self, build_result: BuildResult) -> None:
        """Move issue to in-review state for human gate."""
        from .gitlab_client import update_issue
        await update_issue(
            self.issue.iid,
            labels=",".join(
                [lbl for lbl in self.issue.labels if not lbl.startswith("status::")]
                + ["status::in-review"]
            ),
        )
        from .gitlab_client import add_comment
        await add_comment(
            self.issue.iid,
            f"✅ Agent work complete. MR ready for human review: {build_result.mr_url}\n\n"
            "Move to `status::done` and merge when satisfied.",
        )
