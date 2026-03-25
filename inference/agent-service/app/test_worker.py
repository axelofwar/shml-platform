"""
Test Worker — generates missing tests and runs pytest in the workspace.

Workflow:
  1. Scan changed files for test coverage gaps
  2. Generate pytest tests via Qwen3.5 (using existing tests as few-shot)
  3. Run pytest inside NemoClaw sandbox (or workspace root)
  4. Feed failures back to Qwen3.5 for fixes (up to max_fix_retries)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import textwrap
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_CODING_URL = os.getenv("QWEN_CODING_URL", "http://qwen-coding:8000/v1")
_CODING_MODEL = os.getenv("CODING_MODEL_NAME", "qwen3.5-coder")
_WORKSPACE_ROOT = os.getenv("AGENT_WORKSPACE_ROOT", "/workspace")
_PYTEST_TIMEOUT = int(os.getenv("AGENT_PYTEST_TIMEOUT", "120"))


# ── Domain models ──────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    passed: bool
    test_count: int
    passed_count: int
    failed_count: int
    error_count: int
    summary: str
    failures: list[str] = field(default_factory=list)
    generated_test_files: list[str] = field(default_factory=list)


# ── Shell helper (same contract as code_worker) ───────────────────────────────

async def _shell(cmd: str, cwd: Optional[str] = None, timeout: int = 60) -> tuple[int, str, str]:
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
        return 1, "", f"Command timed out after {timeout}s"
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def _chat(messages: list[dict], temperature: float = 0.1, max_tokens: int = 4096) -> str:
    import httpx
    payload = {
        "model": _CODING_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{_CODING_URL}/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# ── Few-shot loader ─────────────────────────────────────────────────────────

async def _load_few_shot_tests(n: int = 2) -> str:
    """Load a few existing test files as examples for the LLM."""
    test_dirs = [
        os.path.join(_WORKSPACE_ROOT, "inference", "agent-service", "tests"),
        os.path.join(_WORKSPACE_ROOT, "tests"),
    ]
    examples: list[str] = []
    for tdir in test_dirs:
        if not os.path.isdir(tdir):
            continue
        for fname in sorted(os.listdir(tdir)):
            if fname.startswith("test_") and fname.endswith(".py") and len(examples) < n:
                path = os.path.join(tdir, fname)
                with open(path) as f:
                    content = f.read(2000)
                examples.append(f"### {fname}\n```python\n{content}\n```")
        if len(examples) >= n:
            break
    return "\n\n".join(examples)


# ── Coverage gap detector ─────────────────────────────────────────────────────

def _infer_test_path(source_path: str) -> str:
    """Given a source file path, return the expected test file path."""
    # inference/agent-service/app/foo.py → inference/agent-service/tests/test_foo.py
    parts = source_path.replace("\\", "/").split("/")
    filename = parts[-1]
    test_name = f"test_{filename}"
    # Walk upward to find an 'app' or 'src' parent, replace with 'tests'
    for i, part in enumerate(parts):
        if part in ("app", "src", "lib"):
            new_parts = parts[:i] + ["tests"] + [test_name]
            return "/".join(new_parts)
    # Fallback: put at workspace-root tests/
    return f"tests/{test_name}"


# ── TestWorker ────────────────────────────────────────────────────────────────

class TestWorker:
    """Generates missing tests and runs pytest for a completed build."""

    def __init__(self, issue: object, build_result: object) -> None:
        self.issue = issue
        self.build_result = build_result

    async def run(self, max_fix_retries: int = 3) -> TestResult:
        """Full test cycle: generate → run → fix loop."""
        generated = await self._generate_missing_tests()

        # Stage git-add any generated test files so pytest can find them
        for tf in generated:
            full = os.path.join(_WORKSPACE_ROOT, tf)
            if os.path.exists(full):
                await _shell(f"git add {full!r}")

        # Run tests
        result = await self._run_pytest()

        # Fix-retry loop
        for attempt in range(1, max_fix_retries + 1):
            if result.passed or not result.failures:
                break
            logger.info(
                "Test attempt %d/%d — %d failures; requesting fixes",
                attempt, max_fix_retries, result.failed_count,
            )
            await self._fix_failures(result.failures)
            result = await self._run_pytest()

        result.generated_test_files = generated
        return result

    # ── Test generation ───────────────────────────────────────────────────────

    async def _generate_missing_tests(self) -> list[str]:
        """For each changed Python file, generate a test file if one doesn't exist."""
        generated: list[str] = []
        few_shot = await _load_few_shot_tests()

        for source_path in getattr(self.build_result, "changed_files", []):
            if not source_path.endswith(".py"):
                continue
            test_path = _infer_test_path(source_path)
            full_test_path = os.path.join(_WORKSPACE_ROOT, test_path)
            if os.path.exists(full_test_path):
                continue  # test file already exists

            source_content = ""
            full_source = os.path.join(_WORKSPACE_ROOT, source_path)
            if os.path.exists(full_source):
                with open(full_source) as f:
                    source_content = f.read(6000)

            if not source_content:
                continue

            test_code = await self._generate_test_file(
                source_path, source_content, test_path, few_shot
            )
            if test_code:
                os.makedirs(os.path.dirname(full_test_path), exist_ok=True)
                with open(full_test_path, "w") as f:
                    f.write(test_code)
                generated.append(test_path)
                logger.info("Generated test file: %s", test_path)

        return generated

    async def _generate_test_file(
        self,
        source_path: str,
        source_content: str,
        test_path: str,
        few_shot: str,
    ) -> Optional[str]:
        system = textwrap.dedent("""
            You are an expert Python test engineer. Generate a pytest test file for the given source.

            Rules:
            - Use pytest and pytest-asyncio for async functions.
            - Mock external I/O (HTTP calls, database, filesystem) with unittest.mock.
            - Include at least one test per public function / class method.
            - Do NOT hardcode any secrets, tokens, or real credentials.
            - Return ONLY the Python code for the test file. No explanations.
        """).strip()

        prompt = textwrap.dedent(f"""
            ## Source file: `{source_path}`
            ```python
            {source_content}
            ```

            ## Existing test examples in this project:
            {few_shot}

            Generate the test file `{test_path}`.
        """).strip()

        raw = await _chat(
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            temperature=0.1,
        )
        raw = re.sub(r"^```[a-z]*\n", "", raw.strip())
        raw = re.sub(r"\n```$", "", raw.strip())
        return raw if "def test_" in raw else None

    # ── pytest runner ─────────────────────────────────────────────────────────

    async def _run_pytest(self) -> TestResult:
        """Run pytest against changed files and return structured results."""
        # Determine test scope — run tests related to changed files
        test_targets = self._resolve_test_targets()
        target_str = " ".join(f"{t!r}" for t in test_targets) if test_targets else ""
        cmd = f"python3 -m pytest {target_str} -v --tb=short --timeout={_PYTEST_TIMEOUT} 2>&1"

        rc, output, _ = await _shell(cmd, timeout=_PYTEST_TIMEOUT + 30)

        return _parse_pytest_output(output, rc)

    def _resolve_test_targets(self) -> list[str]:
        """Return test file paths to run based on changed sources."""
        targets: list[str] = []
        for src in getattr(self.build_result, "changed_files", []):
            tp = _infer_test_path(src)
            full = os.path.join(_WORKSPACE_ROOT, tp)
            if os.path.exists(full):
                targets.append(tp)
        return targets or ["tests/", "inference/agent-service/tests/"]

    # ── Fix loop ──────────────────────────────────────────────────────────────

    async def _fix_failures(self, failures: list[str]) -> None:
        """Ask Qwen3.5 to fix failing tests by patching the source files."""
        changed_sources = [
            f for f in getattr(self.build_result, "changed_files", [])
            if f.endswith(".py")
        ]
        if not changed_sources:
            return

        # Find which source is most likely implicated
        for source_path in changed_sources[:3]:
            full = os.path.join(_WORKSPACE_ROOT, source_path)
            if not os.path.exists(full):
                continue
            with open(full) as f:
                existing = f.read(6000)

            failure_block = "\n\n".join(failures[:5])
            system = textwrap.dedent("""
                You are fixing Python code that has failing tests.
                Return ONLY the corrected file content. No explanations, no markdown fences.
            """).strip()
            user = textwrap.dedent(f"""
                ## File: `{source_path}`
                ```python
                {existing}
                ```

                ## Failing tests:
                {failure_block}

                Fix the source code so the tests pass.
            """).strip()

            fixed = await _chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.0,
            )
            fixed = re.sub(r"^```[a-z]*\n", "", fixed.strip())
            fixed = re.sub(r"\n```$", "", fixed.strip())
            if fixed.strip():
                with open(full, "w") as f:
                    f.write(fixed)
                await _shell(f"git add {full!r}")

        # Re-commit fixes
        _, _, _ = await _shell(
            f'git commit -m "fix: test failures for issue #{getattr(self.issue, "iid", "?")}" --allow-empty'
        )


# ── pytest output parser ──────────────────────────────────────────────────────

def _parse_pytest_output(output: str, returncode: int) -> TestResult:
    """Parse pytest's stdout into a structured TestResult."""
    passed_count = 0
    failed_count = 0
    error_count = 0
    test_count = 0
    failures: list[str] = []

    # Summary line: "5 passed, 2 failed, 1 error in 3.45s"
    summary_match = re.search(
        r"(\d+) passed(?:, (\d+) failed)?(?:, (\d+) error)?",
        output,
        re.IGNORECASE,
    )
    if summary_match:
        passed_count = int(summary_match.group(1) or 0)
        failed_count = int(summary_match.group(2) or 0)
        error_count = int(summary_match.group(3) or 0)
        test_count = passed_count + failed_count + error_count

    # no tests collected
    if "no tests ran" in output.lower() or "no tests collected" in output.lower():
        return TestResult(
            passed=True,
            test_count=0,
            passed_count=0,
            failed_count=0,
            error_count=0,
            summary="No tests collected — tests will be gated by CI.",
        )

    # Extract failure blocks
    failure_blocks = re.findall(
        r"_{5,}.*?_{5,}|FAILED .+?(?=\nFAILED|\n={5,}|\Z)",
        output,
        re.DOTALL,
    )
    failures = [fb.strip()[:2000] for fb in failure_blocks[:10]]

    summary_line = output.split("\n")[-2] if "\n" in output else output[:200]

    return TestResult(
        passed=returncode == 0,
        test_count=test_count,
        passed_count=passed_count,
        failed_count=failed_count,
        error_count=error_count,
        summary=summary_line.strip(),
        failures=failures,
    )
