from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ROUTER_TOOLS = _ROOT / "inference" / "router" / "tools"
_ROUTER = _ROOT / "inference" / "router"
_INFERENCE = _ROOT / "inference"

for _path in [str(_ROOT), str(_INFERENCE), str(_ROUTER), str(_ROUTER_TOOLS)]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tools.github_tools import GitHubTools, PRInfo


def _cp(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr)


class TestGitHubToolsInitAndHelpers:
    def test_init_verifies_gh_auth(self, tmp_path):
        with patch("tools.github_tools.subprocess.run", return_value=_cp() ) as run_mock:
            tools = GitHubTools(str(tmp_path))

        assert tools.repo_path == tmp_path.resolve()
        run_mock.assert_called_once_with(["gh", "auth", "status"], capture_output=True, text=True)

    def test_init_raises_when_gh_not_authenticated(self, tmp_path):
        with patch("tools.github_tools.subprocess.run", return_value=_cp(returncode=1)):
            with pytest.raises(RuntimeError, match="GitHub CLI not authenticated"):
                GitHubTools(str(tmp_path))

    def test_run_gh_uses_repo_cwd_and_returns_trimmed_output(self, tmp_path):
        with patch("tools.github_tools.subprocess.run", side_effect=[_cp(), _cp(stdout=" ok \n", stderr=" warn \n")]) as run_mock:
            tools = GitHubTools(str(tmp_path))
            result = tools._run_gh("pr", "status")

        assert result == {
            "success": True,
            "stdout": "ok",
            "stderr": "warn",
            "returncode": 0,
        }
        assert run_mock.call_args_list[1].kwargs["cwd"] == tmp_path.resolve()
        assert run_mock.call_args_list[1].args[0] == ["gh", "pr", "status"]

    def test_get_repo_info_returns_parsed_json_or_empty(self, tmp_path):
        payload = {
            "name": "shml-platform",
            "owner": {"login": "axelofwar"},
            "url": "https://github.com/axelofwar/shml-platform",
        }
        with patch(
            "tools.github_tools.subprocess.run",
            side_effect=[_cp(), _cp(stdout=json.dumps(payload)), _cp(returncode=1)],
        ):
            tools = GitHubTools(str(tmp_path))
            assert tools.get_repo_info() == payload
            assert tools.get_repo_info() == {}


class TestGitHubToolsPullRequests:
    def test_create_pr_builds_command_and_returns_prinfo(self, tmp_path):
        with patch(
            "tools.github_tools.subprocess.run",
            side_effect=[_cp(), _cp(stdout="https://github.com/org/repo/pull/42\n")],
        ) as run_mock:
            tools = GitHubTools(str(tmp_path))
            pr = tools.create_pr(
                title="Improve coverage",
                body="Detailed body",
                head_branch="feature/tests",
                base_branch="develop",
                draft=True,
                labels=["tests", "automation"],
            )

        assert pr == PRInfo(
            number=42,
            url="https://github.com/org/repo/pull/42",
            title="Improve coverage",
            state="open",
            head_branch="feature/tests",
            base_branch="develop",
            body="Detailed body",
            draft=True,
        )
        cmd = run_mock.call_args_list[1].args[0]
        assert cmd[:2] == ["gh", "pr"]
        assert "--draft" in cmd
        assert cmd.count("--label") == 2

    def test_create_pr_returns_none_when_command_fails(self, tmp_path, capsys):
        with patch(
            "tools.github_tools.subprocess.run",
            side_effect=[_cp(), _cp(returncode=1, stderr="boom")],
        ):
            tools = GitHubTools(str(tmp_path))
            pr = tools.create_pr("Title", "Body", "branch")

        assert pr is None
        assert "PR creation failed: boom" in capsys.readouterr().out

    def test_get_pr_returns_info_or_none(self, tmp_path):
        payload = {
            "number": 7,
            "url": "https://github.com/org/repo/pull/7",
            "title": "Fix bug",
            "state": "OPEN",
            "headRefName": "fix/bug",
            "baseRefName": "main",
            "body": "Summary",
            "isDraft": True,
            "mergeable": "MERGEABLE",
        }
        with patch(
            "tools.github_tools.subprocess.run",
            side_effect=[_cp(), _cp(stdout=json.dumps(payload)), _cp(returncode=1)],
        ):
            tools = GitHubTools(str(tmp_path))
            pr = tools.get_pr(7)
            missing = tools.get_pr(8)

        assert pr == PRInfo(
            number=7,
            url=payload["url"],
            title="Fix bug",
            state="OPEN",
            head_branch="fix/bug",
            base_branch="main",
            body="Summary",
            draft=True,
            mergeable="MERGEABLE",
        )
        assert missing is None

    def test_list_prs_supports_filters_and_failure(self, tmp_path):
        payload = [
            {
                "number": 1,
                "url": "https://github.com/org/repo/pull/1",
                "title": "One",
                "state": "OPEN",
                "headRefName": "branch-1",
                "baseRefName": "main",
                "isDraft": False,
            },
            {
                "number": 2,
                "url": "https://github.com/org/repo/pull/2",
                "title": "Two",
                "state": "OPEN",
                "headRefName": "branch-2",
                "baseRefName": "develop",
                "isDraft": True,
            },
        ]
        with patch(
            "tools.github_tools.subprocess.run",
            side_effect=[_cp(), _cp(stdout=json.dumps(payload)), _cp(returncode=1)],
        ) as run_mock:
            tools = GitHubTools(str(tmp_path))
            prs = tools.list_prs(head_branch="branch-1", limit=10)
            failed = tools.list_prs(state="closed")

        cmd = run_mock.call_args_list[1].args[0]
        assert cmd[:4] == ["gh", "pr", "list", "--state"]
        assert "--head" in cmd
        assert len(prs) == 2
        assert prs[1].draft is True
        assert failed == []

    def test_pr_mutation_helpers_reflect_return_codes_and_parse_checks(self, tmp_path):
        checks = [
            {"name": "unit", "state": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "lint", "state": "IN_PROGRESS", "conclusion": None},
        ]
        with patch(
            "tools.github_tools.subprocess.run",
            side_effect=[
                _cp(),
                _cp(),
                _cp(stdout=json.dumps(checks)),
                _cp(),
                _cp(returncode=1),
                _cp(),
                _cp(),
                _cp(returncode=1),
            ],
        ):
            tools = GitHubTools(str(tmp_path))
            assert tools.add_pr_comment(5, "Looks good") is True
            assert tools.get_pr_checks(5) == {"unit": "SUCCESS", "lint": "IN_PROGRESS"}
            assert tools.merge_pr(5, method="rebase", delete_branch=False) is True
            assert tools.close_pr(5) is False
            assert tools.update_pr(5, title="Retitle", body="New body") is True
            assert tools.ready_for_review(5) is True
            assert tools.get_pr_checks(99) == {}
