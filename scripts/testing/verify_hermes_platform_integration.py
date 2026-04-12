#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml


HERMES_HOME = Path.home() / ".hermes"
HERMES_CONFIG = HERMES_HOME / "config.yaml"
HERMES_SOUL = HERMES_HOME / "SOUL.md"
HERMES_REPO = HERMES_HOME / "hermes-agent"
HERMES_PYTHON = HERMES_REPO / "venv" / "bin" / "python"
HERMES_CLI = HERMES_REPO / "hermes"
PLATFORM_ROOT = Path("/home/axelofwar/Projects/shml-platform")
NESTED_CONTEXT_CWD = PLATFORM_ROOT / "ray_compute"
PLATFORM_MCP_HEALTH = "http://127.0.0.1:8099/mcp/health"

EXPECTED_MCP_SERVERS = {
    "shml-platform",
    "gitlab",
    "prometheus",
    "obsidian-vault",
    "gitnexus",
}

EXPECTED_SKILLS = {
    "gitlab-integration",
    "platform-health",
    "platform-services",
    "ray-compute",
    "gpu-monitoring",
    "robotics-sim",
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def run_command(command: list[str], timeout: int = 120, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=os.environ.copy(),
    )


def hermes_command(*args: str) -> list[str]:
    return [str(HERMES_PYTHON), str(HERMES_CLI), *args]


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def check_config() -> CheckResult:
    if not HERMES_CONFIG.exists():
        return CheckResult("config", False, f"missing {HERMES_CONFIG}")
    config = load_yaml(HERMES_CONFIG)
    mcp_servers = set((config.get("mcp_servers") or {}).keys())
    missing_servers = sorted(EXPECTED_MCP_SERVERS - mcp_servers)
    external_dirs = set((config.get("skills") or {}).get("external_dirs") or [])
    required_dirs = {
        "/home/axelofwar/Projects/shml-platform/.github/skills",
        "/home/axelofwar/Projects/shml-platform/.claude/skills",
        "/home/axelofwar/Projects/shml-platform/inference/agent-service/skills",
    }
    missing_dirs = sorted(required_dirs - external_dirs)
    if missing_servers or missing_dirs:
        parts = []
        if missing_servers:
            parts.append(f"missing_mcp={missing_servers}")
        if missing_dirs:
            parts.append(f"missing_skill_dirs={missing_dirs}")
        return CheckResult("config", False, "; ".join(parts))
    return CheckResult("config", True, f"mcp_servers={sorted(mcp_servers)}")


def check_soul() -> CheckResult:
    if not HERMES_SOUL.exists():
        return CheckResult("soul", False, f"missing {HERMES_SOUL}")
    soul = HERMES_SOUL.read_text(encoding="utf-8")
    required_snippets = [
        "SHML projects",
        "local and private",
        "Only then use web search",
        "/home/axelofwar/Projects/shml-platform",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in soul]
    if missing:
        return CheckResult("soul", False, f"missing_snippets={missing}")
    return CheckResult("soul", True, "custom SHML identity present")


def check_prompt_builder() -> CheckResult:
    sys.path.insert(0, str(HERMES_REPO))
    from agent.prompt_builder import build_context_files_prompt, build_skills_system_prompt

    context = build_context_files_prompt(cwd=str(NESTED_CONTEXT_CWD), skip_soul=True)
    skills_prompt = build_skills_system_prompt()

    context_checks = {
        "AGENTS.md": "## AGENTS.md" in context,
        "Every Session": "Every Session" in context,
        "GitLab Issues": "GitLab Issues" in context,
    }
    missing_context = [name for name, ok in context_checks.items() if not ok]
    missing_skills = [name for name in sorted(EXPECTED_SKILLS) if name not in skills_prompt]

    if missing_context or missing_skills:
        parts = []
        if missing_context:
            parts.append(f"missing_context={missing_context}")
        if missing_skills:
            parts.append(f"missing_skills={missing_skills}")
        return CheckResult("prompt-builder", False, "; ".join(parts))

    return CheckResult("prompt-builder", True, "context hierarchy and skill visibility OK")


def check_platform_mcp_health() -> CheckResult:
    proc = run_command(["curl", "-sf", PLATFORM_MCP_HEALTH], timeout=30)
    if proc.returncode != 0:
        return CheckResult("platform-mcp-health", False, proc.stderr.strip() or proc.stdout.strip() or "curl failed")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return CheckResult("platform-mcp-health", False, f"invalid_json={exc}")
    if payload.get("status") != "healthy":
        return CheckResult("platform-mcp-health", False, f"payload={payload}")
    return CheckResult(
        "platform-mcp-health",
        True,
        f"tools_count={payload.get('tools_count')} training_active={payload.get('training_active')}",
    )


def check_mcp_list() -> CheckResult:
    proc = run_command(hermes_command("mcp", "list"), timeout=60)
    if proc.returncode != 0:
        return CheckResult("mcp-list", False, proc.stderr.strip() or proc.stdout.strip() or "hermes mcp list failed")
    output = proc.stdout
    missing = [name for name in sorted(EXPECTED_MCP_SERVERS) if name not in output]
    if missing:
        return CheckResult("mcp-list", False, f"missing={missing}")
    return CheckResult("mcp-list", True, "all expected MCP servers registered")


def check_mcp_test(server_name: str) -> CheckResult:
    proc = run_command(hermes_command("mcp", "test", server_name), timeout=120)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "test failed"
        return CheckResult(f"mcp-test:{server_name}", False, detail)
    if "Connected" not in proc.stdout:
        return CheckResult(f"mcp-test:{server_name}", False, "missing Connected marker")
    return CheckResult(f"mcp-test:{server_name}", True, "connected")


def check_local_first_smoke() -> CheckResult:
    query = "What does this repository's AGENTS.md say to do every session before anything else? Answer in two short bullets."
    transcript = Path("/tmp/hermes_local_first_smoke.txt")
    if transcript.exists():
        transcript.unlink()

    hermes_cli = shlex.quote(str(HERMES_CLI))
    command = (
        f"cd {shlex.quote(str(NESTED_CONTEXT_CWD))} && "
        f"{shlex.quote(str(HERMES_PYTHON))} {hermes_cli} chat -q {shlex.quote(query)} --max-turns 4"
    )
    proc = run_command(["timeout", "90s", "script", "-q", "-c", command, str(transcript)], timeout=120)
    if proc.returncode not in (0, 124) and not transcript.exists():
        return CheckResult("local-first-smoke", False, "script capture failed")
    if not transcript.exists():
        return CheckResult("local-first-smoke", False, "missing transcript")

    clean = re.sub(
        r"\x1b\[[0-9;?]*[ -/]*[@-~]",
        "",
        transcript.read_text(encoding="utf-8", errors="ignore"),
    ).replace("\r", "")

    used_web_search = "preparing web_search" in clean or " web_search" in clean
    used_read_file = "preparing read_file" in clean or "read      " in clean
    if used_web_search:
        return CheckResult("local-first-smoke", False, "unexpected web_search")
    if not used_read_file:
        return CheckResult("local-first-smoke", False, "did not use local file context")
    required_markers = ["AGENTS.md", "SOUL.md", "USER.md"]
    missing_markers = [marker for marker in required_markers if marker not in clean]
    if missing_markers:
        return CheckResult(
            "local-first-smoke",
            False,
            f"missing_response_markers={missing_markers}",
        )
    return CheckResult("local-first-smoke", True, "used local file context without web search")


def main() -> int:
    checks: list[Callable[[], CheckResult]] = [
        check_config,
        check_soul,
        check_prompt_builder,
        check_platform_mcp_health,
        check_mcp_list,
        lambda: check_mcp_test("shml-platform"),
        lambda: check_mcp_test("gitlab"),
        lambda: check_mcp_test("prometheus"),
        lambda: check_mcp_test("obsidian-vault"),
        lambda: check_mcp_test("gitnexus"),
        check_local_first_smoke,
    ]

    results = [check() for check in checks]

    failures = [result for result in results if not result.ok]
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
