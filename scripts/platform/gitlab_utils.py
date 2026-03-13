#!/usr/bin/env python3
"""
gitlab_utils.py — Shared GitLab CE API helpers for SHML-Platform scripts.

Used by:
  • watchdog.sh          (via `python3 gitlab_utils.py create-issue ...`)
  • scan_repo_state.sh   (via `python3 gitlab_utils.py upsert-issue ...`)
  • kanban_updater.py    (import gitlab_utils)
  • autoresearch scripts (via CLI or import)

Environment:
  GITLAB_API_TOKEN          — Personal Access Token (PAT) with api scope
  GITLAB_BASE_URL           — e.g. http://shml-gitlab:8929/gitlab  (default)
  GITLAB_PROJECT_ID         — Numeric project ID (default: 2)

All functions work against the local GitLab CE container via Docker network.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── Configuration ────────────────────────────────────────────────────────────

_DEFAULT_BASE_URL = "http://shml-gitlab:8929/gitlab"
_DEFAULT_PROJECT_ID = "2"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _base_url() -> str:
    return _env("GITLAB_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def _project_id() -> str:
    return _env("GITLAB_PROJECT_ID", _DEFAULT_PROJECT_ID)


def _token() -> str:
    token = _env("GITLAB_API_TOKEN") or _env("GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError(
            "Set GITLAB_API_TOKEN or GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN"
        )
    return token


# ── Low-level API ────────────────────────────────────────────────────────────


def _api(
    method: str,
    path: str,
    *,
    data: dict | None = None,
    params: dict | None = None,
    timeout: int = 15,
) -> dict | list:
    """Make an authenticated request to the GitLab REST API."""
    base = _base_url()
    url = f"{base}/api/v4{path}"

    if params:
        qs = urllib.parse.urlencode(params)
        url = f"{url}?{qs}"

    body_bytes: bytes | None = None
    if data is not None:
        body_bytes = json.dumps(data).encode()

    req = urllib.request.Request(url, data=body_bytes, method=method)
    req.add_header("PRIVATE-TOKEN", _token())
    if body_bytes is not None:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode() if exc.fp else ""
        raise RuntimeError(
            f"GitLab API {method} {path} → {exc.code}: {err_body}"
        ) from exc


# ── Issue helpers ────────────────────────────────────────────────────────────


@dataclass
class Issue:
    iid: int
    title: str
    state: str
    labels: list[str] = field(default_factory=list)
    web_url: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Issue":
        return cls(
            iid=d["iid"],
            title=d["title"],
            state=d["state"],
            labels=d.get("labels", []),
            web_url=d.get("web_url", ""),
        )


def list_issues(
    *,
    state: str = "opened",
    labels: str | None = None,
    search: str | None = None,
    per_page: int = 20,
) -> list[Issue]:
    """List project issues with optional filters."""
    pid = _project_id()
    params: dict[str, str] = {"state": state, "per_page": str(per_page)}
    if labels:
        params["labels"] = labels
    if search:
        params["search"] = search
    raw = _api("GET", f"/projects/{pid}/issues", params=params)
    return [Issue.from_dict(d) for d in raw]


def get_issue(iid: int) -> Issue:
    """Get a single issue by IID."""
    pid = _project_id()
    d = _api("GET", f"/projects/{pid}/issues/{iid}")
    return Issue.from_dict(d)


def create_issue(
    title: str,
    *,
    description: str = "",
    labels: list[str] | None = None,
    confidential: bool = False,
) -> Issue:
    """Create a new issue. Returns the created Issue."""
    pid = _project_id()
    body: dict[str, Any] = {"title": title}
    if description:
        body["description"] = description
    if labels:
        body["labels"] = ",".join(labels)
    if confidential:
        body["confidential"] = True
    d = _api("POST", f"/projects/{pid}/issues", data=body)
    return Issue.from_dict(d)


def close_issue(iid: int) -> Issue:
    """Close an issue."""
    pid = _project_id()
    d = _api("PUT", f"/projects/{pid}/issues/{iid}", data={"state_event": "close"})
    return Issue.from_dict(d)


def reopen_issue(iid: int) -> Issue:
    """Reopen a closed issue."""
    pid = _project_id()
    d = _api("PUT", f"/projects/{pid}/issues/{iid}", data={"state_event": "reopen"})
    return Issue.from_dict(d)


def add_issue_comment(iid: int, body: str) -> dict:
    """Add a note (comment) to an issue."""
    pid = _project_id()
    return _api("POST", f"/projects/{pid}/issues/{iid}/notes", data={"body": body})


def update_issue_labels(iid: int, labels: list[str]) -> Issue:
    """Replace all labels on an issue."""
    pid = _project_id()
    d = _api(
        "PUT",
        f"/projects/{pid}/issues/{iid}",
        data={"labels": ",".join(labels)},
    )
    return Issue.from_dict(d)


def upsert_issue(
    search_title: str,
    *,
    title: str | None = None,
    description: str = "",
    labels: list[str] | None = None,
    comment: str | None = None,
    close_if_resolved: bool = False,
) -> Issue:
    """
    Find an open issue whose title contains `search_title`.
    If found, optionally add a comment and/or update labels.
    If not found, create a new issue.

    Useful for watchdog/scan scripts that detect the same condition repeatedly
    and want to avoid duplicate issues.
    """
    existing = list_issues(search=search_title, state="opened")
    # Exact substring match (GitLab search is fuzzy)
    match = None
    for issue in existing:
        if search_title.lower() in issue.title.lower():
            match = issue
            break

    if match:
        if comment:
            add_issue_comment(match.iid, comment)
        if labels:
            update_issue_labels(match.iid, labels)
        if close_if_resolved:
            return close_issue(match.iid)
        return match

    # Create new
    return create_issue(
        title or search_title,
        description=description,
        labels=labels,
    )


# ── Label helpers ────────────────────────────────────────────────────────────


def list_labels(*, per_page: int = 100) -> list[dict]:
    """List all project labels."""
    pid = _project_id()
    return _api("GET", f"/projects/{pid}/labels", params={"per_page": str(per_page)})


def ensure_label(
    name: str,
    *,
    color: str = "#428BCA",
    description: str = "",
) -> dict:
    """Create a label if it doesn't exist; return it either way."""
    existing = list_labels()
    for lab in existing:
        if lab["name"].lower() == name.lower():
            return lab
    pid = _project_id()
    return _api(
        "POST",
        f"/projects/{pid}/labels",
        data={"name": name, "color": color, "description": description},
    )


# ── Milestone helpers ────────────────────────────────────────────────────────


def list_milestones(*, state: str = "active") -> list[dict]:
    """List project milestones."""
    pid = _project_id()
    return _api(
        "GET",
        f"/projects/{pid}/milestones",
        params={"state": state, "per_page": "50"},
    )


def ensure_milestone(title: str, *, description: str = "") -> dict:
    """Create a milestone if it doesn't exist."""
    for ms in list_milestones():
        if ms["title"].lower() == title.lower():
            return ms
    pid = _project_id()
    body: dict[str, str] = {"title": title}
    if description:
        body["description"] = description
    return _api("POST", f"/projects/{pid}/milestones", data=body)


# ── Pipeline helpers ─────────────────────────────────────────────────────────


def get_latest_pipeline(ref: str = "main") -> dict | None:
    """Get the latest pipeline for a ref."""
    pid = _project_id()
    pipelines = _api(
        "GET",
        f"/projects/{pid}/pipelines",
        params={"ref": ref, "per_page": "1"},
    )
    return pipelines[0] if pipelines else None


def get_pipeline_jobs(pipeline_id: int) -> list[dict]:
    """List jobs in a pipeline."""
    pid = _project_id()
    return _api("GET", f"/projects/{pid}/pipelines/{pipeline_id}/jobs")


# ── CLI interface ────────────────────────────────────────────────────────────


def _cli_create_issue(args: list[str]) -> int:
    """CLI: create-issue <title> [--labels l1,l2] [--description text]"""
    import argparse

    parser = argparse.ArgumentParser(prog="gitlab_utils create-issue")
    parser.add_argument("title", help="Issue title")
    parser.add_argument("--labels", default="", help="Comma-separated labels")
    parser.add_argument("--description", default="", help="Issue body (markdown)")
    parser.add_argument("--confidential", action="store_true")
    parsed = parser.parse_args(args)

    labels = [l.strip() for l in parsed.labels.split(",") if l.strip()] or None
    issue = create_issue(
        parsed.title,
        description=parsed.description,
        labels=labels,
        confidential=parsed.confidential,
    )
    print(json.dumps({"iid": issue.iid, "title": issue.title, "url": issue.web_url}))
    return 0


def _cli_upsert_issue(args: list[str]) -> int:
    """CLI: upsert-issue <search_title> [--comment text] [--labels l1,l2] [--close]"""
    import argparse

    parser = argparse.ArgumentParser(prog="gitlab_utils upsert-issue")
    parser.add_argument("search_title", help="Title substring to search")
    parser.add_argument("--title", default=None, help="Full title for new issue")
    parser.add_argument("--labels", default="", help="Comma-separated labels")
    parser.add_argument("--description", default="", help="Issue body for new issue")
    parser.add_argument("--comment", default=None, help="Comment to add if issue exists")
    parser.add_argument("--close", action="store_true", help="Close if found")
    parsed = parser.parse_args(args)

    labels = [l.strip() for l in parsed.labels.split(",") if l.strip()] or None
    issue = upsert_issue(
        parsed.search_title,
        title=parsed.title,
        description=parsed.description,
        labels=labels,
        comment=parsed.comment,
        close_if_resolved=parsed.close,
    )
    print(json.dumps({"iid": issue.iid, "title": issue.title, "state": issue.state, "url": issue.web_url}))
    return 0


def _cli_add_comment(args: list[str]) -> int:
    """CLI: add-comment <iid> <body>"""
    if len(args) < 2:
        print("Usage: gitlab_utils add-comment <iid> <body>", file=sys.stderr)
        return 1
    iid = int(args[0])
    body = " ".join(args[1:])
    result = add_issue_comment(iid, body)
    print(json.dumps({"note_id": result.get("id"), "iid": iid}))
    return 0


def _cli_list_issues(args: list[str]) -> int:
    """CLI: list-issues [--state opened] [--labels label1,label2]"""
    import argparse

    parser = argparse.ArgumentParser(prog="gitlab_utils list-issues")
    parser.add_argument("--state", default="opened")
    parser.add_argument("--labels", default=None)
    parser.add_argument("--search", default=None)
    parsed = parser.parse_args(args)

    issues = list_issues(state=parsed.state, labels=parsed.labels, search=parsed.search)
    for iss in issues:
        print(f"  #{iss.iid:4d} [{iss.state:6s}] {iss.title}  labels={iss.labels}")
    return 0


def _cli_setup_board(args: list[str]) -> int:
    """CLI: setup-board — Create standard labels and milestones for the project."""
    print("Setting up GitLab Issues board...")

    # ── Labels ───────────────────────────────────────────────────────────
    label_defs = [
        # Type labels
        ("type::bug", "#CC0000", "Bug or regression"),
        ("type::feature", "#428BCA", "New feature or enhancement"),
        ("type::chore", "#A8D695", "Infrastructure, CI, maintenance"),
        ("type::training", "#7F8C8D", "ML training run or experiment"),
        ("type::security", "#D10069", "Security concern or fix"),
        # Priority labels
        ("priority::critical", "#CC0000", "Needs immediate attention"),
        ("priority::high", "#FC9403", "Important, schedule soon"),
        ("priority::medium", "#428BCA", "Normal priority"),
        ("priority::low", "#A8D695", "Nice to have"),
        # Status labels
        ("status::blocked", "#7F8C8D", "Blocked by external dependency"),
        ("status::stale", "#808080", "No activity for 7+ days"),
        # Component labels
        ("component::watchdog", "#9400D3", "Self-healing watchdog"),
        ("component::ci-cd", "#8B4513", "CI/CD pipeline"),
        ("component::autoresearch", "#FF6347", "Autoresearch training"),
        ("component::agent-service", "#4169E1", "Agent service / skills"),
        ("component::chat-ui", "#20B2AA", "Chat UI frontend"),
        ("component::fusionauth", "#DAA520", "FusionAuth / auth"),
        ("component::infra", "#2F4F4F", "Docker, Traefik, networking"),
        # Source labels
        ("source::watchdog", "#9400D3", "Auto-created by watchdog"),
        ("source::scan", "#FF6347", "Auto-created by scan_repo_state"),
        ("source::autoresearch", "#FF6347", "Auto-created by autoresearch"),
        ("source::ci", "#8B4513", "Auto-created by CI pipeline"),
    ]

    for name, color, desc in label_defs:
        lab = ensure_label(name, color=color, description=desc)
        print(f"  ✓ Label: {lab['name']}")

    # ── Milestones ───────────────────────────────────────────────────────
    milestone_defs = [
        ("v1.0 — Platform Stability", "Core services healthy, CI green, watchdog operational"),
        ("v1.1 — GitLab Integration", "Full GitLab-centric workflow: issues, CI, mirror"),
        ("v2.0 — Training Pipeline", "Autoresearch, model evaluation, MLflow tracking"),
    ]

    for title, desc in milestone_defs:
        ms = ensure_milestone(title, description=desc)
        print(f"  ✓ Milestone: {ms['title']}")

    print("Board setup complete.")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: python3 gitlab_utils.py <command> [args...]\n\n"
            "Commands:\n"
            "  create-issue   Create a new issue\n"
            "  upsert-issue   Find or create an issue (idempotent)\n"
            "  add-comment    Add a comment to an issue\n"
            "  list-issues    List open issues\n"
            "  setup-board    Create labels and milestones\n",
            file=sys.stderr,
        )
        return 1

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    dispatch = {
        "create-issue": _cli_create_issue,
        "upsert-issue": _cli_upsert_issue,
        "add-comment": _cli_add_comment,
        "list-issues": _cli_list_issues,
        "setup-board": _cli_setup_board,
    }

    handler = dispatch.get(cmd)
    if handler is None:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 1

    return handler(rest)


if __name__ == "__main__":
    sys.exit(main())
