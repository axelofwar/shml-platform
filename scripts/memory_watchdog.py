#!/usr/bin/env python3
"""
Memory Watchdog
===============
Monitors system RAM and per-process memory to guard against leaks
from VS Code, Copilot Chat, and other non-training processes that
can cause OOM events during GPU training runs.

SAFE-MODE: This watchdog NEVER touches training processes.
           It only logs, alerts, and optionally suggests which
           non-essential processes to trim.

Usage:
    python scripts/memory_watchdog.py               # foreground
    python scripts/memory_watchdog.py --daemon       # background (nohup)
    python scripts/memory_watchdog.py --interval 30  # poll every 30s
    python scripts/memory_watchdog.py --alert-mb 10240  # alert when VSCode > 10 GB

Log:   /tmp/memory_watchdog.log
Alert: /tmp/memory_watchdog_alert.log
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    import psutil
except ImportError:
    print("ERROR: psutil not installed. Run: pip install psutil", file=sys.stderr)
    sys.exit(1)

# ── Constants ────────────────────────────────────────────────────────────────
LOG_FILE = Path("/tmp/memory_watchdog.log")
ALERT_FILE = Path("/tmp/memory_watchdog_alert.log")
STATS_FILE = Path("/tmp/memory_watchdog_stats.json")

# Process name patterns for each category
TRAINING_PATTERNS = [
    "autoresearch_face",
    "ray",
    "yolo",
    "train.py",
    "ultralytics",
]
VSCODE_PATTERNS = [
    "code",
    "electron",
    "vscode-server",
    ".vscode-server",
    "extensionHost",
    "node",  # VS Code node workers - filtered further by cmd
]
COPILOT_PATTERNS = [
    "copilot",
    "github-copilot",
    "copilot-language-server",
]
GPU_PATTERNS = [
    "nvidia-smi",
    "nvcc",
    "cuda",
]

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [memory-watchdog] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="a"),
    ],
)
logger = logging.getLogger("memory-watchdog")

alert_logger = logging.getLogger("memory-alert")
alert_handler = logging.FileHandler(ALERT_FILE, mode="a")
alert_handler.setFormatter(
    logging.Formatter("%(asctime)s ALERT %(message)s", "%Y-%m-%dT%H:%M:%S")
)
alert_logger.addHandler(alert_handler)
alert_logger.setLevel(logging.WARNING)


# ── Data structures ──────────────────────────────────────────────────────────
@dataclass
class ProcessInfo:
    pid: int
    name: str
    cmdline: str
    rss_mb: float
    vms_mb: float
    cpu_pct: float
    category: str


@dataclass
class MemorySnapshot:
    timestamp: str
    total_ram_gb: float
    used_ram_gb: float
    available_ram_gb: float
    used_pct: float
    swap_used_gb: float
    swap_pct: float
    by_category: Dict[str, float] = field(default_factory=dict)   # category → RSS MB
    top_procs: List[ProcessInfo] = field(default_factory=list)
    training_safe: bool = True  # always True — we never disturb training


# ── Process categorization ───────────────────────────────────────────────────
def _matches(cmdline: str, patterns: List[str]) -> bool:
    cmdl = cmdline.lower()
    return any(p.lower() in cmdl for p in patterns)


def categorize(proc: psutil.Process) -> Optional[str]:
    """
    Returns category string or None if process can't be read.
    Categories: training | vscode | copilot | gpu | other
    """
    try:
        cmdline = " ".join(proc.cmdline())
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return None

    if _matches(cmdline, TRAINING_PATTERNS):
        return "training"
    if _matches(cmdline, COPILOT_PATTERNS):
        return "copilot"
    # VS Code: match "code" or "electron" but only if path contains ".vscode"
    if _matches(cmdline, [".vscode", "vscode", "Code/resources"]):
        return "vscode"
    if _matches(cmdline, GPU_PATTERNS):
        return "gpu"
    return "other"


def collect_processes() -> List[ProcessInfo]:
    procs = []
    for proc in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
        try:
            info = proc.info
            category = categorize(proc)
            if category is None:
                continue
            mem = proc.memory_info()
            cpu = proc.cpu_percent(interval=None)
            cmdline = " ".join(info.get("cmdline") or [])
            procs.append(
                ProcessInfo(
                    pid=info["pid"],
                    name=info["name"] or "",
                    cmdline=cmdline[:200],
                    rss_mb=mem.rss / 1024**2,
                    vms_mb=mem.vms / 1024**2,
                    cpu_pct=cpu,
                    category=category,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return procs


def snapshot(top_n: int = 10) -> MemorySnapshot:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    procs = collect_processes()

    by_category: Dict[str, float] = {}
    for p in procs:
        by_category[p.category] = by_category.get(p.category, 0.0) + p.rss_mb

    top_procs = sorted(procs, key=lambda x: x.rss_mb, reverse=True)[:top_n]

    return MemorySnapshot(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        total_ram_gb=vm.total / 1024**3,
        used_ram_gb=vm.used / 1024**3,
        available_ram_gb=vm.available / 1024**3,
        used_pct=vm.percent,
        swap_used_gb=sw.used / 1024**3,
        swap_pct=sw.percent,
        by_category=by_category,
        top_procs=top_procs,
        training_safe=True,
    )


# ── Alerting ─────────────────────────────────────────────────────────────────
def check_alerts(
    snap: MemorySnapshot,
    vscode_alert_mb: float,
    ram_alert_pct: float,
    swap_alert_gb: float,
) -> List[str]:
    alerts = []

    vscode_mb = snap.by_category.get("vscode", 0.0)
    copilot_mb = snap.by_category.get("copilot", 0.0)
    vscode_total = vscode_mb + copilot_mb

    if vscode_total > vscode_alert_mb:
        alerts.append(
            f"VSCode+Copilot memory = {vscode_total/1024:.1f} GB "
            f"(threshold={vscode_alert_mb/1024:.1f} GB). "
            f"Consider restarting VS Code if training is near OOM."
        )

    if snap.used_pct > ram_alert_pct:
        training_mb = snap.by_category.get("training", 0.0)
        alerts.append(
            f"System RAM at {snap.used_pct:.1f}% used "
            f"({snap.used_ram_gb:.1f}/{snap.total_ram_gb:.1f} GB). "
            f"Training = {training_mb/1024:.1f} GB RSS. "
            f"Available = {snap.available_ram_gb:.1f} GB."
        )

    if snap.swap_used_gb > swap_alert_gb:
        alerts.append(
            f"Swap usage = {snap.swap_used_gb:.2f} GB (threshold={swap_alert_gb:.1f} GB). "
            f"Training may be generating swap I/O — check GPU mem pressure."
        )

    return alerts


def log_snapshot(snap: MemorySnapshot, verbose: bool = False) -> None:
    training_gb = snap.by_category.get("training", 0) / 1024
    vscode_gb = (
        snap.by_category.get("vscode", 0) + snap.by_category.get("copilot", 0)
    ) / 1024
    other_gb = snap.by_category.get("other", 0) / 1024

    logger.info(
        f"RAM {snap.used_pct:.0f}% "
        f"({snap.used_ram_gb:.1f}/{snap.total_ram_gb:.1f} GB) | "
        f"avail={snap.available_ram_gb:.1f} GB | "
        f"swap={snap.swap_used_gb:.2f} GB | "
        f"training={training_gb:.1f} GB | "
        f"vscode+copilot={vscode_gb:.1f} GB | "
        f"other={other_gb:.1f} GB"
    )

    if verbose and snap.top_procs:
        logger.info("Top processes by RSS:")
        for p in snap.top_procs[:5]:
            logger.info(
                f"  [{p.category:8s}] pid={p.pid} {p.name:<20s} "
                f"rss={p.rss_mb/1024:.2f} GB"
            )

    # Write JSON stats for external consumers (grafana, agent, etc.)
    try:
        stats = {
            "timestamp": snap.timestamp,
            "ram_used_pct": round(snap.used_pct, 1),
            "ram_used_gb": round(snap.used_ram_gb, 2),
            "ram_available_gb": round(snap.available_ram_gb, 2),
            "swap_used_gb": round(snap.swap_used_gb, 3),
            "by_category_gb": {
                k: round(v / 1024, 3) for k, v in snap.by_category.items()
            },
            "training_safe": snap.training_safe,
        }
        STATS_FILE.write_text(json.dumps(stats, indent=2))
    except Exception:
        pass


# ── Main loop ────────────────────────────────────────────────────────────────
def run_watchdog(
    interval: int = 60,
    vscode_alert_mb: float = 10 * 1024,   # 10 GB
    ram_alert_pct: float = 88.0,
    swap_alert_gb: float = 2.0,
    verbose_every: int = 5,               # log verbose every N intervals
    once: bool = False,
) -> None:
    logger.info(
        f"Memory watchdog started | interval={interval}s | "
        f"vscode_alert={vscode_alert_mb/1024:.0f}GB | "
        f"ram_alert={ram_alert_pct:.0f}% | "
        f"training_safe=ALWAYS"
    )
    consecutive_alerts = 0
    tick = 0

    while True:
        try:
            snap = snapshot(top_n=10)
            log_snapshot(snap, verbose=(tick % verbose_every == 0))

            alerts = check_alerts(
                snap,
                vscode_alert_mb=vscode_alert_mb,
                ram_alert_pct=ram_alert_pct,
                swap_alert_gb=swap_alert_gb,
            )

            if alerts:
                consecutive_alerts += 1
                for alert in alerts:
                    alert_logger.warning(alert)
                    if consecutive_alerts >= 3:
                        # Escalate — log louder
                        logger.warning(f"[ALERT x{consecutive_alerts}] {alert}")
            else:
                consecutive_alerts = 0

        except Exception as e:
            logger.error(f"Watchdog cycle error: {e}", exc_info=False)

        if once:
            return

        tick += 1
        time.sleep(interval)


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="SHML Memory Watchdog")
    parser.add_argument("--interval", type=int, default=60,
                        help="Poll interval in seconds (default: 60)")
    parser.add_argument("--alert-mb", type=float, default=10240,
                        help="VSCode+Copilot RSS alert threshold in MB (default: 10240 = 10GB)")
    parser.add_argument("--ram-pct", type=float, default=88.0,
                        help="System RAM %% alert threshold (default: 88)")
    parser.add_argument("--swap-gb", type=float, default=2.0,
                        help="Swap usage alert threshold in GB (default: 2.0)")
    parser.add_argument("--verbose-every", type=int, default=5,
                        help="Print top-procs every N intervals (default: 5)")
    parser.add_argument("--daemon", action="store_true",
                        help="Detach and run as daemon (writes to log file)")
    parser.add_argument("--once", action="store_true",
                        help="Run a single snapshot + alert pass, then exit")
    args = parser.parse_args()

    if args.daemon and args.once:
        parser.error("--daemon and --once are mutually exclusive")

    if args.daemon:
        # Double-fork to detach
        if os.fork() > 0:
            sys.exit(0)
        os.setsid()
        if os.fork() > 0:
            sys.exit(0)
        # Redirect stdin/stdout/stderr
        sys.stdin = open(os.devnull, "r")
        sys.stdout.flush()
        sys.stderr.flush()
        with open(LOG_FILE, "a") as lf:
            os.dup2(lf.fileno(), sys.stdout.fileno())
            os.dup2(lf.fileno(), sys.stderr.fileno())
        print(f"Memory watchdog daemon started (pid={os.getpid()})", flush=True)

    run_watchdog(
        interval=args.interval,
        vscode_alert_mb=args.alert_mb,
        ram_alert_pct=args.ram_pct,
        swap_alert_gb=args.swap_gb,
        verbose_every=args.verbose_every,
        once=args.once,
    )


if __name__ == "__main__":
    main()
