#!/usr/bin/env python3
"""
host_process_guard.py — psutil-based memory leak guard for host processes.

Monitors VSCode, Python training processes, and other long-running host
processes for memory growth. Sends Telegram alerts and creates GitLab issues
when thresholds are exceeded.

Called by watchdog.sh (or directly via systemd) on each watchdog cycle.

Usage:
    python3 host_process_guard.py [--state-dir PATH] [--threshold-mb N]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import psutil
except ImportError:
    print("WARN: psutil not available — skipping host process guard", file=sys.stderr)
    sys.exit(0)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_STATE_DIR = os.environ.get("STATE_DIR", "/tmp/shml-watchdog/host-process-guard")
DEFAULT_THRESHOLD_MB = int(os.environ.get("HOST_PROCESS_LEAK_THRESHOLD_MB", "500"))
DEFAULT_BASELINE_SECS = int(os.environ.get("HOST_PROCESS_BASELINE_SECS", "1800"))  # 30 min

# Process name patterns to watch: (pattern, display_name, alert_threshold_mb_per_hr)
WATCHED_PATTERNS = [
    ("code",         "VSCode",            DEFAULT_THRESHOLD_MB),
    ("electron",     "VSCode/Electron",   DEFAULT_THRESHOLD_MB),
    ("python",       "Python/Training",   DEFAULT_THRESHOLD_MB * 2),  # training uses more
    ("ray",          "Ray Worker",        DEFAULT_THRESHOLD_MB * 2),
    ("node",         "Node.js",           DEFAULT_THRESHOLD_MB),
]

# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state(state_path: Path) -> dict:
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except Exception:
            pass
    return {}


def save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Process scanning
# ---------------------------------------------------------------------------

def gather_process_memory() -> dict[str, dict]:
    """Collect total RSS memory for each watched process group (by name pattern)."""
    totals: dict[str, dict] = {}
    now = time.time()

    for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info", "status"]):
        try:
            if proc.info["status"] in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                continue
            name = (proc.info["name"] or "").lower()
            cmdline = " ".join(proc.info["cmdline"] or []).lower()
            rss_mb = (proc.info["memory_info"].rss // (1024 * 1024)) if proc.info["memory_info"] else 0

            for pattern, display, threshold in WATCHED_PATTERNS:
                if pattern in name or pattern in cmdline:
                    key = display
                    if key not in totals:
                        totals[key] = {"rss_mb": 0, "pids": [], "threshold_mb_per_hr": threshold, "ts": now}
                    totals[key]["rss_mb"] += rss_mb
                    totals[key]["pids"].append(proc.info["pid"])
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return totals


# ---------------------------------------------------------------------------
# Alert helpers (uses Telegram env vars set by watchdog environment)
# ---------------------------------------------------------------------------

def send_telegram(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print(f"TELEGRAM_UNAVAIL: {message[:120]}", file=sys.stderr)
        return
    import urllib.request
    import urllib.parse
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message, "parse_mode": "HTML"}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=8):
            pass
    except Exception as e:
        print(f"TELEGRAM_ERR: {e}", file=sys.stderr)


def create_gitlab_issue(title: str, body: str) -> None:
    token = os.environ.get("GITLAB_AXELOFWAR_PERSONAL_ACCESS_TOKEN") or os.environ.get("GITLAB_API_TOKEN", "")
    api_url = os.environ.get("GITLAB_API_URL", "http://shml-gitlab:8929/gitlab/api/v4")
    project_id = os.environ.get("GITLAB_PROJECT_ID", "2")
    if not token:
        print(f"GITLAB_UNAVAIL: would create issue: {title}", file=sys.stderr)
        return
    import urllib.request
    import urllib.parse
    url = f"{api_url}/projects/{project_id}/issues"
    payload = json.dumps({
        "title": title,
        "description": body,
        "labels": "type::bug,priority::high,status::todo,source::watchdog,component::infra",
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"},
                                  method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        print(f"GITLAB_ERR: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Host process memory leak guard")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    parser.add_argument("--threshold-mb", type=int, default=DEFAULT_THRESHOLD_MB)
    parser.add_argument("--baseline-secs", type=int, default=DEFAULT_BASELINE_SECS)
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "process_memory.json"

    now = time.time()
    current = gather_process_memory()

    if not current:
        print("INFO: No watched processes found on host")
        return 0

    previous = load_state(state_path)
    leaks_found = 0

    for name, info in current.items():
        rss_mb = info["rss_mb"]
        threshold = info["threshold_mb_per_hr"]
        pid_count = len(info["pids"])

        prev = previous.get(name)
        if prev:
            elapsed = now - prev["ts"]
            if elapsed >= args.baseline_secs:
                growth = rss_mb - prev["rss_mb"]
                growth_per_hr = int(growth * 3600 / elapsed) if elapsed > 0 else 0

                if growth_per_hr > threshold:
                    leaks_found += 1
                    msg = (f"⚠️ <b>Host Process Memory Leak</b>: <code>{name}</code>\n"
                           f"Growth: <b>{growth_per_hr} MB/hr</b> (threshold: {threshold} MB/hr)\n"
                           f"RSS: {prev['rss_mb']} MB → {rss_mb} MB over {int(elapsed/60)}min\n"
                           f"PIDs: {pid_count}")
                    print(f"LEAK: {name}: {growth_per_hr} MB/hr (was {prev['rss_mb']} MB, now {rss_mb} MB)")
                    send_telegram(msg)
                    create_gitlab_issue(
                        f"Host Memory Leak: {name}",
                        f"Host process `{name}` is leaking memory.\n\n"
                        f"Growth: {growth_per_hr} MB/hr (threshold: {threshold} MB/hr)\n"
                        f"RSS: {prev['rss_mb']} MB → {rss_mb} MB over {int(elapsed/60)} min\n"
                        f"Active PIDs: {pid_count}\n\n"
                        f"Detected by host_process_guard.py at {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"
                    )
                else:
                    print(f"OK: {name}: {rss_mb} MB RSS ({pid_count} pids), growth={growth_per_hr} MB/hr")
        else:
            print(f"BASELINE: {name}: {rss_mb} MB RSS ({pid_count} pids) — establishing baseline")

        # Update state
        previous[name] = {"ts": now, "rss_mb": rss_mb, "pids": info["pids"]}

    save_state(state_path, previous)
    return 1 if leaks_found > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
