#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_PLATFORM_ROOT = Path("/home/axelofwar/Projects/shml-platform")
DEFAULT_HERMES_BIN = Path("/home/axelofwar/.hermes/hermes-agent/venv/bin/hermes")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Hermes against a watchdog incident evidence bundle")
    parser.add_argument("--issue-type", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--containers", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--transcript-path", type=Path, required=True)
    parser.add_argument("--platform-root", type=Path, default=Path(os.environ.get("WATCHDOG_PLATFORM_ROOT", DEFAULT_PLATFORM_ROOT)))
    parser.add_argument("--hermes-bin", type=Path, default=Path(os.environ.get("HERMES_BIN", DEFAULT_HERMES_BIN)))
    parser.add_argument("--timeout", type=int, default=300)
    return parser.parse_args()


def build_prompt(args: argparse.Namespace) -> str:
    return f"""You are Hermes, the local SHML platform incident responder.

Use local evidence first. Read the evidence bundle at:
- {args.evidence_dir}

Incident:
- Type: {args.issue_type}
- Affected containers: {args.containers}
- Description: {args.description}

Tasks:
1. Inspect the evidence bundle contents, especially container logs, inspect output, health snapshots, and platform state.
2. Diagnose the most likely root cause.
3. Propose the safest restart order if remediation should happen now.
4. State whether GPU yield is needed before restarting anything.
5. Summarize what should be written to the shared vault note.

Return JSON only — use EXACT container names from the evidence above, not placeholder names:
{{
  "diagnosis": "short diagnosis",
  "root_cause": "most likely root cause",
  "severity": "critical|warning|info",
  "restart_order": [],
  "gpu_yield_needed": false,
  "requires_agent_service": false,
  "vault_summary": "2-3 sentence incident summary",
  "operator_notes": "short operational notes"
}}

Do not wrap the JSON in Markdown fences.
Do not use example or placeholder names — use real container names from the incident context."""


def run_hermes(args: argparse.Namespace, prompt: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    hermes_parts = args.hermes_bin.parts
    if ".hermes" in hermes_parts:
        hermes_index = hermes_parts.index(".hermes")
        if hermes_index > 0:
            env["HOME"] = str(Path(*hermes_parts[:hermes_index]))
    command = [str(args.hermes_bin), "chat", "--yolo", "-q", prompt]
    return subprocess.run(
        command,
        cwd=str(args.platform_root),
        text=True,
        capture_output=True,
        timeout=args.timeout,
        env=env,
        check=False,
    )


def clean_output(text: str) -> str:
    return ANSI_ESCAPE.sub("", text).replace("\r", "")


def extract_payload(text: str) -> dict[str, Any]:
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
        if isinstance(payload, dict) and "diagnosis" in payload:
            return payload
    raise ValueError("Hermes output did not contain a valid diagnosis JSON object")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def main() -> int:
    args = parse_args()
    if not args.hermes_bin.exists():
        raise SystemExit(f"Hermes binary not found: {args.hermes_bin}")
    if not args.evidence_dir.exists():
        raise SystemExit(f"Evidence directory not found: {args.evidence_dir}")

    prompt = build_prompt(args)
    proc = run_hermes(args, prompt)
    transcript = "\n".join(
        [
            f"command_exit_code={proc.returncode}",
            "--- stdout ---",
            proc.stdout,
            "--- stderr ---",
            proc.stderr,
        ]
    )
    ensure_parent(args.transcript_path)
    args.transcript_path.write_text(transcript, encoding="utf-8")

    if proc.returncode != 0:
        raise SystemExit(f"Hermes command failed with exit code {proc.returncode}")

    payload = extract_payload(proc.stdout + "\n" + proc.stderr)
    ensure_parent(args.output_json)
    args.output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())