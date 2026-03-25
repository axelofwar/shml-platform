"""Unit tests for inference/router/executor.py — pure logic parts.

Covers: SubtaskStatus, MergeStrategy, Subtask (dataclass + properties),
ExecutionPlan.get_ready_subtasks(), MergeResult.
No HTTP or live model calls needed.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure inference/router is importable as a package
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_INFERENCE = _ROOT / "inference"
_ROUTER = _INFERENCE / "router"

# Only add _INFERENCE to sys.path so 'router' is found as a package,
# NOT as the file router.py (which would break relative imports in router.py)
for _p in [str(_ROOT), str(_INFERENCE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Stub all provider modules so executor's transitive imports don't fail
from unittest.mock import MagicMock

def _stub_providers():
    fake_providers = MagicMock()
    for name in [
        "router.providers", "inference.router.providers",
        "router.providers.gemini", "inference.router.providers.gemini",
        "router.providers.github_copilot", "inference.router.providers.github_copilot",
        "router.providers.openrouter", "inference.router.providers.openrouter",
        "router.providers.local", "inference.router.providers.local",
        "providers", "providers.gemini", "providers.github_copilot",
        "providers.openrouter", "providers.local",
    ]:
        sys.modules.setdefault(name, MagicMock())

_stub_providers()

# Pre-import at module level so sys.modules cache is set correctly
from router.executor import (
    SubtaskStatus,
    MergeStrategy,
    Subtask,
    ExecutionPlan,
    MergeResult,
)


# ===========================================================================
# SubtaskStatus
# ===========================================================================

class TestSubtaskStatus:
    def test_all_values(self):
        expected = {"pending", "running", "completed", "failed", "superseded"}
        actual = {s.value for s in SubtaskStatus}
        assert actual == expected

    def test_count(self):
        assert len(SubtaskStatus) == 5

    def test_pending_value(self):
        assert SubtaskStatus.PENDING.value == "pending"

    def test_completed_value(self):
        assert SubtaskStatus.COMPLETED.value == "completed"

    def test_superseded_value(self):
        assert SubtaskStatus.SUPERSEDED.value == "superseded"


# ===========================================================================
# MergeStrategy
# ===========================================================================

class TestMergeStrategy:
    def test_all_values(self):
        expected = {"research_wins", "keep_both", "smart_merge", "first_wins"}
        actual = {s.value for s in MergeStrategy}
        assert actual == expected

    def test_count(self):
        assert len(MergeStrategy) == 4

    def test_research_wins(self):
        assert MergeStrategy.RESEARCH_WINS.value == "research_wins"

    def test_smart_merge(self):
        assert MergeStrategy.SMART_MERGE.value == "smart_merge"

    def test_first_wins(self):
        assert MergeStrategy.FIRST_WINS.value == "first_wins"

    def test_keep_both(self):
        assert MergeStrategy.KEEP_BOTH.value == "keep_both"


# ===========================================================================
# Subtask dataclass
# ===========================================================================

class TestSubtask:
    def test_minimal_creation(self):
        st = Subtask(id="t1", type="code", prompt="Write a function")
        assert st.id == "t1"
        assert st.type == "code"
        assert st.prompt == "Write a function"

    def test_status_defaults_to_pending(self):
        st = Subtask(id="t1", type="code", prompt="x")
        assert st.status == SubtaskStatus.PENDING

    def test_priority_default(self):
        st = Subtask(id="t1", type="code", prompt="x")
        assert st.priority == 1

    def test_speculative_default_false(self):
        st = Subtask(id="t1", type="code", prompt="x")
        assert st.speculative is False

    def test_dependencies_default_empty(self):
        st = Subtask(id="t1", type="code", prompt="x")
        assert st.dependencies == []

    def test_result_default_none(self):
        st = Subtask(id="t1", type="code", prompt="x")
        assert st.result is None

    def test_error_default_none(self):
        st = Subtask(id="t1", type="code", prompt="x")
        assert st.error is None

    def test_model_default_none(self):
        st = Subtask(id="t1", type="code", prompt="x")
        assert st.model is None

    def test_duration_ms_none_when_no_times(self):
        st = Subtask(id="t1", type="code", prompt="x")
        assert st.duration_ms is None

    def test_duration_ms_none_when_only_start(self):
        st = Subtask(id="t1", type="code", prompt="x")
        st.start_time = datetime(2024, 1, 1, 0, 0, 0)
        assert st.duration_ms is None

    def test_duration_ms_none_when_only_end(self):
        st = Subtask(id="t1", type="code", prompt="x")
        st.end_time = datetime(2024, 1, 1, 0, 0, 1)
        assert st.duration_ms is None

    def test_duration_ms_calculated_correctly(self):
        st = Subtask(id="t1", type="code", prompt="x")
        st.start_time = datetime(2024, 1, 1, 0, 0, 0)
        st.end_time = datetime(2024, 1, 1, 0, 0, 2)  # 2 seconds
        assert st.duration_ms == 2000

    def test_duration_ms_500ms(self):
        from datetime import timedelta
        st = Subtask(id="t1", type="code", prompt="x")
        st.start_time = datetime(2024, 1, 1, 0, 0, 0)
        st.end_time = st.start_time + timedelta(milliseconds=500)
        assert st.duration_ms == 500

    def test_speculative_subtask(self):
        st = Subtask(id="t1", type="code", prompt="x", speculative=True, priority=3)
        assert st.speculative is True
        assert st.priority == 3

    def test_subtask_with_dependencies(self):
        st = Subtask(id="t3", type="test", prompt="test it", dependencies=["t1", "t2"])
        assert st.dependencies == ["t1", "t2"]


# ===========================================================================
# ExecutionPlan.get_ready_subtasks()
# ===========================================================================

class TestExecutionPlanGetReadySubtasks:
    def _make_plan(self, subtasks):
        return ExecutionPlan(
            task_description="test task",
            subtasks=subtasks,
        )

    def test_all_pending_no_deps_all_ready(self):
        tasks = [
            Subtask(id="t1", type="research", prompt="research"),
            Subtask(id="t2", type="code", prompt="code"),
        ]
        plan = self._make_plan(tasks)
        ready = plan.get_ready_subtasks()
        assert len(ready) == 2
        ids = {t.id for t in ready}
        assert ids == {"t1", "t2"}

    def test_empty_plan_gives_no_ready(self):
        plan = self._make_plan([])
        assert plan.get_ready_subtasks() == []

    def test_task_with_unmet_dependency_excluded(self):
        tasks = [
            Subtask(id="t1", type="research", prompt="research"),
            Subtask(id="t2", type="code", prompt="code", dependencies=["t1"]),
        ]
        plan = self._make_plan(tasks)
        ready = plan.get_ready_subtasks()
        assert len(ready) == 1
        assert ready[0].id == "t1"

    def test_task_with_met_dependency_included(self):
        tasks = [
            Subtask(id="t1", type="research", prompt="research",
                    status=SubtaskStatus.COMPLETED),
            Subtask(id="t2", type="code", prompt="code", dependencies=["t1"]),
        ]
        plan = self._make_plan(tasks)
        ready = plan.get_ready_subtasks()
        assert len(ready) == 1
        assert ready[0].id == "t2"

    def test_completed_tasks_not_in_ready(self):
        tasks = [
            Subtask(id="t1", type="code", prompt="x", status=SubtaskStatus.COMPLETED),
            Subtask(id="t2", type="code", prompt="y"),
        ]
        plan = self._make_plan(tasks)
        ready = plan.get_ready_subtasks()
        assert len(ready) == 1
        assert ready[0].id == "t2"

    def test_running_tasks_not_in_ready(self):
        tasks = [
            Subtask(id="t1", type="code", prompt="x", status=SubtaskStatus.RUNNING),
        ]
        plan = self._make_plan(tasks)
        ready = plan.get_ready_subtasks()
        assert ready == []

    def test_failed_tasks_not_in_ready(self):
        tasks = [
            Subtask(id="t1", type="code", prompt="x", status=SubtaskStatus.FAILED),
        ]
        plan = self._make_plan(tasks)
        ready = plan.get_ready_subtasks()
        assert ready == []

    def test_complex_dependency_chain(self):
        tasks = [
            Subtask(id="t1", type="research", prompt="r", status=SubtaskStatus.COMPLETED),
            Subtask(id="t2", type="code", prompt="c", dependencies=["t1"],
                    status=SubtaskStatus.COMPLETED),
            Subtask(id="t3", type="test", prompt="t", dependencies=["t2"]),
            Subtask(id="t4", type="code", prompt="c2", dependencies=["t1"]),
        ]
        plan = self._make_plan(tasks)
        ready = plan.get_ready_subtasks()
        ids = {t.id for t in ready}
        assert ids == {"t3", "t4"}

    def test_execution_plan_defaults(self):
        plan = ExecutionPlan(
            task_description="test",
            subtasks=[],
        )
        assert plan.merge_strategy == MergeStrategy.SMART_MERGE
        assert plan.max_concurrent == 3
        assert plan.timeout_seconds == 120


# ===========================================================================
# MergeResult
# ===========================================================================

class TestMergeResult:
    def test_creation(self):
        mr = MergeResult(
            final_output="Combined output",
            used_results=["t1", "t2"],
            discarded_results=["t3"],
            merge_notes="Used research from t1",
            total_cost=0.05,
            total_latency_ms=1500,
        )
        assert mr.final_output == "Combined output"
        assert mr.total_cost == 0.05
        assert "t1" in mr.used_results
        assert "t3" in mr.discarded_results

    def test_empty_lists(self):
        mr = MergeResult(
            final_output="result",
            used_results=[],
            discarded_results=[],
            merge_notes="",
            total_cost=0.0,
            total_latency_ms=100,
        )
        assert mr.used_results == []
        assert mr.discarded_results == []
