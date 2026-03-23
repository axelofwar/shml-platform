"""T9: Platform wiring tests — regression guards for infrastructure plumbing.

These tests validate that:
1. All docker compose paths referenced in start_all_safe.sh exist on disk (G1 regression)
2. All required __init__.py files exist for Python packages
3. deploy/compose directory has expected files
4. .env.example does NOT contain hardcoded secrets (pattern check)
5. start_all_safe.sh is executable
6. Taskfile has expected task names
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    with open(path) as f:
        return f.read()


# ---------------------------------------------------------------------------
# T9.1: start_all_safe.sh compose path regression (G1 guard)
# ---------------------------------------------------------------------------


class TestStartAllSafeComposePaths:
    """Regression: every compose -f <path> in start_all_safe.sh must exist."""

    @pytest.fixture(scope="class")
    def compose_paths(self):
        script = REPO_ROOT / "start_all_safe.sh"
        if not script.exists():
            pytest.skip("start_all_safe.sh not found")
        content = _read(script)
        # Extract all paths passed to `docker compose -f <path>` or `docker-compose -f <path>`
        # Require the path to look like a file path (contains / or .yml)
        pattern = re.compile(
            r"docker(?:-compose|\s+compose)\b[^\n]*?-f\s+([\./][^\s|&;\n\"']+\.yml)"
        )
        paths = pattern.findall(content)
        # Also catch quoted paths that end in .yml
        pattern2 = re.compile(r'-f\s+"([^"]+\.yml)"|-f\s+\'([^\']+\.yml)\'')
        for a, b in pattern2.findall(content):
            paths.append(a or b)
        return [p.strip() for p in paths if p.strip()]

    def test_at_least_one_compose_path_found(self, compose_paths):
        assert len(compose_paths) > 5, "Expected many compose paths in start_all_safe.sh"

    def test_all_compose_paths_exist_on_disk(self, compose_paths):
        missing = []
        for raw_path in compose_paths:
            # Strip shell variable prefixes like ${COMPOSE_DIR}/
            cleaned = re.sub(r"\$\{[^}]+\}/", "", raw_path)
            cleaned = re.sub(r"\$[A-Z_]+/", "", cleaned)
            if cleaned.startswith("$") or not cleaned:
                continue
            full = REPO_ROOT / cleaned
            if not full.exists():
                missing.append(cleaned)
        assert missing == [], f"Missing compose files referenced in start_all_safe.sh:\n" + "\n".join(missing)


# ---------------------------------------------------------------------------
# T9.2: Python package __init__.py presence
# ---------------------------------------------------------------------------


class TestPackageInits:
    """Required __init__.py files must exist."""

    REQUIRED_INITS = [
        "libs/__init__.py",
        "inference/__init__.py",
        "ray_compute/jobs/inference/__init__.py",
        "ray_compute/jobs/features/__init__.py",
        "tests/unit/__init__.py",
        "tests/unit/libs/__init__.py",
        "tests/unit/inference/__init__.py",
        "tests/unit/ray_compute/__init__.py",
    ]

    @pytest.mark.parametrize("rel_path", REQUIRED_INITS)
    def test_init_exists(self, rel_path):
        full = REPO_ROOT / rel_path
        assert full.exists(), f"Missing required __init__.py: {rel_path}"


# ---------------------------------------------------------------------------
# T9.3: deploy/compose directory contains key stacks
# ---------------------------------------------------------------------------


class TestDeployCompose:
    """deploy/compose must contain the primary docker-compose stacks."""

    EXPECTED_COMPOSE_FILES = [
        "deploy/compose/docker-compose.infra.yml",
        "deploy/compose/docker-compose.auth.yml",
        "deploy/compose/docker-compose.core.yml",
    ]

    @pytest.mark.parametrize("rel_path", EXPECTED_COMPOSE_FILES)
    def test_compose_file_exists(self, rel_path):
        full = REPO_ROOT / rel_path
        assert full.exists(), f"Expected compose file missing: {rel_path}"


# ---------------------------------------------------------------------------
# T9.4: .env.example does not contain hardcoded secrets
# ---------------------------------------------------------------------------


class TestEnvExample:
    """Check that .env.example uses placeholder values, not real secrets."""

    SECRET_PATTERNS = [
        r'(?i)password[ \t]*=[ \t]*[A-Za-z0-9+/]{16,}',
        r'(?i)secret[ \t]*=[ \t]*[A-Za-z0-9+/]{16,}',
        r'(?i)api_key[ \t]*=[ \t]*[A-Za-z0-9_\-]{20,}',
        r'sk-[A-Za-z0-9]{20,}',
    ]

    @pytest.fixture(scope="class")
    def env_example_content(self):
        env_file = REPO_ROOT / ".env.example"
        if not env_file.exists():
            pytest.skip(".env.example not found")
        return _read(env_file)

    def test_no_hardcoded_passwords(self, env_example_content):
        for pattern in self.SECRET_PATTERNS:
            matches = re.findall(pattern, env_example_content)
            # Allow ${VAR} substitution patterns
            real = [m for m in matches if not re.search(r'\$\{', m)]
            assert real == [], f"Potential hardcoded secret found in .env.example: {real}"


# ---------------------------------------------------------------------------
# T9.5: start_all_safe.sh is executable
# ---------------------------------------------------------------------------


class TestScriptPermissions:
    """start_all_safe.sh and stop_all.sh must be executable."""

    @pytest.mark.parametrize("script", ["start_all_safe.sh", "stop_all.sh"])
    def test_script_is_executable(self, script):
        path = REPO_ROOT / script
        if not path.exists():
            pytest.skip(f"{script} not found")
        mode = os.stat(path).st_mode
        assert bool(mode & stat.S_IXUSR), f"{script} is not executable"


# ---------------------------------------------------------------------------
# T9.6: Taskfile has expected task names
# ---------------------------------------------------------------------------


class TestTaskfileStructure:
    """Key task names must be present in Taskfile.yml."""

    EXPECTED_TASKS = ["status", "start", "stop", "restart"]

    @pytest.fixture(scope="class")
    def taskfile_content(self):
        tf = REPO_ROOT / "Taskfile.yml"
        if not tf.exists():
            pytest.skip("Taskfile.yml not found")
        return _read(tf)

    @pytest.mark.parametrize("task_name", EXPECTED_TASKS)
    def test_task_name_present(self, task_name, taskfile_content):
        assert task_name in taskfile_content, f"Task '{task_name}' missing from Taskfile.yml"


# ---------------------------------------------------------------------------
# T9.7: Coverage config exists
# ---------------------------------------------------------------------------


class TestCoverageConfig:
    """.coveragerc must exist and have a [run] source section."""

    def test_coveragerc_exists(self):
        assert (REPO_ROOT / ".coveragerc").exists()

    def test_coveragerc_has_run_section(self):
        content = _read(REPO_ROOT / ".coveragerc")
        assert "[run]" in content

    def test_coveragerc_includes_libs(self):
        content = _read(REPO_ROOT / ".coveragerc")
        assert "libs" in content
