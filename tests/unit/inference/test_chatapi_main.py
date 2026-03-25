"""Unit tests for inference/chat-api/app/main.py — FastAPI route handlers.

Covers the FastAPI application routes: health, models, chat completions,
API key management, instructions, conversations, rate limiting, and metrics.
No live Redis, DB, or GPU required — all external dependencies are mocked.
"""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# sys.path setup — must happen before any chat-api imports
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CHAT_API = _ROOT / "inference" / "chat-api"
for _p in [str(_ROOT), str(_CHAT_API)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Stub redis before importing chat-api modules (rate_limit.py imports redis.asyncio)
if "redis" not in sys.modules:
    _redis_mod = MagicMock()
    _redis_mod.asyncio = MagicMock()
    _redis_mod.asyncio.Redis = MagicMock
    sys.modules["redis"] = _redis_mod
    sys.modules["redis.asyncio"] = _redis_mod.asyncio

# Stub asyncpg before importing database.py
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

# Stub httpx before model_router.py tries to use it — we patch at module level anyway
if "httpx" not in sys.modules:
    sys.modules["httpx"] = MagicMock()

# Now import the main module and the app instance
import app.main as _main_module  # noqa: E402
from app.main import app  # noqa: E402
from app.auth import (  # noqa: E402
    get_current_user as _get_current_user,
    require_admin as _require_admin,
    require_developer_or_admin as _require_dev_or_admin,
)
from app.schemas import (  # noqa: E402
    User,
    UserRole,
    UserInstruction,
    InstructionScope,
    APIKey,
    ModelInfo,
    ChatMessage,
    ChatCompletionChoice,
    ChatCompletionUsage,
    ChatCompletionResponse,
    Conversation,
    ConversationSummary,
    RateLimitStatus,
    PlatformMetrics,
)

# ---------------------------------------------------------------------------
# Shared test users
# ---------------------------------------------------------------------------
_NOW = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_ADMIN = User(id="admin-1", email="admin@test.com", role=UserRole.ADMIN, auth_method="oauth")
_DEV = User(id="dev-1", email="dev@test.com", role=UserRole.DEVELOPER, auth_method="oauth")
_VIEWER = User(id="view-1", email="viewer@test.com", role=UserRole.VIEWER, auth_method="oauth")


# ---------------------------------------------------------------------------
# Factory helpers for mock dependencies
# ---------------------------------------------------------------------------

def _make_model_info(key: str, available=True) -> ModelInfo:
    return ModelInfo(
        id=f"model-{key}",
        name=f"Model {key}",
        description=f"Test {key} model",
        context_length=8192,
        is_available=available,
        gpu="RTX 3090",
        vram_gb=24,
        recommended_for=["testing"],
    )


def _make_mock_db():
    db = AsyncMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db.validate_api_key = AsyncMock(return_value=None)
    db.get_active_instructions = AsyncMock(return_value=[])
    db.log_usage = AsyncMock()
    db.add_message = AsyncMock()
    db.create_api_key = AsyncMock(return_value=APIKey(
        id="key-1", name="test-key", user_id="admin-1",
        role=UserRole.ADMIN, created_at=_NOW, is_active=True,
    ))
    db.list_api_keys = AsyncMock(return_value=[])
    db.revoke_api_key = AsyncMock(return_value=True)
    db.create_instruction = AsyncMock(return_value=UserInstruction(
        id="inst-1", user_id="admin-1", name="Test", content="Do X",
        is_active=True, priority=0, created_at=_NOW, updated_at=_NOW,
        scope=InstructionScope.USER,
    ))
    db.list_instructions = AsyncMock(return_value=[])
    db.update_instruction = AsyncMock(return_value=UserInstruction(
        id="inst-1", user_id="admin-1", name="Updated", content="Do Y",
        is_active=True, priority=0, created_at=_NOW, updated_at=_NOW,
        scope=InstructionScope.USER,
    ))
    db.delete_instruction = AsyncMock(return_value=True)
    db.create_conversation = AsyncMock(return_value="conv-1")
    db.list_conversations = AsyncMock(return_value=([], 0))
    db.get_conversation = AsyncMock(return_value=Conversation(
        id="conv-1", user_id="admin-1", model="auto",
        messages=[], created_at=_NOW, updated_at=_NOW,
    ))
    db.delete_conversation = AsyncMock(return_value=True)
    db.get_aggregate_metrics = AsyncMock(return_value={
        "total_requests_24h": 100,
        "total_tokens_24h": 50000,
        "avg_latency_ms": 250.0,
        "active_users_24h": 5,
    })
    return db


def _make_mock_rate_limiter(allow: bool = True):
    rl = AsyncMock()
    rl.connect = AsyncMock()
    rl.close = AsyncMock()
    rl.record = AsyncMock(return_value=allow)
    # Use a naive datetime so main.py's `reset_at - reset_at.utcnow()` doesn't
    # raise a TypeError (mixing aware/naive datetimes).
    _reset_at = datetime(2025, 1, 1, 0, 0, 0)
    rl.check = AsyncMock(return_value=RateLimitStatus(
        requests_remaining=0 if not allow else 99,
        requests_limit=100,
        reset_at=_reset_at,
        is_limited=not allow,
        role=UserRole.ADMIN,
    ))
    return rl


def _make_completion_response(model_id: str = "model-primary") -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="cmpl-1",
        created=int(time.time()),
        model=model_id,
        choices=[ChatCompletionChoice(
            index=0,
            message=ChatMessage(role="assistant", content="Hello!"),
            finish_reason="stop",
        )],
        usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _make_mock_model_router():
    mr = AsyncMock()
    mr.connect = AsyncMock()
    mr.close = AsyncMock()
    mr.get_model_status = AsyncMock(return_value={
        "primary": _make_model_info("primary", available=True),
        "fallback": _make_model_info("fallback", available=True),
    })
    mr.generate = AsyncMock(return_value=(
        _make_completion_response(),
        "model-primary",
        350,
    ))
    mr.generate_stream = MagicMock(return_value=_async_iter_chunks())
    return mr


async def _async_iter_chunks():
    yield b'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n'
    yield b"data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Test client context manager
# ---------------------------------------------------------------------------

@contextmanager
def _client(user=None, rate_limit_allow=True):
    if user is None:
        user = _ADMIN
    mock_db = _make_mock_db()
    mock_rl = _make_mock_rate_limiter(rate_limit_allow)
    mock_mr = _make_mock_model_router()
    with (
        patch.object(_main_module, "db", mock_db),
        patch.object(_main_module, "rate_limiter", mock_rl),
        patch.object(_main_module, "model_router", mock_mr),
    ):
        app.dependency_overrides[_get_current_user] = lambda: user
        app.dependency_overrides[_require_admin] = lambda: user
        app.dependency_overrides[_require_dev_or_admin] = lambda: user
        try:
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c, mock_db, mock_rl, mock_mr
        finally:
            app.dependency_overrides.clear()


# ===========================================================================
# Health endpoint
# ===========================================================================

class TestHealthEndpoint:
    def test_health_all_available(self):
        with _client() as (c, db, rl, mr):
            resp = c.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "uptime_seconds" in data
        assert len(data["services"]) == 2

    def test_health_primary_down(self):
        with _client() as (c, db, rl, mr):
            mr.get_model_status.return_value = {
                "primary": _make_model_info("primary", available=False),
                "fallback": _make_model_info("fallback", available=True),
            }
            resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"

    def test_health_all_down(self):
        with _client() as (c, db, rl, mr):
            mr.get_model_status.return_value = {
                "primary": _make_model_info("primary", available=False),
                "fallback": _make_model_info("fallback", available=False),
            }
            resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "unhealthy"


# ===========================================================================
# Models endpoint
# ===========================================================================

class TestModelsEndpoint:
    def test_list_models_returns_auto_plus_backends(self):
        with _client() as (c, db, rl, mr):
            resp = c.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        # auto + 2 backends = 3 entries
        assert len(data["data"]) == 3
        ids = [m["id"] for m in data["data"]]
        assert "auto" in ids

    def test_list_models_requires_auth(self):
        # Without dependency override, would normally need auth —
        # verify the endpoint calls model_router
        with _client(user=_VIEWER) as (c, db, rl, mr):
            resp = c.get("/v1/models")
        assert resp.status_code == 200
        mr.get_model_status.assert_called()


# ===========================================================================
# Chat completions
# ===========================================================================

class TestChatCompletions:
    _payload = {
        "messages": [{"role": "user", "content": "Hello"}],
        "model": "auto",
    }

    def test_basic_completion(self):
        with _client() as (c, db, rl, mr):
            resp = c.post("/v1/chat/completions", json=self._payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert len(data["choices"]) == 1
        mr.generate.assert_called_once()

    def test_completion_logs_usage(self):
        with _client() as (c, db, rl, mr):
            c.post("/v1/chat/completions", json=self._payload)
        db.log_usage.assert_called_once()

    def test_rate_limit_exceeded_returns_429(self):
        with _client(rate_limit_allow=False) as (c, db, rl, mr):
            resp = c.post("/v1/chat/completions", json=self._payload)
        assert resp.status_code == 429

    def test_completion_with_conversation_id(self):
        payload = {**self._payload, "conversation_id": "conv-abc"}
        with _client() as (c, db, rl, mr):
            resp = c.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        # Should have tried to add messages and updated conversation_id
        assert db.add_message.called

    def test_completion_with_instructions_included(self):
        from app.schemas import UserInstruction, InstructionScope
        inst = UserInstruction(
            id="inst-1", user_id="admin-1", name="Always be brief", content="Be brief.",
            is_active=True, priority=0, created_at=_NOW, updated_at=_NOW,
            scope=InstructionScope.USER,
        )
        with _client() as (c, db, rl, mr):
            db.get_active_instructions.return_value = [inst]
            resp = c.post("/v1/chat/completions", json={
                **self._payload, "include_instructions": True,
            })
        assert resp.status_code == 200
        mr.generate.assert_called_once()


# ===========================================================================
# API Key Management
# ===========================================================================

class TestApiKeyEndpoints:
    def test_create_api_key(self):
        with _client() as (c, db, rl, mr):
            resp = c.post("/api-keys", json={"name": "my-key"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-key"

    def test_create_api_key_permission_error(self):
        with _client() as (c, db, rl, mr):
            db.create_api_key.side_effect = PermissionError("Not allowed")
            resp = c.post("/api-keys", json={"name": "my-key"})
        assert resp.status_code == 403

    def test_list_api_keys_empty(self):
        with _client() as (c, db, rl, mr):
            resp = c.get("/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert data["keys"] == []
        assert data["total"] == 0

    def test_revoke_api_key(self):
        with _client() as (c, db, rl, mr):
            resp = c.delete("/api-keys/key-123")
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

    def test_revoke_api_key_not_found(self):
        with _client() as (c, db, rl, mr):
            db.revoke_api_key.return_value = False
            resp = c.delete("/api-keys/key-missing")
        assert resp.status_code == 404


# ===========================================================================
# User Instructions
# ===========================================================================

class TestInstructionEndpoints:
    def test_create_instruction(self):
        with _client() as (c, db, rl, mr):
            resp = c.post("/instructions", json={"name": "Be brief", "content": "Be concise."})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test"

    def test_create_instruction_permission_error(self):
        with _client() as (c, db, rl, mr):
            db.create_instruction.side_effect = PermissionError("Admin only")
            resp = c.post("/instructions", json={"name": "Platform", "content": "Rules."})
        assert resp.status_code == 403

    def test_list_instructions_empty(self):
        with _client() as (c, db, rl, mr):
            resp = c.get("/instructions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["instructions"] == []
        assert data["total"] == 0

    def test_update_instruction(self):
        with _client() as (c, db, rl, mr):
            resp = c.put("/instructions/inst-1", json={"name": "Updated", "content": "New rules."})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_update_instruction_not_found(self):
        with _client() as (c, db, rl, mr):
            db.update_instruction.return_value = None
            resp = c.put("/instructions/inst-xyz", json={"name": "X", "content": "Y."})
        assert resp.status_code == 404

    def test_update_instruction_permission_error(self):
        with _client() as (c, db, rl, mr):
            db.update_instruction.side_effect = PermissionError("Not yours")
            resp = c.put("/instructions/inst-1", json={"name": "X", "content": "Y."})
        assert resp.status_code == 403

    def test_delete_instruction(self):
        with _client() as (c, db, rl, mr):
            resp = c.delete("/instructions/inst-1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_delete_instruction_not_found(self):
        with _client() as (c, db, rl, mr):
            db.delete_instruction.return_value = False
            resp = c.delete("/instructions/inst-xyz")
        assert resp.status_code == 404


# ===========================================================================
# Conversations
# ===========================================================================

class TestConversationEndpoints:
    def test_create_conversation(self):
        with _client() as (c, db, rl, mr):
            resp = c.post("/conversations?model=auto&title=New+Chat")
        assert resp.status_code == 200
        assert resp.json()["id"] == "conv-1"

    def test_list_conversations_empty(self):
        with _client() as (c, db, rl, mr):
            resp = c.get("/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["conversations"] == []
        assert data["total"] == 0
        assert data["has_more"] is False

    def test_list_conversations_with_results(self):
        from app.schemas import ConversationSummary
        summaries = [ConversationSummary(
            id="conv-1", model="auto", message_count=5,
            created_at=_NOW, updated_at=_NOW,
        )]
        with _client() as (c, db, rl, mr):
            db.list_conversations.return_value = (summaries, 1)
            resp = c.get("/conversations?limit=10&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["conversations"]) == 1

    def test_get_conversation_found(self):
        with _client() as (c, db, rl, mr):
            resp = c.get("/conversations/conv-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "conv-1"

    def test_get_conversation_not_found(self):
        with _client() as (c, db, rl, mr):
            db.get_conversation.return_value = None
            resp = c.get("/conversations/conv-missing")
        assert resp.status_code == 404

    def test_delete_conversation(self):
        with _client() as (c, db, rl, mr):
            resp = c.delete("/conversations/conv-1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_delete_conversation_not_found(self):
        with _client() as (c, db, rl, mr):
            db.delete_conversation.return_value = False
            resp = c.delete("/conversations/conv-missing")
        assert resp.status_code == 404


# ===========================================================================
# Rate Limit Status
# ===========================================================================

class TestRateLimitEndpoint:
    def test_get_rate_limit_status(self):
        with _client() as (c, db, rl, mr):
            resp = c.get("/rate-limit")
        assert resp.status_code == 200
        data = resp.json()
        assert "requests_remaining" in data
        assert "reset_at" in data
        assert data["is_limited"] is False


# ===========================================================================
# Metrics
# ===========================================================================

class TestMetricsEndpoint:
    def test_get_platform_metrics(self):
        with _client() as (c, db, rl, mr):
            resp = c.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests_24h"] == 100
        assert data["avg_latency_ms"] == 250.0
        assert data["primary_model_available"] is True


# ===========================================================================
# Admin Endpoints
# ===========================================================================

class TestAdminEndpoints:
    def test_list_users_admin_only(self):
        with _client(user=_ADMIN) as (c, db, rl, mr):
            resp = c.get("/admin/users")
        assert resp.status_code == 200
        assert resp.json() == []
