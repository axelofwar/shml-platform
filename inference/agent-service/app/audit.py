"""Audit logging for agent actions."""

import logging
from typing import Optional, List
from datetime import datetime
import asyncpg

from .config import settings
from .schemas import AuditLog

logger = logging.getLogger(__name__)


class AuditLogger:
    """Manages audit logs in PostgreSQL."""

    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Connect to PostgreSQL."""
        try:
            self.pool = await asyncpg.create_pool(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                database=settings.POSTGRES_DB,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                min_size=2,
                max_size=10,
            )

            # Create audit table if not exists
            await self._create_table()

            logger.info("Connected to PostgreSQL for audit logging")
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    async def close(self):
        """Close PostgreSQL connection."""
        if self.pool:
            await self.pool.close()

    async def _create_table(self):
        """Create agent_actions table if not exists."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_actions (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    user_roles TEXT[] NOT NULL,
                    action_type TEXT NOT NULL,
                    tool_name TEXT,
                    arguments JSONB,
                    result JSONB,
                    error TEXT,
                    approved_by TEXT,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT action_type_check CHECK (action_type IN (
                        'tool_call', 'approval', 'rejection', 'interrupt', 'error'
                    ))
                );

                CREATE INDEX IF NOT EXISTS idx_agent_actions_session
                ON agent_actions(session_id);

                CREATE INDEX IF NOT EXISTS idx_agent_actions_user
                ON agent_actions(user_id);

                CREATE INDEX IF NOT EXISTS idx_agent_actions_timestamp
                ON agent_actions(timestamp);
                """
            )

    async def log(self, entry: AuditLog) -> int:
        """
        Log an agent action to PostgreSQL.

        Returns:
            ID of the created log entry
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO agent_actions (
                    session_id, user_id, user_roles, action_type,
                    tool_name, arguments, result, error, approved_by, timestamp
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                entry.session_id,
                entry.user_id,
                entry.user_roles,
                entry.action_type,
                entry.tool_name,
                entry.arguments,
                entry.result,
                entry.error,
                entry.approved_by,
                entry.timestamp,
            )

            log_id = result["id"]
            logger.info(
                f"Logged action {entry.action_type} for session {entry.session_id} (id={log_id})"
            )
            return log_id

    async def get_session_logs(self, session_id: str) -> List[AuditLog]:
        """Get all logs for a session."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM agent_actions
                WHERE session_id = $1
                ORDER BY timestamp ASC
                """,
                session_id,
            )

            return [
                AuditLog(
                    id=row["id"],
                    session_id=row["session_id"],
                    user_id=row["user_id"],
                    user_roles=list(row["user_roles"]),
                    action_type=row["action_type"],
                    tool_name=row["tool_name"],
                    arguments=row["arguments"],
                    result=row["result"],
                    error=row["error"],
                    approved_by=row["approved_by"],
                    timestamp=row["timestamp"],
                )
                for row in rows
            ]

    async def get_user_logs(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLog]:
        """Get logs for a specific user."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM agent_actions
                WHERE user_id = $1
                ORDER BY timestamp DESC
                LIMIT $2 OFFSET $3
                """,
                user_id,
                limit,
                offset,
            )

            return [
                AuditLog(
                    id=row["id"],
                    session_id=row["session_id"],
                    user_id=row["user_id"],
                    user_roles=list(row["user_roles"]),
                    action_type=row["action_type"],
                    tool_name=row["tool_name"],
                    arguments=row["arguments"],
                    result=row["result"],
                    error=row["error"],
                    approved_by=row["approved_by"],
                    timestamp=row["timestamp"],
                )
                for row in rows
            ]


# Global audit logger instance
audit_logger = AuditLogger()
