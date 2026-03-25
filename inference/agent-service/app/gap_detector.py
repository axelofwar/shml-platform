"""
Gap Detector — scans the workspace after a successful merge and identifies
integration gaps that should become new GitLab issues.

Scans for:
  1. Broken Python imports in changed files
  2. New Python modules that lack test files
  3. Docker Compose services missing healthchecks
  4. Traefik router labels missing priority=2147483647
  5. New SKILL.md files without a tests/ example
  6. Environment variables used in code but absent from docker-compose.yml
  7. Security patterns (hardcoded secrets, shell=True, etc.)

Each gap → a GitLab issue with source::agent label.
"""
from __future__ import annotations

import ast
import logging
import os
import re
import textwrap
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = os.getenv("AGENT_WORKSPACE_ROOT", "/workspace")
_CODING_URL = os.getenv("QWEN_CODING_URL", "http://qwen-coding:8000/v1")
_CODING_MODEL = os.getenv("CODING_MODEL_NAME", "qwen3.5-coder")


@dataclass
class Gap:
    title: str
    description: str
    labels: list[str]
    component: str = "infra"
    priority: str = "low"


class GapDetector:
    """Scans the workspace and opens GitLab issues for found integration gaps."""

    def __init__(self) -> None:
        self._gaps: list[Gap] = []

    async def scan_after_merge(self, changed_files: list[str]) -> list[Gap]:
        """Entry point: run all scanners, return list of gaps found and created."""
        self._gaps = []

        for source_path in changed_files:
            full = os.path.join(_WORKSPACE_ROOT, source_path)
            if not os.path.exists(full):
                continue
            with open(full, errors="replace") as f:
                content = f.read()

            if source_path.endswith(".py"):
                self._check_broken_imports(source_path, content)
                self._check_missing_tests(source_path)
                self._check_security_patterns(source_path, content)
                self._check_unset_env_vars(source_path, content, changed_files)

            if source_path.endswith((".yml", ".yaml")):
                self._check_compose_healthchecks(source_path, content)
                self._check_traefik_priority(source_path, content)

            if source_path.endswith("SKILL.md"):
                self._check_skill_examples(source_path, content)

        # LLM deep scan for semantic gaps (async, runs on all changed files together)
        await self._llm_deep_scan(changed_files)

        # Create GitLab issues for all found gaps
        created_issues = await self._create_issues()
        return created_issues

    # ── Deterministic scanners ────────────────────────────────────────────────

    def _check_broken_imports(self, path: str, content: str) -> None:
        """Detect imports that reference modules not existing in workspace."""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module_path = node.module.replace(".", "/")
                # Only check relative-style intra-project imports
                if not module_path.startswith((".", "app", "inference")):
                    continue
                full_candidate = os.path.join(_WORKSPACE_ROOT, module_path + ".py")
                pkg_candidate = os.path.join(_WORKSPACE_ROOT, module_path, "__init__.py")
                if not os.path.exists(full_candidate) and not os.path.exists(pkg_candidate):
                    self._gaps.append(Gap(
                        title=f"Broken import `{node.module}` in `{path}`",
                        description=(
                            f"`{path}` imports `{node.module}` which does not exist in the workspace.\n\n"
                            f"Either create the module or fix the import path.\n\n"
                            f"Detected by agent gap scanner after merge."
                        ),
                        labels=["type::bug", "priority::high", "source::agent", f"component::infra"],
                        priority="high",
                    ))

    def _check_missing_tests(self, source_path: str) -> None:
        """Flag Python source files that have no corresponding test file."""
        # Only flag app/ and inference/ modules, not test files themselves
        if "test_" in os.path.basename(source_path):
            return
        # Infer test path
        parts = source_path.replace("\\", "/").split("/")
        filename = parts[-1]
        test_name = f"test_{filename}"
        for i, part in enumerate(parts):
            if part in ("app", "src", "lib"):
                test_path = "/".join(parts[:i] + ["tests", test_name])
                break
        else:
            test_path = f"tests/{test_name}"

        full_test = os.path.join(_WORKSPACE_ROOT, test_path)
        if not os.path.exists(full_test):
            self._gaps.append(Gap(
                title=f"Missing tests for `{source_path}`",
                description=(
                    f"`{source_path}` has no corresponding test file at `{test_path}`.\n\n"
                    "Create pytest tests covering all public functions and error paths.\n\n"
                    "Detected by agent gap scanner after merge."
                ),
                labels=["type::chore", "priority::low", "source::agent", "component::infra"],
                priority="low",
            ))

    def _check_security_patterns(self, path: str, content: str) -> None:
        """Simple static scan for common security issues."""
        patterns = [
            (r'subprocess\.call\(.*shell=True', "shell=True in subprocess (command injection risk)"),
            (r'subprocess\.Popen\(.*shell=True', "shell=True in subprocess Popen"),
            (r'eval\s*\(', "eval() usage (code injection risk)"),
            (r'SECRET_KEY\s*=\s*["\'][^$\{]{6,}', "Hardcoded SECRET_KEY"),
            (r'PASSWORD\s*=\s*["\'][^$\{]{4,}', "Hardcoded PASSWORD"),
            (r'API_KEY\s*=\s*["\'][A-Za-z0-9_\-]{16,}', "Possibly hardcoded API key"),
        ]
        for pattern, description in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                self._gaps.append(Gap(
                    title=f"Security: {description} in `{path}`",
                    description=(
                        f"Detected `{pattern}` in `{path}`.\n\n"
                        f"{description}\n\n"
                        "Review and remediate per OWASP guidelines.\n\n"
                        "Detected by agent security scanner."
                    ),
                    labels=["type::security", "priority::high", "source::agent", "component::infra"],
                    priority="high",
                    component="infra",
                ))

    def _check_unset_env_vars(
        self, path: str, content: str, all_changed: list[str]
    ) -> None:
        """Flag os.getenv/os.environ calls not present in docker-compose env sections."""
        env_refs = set(re.findall(r'os\.(?:getenv|environ)\[?\(?["\']([A-Z][A-Z0-9_]{3,})', content))
        if not env_refs:
            return

        # Find nearest docker-compose.yml
        dir_parts = path.split("/")
        compose_candidates = []
        for depth in range(1, len(dir_parts)):
            candidate = "/".join(dir_parts[:depth]) + "/docker-compose.yml"
            full = os.path.join(_WORKSPACE_ROOT, candidate)
            if os.path.exists(full):
                compose_candidates.append(full)

        compose_env_vars: set[str] = set()
        for compose_path in compose_candidates:
            with open(compose_path) as f:
                compose_env_vars.update(re.findall(r"\b([A-Z][A-Z0-9_]{3,})(?:=|\b)", f.read()))

        missing = env_refs - compose_env_vars - {
            # well-known vars that are always set
            "HOME", "PATH", "PWD", "USER", "LOGNAME", "TERM",
            "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED",
        }
        for var in sorted(missing):
            self._gaps.append(Gap(
                title=f"Undocumented env var `{var}` used in `{path}`",
                description=(
                    f"`{path}` references `{var}` via `os.getenv`/`os.environ`, "
                    f"but this variable is not declared in the nearest docker-compose.yml.\n\n"
                    "Add it to the `environment:` section with a safe default or reference to `.env`.\n\n"
                    "Detected by agent env-var scanner."
                ),
                labels=["type::chore", "priority::low", "source::agent", "component::infra"],
                priority="low",
            ))

    def _check_compose_healthchecks(self, path: str, content: str) -> None:
        """Flag Docker Compose services that are missing healthcheck blocks."""
        services_block = re.search(r"^services:(.*)", content, re.DOTALL | re.MULTILINE)
        if not services_block:
            return
        # Split by 2-space service names at indent level 2
        service_sections = re.split(r"\n  (\w[\w-]+):\n", services_block.group(1))
        for section in service_sections:
            if "image:" in section or "build:" in section:
                if "healthcheck:" not in section:
                    service_name_match = re.search(r"\b([\w-]+):\s*\n\s+(?:image|build):", section)
                    name = service_name_match.group(1) if service_name_match else "unknown"
                    self._gaps.append(Gap(
                        title=f"Service `{name}` in `{path}` missing healthcheck",
                        description=(
                            f"Service `{name}` in `{path}` has no `healthcheck:` block.\n\n"
                            "Add a healthcheck so `start_all_safe.sh` can validate readiness:\n"
                            "```yaml\nhealthcheck:\n  test: [\"CMD\", \"curl\", \"-f\", \"http://localhost:8000/health\"]\n"
                            "  interval: 30s\n  timeout: 10s\n  retries: 3\n  start_period: 60s\n```\n\n"
                            "Detected by agent gap scanner."
                        ),
                        labels=["type::chore", "priority::low", "source::agent", "component::infra"],
                    ))

    def _check_traefik_priority(self, path: str, content: str) -> None:
        """Flag Traefik router labels missing max-priority guard."""
        if "traefik.http.routers" not in content:
            return
        # Find router rules without a matching priority label
        rules = re.findall(r'traefik\.http\.routers\.([\w-]+)\.rule', content)
        for router in rules:
            priority_pattern = f"traefik.http.routers.{router}.priority"
            if priority_pattern not in content:
                self._gaps.append(Gap(
                    title=f"Traefik router `{router}` missing priority label in `{path}`",
                    description=(
                        f"Router `{router}` in `{path}` has no priority label.\n\n"
                        "Without `priority=2147483647` the Traefik internal API may intercept "
                        "requests to `/api/*` routes. Add:\n"
                        f"```yaml\n- traefik.http.routers.{router}.priority=2147483647\n```\n\n"
                        "Detected by agent Traefik scanner."
                    ),
                    labels=["type::bug", "priority::medium", "source::agent", "component::infra"],
                    priority="medium",
                ))

    def _check_skill_examples(self, path: str, content: str) -> None:
        """Flag SKILL.md files that lack a learning-series or examples section."""
        if "## Examples" not in content and "## Learning Series" not in content:
            skill_name = path.split("/")[-2] if "/" in path else path
            self._gaps.append(Gap(
                title=f"SKILL.md `{skill_name}` missing Examples / Learning Series section",
                description=(
                    f"`{path}` has no `## Examples` or `## Learning Series` section.\n\n"
                    "Add at least one working code example and a 'What I learned' entry so "
                    "the GEPA engine can evolve this skill over time.\n\n"
                    "Detected by agent gap scanner."
                ),
                labels=["type::docs", "priority::low", "source::agent", "component::agent-service"],
            ))

    # ── LLM deep scan ────────────────────────────────────────────────────────

    async def _llm_deep_scan(self, changed_files: list[str]) -> None:
        """Ask Qwen3.5 to identify semantic gaps not caught by static analysis."""
        if not changed_files:
            return

        # Build a small summary of changed file paths
        file_list = "\n".join(f"- `{f}`" for f in changed_files[:20])

        system = textwrap.dedent("""
            You are a senior platform engineer reviewing a set of recently changed files.
            Identify integration gaps, missing connections, or follow-up work needed.

            Return a JSON array of objects:
            [{"title": "short title", "description": "details", "priority": "low|medium|high",
              "component": "infra|agent-service|chat-ui|..."}]

            Return at most 5 gaps. Return ONLY the JSON array.
            If there are no significant gaps, return [].
        """).strip()

        user = f"## Changed files in this merge:\n{file_list}"

        try:
            payload = {
                "model": _CODING_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "max_tokens": 1024,
                "stream": False,
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{_CODING_URL}/chat/completions", json=payload)
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]

            raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
            raw = re.sub(r"\n?```$", "", raw.strip())
            import json
            items = json.loads(raw)
            if not isinstance(items, list):
                return
            for item in items[:5]:
                if not isinstance(item, dict) or not item.get("title"):
                    continue
                self._gaps.append(Gap(
                    title=item["title"],
                    description=item.get("description", ""),
                    labels=[
                        "type::chore",
                        f"priority::{item.get('priority', 'low')}",
                        "source::agent",
                        f"component::{item.get('component', 'infra')}",
                    ],
                    priority=item.get("priority", "low"),
                    component=item.get("component", "infra"),
                ))
        except Exception as exc:
            logger.debug("LLM deep gap scan failed: %s", exc)

    # ── Issue creation ────────────────────────────────────────────────────────

    async def _create_issues(self) -> list[Gap]:
        """Create GitLab issues for each unique gap found."""
        if not self._gaps:
            return []
        from .gitlab_client import create_issue, list_issues

        # Dedup — don't create issues with identical titles
        try:
            existing: list[Any] = await list_issues(state="opened", limit=100)
            existing_titles = {i.title.lower() for i in existing}
        except Exception:
            existing_titles = set()

        created: list[Gap] = []
        for gap in self._gaps:
            if gap.title.lower() in existing_titles:
                logger.debug("Gap already has open issue: %s", gap.title)
                continue
            try:
                await create_issue(
                    title=gap.title,
                    description=gap.description,
                    labels=gap.labels,
                )
                created.append(gap)
                logger.info("Created gap issue: %s", gap.title)
            except Exception as exc:
                logger.warning("Failed to create gap issue '%s': %s", gap.title, exc)

        return created
