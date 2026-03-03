"""
Change Staging System: Copilot-like approve/reject workflow for code changes.
"""

import asyncio
import difflib
import logging
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
import json
import uuid

import asyncpg

from .schemas import (
    StagedChange,
    ChangeSet,
    ChangeStatus,
)

logger = logging.getLogger(__name__)


class ChangeStaging:
    """
    Manages staged code changes with approve/reject workflow.

    Similar to GitHub Copilot's change staging:
    - Changes are proposed but not immediately applied
    - User can review, approve, reject, or modify
    - Changes can be applied individually or as a set
    - Full audit trail maintained
    """

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool: Optional[asyncpg.Pool] = None

    async def initialize(self):
        """Initialize database connection and schema."""
        self.pool = await asyncpg.create_pool(
            self.database_url,
            min_size=1,
            max_size=5,
        )
        await self._ensure_schema()

    async def _ensure_schema(self):
        """Create staging tables."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS staged_changes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id VARCHAR(255) NOT NULL,
                    session_id VARCHAR(255) NOT NULL,
                    changeset_id UUID,

                    file_path TEXT NOT NULL,
                    original_content TEXT,
                    new_content TEXT NOT NULL,

                    change_type VARCHAR(20) NOT NULL,
                    diff TEXT,
                    description TEXT NOT NULL,

                    conversation_id VARCHAR(255),
                    related_memory_id UUID,

                    status VARCHAR(20) DEFAULT 'pending',

                    created_at TIMESTAMP DEFAULT NOW(),
                    reviewed_at TIMESTAMP,
                    applied_at TIMESTAMP,

                    review_comment TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_staged_user ON staged_changes(user_id);
                CREATE INDEX IF NOT EXISTS idx_staged_session ON staged_changes(session_id);
                CREATE INDEX IF NOT EXISTS idx_staged_status ON staged_changes(status);
                CREATE INDEX IF NOT EXISTS idx_staged_changeset ON staged_changes(changeset_id);

                CREATE TABLE IF NOT EXISTS change_sets (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id VARCHAR(255) NOT NULL,
                    session_id VARCHAR(255) NOT NULL,

                    description TEXT NOT NULL,
                    conversation_summary TEXT,

                    status VARCHAR(20) DEFAULT 'pending',

                    created_at TIMESTAMP DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_changesets_user ON change_sets(user_id);
                CREATE INDEX IF NOT EXISTS idx_changesets_session ON change_sets(session_id);
            """
            )

    def _generate_diff(self, original: Optional[str], new: str, file_path: str) -> str:
        """Generate unified diff between original and new content."""
        if original is None:
            # New file
            return f"+++ {file_path} (new file)\n" + "\n".join(
                f"+{line}" for line in new.splitlines()
            )

        original_lines = original.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )

        return "".join(diff)

    async def stage_change(
        self,
        user_id: str,
        session_id: str,
        file_path: str,
        new_content: str,
        description: str,
        original_content: Optional[str] = None,
        conversation_id: Optional[str] = None,
        related_memory_id: Optional[str] = None,
        changeset_id: Optional[str] = None,
    ) -> StagedChange:
        """
        Stage a code change for review.

        Args:
            user_id: User identifier
            session_id: Current session identifier
            file_path: Path to the file being changed
            new_content: The new content for the file
            description: Human-readable description of the change
            original_content: Original file content (None if new file)
            conversation_id: ID of conversation that generated this change
            related_memory_id: Related memory ID for context
            changeset_id: Optional changeset to group changes
        """
        # Determine change type
        if original_content is None:
            change_type = "create"
        elif new_content == "":
            change_type = "delete"
        else:
            change_type = "modify"

        # Generate diff
        diff = self._generate_diff(original_content, new_content, file_path)

        change = StagedChange(
            user_id=user_id,
            session_id=session_id,
            file_path=file_path,
            original_content=original_content,
            new_content=new_content,
            change_type=change_type,
            diff=diff,
            description=description,
            conversation_id=conversation_id,
            related_memory_id=related_memory_id,
        )

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO staged_changes (
                    id, user_id, session_id, changeset_id,
                    file_path, original_content, new_content,
                    change_type, diff, description,
                    conversation_id, related_memory_id,
                    status, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            """,
                change.id,
                change.user_id,
                change.session_id,
                changeset_id,
                change.file_path,
                change.original_content,
                change.new_content,
                change.change_type,
                change.diff,
                change.description,
                change.conversation_id,
                change.related_memory_id,
                change.status,
                change.created_at,
            )

        logger.info(f"Staged change {change.id} for {file_path}")
        return change

    async def stage_multiple(
        self,
        user_id: str,
        session_id: str,
        changes: List[Dict[str, Any]],
        description: str,
        conversation_summary: Optional[str] = None,
    ) -> ChangeSet:
        """
        Stage multiple changes as a set.

        Args:
            user_id: User identifier
            session_id: Session identifier
            changes: List of change dicts with file_path, new_content, description
            description: Overall description of the changeset
            conversation_summary: Optional summary of the conversation
        """
        changeset = ChangeSet(
            user_id=user_id,
            session_id=session_id,
            description=description,
            conversation_summary=conversation_summary,
        )

        async with self.pool.acquire() as conn:
            # Create changeset
            await conn.execute(
                """
                INSERT INTO change_sets (id, user_id, session_id, description, conversation_summary, status, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
                changeset.id,
                changeset.user_id,
                changeset.session_id,
                changeset.description,
                changeset.conversation_summary,
                changeset.status,
                changeset.created_at,
            )

        # Stage individual changes
        for change_data in changes:
            staged = await self.stage_change(
                user_id=user_id,
                session_id=session_id,
                file_path=change_data["file_path"],
                new_content=change_data["new_content"],
                description=change_data.get("description", ""),
                original_content=change_data.get("original_content"),
                changeset_id=changeset.id,
            )
            changeset.changes.append(staged)

        logger.info(
            f"Created changeset {changeset.id} with {len(changeset.changes)} changes"
        )
        return changeset

    async def get_pending_changes(
        self,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> List[StagedChange]:
        """Get all pending changes for a user/session."""
        async with self.pool.acquire() as conn:
            if session_id:
                rows = await conn.fetch(
                    """
                    SELECT * FROM staged_changes
                    WHERE user_id = $1 AND session_id = $2 AND status = 'pending'
                    ORDER BY created_at DESC
                """,
                    user_id,
                    session_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM staged_changes
                    WHERE user_id = $1 AND status = 'pending'
                    ORDER BY created_at DESC
                """,
                    user_id,
                )

            return [
                StagedChange(
                    id=str(row["id"]),
                    user_id=row["user_id"],
                    session_id=row["session_id"],
                    file_path=row["file_path"],
                    original_content=row["original_content"],
                    new_content=row["new_content"],
                    change_type=row["change_type"],
                    diff=row["diff"],
                    description=row["description"],
                    status=ChangeStatus(row["status"]),
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    async def approve_change(
        self,
        change_id: str,
        user_id: str,
        comment: Optional[str] = None,
    ) -> StagedChange:
        """Approve a staged change."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE staged_changes
                SET status = 'approved', reviewed_at = NOW(), review_comment = $3
                WHERE id = $1 AND user_id = $2
                RETURNING *
            """,
                change_id,
                user_id,
                comment,
            )

            if not row:
                raise ValueError(f"Change {change_id} not found")

            return StagedChange(
                id=str(row["id"]),
                user_id=row["user_id"],
                session_id=row["session_id"],
                file_path=row["file_path"],
                original_content=row["original_content"],
                new_content=row["new_content"],
                change_type=row["change_type"],
                diff=row["diff"],
                description=row["description"],
                status=ChangeStatus(row["status"]),
                created_at=row["created_at"],
                reviewed_at=row["reviewed_at"],
                review_comment=row["review_comment"],
            )

    async def reject_change(
        self,
        change_id: str,
        user_id: str,
        comment: Optional[str] = None,
    ) -> StagedChange:
        """Reject a staged change."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE staged_changes
                SET status = 'rejected', reviewed_at = NOW(), review_comment = $3
                WHERE id = $1 AND user_id = $2
                RETURNING *
            """,
                change_id,
                user_id,
                comment,
            )

            if not row:
                raise ValueError(f"Change {change_id} not found")

            return StagedChange(
                id=str(row["id"]),
                user_id=row["user_id"],
                session_id=row["session_id"],
                file_path=row["file_path"],
                original_content=row["original_content"],
                new_content=row["new_content"],
                change_type=row["change_type"],
                diff=row["diff"],
                description=row["description"],
                status=ChangeStatus(row["status"]),
                created_at=row["created_at"],
                reviewed_at=row["reviewed_at"],
                review_comment=row["review_comment"],
            )

    async def apply_change(
        self,
        change_id: str,
        user_id: str,
        workspace_path: str,
    ) -> StagedChange:
        """
        Apply an approved change to the filesystem.

        Args:
            change_id: The change to apply
            user_id: User identifier
            workspace_path: Base path for the workspace
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM staged_changes
                WHERE id = $1 AND user_id = $2 AND status = 'approved'
            """,
                change_id,
                user_id,
            )

            if not row:
                raise ValueError(f"Approved change {change_id} not found")

            file_path = row["file_path"]
            new_content = row["new_content"]
            change_type = row["change_type"]

            # Resolve full path
            if not os.path.isabs(file_path):
                full_path = os.path.join(workspace_path, file_path)
            else:
                full_path = file_path

            # Apply the change
            try:
                if change_type == "delete":
                    if os.path.exists(full_path):
                        os.remove(full_path)
                else:
                    # Create directory if needed
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)

                    with open(full_path, "w") as f:
                        f.write(new_content)

                # Mark as applied
                await conn.execute(
                    """
                    UPDATE staged_changes
                    SET status = 'applied', applied_at = NOW()
                    WHERE id = $1
                """,
                    change_id,
                )

                logger.info(f"Applied change {change_id} to {full_path}")

            except Exception as e:
                logger.error(f"Failed to apply change {change_id}: {e}")
                raise

            return StagedChange(
                id=str(row["id"]),
                user_id=row["user_id"],
                session_id=row["session_id"],
                file_path=row["file_path"],
                original_content=row["original_content"],
                new_content=row["new_content"],
                change_type=row["change_type"],
                diff=row["diff"],
                description=row["description"],
                status=ChangeStatus.APPLIED,
                created_at=row["created_at"],
                applied_at=datetime.utcnow(),
            )

    async def revert_change(
        self,
        change_id: str,
        user_id: str,
        workspace_path: str,
    ) -> StagedChange:
        """
        Revert an applied change back to original.

        Args:
            change_id: The change to revert
            user_id: User identifier
            workspace_path: Base path for the workspace
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM staged_changes
                WHERE id = $1 AND user_id = $2 AND status = 'applied'
            """,
                change_id,
                user_id,
            )

            if not row:
                raise ValueError(f"Applied change {change_id} not found")

            file_path = row["file_path"]
            original_content = row["original_content"]
            change_type = row["change_type"]

            # Resolve full path
            if not os.path.isabs(file_path):
                full_path = os.path.join(workspace_path, file_path)
            else:
                full_path = file_path

            # Revert the change
            try:
                if change_type == "create":
                    # Remove the created file
                    if os.path.exists(full_path):
                        os.remove(full_path)
                elif change_type == "delete":
                    # Restore the deleted file
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, "w") as f:
                        f.write(original_content)
                else:
                    # Restore original content
                    with open(full_path, "w") as f:
                        f.write(original_content)

                # Mark as reverted
                await conn.execute(
                    """
                    UPDATE staged_changes
                    SET status = 'reverted'
                    WHERE id = $1
                """,
                    change_id,
                )

                logger.info(f"Reverted change {change_id}")

            except Exception as e:
                logger.error(f"Failed to revert change {change_id}: {e}")
                raise

            return StagedChange(
                id=str(row["id"]),
                user_id=row["user_id"],
                session_id=row["session_id"],
                file_path=row["file_path"],
                original_content=row["original_content"],
                new_content=row["new_content"],
                change_type=row["change_type"],
                diff=row["diff"],
                description=row["description"],
                status=ChangeStatus.REVERTED,
                created_at=row["created_at"],
            )

    async def approve_and_apply_all(
        self,
        user_id: str,
        session_id: str,
        workspace_path: str,
    ) -> List[StagedChange]:
        """Approve and apply all pending changes for a session."""
        pending = await self.get_pending_changes(user_id, session_id)

        applied = []
        for change in pending:
            await self.approve_change(change.id, user_id)
            applied_change = await self.apply_change(change.id, user_id, workspace_path)
            applied.append(applied_change)

        return applied

    async def reject_all(
        self,
        user_id: str,
        session_id: str,
        comment: Optional[str] = None,
    ) -> List[StagedChange]:
        """Reject all pending changes for a session."""
        pending = await self.get_pending_changes(user_id, session_id)

        rejected = []
        for change in pending:
            rejected_change = await self.reject_change(change.id, user_id, comment)
            rejected.append(rejected_change)

        return rejected

    async def close(self):
        """Close database connection."""
        if self.pool:
            await self.pool.close()
