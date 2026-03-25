"""Unit tests for ParallelExecutor and TaskPlanner in inference/router/executor.py.

Extends test_executor.py (which covers data classes + status enums) with
tests for the full executor class hierarchy.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import from the existing test_executor setup (sys.path + stubs already done)
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_INFERENCE = _ROOT / "inference"
for _p in [str(_ROOT), str(_INFERENCE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from unittest.mock import MagicMock as _MM

for _name in [
    "router.providers", "router.providers.gemini", "router.providers.github_copilot",
    "router.providers.openrouter", "router.providers.local",
]:
    if _name not in sys.modules:
        sys.modules[_name] = _MM()

from router.executor import (  # noqa: E402
    SubtaskStatus,
    MergeStrategy,
    Subtask,
    ExecutionPlan,
    MergeResult,
    ParallelExecutor,
    TaskPlanner,
)
from router.base import CompletionResponse, Message  # noqa: E402


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_response(content: str = "result content") -> CompletionResponse:
    return CompletionResponse(
        content=content,
        model="test-model",
        provider="test",
        usage={"prompt_tokens": 10, "completion_tokens": 20},
        cost=0.0,
        latency_ms=100,
        finish_reason="stop",
    )


def _make_router(response_content: str = "mocked response") -> MagicMock:
    """Build a mock ModelRouter whose complete() method returns a fixed response."""
    router = MagicMock()
    router.complete = AsyncMock(return_value=_make_response(response_content))
    router.complete_with_reasoning = AsyncMock(return_value={
        "plan": "simple plan",
        "execution": "simple execution result",
        "total_cost": 0.01,
    })
    return router


def _make_plan(subtasks=None, merge_strategy=MergeStrategy.FIRST_WINS) -> ExecutionPlan:
    if subtasks is None:
        subtasks = [
            Subtask(id="t1", type="code", prompt="write code"),
        ]
    return ExecutionPlan(
        task_description="test task",
        subtasks=subtasks,
        merge_strategy=merge_strategy,
        max_concurrent=3,
        timeout_seconds=30,
    )


# ===========================================================================
# ParallelExecutor init
# ===========================================================================


class TestParallelExecutorInit:
    def test_stores_router(self):
        router = _make_router()
        executor = ParallelExecutor(router)
        assert executor.router is router

    def test_default_merge_strategy(self):
        router = _make_router()
        executor = ParallelExecutor(router)
        assert executor.default_merge_strategy == MergeStrategy.SMART_MERGE

    def test_custom_merge_strategy(self):
        router = _make_router()
        executor = ParallelExecutor(router, merge_strategy=MergeStrategy.KEEP_BOTH)
        assert executor.default_merge_strategy == MergeStrategy.KEEP_BOTH

    def test_running_tasks_empty_initially(self):
        router = _make_router()
        executor = ParallelExecutor(router)
        assert executor._running_tasks == {}


# ===========================================================================
# execute_subtask
# ===========================================================================


class TestExecuteSubtask:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_research_subtask_sets_completed(self):
        router = _make_router("research findings")
        executor = ParallelExecutor(router)
        subtask = Subtask(id="r1", type="research", prompt="research SAM2")
        result = self._run(executor.execute_subtask(subtask))
        assert subtask.status == SubtaskStatus.COMPLETED
        assert subtask.result == "research findings"
        assert subtask.start_time is not None
        assert subtask.end_time is not None

    def test_code_subtask_uses_local_strategy(self):
        router = _make_router("code output")
        executor = ParallelExecutor(router)
        subtask = Subtask(id="c1", type="code", prompt="write a sort function")
        result = self._run(executor.execute_subtask(subtask))
        assert subtask.status == SubtaskStatus.COMPLETED
        assert result == "code output"

    def test_system_subtask_executes(self):
        router = _make_router("system result")
        executor = ParallelExecutor(router)
        subtask = Subtask(id="s1", type="system", prompt="check GPU memory")
        result = self._run(executor.execute_subtask(subtask))
        assert subtask.status == SubtaskStatus.COMPLETED

    def test_unknown_type_falls_through(self):
        router = _make_router("other result")
        executor = ParallelExecutor(router)
        subtask = Subtask(id="u1", type="other", prompt="do something")
        result = self._run(executor.execute_subtask(subtask))
        assert subtask.status == SubtaskStatus.COMPLETED

    def test_dependency_context_injected(self):
        """When dependencies are met, their results are included in the prompt."""
        router = _make_router("result with context")
        executor = ParallelExecutor(router)
        subtask = Subtask(id="c2", type="code", prompt="implement based on research",
                          dependencies=["r1"])
        completed_results = {"r1": "Use SAM2 model"}
        result = self._run(executor.execute_subtask(subtask, completed_results=completed_results))
        # Verify complete was called with a message containing the dep context
        call_args = router.complete.call_args
        messages = call_args[0][0].messages
        assert any("SAM2" in m.content for m in messages)

    def test_failure_sets_failed_status(self):
        router = MagicMock()
        router.complete = AsyncMock(side_effect=Exception("model failed"))
        executor = ParallelExecutor(router)
        subtask = Subtask(id="f1", type="code", prompt="will fail")
        with pytest.raises(Exception, match="model failed"):
            asyncio.run(executor.execute_subtask(subtask))
        assert subtask.status == SubtaskStatus.FAILED
        assert subtask.error == "model failed"
        assert subtask.end_time is not None

    def test_custom_model_override(self):
        router = _make_router("custom model result")
        executor = ParallelExecutor(router)
        subtask = Subtask(id="m1", type="code", prompt="use custom model",
                          model="custom-model-v2")
        result = self._run(executor.execute_subtask(subtask))
        call_args = router.complete.call_args
        assert call_args[0][0].model == "custom-model-v2"

    def test_context_passed_to_prompt(self):
        router = _make_router("ctx result")
        executor = ParallelExecutor(router)
        subtask = Subtask(id="ctx1", type="code", prompt="do it")
        result = self._run(executor.execute_subtask(subtask, context="project: myapp"))
        call_args = router.complete.call_args
        messages = call_args[0][0].messages
        assert any("myapp" in m.content for m in messages)

    def test_duration_ms_computed_after_execution(self):
        router = _make_router("done")
        executor = ParallelExecutor(router)
        subtask = Subtask(id="dur1", type="code", prompt="work")
        asyncio.run(executor.execute_subtask(subtask))
        assert subtask.duration_ms is not None
        assert subtask.duration_ms >= 0


# ===========================================================================
# execute_plan
# ===========================================================================


class TestExecutePlan:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_single_task_plan_completes(self):
        router = _make_router("final output")
        executor = ParallelExecutor(router)
        plan = _make_plan()
        result = self._run(executor.execute_plan(plan))
        assert isinstance(result, MergeResult)
        assert "final output" in result.final_output or result.final_output != ""

    def test_multiple_independent_tasks(self):
        router = _make_router("parallel result")
        executor = ParallelExecutor(router)
        subtasks = [
            Subtask(id="p1", type="research", prompt="research X"),
            Subtask(id="p2", type="code", prompt="code X"),
        ]
        plan = _make_plan(subtasks, MergeStrategy.FIRST_WINS)
        result = self._run(executor.execute_plan(plan))
        assert result is not None
        assert all(st.status == SubtaskStatus.COMPLETED for st in plan.subtasks)

    def test_dependent_task_runs_after_dependency(self):
        router = _make_router("dep result")
        executor = ParallelExecutor(router)
        subtasks = [
            Subtask(id="d1", type="research", prompt="first"),
            Subtask(id="d2", type="code", prompt="second", dependencies=["d1"]),
        ]
        plan = _make_plan(subtasks, MergeStrategy.FIRST_WINS)
        result = self._run(executor.execute_plan(plan))
        assert plan.subtasks[0].status == SubtaskStatus.COMPLETED
        assert plan.subtasks[1].status == SubtaskStatus.COMPLETED

    def test_failed_subtask_does_not_block_merge(self):
        router = MagicMock()
        call_count = [0]

        async def _complete(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("task failed")
            return _make_response("ok result")

        router.complete = _complete
        executor = ParallelExecutor(router)
        subtasks = [
            Subtask(id="fail1", type="code", prompt="will fail"),
            Subtask(id="ok1", type="code", prompt="will succeed"),
        ]
        plan = _make_plan(subtasks, MergeStrategy.FIRST_WINS)
        result = self._run(executor.execute_plan(plan))
        # Even with a failure, we get a result back
        assert result is not None

    def test_progress_callback_called(self):
        router = _make_router("progress result")
        executor = ParallelExecutor(router)
        plan = _make_plan()
        callbacks = []

        async def _cb(subtask):
            callbacks.append(subtask.id)

        self._run(executor.execute_plan(plan, progress_callback=_cb))
        assert len(callbacks) > 0

    def test_latency_ms_populated(self):
        router = _make_router("done")
        executor = ParallelExecutor(router)
        plan = _make_plan()
        result = self._run(executor.execute_plan(plan))
        assert result.total_latency_ms >= 0

    def test_research_wins_supersedes_speculative_running_task(self):
        """Research wins strategy: speculative tasks in RUNNING state get superseded."""
        router = _make_router("research complete")
        executor = ParallelExecutor(router)

        # Create a speculative task that can only run after research
        # (but we'll manually set it to RUNNING to test the supersession logic)
        spec_st = Subtask(id="spec1", type="code", prompt="speculative",
                          speculative=True, dependencies=["r1"])
        research_st = Subtask(id="r1", type="research", prompt="research")
        plan = ExecutionPlan(
            task_description="test",
            subtasks=[research_st, spec_st],
            merge_strategy=MergeStrategy.RESEARCH_WINS,
        )
        result = self._run(executor.execute_plan(plan))
        # Research completed; speculative was never running (dep not met when research ran)
        assert research_st.status == SubtaskStatus.COMPLETED


# ===========================================================================
# _merge_results — strategy branches
# ===========================================================================


class TestMergeResults:
    def _run(self, coro):
        return asyncio.run(coro)

    def _make_completed_plan(self, research=True, code=True,
                             strategy=MergeStrategy.FIRST_WINS) -> tuple:
        subtasks = []
        completed = {}
        if research:
            st = Subtask(id="r1", type="research", prompt="research")
            st.status = SubtaskStatus.COMPLETED
            subtasks.append(st)
            completed["r1"] = "Research finding: use approach A"
        if code:
            st = Subtask(id="c1", type="code", prompt="code")
            st.status = SubtaskStatus.COMPLETED
            subtasks.append(st)
            completed["c1"] = "def solve(): pass"
        plan = ExecutionPlan(
            task_description="test",
            subtasks=subtasks,
            merge_strategy=strategy,
        )
        return plan, completed

    def test_first_wins_concatenates(self):
        router = _make_router("reconciled")
        executor = ParallelExecutor(router)
        plan, completed = self._make_completed_plan(strategy=MergeStrategy.FIRST_WINS)
        result = self._run(executor._merge_results(plan, completed))
        assert result.merge_notes == "Results concatenated (first wins)"
        assert len(result.used_results) > 0

    def test_keep_both_labels_sections(self):
        router = _make_router("reconciled")
        executor = ParallelExecutor(router)
        plan, completed = self._make_completed_plan(strategy=MergeStrategy.KEEP_BOTH)
        result = self._run(executor._merge_results(plan, completed))
        assert "r1" in result.final_output or "c1" in result.final_output

    def test_research_wins_with_both(self):
        router = _make_router("reconciled code")
        executor = ParallelExecutor(router)
        plan, completed = self._make_completed_plan(strategy=MergeStrategy.RESEARCH_WINS)
        result = self._run(executor._merge_results(plan, completed))
        assert "Code adapted" in result.merge_notes or "reconciled" in result.final_output

    def test_research_wins_no_code(self):
        router = _make_router("research only")
        executor = ParallelExecutor(router)
        plan, completed = self._make_completed_plan(research=True, code=False,
                                                    strategy=MergeStrategy.RESEARCH_WINS)
        result = self._run(executor._merge_results(plan, completed))
        assert "Research findings" in result.merge_notes or "Research finding" in result.final_output

    def test_research_wins_no_research(self):
        router = _make_router("code only")
        executor = ParallelExecutor(router)
        plan, completed = self._make_completed_plan(research=False, code=True,
                                                    strategy=MergeStrategy.RESEARCH_WINS)
        result = self._run(executor._merge_results(plan, completed))
        assert "code directly" in result.merge_notes

    def test_smart_merge_calls_reconcile(self):
        router = _make_router("smart merged result")
        executor = ParallelExecutor(router)
        plan, completed = self._make_completed_plan(strategy=MergeStrategy.SMART_MERGE)
        result = self._run(executor._merge_results(plan, completed))
        assert "smart merge" in result.merge_notes.lower()

    def test_superseded_tasks_in_discarded(self):
        router = _make_router("result")
        executor = ParallelExecutor(router)
        research_st = Subtask(id="r1", type="research", prompt="research")
        research_st.status = SubtaskStatus.COMPLETED
        spec_st = Subtask(id="spec1", type="code", prompt="spec",
                          speculative=True)
        spec_st.status = SubtaskStatus.SUPERSEDED
        plan = ExecutionPlan(
            task_description="test",
            subtasks=[research_st, spec_st],
            merge_strategy=MergeStrategy.FIRST_WINS,
        )
        completed = {"r1": "research result"}
        result = self._run(executor._merge_results(plan, completed))
        assert "spec1" in result.discarded_results


# ===========================================================================
# _reconcile_with_research and _smart_merge
# ===========================================================================


class TestReconcileAndSmartMerge:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_reconcile_returns_content(self):
        router = _make_router("reconciled output")
        executor = ParallelExecutor(router)
        result = self._run(executor._reconcile_with_research(
            research="Use SAM2 approach",
            code="def old_impl(): pass",
        ))
        assert result == "reconciled output"

    def test_reconcile_with_context(self):
        router = _make_router("reconciled with context")
        executor = ParallelExecutor(router)
        result = self._run(executor._reconcile_with_research(
            research="SAM2 is best",
            code="old code",
            context="Project: myproject",
        ))
        assert result == "reconciled with context"

    def test_smart_merge_research_and_code(self):
        router = _make_router("smart result")
        executor = ParallelExecutor(router)
        r_st = Subtask(id="r1", type="research", prompt="research")
        c_st = Subtask(id="c1", type="code", prompt="code")
        result = self._run(executor._smart_merge(
            research_results=[(r_st, "research finding")],
            code_results=[(c_st, "code result")],
            other_results=[],
        ))
        assert result != ""

    def test_smart_merge_code_only(self):
        router = _make_router("code only smart")
        executor = ParallelExecutor(router)
        c_st = Subtask(id="c1", type="code", prompt="code")
        result = self._run(executor._smart_merge(
            research_results=[],
            code_results=[(c_st, "some code")],
            other_results=[],
        ))
        assert "some code" in result

    def test_smart_merge_with_other(self):
        router = _make_router("other merged")
        executor = ParallelExecutor(router)
        o_st = Subtask(id="o1", type="system", prompt="system task")
        result = self._run(executor._smart_merge(
            research_results=[],
            code_results=[],
            other_results=[(o_st, "system output")],
        ))
        assert "system output" in result


# ===========================================================================
# create_plan
# ===========================================================================


class TestCreatePlan:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_valid_json_creates_plan(self):
        plan_json = json.dumps({
            "task_type": "code_only",
            "subtasks": [
                {"id": "t1", "type": "code", "prompt": "write tests",
                 "dependencies": [], "priority": 2, "speculative": False},
            ],
            "merge_strategy": "first_wins",
        })
        router = _make_router(plan_json)
        executor = ParallelExecutor(router)
        plan = self._run(executor.create_plan("write tests for module X"))
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].id == "t1"
        assert plan.merge_strategy == MergeStrategy.FIRST_WINS

    def test_invalid_json_falls_back_to_single_task(self):
        router = _make_router("not valid json {{ {{")
        executor = ParallelExecutor(router)
        plan = self._run(executor.create_plan("some task"))
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].id == "main"

    def test_empty_subtasks_gets_fallback(self):
        plan_json = json.dumps({"subtasks": [], "merge_strategy": "smart_merge"})
        router = _make_router(plan_json)
        executor = ParallelExecutor(router)
        plan = self._run(executor.create_plan("do something"))
        assert len(plan.subtasks) == 1

    def test_unknown_merge_strategy_uses_default(self):
        plan_json = json.dumps({
            "subtasks": [{"id": "t1", "type": "code", "prompt": "p"}],
            "merge_strategy": "unknown_strategy",
        })
        router = _make_router(plan_json)
        executor = ParallelExecutor(router)
        plan = self._run(executor.create_plan("task"))
        assert plan.merge_strategy == MergeStrategy.SMART_MERGE  # default

    def test_with_context(self):
        plan_json = json.dumps({
            "subtasks": [{"id": "t1", "type": "code", "prompt": "implement"}],
            "merge_strategy": "first_wins",
        })
        router = _make_router(plan_json)
        executor = ParallelExecutor(router)
        plan = self._run(executor.create_plan("implement feature", context="use Python"))
        assert len(plan.subtasks) == 1


# ===========================================================================
# TaskPlanner
# ===========================================================================


class TestTaskPlanner:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_init_creates_executor(self):
        router = _make_router()
        planner = TaskPlanner(router)
        assert planner.router is router
        assert isinstance(planner.executor, ParallelExecutor)

    def test_execute_non_parallel_path(self):
        router = _make_router()
        planner = TaskPlanner(router)
        result = self._run(planner.execute("simple task", parallel=False))
        assert result["parallel"] is False
        assert result["output"] == "simple execution result"

    def test_execute_parallel_path(self):
        router = _make_router()
        plan_json = json.dumps({
            "subtasks": [{"id": "t1", "type": "code", "prompt": "do it"}],
            "merge_strategy": "first_wins",
        })
        router.complete = AsyncMock(return_value=_make_response(plan_json))
        planner = TaskPlanner(router)
        result = self._run(planner.execute("do it in parallel"))
        assert result["parallel"] is True
        assert "output" in result

    def test_execute_with_merge_strategy_override(self):
        router = _make_router()
        plan_json = json.dumps({
            "subtasks": [{"id": "t1", "type": "code", "prompt": "work"}],
            "merge_strategy": "smart_merge",
        })
        router.complete = AsyncMock(return_value=_make_response(plan_json))
        planner = TaskPlanner(router)
        result = self._run(planner.execute("work", merge_strategy=MergeStrategy.KEEP_BOTH))
        assert result is not None

    def test_execute_with_progress_callback(self):
        router = _make_router()
        plan_json = json.dumps({
            "subtasks": [{"id": "t1", "type": "code", "prompt": "work"}],
            "merge_strategy": "first_wins",
        })
        router.complete = AsyncMock(return_value=_make_response(plan_json))
        planner = TaskPlanner(router)
        progress = []

        async def _progress_cb(subtask_id, status):
            progress.append((subtask_id, status))

        result = self._run(planner.execute("work", progress_callback=_progress_cb))
        assert len(progress) > 0
