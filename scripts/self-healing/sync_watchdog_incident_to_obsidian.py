#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
PLATFORM_ROOT = Path(os.environ.get("WATCHDOG_PLATFORM_ROOT", str(DEFAULT_PLATFORM_ROOT)))
VAULT_NOTE = PLATFORM_ROOT / "docs" / "obsidian-vault" / "50-Projects" / "plan.md"
SECTION_HEADER = "## Recent Watchdog Incident Sync"
START_MARKER = "<!-- watchdog-incident-sync:start -->"
END_MARKER = "<!-- watchdog-incident-sync:end -->"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync a watchdog incident summary into the shared Obsidian vault")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--issue-type", required=True)
    parser.add_argument("--severity", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--root-cause", required=True)
    parser.add_argument("--containers", default="")
    parser.add_argument("--restart-order", default="")
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--transcript-path", default="")
    parser.add_argument("--gitlab-issue", default="")
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_entry(args: argparse.Namespace) -> str:
    restart_order = [item for item in args.restart_order.split() if item]
    containers = [item for item in args.containers.split() if item]
    lines = [
        f"### Incident {args.incident_id} — {args.issue_type}",
        f"- Severity: `{args.severity}`",
        f"- Synced: `{utc_now()}`",
        f"- Summary: {args.summary}",
        f"- Root Cause: {args.root_cause}",
        f"- Evidence Bundle: `{args.evidence_dir}`",
    ]
    if containers:
        lines.append(f"- Affected Containers: `{', '.join(containers)}`")
    if restart_order:
        lines.append(f"- Restart Order: `{', '.join(restart_order)}`")
    if args.transcript_path:
        lines.append(f"- Hermes Transcript: `{args.transcript_path}`")
    if args.gitlab_issue:
        lines.append(f"- GitLab Issue: `{args.gitlab_issue}`")
    lines.append(
        "- Related Vault Notes: [[50-Projects/INDEX|Projects]] | [[50-Projects/PLATFORM_STATUS|Platform Status]] | [[00-Dashboard/HOME|Vault Home]]"
    )
    return "\n".join(lines)


def ensure_section(text: str) -> str:
    if START_MARKER in text and END_MARKER in text:
        return text
    suffix = "\n" if text.endswith("\n") else "\n\n"
    return text + suffix + SECTION_HEADER + "\n\n" + START_MARKER + "\n" + END_MARKER + "\n"


def upsert_entry(text: str, args: argparse.Namespace) -> str:
    entry = build_entry(args)
    if START_MARKER not in text or END_MARKER not in text:
        suffix = "\n" if text.endswith("\n") else "\n\n"
        return text + suffix + SECTION_HEADER + "\n\n" + START_MARKER + "\n" + entry + "\n" + END_MARKER + "\n"

    text = ensure_section(text)
    pattern = re.compile(rf"^### Incident {re.escape(args.incident_id)} — .*?(?=^### Incident |\Z)", re.MULTILINE | re.DOTALL)
    start_token = START_MARKER + "\n"
    end_token = "\n" + END_MARKER
    start_index = text.find(start_token)
    end_index = text.find(end_token, start_index + len(start_token))
    if start_index == -1 or end_index == -1:
        raise SystemExit("Managed watchdog sync section is missing")

    body = text[start_index + len(start_token):end_index].strip()
    if body:
        if pattern.search(body):
            body = pattern.sub(entry + "\n\n", body).strip()
        else:
            body = entry + "\n\n" + body
    else:
        body = entry

    replacement = start_token + body + end_token
    return text[:start_index] + replacement + text[end_index + len(end_token):]


def main() -> int:
    args = parse_args()
    if not VAULT_NOTE.exists():
        raise SystemExit(f"Vault note not found: {VAULT_NOTE}")

    content = VAULT_NOTE.read_text(encoding="utf-8")
    updated = upsert_entry(content, args)
    VAULT_NOTE.write_text(updated, encoding="utf-8")
    print(f"Updated Obsidian vault note: {VAULT_NOTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
