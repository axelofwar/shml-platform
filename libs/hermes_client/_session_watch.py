"""Live session watcher: tail a Hermes session JSON and render it like hermes chat.

Renders messages using Rich with the same aesthetic as the Hermes terminal:
  - User: dim box header
  - Assistant: rich Markdown inside a styled panel
  - Tool calls: yellow ⚡ name(args)
  - Tool results: cyan → preview

Usage:
    from libs.hermes_client._session_watch import watch_session
    watch_session()  # auto-detects newest session

CLI:
    python3 -m libs.hermes_client jobs watch [SESSION_ID] [--job JOB_ID]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
HERMES_HOME = Path.home() / ".hermes"
SESSIONS_DIR = HERMES_HOME / "sessions"


# ---------------------------------------------------------------------------
# Rich imports — available in the hermes venv and most system pythons
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.text import Text
    from rich.rule import Rule
    _RICH = True
except ImportError:
    _RICH = False


console = Console(highlight=False) if _RICH else None


def _plain_print(*args: object, **kw: object) -> None:
    print(*args, **kw)


def _render_user(text: str) -> None:
    if _RICH and console:
        console.print(Rule(f"[dim]👤 user[/dim]", style="dim blue"))
        console.print(Text(text, style="bright_white"))
    else:
        _plain_print(f"\n--- user ---\n{text}")


def _render_assistant(text: str) -> None:
    if _RICH and console:
        console.print(Rule(f"[bold green]⚕ Hermes[/bold green]", style="green"))
        try:
            console.print(Markdown(text))
        except Exception:
            console.print(text)
    else:
        _plain_print(f"\n--- hermes ---\n{text}")


def _render_tool_call(call: dict) -> None:
    name = call.get("function", {}).get("name", "?")
    raw_args = call.get("function", {}).get("arguments", "")
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        args_str = json.dumps(args, separators=(",", ":"))[:200]
    except Exception:
        args_str = str(raw_args)[:200]
    if _RICH and console:
        console.print(f"  [yellow]⚡[/yellow] [bold yellow]{name}[/bold yellow]([dim]{args_str}[/dim])")
    else:
        _plain_print(f"  ⚡ {name}({args_str})")


def _render_tool_result(content: str) -> None:
    preview = content[:400].replace("\n", "↵ ") if content else "(empty)"
    if _RICH and console:
        console.print(f"  [cyan]→[/cyan] [dim]{preview}[/dim]")
    else:
        _plain_print(f"  → {preview}")


def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                parts.append(p.get("text", ""))
            else:
                parts.append(str(p))
        return "".join(parts)
    return str(content) if content else ""


def _render_message(msg: dict, idx: int) -> None:
    role = msg.get("role", "unknown")
    content = _extract_text(msg.get("content", ""))
    tool_calls = msg.get("tool_calls") or []
    tool_call_id = msg.get("tool_call_id", "")

    if role == "user" and content:
        _render_user(content)
    elif role == "assistant":
        if content:
            _render_assistant(content)
        for tc in tool_calls:
            _render_tool_call(tc)
    elif role == "tool":
        _render_tool_result(content)
    # system messages: skip (too verbose)


def _load_session(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _find_session_for_job(job_id: str) -> Optional[Path]:
    """Match session_YYYYMMDD_HHMMSS to job_id YYYYMMDD_HHMMSS prefix."""
    prefix = job_id[:15]  # YYYYMMDD_HHMMSS
    for f in SESSIONS_DIR.glob("session_*.json"):
        if prefix in f.name:
            return f
    return None


def _newest_session() -> Optional[Path]:
    sessions = sorted(SESSIONS_DIR.glob("session_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return sessions[0] if sessions else None


def watch_session(
    session_id: Optional[str] = None,
    job_id: Optional[str] = None,
    poll_interval: float = 0.8,
    stop_on_job_done: bool = True,
) -> None:
    """Watch a Hermes session file and render new messages in real-time.

    Args:
        session_id: Explicit session ID to watch (e.g. 20260417_150634_d7bb88).
        job_id: If given, auto-detect session from job timestamp.
        poll_interval: Seconds between polls.
        stop_on_job_done: Stop when job status changes to completed/failed.
    """
    # Resolve session path
    session_path: Optional[Path] = None
    if session_id:
        candidates = [
            SESSIONS_DIR / f"session_{session_id}.json",
            SESSIONS_DIR / f"{session_id}.json",
            Path(session_id) if os.sep in session_id else None,
        ]
        for c in candidates:
            if c and c.exists():
                session_path = c
                break
        if not session_path:
            # Try prefix match
            for f in SESSIONS_DIR.glob(f"session_{session_id}*.json"):
                session_path = f
                break
    elif job_id:
        session_path = _find_session_for_job(job_id)
    if not session_path:
        session_path = _newest_session()

    if not session_path or not session_path.exists():
        print("No session file found.", file=sys.stderr)
        return

    if _RICH and console:
        console.print(f"\n[bold blue]🔍 Watching session:[/bold blue] [dim]{session_path.name}[/dim]")
        console.print("[dim]Press Ctrl-C to stop.[/dim]\n")
    else:
        print(f"\nWatching: {session_path.name}\nPress Ctrl-C to stop.\n")

    seen_count = 0
    job_state_file: Optional[Path] = None

    # Resolve job state file for stop-on-done
    if stop_on_job_done and job_id:
        from ._jobs import JOBS_DIR
        job_state_file = JOBS_DIR / job_id / "state.json"

    try:
        while True:
            data = _load_session(session_path)
            if data:
                messages = data.get("messages", [])
                new_msgs = messages[seen_count:]
                for i, msg in enumerate(new_msgs, seen_count):
                    _render_message(msg, i)
                seen_count = len(messages)

            # Check if job is done
            if job_state_file and job_state_file.exists():
                try:
                    state = json.loads(job_state_file.read_text())
                    status = state.get("status", "")
                    if status in ("completed", "failed", "interrupted", "timeout"):
                        if _RICH and console:
                            console.print(f"\n[bold]Job {status}.[/bold]")
                        else:
                            print(f"\nJob {status}.")
                        break
                except Exception:
                    pass

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        if _RICH and console:
            console.print("\n[dim]Stopped.[/dim]")
        else:
            print("\nStopped.")
