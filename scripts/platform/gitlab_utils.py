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

try:
    from service_discovery import resolve_gitlab_base_url
except ModuleNotFoundError:  # pragma: no cover - script execution fallback
    sys.path.insert(0, os.path.dirname(__file__))
    from service_discovery import resolve_gitlab_base_url

# ── Configuration ────────────────────────────────────────────────────────────

_DEFAULT_BASE_URL = "http://shml-gitlab:8929/gitlab"
_DEFAULT_PROJECT_ID = "2"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _base_url() -> str:
    return resolve_gitlab_base_url().rstrip("/")


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
        # Status workflow labels
        ("status::in-progress", "#1F75FE", "Actively being worked on"),
        ("status::ready", "#00C853", "Ready to start, no blockers"),
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
        ("v2.0 — Training Pipeline", "Autoresearch, model evaluation, MLflow tracking"),        ("PII SOTA — recall > 0.760", "Beat Phase 9 recall (0.729) → 0.760+ on WIDER Face; mAP50 ≥ 0.798 floor"),
        ("Platform Brain v1", "Redis pub/sub + GitLab webhooks + cross-service event routing live"),
        ("Production Deploy", "PII blurring model in prod inference pipeline, end-to-end validated"),    ]

    for title, desc in milestone_defs:
        ms = ensure_milestone(title, description=desc)
        print(f"  ✓ Milestone: {ms['title']}")

    print("Board setup complete.")
    return 0


def _cli_setup_webhook(args: list[str]) -> int:
    """CLI: setup-webhook — Register GitLab outbound webhook to webhook-deployer."""
    import argparse
    parser = argparse.ArgumentParser(prog="gitlab_utils setup-webhook")
    parser.add_argument(
        "--hook-url",
        default="https://shml-platform.tail38b60a.ts.net/webhook/gitlab-events",
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


def _cli_migrate_kanban(args: list[str]) -> int:
    """CLI: migrate-kanban — Create GitLab issues from KANBAN.md snapshot.

    Idempotent: uses upsert_issue so re-running won’t create duplicates.
    """
    kanban_items = [
        # ── In Progress ─────────────────────────────────────────────────────
        {
            "title": "Autoresearch Round 3 — PII Face Detection (recall > 0.760)",
            "labels": ["type::training", "component::autoresearch", "component::pii-blurring",
                       "priority::critical", "status::in-progress", "metric::recall-primary",
                       "source::autoresearch"],
            "description": (
                "## Goal\nBeat Phase 9 recall (0.729) → **recall > 0.760** on WIDER Face val.\n\n"
                "**Primary metric:** recall (PII: a missed face = privacy violation)\n"
                "**Floor:** mAP50 ≥ 0.798 (Phase 5 baseline)\n"
                "**Hardware:** RTX 3090 Ti 24GB\n"
                "**Strategy:** multi-scale imgsz=960 ±33%, batch=2, 30 epochs, "
                "Phase 9 loss weights locked\n\n"
                "*Migrated from KANBAN.md*"
            ),
        },
        {
            "title": "Track 8: nanochat — T8.1 pipeline (Stage 1 data export)",
            "labels": ["type::training", "component::agent-service", "priority::high",
                       "status::in-progress"],
            "description": "T8.1 pipeline running — Stage 1 data export for nanochat SFT.\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "Memory Watchdog — psutil memory leak guard",
            "labels": ["type::chore", "component::watchdog", "priority::medium",
                       "status::in-progress"],
            "description": "psutil-based memory leak guard for VSCode + training processes.\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T3.3 GEPA live cycle — first skill evolution cycle",
            "labels": ["type::feature", "component::agent-service", "priority::medium",
                       "status::in-progress"],
            "description": "First real GEPA cycle.\nTrigger: `curl -X POST http://localhost:8000/api/skills/evolve -d '{\"skill\":\"coding-assistant\"}'`\n\n*Migrated from KANBAN.md*",
        },
        # ── Backlog ────────────────────────────────────────────────────────
        {
            "title": "CLOUD_API_KEY — activate cloud failover tier",
            "labels": ["type::chore", "component::infra", "priority::high", "status::ready"],
            "description": "T5.1 hybrid router is built; just needs CLOUD_API_KEY env var set.\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T6.1 Nemotron-3-Super-120B — eval as cloud fallback",
            "labels": ["type::research", "component::agent-service", "priority::medium"],
            "description": "Eval Nemotron-3-Super-120B as cloud fallback; 12B active / 120B MoE.\nRef: https://research.nvidia.com/labs/nemotron/Nemotron-3-Super/\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T6.2 Moondream edge vision — benchmark vs YOLO on WIDER Hard",
            "labels": ["type::research", "component::face-detection", "priority::medium"],
            "description": "Benchmark moondream vs YOLO on WIDER Hard subset; VQA PII queries.\nRef: https://github.com/vikhyat/moondream\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T6.4 Base44 superagents — multi-agent orchestration review",
            "labels": ["type::research", "component::agent-service", "priority::low"],
            "description": "Review multi-agent orchestration vs ACE loop.\nRef: https://base44.com/superagents\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T7.6 Telegram activation — alertmanager-telegram token setup",
            "labels": ["type::chore", "component::infra", "priority::medium"],
            "description": "BotFather → TELEGRAM_BOT_TOKEN + CHAT_ID → activate alertmanager-telegram.\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T7.7 skill_updater path sync — SKILLS_DIR in compose",
            "labels": ["type::bug", "component::agent-service", "priority::medium"],
            "description": "SKILLS_DIR=/workspace/inference/agent-service/skills in compose.\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T7.8 MLflow artifact hardening",
            "labels": ["type::chore", "component::infra", "priority::low"],
            "description": "Add `user: '1000:1000'` + startup write-check to mlflow service.\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T8.6 Shadow A/B — 10% traffic nano vs Qwen3",
            "labels": ["type::feature", "component::agent-service", "priority::medium"],
            "description": "Route 10% of inference requests to nano model vs Qwen3.\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T8.8 Weekly Retrain — auto SFT on new conversations",
            "labels": ["type::chore", "component::agent-service", "priority::low"],
            "description": "Auto-retrain SFT on new conversations (cron, post T8.4).\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T8.9 Unsloth packing — 3× SFT speedup for nanochat",
            "labels": ["type::feature", "component::agent-service", "priority::medium"],
            "description": "Apply Unsloth 3× packing to nanochat SFT data pipeline.\nRef: https://docs.unsloth.ai/new/3x-faster-training-packing\n\n*From links.md 2025-12-13*",
        },
        # ── Blocked ────────────────────────────────────────────────────────
        {
            "title": "FiftyOne deep eval — blocked on autoresearch Round 3 winner",
            "labels": ["type::training", "component::face-detection", "priority::high",
                       "status::blocked", "metric::recall-primary"],
            "description": "Run FiftyOne Brain failure analysis once recall > 0.760 achieved.\nBlocked by: Autoresearch Round 3\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T7.4 Phase 6B: YOLOv8l P2 — blocked on autoresearch champion",
            "labels": ["type::training", "component::face-detection", "priority::high",
                       "status::blocked"],
            "description": "Start YOLOv8l P2 Phase 6B full training once Round 3 produces a champion config.\nBlocked by: Autoresearch Round 3\n\n*Migrated from KANBAN.md*",
        },
        {
            "title": "T7.5 RF-DETR vs YOLO comparison — blocked on T7.4",
            "labels": ["type::training", "component::face-detection", "priority::medium",
                       "status::blocked"],
            "description": "Compare RF-DETR curriculum pipeline vs YOLOv8l P2 once T7.4 completes.\nRef: https://github.com/roboflow/rf-detr\nBlocked by: T7.4\n\n*Migrated from KANBAN.md*",
        },
        # ── New — from links.md analysis ─────────────────────────────────
        {
            "title": "Evaluate autoresearch-at-home loop improvements",
            "labels": ["type::research", "component::autoresearch", "priority::low"],
            "description": "Evaluate mutable-state-inc/autoresearch-at-home for loop design improvements (LLM mutation quality).\nRef: https://github.com/mutable-state-inc/autoresearch-at-home\n\n*From links.md 2026-03-12*",
        },
        {
            "title": "Evaluate computer-use-large for GUI agent fine-tuning",
            "labels": ["type::research", "component::agent-service", "priority::low"],
            "description": "48k videos / 12.3k hrs of professional screen recordings (AutoCAD, Excel, VS Code etc). Evaluate as training data for a computer-use agent.\nRef: https://huggingface.co/datasets/markov-ai/computer-use-large\n\n*From links.md 2026-03-12*",
        },
        {
            "title": "Synthetic hard-negative face mining via NeMo DataDesigner",
            "labels": ["type::feature", "component::face-detection", "priority::medium",
                       "metric::recall-primary"],
            "description": "Use NVIDIA NeMo DataDesigner to generate synthetic hard-negative faces (small/occluded in crowds) to augment WIDER Face training set.\nPlan for Round 4 after Round 3 completes.\nRef: https://github.com/NVIDIA-NeMo/DataDesigner\n\n*From links.md analysis*",
        },
    ]

    print(f"Migrating {len(kanban_items)} kanban items to GitLab issues...")
    ok = 0
    fail = 0
    for item in kanban_items:
        try:
            issue = upsert_issue(
                item["title"][:50],  # search key
                title=item["title"],
                description=item.get("description", ""),
                labels=item.get("labels", []),
            )
            print(f"  ✓ #{issue.iid:4d}  {item['title'][:65]}")
            ok += 1
        except Exception as e:
            print(f"  ✗ FAILED  {item['title'][:65]} — {e}")
            fail += 1

    print(f"\nDone: {ok} created/updated, {fail} failed.")
    return 0 if fail == 0 else 1


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: python3 gitlab_utils.py <command> [args...]\n\n"
            "Commands:\n"
            "  create-issue    Create a new issue\n"
            "  upsert-issue    Find or create an issue (idempotent)\n"
            "  add-comment     Add a comment to an issue\n"
            "  list-issues     List open issues\n"
            "  setup-board     Create labels and milestones\n"
            "  setup-webhook   Register GitLab outbound webhook\n"
            "  migrate-kanban  Migrate KANBAN.md items to GitLab issues\n",
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
        "setup-webhook": _cli_setup_webhook,
        "migrate-kanban": _cli_migrate_kanban,
    }

    handler = dispatch.get(cmd)
    if handler is None:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 1

    return handler(rest)


if __name__ == "__main__":
    sys.exit(main())
