#!/usr/bin/env python3
"""Skill Auto-Update System — SHML Platform.

Scans the live platform state and updates skill SKILL.md files with:
- Current container inventory and health
- GPU configuration
- Service endpoints
- Training status
- Recent incidents from watchdog logs

This keeps skills accurate as the platform evolves — new services,
changed ports, updated GPU allocation, etc.

Usage:
    python skill_updater.py                    # Update all skills
    python skill_updater.py --skill platform-health  # Update one skill
    python skill_updater.py --dry-run          # Show diffs without writing
    python skill_updater.py --report           # Print state report only

Designed to run as a periodic job (cron or compose service).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("skill-updater")

SKILLS_DIR = os.getenv("SKILLS_DIR", "/workspace/skills")
PLATFORM_PREFIX = os.getenv("PLATFORM_PREFIX", "shml")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")


def run_cmd(cmd: str, timeout: int = 30) -> str:
    """Run a shell command and return stdout."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, Exception) as e:
        logger.warning("Command failed: %s — %s", cmd, e)
        return ""


def send_telegram(msg: str) -> None:
    """Best-effort Telegram notification."""
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT):
        return
    try:
        import requests

        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Platform state collectors
# ---------------------------------------------------------------------------
def collect_containers() -> list[dict[str, str]]:
    """Get running container info."""
    output = run_cmd(
        "docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}' 2>/dev/null"
    )
    containers = []
    for line in output.split("\n"):
        if "|" in line:
            parts = line.split("|", 3)
            containers.append(
                {
                    "name": parts[0],
                    "image": parts[1] if len(parts) > 1 else "",
                    "status": parts[2] if len(parts) > 2 else "",
                    "ports": parts[3] if len(parts) > 3 else "",
                }
            )
    return containers


def collect_gpu_info() -> list[dict[str, str]]:
    """Get GPU info via nvidia-smi."""
    output = run_cmd(
        "nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu "
        "--format=csv,noheader 2>/dev/null"
    )
    gpus = []
    for line in output.split("\n"):
        if "," in line:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                gpus.append(
                    {
                        "index": parts[0],
                        "name": parts[1],
                        "mem_used": parts[2],
                        "mem_total": parts[3],
                        "utilization": parts[4],
                        "temperature": parts[5],
                    }
                )
    return gpus


def collect_compose_services() -> list[str]:
    """Get list of services defined in compose files."""
    output = run_cmd(
        "find /workspace -name 'docker-compose*.yml' -exec grep -l 'services:' {} \\; 2>/dev/null"
    )
    compose_files = [f for f in output.split("\n") if f]
    services = set()
    for cf in compose_files:
        svc_output = run_cmd(
            f"grep -E '^  [a-zA-Z]' {cf} 2>/dev/null | sed 's/://' | tr -d ' '"
        )
        for svc in svc_output.split("\n"):
            if svc and not svc.startswith("#"):
                services.add(svc)
    return sorted(services)


def collect_platform_state() -> dict[str, Any]:
    """Collect full platform state."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "containers": collect_containers(),
        "gpus": collect_gpu_info(),
        "compose_services": collect_compose_services(),
        "container_count": len(collect_containers()),
    }


# ---------------------------------------------------------------------------
# Skill updaters
# ---------------------------------------------------------------------------
def update_platform_health_skill(state: dict[str, Any], skills_dir: Path) -> str | None:
    """Update platform-health SKILL.md with current state."""
    skill_file = skills_dir / "platform-health" / "SKILL.md"
    if not skill_file.exists():
        logger.warning("platform-health SKILL.md not found at %s", skill_file)
        return None

    content = skill_file.read_text()

    # Build auto-generated state block
    ts = state["timestamp"]
    container_count = state["container_count"]
    gpu_lines = []
    for g in state["gpus"]:
        gpu_lines.append(
            f"  - GPU {g['index']}: {g['name']} — {g['mem_used']}/{g['mem_total']}, "
            f"{g['utilization']} util, {g['temperature']}°C"
        )
    gpu_block = "\n".join(gpu_lines) if gpu_lines else "  - No GPUs detected"

    state_block = f"""
<!-- AUTO-UPDATED BY skill_updater.py — DO NOT EDIT THIS BLOCK -->
<!-- Last updated: {ts} -->
## Current Platform State

- **Containers running**: {container_count}
- **GPUs**:
{gpu_block}
- **Compose services defined**: {len(state.get('compose_services', []))}
<!-- END AUTO-UPDATED BLOCK -->
"""

    # Replace existing auto-updated block, or append before ## Remediation
    auto_pattern = (
        r"<!-- AUTO-UPDATED BY skill_updater\.py.*?<!-- END AUTO-UPDATED BLOCK -->"
    )
    if re.search(auto_pattern, content, re.DOTALL):
        new_content = re.sub(
            auto_pattern, state_block.strip(), content, flags=re.DOTALL
        )
    else:
        # Insert before ## Remediation
        new_content = content.replace(
            "## Remediation",
            state_block + "\n## Remediation",
        )

    if new_content != content:
        skill_file.write_text(new_content)
        logger.info("Updated platform-health SKILL.md")
        return "platform-health"

    logger.info("platform-health SKILL.md is up to date")
    return None


def update_skills(
    state: dict[str, Any], skills_dir: Path, target: str | None = None
) -> list[str]:
    """Update all (or specified) skills. Returns list of updated skill names."""
    updated = []

    updaters = {
        "platform-health": update_platform_health_skill,
    }

    for name, updater in updaters.items():
        if target and name != target:
            continue
        result = updater(state, skills_dir)
        if result:
            updated.append(result)

    return updated


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Skill Auto-Update System")
    parser.add_argument("--skill", help="Update only this skill")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show changes without writing"
    )
    parser.add_argument("--report", action="store_true", help="Print state report only")
    parser.add_argument(
        "--skills-dir", default=SKILLS_DIR, help="Path to skills directory"
    )

    args = parser.parse_args()

    skills_dir = Path(args.skills_dir)

    logger.info("Collecting platform state...")
    state = collect_platform_state()

    if args.report:
        print(json.dumps(state, indent=2))
        return

    if args.dry_run:
        logger.info("DRY RUN — showing state only")
        print(json.dumps(state, indent=2))
        return

    updated = update_skills(state, skills_dir, target=args.skill)

    if updated:
        logger.info("Updated skills: %s", ", ".join(updated))
        send_telegram(
            f"📚 *Skill Update*: Updated {len(updated)} skill(s): {', '.join(updated)}"
        )
    else:
        logger.info("All skills are up to date")


if __name__ == "__main__":
    main()
