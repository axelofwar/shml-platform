"""Chat history storage with PostgreSQL."""

import json
import uuid
import logging
from typing import Optional, List
from datetime import datetime

import asyncpg

from .config import (
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DB,
    POSTGRES_USER,
    POSTGRES_PASSWORD_FILE,
)
from .schemas import Conversation, ConversationSummary, ChatMessage

logger = logging.getLogger(__name__)


def _read_password() -> str:
    """Read password from Docker secret file."""
    try:
        with open(POSTGRES_PASSWORD_FILE, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"PostgreSQL password file not found at {POSTGRES_PASSWORD_FILE}. Refusing to use insecure fallback password. Please provide the password file."
        )


class ChatHistoryDB:
    """PostgreSQL-based chat history storage."""

    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Connect to PostgreSQL."""
        password = _read_password()
        self.pool = await asyncpg.create_pool(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=password,
            min_size=2,
            max_size=10,
        )
        await self._init_schema()
        logger.info(f"Connected to PostgreSQL at {POSTGRES_HOST}:{POSTGRES_PORT}")

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()

    async def _init_schema(self):
        """Create tables if not exists."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id VARCHAR(64) PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    title VARCHAR(256),
                    model VARCHAR(64) NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    metadata JSONB
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    conversation_id VARCHAR(64) REFERENCES conversations(id) ON DELETE CASCADE,
                    role VARCHAR(16) NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
                CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
            """
            )

    async def create_conversation(
        self,
        user_id: str,
        model: str,
        title: Optional[str] = None,
    ) -> str:
        """Create new conversation. Returns conversation ID."""
        conv_id = f"conv-{uuid.uuid4().hex[:12]}"

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO conversations (id, user_id, title, model)
                VALUES ($1, $2, $3, $4)
            """,
                conv_id,
                user_id,
                title,
                model,
            )

        return conv_id

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> None:
        """Add message to conversation."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content)
                VALUES ($1, $2, $3)
            """,
                conversation_id,
                role,
                content,
            )

            # Update conversation timestamp
            await conn.execute(
                """
                UPDATE conversations SET updated_at = NOW() WHERE id = $1
            """,
                conversation_id,
            )

    async def get_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Optional[Conversation]:
        """Get full conversation with messages."""
        async with self.pool.acquire() as conn:
            # Get conversation
            conv_row = await conn.fetchrow(
                """
                SELECT id, user_id, title, model, created_at, updated_at, metadata
                FROM conversations WHERE id = $1 AND user_id = $2
            """,
                conversation_id,
                user_id,
            )

            if not conv_row:
                return None

            # Get messages
            msg_rows = await conn.fetch(
                """
                SELECT role, content, timestamp
                FROM messages WHERE conversation_id = $1
                ORDER BY timestamp ASC
            """,
                conversation_id,
            )

            messages = [
                ChatMessage(
                    role=row["role"],
                    content=row["content"],
                    timestamp=row["timestamp"],
                )
                for row in msg_rows
            ]

            return Conversation(
                id=conv_row["id"],
                user_id=conv_row["user_id"],
                title=conv_row["title"],
                model=conv_row["model"],
                created_at=conv_row["created_at"],
                updated_at=conv_row["updated_at"],
                messages=messages,
                metadata=conv_row["metadata"],
            )

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ConversationSummary]:
        """List user's conversations."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.title, c.model, c.created_at, c.updated_at,
                       COUNT(m.id) as message_count
                FROM conversations c
                LEFT JOIN messages m ON c.id = m.conversation_id
                WHERE c.user_id = $1
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                LIMIT $2 OFFSET $3
            """,
                user_id,
                limit,
                offset,
            )

            return [
                ConversationSummary(
                    id=row["id"],
                    title=row["title"],
                    message_count=row["message_count"],
                    model=row["model"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]

    async def update_title(
        self,
        conversation_id: str,
        user_id: str,
        title: str,
    ) -> bool:
        """Update conversation title."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE conversations SET title = $1
                WHERE id = $2 AND user_id = $3
            """,
                title,
                conversation_id,
                user_id,
            )
            return result == "UPDATE 1"

    async def delete_conversation(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:
        """Delete conversation and all messages."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM conversations WHERE id = $1 AND user_id = $2
            """,
                conversation_id,
                user_id,
            )
            return result == "DELETE 1"

    async def export_user_data(self, user_id: str) -> dict:
        """Export all user data for backup."""
        conversations = []

        async with self.pool.acquire() as conn:
            conv_rows = await conn.fetch(
                """
                SELECT id FROM conversations WHERE user_id = $1
            """,
                user_id,
            )

            for conv_row in conv_rows:
                conv = await self.get_conversation(conv_row["id"], user_id)
                if conv:
                    conversations.append(conv.model_dump())

        return {
            "user_id": user_id,
            "exported_at": datetime.now().isoformat(),
            "conversations": conversations,
        }


# Global instance
chat_history = ChatHistoryDB()
