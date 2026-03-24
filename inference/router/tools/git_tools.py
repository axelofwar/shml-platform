"""
Git Tools - Branch, commit, and repository operations

Provides git operations for:
- Creating feature branches
- Committing changes
- Pushing to remote
- Managing working tree
"""

import subprocess
import os
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class GitResult:
    """Result of a git operation"""

    success: bool
    command: str
    stdout: str
    stderr: str
    returncode: int


class GitTools:
    """
    Git operations for agent execution.

    Manages branches, commits, and sync with remote.
    """

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()

        # Verify it's a git repo
        if not (self.repo_path / ".git").exists():
            raise ValueError(f"Not a git repository: {repo_path}")

    def _run_git(self, *args: str, check: bool = False) -> GitResult:
        """Run a git command"""
        cmd = ["git", "-C", str(self.repo_path)] + list(args)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        git_result = GitResult(
            success=result.returncode == 0,
            command=" ".join(cmd),
            stdout=result.stdout.rstrip(),
            stderr=result.stderr.rstrip(),
            returncode=result.returncode,
        )

        if check and not git_result.success:
            raise RuntimeError(f"Git command failed: {git_result.stderr}")

        return git_result

    def get_current_branch(self) -> str:
        """Get current branch name"""
        result = self._run_git("rev-parse", "--abbrev-ref", "HEAD", check=True)
        return result.stdout

    def get_status(self) -> Dict[str, List[str]]:
        """Get working tree status"""
        result = self._run_git("status", "--porcelain")

        status = {
            "staged": [],
            "modified": [],
            "untracked": [],
            "deleted": [],
        }

        for line in result.stdout.splitlines():
            if not line:
                continue

            index_status = line[0]
            work_status = line[1]
            filepath = line[3:]

            if index_status in "MADRC":
                status["staged"].append(filepath)
            if work_status == "M":
                status["modified"].append(filepath)
            if work_status == "D":
                status["deleted"].append(filepath)
            if index_status == "?" and work_status == "?":
                status["untracked"].append(filepath)

        return status

    def create_branch(self, branch_name: str, from_branch: str = "main") -> GitResult:
        """
        Create a new branch from specified base.

        Args:
            branch_name: Name for new branch
            from_branch: Base branch (default: main)

        Returns:
            GitResult
        """
        # First, fetch to ensure we have latest
        self._run_git("fetch", "origin")

        # Checkout base branch and pull
        self._run_git("checkout", from_branch)
        self._run_git("pull", "origin", from_branch)

        # Create and checkout new branch
        result = self._run_git("checkout", "-b", branch_name)

        return result

    def checkout_branch(self, branch_name: str) -> GitResult:
        """Checkout existing branch"""
        return self._run_git("checkout", branch_name)

    def add_files(self, files: Optional[List[str]] = None) -> GitResult:
        """
        Stage files for commit.

        Args:
            files: List of file paths, or None for all changes
        """
        if files is None:
            return self._run_git("add", "-A")
        else:
            return self._run_git("add", *files)

    def commit(self, message: str, add_all: bool = True) -> GitResult:
        """
        Create a commit.

        Args:
            message: Commit message
            add_all: Whether to add all changes before commit
        """
        if add_all:
            self.add_files()

        return self._run_git("commit", "-m", message)

    def push(
        self, branch: Optional[str] = None, set_upstream: bool = True
    ) -> GitResult:
        """
        Push branch to remote.

        Args:
            branch: Branch to push (default: current)
            set_upstream: Whether to set upstream tracking
        """
        if branch is None:
            branch = self.get_current_branch()

        if set_upstream:
            return self._run_git("push", "-u", "origin", branch)
        else:
            return self._run_git("push", "origin", branch)

    def get_diff(self, staged: bool = False) -> str:
        """Get diff of changes"""
        if staged:
            result = self._run_git("diff", "--staged")
        else:
            result = self._run_git("diff")
        return result.stdout

    def get_log(self, count: int = 10) -> List[Dict[str, str]]:
        """Get recent commit log"""
        result = self._run_git("log", f"-{count}", "--pretty=format:%H|%an|%ae|%s|%ci")

        commits = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 5:
                commits.append(
                    {
                        "hash": parts[0],
                        "author": parts[1],
                        "email": parts[2],
                        "message": parts[3],
                        "date": parts[4],
                    }
                )

        return commits

    def stash(self, message: Optional[str] = None) -> GitResult:
        """Stash current changes"""
        if message:
            return self._run_git("stash", "push", "-m", message)
        return self._run_git("stash")

    def stash_pop(self) -> GitResult:
        """Pop last stash"""
        return self._run_git("stash", "pop")

    def reset_hard(self, ref: str = "HEAD") -> GitResult:
        """Hard reset to ref (destructive!)"""
        return self._run_git("reset", "--hard", ref)

    def get_remote_url(self) -> str:
        """Get origin remote URL"""
        result = self._run_git("remote", "get-url", "origin")
        return result.stdout

    def get_changed_files(self, base_branch: str = "main") -> List[str]:
        """Get list of files changed vs base branch"""
        result = self._run_git("diff", "--name-only", base_branch)
        return result.stdout.splitlines()

    def branch_exists(self, branch_name: str) -> bool:
        """Check if branch exists locally"""
        result = self._run_git("rev-parse", "--verify", branch_name)
        return result.success

    def delete_branch(self, branch_name: str, force: bool = False) -> GitResult:
        """Delete a local branch"""
        if force:
            return self._run_git("branch", "-D", branch_name)
        return self._run_git("branch", "-d", branch_name)
