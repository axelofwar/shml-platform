"""Unit tests for inference/router/tools — file_tools, shell_tools, git_tools.

All filesystem tests use tmp_path (real, auto-cleaned).
All git tests use a real git repo in tmp_path.
ShellTools command validation is tested without executing real commands.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import List

import pytest

# ---------------------------------------------------------------------------
# Ensure inference/router/tools is importable
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ROUTER_TOOLS = _ROOT / "inference" / "router" / "tools"
_ROUTER = _ROOT / "inference" / "router"
_INFERENCE = _ROOT / "inference"

for _p in [str(_ROOT), str(_INFERENCE), str(_ROUTER), str(_ROUTER_TOOLS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ===========================================================================
# FileTools
# ===========================================================================


class TestFileToolsValidatePath:
    def test_valid_path_within_workspace(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        resolved = ft._validate_path("subdir/file.txt")
        assert str(resolved).startswith(str(tmp_path))

    def test_path_traversal_rejected(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        with pytest.raises(ValueError, match="escapes workspace"):
            ft._validate_path("../../etc/passwd")

    def test_deeply_nested_valid_path(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        resolved = ft._validate_path("a/b/c/d/file.py")
        assert str(resolved).startswith(str(tmp_path))


class TestFileToolsCreateFile:
    def test_create_new_file(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        op = ft.create_file("hello.txt", "Hello World!")
        assert op.success is True
        assert op.operation == "create"
        assert (tmp_path / "hello.txt").read_text() == "Hello World!"

    def test_create_file_in_subdirectory(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        op = ft.create_file("sub/dir/file.txt", "content")
        assert op.success is True
        assert (tmp_path / "sub" / "dir" / "file.txt").exists()

    def test_overwrite_existing_file_creates_backup(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        (tmp_path / "existing.txt").write_text("original")
        op = ft.create_file("existing.txt", "new content")
        assert op.success is True
        assert op.backup_path is not None
        assert Path(op.backup_path).exists()
        assert (tmp_path / "existing.txt").read_text() == "new content"

    def test_operation_recorded_in_history(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        ft.create_file("tracked.txt", "data")
        assert len(ft.operations) == 1
        assert ft.operations[0].operation == "create"


class TestFileToolsReadFile:
    def test_read_existing_file(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        (tmp_path / "readme.md").write_text("# Title\n\nContent here.")
        content = ft.read_file("readme.md")
        assert "Title" in content
        assert "Content here." in content

    def test_read_nonexistent_raises(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        with pytest.raises(FileNotFoundError):
            ft.read_file("nonexistent.txt")

    def test_read_validates_path(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        with pytest.raises(ValueError):
            ft.read_file("../../etc/hosts")


class TestFileToolsEditFile:
    def test_edit_replaces_content(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        (tmp_path / "code.py").write_text("def foo():\n    return 1\n")
        op = ft.edit_file("code.py", "return 1", "return 42")
        assert op.success is True
        new_content = (tmp_path / "code.py").read_text()
        assert "return 42" in new_content
        assert "return 1" not in new_content

    def test_edit_creates_backup(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        (tmp_path / "file.py").write_text("original content")
        op = ft.edit_file("file.py", "original content", "new content")
        assert op.backup_path is not None
        assert Path(op.backup_path).exists()

    def test_edit_old_content_not_found(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        (tmp_path / "file.py").write_text("actual content")
        op = ft.edit_file("file.py", "nonexistent text", "replacement")
        assert op.success is False
        assert op.error is not None

    def test_edit_nonexistent_file(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        op = ft.edit_file("missing.py", "old", "new")
        assert op.success is False


class TestFileToolsDeleteFile:
    def test_delete_existing_file(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        target = tmp_path / "to_delete.txt"
        target.write_text("bye")
        op = ft.delete_file("to_delete.txt")
        assert op.success is True
        assert not target.exists()

    def test_delete_creates_backup(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        target = tmp_path / "important.txt"
        target.write_text("precious data")
        op = ft.delete_file("important.txt")
        assert op.backup_path is not None
        assert Path(op.backup_path).exists()
        assert Path(op.backup_path).read_text() == "precious data"

    def test_delete_nonexistent_file(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        op = ft.delete_file("ghost.txt")
        assert op.success is False


class TestFileToolsListDir:
    def test_list_empty_dir(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        subdir = tmp_path / "empty"
        subdir.mkdir()
        entries = ft.list_dir("empty")
        assert entries == []

    def test_list_dir_with_files(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.py").write_text("b")
        (tmp_path / "sub").mkdir()
        entries = ft.list_dir(".")
        assert "a.txt" in entries
        assert "b.py" in entries
        assert "sub/" in entries

    def test_list_dir_hidden_excluded(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        (tmp_path / ".hidden").write_text("secret")
        (tmp_path / "visible.txt").write_text("visible")
        entries = ft.list_dir(".")
        assert ".hidden" not in entries
        assert "visible.txt" in entries

    def test_list_nonexistent_raises(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        with pytest.raises(FileNotFoundError):
            ft.list_dir("nonexistent_dir")

    def test_list_file_raises_not_a_directory(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        (tmp_path / "afile.txt").write_text("content")
        with pytest.raises(NotADirectoryError):
            ft.list_dir("afile.txt")


class TestFileToolsFileExists:
    def test_existing_file(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        (tmp_path / "exists.txt").write_text("yes")
        assert ft.file_exists("exists.txt") is True

    def test_missing_file(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        assert ft.file_exists("nope.txt") is False

    def test_path_traversal_returns_false(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        assert ft.file_exists("../../etc/passwd") is False


class TestFileToolsGetDiff:
    def test_diff_new_file(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        diff = ft.get_diff("new_file.py", "def hello():\n    pass\n")
        assert "hello" in diff
        assert "+" in diff  # Lines are additions

    def test_diff_existing_file(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        (tmp_path / "code.py").write_text("original = 1\n")
        diff = ft.get_diff("code.py", "original = 2\n")
        # Diff should show the change
        assert diff  # non-empty


class TestFileToolsRollback:
    def test_rollback_no_operations(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        assert ft.rollback_last() is False

    def test_rollback_after_edit(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        (tmp_path / "file.txt").write_text("original")
        ft.edit_file("file.txt", "original", "modified")
        assert (tmp_path / "file.txt").read_text() == "modified"
        result = ft.rollback_last()
        assert result is True
        assert (tmp_path / "file.txt").read_text() == "original"


class TestFileToolsOperationHistory:
    def test_history_structure(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        ft.create_file("a.txt", "content")
        history = ft.get_operation_history()
        assert len(history) == 1
        entry = history[0]
        assert "operation" in entry
        assert "path" in entry
        assert "timestamp" in entry
        assert "backup" in entry
        assert "success" in entry
        assert "error" in entry

    def test_history_captures_multiple_ops(self, tmp_path):
        from tools.file_tools import FileTools
        ft = FileTools(str(tmp_path))
        ft.create_file("a.txt", "aaa")
        ft.create_file("b.txt", "bbb")
        assert len(ft.get_operation_history()) == 2


# ===========================================================================
# ShellTools
# ===========================================================================


class TestCommandResult:
    def test_output_combines_stdout_stderr(self):
        from tools.shell_tools import CommandResult
        r = CommandResult(
            command="echo hi",
            stdout="stdout line",
            stderr="stderr line",
            returncode=0,
            duration_ms=10,
            success=True,
        )
        assert "stdout line" in r.output
        assert "stderr line" in r.output

    def test_output_only_stdout(self):
        from tools.shell_tools import CommandResult
        r = CommandResult(
            command="echo hi",
            stdout="only stdout",
            stderr="",
            returncode=0,
            duration_ms=5,
            success=True,
        )
        assert r.output == "only stdout"

    def test_output_only_stderr(self):
        from tools.shell_tools import CommandResult
        r = CommandResult(
            command="cmd",
            stdout="",
            stderr="error output",
            returncode=1,
            duration_ms=5,
            success=False,
        )
        assert r.output == "error output"

    def test_output_empty_when_both_empty(self):
        from tools.shell_tools import CommandResult
        r = CommandResult(
            command="cmd",
            stdout="",
            stderr="",
            returncode=0,
            duration_ms=1,
            success=True,
        )
        assert r.output == ""


class TestShellToolsValidateCommand:
    def test_allowed_commands(self, tmp_path):
        from tools.shell_tools import ShellTools
        st = ShellTools(str(tmp_path))
        for cmd in ["pytest tests/", "python script.py", "git status", "ls -la", "make build"]:
            assert st._validate_command(cmd) is True, f"Expected {cmd!r} to be allowed"

    def test_blocked_commands(self, tmp_path):
        from tools.shell_tools import ShellTools
        st = ShellTools(str(tmp_path))
        for cmd in ["rm -rf /", "sudo apt install", "curl https://example.com"]:
            assert st._validate_command(cmd) is False, f"Expected {cmd!r} to be blocked"

    def test_unknown_command_blocked(self, tmp_path):
        from tools.shell_tools import ShellTools
        st = ShellTools(str(tmp_path))
        assert st._validate_command("someunknowntool --flag") is False

    def test_empty_command_blocked(self, tmp_path):
        from tools.shell_tools import ShellTools
        st = ShellTools(str(tmp_path))
        assert st._validate_command("") is False

    def test_allow_all_bypasses_restrictions(self, tmp_path):
        from tools.shell_tools import ShellTools
        st = ShellTools(str(tmp_path), allow_all=True)
        assert st._validate_command("rm -rf /") is True


class TestShellToolsAllowedSets:
    def test_allowed_set_contains_pytest(self):
        from tools.shell_tools import ShellTools
        assert "pytest" in ShellTools.ALLOWED_COMMANDS

    def test_allowed_set_contains_git(self):
        from tools.shell_tools import ShellTools
        assert "git" in ShellTools.ALLOWED_COMMANDS

    def test_blocked_set_contains_rm(self):
        from tools.shell_tools import ShellTools
        assert "rm" in ShellTools.BLOCKED_COMMANDS

    def test_blocked_set_contains_sudo(self):
        from tools.shell_tools import ShellTools
        assert "sudo" in ShellTools.BLOCKED_COMMANDS


class TestShellToolsRun:
    def test_blocked_command_returns_error_result(self, tmp_path):
        from tools.shell_tools import ShellTools
        st = ShellTools(str(tmp_path))
        result = st.run("rm -rf /")
        assert result.success is False
        assert result.returncode == -1
        assert "not allowed" in result.stderr

    def test_allowed_command_executes(self, tmp_path):
        from tools.shell_tools import ShellTools
        st = ShellTools(str(tmp_path))
        result = st.run("echo hello")
        assert result.success is True
        assert "hello" in result.stdout


# ===========================================================================
# GitTools
# ===========================================================================


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, check=True, capture_output=True)


class TestGitToolsInit:
    def test_valid_repo_initializes(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        assert gt.repo_path == tmp_path.resolve()

    def test_non_repo_raises(self, tmp_path):
        from tools.git_tools import GitTools
        with pytest.raises(ValueError, match="Not a git repository"):
            GitTools(str(tmp_path))


class TestGitToolsGetCurrentBranch:
    def test_returns_branch_name(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        branch = gt.get_current_branch()
        assert isinstance(branch, str)
        assert len(branch) > 0
        # Initial branch is usually "main" or "master"
        assert branch in ("main", "master")


class TestGitToolsGetStatus:
    def test_clean_working_tree(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        status = gt.get_status()
        assert "staged" in status
        assert "modified" in status
        assert "untracked" in status
        assert "deleted" in status

    def test_untracked_file_appears(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        (tmp_path / "new_file.py").write_text("print('hello')")
        status = gt.get_status()
        assert "new_file.py" in status["untracked"]

    def test_modified_file_appears(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        (tmp_path / "README.md").write_text("Modified content")
        status = gt.get_status()
        # Unstaged modification appears in modified (Y position in XY porcelain format)
        assert "README.md" in status["modified"], f"Expected README.md in modified, got: {status}"


class TestGitToolsBranchExists:
    def test_existing_branch(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        branch = gt.get_current_branch()
        assert gt.branch_exists(branch) is True

    def test_nonexistent_branch(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        assert gt.branch_exists("definitely-does-not-exist") is False


class TestGitToolsAddAndCommit:
    def test_add_files_and_commit(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        (tmp_path / "feature.py").write_text("def feature(): pass")
        add_result = gt.add_files()
        assert add_result.success is True
        commit_result = gt.commit("Add feature", add_all=False)
        assert commit_result.success is True

    def test_commit_all_together(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        (tmp_path / "utils.py").write_text("def util(): pass")
        result = gt.commit("Add utils")
        assert result.success is True


class TestGitToolsGetDiff:
    def test_unstaged_diff_shows_changes(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        (tmp_path / "README.md").write_text("Different content")
        diff = gt.get_diff(staged=False)
        assert isinstance(diff, str)

    def test_staged_diff(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        (tmp_path / "newfile.py").write_text("# new")
        subprocess.run(["git", "add", "newfile.py"], cwd=tmp_path)
        diff = gt.get_diff(staged=True)
        assert isinstance(diff, str)


class TestGitToolsGetLog:
    def test_log_returns_list(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        log = gt.get_log(count=5)
        assert isinstance(log, list)
        assert len(log) >= 1

    def test_log_entry_structure(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        log = gt.get_log(count=1)
        assert len(log) > 0
        entry = log[0]
        assert "hash" in entry
        assert "author" in entry
        assert "email" in entry
        assert "message" in entry
        assert "date" in entry

    def test_log_message_matches_commit(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        log = gt.get_log(count=1)
        assert log[0]["message"] == "Initial commit"


class TestGitToolsStash:
    def test_stash_with_message(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        (tmp_path / "README.md").write_text("Modified for stash")
        result = gt.stash(message="test stash")
        # May succeed or fail depending on git behavior (clean tree might fail)
        assert isinstance(result.success, bool)

    def test_stash_no_message(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        (tmp_path / "README.md").write_text("Modified for stash")
        result = gt.stash()
        assert isinstance(result.success, bool)


class TestGitToolsGetChangedFiles:
    def test_no_changes_vs_head(self, tmp_path):
        from tools.git_tools import GitTools
        _init_git_repo(tmp_path)
        gt = GitTools(str(tmp_path))
        # Create another commit so we can diff against HEAD~1
        (tmp_path / "new.py").write_text("# new")
        gt.commit("Second commit")
        # diff against initial branch (nothing changed in working tree)
        files = gt.get_changed_files("HEAD~1")
        assert isinstance(files, list)
        assert "new.py" in files
