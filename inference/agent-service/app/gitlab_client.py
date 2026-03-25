"""
Async GitLab CE API client for the agent-service container.

Designed to work inside Docker (no service_discovery.py access — uses
GITLAB_BASE_URL env var set by docker-compose from the platform .env).

Token hierarchy:
  1. GITLAB_API_TOKEN          — primary PAT (api + read_user scope)
  2. GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN — legacy alias
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# defaults injected via docker-compose env
_DEFAULT_BASE = "http://shml-gitlab:8929/gitlab"
_DEFAULT_PROJECT_ID = "2"


def _token() -> str:
    t = os.getenv("GITLAB_API_TOKEN") or os.getenv(
        "GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN"
    )
    if not t:
        raise RuntimeError(
            "GITLAB_API_TOKEN not set — add it to agent-service docker-compose env"
        )
    return t


def _base_url() -> str:
    return (os.getenv("GITLAB_BASE_URL") or _DEFAULT_BASE).rstrip("/")


def _project_id() -> str:
    return os.getenv("GITLAB_PROJECT_ID", _DEFAULT_PROJECT_ID)


def _headers() -> dict[str, str]:
    return {"PRIVATE-TOKEN": _token(), "Content-Type": "application/json"}


# ── Domain model ──────────────────────────────────────────────────────────────


@dataclass
class Issue:
    iid: int
    title: str
    state: str
    labels: list[str] = field(default_factory=list)
    web_url: str = ""
    description: str = ""
    assignees: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Issue":
        return cls(
            iid=d["iid"],
            title=d["title"],
            state=d["state"],
            labels=d.get("labels", []),
            web_url=d.get("web_url", ""),
            description=d.get("description") or "",
            assignees=d.get("assignees", []),
        )

    def to_summary(self) -> dict:
        return {
            "iid": self.iid,
            "title": self.title,
            "state": self.state,
            "labels": self.labels,
            "url": self.web_url,
        }


# ── Low-level async wrapper ───────────────────────────────────────────────────


async def _api(
    method: str,
    path: str,
    *,
    data: dict | None = None,
    params: dict | None = None,
    timeout: int = 15,
) -> Any:
    """Single async GitLab REST call."""
    url = f"{_base_url()}/api/v4{path}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method,
            url,
            headers=_headers(),
            params=params,
            json=data,
        )
    if not resp.is_success:
        raise RuntimeError(
            f"GitLab API {method} {path} → {resp.status_code}: {resp.text[:400]}"
        )
    text = resp.text.strip()
    if not text:
        return {}
    return resp.json()


# ── Issue operations ──────────────────────────────────────────────────────────


async def list_issues(
    *,
    state: str = "opened",
    labels: str | None = None,
    search: str | None = None,
    assignee_labels: str | None = None,
    per_page: int = 20,
) -> list[Issue]:
    pid = _project_id()
    p: dict[str, str] = {"state": state, "per_page": str(per_page)}
    if labels:
        p["labels"] = labels
    if search:
        p["search"] = search
    raw = await _api("GET", f"/projects/{pid}/issues", params=p)
    issues = [Issue.from_dict(d) for d in raw]
    if assignee_labels:
        # Filter to issues that have ALL given labels (GitLab search is OR)
        required = {l.strip() for l in assignee_labels.split(",") if l.strip()}
        issues = [i for i in issues if required.issubset(set(i.labels))]
    return issues


async def get_issue(iid: int) -> Issue:
    pid = _project_id()
    d = await _api("GET", f"/projects/{pid}/issues/{iid}")
    return Issue.from_dict(d)


async def create_issue(
    title: str,
    *,
    description: str = "",
    labels: list[str] | None = None,
    milestone_id: int | None = None,
) -> Issue:
    pid = _project_id()
    body: dict[str, Any] = {"title": title}
    if description:
        body["description"] = description
    if labels:
        body["labels"] = ",".join(labels)
    if milestone_id is not None:
        body["milestone_id"] = milestone_id
    d = await _api("POST", f"/projects/{pid}/issues", data=body)
    return Issue.from_dict(d)


async def update_issue(
    iid: int,
    *,
    labels: list[str] | None = None,
    state_event: str | None = None,
    description: str | None = None,
    assignee_ids: list[int] | None = None,
) -> Issue:
    pid = _project_id()
    body: dict[str, Any] = {}
    if labels is not None:
        body["labels"] = ",".join(labels)
    if state_event is not None:
        body["state_event"] = state_event
    if description is not None:
        body["description"] = description
    if assignee_ids is not None:
        body["assignee_ids"] = assignee_ids
    d = await _api("PUT", f"/projects/{pid}/issues/{iid}", data=body)
    return Issue.from_dict(d)


async def add_comment(iid: int, body: str) -> dict:
    pid = _project_id()
    return await _api(
        "POST", f"/projects/{pid}/issues/{iid}/notes", data={"body": body}
    )


async def close_issue(iid: int) -> Issue:
    return await update_issue(iid, state_event="close")


# ── Agent workflow helpers ────────────────────────────────────────────────────


def _replace_status_label(labels: list[str], new_status: str) -> list[str]:
    """Replace any existing status:: label with the new one."""
    out = [l for l in labels if not l.startswith("status::")]
    out.append(new_status)
    return out


async def claim_issue(iid: int, plan: str = "") -> Issue:
    """
    Mark an issue as taken by the agent:
    - Sets status::in-progress
    - Adds assignee::agent label
    - Posts a comment with the agent's plan

    Returns the updated Issue.
    """
    issue = await get_issue(iid)
    new_labels = _replace_status_label(issue.labels, "status::in-progress")
    if "assignee::agent" not in new_labels:
        new_labels.append("assignee::agent")
    updated = await update_issue(iid, labels=new_labels)

    comment = f"🤖 **Agent taking this on.**\n\n"
    if plan:
        comment += f"**Plan:**\n{plan}\n\n"
    comment += "_Status set to `in-progress`. Will update when complete._"
    await add_comment(iid, comment)

    logger.info("Agent claimed issue #%d", iid)
    return updated


async def complete_issue(iid: int, summary: str = "") -> Issue:
    """
    Mark an issue as done by the agent:
    - Sets status::done
    - Removes assignee::agent
    - Posts a completion comment
    - Closes the issue

    Returns the closed Issue.
    """
    issue = await get_issue(iid)
    new_labels = _replace_status_label(issue.labels, "status::done")
    new_labels = [l for l in new_labels if l != "assignee::agent"]

    comment = f"✅ **Agent completed this issue.**\n\n"
    if summary:
        comment += f"**Summary:**\n{summary}\n\n"
    comment += "_Closing issue._"
    await add_comment(iid, comment)

    return await update_issue(iid, labels=new_labels, state_event="close")


async def triage_issue(
    iid: int,
    *,
    priority: str | None = None,
    type_label: str | None = None,
    component: str | None = None,
    comment: str | None = None,
) -> Issue:
    """
    Triage an issue into the backlog with proper labels.

    priority: "critical" | "high" | "medium" | "low"
    type_label: "bug" | "feature" | "chore" | "training" | "security"
    component: "infra" | "ci-cd" | "agent-service" | "chat-ui" | etc.
    """
    issue = await get_issue(iid)
    new_labels = list(issue.labels)

    if priority:
        new_labels = [l for l in new_labels if not l.startswith("priority::")]
        new_labels.append(f"priority::{priority}")
    if type_label:
        new_labels = [l for l in new_labels if not l.startswith("type::")]
        new_labels.append(f"type::{type_label}")
    if component:
        new_labels = [l for l in new_labels if not l.startswith("component::")]
        new_labels.append(f"component::{component}")

    # Move to backlog if still in triage
    if "status::triage" in new_labels or not any(
        l.startswith("status::") for l in new_labels
    ):
        new_labels = _replace_status_label(new_labels, "status::backlog")

    updated = await update_issue(iid, labels=new_labels)

    if comment:
        await add_comment(iid, f"🏷️ **Triaged.**\n\n{comment}")

    return updated


async def list_agent_queue(limit: int = 10) -> list[Issue]:
    """
    Return issues tagged for the agent: status::backlog + assignee::agent
    OR issues that have no assignee and are in backlog with small scope.
    Ordered by priority (critical → high → medium → low).
    """
    issues = await list_issues(
        labels="assignee::agent,status::backlog", per_page=limit
    )

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def _priority_key(issue: Issue) -> int:
        for label in issue.labels:
            if label.startswith("priority::"):
                p = label.split("::", 1)[1]
                return priority_order.get(p, 4)
        return 4

    return sorted(issues, key=_priority_key)


async def get_current_user() -> dict:
    """Return the authenticated GitLab user object."""
    return await _api("GET", "/user")


async def list_labels() -> list[str]:
    """Return all label names in the project."""
    pid = _project_id()
    raw = await _api("GET", f"/projects/{pid}/labels", params={"per_page": "100"})
    return [d["name"] for d in raw]


async def create_label(
    name: str, color: str, description: str = ""
) -> dict:
    pid = _project_id()
    return await _api(
        "POST",
        f"/projects/{pid}/labels",
        data={"name": name, "color": color, "description": description},
    )


async def list_milestones() -> list[dict]:
    pid = _project_id()
    raw = await _api(
        "GET", f"/projects/{pid}/milestones", params={"state": "active", "per_page": "20"}
    )
    return raw


async def create_milestone(
    title: str,
    *,
    description: str = "",
    due_date: Optional[str] = None,
) -> dict:
    pid = _project_id()
    body: dict[str, Any] = {"title": title}
    if description:
        body["description"] = description
    if due_date:
        body["due_date"] = due_date
    return await _api("POST", f"/projects/{pid}/milestones", data=body)
