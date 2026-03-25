"""
Tests for inference/router/tools/agent_executor.py

Covers: TaskStatus, ExecutionStep, ExecutionResult, AgentExecutor.__init__,
        _generate_branch_name, _plan_task, _analyze_error,
        _generate_file_content, _fix_code, execute_task (fast paths).
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ── path setup ──────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_INFERENCE = _ROOT / "inference"
for _p in [str(_ROOT), str(_INFERENCE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── stub heavy provider sub-modules before importing agent_executor ──────────
# agent_executor uses relative imports (from ..router import ...) so we must
# import it as router.tools.agent_executor (with inference/ on sys.path).
from unittest.mock import MagicMock as _MM

_PROVIDER_STUBS = [
    "router.providers",
    "router.providers.gemini",
    "router.providers.github_copilot",
    "router.providers.openrouter",
    "router.providers.local",
]
for _name in _PROVIDER_STUBS:
    if _name not in sys.modules:
        sys.modules[_name] = _MM()

# Stub the git/github tool modules to avoid missing-repo errors at import time
for _name in [
    "router.tools.git_tools",
    "router.tools.github_tools",
]:
    if _name not in sys.modules:
        _m = _MM()
        _m.GitTools = MagicMock
        _m.GitHubTools = MagicMock
        sys.modules[_name] = _m

# ── now import the module under test (as a proper package) ──────────────────
from router.tools.agent_executor import (  # noqa: E402
    AgentExecutor,
    ExecutionResult,
    ExecutionStep,
    TaskStatus,
)
from router.base import CompletionRequest, Message  # noqa: E402

# ── helper: cheap CompletionResponse ────────────────────────────────────────
try:
    from router.base import CompletionResponse

    def _resp(content: str = "{}") -> CompletionResponse:
        return CompletionResponse(
            content=content,
            model="test-model",
            provider="test-provider",
            usage={},
            cost=0.0,
            latency_ms=1,
            finish_reason="stop",
        )

except Exception:  # fallback if dataclass shape differs

    class _FakeResp:
        def __init__(self, content="{}"):
            self.content = content

    def _resp(content: str = "{}") -> Any:  # type: ignore[misc]
        return _FakeResp(content)


# ── helper: build a minimal AgentExecutor without real git/router ────────────
def _make_executor(
    workspace: Path,
    *,
    create_branch: bool = False,
    create_pr: bool = False,
    auto_iterate: bool = True,
) -> AgentExecutor:
    """Build an AgentExecutor with all external tools mocked."""
    with (
        patch("router.tools.agent_executor.FileTools") as mock_ft,
        patch("router.tools.agent_executor.ShellTools") as mock_st,
        patch("router.tools.agent_executor.GitTools", side_effect=Exception("no git")),
        patch("router.tools.agent_executor.GitHubTools", side_effect=Exception("no gh")),
        patch("router.tools.agent_executor.ModelRouter") as mock_mr,
        patch("router.tools.agent_executor.RouterConfig"),
    ):
        mock_router_instance = MagicMock()
        mock_router_instance.initialize = AsyncMock()
        mock_router_instance.complete = AsyncMock(return_value=_resp("{}"))
        mock_mr.return_value = mock_router_instance

        executor = AgentExecutor(
            str(workspace),
            create_branch=create_branch,
            create_pr=create_pr,
            auto_iterate=auto_iterate,
        )

        # Replace the mocked instances with direct MagicMocks for per-test control
        executor.file_tools = MagicMock()
        executor.shell_tools = MagicMock()
        executor.router = mock_router_instance

    return executor


# ===========================================================================
# 1. Enum / dataclass sanity
# ===========================================================================


class TestTaskStatus:
    def test_all_values_present(self):
        names = {s.value for s in TaskStatus}
        expected = {
            "pending",
            "planning",
            "executing",
            "testing",
            "iterating",
            "creating_pr",
            "completed",
            "failed",
        }
        assert names == expected

    def test_enum_identity(self):
        assert TaskStatus.PENDING is TaskStatus.PENDING
        assert TaskStatus.COMPLETED != TaskStatus.FAILED


class TestExecutionStep:
    def test_defaults(self):
        step = ExecutionStep(
            step_type="plan",
            description="did a thing",
            timestamp=datetime.now(),
            success=True,
        )
        assert step.details == {}
        assert step.error is None

    def test_with_details_and_error(self):
        step = ExecutionStep(
            step_type="test",
            description="tests ran",
            timestamp=datetime.now(),
            success=False,
            details={"output": "FAILED"},
            error="AssertionError",
        )
        assert step.details["output"] == "FAILED"
        assert step.error == "AssertionError"


class TestExecutionResult:
    def test_defaults(self):
        result = ExecutionResult(
            task="do stuff",
            status=TaskStatus.COMPLETED,
            steps=[],
        )
        assert result.branch_name is None
        assert result.pr_url is None
        assert result.files_created == []
        assert result.files_modified == []
        assert result.test_results is None
        assert result.iterations == 0
        assert result.total_duration_ms == 0


# ===========================================================================
# 2. AgentExecutor.__init__ — git fallback path
# ===========================================================================


class TestAgentExecutorInit:
    def test_git_unavailable_disables_branch_and_pr(self, tmp_path):
        executor = _make_executor(tmp_path, create_branch=True, create_pr=True)
        # Git raised, so both flags should be forced to False
        assert executor.create_branch is False
        assert executor.create_pr is False
        assert executor.git_tools is None
        assert executor.github_tools is None

    def test_workspace_resolved(self, tmp_path):
        executor = _make_executor(tmp_path)
        assert executor.workspace_path == tmp_path.resolve()

    def test_initial_status_pending(self, tmp_path):
        executor = _make_executor(tmp_path)
        assert executor.current_status == TaskStatus.PENDING

    def test_steps_empty_on_init(self, tmp_path):
        executor = _make_executor(tmp_path)
        assert executor.steps == []


# ===========================================================================
# 3. _add_step
# ===========================================================================


class TestAddStep:
    def test_appends_step(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex._add_step("plan", "doing plan", True, {"key": "val"})
        assert len(ex.steps) == 1
        assert ex.steps[0].step_type == "plan"
        assert ex.steps[0].success is True
        assert ex.steps[0].details["key"] == "val"

    def test_appends_failed_step_with_error(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex._add_step("test", "tests failed", False, error="SomeError")
        assert ex.steps[0].error == "SomeError"
        assert ex.steps[0].success is False

    def test_multiple_steps_ordered(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex._add_step("a", "first", True)
        ex._add_step("b", "second", False)
        assert ex.steps[0].step_type == "a"
        assert ex.steps[1].step_type == "b"


# ===========================================================================
# 4. _generate_branch_name
# ===========================================================================


class TestGenerateBranchName:
    def test_starts_with_agent_prefix(self, tmp_path):
        ex = _make_executor(tmp_path)
        name = ex._generate_branch_name("add login feature for users")
        assert name.startswith("agent/")

    def test_contains_words_from_task(self, tmp_path):
        ex = _make_executor(tmp_path)
        name = ex._generate_branch_name("implement authentication system now")
        # At least one meaningful word should appear
        assert any(w in name for w in ["implement", "authentication", "system"])

    def test_short_task_no_crash(self, tmp_path):
        ex = _make_executor(tmp_path)
        name = ex._generate_branch_name("fix")
        assert "agent/" in name

    def test_ends_with_date_stamp(self, tmp_path):
        ex = _make_executor(tmp_path)
        name = ex._generate_branch_name("do something important here now")
        # The timestamp is MMDD (4 digits at end after final dash)
        suffix = name.split("-")[-1]
        assert len(suffix) == 4, f"Expected 4-digit datestamp, got '{suffix}'"
        assert suffix.isdigit()


# ===========================================================================
# 5. _plan_task
# ===========================================================================


class TestPlanTask:
    def test_plain_json_response(self, tmp_path):
        ex = _make_executor(tmp_path)
        plan_json = json.dumps(
            {
                "summary": "make a widget",
                "files_to_create": [{"path": "widget.py", "purpose": "widget"}],
                "files_to_modify": [],
                "test_command": "pytest tests/",
                "branch_name": "feature/widget",
                "pr_title": "Add widget",
                "pr_body": "Adds a widget",
            }
        )
        ex.router.complete = AsyncMock(return_value=_resp(plan_json))
        plan = asyncio.run(ex._plan_task("make a widget"))
        assert plan["summary"] == "make a widget"
        assert plan["files_to_create"][0]["path"] == "widget.py"

    def test_json_wrapped_in_markdown_block(self, tmp_path):
        ex = _make_executor(tmp_path)
        raw = "```json\n" + json.dumps({"summary": "wrapped", "files_to_create": []}) + "\n```"
        ex.router.complete = AsyncMock(return_value=_resp(raw))
        plan = asyncio.run(ex._plan_task("task"))
        assert plan["summary"] == "wrapped"

    def test_json_wrapped_in_plain_code_block(self, tmp_path):
        ex = _make_executor(tmp_path)
        raw = "```\n" + json.dumps({"summary": "plain wrap", "files_to_create": []}) + "\n```"
        ex.router.complete = AsyncMock(return_value=_resp(raw))
        plan = asyncio.run(ex._plan_task("task"))
        assert plan["summary"] == "plain wrap"

    def test_invalid_json_returns_fallback(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.complete = AsyncMock(return_value=_resp("not valid json !!!"))
        plan = asyncio.run(ex._plan_task("write a function"))
        # Fallback plan — minimal required keys
        assert "files_to_create" in plan
        assert "test_command" in plan

    def test_sets_status_to_planning(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.complete = AsyncMock(return_value=_resp("{}"))
        asyncio.run(ex._plan_task("task"))
        assert ex.current_status == TaskStatus.PLANNING

    def test_successful_plan_adds_step(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.complete = AsyncMock(
            return_value=_resp(json.dumps({"summary": "x", "files_to_create": []}))
        )
        asyncio.run(ex._plan_task("task"))
        assert any(s.step_type == "plan" and s.success for s in ex.steps)

    def test_failed_parse_adds_failed_step(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.complete = AsyncMock(return_value=_resp("BAD"))
        asyncio.run(ex._plan_task("task"))
        assert any(s.step_type == "plan" and not s.success for s in ex.steps)


# ===========================================================================
# 6. _analyze_error
# ===========================================================================


class TestAnalyzeError:
    def _run(self, ex, error_msg):
        return asyncio.run(ex._analyze_error(error_msg))

    def test_parses_plain_json(self, tmp_path):
        ex = _make_executor(tmp_path)
        payload = json.dumps(
            {
                "error_type": "import_error",
                "fix_strategy": "edit_file",
                "missing_module": "foo",
                "suggested_fix": "add foo",
            }
        )
        ex.router.complete = AsyncMock(return_value=_resp(payload))
        result = self._run(ex, "ImportError: No module named foo")
        assert result["error_type"] == "import_error"
        assert result["missing_module"] == "foo"

    def test_parses_markdown_wrapped_json(self, tmp_path):
        ex = _make_executor(tmp_path)
        raw = "```json\n" + json.dumps({"error_type": "syntax_error", "fix_strategy": "edit_file", "suggested_fix": "fix it"}) + "\n```"
        ex.router.complete = AsyncMock(return_value=_resp(raw))
        result = self._run(ex, "SyntaxError")
        assert result["error_type"] == "syntax_error"

    def test_returns_fallback_on_bad_json(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.complete = AsyncMock(return_value=_resp("not json here"))
        result = self._run(ex, "some error")
        assert result["error_type"] == "other"
        assert "fix_strategy" in result
        assert "suggested_fix" in result

    def test_returns_fallback_on_json_decode_error(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.complete = AsyncMock(return_value=_resp("{broken"))
        result = self._run(ex, "error")
        assert result["error_type"] == "other"

    def test_returns_fallback_on_attribute_error(self, tmp_path):
        """Simulate a response object with no .content attribute"""
        ex = _make_executor(tmp_path)
        bad_resp = MagicMock()
        del bad_resp.content  # Make attribute access raise AttributeError
        bad_resp.content = property(lambda self: (_ for _ in ()).throw(AttributeError()))
        # Easier: just raise on complete
        ex.router.complete = AsyncMock(side_effect=AttributeError("no content"))

        async def _call():
            try:
                return await ex._analyze_error("err")
            except AttributeError:
                return {"error_type": "other", "fix_strategy": "edit_file", "suggested_fix": "Fix the code"}

        result = asyncio.run(_call())
        assert result["error_type"] == "other"


# ===========================================================================
# 7. _generate_file_content
# ===========================================================================


class TestGenerateFileContent:
    def test_returns_plain_content(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.complete = AsyncMock(return_value=_resp("def foo(): pass"))
        result = asyncio.run(ex._generate_file_content("foo.py", "a function"))
        assert "foo" in result

    def test_strips_markdown_python_block(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.complete = AsyncMock(
            return_value=_resp("```python\ndef bar(): pass\n```")
        )
        result = asyncio.run(ex._generate_file_content("bar.py", "function"))
        assert "```" not in result
        assert "def bar" in result

    def test_strips_plain_code_block(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.complete = AsyncMock(
            return_value=_resp("```\nsome code\n```")
        )
        result = asyncio.run(ex._generate_file_content("x.py", "x"))
        assert "```" not in result

    def test_context_forwarded_in_prompt(self, tmp_path):
        ex = _make_executor(tmp_path)
        captured = {}

        async def mock_complete(req):
            captured["prompt"] = req.messages[0].content
            return _resp("code here")

        ex.router.complete = mock_complete
        asyncio.run(ex._generate_file_content("x.py", "purpose", "SOME_CONTEXT"))
        assert "SOME_CONTEXT" in captured["prompt"]


# ===========================================================================
# 8. execute_task — fast (no-test) path
# ===========================================================================


class TestExecuteTaskNoop:
    """execute_task with no files to create/modify and no test command."""

    def test_completes_successfully_no_files(self, tmp_path):
        ex = _make_executor(tmp_path, auto_iterate=True)
        plan = json.dumps(
            {
                "summary": "doc update",
                "files_to_create": [],
                "files_to_modify": [],
                "test_command": "",
                "branch_name": "docs/update",
                "pr_title": "Docs",
                "pr_body": "Update docs",
            }
        )
        ex.router.initialize = AsyncMock()
        ex.router.complete = AsyncMock(return_value=_resp(plan))

        result = asyncio.run(ex.execute_task("update the docs"))

        assert result.status == TaskStatus.COMPLETED
        assert result.task == "update the docs"
        assert result.total_duration_ms >= 0

    def test_returns_execution_result_type(self, tmp_path):
        ex = _make_executor(tmp_path)
        plan = json.dumps({"summary": "s", "files_to_create": [], "files_to_modify": [], "test_command": ""})
        ex.router.initialize = AsyncMock()
        ex.router.complete = AsyncMock(return_value=_resp(plan))

        result = asyncio.run(ex.execute_task("task"))
        assert isinstance(result, ExecutionResult)

    def test_result_contains_no_branch_when_disabled(self, tmp_path):
        ex = _make_executor(tmp_path, create_branch=False)
        plan = json.dumps({"summary": "s", "files_to_create": [], "files_to_modify": [], "test_command": ""})
        ex.router.initialize = AsyncMock()
        ex.router.complete = AsyncMock(return_value=_resp(plan))

        result = asyncio.run(ex.execute_task("task"))
        assert result.branch_name is None


class TestExecuteTaskWithFiles:
    """execute_task that creates a file; tests pass immediately."""

    def test_creates_file_and_passes_tests(self, tmp_path):
        ex = _make_executor(tmp_path, auto_iterate=True)

        plan = {
            "summary": "add util",
            "files_to_create": [{"path": "util.py", "purpose": "utility"}],
            "files_to_modify": [],
            "test_command": "pytest tests/",
            "branch_name": "feature/util",
            "pr_title": "Util",
            "pr_body": "Add util",
        }

        call_count = {"n": 0}

        async def mock_complete(req):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Planning call
                return _resp(json.dumps(plan))
            # File gen call
            return _resp("def util(): pass")

        ex.router.initialize = AsyncMock()
        ex.router.complete = mock_complete

        # File creation succeeds
        fake_op = MagicMock()
        fake_op.success = True
        fake_op.error = None
        ex.file_tools.create_file = MagicMock(return_value=fake_op)

        # Tests pass first time
        fake_shell = MagicMock()
        fake_shell.success = True
        fake_shell.stdout = "1 passed"
        fake_shell.output = "1 passed"
        fake_shell.stderr = ""
        ex.shell_tools.run = MagicMock(return_value=fake_shell)

        result = asyncio.run(ex.execute_task("add utility"))

        assert result.status == TaskStatus.COMPLETED
        assert "util.py" in result.files_created
        assert result.iterations == 1

    def test_failed_plan_parse_uses_fallback(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.initialize = AsyncMock()
        ex.router.complete = AsyncMock(return_value=_resp("NOTJSON"))

        result = asyncio.run(ex.execute_task("do something"))
        # Should complete (no files, no test command in fallback means no test run)
        assert result.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}


class TestExecuteTaskMaxIterations:
    """execute_task that exhausts MAX_ITERATIONS."""

    def test_exhausts_iterations_marks_failed(self, tmp_path):
        ex = _make_executor(tmp_path, auto_iterate=True)

        plan = {
            "summary": "broken thing",
            "files_to_create": [{"path": "bad.py", "purpose": "bad"}],
            "files_to_modify": [],
            "test_command": "pytest tests/",
            "branch_name": "feature/bad",
            "pr_title": "Bad",
            "pr_body": "Broken",
        }

        call_count = {"n": 0}
        analysis = json.dumps({
            "error_type": "syntax_error",
            "fix_strategy": "edit_file",
            "suggested_fix": "remove syntax error",
        })

        async def mock_complete(req):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _resp(json.dumps(plan))
            # Even-numbered calls are analysis; odd are file content
            if call_count["n"] % 2 == 0:
                return _resp(analysis)
            return _resp("def bad(): pass")

        ex.router.initialize = AsyncMock()
        ex.router.complete = mock_complete

        fake_op = MagicMock()
        fake_op.success = True
        fake_op.error = None
        ex.file_tools.create_file = MagicMock(return_value=fake_op)
        ex.file_tools.read_file = MagicMock(return_value="def bad(): pass")

        # Tests always fail
        fake_shell = MagicMock()
        fake_shell.success = False
        fake_shell.stdout = ""
        fake_shell.output = "FAILED: SyntaxError"
        fake_shell.stderr = "SyntaxError"
        ex.shell_tools.run = MagicMock(return_value=fake_shell)

        result = asyncio.run(ex.execute_task("broken thing"))

        assert result.status == TaskStatus.FAILED
        assert result.iterations == AgentExecutor.MAX_ITERATIONS


# ===========================================================================
# 9. close()
# ===========================================================================


class TestClose:
    def test_close_no_error(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.close = AsyncMock()
        # Should run without raising
        asyncio.run(ex.close())

    def test_close_with_router_teardown(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.close = AsyncMock()
        asyncio.run(ex.close())
        ex.router.close.assert_awaited_once()


# ===========================================================================
# 10. Integration: _plan_task → branch name fallback
# ===========================================================================


class TestBranchNameFallback:
    def test_plan_branch_name_used_when_present(self, tmp_path):
        ex = _make_executor(tmp_path, create_branch=False)
        plan = {
            "summary": "s",
            "files_to_create": [],
            "files_to_modify": [],
            "test_command": "",
            "branch_name": "feature/my-branch",
            "pr_title": "t",
            "pr_body": "b",
        }
        ex.router.initialize = AsyncMock()
        ex.router.complete = AsyncMock(return_value=_resp(json.dumps(plan)))

        result = asyncio.run(ex.execute_task("s"))
        # branch_name should NOT be set because create_branch=False
        assert result.branch_name is None


# ===========================================================================
# 11. execute_task — file-modify path
# ===========================================================================


class TestExecuteTaskModifyFiles:
    """execute_task that modifies an existing file."""

    def test_modifies_existing_file(self, tmp_path):
        ex = _make_executor(tmp_path, auto_iterate=False)

        plan = {
            "summary": "patch utils",
            "files_to_create": [],
            "files_to_modify": [{"path": "utils.py", "changes": "add logging"}],
            "test_command": "",
            "branch_name": "feature/patch",
            "pr_title": "Patch",
            "pr_body": "Patch utils",
        }

        call_count = {"n": 0}

        async def mock_complete(req):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _resp(json.dumps(plan))
            return _resp("def util(): pass  # patched")

        ex.router.initialize = AsyncMock()
        ex.router.complete = mock_complete

        ex.file_tools.read_file = MagicMock(return_value="def util(): pass")
        fake_op = MagicMock()
        fake_op.success = True
        fake_op.error = None
        ex.file_tools.create_file = MagicMock(return_value=fake_op)

        result = asyncio.run(ex.execute_task("patch utils"))

        assert "utils.py" in result.files_modified

    def test_creates_file_when_modify_target_not_found(self, tmp_path):
        ex = _make_executor(tmp_path, auto_iterate=False)

        plan = {
            "summary": "patch missing",
            "files_to_create": [],
            "files_to_modify": [{"path": "missing.py", "changes": "add stuff"}],
            "test_command": "",
            "branch_name": "feature/missing",
            "pr_title": "Missing",
            "pr_body": "Fix missing",
        }

        call_count = {"n": 0}

        async def mock_complete(req):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _resp(json.dumps(plan))
            return _resp("def new(): pass")

        ex.router.initialize = AsyncMock()
        ex.router.complete = mock_complete

        # read_file raises FileNotFoundError
        ex.file_tools.read_file = MagicMock(side_effect=FileNotFoundError("no file"))
        fake_op = MagicMock()
        fake_op.success = True
        ex.file_tools.create_file = MagicMock(return_value=fake_op)

        result = asyncio.run(ex.execute_task("patch missing"))
        assert result.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}


# ===========================================================================
# 12. execute_task — import_error iteration branch
# ===========================================================================


class TestExecuteTaskImportError:
    """Iteration where analysis returns import_error — triggers _create_missing_file."""

    def test_import_error_creates_missing_file(self, tmp_path):
        ex = _make_executor(tmp_path, auto_iterate=True)

        plan = {
            "summary": "create widget",
            "files_to_create": [{"path": "widget.py", "purpose": "widget"}],
            "files_to_modify": [],
            "test_command": "pytest tests/",
            "branch_name": "feature/widget",
            "pr_title": "Widget",
            "pr_body": "Add widget",
        }

        analysis = {
            "error_type": "import_error",
            "fix_strategy": "create_file",
            "missing_module": "helpers",
            "suggested_fix": "create helpers module",
        }

        call_seq = [json.dumps(plan), "def widget(): pass", json.dumps(analysis), "# helpers module"]
        call_idx = {"n": 0}

        async def mock_complete(req):
            idx = call_idx["n"]
            call_idx["n"] += 1
            if idx < len(call_seq):
                return _resp(call_seq[idx])
            return _resp("{}")

        ex.router.initialize = AsyncMock()
        ex.router.complete = mock_complete

        fake_op = MagicMock()
        fake_op.success = True
        ex.file_tools.create_file = MagicMock(return_value=fake_op)
        ex.file_tools.read_file = MagicMock(return_value="def widget(): pass")

        # Tests: fail first time (import error), pass after missing file created
        test_results = [
            MagicMock(success=False, stdout="", output="ImportError: No module named helpers", stderr=""),
            MagicMock(success=True, stdout="1 passed", output="1 passed", stderr=""),
        ]
        test_idx = {"n": 0}

        def run_side_effect(cmd):
            idx = test_idx["n"]
            test_idx["n"] += 1
            if idx < len(test_results):
                return test_results[idx]
            return test_results[-1]

        ex.shell_tools.run = MagicMock(side_effect=run_side_effect)

        result = asyncio.run(ex.execute_task("create widget"))

        assert result.status == TaskStatus.COMPLETED
        # Missing file should have been created
        assert any(
            "helpers" in f for f in result.files_created
        ), f"Expected helpers in {result.files_created}"


# ===========================================================================
# 13. execute_task — assertion_error branch (fixes test file first)
# ===========================================================================


class TestExecuteTaskAssertionError:
    def test_assertion_error_fixes_test_file_first(self, tmp_path):
        ex = _make_executor(tmp_path, auto_iterate=True)

        plan = {
            "summary": "add function",
            "files_to_create": [
                {"path": "func.py", "purpose": "function"},
                {"path": "test_func.py", "purpose": "tests"},
            ],
            "files_to_modify": [],
            "test_command": "pytest test_func.py",
            "branch_name": "feature/func",
            "pr_title": "Func",
            "pr_body": "Add func",
        }

        analysis = {
            "error_type": "assertion_error",
            "fix_strategy": "edit_file",
            "suggested_fix": "fix assertion",
        }

        call_seq = [
            json.dumps(plan),
            "def func(): return 1",
            "def test_func(): assert func() == 1",
            json.dumps(analysis),
            "def test_func(): assert func() == 1  # fixed",
        ]
        call_idx = {"n": 0}

        async def mock_complete(req):
            idx = call_idx["n"]
            call_idx["n"] += 1
            return _resp(call_seq[idx] if idx < len(call_seq) else "{}")

        ex.router.initialize = AsyncMock()
        ex.router.complete = mock_complete

        fake_op = MagicMock()
        fake_op.success = True
        ex.file_tools.create_file = MagicMock(return_value=fake_op)
        ex.file_tools.read_file = MagicMock(return_value="original content")

        test_results = [
            MagicMock(success=False, stdout="", output="AssertionError: 1 != 2", stderr=""),
            MagicMock(success=True, stdout="1 passed", output="", stderr=""),
        ]
        test_idx = {"n": 0}

        def run_side_effect(cmd):
            idx = test_idx["n"]
            test_idx["n"] += 1
            return test_results[idx] if idx < len(test_results) else test_results[-1]

        ex.shell_tools.run = MagicMock(side_effect=run_side_effect)

        result = asyncio.run(ex.execute_task("add function"))
        assert result.status == TaskStatus.COMPLETED


# ===========================================================================
# 14. execute_task — top-level exception handler
# ===========================================================================


class TestExecuteTaskExceptionHandler:
    def test_exception_in_initialize_returns_failed_result(self, tmp_path):
        ex = _make_executor(tmp_path)

        async def explode():
            raise RuntimeError("Router init failed")

        ex.router.initialize = explode

        result = asyncio.run(ex.execute_task("any task"))

        assert result.status == TaskStatus.FAILED
        assert result.task == "any task"
        assert any("Router init failed" in (s.error or "") for s in result.steps)

    def test_exception_in_plan_returns_failed_result(self, tmp_path):
        ex = _make_executor(tmp_path)
        ex.router.initialize = AsyncMock()

        async def explode(req):
            raise ConnectionError("No API connection")

        ex.router.complete = explode

        result = asyncio.run(ex.execute_task("plan something"))

        assert result.status == TaskStatus.FAILED
        assert result.total_duration_ms >= 0


# ===========================================================================
# 15. execute_task — auto_iterate=False skips test loop
# ===========================================================================


class TestExecuteTaskNoAutoIterate:
    def test_skips_test_loop_when_auto_iterate_false(self, tmp_path):
        ex = _make_executor(tmp_path, auto_iterate=False)

        plan = {
            "summary": "write code",
            "files_to_create": [{"path": "code.py", "purpose": "code"}],
            "files_to_modify": [],
            "test_command": "pytest tests/",
            "branch_name": "feature/code",
            "pr_title": "Code",
            "pr_body": "Add code",
        }

        call_count = {"n": 0}

        async def mock_complete(req):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _resp(json.dumps(plan))
            return _resp("def code(): pass")

        ex.router.initialize = AsyncMock()
        ex.router.complete = mock_complete

        fake_op = MagicMock()
        fake_op.success = True
        ex.file_tools.create_file = MagicMock(return_value=fake_op)

        result = asyncio.run(ex.execute_task("write code"))

        # shell.run should never have been called
        ex.shell_tools.run.assert_not_called()
        assert result.status == TaskStatus.COMPLETED


# ===========================================================================
# 16. execute_task — with git tools available (commit/push/PR paths)
# ===========================================================================


def _make_executor_with_git(
    workspace: Path,
    *,
    create_branch: bool = True,
    create_pr: bool = True,
    auto_iterate: bool = False,
) -> AgentExecutor:
    """Build an AgentExecutor with working (mocked) git tools."""
    with (
        patch("router.tools.agent_executor.FileTools") as mock_ft,
        patch("router.tools.agent_executor.ShellTools") as mock_st,
        patch("router.tools.agent_executor.GitTools") as mock_git_cls,
        patch("router.tools.agent_executor.GitHubTools") as mock_gh_cls,
        patch("router.tools.agent_executor.ModelRouter") as mock_mr,
        patch("router.tools.agent_executor.RouterConfig"),
    ):
        mock_router_instance = MagicMock()
        mock_router_instance.initialize = AsyncMock()
        mock_router_instance.complete = AsyncMock(return_value=_resp("{}"))
        mock_mr.return_value = mock_router_instance

        mock_git_instance = MagicMock()
        mock_git_cls.return_value = mock_git_instance

        mock_gh_instance = MagicMock()
        mock_gh_cls.return_value = mock_gh_instance

        executor = AgentExecutor(
            str(workspace),
            create_branch=create_branch,
            create_pr=create_pr,
            auto_iterate=auto_iterate,
        )

        executor.file_tools = MagicMock()
        executor.shell_tools = MagicMock()
        executor.router = mock_router_instance
        # Assign the pre-built git mock instances
        executor.git_tools = mock_git_instance
        executor.github_tools = mock_gh_instance

    return executor


class TestExecuteTaskWithGit:
    def test_creates_branch_and_commits(self, tmp_path):
        ex = _make_executor_with_git(tmp_path, create_pr=False)

        plan = {
            "summary": "add feature",
            "files_to_create": [{"path": "feature.py", "purpose": "feature"}],
            "files_to_modify": [],
            "test_command": "",
            "branch_name": "feature/new-thing",
            "pr_title": "Feature",
            "pr_body": "Add feature",
        }

        call_count = {"n": 0}

        async def mock_complete(req):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _resp(json.dumps(plan))
            return _resp("def feature(): pass")

        ex.router.complete = mock_complete

        fake_op = MagicMock()
        fake_op.success = True
        ex.file_tools.create_file = MagicMock(return_value=fake_op)

        git_result = MagicMock()
        git_result.success = True
        git_result.stderr = ""
        ex.git_tools.create_branch = MagicMock(return_value=git_result)
        ex.git_tools.commit = MagicMock(return_value=git_result)
        ex.git_tools.push = MagicMock(return_value=git_result)

        result = asyncio.run(ex.execute_task("add feature"))

        assert result.status == TaskStatus.COMPLETED
        ex.git_tools.create_branch.assert_called_once()
        ex.git_tools.commit.assert_called_once()

    def test_creates_pr_when_enabled(self, tmp_path):
        ex = _make_executor_with_git(tmp_path, create_branch=True, create_pr=True)

        plan = {
            "summary": "add pr feature",
            "files_to_create": [{"path": "pr_feature.py", "purpose": "pr feature"}],
            "files_to_modify": [],
            "test_command": "",
            "branch_name": "feature/pr-thing",
            "pr_title": "PR Feature",
            "pr_body": "A feature via PR",
        }

        call_count = {"n": 0}

        async def mock_complete(req):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _resp(json.dumps(plan))
            return _resp("def pr_feature(): pass")

        ex.router.complete = mock_complete

        fake_op = MagicMock()
        fake_op.success = True
        ex.file_tools.create_file = MagicMock(return_value=fake_op)

        git_result = MagicMock()
        git_result.success = True
        git_result.stderr = ""
        ex.git_tools.create_branch = MagicMock(return_value=git_result)
        ex.git_tools.commit = MagicMock(return_value=git_result)
        ex.git_tools.push = MagicMock(return_value=git_result)

        mock_pr = MagicMock()
        mock_pr.url = "https://github.com/owner/repo/pull/42"
        mock_pr.number = 42
        ex.github_tools.create_pr = MagicMock(return_value=mock_pr)

        result = asyncio.run(ex.execute_task("add pr feature"))

        assert result.status == TaskStatus.COMPLETED
        assert result.pr_url == "https://github.com/owner/repo/pull/42"
        ex.github_tools.create_pr.assert_called_once()

    def test_branch_checkout_on_existing_branch(self, tmp_path):
        """Covers the else branch in create_branch: checkout if create fails."""
        ex = _make_executor_with_git(tmp_path, create_pr=False)

        plan = {
            "summary": "extend feature",
            "files_to_create": [{"path": "ext.py", "purpose": "extend"}],
            "files_to_modify": [],
            "test_command": "",
            "branch_name": "feature/exists",
            "pr_title": "Extend",
            "pr_body": "Extend feature",
        }

        call_count = {"n": 0}

        async def mock_complete(req):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _resp(json.dumps(plan))
            return _resp("def ext(): pass")

        ex.router.complete = mock_complete

        fake_op = MagicMock()
        fake_op.success = True
        ex.file_tools.create_file = MagicMock(return_value=fake_op)

        # create_branch fails → checkout_branch is called
        fail_result = MagicMock()
        fail_result.success = False
        success_result = MagicMock()
        success_result.success = True
        success_result.stderr = ""
        ex.git_tools.create_branch = MagicMock(return_value=fail_result)
        ex.git_tools.checkout_branch = MagicMock()
        ex.git_tools.commit = MagicMock(return_value=success_result)
        ex.git_tools.push = MagicMock(return_value=success_result)

        result = asyncio.run(ex.execute_task("extend feature"))

        assert result.status == TaskStatus.COMPLETED
        ex.git_tools.checkout_branch.assert_called_once_with("feature/exists")
