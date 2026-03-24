"""Unit tests for inference/common — shared schemas and base config.

Covers: inference/common/schemas.py, inference/common/base_config.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure inference/ is importable
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_INFERENCE = _ROOT / "inference"
for _p in [str(_ROOT), str(_INFERENCE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ===========================================================================
# inference/common/schemas.py
# ===========================================================================


class TestHealthResponse:
    def test_defaults(self):
        from common.schemas import HealthResponse
        hr = HealthResponse(service="qwen3-vl")
        assert hr.status == "healthy"
        assert hr.version == "1.0.0"
        assert hr.model_loaded is None
        assert hr.gpu_available is None

    def test_all_fields(self):
        from common.schemas import HealthResponse
        hr = HealthResponse(
            service="z-image",
            status="degraded",
            version="2.0.0",
            model_loaded=True,
            gpu_available=True,
        )
        assert hr.status == "degraded"
        assert hr.model_loaded is True
        assert hr.gpu_available is True


class TestErrorResponse:
    def test_minimal(self):
        from common.schemas import ErrorResponse
        err = ErrorResponse(error="Something went wrong")
        assert err.error == "Something went wrong"
        assert err.detail is None
        assert err.code is None

    def test_full(self):
        from common.schemas import ErrorResponse
        err = ErrorResponse(error="Rate limited", detail="Try again later", code="RATE_LIMIT")
        assert err.code == "RATE_LIMIT"
        assert err.detail == "Try again later"


class TestCommonChatMessage:
    def test_minimal(self):
        from common.schemas import ChatMessage
        msg = ChatMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.name is None

    def test_with_name(self):
        from common.schemas import ChatMessage
        msg = ChatMessage(role="assistant", content="hi", name="assistant_1")
        assert msg.name == "assistant_1"


class TestCommonChatCompletionRequest:
    def test_defaults(self):
        from common.schemas import ChatCompletionRequest, ChatMessage
        req = ChatCompletionRequest(
            model="qwen3-vl-8b",
            messages=[ChatMessage(role="user", content="hello")],
        )
        assert req.temperature == pytest.approx(0.7)
        assert req.top_p == pytest.approx(0.95)
        assert req.max_tokens == 4096
        assert req.stream is False
        assert req.stop is None

    def test_custom_params(self):
        from common.schemas import ChatCompletionRequest, ChatMessage
        req = ChatCompletionRequest(
            model="nemotron",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.1,
            max_tokens=100,
            stream=True,
            stop=["<|end|>"],
        )
        assert req.temperature == pytest.approx(0.1)
        assert req.max_tokens == 100
        assert req.stream is True
        assert req.stop == ["<|end|>"]


class TestCommonChatCompletionChoice:
    def test_creation(self):
        from common.schemas import ChatCompletionChoice, ChatMessage
        msg = ChatMessage(role="assistant", content="Hello!")
        choice = ChatCompletionChoice(index=0, message=msg, finish_reason="stop")
        assert choice.index == 0
        assert choice.finish_reason == "stop"
        assert choice.message.content == "Hello!"


class TestUsage:
    def test_token_counts(self):
        from common.schemas import Usage
        u = Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        assert u.prompt_tokens == 10
        assert u.completion_tokens == 20
        assert u.total_tokens == 30


class TestCommonChatCompletionResponse:
    def test_full_response(self):
        from common.schemas import (
            ChatCompletionResponse, ChatCompletionChoice, ChatMessage, Usage,
        )
        msg = ChatMessage(role="assistant", content="42")
        choice = ChatCompletionChoice(index=0, message=msg, finish_reason="stop")
        usage = Usage(prompt_tokens=5, completion_tokens=1, total_tokens=6)
        resp = ChatCompletionResponse(
            id="resp-001",
            created=int(time.time()),
            model="qwen3-vl-8b",
            choices=[choice],
            usage=usage,
        )
        assert resp.object == "chat.completion"
        assert len(resp.choices) == 1
        assert resp.usage.total_tokens == 6


# ===========================================================================
# inference/common/base_config.py
# ===========================================================================


class TestGetPostgresPassword:
    def test_from_file(self, tmp_path):
        pw_file = tmp_path / "pg_password"
        pw_file.write_text("supersecret\n")
        with patch.dict(os.environ, {"POSTGRES_PASSWORD_FILE": str(pw_file)}):
            from common import base_config
            import importlib
            importlib.reload(base_config)
            assert base_config.get_postgres_password() == "supersecret"

    def test_from_env_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("POSTGRES_PASSWORD", "envpw")
        monkeypatch.delenv("POSTGRES_PASSWORD_FILE", raising=False)
        from common.base_config import get_postgres_password
        assert get_postgres_password() == "envpw"

    def test_empty_when_no_source(self, tmp_path, monkeypatch):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD_FILE", raising=False)
        from common.base_config import get_postgres_password
        assert get_postgres_password() == ""


class TestBaseInferenceSettings:
    """BaseInferenceSettings reads from .env by default — use _env_file=None to skip."""

    def test_default_host_port(self, monkeypatch):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD_FILE", raising=False)
        from common.base_config import BaseInferenceSettings
        settings = BaseInferenceSettings(_env_file=None)
        assert settings.HOST == "0.0.0.0"
        assert settings.PORT == 8000

    def test_database_url_property(self, monkeypatch):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD_FILE", raising=False)
        from common.base_config import BaseInferenceSettings
        settings = BaseInferenceSettings(
            _env_file=None,
            POSTGRES_USER="testuser",
            POSTGRES_HOST="db-host",
            POSTGRES_PORT=5432,
            POSTGRES_DB="testdb",
        )
        url = settings.database_url
        assert "postgresql+asyncpg://" in url
        assert "testuser" in url
        assert "db-host" in url
        assert "testdb" in url

    def test_redis_url_no_password(self, monkeypatch):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD_FILE", raising=False)
        from common.base_config import BaseInferenceSettings
        settings = BaseInferenceSettings(_env_file=None, REDIS_HOST="redis-host", REDIS_PORT=6379)
        url = settings.redis_url
        assert url == "redis://redis-host:6379"

    def test_redis_url_with_password(self, monkeypatch):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD_FILE", raising=False)
        from common.base_config import BaseInferenceSettings
        settings = BaseInferenceSettings(
            _env_file=None,
            REDIS_HOST="redis-host",
            REDIS_PORT=6379,
            REDIS_PASSWORD="redispass",
        )
        url = settings.redis_url
        assert "redispass" in url
        assert "redis://" in url
