"""Prompt builders for Hermes dispatch tasks."""
from __future__ import annotations

import json

from ._types import DispatchTask

_ISSUE_JSON_SCHEMA = """{
  "analysis": "what the issue requires",
  "actions_taken": ["action1"],
  "code_changes": [{"file": "path/to/file", "change": "description"}],
  "findings": "investigation findings",
  "status": "completed|in-progress|blocked",
  "blocked_reason": null,
  "vault_summary": "2-3 sentence summary for knowledge base",
  "next_steps": ["step1"],
  "mr_ready": false,
  "mr_title": null,
  "mr_description": null
}"""

_INCIDENT_JSON_SCHEMA = """{
  "diagnosis": "short diagnosis",
  "root_cause": "most likely root cause",
  "severity": "critical|warning|info",
  "actions_taken": [],
  "restart_order": [],
  "gpu_yield_needed": false,
  "vault_summary": "2-3 sentence summary",
  "operator_notes": "notes for human review"
}"""


def build_issue_prompt(task: DispatchTask) -> str:
    labels_str = ", ".join(task.labels) if task.labels else "none"
    extra = ""
    if task.extra_context:
        extra = "\n\nAdditional context:\n" + json.dumps(task.extra_context, indent=2)

    return (
        f"You are Hermes, the SHML platform autonomous agent.\n\n"
        f"You have been assigned GitLab issue #{task.gitlab_issue_iid or 'N/A'} "
        f"(project {task.project_id}):\n"
        f"- Title: {task.title}\n"
        f"- Labels: {labels_str}\n"
        f"- Description:\n{task.description}"
        f"{extra}\n\n"
        f"Instructions:\n"
        f"1. Analyze the issue and determine exactly what needs to be done.\n"
        f"2. If code changes are required, make them directly — do not just describe.\n"
        f"3. If investigation only, provide findings with evidence.\n"
        f"4. Summarize what was done and what remains.\n\n"
        f"Return JSON only:\n{_ISSUE_JSON_SCHEMA}"
    )


def build_incident_prompt(task: DispatchTask) -> str:
    evidence_listing = ""
    if task.evidence_dir and task.evidence_dir.exists():
        files = sorted(task.evidence_dir.rglob("*"))
        evidence_listing = "\n".join(
            f"  - {f.relative_to(task.evidence_dir)}"
            for f in files if f.is_file()
        )
        evidence_listing = f"\nEvidence files:\n{evidence_listing}"

    return (
        f"You are Hermes, the SHML platform incident responder.\n\n"
        f"Incident:\n"
        f"- Type: {task.title}\n"
        f"- Affected containers: {', '.join(task.containers) or 'unknown'}\n"
        f"- Description: {task.description}\n"
        f"- Evidence bundle: {task.evidence_dir or 'N/A'}"
        f"{evidence_listing}\n\n"
        f"Tasks:\n"
        f"1. Inspect evidence bundle contents.\n"
        f"2. Diagnose the most likely root cause.\n"
        f"3. Propose the safest restart order.\n"
        f"4. State whether GPU yield is needed.\n"
        f"5. Summarize for the shared vault note.\n\n"
        f"Return JSON only:\n{_INCIDENT_JSON_SCHEMA}"
    )


def build_prompt(task: DispatchTask) -> str:
    """Dispatch to the correct prompt builder based on task_type."""
    if task.task_type == "incident":
        return build_incident_prompt(task)
    return build_issue_prompt(task)
