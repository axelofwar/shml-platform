"""
Message Compaction Hierarchy — P1 improvement.

Three-tier compaction to keep context within LLM token budget:
1. Microcompact: Deduplicate repeated tool results and identical messages
2. Snip: Drop old messages, protect recent tail (last N messages)
3. Summarize: LLM-based compression of old context into a single summary

Usage:
    from .compaction import compact_messages
    messages = compact_messages(state['messages'], max_chars=80000)
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Tier 1: Microcompact (deduplication) ──────────────────────────────────────

def _content_hash(msg: dict[str, Any]) -> str:
    """Deterministic hash of a message's content for dedup."""
    content = msg.get("content", "")
    role = msg.get("role", "")
    return hashlib.md5(f"{role}:{content}".encode()).hexdigest()


def microcompact(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate messages (same role+content). Keeps first occurrence."""
    seen: set[str] = set()
    deduped = []
    removed = 0
    for msg in messages:
        h = _content_hash(msg)
        if h in seen:
            removed += 1
            continue
        seen.add(h)
        deduped.append(msg)
    if removed:
        logger.info("Microcompact: removed %d duplicate messages", removed)
    return deduped


# ── Tier 2: Snip (drop old, protect recent tail) ─────────────────────────────

def snip(
    messages: list[dict[str, Any]],
    *,
    max_chars: int,
    protect_recent: int = 6,
) -> list[dict[str, Any]]:
    """Drop oldest messages to fit within max_chars, protecting the most recent N.

    Always keeps the first message (system prompt) and last `protect_recent` messages.
    """
    if not messages:
        return messages

    total = sum(len(m.get("content", "")) for m in messages)
    if total <= max_chars:
        return messages

    # Protect: first message + last N
    head = messages[:1]
    tail = messages[-protect_recent:] if len(messages) > protect_recent else messages[1:]
    middle = messages[1:-protect_recent] if len(messages) > protect_recent + 1 else []

    # Drop from middle (oldest first) until under budget
    kept_middle = []
    chars_used = sum(len(m.get("content", "")) for m in head + tail)

    for msg in reversed(middle):
        msg_chars = len(msg.get("content", ""))
        if chars_used + msg_chars <= max_chars:
            kept_middle.insert(0, msg)
            chars_used += msg_chars

    dropped = len(middle) - len(kept_middle)
    if dropped:
        logger.info("Snip: dropped %d old messages (kept %d)", dropped, len(kept_middle))
        # Insert a marker so the model knows messages were dropped
        marker = {
            "role": "system",
            "content": f"[{dropped} earlier messages omitted for context budget]",
        }
        return head + [marker] + kept_middle + tail

    return head + kept_middle + tail


# ── Tier 3: Summarize (LLM-based, optional) ──────────────────────────────────

async def summarize_old_context(
    messages: list[dict[str, Any]],
    *,
    max_chars: int,
    protect_recent: int = 6,
    summarizer_fn=None,
) -> list[dict[str, Any]]:
    """Replace old messages with an LLM-generated summary.

    Only called when snip alone isn't enough. Uses summarizer_fn (async callable)
    to generate a summary of dropped messages. Falls back to snip if no summarizer.
    """
    if summarizer_fn is None:
        return snip(messages, max_chars=max_chars, protect_recent=protect_recent)

    total = sum(len(m.get("content", "")) for m in messages)
    if total <= max_chars:
        return messages

    head = messages[:1]
    tail = messages[-protect_recent:] if len(messages) > protect_recent else messages[1:]
    middle = messages[1:-protect_recent] if len(messages) > protect_recent + 1 else []

    if not middle:
        return snip(messages, max_chars=max_chars, protect_recent=protect_recent)

    # Summarize middle messages
    middle_text = "\n".join(
        f"[{m.get('role', '?')}]: {m.get('content', '')[:500]}" for m in middle
    )

    try:
        summary = await summarizer_fn(
            f"Summarize these conversation messages concisely (max 500 chars):\n\n{middle_text[:4000]}"
        )
        summary_msg = {
            "role": "system",
            "content": f"[Summary of {len(middle)} earlier messages]: {summary[:1000]}",
        }
        logger.info("Summarize: compressed %d messages into summary", len(middle))
        return head + [summary_msg] + tail
    except Exception as e:
        logger.warning("Summarize failed, falling back to snip: %s", e)
        return snip(messages, max_chars=max_chars, protect_recent=protect_recent)


# ── Combined compaction pipeline ──────────────────────────────────────────────

def compact_messages(
    messages: list[dict[str, Any]],
    *,
    max_chars: int = 80000,
    protect_recent: int = 6,
) -> list[dict[str, Any]]:
    """Apply compaction hierarchy: microcompact → snip.

    For async summarization (tier 3), use compact_messages_async() instead.
    """
    result = microcompact(messages)
    result = snip(result, max_chars=max_chars, protect_recent=protect_recent)
    return result


async def compact_messages_async(
    messages: list[dict[str, Any]],
    *,
    max_chars: int = 80000,
    protect_recent: int = 6,
    summarizer_fn=None,
) -> list[dict[str, Any]]:
    """Apply full compaction hierarchy: microcompact → snip → summarize."""
    result = microcompact(messages)
    result = await summarize_old_context(
        result,
        max_chars=max_chars,
        protect_recent=protect_recent,
        summarizer_fn=summarizer_fn,
    )
    return result
