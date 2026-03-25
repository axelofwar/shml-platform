"""Unit tests for inference/chat-api — schemas, config, and rate limit logic.

Covers: app/schemas.py, app/config.py, app/rate_limit.py
No live Redis or DB required — rate limiter internals tested with mocked Redis.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure inference/chat-api/app is importable
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CHAT_API = _ROOT / "inference" / "chat-api"
for _p in [str(_ROOT), str(_CHAT_API)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Stub redis.asyncio before importing rate_limit
if "redis" not in sys.modules:
    _redis_mod = MagicMock()
    _redis_mod.asyncio = MagicMock()
    _redis_mod.asyncio.Redis = MagicMock
    sys.modules["redis"] = _redis_mod
    sys.modules["redis.asyncio"] = _redis_mod.asyncio

# ---------------------------------------------------------------------------
# Pre-import chat-api modules at collection time so sys.modules caches the
# correct paths before test_gateway.py (alphabetically later) adds its own
# inference/gateway path to sys.path.
# ---------------------------------------------------------------------------
import pydantic
import app.config as _chat_api_config
from app.schemas import (
    UserRole, User,
    APIKeyCreate, APIKey, APIKeyList,
    InstructionScope, InstructionCreate, UserInstruction, InstructionList,
    ModelSelection, ModelInfo, ModelsResponse,
    ChatMessage, RequestSource, ChatCompletionRequest,
    ChatCompletionChoice, ChatCompletionUsage, ChatCompletionResponse,
    RateLimitStatus,
    Conversation, ConversationSummary, ConversationList,
    ServiceHealth, HealthResponse,
    PlatformMetrics,
)
from app.rate_limit import RateLimiter, rate_limiter


# ===========================================================================
# Schema tests
# ===========================================================================


class TestUserRole:
    def test_enum_values(self):
        assert UserRole.ADMIN == "admin"
        assert UserRole.DEVELOPER == "developer"
        assert UserRole.VIEWER == "viewer"

    def test_enum_member_count(self):
        assert len(UserRole) == 3


class TestUserSchema:
    def test_minimal_user(self):
        u = User(id="uid-1")
        assert u.id == "uid-1"
        assert u.role == UserRole.VIEWER
        assert u.groups == []
        assert u.auth_method == "oauth"
        assert u.email is None
        assert u.api_key_id is None

    def test_user_all_fields(self):
        u = User(
            id="uid-2",
            email="dev@example.com",
            name="Dev User",
            role=UserRole.DEVELOPER,
            groups=["ml-team", "infra"],
            auth_method="api_key",
            api_key_id="key-abc",
        )
        assert u.email == "dev@example.com"
        assert u.role == UserRole.DEVELOPER
        assert "ml-team" in u.groups
        assert u.api_key_id == "key-abc"

    def test_invalid_auth_method_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            User(id="x", auth_method="bearer")

    def test_invalid_role_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            User(id="x", role="superuser")


class TestAPIKeySchemas:
    def test_create_minimal(self):
        req = APIKeyCreate(name="my-key")
        assert req.name == "my-key"
        assert req.description is None
        assert req.expires_at is None
        assert req.target_user_id is None
        assert req.target_role is None

    def test_create_name_too_short_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            APIKeyCreate(name="")

    def test_create_name_too_long_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            APIKeyCreate(name="x" * 101)

    def test_api_key_response_defaults(self):
        now = datetime.now(timezone.utc)
        key = APIKey(
            id="kid-1",
            name="test-key",
            user_id="uid-1",
            role=UserRole.DEVELOPER,
            created_at=now,
        )
        assert key.is_active is True
        assert key.key is None
        assert key.description is None
        assert key.expires_at is None
        assert key.last_used_at is None

    def test_api_key_with_secret(self):
        now = datetime.now(timezone.utc)
        key = APIKey(
            id="kid-2",
            name="k2",
            user_id="u2",
            role=UserRole.ADMIN,
            created_at=now,
            key="shml_secret_value",
        )
        assert key.key == "shml_secret_value"

    def test_api_key_list(self):
        now = datetime.now(timezone.utc)
        k = APIKey(id="k1", name="k1", user_id="u1", role=UserRole.ADMIN, created_at=now)
        lst = APIKeyList(keys=[k], total=1)
        assert lst.total == 1
        assert len(lst.keys) == 1


class TestInstructionSchemas:
    def test_instruction_scope_enum(self):
        assert InstructionScope.USER == "user"
        assert InstructionScope.PLATFORM == "platform"

    def test_create_instruction_defaults(self):
        inst = InstructionCreate(name="Rule 1", content="Be helpful.")
        assert inst.scope == InstructionScope.USER
        assert inst.priority == 0
        assert inst.is_active is True

    def test_create_instruction_content_too_long_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            InstructionCreate(name="x", content="y" * 10001)

    def test_create_instruction_empty_name_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            InstructionCreate(name="", content="content")

    def test_user_instruction_defaults(self):
        now = datetime.now(timezone.utc)
        item = UserInstruction(
            id="i1",
            user_id="u1",
            name="rule",
            content="be polite",
            created_at=now,
            updated_at=now,
        )
        assert item.scope == InstructionScope.USER
        assert item.priority == 0
        assert item.is_active is True

    def test_instruction_list(self):
        now = datetime.now(timezone.utc)
        item = UserInstruction(
            id="i1", user_id="u1", name="rule", content="be polite",
            created_at=now, updated_at=now,
        )
        lst = InstructionList(instructions=[item], total=1)
        assert lst.total == 1
        assert len(lst.instructions) == 1


class TestModelSchemas:
    def test_model_selection_enum(self):
        assert ModelSelection.AUTO == "auto"
        assert ModelSelection.PRIMARY == "primary"
        assert ModelSelection.FALLBACK == "fallback"
        assert ModelSelection.QUALITY == "quality"
        assert ModelSelection.FAST == "fast"

    def test_model_info(self):
        info = ModelInfo(
            id="qwen3-vl-8b",
            name="Qwen3-VL-8B",
            description="Local VLM",
            context_length=32768,
            is_available=True,
            gpu="RTX 2070",
            vram_gb=8,
            recommended_for=["coding"],
        )
        assert info.is_available is True
        assert info.vram_gb == 8

    def test_models_response_defaults(self):
        resp = ModelsResponse(data=[])
        assert resp.object == "list"
        assert resp.data == []


class TestChatSchemas:
    def test_chat_message_valid_roles(self):
        for role in ("system", "user", "assistant", "tool"):
            ChatMessage(role=role, content="hello")

    def test_chat_message_invalid_role_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            ChatMessage(role="bot", content="hi")

    def test_chat_message_optional_fields(self):
        msg = ChatMessage(role="assistant", content="ok", name="ast_1", tool_call_id="tc-1")
        assert msg.name == "ast_1"
        assert msg.tool_calls is None

    def test_completion_request_defaults(self):
        req = ChatCompletionRequest(messages=[ChatMessage(role="user", content="hello")])
        assert req.model == "auto"
        assert req.temperature == pytest.approx(0.7)
        assert req.top_p == pytest.approx(0.9)
        assert req.max_tokens == 4096
        assert req.stream is False
        assert req.include_instructions is True
        assert req.source == RequestSource.API

    def test_completion_request_temp_out_of_range_rejected(self):
        msgs = [ChatMessage(role="user", content="hi")]
        with pytest.raises(pydantic.ValidationError):
            ChatCompletionRequest(messages=msgs, temperature=2.1)

    def test_completion_request_negative_temp_rejected(self):
        msgs = [ChatMessage(role="user", content="hi")]
        with pytest.raises(pydantic.ValidationError):
            ChatCompletionRequest(messages=msgs, temperature=-0.1)

    def test_request_source_enum(self):
        assert RequestSource.WEB == "web"
        assert RequestSource.API == "api"

    def test_completion_choice(self):
        msg = ChatMessage(role="assistant", content="result")
        choice = ChatCompletionChoice(index=0, message=msg, finish_reason="stop")
        assert choice.finish_reason == "stop"

    def test_completion_usage(self):
        usage = ChatCompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        assert usage.total_tokens == 30

    def test_completion_response(self):
        msg = ChatMessage(role="assistant", content="done")
        choice = ChatCompletionChoice(index=0, message=msg, finish_reason="stop")
        usage = ChatCompletionUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8)
        resp = ChatCompletionResponse(
            id="chatcmpl-1",
            created=int(time.time()),
            model="qwen3-vl-8b",
            choices=[choice],
            usage=usage,
        )
        assert resp.object == "chat.completion"
        assert resp.model_selection == "auto"

    def test_rate_limit_status(self):
        now = datetime.now(timezone.utc)
        status = RateLimitStatus(
            requests_remaining=95,
            requests_limit=100,
            reset_at=now,
            is_limited=False,
            role=UserRole.DEVELOPER,
        )
        assert status.requests_remaining == 95
        assert status.is_limited is False


class TestConversationSchemas:
    def test_conversation_defaults(self):
        now = datetime.now(timezone.utc)
        conv = Conversation(id="conv-1", user_id="u-1", model="qwen3", created_at=now, updated_at=now)
        assert conv.messages == []
        assert conv.title is None
        assert conv.metadata is None

    def test_conversation_summary(self):
        now = datetime.now(timezone.utc)
        s = ConversationSummary(id="cs-1", model="auto", message_count=5, created_at=now, updated_at=now)
        assert s.message_count == 5

    def test_conversation_list(self):
        lst = ConversationList(conversations=[], total=0, has_more=False)
        assert lst.has_more is False


class TestHealthSchemas:
    def test_service_health_all_statuses(self):
        for status in ("healthy", "unhealthy", "degraded", "unknown"):
            ServiceHealth(name="redis", status=status)

    def test_health_response(self):
        sh = ServiceHealth(name="redis", status="healthy", latency_ms=1.5)
        hr = HealthResponse(status="healthy", version="0.1.0", services=[sh], uptime_seconds=3600.0)
        assert hr.status == "healthy"
        assert hr.uptime_seconds == 3600.0


class TestPlatformMetrics:
    def test_platform_metrics(self):
        m = PlatformMetrics(
            total_requests_24h=1000,
            total_tokens_24h=500000,
            avg_latency_ms=250.0,
            primary_model_available=True,
            fallback_model_available=True,
            active_users_24h=50,
            queue_length=3,
            gpu_utilization={"gpu_0": 0.75, "gpu_1": 0.45},
        )
        assert m.primary_model_available is True
        assert m.gpu_utilization["gpu_0"] == 0.75


# ===========================================================================
# Config tests
# ===========================================================================


class TestChatApiConfig:
    def test_server_defaults(self):
        assert _chat_api_config.HOST == "0.0.0.0"
        assert _chat_api_config.PORT == 8000

    def test_redis_defaults(self):
        assert _chat_api_config.REDIS_PORT == 6379
        assert _chat_api_config.REDIS_DB == 3

    def test_rate_limit_defaults(self):
        assert _chat_api_config.RATE_LIMIT_ADMIN == 0
        assert _chat_api_config.RATE_LIMIT_DEVELOPER == 100
        assert _chat_api_config.RATE_LIMIT_VIEWER == 20
        assert _chat_api_config.RATE_LIMIT_WINDOW_SECONDS == 60

    def test_api_key_defaults(self):
        assert _chat_api_config.API_KEY_PREFIX == "shml_"
        assert _chat_api_config.API_KEY_LENGTH == 48

    def test_ask_only_prompt_has_security_instructions(self):
        assert len(_chat_api_config.ASK_ONLY_SYSTEM_PROMPT) > 100
        assert "NEVER" in _chat_api_config.ASK_ONLY_SYSTEM_PROMPT

    def test_read_password_from_file(self, tmp_path):
        secret = tmp_path / "db_password"
        secret.write_text("filepassword\n")
        orig = _chat_api_config.POSTGRES_PASSWORD_FILE
        try:
            _chat_api_config.POSTGRES_PASSWORD_FILE = str(secret)
            assert _chat_api_config.read_password() == "filepassword"
        finally:
            _chat_api_config.POSTGRES_PASSWORD_FILE = orig

    def test_read_password_fallback_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("POSTGRES_PASSWORD", "envpassword")
        orig = _chat_api_config.POSTGRES_PASSWORD_FILE
        try:
            _chat_api_config.POSTGRES_PASSWORD_FILE = str(tmp_path / "nonexistent")
            assert _chat_api_config.read_password() == "envpassword"
        finally:
            _chat_api_config.POSTGRES_PASSWORD_FILE = orig

    def test_read_password_missing_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        orig = _chat_api_config.POSTGRES_PASSWORD_FILE
        try:
            _chat_api_config.POSTGRES_PASSWORD_FILE = str(tmp_path / "nonexistent")
            with pytest.raises(FileNotFoundError):
                _chat_api_config.read_password()
        finally:
            _chat_api_config.POSTGRES_PASSWORD_FILE = orig


# ===========================================================================
# Rate limiter tests
# ===========================================================================


class TestRateLimiter:
    def test_get_limit_all_roles(self):
        rl = RateLimiter()
        assert rl._get_limit(UserRole.ADMIN) == 0
        assert rl._get_limit(UserRole.DEVELOPER) == 100
        assert rl._get_limit(UserRole.VIEWER) == 20

    def test_limits_dict_has_all_roles(self):
        rl = RateLimiter()
        assert UserRole.ADMIN in rl.limits
        assert UserRole.DEVELOPER in rl.limits
        assert UserRole.VIEWER in rl.limits

    def test_global_singleton_exists(self):
        assert isinstance(rate_limiter, RateLimiter)

    @pytest.mark.asyncio
    async def test_check_admin_bypasses_redis(self):
        rl = RateLimiter()  # no redis — admin must not touch it
        status = await rl.check("admin-user", UserRole.ADMIN)
        assert isinstance(status, RateLimitStatus)
        assert status.is_limited is False
        assert status.requests_remaining == 999999
        assert status.requests_limit == 0
        assert status.role == UserRole.ADMIN

    @pytest.mark.asyncio
    async def test_check_developer_under_limit(self):
        rl = RateLimiter()
        mock_redis = AsyncMock()
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.zcard = AsyncMock(return_value=3)
        mock_redis.zrange = AsyncMock(return_value=[])
        rl.redis = mock_redis
        status = await rl.check("dev-user", UserRole.DEVELOPER)
        assert status.is_limited is False
        assert status.requests_remaining == 97
        assert status.requests_limit == 100

    @pytest.mark.asyncio
    async def test_check_viewer_at_limit(self):
        rl = RateLimiter()
        mock_redis = AsyncMock()
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.zcard = AsyncMock(return_value=20)
        mock_redis.zrange = AsyncMock(return_value=[])
        rl.redis = mock_redis
        status = await rl.check("viewer-user", UserRole.VIEWER)
        assert status.is_limited is True
        assert status.requests_remaining == 0

    @pytest.mark.asyncio
    async def test_record_admin_always_true(self):
        rl = RateLimiter()
        assert await rl.record("admin-user", UserRole.ADMIN) is True

    @pytest.mark.asyncio
    async def test_record_developer_allowed_adds_entry(self):
        rl = RateLimiter()
        mock_redis = AsyncMock()
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.zcard = AsyncMock(return_value=0)
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zadd = AsyncMock()
        mock_redis.expire = AsyncMock()
        rl.redis = mock_redis
        result = await rl.record("dev-user", UserRole.DEVELOPER)
        assert result is True
        mock_redis.zadd.assert_awaited_once()
        mock_redis.expire.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_viewer_blocked_at_limit(self):
        rl = RateLimiter()
        mock_redis = AsyncMock()
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.zcard = AsyncMock(return_value=20)
        mock_redis.zrange = AsyncMock(return_value=[])
        rl.redis = mock_redis
        assert await rl.record("viewer-user", UserRole.VIEWER) is False
