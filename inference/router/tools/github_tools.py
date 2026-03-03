"""
GitHub Tools - PR creation and management

Uses GitHub CLI (gh) for:
- Creating pull requests
- Checking PR status
- Adding comments/reviews
"""

import subprocess
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class PRInfo:
    """Pull request information"""

    number: int
    url: str
    title: str
    state: str
    head_branch: str
    base_branch: str
    body: Optional[str] = None
    draft: bool = False
    mergeable: Optional[bool] = None
    checks_status: Optional[str] = None


class GitHubTools:
    """
    GitHub operations using gh CLI.

    Requires: gh auth login
    """

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        self._verify_gh_auth()

    def _verify_gh_auth(self):
        """Verify gh CLI is authenticated"""
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError("GitHub CLI not authenticated. Run: gh auth login")

    def _run_gh(self, *args: str) -> Dict[str, Any]:
        """Run gh command and return result"""
        cmd = ["gh", "-R", str(self.repo_path)] + list(args)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }

    def get_repo_info(self) -> Dict[str, str]:
        """Get repository info"""
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "name,owner,url,defaultBranchRef"],
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )

        if result.returncode == 0:
            return json.loads(result.stdout)
        return {}

    def create_pr(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        draft: bool = False,
        labels: Optional[List[str]] = None,
    ) -> Optional[PRInfo]:
        """
        Create a pull request.

        Args:
            title: PR title
            body: PR description (markdown)
            head_branch: Source branch
            base_branch: Target branch (default: main)
            draft: Create as draft PR
            labels: Optional labels to add

        Returns:
            PRInfo or None if failed
        """
        cmd = [
            "gh",
            "pr",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--head",
            head_branch,
            "--base",
            base_branch,
        ]

        if draft:
            cmd.append("--draft")

        if labels:
            for label in labels:
                cmd.extend(["--label", label])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )

        if result.returncode != 0:
            print(f"PR creation failed: {result.stderr}")
            return None

        # Parse PR URL from output
        pr_url = result.stdout.strip()

        # Get PR number from URL
        pr_number = int(pr_url.split("/")[-1])

        return PRInfo(
            number=pr_number,
            url=pr_url,
            title=title,
            state="open",
            head_branch=head_branch,
            base_branch=base_branch,
            body=body,
            draft=draft,
        )

    def get_pr(self, pr_number: int) -> Optional[PRInfo]:
        """Get PR info by number"""
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--json",
                "number,url,title,state,headRefName,baseRefName,body,isDraft,mergeable",
            ],
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )

        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)

        return PRInfo(
            number=data["number"],
            url=data["url"],
            title=data["title"],
            state=data["state"],
            head_branch=data["headRefName"],
            base_branch=data["baseRefName"],
            body=data.get("body"),
            draft=data.get("isDraft", False),
            mergeable=data.get("mergeable"),
        )

    def list_prs(
        self,
        state: str = "open",
        head_branch: Optional[str] = None,
        limit: int = 30,
    ) -> List[PRInfo]:
        """List pull requests"""
        cmd = [
            "gh",
            "pr",
            "list",
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            "number,url,title,state,headRefName,baseRefName,isDraft",
        ]

        if head_branch:
            cmd.extend(["--head", head_branch])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )

        if result.returncode != 0:
            return []

        prs = json.loads(result.stdout)

        return [
            PRInfo(
                number=pr["number"],
                url=pr["url"],
                title=pr["title"],
                state=pr["state"],
                head_branch=pr["headRefName"],
                base_branch=pr["baseRefName"],
                draft=pr.get("isDraft", False),
            )
            for pr in prs
        ]

    def add_pr_comment(self, pr_number: int, comment: str) -> bool:
        """Add comment to PR"""
        result = subprocess.run(
            ["gh", "pr", "comment", str(pr_number), "--body", comment],
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )
        return result.returncode == 0

    def get_pr_checks(self, pr_number: int) -> Dict[str, str]:
        """Get CI check status for PR"""
        result = subprocess.run(
            ["gh", "pr", "checks", str(pr_number), "--json", "name,state,conclusion"],
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )

        if result.returncode != 0:
            return {}

        checks = json.loads(result.stdout)
        return {
            check["name"]: check.get("conclusion") or check["state"] for check in checks
        }

    def merge_pr(
        self,
        pr_number: int,
        method: str = "squash",  # merge, squash, rebase
        delete_branch: bool = True,
    ) -> bool:
        """Merge a PR"""
        cmd = [
            "gh",
            "pr",
            "merge",
            str(pr_number),
            f"--{method}",
        ]

        if delete_branch:
            cmd.append("--delete-branch")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )

        return result.returncode == 0

    def close_pr(self, pr_number: int) -> bool:
        """Close a PR without merging"""
        result = subprocess.run(
            ["gh", "pr", "close", str(pr_number)],
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )
        return result.returncode == 0

    def update_pr(
        self,
        pr_number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
    ) -> bool:
        """Update PR title/body"""
        cmd = ["gh", "pr", "edit", str(pr_number)]

        if title:
            cmd.extend(["--title", title])
        if body:
            cmd.extend(["--body", body])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )

        return result.returncode == 0

    def ready_for_review(self, pr_number: int) -> bool:
        """Mark draft PR as ready for review"""
        result = subprocess.run(
            ["gh", "pr", "ready", str(pr_number)],
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )
        return result.returncode == 0
