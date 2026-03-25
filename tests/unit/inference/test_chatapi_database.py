"""Unit tests for inference/chat-api/app/database.py.

Covers Database class methods using mocked asyncpg pool/connection.
No live PostgreSQL required.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# sys.path setup
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CHAT_API = _ROOT / "inference" / "chat-api"
for _p in [str(_ROOT), str(_CHAT_API)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Stub asyncpg (not installed in tests/venv)
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

# Stub redis (imported by rate_limit / config chain)
if "redis" not in sys.modules:
    _redis_mod = MagicMock()
    _redis_mod.asyncio = MagicMock()
    sys.modules["redis"] = _redis_mod
    sys.modules["redis.asyncio"] = _redis_mod.asyncio

from app.database import Database  # noqa: E402
from app.schemas import (  # noqa: E402
    APIKeyCreate,
    InstructionCreate,
    InstructionScope,
    ChatMessage,
    User,
    UserRole,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(**fetch_results) -> MagicMock:
    """Build a mock asyncpg connection."""
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")
    conn.fetchrow = AsyncMock(return_value=fetch_results.get("fetchrow"))
    conn.fetch = AsyncMock(return_value=fetch_results.get("fetch", []))
    conn.fetchval = AsyncMock(return_value=fetch_results.get("fetchval", 0))
    return conn


def _make_db(conn: MagicMock) -> Database:
    """Create a Database instance with a mocked pool over the given connection."""
    db = Database()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    db.pool = MagicMock()
    db.pool.acquire = MagicMock(return_value=cm)
    db.pool.close = AsyncMock()
    return db


def _admin() -> User:
    return User(id="u-admin", role=UserRole.ADMIN, auth_method="oauth")


def _developer() -> User:
    return User(id="u-dev", role=UserRole.DEVELOPER, auth_method="oauth")


def _viewer() -> User:
    return User(id="u-viewer", role=UserRole.VIEWER, auth_method="oauth")


# ---------------------------------------------------------------------------
# Tests: __init__ and close
# ---------------------------------------------------------------------------

class TestDatabaseInit:
    def test_init_pool_is_none(self):
        db = Database()
        assert db.pool is None

    @pytest.mark.asyncio
    async def test_close_with_pool_calls_pool_close(self):
        db = Database()
        db.pool = MagicMock()
        db.pool.close = AsyncMock()
        await db.close()
        db.pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_without_pool_is_noop(self):
        db = Database()
        await db.close()  # Should not raise


# ---------------------------------------------------------------------------
# Tests: _generate_api_key
# ---------------------------------------------------------------------------

class TestGenerateApiKey:
    def test_returns_key_and_hash(self):
        db = Database()
        key, key_hash = db._generate_api_key()
        assert key.startswith("shml_")
        assert len(key_hash) == 64  # sha256 hex digest

    def test_keys_are_unique(self):
        db = Database()
        key1, _ = db._generate_api_key()
        key2, _ = db._generate_api_key()
        assert key1 != key2


# ---------------------------------------------------------------------------
# Tests: create_api_key
# ---------------------------------------------------------------------------

class TestCreateApiKey:
    @pytest.mark.asyncio
    async def test_admin_creates_key_for_anyone(self):
        conn = _make_conn()
        db = _make_db(conn)
        req = APIKeyCreate(name="mykey", target_user_id="u-other")
        result = await db.create_api_key(_admin(), req)
        assert result.name == "mykey"
        assert result.key is not None
        conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_viewer_cannot_create_key(self):
        conn = _make_conn()
        db = _make_db(conn)
        req = APIKeyCreate(name="key")
        with pytest.raises(PermissionError, match="Viewers cannot create"):
            await db.create_api_key(_viewer(), req)

    @pytest.mark.asyncio
    async def test_developer_cannot_create_key_for_others(self):
        conn = _make_conn()
        db = _make_db(conn)
        req = APIKeyCreate(name="key", target_user_id="u-other")
        with pytest.raises(PermissionError, match="Developers can only create keys for themselves"):
            await db.create_api_key(_developer(), req)

    @pytest.mark.asyncio
    async def test_developer_creates_own_key(self):
        conn = _make_conn()
        db = _make_db(conn)
        req = APIKeyCreate(name="devkey")
        result = await db.create_api_key(_developer(), req)
        assert result.role == UserRole.DEVELOPER


# ---------------------------------------------------------------------------
# Tests: validate_api_key
# ---------------------------------------------------------------------------

class TestValidateApiKey:
    @pytest.mark.asyncio
    async def test_valid_key_returns_user(self):
        import hashlib
        key = "shml_testkey"
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        row = {
            "id": "key-1",
            "user_id": "u-1",
            "role": "admin",
            "expires_at": None,
            "is_active": True,
        }
        conn = _make_conn(fetchrow=row)
        db = _make_db(conn)
        user = await db.validate_api_key(key)
        assert user is not None
        assert user.role == UserRole.ADMIN

    @pytest.mark.asyncio
    async def test_revoked_key_returns_none(self):
        row = {
            "id": "key-1",
            "user_id": "u-1",
            "role": "admin",
            "expires_at": None,
            "is_active": False,
        }
        conn = _make_conn(fetchrow=row)
        db = _make_db(conn)
        user = await db.validate_api_key("shml_anything")
        assert user is None

    @pytest.mark.asyncio
    async def test_expired_key_returns_none(self):
        row = {
            "id": "key-1",
            "user_id": "u-1",
            "role": "viewer",
            "expires_at": datetime.utcnow() - timedelta(hours=1),
            "is_active": True,
        }
        conn = _make_conn(fetchrow=row)
        db = _make_db(conn)
        user = await db.validate_api_key("shml_anything")
        assert user is None

    @pytest.mark.asyncio
    async def test_missing_key_returns_none(self):
        conn = _make_conn(fetchrow=None)
        db = _make_db(conn)
        user = await db.validate_api_key("shml_invalid")
        assert user is None


# ---------------------------------------------------------------------------
# Tests: list_api_keys
# ---------------------------------------------------------------------------

class TestListApiKeys:
    @pytest.mark.asyncio
    async def test_admin_sees_all_keys(self):
        rows = [
            {
                "id": "k1", "name": "k", "description": None, "user_id": "u1",
                "role": "viewer", "created_at": datetime.utcnow(),
                "expires_at": None, "last_used_at": None, "is_active": True,
            }
        ]
        conn = _make_conn(fetch=rows)
        db = _make_db(conn)
        keys = await db.list_api_keys(_admin())
        assert len(keys) == 1

    @pytest.mark.asyncio
    async def test_non_admin_sees_own_keys(self):
        conn = _make_conn(fetch=[])
        db = _make_db(conn)
        keys = await db.list_api_keys(_developer())
        assert keys == []


# ---------------------------------------------------------------------------
# Tests: revoke_api_key
# ---------------------------------------------------------------------------

class TestRevokeApiKey:
    @pytest.mark.asyncio
    async def test_revoke_returns_true_on_update(self):
        conn = _make_conn()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        db = _make_db(conn)
        result = await db.revoke_api_key(_admin(), "key-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_revoke_returns_false_when_not_found(self):
        conn = _make_conn()
        conn.execute = AsyncMock(return_value="UPDATE 0")
        db = _make_db(conn)
        result = await db.revoke_api_key(_developer(), "key-missing")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: create_instruction
# ---------------------------------------------------------------------------

class TestCreateInstruction:
    @pytest.mark.asyncio
    async def test_create_user_instruction(self):
        conn = _make_conn()
        db = _make_db(conn)
        req = InstructionCreate(name="Be helpful", content="Always be helpful.")
        result = await db.create_instruction(_developer(), req)
        assert result.name == "Be helpful"
        conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_admin_cannot_create_platform_instruction(self):
        conn = _make_conn()
        db = _make_db(conn)
        req = InstructionCreate(
            name="Global", content="Always...", scope=InstructionScope.PLATFORM
        )
        with pytest.raises(PermissionError, match="Only admins"):
            await db.create_instruction(_developer(), req)

    @pytest.mark.asyncio
    async def test_admin_can_create_platform_instruction(self):
        conn = _make_conn()
        db = _make_db(conn)
        req = InstructionCreate(
            name="Global", content="Always...", scope=InstructionScope.PLATFORM
        )
        result = await db.create_instruction(_admin(), req)
        assert result.scope == InstructionScope.PLATFORM


# ---------------------------------------------------------------------------
# Tests: get_active_instructions
# ---------------------------------------------------------------------------

class TestGetActiveInstructions:
    @pytest.mark.asyncio
    async def test_returns_instruction_list(self):
        rows = [
            {
                "id": "inst-1", "user_id": "u-dev", "scope": "user",
                "name": "Be helpful", "content": "...", "is_active": True,
                "priority": 0, "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        ]
        conn = _make_conn(fetch=rows)
        db = _make_db(conn)
        result = await db.get_active_instructions("u-dev")
        assert len(result) == 1
        assert result[0].name == "Be helpful"


# ---------------------------------------------------------------------------
# Tests: list_instructions
# ---------------------------------------------------------------------------

class TestListInstructions:
    @pytest.mark.asyncio
    async def test_admin_sees_all(self):
        conn = _make_conn(fetch=[])
        db = _make_db(conn)
        result = await db.list_instructions(_admin())
        assert result == []

    @pytest.mark.asyncio
    async def test_non_admin_filtered(self):
        conn = _make_conn(fetch=[])
        db = _make_db(conn)
        result = await db.list_instructions(_developer())
        assert result == []


# ---------------------------------------------------------------------------
# Tests: update_instruction
# ---------------------------------------------------------------------------

class TestUpdateInstruction:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        conn = _make_conn(fetchrow=None)
        db = _make_db(conn)
        req = InstructionCreate(name="New", content="...")
        result = await db.update_instruction(_developer(), "inst-missing", req)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_owner_cannot_update(self):
        conn = _make_conn(fetchrow={"user_id": "u-other", "scope": "user"})
        db = _make_db(conn)
        req = InstructionCreate(name="New", content="...")
        with pytest.raises(PermissionError, match="Cannot update"):
            await db.update_instruction(_developer(), "inst-1", req)

    @pytest.mark.asyncio
    async def test_owner_can_update(self):
        row = {"user_id": "u-dev", "scope": "user"}
        conn = _make_conn(fetchrow=row)
        db = _make_db(conn)
        req = InstructionCreate(name="Updated", content="New content")
        result = await db.update_instruction(_developer(), "inst-1", req)
        assert result is not None
        assert result.name == "Updated"


# ---------------------------------------------------------------------------
# Tests: delete_instruction
# ---------------------------------------------------------------------------

class TestDeleteInstruction:
    @pytest.mark.asyncio
    async def test_admin_delete_returns_true(self):
        conn = _make_conn()
        conn.execute = AsyncMock(return_value="DELETE 1")
        db = _make_db(conn)
        result = await db.delete_instruction(_admin(), "inst-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_non_admin_delete_not_found(self):
        conn = _make_conn()
        conn.execute = AsyncMock(return_value="DELETE 0")
        db = _make_db(conn)
        result = await db.delete_instruction(_developer(), "inst-x")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: Conversations
# ---------------------------------------------------------------------------

class TestConversations:
    @pytest.mark.asyncio
    async def test_create_conversation_returns_id(self):
        conn = _make_conn()
        db = _make_db(conn)
        conv_id = await db.create_conversation("u-1", "gpt-4", title="My Chat")
        assert conv_id.startswith("conv_")

    @pytest.mark.asyncio
    async def test_add_message_calls_execute_twice(self):
        conn = _make_conn()
        db = _make_db(conn)
        msg = ChatMessage(role="user", content="Hello")
        await db.add_message("conv-1", msg)
        assert conn.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_get_conversation_not_found(self):
        conn = _make_conn(fetchrow=None)
        db = _make_db(conn)
        result = await db.get_conversation("conv-x", "u-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_conversation_with_messages(self):
        conv_row = {
            "id": "conv-1", "user_id": "u-1", "title": "Chat",
            "model": "gpt-4", "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(), "metadata": None,
        }
        msg_rows = [
            {"role": "user", "content": "Hi", "name": None,
             "tool_calls": None, "tool_call_id": None},
        ]
        conn = _make_conn(fetchrow=conv_row, fetch=msg_rows)
        db = _make_db(conn)
        result = await db.get_conversation("conv-1", "u-1")
        assert result is not None
        assert len(result.messages) == 1

    @pytest.mark.asyncio
    async def test_list_conversations_returns_tuple(self):
        rows = [
            {
                "id": "c1", "title": None, "model": "gpt-4",
                "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
                "msg_count": 2, "preview": "Hello there",
            }
        ]
        conn = _make_conn(fetch=rows, fetchval=1)
        db = _make_db(conn)
        summaries, total = await db.list_conversations("u-1")
        assert total == 1
        assert len(summaries) == 1

    @pytest.mark.asyncio
    async def test_delete_conversation_returns_true(self):
        conn = _make_conn()
        conn.execute = AsyncMock(return_value="DELETE 1")
        db = _make_db(conn)
        result = await db.delete_conversation("u-1", "conv-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_conversation_not_found(self):
        conn = _make_conn()
        conn.execute = AsyncMock(return_value="DELETE 0")
        db = _make_db(conn)
        result = await db.delete_conversation("u-1", "conv-x")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: log_usage + get_aggregate_metrics
# ---------------------------------------------------------------------------

class TestUsage:
    @pytest.mark.asyncio
    async def test_log_usage_calls_execute(self):
        conn = _make_conn()
        db = _make_db(conn)
        await db.log_usage("u-1", "gpt-4", 100, 50, 300)
        conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_usage_with_api_key_id(self):
        conn = _make_conn()
        db = _make_db(conn)
        await db.log_usage("u-1", "gpt-4", 100, 50, 300, api_key_id="key-1")
        conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_aggregate_metrics_returns_dict(self):
        row = {
            "total_requests": 100,
            "total_tokens": 50000,
            "avg_latency": 250.5,
            "active_users": 5,
        }
        conn = _make_conn(fetchrow=row)
        db = _make_db(conn)
        metrics = await db.get_aggregate_metrics(hours=24)
        assert metrics["total_requests_24h"] == 100
        assert metrics["active_users_24h"] == 5
        assert isinstance(metrics["avg_latency_ms"], float)
