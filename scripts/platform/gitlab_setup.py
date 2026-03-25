#!/usr/bin/env python3
"""
gitlab_setup.py — Idempotent GitLab board configuration for SHML Platform.

Applies Linear.app/next best practices to the self-hosted GitLab CE instance:
  - Linear-inspired status labels with color coding
  - Priority, type, component, source, and assignee label groups
  - Sprint-based milestones (2-week cycles)
  - Issue board with Backlog → In Progress → In Review → Done columns

Run from the repo root:
    python3 scripts/platform/gitlab_setup.py

Safe to run multiple times — creates only what is missing.
"""
from __future__ import annotations

import sys
import os
from datetime import date, timedelta
from pathlib import Path

# Allow local import of gitlab_utils
sys.path.insert(0, str(Path(__file__).parent))

from gitlab_utils import (
    _api,
    _project_id,
    _base_url,
    _token,
    list_issues,
    add_issue_comment,
)


# ── Label definitions (Linear-inspired) ──────────────────────────────────────
# Format: (name, hex_color, description)

LABELS: list[tuple[str, str, str]] = [
    # ── Status workflow (maps to Linear's cycle states) ──
    ("status::triage",      "#8B572A", "New issue, needs categorisation before entering backlog"),
    ("status::backlog",     "#6B6B6B", "Accepted, ready to be picked up in a sprint"),
    ("status::in-progress", "#0052CC", "Actively being worked on"),
    ("status::in-review",   "#7B61FF", "Work done, under review / waiting for verification"),
    ("status::done",        "#36B37E", "Completed successfully"),
    ("status::blocked",     "#FF5630", "Progress blocked by external dependency"),
    ("status::cancelled",   "#97A0AF", "Will not be implemented"),

    # ── Priority (Linear's urgency levels) ──
    ("priority::critical",  "#FF5630", "System down / data loss — fix immediately"),
    ("priority::high",      "#FF8B00", "Significant impact, should be in current sprint"),
    ("priority::medium",    "#0065FF", "Normal priority, plan for next sprint"),
    ("priority::low",       "#36B37E", "Nice to have, no specific timeline"),

    # ── Issue type ──
    ("type::bug",           "#FF5630", "Regression or incorrect behaviour"),
    ("type::feature",       "#0052CC", "New capability or enhancement"),
    ("type::chore",         "#36B37E", "Infrastructure, CI, documentation, maintenance"),
    ("type::training",      "#6554C0", "ML training run or experiment"),
    ("type::security",      "#FF5630", "Security concern or audit finding"),

    # ── Component ──
    ("component::infra",        "#42526E", "Docker, Traefik, networking, GPU"),
    ("component::ci-cd",        "#42526E", "GitHub Actions, GitLab CI, scripts"),
    ("component::agent-service","#42526E", "Agent service, skills, MCP tools"),
    ("component::chat-ui",      "#42526E", "Chat UI frontend (chat-ui-v2)"),
    ("component::autoresearch",  "#42526E", "Autoresearch training pipeline"),
    ("component::fusionauth",    "#42526E", "FusionAuth / auth layer"),
    ("component::inference",     "#42526E", "LLM / image gen inference services"),
    ("component::mlflow",        "#42526E", "MLflow tracking and experiment management"),
    ("component::ray",           "#42526E", "Ray compute stack"),

    # ── Source (automated issue creation) ──
    ("source::watchdog",     "#C1C7D0", "Auto-created by platform watchdog"),
    ("source::scan",         "#C1C7D0", "Auto-created by scan_repo_state"),
    ("source::autoresearch", "#C1C7D0", "Auto-created by autoresearch"),
    ("source::ci",           "#C1C7D0", "Auto-created by CI pipeline"),
    ("source::pipeline",     "#C1C7D0", "Auto-created by T8 training pipeline"),

    # ── Assignee (for autonomous agent work) ──
    ("assignee::agent",     "#7B61FF", "Claimed by Qwen3.5 / Nemotron autonomous agent"),
]


# ── Board layout ──────────────────────────────────────────────────────────────
# GitLab board lists each reference a label; issues appear in the column
# that matches their current status:: label.

BOARD_COLUMNS = [
    "status::triage",
    "status::backlog",
    "status::in-progress",
    "status::in-review",
    # status::done issues are auto-closed; GitLab shows a built-in Closed column
]


# ── Milestones — 2-week sprints ───────────────────────────────────────────────

def _sprint_milestones(n: int = 4) -> list[tuple[str, str, str]]:
    """Generate n upcoming 2-week sprint milestones from today."""
    today = date.today()
    # Start at the next Monday
    days_until_monday = (7 - today.weekday()) % 7 or 7
    sprint_start = today + timedelta(days=days_until_monday)

    milestones = []
    for i in range(n):
        start = sprint_start + timedelta(weeks=2 * i)
        end = start + timedelta(days=13)
        title = f"Sprint {start.strftime('%Y-%m-%d')}"
        desc = f"2-week sprint: {start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
        milestones.append((title, desc, end.strftime("%Y-%m-%d")))
    return milestones


# ── Helpers ───────────────────────────────────────────────────────────────────

def _existing_labels() -> set[str]:
    pid = _project_id()
    raw = _api("GET", f"/projects/{pid}/labels", params={"per_page": "200"})
    return {d["name"] for d in raw}


def _existing_milestones() -> set[str]:
    pid = _project_id()
    raw = _api("GET", f"/projects/{pid}/milestones", params={"per_page": "100"})
    return {d["title"] for d in raw}


def _existing_boards() -> list[dict]:
    pid = _project_id()
    return _api("GET", f"/projects/{pid}/boards")


def _board_list_labels(board_id: int) -> set[str]:
    pid = _project_id()
    raw = _api("GET", f"/projects/{pid}/boards/{board_id}/lists")
    return {d["label"]["name"] for d in raw if d.get("label")}


# ── Setup routines ────────────────────────────────────────────────────────────

def setup_labels() -> None:
    print("\n── Labels ──────────────────────────────────────────")
    existing = _existing_labels()
    pid = _project_id()
    created = 0
    skipped = 0
    for name, color, desc in LABELS:
        if name in existing:
            print(f"  SKIP  {name}")
            skipped += 1
            continue
        try:
            _api(
                "POST",
                f"/projects/{pid}/labels",
                data={"name": name, "color": color, "description": desc},
            )
            print(f"  CREATE {name}  ({color})")
            created += 1
        except RuntimeError as exc:
            print(f"  ERROR  {name}: {exc}")
    print(f"  → {created} created, {skipped} already existed")


def setup_milestones() -> None:
    print("\n── Milestones ──────────────────────────────────────")
    existing = _existing_milestones()
    pid = _project_id()
    created = 0
    for title, desc, due in _sprint_milestones(n=4):
        if title in existing:
            print(f"  SKIP  {title}")
            continue
        try:
            _api(
                "POST",
                f"/projects/{pid}/milestones",
                data={"title": title, "description": desc, "due_date": due},
            )
            print(f"  CREATE {title} (due {due})")
            created += 1
        except RuntimeError as exc:
            print(f"  ERROR  {title}: {exc}")
    print(f"  → {created} sprint milestones created")


def setup_board() -> None:
    print("\n── Issue Board ─────────────────────────────────────")
    pid = _project_id()
    boards = _existing_boards()

    # Use the first board (GitLab CE only allows one board per project)
    if not boards:
        print("  No boards found — GitLab should create one automatically.")
        return

    board = boards[0]
    board_id = board["id"]
    print(f"  Board: '{board['name']}' (id={board_id})")

    existing_list_labels = _board_list_labels(board_id)
    added = 0
    for label in BOARD_COLUMNS:
        if label in existing_list_labels:
            print(f"  SKIP  column '{label}'")
            continue
        try:
            _api(
                "POST",
                f"/projects/{pid}/boards/{board_id}/lists",
                data={"label_id": _label_id(label)},
            )
            print(f"  CREATE column '{label}'")
            added += 1
        except RuntimeError as exc:
            print(f"  ERROR  column '{label}': {exc}")
    print(f"  → {added} board columns added")


def _label_id(name: str) -> int:
    pid = _project_id()
    raw = _api("GET", f"/projects/{pid}/labels", params={"search": name, "per_page": "5"})
    for d in raw:
        if d["name"] == name:
            return d["id"]
    raise RuntimeError(f"Label '{name}' not found — run setup_labels first")


def triage_existing_issues() -> None:
    """
    Auto-triage existing issues that have no status:: label.
    Set them to status::triage so they appear in the first board column.
    """
    print("\n── Triaging label-less issues ──────────────────────")
    issues = list_issues(state="opened", per_page=100)
    pid = _project_id()
    count = 0
    for issue in issues:
        if not any(l.startswith("status::") for l in issue.labels):
            new_labels = list(issue.labels) + ["status::triage"]
            try:
                _api(
                    "PUT",
                    f"/projects/{pid}/issues/{issue.iid}",
                    data={"labels": ",".join(new_labels)},
                )
                add_issue_comment(
                    issue.iid,
                    "🏷️ **Auto-triaged.** This issue had no status label. "
                    "Set to `status::triage` — please categorise and move to backlog.",
                )
                print(f"  TRIAGE  #{issue.iid}: {issue.title[:60]}")
                count += 1
            except RuntimeError as exc:
                print(f"  ERROR  #{issue.iid}: {exc}")
    if count == 0:
        print("  All open issues already have a status label.")
    else:
        print(f"  → {count} issues auto-triaged")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"GitLab Setup — {_base_url()}/api/v4 (project {_project_id()})")
    print("=" * 60)

    try:
        user = _api("GET", "/user")
        print(f"Authenticated as: {user.get('username', '?')} ({user.get('name', '?')})")
    except RuntimeError as exc:
        print(f"ERROR: Cannot authenticate: {exc}")
        sys.exit(1)

    setup_labels()
    setup_milestones()
    setup_board()
    triage_existing_issues()

    print("\n✅ GitLab setup complete.")
    print(f"   Board: {_base_url().rstrip('/gitlab')}/gitlab/shml/platform/-/boards")


if __name__ == "__main__":
    main()
