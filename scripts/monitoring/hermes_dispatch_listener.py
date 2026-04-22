#!/usr/bin/env python3
"""Bidirectional Telegram ↔ Hermes dispatch listener (issue #564).

Long-polls Telegram getUpdates for messages from a single allow-listed chat
(TELEGRAM_DISPATCH_CHAT_ID, falling back to TELEGRAM_CHAT_ID) and routes them
to either a fast synchronous handler (status/gpu/issue/ping) or a background
worker that dispatches a free-form prompt to the Hermes CLI.

Security model
--------------
- Only messages whose `message.chat.id` matches the allow-listed ID are
  processed. Everything else is silently dropped (no reply, no log spam).
- Responses go back via `send_telegram_reply(chat_id, ...)` so they land in
  the originating private chat, never in the shared announcement channel.
- No credentials embedded: TELEGRAM_BOT_TOKEN loaded from environment only.

Run
---
    python3 scripts/monitoring/hermes_dispatch_listener.py

Or via systemd (see deploy/systemd/shml-hermes-dispatch-listener.service).
"""
from __future__ import annotations

import json
import logging
import os
import queue
import shlex
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))

from libs.notify import send_telegram_reply  # noqa: E402

logging.basicConfig(
    level=os.environ.get("HERMES_DISPATCH_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [dispatch-listener] %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_DISPATCH_CHAT_ID") or os.environ.get(
    "TELEGRAM_CHAT_ID", ""
)
HERMES_BIN = Path(
    os.environ.get(
        "HERMES_BIN",
        Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "hermes",
    )
)
ALLOW_FREEFORM = os.environ.get("HERMES_TG_ALLOW_FREEFORM", "1") == "1"
FREEFORM_TIMEOUT = int(os.environ.get("HERMES_TG_FREEFORM_TIMEOUT_S", "300"))
POLL_LONG_TIMEOUT = int(os.environ.get("HERMES_TG_POLL_TIMEOUT_S", "25"))
# Emit a heartbeat log line this often so operators can distinguish
# "healthy + idle" from "wedged" at a glance. Default: every 5 minutes.
HEARTBEAT_INTERVAL_S = int(os.environ.get("HERMES_TG_HEARTBEAT_S", "300"))
TELEGRAM_API = "https://api.telegram.org"
STATE_PATH = Path(
    os.environ.get(
        "HERMES_TG_STATE_PATH",
        PLATFORM_ROOT / ".cache" / "hermes_dispatch_listener_offset.json",
    )
)

_freeform_q: "queue.Queue[tuple[int, str]]" = queue.Queue()
_stop_event = threading.Event()


# ---------------------------------------------------------------------------
# Offset persistence (so we don't re-process after a restart)
# ---------------------------------------------------------------------------
def _load_offset() -> int:
    try:
        data = json.loads(STATE_PATH.read_text())
        return int(data.get("offset", 0))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return 0


def _save_offset(offset: int) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"offset": offset}))
    except OSError as e:
        logger.warning("Failed to persist offset: %s", e)


# ---------------------------------------------------------------------------
# Telegram API helpers
# ---------------------------------------------------------------------------
def _tg_get(method: str, params: dict[str, Any], timeout: int = 30) -> dict:
    url = f"{TELEGRAM_API}/bot{BOT_TOKEN}/{method}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _reply(chat_id: int, text: str, *, parse_mode: str = "Markdown") -> None:
    # Retry on transient Telegram API hiccups (connection resets, 502s).
    # Telegram edge has been observed to flake for ~30-60s at a stretch.
    attempts = int(os.environ.get("HERMES_TG_REPLY_RETRIES", "5"))
    delay = 1.0
    for attempt in range(1, attempts + 1):
        if send_telegram_reply(chat_id, text, parse_mode=parse_mode):
            if attempt > 1:
                logger.info("reply to chat_id=%s succeeded on attempt %d", chat_id, attempt)
            return
        if attempt < attempts:
            time.sleep(delay)
            delay = min(delay * 2, 15.0)
    logger.warning("reply to chat_id=%s failed after %d attempts", chat_id, attempts)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
HELP_TEXT = """*Hermes dispatch — available commands*

- `@hermes help` — show this message
- `@hermes ping` — liveness check
- `@hermes status` — platform snapshot (containers, GPU, disk)
- `@hermes gpu` — nvidia-smi summary
- `@hermes issue: <title>` — create a GitLab issue (assignee::agent)
- any free-form text — dispatched to Hermes CLI, response sent when done
"""


def _handle_ping(chat_id: int, _args: str) -> None:
    _reply(chat_id, "pong")


def _handle_help(chat_id: int, _args: str) -> None:
    _reply(chat_id, HELP_TEXT)


def _handle_status(chat_id: int, _args: str) -> None:
    lines = ["*Platform status*"]
    try:
        ps = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        names = [ln for ln in ps.stdout.strip().splitlines() if ln]
        unhealthy = [ln for ln in names if "unhealthy" in ln.lower()]
        lines.append(f"- containers: {len(names)} running, {len(unhealthy)} unhealthy")
        if unhealthy:
            for ln in unhealthy[:5]:
                lines.append(f"  - {ln}")
    except Exception as e:
        lines.append(f"- containers: error ({e})")

    try:
        gpu = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        for ln in gpu.stdout.strip().splitlines():
            parts = [p.strip() for p in ln.split(",")]
            if len(parts) == 5:
                name, used, total, util, temp = parts
                lines.append(f"- gpu: {name} — {used}/{total} MiB, {util}% util, {temp}°C")
    except FileNotFoundError:
        lines.append("- gpu: nvidia-smi not found")
    except Exception as e:
        lines.append(f"- gpu: error ({e})")

    try:
        df = subprocess.run(
            ["df", "-h", "/"], capture_output=True, text=True, timeout=5, check=False,
        )
        root_line = df.stdout.strip().splitlines()[-1] if df.stdout else ""
        if root_line:
            lines.append(f"- disk: `{root_line}`")
    except Exception as e:
        lines.append(f"- disk: error ({e})")

    _reply(chat_id, "\n".join(lines))


def _handle_gpu(chat_id: int, _args: str) -> None:
    try:
        out = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=10, check=False,
        )
        payload = out.stdout[:3500] or out.stderr[:1000] or "(no output)"
        _reply(chat_id, f"```\n{payload}\n```")
    except FileNotFoundError:
        _reply(chat_id, "nvidia-smi not installed on this host")
    except Exception as e:
        _reply(chat_id, f"gpu error: {e}")


def _handle_issue(chat_id: int, args: str) -> None:
    title = args.strip()
    if not title:
        _reply(chat_id, "usage: `@hermes issue: <title>`")
        return
    token = os.environ.get("GITLAB_API_TOKEN", "")
    if not token:
        _reply(chat_id, "GITLAB_API_TOKEN not set — cannot create issue")
        return
    try:
        ip = subprocess.check_output(
            [
                "docker", "inspect",
                os.environ.get("PLATFORM_PREFIX", "shml") + "-gitlab",
                "--format",
                '{{(index .NetworkSettings.Networks "shml-platform").IPAddress}}',
            ], text=True, timeout=5,
        ).strip()
    except Exception as e:
        _reply(chat_id, f"cannot resolve shml-gitlab container: {e}")
        return

    body = (
        "## Created from Telegram dispatch\n\n"
        f"_title was provided by the user via `@hermes issue:` command._\n\n"
        f"- Source chat: `{chat_id}`\n"
        f"- Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
    )
    params = urllib.parse.urlencode({
        "title": title,
        "description": body,
        "labels": "source::telegram,assignee::agent,status::backlog,priority::low",
    })
    url = f"http://{ip}:8929/gitlab/api/v4/projects/shml%2Fplatform/issues?{params}"
    try:
        req = urllib.request.Request(
            url, headers={"PRIVATE-TOKEN": token}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        iid = data["iid"]
        web = data["web_url"]
        _reply(chat_id, f"✅ created #{iid}: [{title}]({web})")
    except urllib.error.HTTPError as e:
        _reply(chat_id, f"gitlab API error: {e.code} {e.reason}")
    except Exception as e:
        _reply(chat_id, f"issue creation failed: {e}")


def _handle_freeform(chat_id: int, text: str) -> None:
    if not ALLOW_FREEFORM:
        _reply(chat_id, "free-form dispatch disabled (set `HERMES_TG_ALLOW_FREEFORM=1`)")
        return
    if not HERMES_BIN.exists():
        _reply(chat_id, f"hermes CLI not found at `{HERMES_BIN}`")
        return
    _freeform_q.put((chat_id, text))
    _reply(chat_id, f"🧠 queued for hermes (timeout {FREEFORM_TIMEOUT}s) — I'll reply when done")


COMMANDS = {
    "ping": _handle_ping,
    "help": _handle_help,
    "status": _handle_status,
    "gpu": _handle_gpu,
    "issue": _handle_issue,  # form: "@hermes issue: <title>"
}


# ---------------------------------------------------------------------------
# Worker: free-form dispatch via hermes CLI
# ---------------------------------------------------------------------------
def _freeform_worker() -> None:
    while not _stop_event.is_set():
        try:
            chat_id, prompt = _freeform_q.get(timeout=1.0)
        except queue.Empty:
            continue
        start = time.time()
        try:
            proc = subprocess.run(
                [str(HERMES_BIN), "chat", "--yolo", "-q", prompt],
                cwd=str(PLATFORM_ROOT),
                capture_output=True, text=True,
                timeout=FREEFORM_TIMEOUT,
                env={**os.environ, "TERM": "dumb"},
                check=False,
            )
            duration = time.time() - start
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            if proc.returncode == 0 and out:
                preview = out if len(out) <= 3500 else out[:3500] + "\n…(truncated)"
                _reply(
                    chat_id,
                    f"✅ hermes done ({duration:.1f}s)\n```\n{preview}\n```",
                )
            else:
                tail = (err or out or "(no output)")[-1500:]
                _reply(
                    chat_id,
                    f"❌ hermes exit={proc.returncode} ({duration:.1f}s)\n```\n{tail}\n```",
                )
        except subprocess.TimeoutExpired:
            _reply(chat_id, f"⏱ hermes exceeded {FREEFORM_TIMEOUT}s — aborted")
        except Exception as e:
            logger.exception("freeform worker error")
            _reply(chat_id, f"worker error: {e}")
        finally:
            _freeform_q.task_done()


# ---------------------------------------------------------------------------
# Command routing
# ---------------------------------------------------------------------------
def _route_message(chat_id: int, text: str) -> None:
    body = text.strip()
    if body.lower().startswith("@hermes"):
        body = body[len("@hermes"):].lstrip(" :,-")
    if not body:
        COMMANDS["help"](chat_id, "")
        return

    first = body.split(None, 1)
    cmd = first[0].lower().rstrip(":")
    rest = first[1] if len(first) > 1 else ""

    handler = COMMANDS.get(cmd)
    if handler is not None:
        try:
            handler(chat_id, rest)
        except Exception as e:
            logger.exception("handler %s crashed", cmd)
            _reply(chat_id, f"handler `{cmd}` crashed: {e}")
        return

    _handle_freeform(chat_id, body)


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------
def _handle_signal(signum, _frame) -> None:  # noqa: ANN001
    logger.info("signal %s received — stopping", signum)
    _stop_event.set()


def main() -> int:
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN missing; nothing to do")
        return 2
    if not ALLOWED_CHAT_ID:
        logger.error(
            "TELEGRAM_DISPATCH_CHAT_ID (or TELEGRAM_CHAT_ID fallback) missing; refusing to start"
        )
        return 2

    try:
        allowed = int(ALLOWED_CHAT_ID)
    except ValueError:
        logger.error("allowed chat id is not an int: %r", ALLOWED_CHAT_ID)
        return 2

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    me = _tg_get("getMe", {})
    if not me.get("ok"):
        logger.error("getMe failed: %s", me)
        return 3
    bot = me["result"]
    logger.info(
        "listening as @%s (id=%s), allowlist=[%s], freeform=%s, hermes=%s",
        bot.get("username"), bot.get("id"), allowed, ALLOW_FREEFORM, HERMES_BIN,
    )

    worker = threading.Thread(target=_freeform_worker, daemon=True, name="freeform")
    worker.start()

    offset = _load_offset()
    backoff = 1.0
    last_heartbeat = time.monotonic()
    polls_since_heartbeat = 0
    messages_since_heartbeat = 0
    while not _stop_event.is_set():
        try:
            resp = _tg_get(
                "getUpdates",
                {"offset": offset, "timeout": POLL_LONG_TIMEOUT,
                 "allowed_updates": json.dumps(["message"])},
                timeout=POLL_LONG_TIMEOUT + 10,
            )
            backoff = 1.0
            polls_since_heartbeat += 1
        except urllib.error.URLError as e:
            logger.warning("getUpdates network error: %s — backoff=%.1fs", e, backoff)
            _stop_event.wait(backoff)
            backoff = min(backoff * 2, 30.0)
            continue
        except Exception as e:
            logger.warning("getUpdates error: %s — backoff=%.1fs", e, backoff)
            _stop_event.wait(backoff)
            backoff = min(backoff * 2, 30.0)
            continue

        if not resp.get("ok"):
            logger.warning("getUpdates not ok: %s", resp)
            _stop_event.wait(5)
            continue

        for update in resp.get("result", []):
            offset = max(offset, update["update_id"] + 1)
            msg = update.get("message") or {}
            chat = msg.get("chat") or {}
            chat_id = chat.get("id")
            text = msg.get("text") or ""
            if chat_id != allowed:
                logger.debug("rejected message from chat_id=%s (not allowlisted)", chat_id)
                continue
            if not text:
                continue
            logger.info("accepted msg from chat_id=%s: %r", chat_id, text[:100])
            messages_since_heartbeat += 1
            try:
                _route_message(chat_id, text)
            except Exception:
                logger.exception("route_message crashed")
        _save_offset(offset)

        now = time.monotonic()
        if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
            logger.info(
                "heartbeat: alive, offset=%s, polls=%d, messages=%d, freeform_queue=%d",
                offset, polls_since_heartbeat, messages_since_heartbeat,
                _freeform_q.qsize(),
            )
            last_heartbeat = now
            polls_since_heartbeat = 0
            messages_since_heartbeat = 0

    logger.info("shutdown clean; offset=%s", offset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
