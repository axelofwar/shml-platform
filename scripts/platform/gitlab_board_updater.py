#!/usr/bin/env python3
"""
gitlab_board_updater.py — Read platform scan evidence and transition GitLab issue labels.

This is the reconciliation layer for GitLab-based state tracking. It resolves
issues (status::done + closed) when the evidence confirms the work is complete.

Rules mirror the original state-transition rules used during the migration:
  • Autoresearch Round 2 done  → resolve "Autoresearch Round 2"
  • T8 all stages done         → resolve "Track 8: nanochat"
  • GEPA triggered             → resolve "T3.3 GEPA"
  • CLOUD_API_KEY set          → resolve "CLOUD_API_KEY"
  • Platform scan running      → resolve "Platform scan framework"

Usage:
    python3 gitlab_board_updater.py --evidence evidence.json [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import NamedTuple

# Allow running from repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "platform"))

from gitlab_utils import resolve_issue  # noqa: E402


class TransitionRule(NamedTuple):
    issue_title_pattern: str   # substring match against GitLab issue title
    condition_key: str         # dot-notation key in evidence.json (truthy = trigger)
    done_comment: str          # comment posted when resolved


TRANSITION_RULES: list[TransitionRule] = [
    TransitionRule(
        "Autoresearch Round 2",
        "autoresearch.round2_done",
        "✅ Autoresearch Round 2 confirmed complete by platform scan (evidence.json).",
    ),
    TransitionRule(
        "Track 8: nanochat",
        "t8.all_done",
        "✅ T8 all pipeline stages confirmed complete by platform scan (evidence.json).",
    ),
    TransitionRule(
        "T3.3 GEPA",
        "gepa_triggered",
        "✅ GEPA engine run confirmed by platform scan (gepa_trigger.log).",
    ),
    TransitionRule(
        "CLOUD_API_KEY",
        "cloud_key_set",
        "✅ CLOUD_API_KEY is set — cloud failover confirmed active.",
    ),
    TransitionRule(
        "Platform scan framework",
        "_scan_running",
        "✅ Platform scan framework is running (this script executed successfully).",
    ),
]


def get_evidence(evidence: dict, dotkey: str) -> bool:
    """Resolve dot-notation key from evidence dict.  Returns bool."""
    if dotkey == "_scan_running":
        return True
    keys = dotkey.split(".")
    val = evidence
    for k in keys:
        if not isinstance(val, dict) or k not in val:
            return False
        val = val[k]
    return bool(val)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transition GitLab issue labels based on platform evidence"
    )
    parser.add_argument("--evidence", required=True, help="Path to evidence.json")
    parser.add_argument("--dry-run", action="store_true", help="Print transitions without applying")
    args = parser.parse_args()

    evidence_path = Path(args.evidence)
    if not evidence_path.exists():
        print(f"ERROR: {evidence_path} not found", file=sys.stderr)
        return 1

    with open(evidence_path) as f:
        evidence = json.load(f)

    triggered = [r for r in TRANSITION_RULES if get_evidence(evidence, r.condition_key)]

    if not triggered:
        print("No GitLab transitions needed.")
        return 0

    print(f"Applying {len(triggered)} GitLab transition(s):")
    for rule in triggered:
        print(f"  → resolve '{rule.issue_title_pattern}'  [{rule.condition_key}]")
        if not args.dry_run:
            try:
                resolve_issue(rule.issue_title_pattern, comment=rule.done_comment)
                print(f"    ✅ resolved")
            except Exception as exc:
                print(f"    ⚠️  {exc} (non-fatal)")

    if args.dry_run:
        print("[dry-run] No changes written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
