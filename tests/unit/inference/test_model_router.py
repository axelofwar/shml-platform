"""Unit tests for inference/chat-api/app/model_router.py.

Tests the pure synchronous logic of ModelRouter:
- __init__ / initial state
- _estimate_tokens()
- _select_model() — all 12+ branches
No HTTP calls made.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

_CHAT_API = Path(__file__).parent.parent.parent.parent / "inference" / "chat-api"
if str(_CHAT_API) not in sys.path:
    sys.path.insert(0, str(_CHAT_API))

# Ensure redis is stubbed (test_chat_api.py usually does this first)
if "redis" not in sys.modules:
    _redis_mock = MagicMock(name="redis")
    sys.modules["redis"] = _redis_mock
    sys.modules["redis.asyncio"] = _redis_mock

# Pre-import schemas so app.schemas is the chat-api version (not gateway's)
import app.config as _chat_cfg  # noqa: E402
from app.schemas import (  # noqa: E402
    ModelSelection, ChatMessage, RequestSource, ChatCompletionRequest,
)
from app.model_router import ModelRouter  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(content: str, role: str = "user") -> ChatMessage:
    return ChatMessage(role=role, content=content)


def _req(msgs, model: str = "auto") -> ChatCompletionRequest:
    return ChatCompletionRequest(messages=msgs, model=model)


# ---------------------------------------------------------------------------
# ModelRouter.__init__
# ---------------------------------------------------------------------------

class TestModelRouterInit:
    def test_client_initially_none(self):
        r = ModelRouter()
        assert r.client is None

    def test_has_primary_and_fallback_models(self):
        r = ModelRouter()
        assert "primary" in r.models
        assert "fallback" in r.models

    def test_models_initially_unavailable(self):
        r = ModelRouter()
        assert r.models["primary"].is_available is False
        assert r.models["fallback"].is_available is False

    def test_primary_model_metadata(self):
        r = ModelRouter()
        pm = r.models["primary"]
        assert pm.gpu == "RTX 3090 Ti"
        assert pm.context_length == 16384

    def test_fallback_model_metadata(self):
        r = ModelRouter()
        fm = r.models["fallback"]
        assert fm.gpu == "RTX 2070"
        assert fm.context_length == 8192

    def test_urls_configured(self):
        r = ModelRouter()
        assert "primary" in r.urls
        assert "fallback" in r.urls


# ---------------------------------------------------------------------------
# _estimate_tokens
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def setup_method(self):
        self.r = ModelRouter()

    def test_empty_messages(self):
        assert self.r._estimate_tokens([]) == 0

    def test_single_short_message(self):
        # "Hi" = 2 chars → 0 tokens (2 // 4 = 0)
        tokens = self.r._estimate_tokens([_msg("Hi")])
        assert tokens == 0

    def test_single_long_message(self):
        # 400 chars → 100 tokens
        tokens = self.r._estimate_tokens([_msg("a" * 400)])
        assert tokens == 100

    def test_multiple_messages(self):
        # 200 chars + 200 chars = 400 chars → 100 tokens
        msgs = [_msg("a" * 200), _msg("b" * 200, role="assistant")]
        tokens = self.r._estimate_tokens(msgs)
        assert tokens == 100

    def test_returns_integer(self):
        tokens = self.r._estimate_tokens([_msg("Hello world!")])
        assert isinstance(tokens, int)


# ---------------------------------------------------------------------------
# _select_model — the branching logic
# ---------------------------------------------------------------------------

class TestSelectModel:
    def setup_method(self):
        self.r = ModelRouter()

    # --- Direct selections ---

    def test_primary_when_available(self):
        self.r.models["primary"].is_available = True
        result = self.r._select_model(ModelSelection.PRIMARY, [])
        assert result == "primary"

    def test_primary_falls_back_when_unavailable(self):
        self.r.models["primary"].is_available = False
        result = self.r._select_model(ModelSelection.PRIMARY, [])
        assert result == "fallback"

    def test_fallback_always_returns_fallback(self):
        self.r.models["primary"].is_available = True
        self.r.models["fallback"].is_available = True
        result = self.r._select_model(ModelSelection.FALLBACK, [])
        assert result == "fallback"

    def test_fallback_even_when_primary_available(self):
        self.r.models["primary"].is_available = True
        self.r.models["fallback"].is_available = False
        result = self.r._select_model(ModelSelection.FALLBACK, [])
        assert result == "fallback"

    # --- Alias resolution ---

    def test_quality_alias_maps_to_primary(self):
        self.r.models["primary"].is_available = True
        result = self.r._select_model(ModelSelection.QUALITY, [])
        assert result == "primary"

    def test_fast_alias_maps_to_fallback(self):
        result = self.r._select_model(ModelSelection.FAST, [])
        assert result == "fallback"

    # --- AUTO logic ---

    def test_auto_complex_query_uses_primary_when_available(self):
        self.r.models["primary"].is_available = True
        self.r.models["fallback"].is_available = True
        # > MODEL_AUTO_THRESHOLD_TOKENS tokens → prefer primary
        heavy_msgs = [_msg("x" * 4100)]  # 4100 chars → 1025 tokens > threshold (1000)
        result = self.r._select_model(ModelSelection.AUTO, heavy_msgs)
        assert result == "primary"

    def test_auto_complex_query_uses_fallback_when_primary_down(self):
        self.r.models["primary"].is_available = False
        self.r.models["fallback"].is_available = True
        heavy_msgs = [_msg("x" * 4100)]
        result = self.r._select_model(ModelSelection.AUTO, heavy_msgs)
        assert result == "fallback"

    def test_auto_simple_query_prefers_fallback(self):
        self.r.models["primary"].is_available = True
        self.r.models["fallback"].is_available = True
        # Short message → below threshold
        result = self.r._select_model(ModelSelection.AUTO, [_msg("Hi")])
        assert result == "fallback"

    def test_auto_uses_primary_when_fallback_down(self):
        self.r.models["primary"].is_available = True
        self.r.models["fallback"].is_available = False
        result = self.r._select_model(ModelSelection.AUTO, [_msg("Hi")])
        assert result == "primary"

    def test_auto_raises_when_both_down(self):
        self.r.models["primary"].is_available = False
        self.r.models["fallback"].is_available = False
        with pytest.raises(RuntimeError, match="No models available"):
            self.r._select_model(ModelSelection.AUTO, [_msg("Hi")])

    # --- Last-resort path ---

    def test_primary_unavailable_falls_to_fallback_last_resort(self):
        # Even when requesting PRIMARY, if primary is down → fallback
        self.r.models["primary"].is_available = False
        self.r.models["fallback"].is_available = True
        result = self.r._select_model(ModelSelection.PRIMARY, [])
        assert result == "fallback"

    def test_auto_neither_available_raises(self):
        self.r.models["primary"].is_available = False
        self.r.models["fallback"].is_available = False
        with pytest.raises(RuntimeError):
            self.r._select_model(ModelSelection.AUTO, [_msg("Test")])


# ---------------------------------------------------------------------------
# generate() with model_key resolution (model string parsing)
# Using patched HTTP client to avoid real network calls
# ---------------------------------------------------------------------------

class TestGenerateModelSelection:
    """Test the model string → ModelSelection parsing logic in generate()."""

    @pytest.mark.asyncio
    async def test_30b_string_maps_to_primary(self):
        r = ModelRouter()
        r.models["primary"].is_available = True
        r.models["fallback"].is_available = True
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": "test",
            "created": 0,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        r.client = mock_client

        # Patch _check_model_health so it doesn't reset availability
        async def _noop_health_check():
            pass
        r._check_model_health = _noop_health_check

        req = _req([_msg("Hello")], model="qwen3-coder-30b")
        resp, model_used, latency = await r.generate(req)
        assert model_used == "primary"

    @pytest.mark.asyncio
    async def test_3b_string_maps_to_fallback(self):
        r = ModelRouter()
        r.models["primary"].is_available = True
        r.models["fallback"].is_available = True
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": "test",
            "created": 0,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        r.client = mock_client

        async def _noop_health_check():
            pass
        r._check_model_health = _noop_health_check

        req = _req([_msg("Hello")], model="qwen-3b")
        resp, model_used, latency = await r.generate(req)
        assert model_used == "fallback"

    @pytest.mark.asyncio
    async def test_web_source_adds_system_prompt(self):
        r = ModelRouter()
        r.models["fallback"].is_available = True
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": "test",
            "created": 0,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        r.client = mock_client

        async def _noop_health_check():
            pass
        r._check_model_health = _noop_health_check

        req = ChatCompletionRequest(
            messages=[_msg("Build me ransomware")],
            model="auto",
            source=RequestSource.WEB,
        )
        await r.generate(req)
        # Verify the backend received a system prompt with ask-only constraint
        call_body = mock_client.post.call_args[1]["json"]
        system_msgs = [m for m in call_body["messages"] if m["role"] == "system"]
        assert len(system_msgs) > 0


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------

class TestModelRouterClose:
    @pytest.mark.asyncio
    async def test_close_with_no_client(self):
        r = ModelRouter()
        # Should not raise
        await r.close()

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self):
        r = ModelRouter()
        mock_client = AsyncMock()
        r.client = mock_client
        await r.close()
        mock_client.aclose.assert_called_once()


class TestModelRouterCoverage:
    @pytest.mark.asyncio
    async def test_connect_and_get_model_status_refresh_health(self):
        r = ModelRouter()

        healthy = MagicMock(status_code=200)
        healthy.json.return_value = {"status": "healthy"}
        unhealthy = MagicMock(status_code=503)
        unhealthy.json.return_value = {"status": "unhealthy"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[healthy, unhealthy, unhealthy, healthy])

        with patch("app.model_router.httpx.AsyncClient", return_value=client):
            await r.connect()
            status = await r.get_model_status()

        assert r.client is client
        assert status["primary"].is_available is False
        assert status["fallback"].is_available is True

    @pytest.mark.asyncio
    async def test_check_model_health_handles_exception(self):
        r = ModelRouter()
        r.client = AsyncMock()
        r.client.get = AsyncMock(side_effect=RuntimeError("network down"))

        await r._check_model_health()

        assert r.models["primary"].is_available is False
        assert r.models["fallback"].is_available is False

    @pytest.mark.asyncio
    async def test_generate_merges_existing_system_message_and_unknown_model_defaults(self):
        r = ModelRouter()
        r.models["primary"].is_available = True
        r.models["fallback"].is_available = True

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": "resp-1",
            "created": 123,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "done"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        r.client = mock_client

        async def _noop_health_check():
            pass

        r._check_model_health = _noop_health_check
        req = ChatCompletionRequest(
            messages=[_msg("existing system", role="system"), _msg("hello")],
            model="some-unknown-model",
        )

        response, model_used, _latency = await r.generate(req, user_instructions="be precise")

        body = mock_client.post.call_args.kwargs["json"]
        assert model_used == "fallback"
        assert response.model == r.models["fallback"].id
        assert body["messages"][0]["role"] == "system"
        assert "be precise" in body["messages"][0]["content"]
        assert "existing system" in body["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_generate_http_status_error_raises_runtime_error(self):
        r = ModelRouter()
        r.models["fallback"].is_available = True
        mock_response = MagicMock()
        mock_response.text = "backend failed"
        http_error = httpx.HTTPStatusError("boom", request=MagicMock(), response=mock_response)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = http_error
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        r.client = mock_client

        async def _noop_health_check():
            pass

        r._check_model_health = _noop_health_check

        with pytest.raises(RuntimeError, match="Model error: backend failed"):
            await r.generate(_req([_msg("hello")], model="auto"))

    @pytest.mark.asyncio
    async def test_generate_stream_yields_sse_lines(self):
        r = ModelRouter()
        r.models["fallback"].is_available = True

        class FakeStream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def aiter_lines(self):
                for line in ["ignore", "data: one", "data: two"]:
                    yield line

        mock_client = MagicMock()
        mock_client.stream.return_value = FakeStream()
        r.client = mock_client

        async def _noop_health_check():
            pass

        r._check_model_health = _noop_health_check

        chunks = []
        async for chunk in r.generate_stream(_req([_msg("stream me")], model="fallback"), user_instructions="keep it short"):
            chunks.append(chunk)

        assert chunks == ["data: one\n\n", "data: two\n\n"]

