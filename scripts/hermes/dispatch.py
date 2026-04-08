#!/usr/bin/env python3
"""Unified Hermes dispatch library for the SHML platform.

Provides a single interface for dispatching Hermes agent tasks, used by:
- Watchdog (incident response)
- Issue board poller (assignee::agent tasks)
- Manual CLI invocations

The dispatch pipeline:
1. Build a context-rich prompt from the task specification
2. Run Hermes in non-interactive (--yolo -q) mode
3. Parse structured JSON output
4. Update GitLab issue with results
5. Send Telegram notification
6. Sync to Obsidian vault
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PLATFORM_ROOT = Path(os.environ.get(
    "WATCHDOG_PLATFORM_ROOT",
    Path(__file__).resolve().parents[2],
))
HERMES_BIN = Path(os.environ.get(
    "HERMES_BIN",
    Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "hermes",
))
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class DispatchTask:
    """A task to dispatch to Hermes."""
    task_type: str                         # "incident", "issue", "manual"
    title: str
    description: str
    project_id: int = 2                    # GitLab project ID
    gitlab_issue_iid: Optional[int] = None
    labels: list[str] = field(default_factory=list)
    evidence_dir: Optional[Path] = None
    containers: list[str] = field(default_factory=list)
    extra_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class DispatchResult:
    """Result from a Hermes dispatch."""
    success: bool
    payload: dict[str, Any]
    transcript: str
    duration_seconds: float = 0.0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_incident_prompt(task: DispatchTask) -> str:
    evidence_listing = ""
    if task.evidence_dir and task.evidence_dir.exists():
        files = sorted(task.evidence_dir.rglob("*"))
        evidence_listing = "\n".join(f"  - {f.relative_to(task.evidence_dir)}" for f in files if f.is_file())

    return f"""You are Hermes, the SHML platform incident responder.

Incident:
- Type: {task.title}
- Affected containers: {', '.join(task.containers) or 'unknown'}
- Description: {task.description}

Evidence bundle at: {task.evidence_dir or 'N/A'}
{evidence_listing}

Tasks:
1. Inspect evidence bundle contents (logs, inspect output, health snapshots).
2. Diagnose the most likely root cause.
3. Propose the safest restart order.
4. State whether GPU yield is needed.
5. Summarize for the shared vault note.

Return JSON only:
{{
  "diagnosis": "short diagnosis",
  "root_cause": "most likely root cause",
  "severity": "critical|warning|info",
  "actions_taken": [],
  "restart_order": [],
  "gpu_yield_needed": false,
  "vault_summary": "2-3 sentence summary",
  "operator_notes": "notes for human review"
}}

Do not use placeholder names — populate restart_order with real container names from the incident context above."""


def _build_issue_prompt(task: DispatchTask) -> str:
    labels_str = ", ".join(task.labels) if task.labels else "none"
    extra_ctx = ""
    if task.extra_context:
        extra_ctx = "\nAdditional context:\n" + json.dumps(task.extra_context, indent=2)

    return f"""You are Hermes, the SHML platform autonomous agent.

You have been assigned GitLab issue #{task.gitlab_issue_iid or 'N/A'}:
- Title: {task.title}
- Labels: {labels_str}
- Description:
{task.description}
{extra_ctx}

Instructions:
1. Analyze the issue and determine what needs to be done.
2. If code changes are needed, describe the exact files and changes.
3. If this is an investigation, provide findings with evidence.
4. Summarize what was done and what remains.

Return JSON only:
{{
  "analysis": "what the issue requires",
  "actions_taken": ["action1", "action2"],
  "code_changes": [{{"file": "path", "change": "description"}}],
  "findings": "investigation findings if applicable",
  "status": "completed|in-progress|blocked",
  "blocked_reason": null,
  "vault_summary": "2-3 sentence summary for knowledge base",
  "next_steps": ["step1", "step2"],
  "mr_ready": false,
  "mr_title": null,
  "mr_description": null
}}"""


def build_prompt(task: DispatchTask) -> str:
    """Build the appropriate prompt based on task type."""
    if task.task_type == "incident":
        return _build_incident_prompt(task)
    return _build_issue_prompt(task)


# ---------------------------------------------------------------------------
# Hermes execution
# ---------------------------------------------------------------------------

def clean_output(text: str) -> str:
    """Strip ANSI escape codes and carriage returns."""
    return ANSI_ESCAPE.sub("", text).replace("\r", "")


def extract_json_payload(text: str) -> dict[str, Any]:
    """Extract the first valid JSON object from Hermes output."""
    decoder = json.JSONDecoder()
    cleaned = clean_output(text)
    for marker in ("```json", "```"):
        cleaned = cleaned.replace(marker, "")
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("No valid JSON object found in Hermes output")


def run_hermes(task: DispatchTask, timeout: int = 300) -> DispatchResult:
    """Execute Hermes with the task prompt and return structured results."""
    hermes_bin = HERMES_BIN
    if not hermes_bin.exists():
        return DispatchResult(
            success=False, payload={}, transcript="",
            error=f"Hermes binary not found: {hermes_bin}",
        )

    prompt = build_prompt(task)
    env = os.environ.copy()
    hermes_parts = hermes_bin.parts
    if ".hermes" in hermes_parts:
        idx = hermes_parts.index(".hermes")
        if idx > 0:
            env["HOME"] = str(Path(*hermes_parts[:idx]))

    command = [str(hermes_bin), "chat", "--yolo", "-q", prompt]
    start = datetime.now(timezone.utc)

    try:
        proc = subprocess.run(
            command,
            cwd=str(PLATFORM_ROOT),
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return DispatchResult(
            success=False, payload={}, transcript="",
            duration_seconds=(datetime.now(timezone.utc) - start).total_seconds(),
            error=f"Hermes timed out after {timeout}s",
        )

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    transcript = "\n".join([
        f"exit_code={proc.returncode}",
        "--- stdout ---",
        proc.stdout or "",
        "--- stderr ---",
        proc.stderr or "",
    ])

    if proc.returncode != 0:
        return DispatchResult(
            success=False, payload={}, transcript=transcript,
            duration_seconds=elapsed,
            error=f"Hermes exited with code {proc.returncode}",
        )

    try:
        payload = extract_json_payload(proc.stdout + "\n" + (proc.stderr or ""))
    except ValueError as e:
        return DispatchResult(
            success=False, payload={}, transcript=transcript,
            duration_seconds=elapsed,
            error=str(e),
        )

    return DispatchResult(
        success=True, payload=payload, transcript=transcript,
        duration_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# Post-dispatch actions
# ---------------------------------------------------------------------------

def update_gitlab_issue(
    task: DispatchTask,
    result: DispatchResult,
    *,
    close_on_complete: bool = False,
) -> Optional[int]:
    """Update the GitLab issue with dispatch results. Returns issue IID."""
    import sys
    sys.path.insert(0, str(PLATFORM_ROOT / "scripts" / "platform"))

    try:
        from gitlab_utils import add_issue_comment, update_issue, upsert_issue
    except ImportError:
        logger.warning("gitlab_utils not available — skipping issue update")
        return None

    old_project = os.environ.get("GITLAB_PROJECT_ID")
    os.environ["GITLAB_PROJECT_ID"] = str(task.project_id)

    try:
        status_emoji = "✅" if result.success else "❌"
        status_label = result.payload.get("status", "completed" if result.success else "failed")

        comment_lines = [
            f"### {status_emoji} Hermes Agent Report",
            f"**Task type:** {task.task_type}",
            f"**Duration:** {result.duration_seconds:.1f}s",
            f"**Status:** {status_label}",
            "",
        ]

        if result.error:
            comment_lines.append(f"**Error:** {result.error}")
        else:
            payload = result.payload
            if task.task_type == "incident":
                comment_lines.extend([
                    f"**Diagnosis:** {payload.get('diagnosis', 'N/A')}",
                    f"**Root cause:** {payload.get('root_cause', 'N/A')}",
                    f"**Severity:** {payload.get('severity', 'N/A')}",
                    f"**Restart order:** {', '.join(payload.get('restart_order', []))}",
                    f"**GPU yield needed:** {payload.get('gpu_yield_needed', False)}",
                ])
            else:
                comment_lines.extend([
                    f"**Analysis:** {payload.get('analysis', 'N/A')}",
                    f"**Actions:** {', '.join(payload.get('actions_taken', []))}",
                    f"**MR ready:** {payload.get('mr_ready', False)}",
                ])
                if payload.get("next_steps"):
                    comment_lines.append(f"**Next steps:** {', '.join(payload['next_steps'])}")
                if payload.get("blocked_reason"):
                    comment_lines.append(f"**Blocked:** {payload['blocked_reason']}")

            if payload.get("vault_summary"):
                comment_lines.extend(["", f"> {payload['vault_summary']}"])

        comment = "\n".join(comment_lines)

        if task.gitlab_issue_iid:
            add_issue_comment(task.gitlab_issue_iid, comment)
            labels_update = list(task.labels)
            if status_label == "completed" and close_on_complete:
                labels_update.append("status::done")
                update_issue(task.gitlab_issue_iid, state_event="close")
            elif status_label == "blocked":
                labels_update.append("status::blocked")
            return task.gitlab_issue_iid
        else:
            issue = upsert_issue(
                task.title,
                description=task.description,
                labels=task.labels,
                comment=comment,
            )
            return issue.iid if issue else None
    finally:
        if old_project is not None:
            os.environ["GITLAB_PROJECT_ID"] = old_project
        elif "GITLAB_PROJECT_ID" in os.environ:
            del os.environ["GITLAB_PROJECT_ID"]


def send_telegram_summary(
    task: DispatchTask,
    result: DispatchResult,
    *,
    gitlab_issue_iid: Optional[int] = None,
    mr_url: Optional[str] = None,
) -> bool:
    """Send a Telegram notification with the dispatch summary."""
    try:
        from libs.notify import send_telegram
    except ImportError:
        import sys
        sys.path.insert(0, str(PLATFORM_ROOT))
        try:
            from libs.notify import send_telegram
        except ImportError:
            logger.warning("libs.notify not available — skipping Telegram")
            return False

    status = "✅ Complete" if result.success else "❌ Failed"
    payload = result.payload

    lines = [
        f"🤖 <b>Hermes Agent — {task.task_type.title()}</b>",
        f"<b>Task:</b> {task.title}",
        f"<b>Status:</b> {status}",
        f"<b>Duration:</b> {result.duration_seconds:.0f}s",
    ]

    if result.error:
        lines.append(f"<b>Error:</b> {result.error}")
    elif payload.get("vault_summary"):
        lines.append(f"<b>Summary:</b> {payload['vault_summary']}")

    if gitlab_issue_iid:
        lines.append(f"<b>Issue:</b> #{gitlab_issue_iid}")

    if mr_url:
        lines.append(f"<b>MR:</b> <a href=\"{mr_url}\">Ready for review</a>")

    if payload.get("mr_ready"):
        lines.append("🔍 <b>MR ready for review!</b>")

    return send_telegram("\n".join(lines), parse_mode="HTML")


def sync_to_obsidian(
    task: DispatchTask,
    result: DispatchResult,
    *,
    gitlab_issue_iid: Optional[int] = None,
) -> bool:
    """Sync the dispatch result to the Obsidian vault."""
    vault_base = PLATFORM_ROOT / "docs" / "obsidian-vault"
    if not vault_base.exists():
        logger.debug("Obsidian vault not found at %s", vault_base)
        return False

    if task.task_type == "incident":
        return _sync_incident_to_vault(task, result, vault_base, gitlab_issue_iid)
    return _sync_task_to_vault(task, result, vault_base, gitlab_issue_iid)


def _sync_incident_to_vault(
    task: DispatchTask,
    result: DispatchResult,
    vault_base: Path,
    gitlab_issue_iid: Optional[int],
) -> bool:
    """Delegate to the existing watchdog incident sync script."""
    script = PLATFORM_ROOT / "scripts" / "self-healing" / "sync_watchdog_incident_to_obsidian.py"
    if not script.exists():
        return False

    payload = result.payload
    cmd = [
        "python3", str(script),
        "--incident-id", str(gitlab_issue_iid or "unknown"),
        "--issue-type", task.title,
        "--severity", payload.get("severity", "info"),
        "--summary", payload.get("vault_summary", task.description),
        "--root-cause", payload.get("root_cause", "unknown"),
        "--containers", " ".join(task.containers),
        "--restart-order", " ".join(payload.get("restart_order", [])),
        "--evidence-dir", str(task.evidence_dir or ""),
        "--gitlab-issue", str(gitlab_issue_iid or ""),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning("Obsidian incident sync failed: %s", e)
        return False


def _sync_task_to_vault(
    task: DispatchTask,
    result: DispatchResult,
    vault_base: Path,
    gitlab_issue_iid: Optional[int],
) -> bool:
    """Create/update an Obsidian note for agent task work."""
    decisions_dir = vault_base / "20-Decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    payload = result.payload
    status = payload.get("status", "completed" if result.success else "failed")
    safe_title = re.sub(r'[^\w\s-]', '', task.title).strip().replace(' ', '-')[:60]
    note_name = f"{date_str}-{safe_title}.md"
    note_path = decisions_dir / note_name

    frontmatter = [
        "---",
        f"title: \"{task.title}\"",
        f"date: {now.isoformat()}",
        f"type: agent-task",
        f"status: {status}",
        f"task_type: {task.task_type}",
        f"project_id: {task.project_id}",
    ]
    if gitlab_issue_iid:
        frontmatter.append(f"gitlab_issue: {gitlab_issue_iid}")
    if task.labels:
        frontmatter.append(f"labels: [{', '.join(task.labels)}]")
    frontmatter.append("---")

    body = [
        "",
        f"# {task.title}",
        "",
        f"**Agent:** Hermes | **Duration:** {result.duration_seconds:.0f}s | **Status:** {status}",
        "",
        "## Task Description",
        "",
        task.description,
        "",
        "## Agent Analysis",
        "",
    ]

    if result.error:
        body.append(f"**Error:** {result.error}")
    else:
        if payload.get("analysis"):
            body.append(payload["analysis"])
        if payload.get("diagnosis"):
            body.extend(["", f"**Diagnosis:** {payload['diagnosis']}"])
        if payload.get("root_cause"):
            body.append(f"**Root cause:** {payload['root_cause']}")

    if payload.get("actions_taken"):
        body.extend(["", "## Actions Taken", ""])
        for action in payload["actions_taken"]:
            body.append(f"- {action}")

    if payload.get("code_changes"):
        body.extend(["", "## Code Changes", ""])
        for change in payload["code_changes"]:
            body.append(f"- `{change.get('file', '?')}`: {change.get('change', '?')}")

    if payload.get("next_steps"):
        body.extend(["", "## Next Steps", ""])
        for step in payload["next_steps"]:
            body.append(f"- {step}")

    if payload.get("vault_summary"):
        body.extend(["", "## Summary", "", f"> {payload['vault_summary']}"])

    body.extend([
        "",
        "## Links",
        "",
        f"- [[50-Projects/INDEX|Projects]]",
    ])
    if gitlab_issue_iid:
        body.append(f"- GitLab Issue: #{gitlab_issue_iid}")

    content = "\n".join(frontmatter + body) + "\n"

    if note_path.exists():
        existing = note_path.read_text(encoding="utf-8")
        if "## Agent Analysis" in existing:
            # Append update rather than overwrite
            update = f"\n\n---\n\n## Update ({now.strftime('%H:%M UTC')})\n\n"
            update += "\n".join(body[body.index("## Agent Analysis") + 1:])
            note_path.write_text(existing + update, encoding="utf-8")
            return True

    note_path.write_text(content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Main dispatch orchestrator
# ---------------------------------------------------------------------------

def dispatch(
    task: DispatchTask,
    *,
    timeout: int = 300,
    update_issue: bool = True,
    notify_telegram: bool = True,
    sync_vault: bool = True,
    close_on_complete: bool = False,
) -> DispatchResult:
    """Full dispatch pipeline: run Hermes → update issue → notify → sync vault."""
    logger.info("Dispatching %s task: %s", task.task_type, task.title)

    result = run_hermes(task, timeout=timeout)

    gitlab_iid = None
    if update_issue:
        gitlab_iid = update_gitlab_issue(
            task, result, close_on_complete=close_on_complete,
        )

    if notify_telegram:
        send_telegram_summary(task, result, gitlab_issue_iid=gitlab_iid)

    if sync_vault:
        sync_to_obsidian(task, result, gitlab_issue_iid=gitlab_iid)

    logger.info(
        "Dispatch complete: success=%s duration=%.1fs",
        result.success, result.duration_seconds,
    )
    return result
