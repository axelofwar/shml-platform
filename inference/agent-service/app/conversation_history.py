"""
Conversation History Persistence - P1

Persists conversation turns to Postgres (schema: inference) with:
- session_id, user_id, role, content, created_at
- Loads recent history for active sessions
- Backward-compatible: all existing endpoints unchanged
"""

import logging
from datetime import datetime
from typing import List

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .database import Base

logger = logging.getLogger(__name__)

# Max turns to load into execution context (safety cap)
MAX_HISTORY_TURNS = 50
DEFAULT_HISTORY_TURNS = 20


class ConversationTurn(Base):
    """Persisted conversation turn in the inference schema."""

    __tablename__ = "conversation_turns"
    __table_args__ = (
        Index("ix_conv_session_created", "session_id", "created_at"),
        Index("ix_conv_user_session", "user_id", "session_id"),
        {"schema": "inference"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(255), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    role = Column(String(50), nullable=False)  # system, user, assistant, tool
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


async def ensure_schema(db: AsyncSession):
    """Ensure the inference schema exists."""
    try:
        await db.execute(text("CREATE SCHEMA IF NOT EXISTS inference"))
        await db.commit()
    except Exception as e:
        logger.warning(f"Schema creation skipped (may already exist): {e}")
        await db.rollback()


async def save_turn(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    role: str,
    content: str,
) -> ConversationTurn:
    """Persist a single conversation turn.

    Args:
        db: Async database session
        session_id: Session identifier
        user_id: User identifier
        role: Message role (system/user/assistant/tool)
        content: Message content

    Returns:
        The persisted ConversationTurn
    """
    turn = ConversationTurn(
        session_id=session_id,
        user_id=user_id,
        role=role,
        content=content,
        created_at=datetime.utcnow(),
    )
    db.add(turn)
    await db.flush()
    logger.debug(f"Saved turn: session={session_id} role={role} len={len(content)}")
    return turn


async def save_turns_batch(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    turns: List[dict],
) -> int:
    """Persist multiple conversation turns in a single transaction.

    Args:
        db: Async database session
        session_id: Session identifier
        user_id: User identifier
        turns: List of dicts with 'role' and 'content' keys

    Returns:
        Number of turns saved
    """
    count = 0
    for t in turns:
        role = t.get("role", "user")
        content = t.get("content", "")
        if isinstance(content, list):
            # Handle multimodal content parts - serialize to text
            content = " ".join(
                p.get("text", "[image]") if isinstance(p, dict) else str(p)
                for p in content
            )
        if not content:
            continue
        turn = ConversationTurn(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content[:65535],  # Truncate to safe limit
            created_at=datetime.utcnow(),
        )
        db.add(turn)
        count += 1

    if count > 0:
        await db.flush()
        logger.info(f"Batch saved {count} turns for session={session_id}")

    return count


async def load_history(
    db: AsyncSession,
    session_id: str,
    limit: int = DEFAULT_HISTORY_TURNS,
) -> List[dict]:
    """Load recent conversation history for a session.

    Args:
        db: Async database session
        session_id: Session identifier
        limit: Max turns to load (capped at MAX_HISTORY_TURNS)

    Returns:
        List of message dicts with 'role' and 'content', ordered oldest-first
    """
    limit = min(limit, MAX_HISTORY_TURNS)

    try:
        # Subquery to get the most recent N turns (desc), then re-order asc
        stmt = (
            select(ConversationTurn)
            .where(ConversationTurn.session_id == session_id)
            .order_by(ConversationTurn.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

        # Reverse to chronological order
        rows.reverse()

        messages = [{"role": row.role, "content": row.content} for row in rows]

        logger.debug(f"Loaded {len(messages)} history turns for session={session_id}")
        return messages

    except Exception as e:
        logger.error(f"Failed to load history for session={session_id}: {e}")
        return []


async def load_history_for_context(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    limit: int = DEFAULT_HISTORY_TURNS,
) -> List[dict]:
    """Load history formatted for inclusion in agent execution context.

    Same as load_history but adds safety checks:
    - Validates user_id matches session
    - Strips any system messages (those come from playbook)
    - Caps total content size

    Args:
        db: Async database session
        session_id: Session identifier
        user_id: User identifier
        limit: Max turns to load

    Returns:
        List of message dicts safe for context injection
    """
    limit = min(limit, MAX_HISTORY_TURNS)

    try:
        stmt = (
            select(ConversationTurn)
            .where(
                ConversationTurn.session_id == session_id,
                ConversationTurn.user_id == user_id,
                ConversationTurn.role.in_(["user", "assistant"]),  # Skip system/tool
            )
            .order_by(ConversationTurn.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        rows.reverse()

        # Cap total content size at ~32KB to avoid context overflow
        MAX_CONTEXT_BYTES = 32 * 1024
        messages = []
        total_size = 0

        for row in rows:
            content_size = len(row.content.encode("utf-8"))
            if total_size + content_size > MAX_CONTEXT_BYTES:
                break
            messages.append({"role": row.role, "content": row.content})
            total_size += content_size

        logger.info(
            f"Context history: {len(messages)} turns, {total_size} bytes "
            f"for session={session_id}"
        )
        return messages

    except Exception as e:
        logger.error(f"Failed to load context history for session={session_id}: {e}")
        return []
