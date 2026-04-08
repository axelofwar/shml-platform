#!/usr/bin/env python3
"""Watchdog incident dispatch adapter for the unified dispatch library.

This script is the new entrypoint called by watchdog.sh inside the
Hermes helper container.  It replaces dispatch_watchdog_hermes.py and
delegates directly to scripts/hermes/dispatch.py so watchdog incidents
use the same pipeline as issue-board tasks (Hermes → GitLab → Telegram
→ Obsidian).

Backwards-compatible argument interface — watchdog.sh passes the same
flags as before.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

PLATFORM_ROOT = Path(os.environ.get(
    "WATCHDOG_PLATFORM_ROOT",
    Path(__file__).resolve().parents[2],
))
sys.path.insert(0, str(PLATFORM_ROOT / "scripts" / "hermes"))
sys.path.insert(0, str(PLATFORM_ROOT / "scripts" / "platform"))
sys.path.insert(0, str(PLATFORM_ROOT))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch a watchdog incident to Hermes via unified pipeline")
    parser.add_argument("--issue-type", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--containers", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--transcript-path", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    from dispatch import DispatchTask, dispatch

    task = DispatchTask(
        task_type="incident",
        title=args.issue_type,
        description=args.description,
        project_id=int(os.environ.get("GITLAB_PROJECT_ID", "2")),
        containers=args.containers.split(",") if args.containers else [],
        evidence_dir=args.evidence_dir,
    )

    result = dispatch(
        task,
        timeout=args.timeout,
        update_issue=True,
        notify_telegram=True,
        sync_vault=True,
        close_on_complete=False,
    )

    # Write outputs for watchdog.sh compatibility
    args.transcript_path.parent.mkdir(parents=True, exist_ok=True)
    args.transcript_path.write_text(result.transcript, encoding="utf-8")

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result.payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if not result.success:
        logger.error("Dispatch failed: %s", result.error)
        return 1

    logger.info("Dispatch completed in %.1fs", result.duration_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
