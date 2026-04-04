#!/usr/bin/env python3
"""
gitlab_utils.py — Shared GitLab CE API helpers for SHML-Platform scripts.

Used by:
  • watchdog.sh          (via `python3 gitlab_utils.py create-issue ...`)
  • scan_repo_state.sh   (via `python3 gitlab_utils.py upsert-issue ...`)
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
from pathlib import Path
from typing import Any

try:
    from service_discovery import resolve_gitlab_base_url
except ModuleNotFoundError:  # pragma: no cover - script execution fallback
    sys.path.insert(0, os.path.dirname(__file__))
    from service_discovery import resolve_gitlab_base_url

# ── Configuration ────────────────────────────────────────────────────────────

_DEFAULT_BASE_URL = "http://shml-gitlab:8929/gitlab"
_DEFAULT_PROJECT_ID = "2"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_CANDIDATES = (
    _REPO_ROOT / ".env",
    _REPO_ROOT / "ray_compute" / ".env",
)
_ENV_KEYS = {
    "GITLAB_API_TOKEN",
    "GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN",
    "GITLAB_CICD_ACCESS_TOKEN",
    "GITLAB_BASE_URL",
    "GITLAB_PROJECT_ID",
}
_ENV_FILE_CACHE: dict[str, str] | None = None


def _load_env_file_cache() -> dict[str, str]:
    global _ENV_FILE_CACHE
    if _ENV_FILE_CACHE is not None:
        return _ENV_FILE_CACHE

    values: dict[str, str] = {}
    for env_path in _ENV_CANDIDATES:
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key not in _ENV_KEYS or key in values:
                continue
            values[key] = value.strip().strip('"').strip("'")

    _ENV_FILE_CACHE = values
    return values


def _env(key: str, default: str = "") -> str:
    if key in os.environ:
        return os.environ[key]
    return _load_env_file_cache().get(key, default)


def _base_url() -> str:
    # os.environ takes top priority (explicit override); otherwise use auto-discovery
    # (docker inspect) which handles container IP changes. Avoid reading GITLAB_BASE_URL
    # from .env since that value can become stale when containers restart.
    if "GITLAB_BASE_URL" in os.environ:
        return os.environ["GITLAB_BASE_URL"].rstrip("/")
    return resolve_gitlab_base_url().rstrip("/")


def _project_id() -> str:
    return _env("GITLAB_PROJECT_ID", _DEFAULT_PROJECT_ID)


def _token() -> str:
    # Preference order:
    #   1. GITLAB_API_TOKEN          — generic, set to root PAT (see .env comment for regen)
    #   2. GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN — legacy, may be expired
    #   3. GITLAB_CICD_ACCESS_TOKEN  — group bot, read-only, limited scope (last resort)
    token = (
        _env("GITLAB_API_TOKEN")
        or _env("GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN")
        or _env("GITLAB_CICD_ACCESS_TOKEN")
    )
    if not token:
        raise RuntimeError(
            "Set GITLAB_API_TOKEN in .env (regenerate via gitlab-rails runner — see .env comment)"
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
    milestone_id: int | None = None,
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
    if milestone_id is not None:
        body["milestone_id"] = milestone_id
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


def update_issue(
    iid: int,
    *,
    title: str | None = None,
    description: str | None = None,
    labels: list[str] | None = None,
    state_event: str | None = None,
    milestone_id: int | None = None,
) -> Issue:
    """Update an existing issue (title, description, labels, state, milestone)."""
    pid = _project_id()
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if description is not None:
        body["description"] = description
    if labels is not None:
        body["labels"] = ",".join(labels)
    if state_event is not None:
        body["state_event"] = state_event
    if milestone_id is not None:
        body["milestone_id"] = milestone_id
    d = _api("PUT", f"/projects/{pid}/issues/{iid}", data=body)
    return Issue.from_dict(d)


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
    reopen_closed: bool = False,
    milestone_id: int | None = None,
) -> Issue:
    """
    Find an open issue whose title contains `search_title`.
    If found, optionally add a comment and/or update labels.
    If not found, create a new issue.

    Useful for watchdog/scan scripts that detect the same condition repeatedly
    and want to avoid duplicate issues.
    """
    existing = list_issues(search=search_title, state="all", per_page=100)
    # Exact substring match (GitLab search is fuzzy)
    match = None
    closed_match = None
    for issue in existing:
        if search_title.lower() in issue.title.lower():
            if issue.state == "opened" and match is None:
                match = issue
            elif issue.state == "closed" and closed_match is None:
                closed_match = issue

    if match:
        if comment:
            add_issue_comment(match.iid, comment)
        if labels:
            update_issue_labels(match.iid, labels)
        if close_if_resolved:
            # Stamp status::done before closing so the board column is correct
            current_labels = [lbl for lbl in match.labels if not lbl.startswith("status::")]
            current_labels.append("status::done")
            update_issue_labels(match.iid, current_labels)
            return close_issue(match.iid)
        return match

    if reopen_closed and closed_match:
        reopened = update_issue(
            closed_match.iid,
            title=title,
            description=description or None,
            labels=labels,
            state_event="reopen",
            milestone_id=milestone_id,
        )
        if comment:
            add_issue_comment(reopened.iid, comment)
        return reopened

    # Create new
    return create_issue(
        title or search_title,
        description=description,
        labels=labels,
        milestone_id=milestone_id,
    )


def resolve_issue(
    search_title: str,
    *,
    comment: str | None = None,
    extra_labels: list[str] | None = None,
) -> Issue | None:
    """
    Mark an open incident as resolved: set status::done, add an optional
    comment, then close the issue.

    Returns the closed Issue on success, or None if no open match is found.
    This is the counterpart to upsert_issue for the recovery / resolution path.
    """
    existing = list_issues(search=search_title, state="opened", per_page=100)
    match = None
    for issue in existing:
        if search_title.lower() in issue.title.lower():
            match = issue
            break

    if match is None:
        return None  # No open incident to close — that's fine

    # Strip all status:: labels and apply status::done
    new_labels = [lbl for lbl in match.labels if not lbl.startswith("status::")]
    new_labels.append("status::done")
    if extra_labels:
        new_labels.extend(extra_labels)
    update_issue_labels(match.iid, new_labels)

    if comment:
        add_issue_comment(match.iid, comment)

    return close_issue(match.iid)


def sync_issue(
    search_title: str,
    *,
    title: str | None = None,
    description: str = "",
    labels: list[str] | None = None,
    comment: str | None = None,
    set_status: str | None = None,
    reopen_closed: bool = False,
) -> Issue:
    """Find an issue by title and update it while preserving existing non-status labels."""
    existing = list_issues(search=search_title, state="all", per_page=100)
    match = None
    closed_match = None
    for issue in existing:
        if search_title.lower() in issue.title.lower():
            if issue.state == "opened" and match is None:
                match = issue
            elif issue.state == "closed" and closed_match is None:
                closed_match = issue

    target = match
    state_event = None
    if target is None and reopen_closed and closed_match is not None:
        target = closed_match
        state_event = "reopen"

    if target is not None:
        merged_labels = set(target.labels)
        if labels:
            merged_labels.update(labels)
        if set_status:
            merged_labels = {label for label in merged_labels if not label.startswith("status::")}
            merged_labels.add(set_status)

        update_kwargs: dict[str, Any] = {}
        if title is not None:
            update_kwargs["title"] = title
        if description:
            update_kwargs["description"] = description
        if labels or set_status:
            update_kwargs["labels"] = sorted(merged_labels)
        if state_event is not None:
            update_kwargs["state_event"] = state_event

        updated = update_issue(target.iid, **update_kwargs) if update_kwargs else target
        if comment:
            add_issue_comment(updated.iid, comment)
        return get_issue(updated.iid)

    create_labels = set(labels or [])
    if set_status:
        create_labels = {label for label in create_labels if not label.startswith("status::")}
        create_labels.add(set_status)

    created = create_issue(
        title or search_title,
        description=description,
        labels=sorted(create_labels) or None,
    )
    if comment:
        add_issue_comment(created.iid, comment)
    return created


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


# ── Board helpers ────────────────────────────────────────────────────────────


def list_boards() -> list[dict]:
    """List all issue boards for the project."""
    pid = _project_id()
    return _api("GET", f"/projects/{pid}/boards")


def ensure_board(name: str = "Development") -> dict:
    """Create an issue board if it doesn't exist."""
    for board in list_boards():
        board_name = board.get("name") or board.get("title") or ""
        if board_name.lower() == name.lower():
            return board

    pid = _project_id()
    return _api("POST", f"/projects/{pid}/boards", data={"name": name})


def list_board_lists(board_id: int) -> list[dict]:
    """List all label lists on a board."""
    pid = _project_id()
    return _api("GET", f"/projects/{pid}/boards/{board_id}/lists")


def ensure_board_list(board_id: int, label_name: str) -> dict:
    """Create a label-backed board list if it doesn't already exist."""
    existing_lists = list_board_lists(board_id)
    for board_list in existing_lists:
        label = board_list.get("label") or {}
        if label.get("name", "").lower() == label_name.lower():
            return board_list

    label_map = {lab["name"]: lab for lab in list_labels()}
    label = label_map.get(label_name)
    if label is None:
        raise RuntimeError(f"Label not found for board list: {label_name}")

    pid = _project_id()
    return _api(
        "POST",
        f"/projects/{pid}/boards/{board_id}/lists",
        data={"label_id": label["id"]},
    )


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


# ── Redis event helpers (optional; silently no-ops when redis unavailable) ────


def publish_event(channel: str, payload: dict) -> bool:
    """Publish a JSON event to Redis pub/sub channel.

    Returns True on success, False if Redis is unavailable.
    Treat as best-effort telemetry; callers should not depend on delivery.
    """
    try:
        import redis as _redis_lib
        _url = os.environ.get("REDIS_URL", "redis://shml-redis:6379/0")
        _r = _redis_lib.from_url(_url, socket_connect_timeout=2, socket_timeout=2)
        _r.publish(channel, json.dumps(payload, default=str))
        return True
    except Exception:
        return False


# ── Project webhook management ────────────────────────────────────────────────


def register_project_webhook(
    hook_url: str,
    *,
    issues_events: bool = True,
    merge_requests_events: bool = False,
    push_events: bool = False,
    pipeline_events: bool = True,
    token: str | None = None,
) -> dict:
    """Register (or update) a project-level outbound webhook in GitLab.

    GitLab will POST to ``hook_url`` when the specified events occur.
    Idempotent: if a hook for this URL already exists it will be updated.
    Returns the created/updated hook dict.
    """
    pid = _project_id()
    body: dict[str, Any] = {
        "url": hook_url,
        "issues_events": issues_events,
        "merge_requests_events": merge_requests_events,
        "push_events": push_events,
        "pipeline_events": pipeline_events,
        "enable_ssl_verification": False,
    }
    if token:
        body["token"] = token
    existing = _api("GET", f"/projects/{pid}/hooks", params={"per_page": "50"})
    for h in existing:
        if h.get("url") == hook_url:
            hook_id = h["id"]
            return _api("PUT", f"/projects/{pid}/hooks/{hook_id}", data=body)
    return _api("POST", f"/projects/{pid}/hooks", data=body)


# ── CLI interface ────────────────────────────────────────────────────────────


def _render_issue_description(
    *,
    template: str,
    summary: str,
    outcome: str,
    scope: str,
    acceptance: list[str],
    dependencies: str,
    observability: str,
    risks: str,
    rollback: str,
    extra_description: str,
) -> str:
    """Render a structured issue body for GitLab CE without premium custom fields."""
    header_map = {
        "bug": "## Problem",
        "task": "## Task",
        "improvement": "## Improvement",
    }
    lines = [header_map.get(template, "## Summary")]
    lines.append(summary or "TBD")

    if outcome:
        lines.extend(["", "## Outcome", outcome])
    if scope:
        lines.extend(["", "## Scope", scope])
    if acceptance:
        lines.append("")
        lines.append("## Acceptance Criteria")
        for item in acceptance:
            lines.append(f"- [ ] {item}")
    if dependencies:
        lines.extend(["", "## Dependencies", dependencies])
    if observability:
        lines.extend(["", "## Observability", observability])
    if risks:
        lines.extend(["", "## Risks", risks])
    if rollback:
        lines.extend(["", "## Rollback", rollback])
    if extra_description:
        lines.extend(["", "## Notes", extra_description])

    return "\n".join(lines).strip()


def _cli_create_issue(args: list[str]) -> int:
    """CLI: create-issue <title> [--labels l1,l2] [--description text]"""
    import argparse

    parser = argparse.ArgumentParser(prog="gitlab_utils create-issue")
    parser.add_argument("title", help="Issue title")
    parser.add_argument("--labels", default="", help="Comma-separated labels")
    parser.add_argument("--description", default="", help="Issue body (markdown)")
    parser.add_argument("--confidential", action="store_true")
    parser.add_argument("--milestone-title", default=None)
    parser.add_argument("--template", choices=["bug", "task", "improvement"], default=None)
    parser.add_argument("--summary", default="")
    parser.add_argument("--outcome", default="")
    parser.add_argument("--scope", default="")
    parser.add_argument("--acceptance", action="append", default=[])
    parser.add_argument("--dependencies", default="")
    parser.add_argument("--observability", default="")
    parser.add_argument("--risks", default="")
    parser.add_argument("--rollback", default="")
    parsed = parser.parse_args(args)

    labels = [l.strip() for l in parsed.labels.split(",") if l.strip()] or None
    milestone_id = None
    if parsed.milestone_title:
        milestone_id = ensure_milestone(parsed.milestone_title)["id"]

    description = parsed.description
    if parsed.template:
        description = _render_issue_description(
            template=parsed.template,
            summary=parsed.summary,
            outcome=parsed.outcome,
            scope=parsed.scope,
            acceptance=parsed.acceptance,
            dependencies=parsed.dependencies,
            observability=parsed.observability,
            risks=parsed.risks,
            rollback=parsed.rollback,
            extra_description=parsed.description,
        )

    issue = create_issue(
        parsed.title,
        description=description,
        labels=labels,
        confidential=parsed.confidential,
        milestone_id=milestone_id,
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
    parser.add_argument("--reopen", action="store_true", help="Reopen a matching closed issue instead of creating a new one")
    parsed = parser.parse_args(args)

    labels = [l.strip() for l in parsed.labels.split(",") if l.strip()] or None
    issue = upsert_issue(
        parsed.search_title,
        title=parsed.title,
        description=parsed.description,
        labels=labels,
        comment=parsed.comment,
        close_if_resolved=parsed.close,
        reopen_closed=parsed.reopen,
    )
    print(json.dumps({"iid": issue.iid, "title": issue.title, "state": issue.state, "url": issue.web_url}))
    return 0


def _cli_resolve_issue(args: list[str]) -> int:
    """CLI: resolve-issue <search_title> [--comment text] [--labels l1,l2]"""
    import argparse

    parser = argparse.ArgumentParser(prog="gitlab_utils resolve-issue")
    parser.add_argument("search_title", help="Title substring of the incident to close")
    parser.add_argument("--comment", default=None, help="Resolution comment to add")
    parser.add_argument("--labels", default="", help="Extra labels to add (comma-separated)")
    parsed = parser.parse_args(args)

    extra_labels = [l.strip() for l in parsed.labels.split(",") if l.strip()] or None
    issue = resolve_issue(parsed.search_title, comment=parsed.comment, extra_labels=extra_labels)
    if issue is None:
        print(json.dumps({"resolved": False, "reason": "no open issue found"}))
    else:
        print(json.dumps({"resolved": True, "iid": issue.iid, "title": issue.title, "url": issue.web_url}))
    return 0


def _cli_sync_issue(args: list[str]) -> int:
    """CLI: sync-issue <search_title> [--comment text] [--status s] [--labels l1,l2]"""
    import argparse

    parser = argparse.ArgumentParser(prog="gitlab_utils sync-issue")
    parser.add_argument("search_title", help="Title substring to search")
    parser.add_argument("--title", default=None, help="Full title for new issue or rename")
    parser.add_argument("--labels", default="", help="Comma-separated labels to add/preserve")
    parser.add_argument("--description", default="", help="Issue body for new issue or description refresh")
    parser.add_argument("--comment", default=None, help="Comment to append")
    parser.add_argument("--status", default=None, help="Set status label without clobbering other labels")
    parser.add_argument("--reopen", action="store_true", help="Reopen a matching closed issue instead of creating a new one")
    parsed = parser.parse_args(args)

    labels = [l.strip() for l in parsed.labels.split(",") if l.strip()] or None
    issue = sync_issue(
        parsed.search_title,
        title=parsed.title,
        description=parsed.description,
        labels=labels,
        comment=parsed.comment,
        set_status=parsed.status,
        reopen_closed=parsed.reopen,
    )
    print(json.dumps({"iid": issue.iid, "title": issue.title, "state": issue.state, "labels": issue.labels, "url": issue.web_url}))
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


def _cli_update_issue(args: list[str]) -> int:
    """CLI: update-issue <iid> [--add-label x] [--remove-label y] [--set-status s]."""
    import argparse

    parser = argparse.ArgumentParser(prog="gitlab_utils update-issue")
    parser.add_argument("iid", type=int, help="Issue IID")
    parser.add_argument("--title", default=None)
    parser.add_argument("--description", default=None)
    parser.add_argument("--add-label", action="append", default=[])
    parser.add_argument("--remove-label", action="append", default=[])
    parser.add_argument("--set-status", default=None)
    parser.add_argument("--state", choices=["close", "reopen"], default=None)
    parser.add_argument("--milestone-title", default=None)
    parsed = parser.parse_args(args)

    issue = get_issue(parsed.iid)
    labels = set(issue.labels)

    for label in parsed.add_label:
        if label:
            labels.add(label)

    for label in parsed.remove_label:
        if label:
            labels.discard(label)

    if parsed.set_status:
        labels = {label for label in labels if not label.startswith("status::")}
        labels.add(parsed.set_status)

    milestone_id = None
    if parsed.milestone_title:
        milestone_id = ensure_milestone(parsed.milestone_title)["id"]

    updated = update_issue(
        parsed.iid,
        title=parsed.title,
        description=parsed.description,
        labels=sorted(labels),
        state_event=parsed.state,
        milestone_id=milestone_id,
    )
    print(
        json.dumps(
            {
                "iid": updated.iid,
                "title": updated.title,
                "state": updated.state,
                "labels": updated.labels,
                "url": updated.web_url,
            }
        )
    )
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
        ("status::todo", "#5E6AD2", "Committed for the current planning horizon"),
        ("status::in-review", "#9C27B0", "Implemented and under review or validation"),
        ("status::done", "#2EAD4B", "Done in working state, awaiting closure"),
        ("status::icebox", "#5F6368", "Explicitly deferred until later"),
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
        ("source::pipeline", "#1E90FF", "Auto-created by training pipeline automation"),
        # Status workflow labels (JIRA-style board columns)
        ("status::backlog", "#808080", "Prioritised but not yet ready to start"),
        ("status::ready", "#00C853", "Ready to start, no blockers"),
        ("status::in-progress", "#1F75FE", "Actively being worked on"),
        # Robotics component labels
        ("component::mujoco", "#FF8C00", "MuJoCo headless RL simulation"),
        ("component::isaac-sim", "#76B900", "NVIDIA Isaac Sim / photorealistic"),
        ("component::ros2", "#22314E", "ROS2 Jazzy / Humble"),
        ("component::urdf", "#8B008B", "Robot description / URDF / MJCF / USD"),
        ("component::rl-training", "#DC143C", "Reinforcement learning training"),
        ("component::world-model", "#4169E1", "Dreamer V3 / world model training"),
        ("source::robotics-sim", "#FF8C00", "Auto-created by robotics sim crash/failure"),
        # PII / ML-specific
        ("metric::recall-primary", "#FF6347", "Recall is the primary success metric (PII)"),
        ("component::pii-blurring", "#C71585", "PII face blurring pipeline"),
        ("component::face-detection", "#FF4500", "Face detection model training / eval"),
        ("type::research", "#A8D695", "Research spike or investigation"),
    ]

    for name, color, desc in label_defs:
        lab = ensure_label(name, color=color, description=desc)
        print(f"  ✓ Label: {lab['name']}")

    # ── Milestones ───────────────────────────────────────────────────────
    milestone_defs = [
        ("v1.0 — Platform Stability", "Core services healthy, CI green, watchdog operational"),
        ("v1.1 — GitLab Integration", "Full GitLab-centric workflow: issues, CI, mirror"),
        ("v2.0 — Training Pipeline", "Autoresearch, model evaluation, MLflow tracking"),
        ("PII SOTA — recall > 0.760", "Beat Phase 9 recall (0.729) → 0.760+ on WIDER Face; mAP50 ≥ 0.798 floor"),
        ("Platform Brain v1", "Redis pub/sub + GitLab webhooks + cross-service event routing live"),
        ("Production Deploy", "PII blurring model in prod inference pipeline, end-to-end validated"),
        # Robotics milestones
        ("Phase 0 — Platform Audit", "All services healthy, watchdog 100% coverage, GitLab board live, NemoClaw tested"),
        ("Sim Foundation", "colcon builds, URDF valid, MuJoCo envs working, platform connected"),
        ("RL Training", "PPO/SAC training, MLflow logging, Grafana dashboards, FiftyOne pipeline"),
        ("Isaac Sim", "Photorealistic backend, FiftyOne domain gap, DCGM monitoring"),
        ("AutoResearch — Robotics", "3 LLM-driven mutation loops: RL, curriculum, world model"),
        ("Hardware Deploy", "ROSMASTER M3 PRO: policy deployed, Zenoh DDS, on-robot ROS2 Humble"),
    ]

    for title, desc in milestone_defs:
        ms = ensure_milestone(title, description=desc)
        print(f"  ✓ Milestone: {ms['title']}")

    board = ensure_board("Development")
    board_name = board.get("name") or board.get("title") or "Development"
    print(f"  ✓ Board: {board_name}")

    workflow_lists = [
        "status::backlog",
        "status::todo",
        "status::ready",
        "status::in-progress",
        "status::in-review",
        "status::blocked",
        "status::icebox",
        "status::done",
    ]
    for label_name in workflow_lists:
        ensure_board_list(board["id"], label_name)
        print(f"  ✓ Board list: {label_name}")

    print("Board setup complete.")
    return 0


def _cli_seed_phase0_issues(args: list[str]) -> int:
    """CLI: seed-phase0-issues — Create GitLab issues for all Phase 0 tasks.

    Idempotent: uses upsert_issue so re-running won't create duplicates.
    """
    # Find milestone IDs
    ms_list = list_milestones()
    ms_map = {m["title"]: m["id"] for m in ms_list}
    phase0_ms_id = ms_map.get("Phase 0 — Platform Audit")

    if not phase0_ms_id:
        print("  ⚠ Milestone 'Phase 0 — Platform Audit' not found — run setup-board first")
        phase0_ms_id = None

    phase0_issues = [
        {
            "title": "Phase 0.1: GitLab project & JIRA-style board setup",
            "labels": ["type::chore", "component::ci-cd", "priority::critical", "status::backlog"],
            "description": (
                "## Goal\nSet up GitLab Issues as single source of truth for all task tracking.\n\n"
                "### Checklist\n"
                "- [ ] Run `python3 scripts/platform/gitlab_utils.py setup-board` to create all labels/milestones\n"
                "- [ ] Run `python3 scripts/platform/gitlab_utils.py seed-phase0-issues` to create all Phase 0 issues\n"
                "- [ ] Verify Labels Board at `/-/boards` shows workflow lists for backlog/todo/ready/in-progress/in-review/blocked/icebox/done\n"
                "- [ ] All Phase 0-5 tasks exist as issues with correct labels + milestones\n\n"
                "**Blocks:** All other Phase 0 tasks\n"
                "**Gate:** GitLab board shows correct JIRA-style columns"
            ),
        },
        {
            "title": "Phase 0.2: Migrate Obsidian kanban → GitLab Issues",
            "labels": ["type::chore", "component::ci-cd", "priority::high", "status::backlog"],
            "description": (
                "## Goal\nComplete the GitLab Issues migration and remove any remaining runtime "
                "dependency on legacy markdown task tracking. All active state tracking must flow "
                "through the GitLab Issues API.\n\n"
                "### Checklist\n"
                "- [ ] Ensure `scripts/data/update_gitlab_board.sh` is the only active board sync entrypoint\n"
                "- [ ] Ensure `scripts/platform/gitlab_board_updater.py` is the reconciliation layer for GitLab transitions\n"
                "- [ ] Update `scripts/platform/scan_repo_state.sh` to reconcile GitLab state only\n"
                "- [ ] Ensure only `shl-gitlab-sync.*` systemd units remain active\n"
                "- [ ] Keep any legacy markdown board material archived or historical only\n"
                "- [ ] Verify 30min scan produces correct GitLab issue transitions\n\n"
                "**Depends on:** Phase 0.1"
            ),
        },
        {
            "title": "Phase 0.3: Full service health audit (all 23+ containers)",
            "labels": ["type::chore", "component::infra", "priority::critical", "status::backlog"],
            "description": (
                "## Goal\nVerify every container is healthy, every Traefik route resolves, "
                "every auth chain works.\n\n"
                "### Checklist\n"
                "- [ ] Run `scripts/platform/platform_audit.sh` → produces `data/platform-audit/audit-YYYY-MM-DD.json`\n"
                "- [ ] Every container in `docker ps` shows healthy/running\n"
                "- [ ] Every Traefik route resolves to correct backend\n"
                "- [ ] Full OAuth2 login flow works for all 4 roles\n"
                "- [ ] Database connectivity verified (all PostgreSQL instances)\n"
                "- [ ] Monitoring stack: all Prometheus scrape targets UP, Grafana loading, "
                "Alertmanager → Telegram functional\n"
                "- [ ] `data/platform-audit/audit-YYYY-MM-DD.json` shows 0 failures\n\n"
                "**Depends on:** Phase 0.1"
            ),
        },
        {
            "title": "Phase 0.4: Service location & Traefik label reconciliation",
            "labels": ["type::chore", "component::infra", "priority::high", "status::backlog"],
            "description": (
                "## Goal\nEnsure all compose files, Traefik labels, network memberships, "
                "and volumes are correct after v0.2 refactor.\n\n"
                "### Checklist\n"
                "- [ ] Every labeled service has `traefik.enable=true`, correct rule, priority, middleware chain\n"
                "- [ ] All services on `shml-platform` network; databases also on `shml-core-net`\n"
                "- [ ] No stale/missing environment variable references\n"
                "- [ ] Compose file audit: walk every `deploy/compose/*.yml` and `inference/docker-compose*.yml`\n\n"
                "**Depends on:** Phase 0.3"
            ),
        },
        {
            "title": "Phase 0.5: Watchdog completeness audit (100% container coverage)",
            "labels": ["type::chore", "component::watchdog", "priority::critical", "status::backlog"],
            "description": (
                "## Goal\nEnsure watchdog monitors 100% of running containers.\n\n"
                "### Checklist\n"
                "- [ ] Compare watchdog critical + standard container lists against `docker ps` output\n"
                "- [ ] Every HTTP-accessible service has a watchdog probe URL\n"
                "- [ ] Training protection covers all GPU-using services\n"
                "- [ ] Memory leak monitoring covers all long-running services\n"
                "- [ ] Restart order respects service dependencies\n"
                "- [ ] Every failure mode sends Telegram notification\n"
                "- [ ] GitLab issue templates correct for all failure types\n\n"
                "**Depends on:** Phase 0.3"
            ),
        },
        {
            "title": "Phase 0.6: NemoClaw autonomous remediation enhancements",
            "labels": ["type::feature", "component::watchdog", "component::agent-service", "priority::high", "status::backlog"],
            "description": (
                "## Goal\nExtend watchdog → agent-service → NemoClaw chain for fully autonomous uptime.\n\n"
                "### Changes\n"
                "- Lower cascade threshold 3→2 unhealthy containers\n"
                "- Single-service root cause: LLM diagnosis before 3rd restart attempt\n"
                "- NemoClaw sandbox for repair (elevated-developer role)\n"
                "- Proactive health forecasting (hourly, via scan_repo_state.sh)\n"
                "- Service dependency graph for cascade restarts\n"
                "- Tiered Telegram notifications (immediate/5min/hourly/daily)\n"
                "- Auto-escalation chain: watchdog → agent → NemoClaw → human\n\n"
                "### Files\n"
                "- `scripts/self-healing/watchdog.sh` — cascade threshold, dependency graph\n"
                "- `inference/agent-service/skills/platform-health/SKILL.md` — LLM diagnosis prompts\n"
                "- `scripts/platform/scan_repo_state.sh` — proactive forecasting\n\n"
                "**Depends on:** Phase 0.5"
            ),
        },
        {
            "title": "Phase 0 gate: Verification checklist",
            "labels": ["type::chore", "component::infra", "priority::critical", "status::backlog"],
            "description": (
                "## Phase 0 is complete when ALL pass:\n\n"
                "- [ ] Every container in `docker ps` healthy/running\n"
                "- [ ] Every Traefik route resolves to correct backend\n"
                "- [ ] Full OAuth2 login flow works for all 4 roles\n"
                "- [ ] Watchdog monitors 100% of running containers\n"
                "- [ ] NemoClaw sandbox remediation tested (stop non-critical service → auto-recovery + Telegram)\n"
                "- [ ] GitLab Issues board shows all tasks with correct `status::` labels\n"
                "- [ ] Obsidian markdown generation fully stopped\n"
                "- [ ] `data/platform-audit/audit-YYYY-MM-DD.json` shows 0 failures\n"
                "- [ ] Telegram receives: hourly digest, daily report, immediate alerts for test failures\n"
                "- [ ] CI (GitHub + GitLab) green on main branch\n\n"
                "**Blocks:** Phase 1 (Sim-Only Foundation)"
            ),
        },
    ]

    print(f"Seeding {len(phase0_issues)} Phase 0 issues...")
    ok = 0
    fail = 0
    for item in phase0_issues:
        try:
            kwargs: dict = {"title": item["title"], "description": item.get("description", ""), "labels": item.get("labels", [])}
            if phase0_ms_id:
                kwargs["milestone_id"] = phase0_ms_id
            issue = upsert_issue(item["title"][:50], **kwargs)
            print(f"  ✓ #{issue.iid:4d}  {item['title'][:65]}")
            ok += 1
        except Exception as e:
            print(f"  ✗ FAILED  {item['title'][:60]} — {e}")
            fail += 1

    print(f"\nDone: {ok} created/updated, {fail} failed.")
    return 0 if fail == 0 else 1



# ── Project management helpers ────────────────────────────────────────────────


def update_project(
    *,
    description: str | None = None,
    topics: list[str] | None = None,
    visibility: str | None = None,
    avatar: str | None = None,
) -> dict:
    """Update project-level metadata (description, topics, visibility)."""
    pid = _project_id()
    body: dict[str, Any] = {}
    if description is not None:
        body["description"] = description
    if topics is not None:
        body["topics"] = topics
    if visibility is not None:
        body["visibility"] = visibility
    return _api("PUT", f"/projects/{pid}", data=body)


def get_project() -> dict:
    """Get current project metadata."""
    pid = _project_id()
    return _api("GET", f"/projects/{pid}")


def find_user_by_email(email: str) -> dict | None:
    """Look up a GitLab user by email address. Returns None if not found."""
    results = _api("GET", "/users", params={"search": email})
    for user in results:
        if user.get("email") == email or user.get("public_email") == email:
            return user
    # Try username match as fallback (GitLab CE may hide emails)
    return results[0] if results else None


def add_project_member(user_id: int, access_level: int = 50) -> dict:
    """Add or update a project member.

    access_level: 10=Guest, 20=Reporter, 30=Developer, 40=Maintainer, 50=Owner
    Owner (50) is available in GitLab CE 13.x+ for project members.
    """
    pid = _project_id()
    try:
        return _api(
            "POST",
            f"/projects/{pid}/members",
            data={"user_id": user_id, "access_level": access_level},
        )
    except RuntimeError as exc:
        if "already" in str(exc).lower() or "409" in str(exc):
            # Member exists — update instead
            return _api(
                "PUT",
                f"/projects/{pid}/members/{user_id}",
                data={"access_level": access_level},
            )
        raise


def _cli_update_project(args: list[str]) -> int:
    """CLI: update-project — Set project description, topics, and owner email."""
    import argparse

    parser = argparse.ArgumentParser(prog="gitlab_utils update-project")
    parser.add_argument("--description", default=None, help="Project description")
    parser.add_argument(
        "--topics", default=None, help="Comma-separated topics/tags"
    )
    parser.add_argument(
        "--owner-email",
        default=None,
        help="Email of user to add as Owner-level member",
    )
    parser.add_argument(
        "--visibility",
        choices=["private", "internal", "public"],
        default=None,
    )
    parsed = parser.parse_args(args)

    update_kwargs: dict[str, Any] = {}
    if parsed.description is not None:
        update_kwargs["description"] = parsed.description
    if parsed.topics is not None:
        update_kwargs["topics"] = [t.strip() for t in parsed.topics.split(",") if t.strip()]
    if parsed.visibility is not None:
        update_kwargs["visibility"] = parsed.visibility

    if update_kwargs:
        proj = update_project(**update_kwargs)
        print(f"  ✓ Project updated: {proj.get('name_with_namespace')} — {proj.get('web_url')}")
        if parsed.description:
            print(f"    description: {proj.get('description', '')[:80]}")

    if parsed.owner_email:
        user = find_user_by_email(parsed.owner_email)
        if user is None:
            print(
                f"  ✗ User not found for email: {parsed.owner_email}\n"
                "    Ensure the account exists in GitLab before granting access.",
                file=sys.stderr,
            )
            return 1
        member = add_project_member(user["id"], access_level=50)
        print(
            f"  ✓ Member added: {user.get('username')} ({parsed.owner_email}) "
            f"→ access_level={member.get('access_level')}"
        )

    return 0


def _cli_setup_webhook(args: list[str]) -> int:
    """CLI: setup-webhook — Register GitLab outbound webhook to webhook-deployer."""
    import argparse
    parser = argparse.ArgumentParser(prog="gitlab_utils setup-webhook")
    parser.add_argument(
        "--hook-url",
        default="https://${PUBLIC_DOMAIN}/webhook/gitlab-events",
        help="Target webhook URL (default: local webhook-deployer)",
    )
    parser.add_argument("--token", default=None, help="Optional secret token")
    parsed = parser.parse_args(args)
    hook = register_project_webhook(
        parsed.hook_url,
        issues_events=True,
        pipeline_events=True,
        token=parsed.token,
    )
    print(f"  ✓ Webhook registered: {hook.get('url')} (id={hook.get('id')})")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: python3 gitlab_utils.py <command> [args...]\n\n"
            "Commands:\n"
            "  create-issue      Create a new issue\n"
            "  upsert-issue      Find or create an issue (idempotent)\n"
            "  sync-issue        Update issue by title while preserving existing labels\n"
            "  resolve-issue     Mark an open incident as status::done and close it\n"
            "  add-comment       Add a comment to an issue\n"
            "  update-issue      Update labels/state/milestone on an issue\n"
            "  list-issues       List open issues\n"
            "  setup-board       Create labels and milestones (incl. robotics)\n"
            "  seed-phase0-issues  Create all Phase 0 tracking issues\n"
            "  setup-webhook     Register GitLab outbound webhook\n"
            "  update-project    Set project description, topics, owner email\n",
            file=sys.stderr,
        )
        return 1

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    dispatch = {
        "create-issue": _cli_create_issue,
        "upsert-issue": _cli_upsert_issue,
        "sync-issue": _cli_sync_issue,
        "resolve-issue": _cli_resolve_issue,
        "add-comment": _cli_add_comment,
        "update-issue": _cli_update_issue,
        "list-issues": _cli_list_issues,
        "setup-board": _cli_setup_board,
        "seed-phase0-issues": _cli_seed_phase0_issues,
        "setup-webhook": _cli_setup_webhook,
        "update-project": _cli_update_project,
    }

    handler = dispatch.get(cmd)
    if handler is None:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 1

    return handler(rest)


if __name__ == "__main__":
    sys.exit(main())
