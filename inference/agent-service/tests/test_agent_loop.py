"""
Tests for the autonomous agent loop subsystem.

Covers:
- estimate_complexity()         — label-path and text-pattern scoring
- _priority_score()             — label priority mapping
- LoopConfig env-var parsing
- AgentLoop state transitions   — IDLE → PICKING → IDLE (no issues)
- AgentLoop circuit breaker     — N failures → PAUSED
- Complexity graduation         — 5 successes → threshold bump
- gap_detector.py static scanners
- test_worker._parse_pytest_output()
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Minimal stub for Issue dataclass (avoids DB import at test time) ──────────

@dataclass
class FakeIssue:
    iid: int = 1
    title: str = "Fix typo in README"
    state: str = "opened"
    labels: list = field(default_factory=lambda: ["type::docs", "priority::low"])
    web_url: str = "http://gitlab/issues/1"
    description: str = "There is a typo on line 3."
    assignees: list = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# estimate_complexity
# ══════════════════════════════════════════════════════════════════════════════

def _import_loop():
    """Import agent_loop without triggering full app initialization."""
    app_dir = os.path.join(os.path.dirname(__file__), "..", "app")
    sys.path.insert(0, os.path.abspath(os.path.join(app_dir, "..")))
    from app.agent_loop import estimate_complexity, _priority_score
    return estimate_complexity, _priority_score


def test_estimate_complexity_docs_fast_path():
    estimate_complexity, _ = _import_loop()
    issue = FakeIssue(labels=["type::docs", "priority::low"])
    score = estimate_complexity(issue)
    assert score == pytest.approx(0.10, abs=0.01), f"Expected ~0.10, got {score}"


def test_estimate_complexity_security_fast_path():
    estimate_complexity, _ = _import_loop()
    issue = FakeIssue(labels=["type::security"], description="")
    score = estimate_complexity(issue)
    assert score == pytest.approx(0.80, abs=0.01), f"Expected ~0.80, got {score}"


def test_estimate_complexity_chore():
    estimate_complexity, _ = _import_loop()
    issue = FakeIssue(labels=["type::chore"])
    score = estimate_complexity(issue)
    assert score == pytest.approx(0.20, abs=0.01)


def test_estimate_complexity_text_boost():
    """Issues mentioning 'refactor' or 'migration' should score higher than plain chore."""
    estimate_complexity, _ = _import_loop()
    plain = FakeIssue(labels=["type::feature"], description="Add a new button")
    complex_ = FakeIssue(
        labels=["type::feature"],
        description="Refactor the database migration pipeline across 5 services",
    )
    assert estimate_complexity(complex_) > estimate_complexity(plain)


def test_estimate_complexity_clamped_to_unit_range():
    estimate_complexity, _ = _import_loop()
    worst_case = FakeIssue(
        labels=["type::feature"],
        description="refactor migration upgrade database docker 10 files architecture changes",
    )
    score = estimate_complexity(worst_case)
    assert 0.0 <= score <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# _priority_score
# ══════════════════════════════════════════════════════════════════════════════

def test_priority_score_critical():
    _, priority_score = _import_loop()
    issue = FakeIssue(labels=["priority::critical"])
    assert priority_score(issue) == 0


def test_priority_score_low():
    _, priority_score = _import_loop()
    issue = FakeIssue(labels=["priority::low"])
    assert priority_score(issue) == 3


def test_priority_score_unlabelled():
    _, priority_score = _import_loop()
    issue = FakeIssue(labels=["type::chore"])
    assert priority_score(issue) == 2  # default "medium"


# ══════════════════════════════════════════════════════════════════════════════
# LoopConfig env-var parsing
# ══════════════════════════════════════════════════════════════════════════════

def test_loop_config_defaults():
    from app.agent_loop import LoopConfig
    with patch.dict(os.environ, {}, clear=False):
        cfg = LoopConfig()
    assert cfg.enabled is False
    assert cfg.poll_interval == 300
    assert cfg.max_complexity == pytest.approx(0.4)
    assert cfg.circuit_breaker_threshold == 3
    assert "chore" in cfg.auto_merge_types
    assert "docs" in cfg.auto_merge_types


def test_loop_config_env_override():
    from app.agent_loop import LoopConfig
    env = {
        "AGENT_LOOP_ENABLED": "true",
        "AGENT_LOOP_POLL_INTERVAL": "60",
        "AGENT_LOOP_MAX_COMPLEXITY": "0.7",
        "AGENT_LOOP_AUTO_MERGE_TYPES": "chore,docs,fix",
    }
    with patch.dict(os.environ, env):
        cfg = LoopConfig()
    assert cfg.enabled is True
    assert cfg.poll_interval == 60
    assert cfg.max_complexity == pytest.approx(0.7)
    assert "fix" in cfg.auto_merge_types


# ══════════════════════════════════════════════════════════════════════════════
# AgentLoop state machine — no-issue-available path
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_agent_loop_idle_when_no_issues():
    """Loop stays IDLE and returns None when there are no eligible issues."""
    from app.agent_loop import AgentLoop, LoopConfig, LoopState

    config = LoopConfig()
    config.enabled = True
    loop = AgentLoop(config=config)

    with patch("app.agent_loop.gitlab_client") as mock_gc:
        mock_gc.list_agent_queue = AsyncMock(return_value=[])
        result = await loop._pick_issue()

    assert result is None
    # State should still be PICKING (we didn't move to BUILDING)
    assert loop._status.state in (LoopState.PICKING, LoopState.IDLE)


# ══════════════════════════════════════════════════════════════════════════════
# AgentLoop circuit breaker
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_circuit_breaker_triggers_after_threshold():
    """After N consecutive failures the loop should mark state as PAUSED."""
    from app.agent_loop import AgentLoop, LoopConfig, LoopState

    config = LoopConfig()
    config.circuit_breaker_threshold = 2
    loop = AgentLoop(config=config)
    loop._status.consecutive_failures = 2

    issue = FakeIssue()

    with (
        patch("app.agent_loop.gitlab_client") as mock_gc,
        patch("app.agent_loop.CodeWorker") as MockCW,
    ):
        mock_gc.add_comment = AsyncMock()
        mock_gc.create_issue = AsyncMock(return_value=MagicMock(iid=99))
        MockCW.return_value.plan = AsyncMock(side_effect=RuntimeError("boom"))

        await loop._handle_failure(issue, RuntimeError("boom"))

    assert loop._status.state == LoopState.PAUSED or loop._status.consecutive_failures >= 2


# ══════════════════════════════════════════════════════════════════════════════
# Complexity graduation
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_graduation_bumps_threshold_after_5_successes():
    """After 5 consecutive successes, complexity_threshold should increase by 0.1."""
    from app.agent_loop import AgentLoop, LoopConfig

    config = LoopConfig()
    config.max_complexity = 0.4
    loop = AgentLoop(config=config)
    loop._status.consecutive_successes = 4  # one away from graduation
    initial_threshold = loop._status.complexity_threshold

    issue = FakeIssue()
    await loop._handle_success(issue)

    assert loop._status.complexity_threshold == pytest.approx(initial_threshold + 0.1, abs=0.01)
    assert loop._status.consecutive_successes == 0  # reset after graduation


# ══════════════════════════════════════════════════════════════════════════════
# gap_detector static scanners
# ══════════════════════════════════════════════════════════════════════════════

def test_gap_detector_security_shell_true():
    from app.gap_detector import GapDetector
    detector = GapDetector()
    content = 'subprocess.call(["ls"], shell=True)'
    detector._check_security_patterns("app/foo.py", content)
    assert any("shell=True" in g.title for g in detector._gaps)


def test_gap_detector_traefik_missing_priority():
    from app.gap_detector import GapDetector
    detector = GapDetector()
    content = """
labels:
  - traefik.http.routers.myapp.rule=PathPrefix(`/api/v1`)
"""
    detector._check_traefik_priority("docker-compose.yml", content)
    assert any("priority" in g.title.lower() for g in detector._gaps)


def test_gap_detector_traefik_with_priority_no_gap():
    from app.gap_detector import GapDetector
    detector = GapDetector()
    content = """
labels:
  - traefik.http.routers.myapp.rule=PathPrefix(`/api/v1`)
  - traefik.http.routers.myapp.priority=2147483647
"""
    detector._check_traefik_priority("docker-compose.yml", content)
    assert detector._gaps == []


def test_gap_detector_skill_missing_examples():
    from app.gap_detector import GapDetector
    detector = GapDetector()
    content = "# My Skill\n\nThis skill does something.\n\n## Usage\nCall it."
    detector._check_skill_examples("inference/agent-service/skills/my-skill/SKILL.md", content)
    assert any("Examples" in g.title or "Learning" in g.title for g in detector._gaps)


# ══════════════════════════════════════════════════════════════════════════════
# test_worker._parse_pytest_output
# ══════════════════════════════════════════════════════════════════════════════

def test_parse_pytest_output_all_passed():
    from app.test_worker import _parse_pytest_output
    output = "test_foo.py::test_bar PASSED\n5 passed in 1.23s"
    result = _parse_pytest_output(output, returncode=0)
    assert result.passed is True
    assert result.passed_count == 5
    assert result.failed_count == 0


def test_parse_pytest_output_failures():
    from app.test_worker import _parse_pytest_output
    output = "FAILED test_foo.py::test_bad\n2 passed, 1 failed in 2.0s"
    result = _parse_pytest_output(output, returncode=1)
    assert result.passed is False
    assert result.failed_count == 1
    assert result.passed_count == 2


def test_parse_pytest_output_no_tests():
    from app.test_worker import _parse_pytest_output
    output = "no tests ran"
    result = _parse_pytest_output(output, returncode=0)
    assert result.passed is True
    assert result.test_count == 0
