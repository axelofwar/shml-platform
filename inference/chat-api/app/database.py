"""Database management for Chat API - PostgreSQL with pgvector."""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import uuid
import hashlib
import secrets

import asyncpg

from .config import (
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DB,
    POSTGRES_USER,
    read_password,
    API_KEY_PREFIX,
    API_KEY_LENGTH,
)
from .schemas import (
    User,
    UserRole,
    APIKey,
    APIKeyCreate,
    UserInstruction,
    InstructionCreate,
    InstructionScope,
    Conversation,
    ConversationSummary,
    ChatMessage,
)

logger = logging.getLogger(__name__)


class Database:
    """PostgreSQL database manager with pgvector support."""

    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Connect to PostgreSQL and initialize schema."""
        password = read_password()
        self.pool = await asyncpg.create_pool(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=password,
            min_size=2,
            max_size=20,
        )
        await self._init_schema()
        logger.info(
            f"Connected to PostgreSQL at {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
        )

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()

    async def _init_schema(self):
        """Create tables if not exists."""
        async with self.pool.acquire() as conn:
            # Enable pgvector extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # API Keys table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id VARCHAR(64) PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    user_id VARCHAR(64) NOT NULL,
                    key_hash VARCHAR(128) NOT NULL UNIQUE,
                    role VARCHAR(20) NOT NULL DEFAULT 'viewer',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMP,
                    last_used_at TIMESTAMP,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE
                );
                CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
                CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
            """
            )

            # User Instructions table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_instructions (
                    id VARCHAR(64) PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    scope VARCHAR(20) NOT NULL DEFAULT 'user',
                    name VARCHAR(100) NOT NULL,
                    content TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    priority INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_instructions_user_id ON user_instructions(user_id);
                CREATE INDEX IF NOT EXISTS idx_instructions_scope ON user_instructions(scope);
            """
            )

            # Conversations table
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
                CREATE INDEX IF NOT EXISTS idx_conv_user_id ON conversations(user_id);
                CREATE INDEX IF NOT EXISTS idx_conv_updated_at ON conversations(updated_at DESC);
            """
            )

            # Messages table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    conversation_id VARCHAR(64) REFERENCES conversations(id) ON DELETE CASCADE,
                    role VARCHAR(16) NOT NULL,
                    content TEXT NOT NULL,
                    name VARCHAR(64),
                    tool_calls JSONB,
                    tool_call_id VARCHAR(64),
                    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_msg_conv_id ON messages(conversation_id);
            """
            )

            # Usage tracking table (for metrics)
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    api_key_id VARCHAR(64),
                    model VARCHAR(64) NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_usage_user_id ON usage_logs(user_id);
                CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_logs(timestamp DESC);
            """
            )

            # Codebase embeddings table (for RAG)
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS code_embeddings (
                    id VARCHAR(64) PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    workspace_id VARCHAR(64),
                    file_path TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector(384),  -- sentence-transformers dimension
                    language VARCHAR(32),
                    last_modified TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_embed_user_id ON code_embeddings(user_id);
                CREATE INDEX IF NOT EXISTS idx_embed_workspace ON code_embeddings(workspace_id);
            """
            )

            # Create HNSW index for fast similarity search
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_embed_vector
                ON code_embeddings
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            """
            )

            logger.info("Database schema initialized")

    # =========================================================================
    # API Key Management
    # =========================================================================

    def _generate_api_key(self) -> tuple[str, str]:
        """Generate a new API key and its hash."""
        key = API_KEY_PREFIX + secrets.token_urlsafe(API_KEY_LENGTH)
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return key, key_hash

    async def create_api_key(
        self,
        creator: User,
        request: APIKeyCreate,
    ) -> APIKey:
        """Create a new API key."""
        key_id = f"key_{uuid.uuid4().hex[:12]}"
        key, key_hash = self._generate_api_key()

        # Determine target user and role
        target_user_id = request.target_user_id or creator.id
        target_role = request.target_role or creator.role

        # Viewers can't create keys for others or with higher roles
        if creator.role == UserRole.VIEWER:
            raise PermissionError("Viewers cannot create API keys")

        # Developers can only create keys for themselves
        if creator.role == UserRole.DEVELOPER:
            if request.target_user_id and request.target_user_id != creator.id:
                raise PermissionError("Developers can only create keys for themselves")
            target_role = UserRole.DEVELOPER

        # Admins can create keys for anyone with any role

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO api_keys (id, name, description, user_id, key_hash, role, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
                key_id,
                request.name,
                request.description,
                target_user_id,
                key_hash,
                target_role.value,
                request.expires_at,
            )

        return APIKey(
            id=key_id,
            name=request.name,
            description=request.description,
            user_id=target_user_id,
            role=target_role,
            created_at=datetime.utcnow(),
            expires_at=request.expires_at,
            is_active=True,
            key=key,  # Only returned on creation
        )

    async def validate_api_key(self, key: str) -> Optional[User]:
        """Validate an API key and return the associated user."""
        key_hash = hashlib.sha256(key.encode()).hexdigest()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, role, expires_at, is_active
                FROM api_keys
                WHERE key_hash = $1
            """,
                key_hash,
            )

            if not row:
                return None

            if not row["is_active"]:
                return None

            if row["expires_at"] and row["expires_at"] < datetime.utcnow():
                return None

            # Update last_used_at
            await conn.execute(
                """
                UPDATE api_keys SET last_used_at = NOW() WHERE id = $1
            """,
                row["id"],
            )

            return User(
                id=row["user_id"],
                role=UserRole(row["role"]),
                auth_method="api_key",
                api_key_id=row["id"],
            )

    async def list_api_keys(
        self, user: User, target_user_id: Optional[str] = None
    ) -> List[APIKey]:
        """List API keys. Admins can see all, others see only their own."""
        async with self.pool.acquire() as conn:
            if user.role == UserRole.ADMIN and target_user_id:
                rows = await conn.fetch(
                    """
                    SELECT id, name, description, user_id, role, created_at,
                           expires_at, last_used_at, is_active
                    FROM api_keys WHERE user_id = $1
                    ORDER BY created_at DESC
                """,
                    target_user_id,
                )
            elif user.role == UserRole.ADMIN:
                rows = await conn.fetch(
                    """
                    SELECT id, name, description, user_id, role, created_at,
                           expires_at, last_used_at, is_active
                    FROM api_keys
                    ORDER BY created_at DESC
                """
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, name, description, user_id, role, created_at,
                           expires_at, last_used_at, is_active
                    FROM api_keys WHERE user_id = $1
                    ORDER BY created_at DESC
                """,
                    user.id,
                )

            return [
                APIKey(
                    id=r["id"],
                    name=r["name"],
                    description=r["description"],
                    user_id=r["user_id"],
                    role=UserRole(r["role"]),
                    created_at=r["created_at"],
                    expires_at=r["expires_at"],
                    last_used_at=r["last_used_at"],
                    is_active=r["is_active"],
                )
                for r in rows
            ]

    async def revoke_api_key(self, user: User, key_id: str) -> bool:
        """Revoke an API key."""
        async with self.pool.acquire() as conn:
            if user.role == UserRole.ADMIN:
                result = await conn.execute(
                    """
                    UPDATE api_keys SET is_active = FALSE WHERE id = $1
                """,
                    key_id,
                )
            else:
                result = await conn.execute(
                    """
                    UPDATE api_keys SET is_active = FALSE
                    WHERE id = $1 AND user_id = $2
                """,
                    key_id,
                    user.id,
                )

            return "UPDATE 1" in result

    # =========================================================================
    # User Instructions
    # =========================================================================

    async def create_instruction(
        self,
        user: User,
        request: InstructionCreate,
    ) -> UserInstruction:
        """Create a new instruction."""
        # Only admins can create platform-wide instructions
        if request.scope == InstructionScope.PLATFORM and user.role != UserRole.ADMIN:
            raise PermissionError("Only admins can create platform-wide instructions")

        instruction_id = f"inst_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_instructions
                (id, user_id, scope, name, content, is_active, priority, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
                instruction_id,
                user.id,
                request.scope.value,
                request.name,
                request.content,
                request.is_active,
                request.priority,
                now,
                now,
            )

        return UserInstruction(
            id=instruction_id,
            user_id=user.id,
            scope=request.scope,
            name=request.name,
            content=request.content,
            is_active=request.is_active,
            priority=request.priority,
            created_at=now,
            updated_at=now,
        )

    async def get_active_instructions(self, user_id: str) -> List[UserInstruction]:
        """Get all active instructions for a user (user + platform)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, scope, name, content, is_active, priority,
                       created_at, updated_at
                FROM user_instructions
                WHERE (user_id = $1 OR scope = 'platform') AND is_active = TRUE
                ORDER BY priority DESC, created_at ASC
            """,
                user_id,
            )

            return [
                UserInstruction(
                    id=r["id"],
                    user_id=r["user_id"],
                    scope=InstructionScope(r["scope"]),
                    name=r["name"],
                    content=r["content"],
                    is_active=r["is_active"],
                    priority=r["priority"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

    async def list_instructions(self, user: User) -> List[UserInstruction]:
        """List all instructions for a user."""
        async with self.pool.acquire() as conn:
            if user.role == UserRole.ADMIN:
                # Admins see all instructions
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, scope, name, content, is_active, priority,
                           created_at, updated_at
                    FROM user_instructions
                    ORDER BY priority DESC, created_at DESC
                """
                )
            else:
                # Users see their own + platform instructions
                rows = await conn.fetch(
                    """
                    SELECT id, user_id, scope, name, content, is_active, priority,
                           created_at, updated_at
                    FROM user_instructions
                    WHERE user_id = $1 OR scope = 'platform'
                    ORDER BY priority DESC, created_at DESC
                """,
                    user.id,
                )

            return [
                UserInstruction(
                    id=r["id"],
                    user_id=r["user_id"],
                    scope=InstructionScope(r["scope"]),
                    name=r["name"],
                    content=r["content"],
                    is_active=r["is_active"],
                    priority=r["priority"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

    async def update_instruction(
        self,
        user: User,
        instruction_id: str,
        request: InstructionCreate,
    ) -> Optional[UserInstruction]:
        """Update an instruction."""
        async with self.pool.acquire() as conn:
            # Check ownership
            row = await conn.fetchrow(
                """
                SELECT user_id, scope FROM user_instructions WHERE id = $1
            """,
                instruction_id,
            )

            if not row:
                return None

            # Only owner or admin can update
            if row["user_id"] != user.id and user.role != UserRole.ADMIN:
                raise PermissionError("Cannot update another user's instruction")

            # Only admins can change to/from platform scope
            if (
                request.scope == InstructionScope.PLATFORM
                and user.role != UserRole.ADMIN
            ):
                raise PermissionError(
                    "Only admins can create platform-wide instructions"
                )

            now = datetime.utcnow()
            await conn.execute(
                """
                UPDATE user_instructions
                SET name = $1, content = $2, scope = $3, is_active = $4,
                    priority = $5, updated_at = $6
                WHERE id = $7
            """,
                request.name,
                request.content,
                request.scope.value,
                request.is_active,
                request.priority,
                now,
                instruction_id,
            )

            return UserInstruction(
                id=instruction_id,
                user_id=row["user_id"],
                scope=request.scope,
                name=request.name,
                content=request.content,
                is_active=request.is_active,
                priority=request.priority,
                created_at=now,  # Will be wrong but we don't fetch it
                updated_at=now,
            )

    async def delete_instruction(self, user: User, instruction_id: str) -> bool:
        """Delete an instruction."""
        async with self.pool.acquire() as conn:
            if user.role == UserRole.ADMIN:
                result = await conn.execute(
                    """
                    DELETE FROM user_instructions WHERE id = $1
                """,
                    instruction_id,
                )
            else:
                result = await conn.execute(
                    """
                    DELETE FROM user_instructions
                    WHERE id = $1 AND user_id = $2 AND scope = 'user'
                """,
                    instruction_id,
                    user.id,
                )

            return "DELETE 1" in result

    # =========================================================================
    # Conversations
    # =========================================================================

    async def create_conversation(
        self,
        user_id: str,
        model: str,
        title: Optional[str] = None,
    ) -> str:
        """Create a new conversation."""
        conv_id = f"conv_{uuid.uuid4().hex[:12]}"

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
        message: ChatMessage,
    ) -> None:
        """Add a message to a conversation."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, name, tool_calls, tool_call_id)
                VALUES ($1, $2, $3, $4, $5, $6)
            """,
                conversation_id,
                message.role,
                message.content,
                message.name,
                message.tool_calls,
                message.tool_call_id,
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
        """Get a conversation with all messages."""
        async with self.pool.acquire() as conn:
            conv = await conn.fetchrow(
                """
                SELECT id, user_id, title, model, created_at, updated_at, metadata
                FROM conversations WHERE id = $1 AND user_id = $2
            """,
                conversation_id,
                user_id,
            )

            if not conv:
                return None

            messages = await conn.fetch(
                """
                SELECT role, content, name, tool_calls, tool_call_id
                FROM messages WHERE conversation_id = $1
                ORDER BY timestamp ASC
            """,
                conversation_id,
            )

            return Conversation(
                id=conv["id"],
                user_id=conv["user_id"],
                title=conv["title"],
                model=conv["model"],
                messages=[
                    ChatMessage(
                        role=m["role"],
                        content=m["content"],
                        name=m["name"],
                        tool_calls=m["tool_calls"],
                        tool_call_id=m["tool_call_id"],
                    )
                    for m in messages
                ],
                created_at=conv["created_at"],
                updated_at=conv["updated_at"],
                metadata=conv["metadata"],
            )

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[ConversationSummary], int]:
        """List conversations for a user."""
        async with self.pool.acquire() as conn:
            # Get total count
            total = await conn.fetchval(
                """
                SELECT COUNT(*) FROM conversations WHERE user_id = $1
            """,
                user_id,
            )

            rows = await conn.fetch(
                """
                SELECT c.id, c.title, c.model, c.created_at, c.updated_at,
                       (SELECT COUNT(*) FROM messages WHERE conversation_id = c.id) as msg_count,
                       (SELECT content FROM messages WHERE conversation_id = c.id
                        AND role = 'user' ORDER BY timestamp LIMIT 1) as preview
                FROM conversations c
                WHERE c.user_id = $1
                ORDER BY c.updated_at DESC
                LIMIT $2 OFFSET $3
            """,
                user_id,
                limit,
                offset,
            )

            return [
                ConversationSummary(
                    id=r["id"],
                    title=r["title"],
                    model=r["model"],
                    message_count=r["msg_count"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    preview=r["preview"][:100] if r["preview"] else None,
                )
                for r in rows
            ], total

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        """Delete a conversation."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM conversations WHERE id = $1 AND user_id = $2
            """,
                conversation_id,
                user_id,
            )
            return "DELETE 1" in result

    # =========================================================================
    # Usage Logging
    # =========================================================================

    async def log_usage(
        self,
        user_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        api_key_id: Optional[str] = None,
    ) -> None:
        """Log API usage for metrics."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO usage_logs (user_id, api_key_id, model, prompt_tokens,
                                       completion_tokens, latency_ms)
                VALUES ($1, $2, $3, $4, $5, $6)
            """,
                user_id,
                api_key_id,
                model,
                prompt_tokens,
                completion_tokens,
                latency_ms,
            )

    async def get_aggregate_metrics(self, hours: int = 24) -> Dict[str, Any]:
        """Get aggregate platform metrics."""
        async with self.pool.acquire() as conn:
            since = datetime.utcnow() - timedelta(hours=hours)

            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_requests,
                    COALESCE(SUM(prompt_tokens + completion_tokens), 0) as total_tokens,
                    COALESCE(AVG(latency_ms), 0) as avg_latency,
                    COUNT(DISTINCT user_id) as active_users
                FROM usage_logs
                WHERE timestamp > $1
            """,
                since,
            )

            return {
                "total_requests_24h": row["total_requests"],
                "total_tokens_24h": row["total_tokens"],
                "avg_latency_ms": float(row["avg_latency"]),
                "active_users_24h": row["active_users"],
            }


# Global instance
db = Database()
