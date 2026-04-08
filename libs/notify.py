"""
Shared Telegram notification utility for SHML platform.

Centralises the send_telegram() pattern that was duplicated across watchdog,
training_pipeline, host_process_guard, skill_updater, etc.

Usage:
    from libs.notify import send_telegram

    send_telegram("🔬 Research discovery found 3 new papers")
    send_telegram("🧠 GEPA evolved 2 skills", parse_mode="HTML")

Environment variables (must be set — no fallback defaults):
    TELEGRAM_BOT_TOKEN  — Bot API token
    TELEGRAM_CHAT_ID    — Target chat/group ID
"""
from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(
    message: str,
    *,
    parse_mode: str = "Markdown",
    disable_notification: bool = False,
) -> bool:
    """Send a Telegram message (best-effort, never raises).

    Returns True if the message was sent successfully, False otherwise.
    """
    token = _BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = _CHAT_ID or os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.debug("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing)")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_notification": str(disable_notification).lower(),
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning("Telegram send failed: %s", e)
        return False


def send_mr_ready_notification(
    mr_url: str,
    title: str,
    issue_iid: int,
    *,
    project_name: str = "shml-platform",
    summary: str = "",
) -> bool:
    """Notify Telegram when an agent MR is ready for human review.

    Returns True if the message was sent successfully.
    """
    lines = [
        "🔍 <b>Agent MR — Ready for Review</b>",
        f"<b>Project:</b> {project_name}",
        f"<b>Title:</b> {title}",
        f"<b>Issue:</b> #{issue_iid}",
    ]
    if summary:
        lines.append(f"<b>Summary:</b> {summary}")
    lines.append(f"<b>Review:</b> <a href=\"{mr_url}\">{mr_url}</a>")

    return send_telegram("\n".join(lines), parse_mode="HTML")
