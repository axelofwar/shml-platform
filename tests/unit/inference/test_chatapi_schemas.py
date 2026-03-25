"""Unit tests for inference/chat-api/app/schemas.py.

Pure Pydantic schema validation — no HTTP calls, no DB, no GPU.
test_chat_api.py (alphabetically before this file) has already:
  - added inference/chat-api to sys.path
  - pre-imported app.schemas so we can import from it directly
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pytest

# Ensure inference/chat-api is on sys.path (idempotent if test_chat_api.py was first)
_CHAT_API = Path(__file__).parent.parent.parent.parent / "inference" / "chat-api"
if str(_CHAT_API) not in sys.path:
    sys.path.insert(0, str(_CHAT_API))

# Pre-import redis stub (test_chat_api.py does this first, but be safe)
if "redis" not in sys.modules:
    from unittest.mock import MagicMock as _MM
    sys.modules["redis"] = _MM(name="redis")
    sys.modules["redis.asyncio"] = _MM(name="redis.asyncio")

from app.schemas import (  # noqa: E402
    UserRole,
    User,
    APIKeyCreate,
    APIKey,
    APIKeyList,
    InstructionScope,
    UserInstruction,
    InstructionCreate,
    InstructionList,
    ModelSelection,
    ModelInfo,
    ModelsResponse,
    ChatMessage,
    RequestSource,
    ChatCompletionRequest,
    ChatCompletionChoice,
    ChatCompletionUsage,
    ChatCompletionResponse,
    Conversation,
    ConversationSummary,
    ConversationList,
    RateLimitStatus,
    PlatformMetrics,
    ServiceHealth,
    HealthResponse,
)

_NOW = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# UserRole
# ---------------------------------------------------------------------------

class TestUserRole:
    def test_values(self):
        assert UserRole.ADMIN == "admin"
        assert UserRole.DEVELOPER == "developer"
        assert UserRole.VIEWER == "viewer"

    def test_is_str_enum(self):
        assert isinstance(UserRole.ADMIN, str)

    def test_all_values(self):
        vals = {r.value for r in UserRole}
        assert vals == {"admin", "developer", "viewer"}


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class TestUser:
    def test_minimal_creation(self):
        u = User(id="user-1")
        assert u.id == "user-1"

    def test_defaults(self):
        u = User(id="u1")
        assert u.role == UserRole.VIEWER
        assert u.groups == []
        assert u.auth_method == "oauth"
        assert u.email is None
        assert u.name is None
        assert u.api_key_id is None

    def test_full_creation(self):
        u = User(
            id="u2",
            email="dev@example.com",
            name="Developer",
            role=UserRole.DEVELOPER,
            groups=["ml-team"],
            auth_method="api_key",
            api_key_id="key-123",
        )
        assert u.role == UserRole.DEVELOPER
        assert u.email == "dev@example.com"
        assert u.groups == ["ml-team"]


# ---------------------------------------------------------------------------
# APIKeyCreate
# ---------------------------------------------------------------------------

class TestAPIKeyCreate:
    def test_minimal(self):
        k = APIKeyCreate(name="my-key")
        assert k.name == "my-key"
        assert k.description is None
        assert k.expires_at is None

    def test_with_expiry(self):
        k = APIKeyCreate(name="ci-key", expires_at=_NOW)
        assert k.expires_at == _NOW

    def test_for_viewer_creation_by_admin(self):
        k = APIKeyCreate(
            name="viewer-key",
            target_role=UserRole.VIEWER,
            target_user_id="target-user-1",
        )
        assert k.target_role == UserRole.VIEWER

    def test_name_min_length_validated(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            APIKeyCreate(name="")  # min_length=1

    def test_name_max_length_validated(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            APIKeyCreate(name="a" * 101)  # max_length=100


# ---------------------------------------------------------------------------
# APIKey
# ---------------------------------------------------------------------------

class TestAPIKey:
    def _make(self, **kw):
        defaults = dict(
            id="key-id-1",
            name="test-key",
            user_id="user-1",
            role=UserRole.VIEWER,
            created_at=_NOW,
            is_active=True,
        )
        defaults.update(kw)
        return APIKey(**defaults)

    def test_basic_creation(self):
        k = self._make()
        assert k.id == "key-id-1"
        assert k.is_active is True

    def test_key_value_none_by_default(self):
        k = self._make()
        assert k.key is None

    def test_key_value_on_creation(self):
        k = self._make(key="shml_abcdef123456")
        assert k.key == "shml_abcdef123456"

    def test_optional_fields(self):
        k = self._make(description="My key", expires_at=_NOW)
        assert k.description == "My key"
        assert k.expires_at == _NOW


class TestAPIKeyList:
    def test_empty_list(self):
        kl = APIKeyList(keys=[], total=0)
        assert kl.total == 0
        assert kl.keys == []

    def test_with_keys(self):
        key = APIKey(id="k1", name="n", user_id="u1", role=UserRole.VIEWER, created_at=_NOW)
        kl = APIKeyList(keys=[key], total=1)
        assert kl.total == 1


# ---------------------------------------------------------------------------
# InstructionScope
# ---------------------------------------------------------------------------

class TestInstructionScope:
    def test_values(self):
        assert InstructionScope.USER == "user"
        assert InstructionScope.PLATFORM == "platform"


# ---------------------------------------------------------------------------
# UserInstruction
# ---------------------------------------------------------------------------

class TestUserInstruction:
    def test_creation(self):
        inst = UserInstruction(
            id="inst-1",
            user_id="user-1",
            name="My instructions",
            content="Always use type hints.",
            created_at=_NOW,
            updated_at=_NOW,
        )
        assert inst.scope == InstructionScope.USER
        assert inst.is_active is True
        assert inst.priority == 0

    def test_platform_scope(self):
        inst = UserInstruction(
            id="inst-2",
            user_id="admin-1",
            name="Platform",
            content="No sensitive data.",
            scope=InstructionScope.PLATFORM,
            created_at=_NOW,
            updated_at=_NOW,
        )
        assert inst.scope == InstructionScope.PLATFORM


class TestInstructionCreate:
    def test_defaults(self):
        ic = InstructionCreate(name="coding style", content="Use PEP8.")
        assert ic.scope == InstructionScope.USER
        assert ic.is_active is True
        assert ic.priority == 0

    def test_name_validation(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            InstructionCreate(name="", content="Test.")

    def test_content_validation(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            InstructionCreate(name="ok", content="")


# ---------------------------------------------------------------------------
# ModelSelection
# ---------------------------------------------------------------------------

class TestModelSelection:
    def test_values(self):
        assert ModelSelection.AUTO == "auto"
        assert ModelSelection.PRIMARY == "primary"
        assert ModelSelection.FALLBACK == "fallback"
        assert ModelSelection.QUALITY == "quality"
        assert ModelSelection.FAST == "fast"

    def test_is_str_enum(self):
        assert isinstance(ModelSelection.AUTO, str)


# ---------------------------------------------------------------------------
# ModelInfo
# ---------------------------------------------------------------------------

class TestModelInfo:
    def _make(self, **kw):
        defaults = dict(
            id="qwen3-30b",
            name="Qwen3 Coder 30B",
            description="High-quality model",
            context_length=16384,
            is_available=True,
            gpu="RTX 3090 Ti",
            vram_gb=24,
            recommended_for=["coding", "refactoring"],
        )
        defaults.update(kw)
        return ModelInfo(**defaults)

    def test_creation(self):
        m = self._make()
        assert m.id == "qwen3-30b"
        assert m.is_available is True

    def test_unavailable(self):
        m = self._make(is_available=False)
        assert m.is_available is False


class TestModelsResponse:
    def test_default_object(self):
        r = ModelsResponse(data=[])
        assert r.object == "list"
        assert r.data == []


# ---------------------------------------------------------------------------
# ChatMessage
# ---------------------------------------------------------------------------

class TestChatMessage:
    def test_user_message(self):
        m = ChatMessage(role="user", content="Hello")
        assert m.role == "user"
        assert m.content == "Hello"
        assert m.tool_calls is None

    def test_assistant_message(self):
        m = ChatMessage(role="assistant", content="Hi there!")
        assert m.role == "assistant"

    def test_system_message(self):
        m = ChatMessage(role="system", content="You are helpful.")
        assert m.role == "system"

    def test_tool_call_message(self):
        m = ChatMessage(
            role="tool",
            content="result",
            tool_call_id="call-123",
        )
        assert m.role == "tool"
        assert m.tool_call_id == "call-123"

    def test_message_with_tool_calls(self):
        tc = [{"id": "call-1", "type": "function", "function": {"name": "read_file"}}]
        m = ChatMessage(role="assistant", content="", tool_calls=tc)
        assert m.tool_calls == tc


# ---------------------------------------------------------------------------
# RequestSource
# ---------------------------------------------------------------------------

class TestRequestSource:
    def test_values(self):
        assert RequestSource.WEB == "web"
        assert RequestSource.API == "api"


# ---------------------------------------------------------------------------
# ChatCompletionRequest
# ---------------------------------------------------------------------------

class TestChatCompletionRequest:
    def _make(self, **kw):
        defaults = dict(messages=[ChatMessage(role="user", content="Hello")])
        defaults.update(kw)
        return ChatCompletionRequest(**defaults)

    def test_defaults(self):
        r = self._make()
        assert r.model == "auto"
        assert r.temperature == 0.7
        assert r.top_p == 0.9
        assert r.max_tokens == 4096
        assert r.stream is False
        assert r.source == RequestSource.API
        assert r.include_instructions is True

    def test_custom_model(self):
        r = self._make(model="primary")
        assert r.model == "primary"

    def test_streaming(self):
        r = self._make(stream=True)
        assert r.stream is True

    def test_web_source(self):
        r = self._make(source=RequestSource.WEB)
        assert r.source == RequestSource.WEB

    def test_temperature_bounds(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make(temperature=3.0)  # > 2

    def test_max_tokens_bounds(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make(max_tokens=50000)  # > 32768


# ---------------------------------------------------------------------------
# ChatCompletionUsage
# ---------------------------------------------------------------------------

class TestChatCompletionUsage:
    def test_creation(self):
        u = ChatCompletionUsage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150
        )
        assert u.total_tokens == 150


# ---------------------------------------------------------------------------
# ChatCompletionResponse
# ---------------------------------------------------------------------------

class TestChatCompletionResponse:
    def test_defaults_and_fields(self):
        r = ChatCompletionResponse(
            id="chatcmpl-1",
            created=1700000000,
            model="qwen3-30b",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="Hello!"),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=10, completion_tokens=5, total_tokens=15
            ),
        )
        assert r.object == "chat.completion"
        assert r.model_selection == "auto"
        assert r.conversation_id is None


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

class TestConversation:
    def test_creation(self):
        c = Conversation(
            id="conv-1",
            user_id="user-1",
            model="qwen3-30b",
            created_at=_NOW,
            updated_at=_NOW,
        )
        assert c.messages == []
        assert c.title is None


class TestConversationSummary:
    def test_creation(self):
        cs = ConversationSummary(
            id="conv-1",
            model="qwen3-30b",
            message_count=5,
            created_at=_NOW,
            updated_at=_NOW,
        )
        assert cs.preview is None
        assert cs.title is None

    def test_with_preview(self):
        cs = ConversationSummary(
            id="conv-2",
            model="auto",
            message_count=1,
            created_at=_NOW,
            updated_at=_NOW,
            preview="Hello, how are you?",
        )
        assert cs.preview == "Hello, how are you?"


class TestConversationList:
    def test_empty(self):
        cl = ConversationList(conversations=[], total=0, has_more=False)
        assert not cl.has_more

    def test_with_more(self):
        cl = ConversationList(conversations=[], total=100, has_more=True)
        assert cl.has_more


# ---------------------------------------------------------------------------
# RateLimitStatus
# ---------------------------------------------------------------------------

class TestRateLimitStatus:
    def test_unlimited(self):
        r = RateLimitStatus(
            requests_remaining=0,
            requests_limit=0,
            reset_at=_NOW,
            is_limited=False,
            role=UserRole.ADMIN,
        )
        assert r.requests_limit == 0  # 0 = unlimited

    def test_limited(self):
        r = RateLimitStatus(
            requests_remaining=5,
            requests_limit=100,
            reset_at=_NOW,
            is_limited=True,
            role=UserRole.VIEWER,
        )
        assert r.is_limited is True


# ---------------------------------------------------------------------------
# PlatformMetrics
# ---------------------------------------------------------------------------

class TestPlatformMetrics:
    def test_creation(self):
        m = PlatformMetrics(
            total_requests_24h=1000,
            total_tokens_24h=500000,
            avg_latency_ms=250.5,
            primary_model_available=True,
            fallback_model_available=True,
            active_users_24h=15,
            queue_length=3,
            gpu_utilization={"gpu_0": 0.75, "gpu_1": 0.45},
        )
        assert m.total_requests_24h == 1000
        assert m.gpu_utilization["gpu_0"] == 0.75


# ---------------------------------------------------------------------------
# ServiceHealth / HealthResponse
# ---------------------------------------------------------------------------

class TestServiceHealth:
    def test_healthy(self):
        s = ServiceHealth(name="llm", status="healthy", latency_ms=12.5)
        assert s.status == "healthy"

    def test_unhealthy_no_latency(self):
        s = ServiceHealth(name="db", status="unhealthy")
        assert s.latency_ms is None


class TestHealthResponse:
    def test_creation(self):
        h = HealthResponse(
            status="healthy",
            version="1.0.0",
            services=[ServiceHealth(name="llm", status="healthy")],
            uptime_seconds=3600.0,
        )
        assert h.status == "healthy"
        assert len(h.services) == 1

    def test_degraded(self):
        h = HealthResponse(
            status="degraded",
            version="1.0.0",
            services=[],
            uptime_seconds=100.0,
        )
        assert h.status == "degraded"
