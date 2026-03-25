from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_INFERENCE = _ROOT / "inference"

for _path in [str(_ROOT), str(_INFERENCE)]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

for _key in [
    "router.providers",
    "router.providers.gemini",
    "router.providers.local",
    "router.providers.openrouter",
    "router.providers.github_copilot",
    "inference.router.providers",
    "inference.router.providers.gemini",
    "inference.router.providers.local",
    "inference.router.providers.openrouter",
    "inference.router.providers.github_copilot",
]:
    sys.modules.pop(_key, None)

from router.base import CompletionRequest, ModelCapability, Message, ProviderError  # noqa: E402
from router.providers.gemini import GeminiProvider  # noqa: E402
from router.providers.github_copilot import (  # noqa: E402
    GitHubCopilotProvider,
    install_copilot_extension,
)
from router.providers.local import LocalProvider  # noqa: E402
from router.providers.openrouter import OpenRouterProvider  # noqa: E402


def _request(*messages: Message, **kwargs) -> CompletionRequest:
    return CompletionRequest(messages=list(messages), **kwargs)


def _message(role: str, content: str, images=None) -> Message:
    return Message(role=role, content=content, images=images)


def _http_response(status_code: int, payload=None, text: str = "payload"):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload if payload is not None else {}
    return response


class _AsyncStreamResponse:
    def __init__(self, status_code: int, lines: list[str]):
        self.status_code = status_code
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class TestGeminiRuntime:
    @pytest.mark.asyncio
    async def test_complete_success_with_tool_call(self):
        provider = GeminiProvider(api_key="key")
        provider._client = MagicMock()
        provider._client.post = AsyncMock(
            return_value=_http_response(
                200,
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "hello"},
                                    {"functionCall": {"name": "read_file"}},
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 100,
                        "candidatesTokenCount": 25,
                    },
                },
            )
        )
        response = await provider.complete(
            _request(_message("user", "hi"), max_tokens=50, tools=[{"name": "read_file"}])
        )
        assert response.content == "hello"
        assert response.tool_calls == [{"name": "read_file"}]
        assert response.usage["input_tokens"] == 100

    @pytest.mark.asyncio
    async def test_complete_missing_api_key(self):
        provider = GeminiProvider(api_key=None)
        with pytest.raises(ProviderError, match="No API key"):
            await provider.complete(_request(_message("user", "hi")))

    @pytest.mark.asyncio
    async def test_complete_rate_limit(self):
        provider = GeminiProvider(api_key="key")
        provider._client = MagicMock()
        provider._client.post = AsyncMock(return_value=_http_response(429))
        with pytest.raises(Exception, match="Rate limit"):
            await provider.complete(_request(_message("user", "hi")))

    @pytest.mark.asyncio
    async def test_complete_quota_exceeded(self):
        provider = GeminiProvider(api_key="key")
        provider._client = MagicMock()
        provider._client.post = AsyncMock(return_value=_http_response(403))
        with pytest.raises(Exception, match="Quota exceeded"):
            await provider.complete(_request(_message("user", "hi")))

    @pytest.mark.asyncio
    async def test_complete_no_candidates(self):
        provider = GeminiProvider(api_key="key")
        provider._client = MagicMock()
        provider._client.post = AsyncMock(return_value=_http_response(200, {"candidates": []}))
        with pytest.raises(ProviderError, match="No response generated"):
            await provider.complete(_request(_message("user", "hi")))

    @pytest.mark.asyncio
    async def test_complete_timeout(self):
        provider = GeminiProvider(api_key="key")
        provider._client = MagicMock()
        provider._client.post = AsyncMock(side_effect=httpx.TimeoutException("slow"))
        with pytest.raises(ProviderError, match="timed out"):
            await provider.complete(_request(_message("user", "hi")))

    @pytest.mark.asyncio
    async def test_stream_success(self):
        provider = GeminiProvider(api_key="key")
        provider._client = MagicMock()
        provider._client.stream.return_value = _AsyncStreamResponse(
            200,
            [
                'data: {"candidates":[{"content":{"parts":[{"text":"hel"}]}}]}',
                'data: {"candidates":[{"content":{"parts":[{"text":"lo"}]}}],"usageMetadata":{"promptTokenCount":20,"candidatesTokenCount":5}}',
            ],
        )
        chunks = [chunk async for chunk in provider.stream(_request(_message("user", "hi")))]
        assert [chunk.content for chunk in chunks] == ["hel", "lo", "hello"]
        assert chunks[-1].is_partial is False

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        provider = GeminiProvider(api_key="key")
        provider._client = MagicMock()
        provider._client.get = AsyncMock(return_value=_http_response(200))
        status = await provider.health_check()
        assert status.available is True

    @pytest.mark.asyncio
    async def test_close(self):
        provider = GeminiProvider(api_key="key")
        mock_client = MagicMock()
        mock_client.aclose = AsyncMock()
        provider._client = mock_client
        await provider.close()
        mock_client.aclose.assert_awaited_once()
        assert provider._client is None


class TestLocalRuntime:
    @pytest.mark.asyncio
    async def test_complete_auto_selects_qwen_for_images(self):
        provider = LocalProvider()
        provider._client = MagicMock()
        provider._client.post = AsyncMock(
            return_value=_http_response(
                200,
                {
                    "choices": [{"message": {"content": "vision-result"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                },
            )
        )
        response = await provider.complete(_request(_message("user", "look", images=["abc"])))
        assert response.model == "qwen3-vl-8b"
        assert response.content == "vision-result"

    @pytest.mark.asyncio
    async def test_complete_uses_required_capability(self):
        provider = LocalProvider()
        provider._client = MagicMock()
        provider._client.post = AsyncMock(
            return_value=_http_response(
                200,
                {
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        )
        response = await provider.complete(
            CompletionRequest(
                messages=[_message("user", "describe")],
                required_capabilities=[ModelCapability.VISION],
            )
        )
        assert response.model == "qwen3-vl-8b"

    @pytest.mark.asyncio
    async def test_complete_non_200_raises(self):
        provider = LocalProvider()
        provider._client = MagicMock()
        provider._client.post = AsyncMock(return_value=_http_response(500, text="bad"))
        with pytest.raises(ProviderError, match="Local API error"):
            await provider.complete(_request(_message("user", "hi")))

    @pytest.mark.asyncio
    async def test_complete_timeout_raises_recoverable(self):
        provider = LocalProvider()
        provider._client = MagicMock()
        provider._client.post = AsyncMock(side_effect=httpx.TimeoutException("slow"))
        with pytest.raises(ProviderError, match="timed out"):
            await provider.complete(_request(_message("user", "hi")))

    @pytest.mark.asyncio
    async def test_stream_success_with_invalid_json_ignored(self):
        provider = LocalProvider()
        provider._client = MagicMock()
        provider._client.stream.return_value = _AsyncStreamResponse(
            200,
            [
                "data: {bad-json}",
                'data: {"choices":[{"delta":{"content":"hel"}}]}',
                'data: {"choices":[{"delta":{"content":"lo"}}]}',
                "data: [DONE]",
            ],
        )
        chunks = [chunk async for chunk in provider.stream(_request(_message("user", "hi")))]
        assert [chunk.content for chunk in chunks] == ["hel", "lo", "hello"]

    @pytest.mark.asyncio
    async def test_health_check_partial_success(self):
        provider = LocalProvider()
        provider._client = MagicMock()
        provider._client.get = AsyncMock(side_effect=[_http_response(200), _http_response(503)])
        status = await provider.health_check()
        assert status.available is True
        assert "HTTP 503" in (status.error or "")

    @pytest.mark.asyncio
    async def test_health_check_all_fail(self):
        provider = LocalProvider()
        provider._client = MagicMock()
        provider._client.get = AsyncMock(side_effect=[RuntimeError("down1"), RuntimeError("down2")])
        status = await provider.health_check()
        assert status.available is False


class TestOpenRouterRuntime:
    @pytest.mark.asyncio
    async def test_complete_success(self):
        provider = OpenRouterProvider(api_key="key")
        provider._client = MagicMock()
        provider._client.post = AsyncMock(
            return_value=_http_response(
                200,
                {
                    "choices": [{"message": {"content": "done", "tool_calls": [{"id": "1"}]}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10},
                },
            )
        )
        response = await provider.complete(_request(_message("user", "hi")))
        assert response.content == "done"
        assert response.tool_calls == [{"id": "1"}]

    @pytest.mark.asyncio
    async def test_complete_no_key(self):
        provider = OpenRouterProvider(api_key=None)
        with pytest.raises(ProviderError, match="No API key"):
            await provider.complete(_request(_message("user", "hi")))

    @pytest.mark.asyncio
    async def test_complete_rate_limit(self):
        provider = OpenRouterProvider(api_key="key")
        provider._client = MagicMock()
        provider._client.post = AsyncMock(return_value=_http_response(429))
        with pytest.raises(Exception, match="Rate limit"):
            await provider.complete(_request(_message("user", "hi")))

    @pytest.mark.asyncio
    async def test_stream_success(self):
        provider = OpenRouterProvider(api_key="key")
        provider._client = MagicMock()
        provider._client.stream.return_value = _AsyncStreamResponse(
            200,
            [
                'data: {"choices":[{"delta":{"content":"hi"}}]}',
                'data: {"choices":[{"delta":{"content":"!"}}]}',
                'data: [DONE]',
            ],
        )
        chunks = [chunk async for chunk in provider.stream(_request(_message("user", "hi")))]
        assert [chunk.content for chunk in chunks] == ["hi", "!", "hi!"]
        assert chunks[-1].usage["output_tokens"] == len("hi!") // 4

    @pytest.mark.asyncio
    async def test_health_check_and_fetch_models(self):
        provider = OpenRouterProvider(api_key="key")
        provider._client = MagicMock()
        provider._client.get = AsyncMock(return_value=_http_response(200, {"data": []}))
        status = await provider.health_check()
        models = await provider.fetch_models()
        assert status.available is True
        assert len(models) == len(provider.MODELS)


class TestGitHubCopilotRuntime:
    @pytest.mark.asyncio
    async def test_check_copilot_installed_success(self):
        provider = GitHubCopilotProvider()
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        with patch("router.providers.github_copilot.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            assert await provider._check_copilot_installed() is True

    @pytest.mark.asyncio
    async def test_check_copilot_installed_missing_binary(self):
        provider = GitHubCopilotProvider()
        with patch("router.providers.github_copilot.asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            assert await provider._check_copilot_installed() is False

    @pytest.mark.asyncio
    async def test_run_copilot_success(self):
        provider = GitHubCopilotProvider()
        provider._copilot_available = True
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"answer", b""))
        with patch("router.providers.github_copilot.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            output = await provider._run_copilot("suggest", "prompt")
        assert output == "answer"

    @pytest.mark.asyncio
    async def test_run_copilot_timeout(self):
        provider = GitHubCopilotProvider()
        provider._copilot_available = True
        proc = MagicMock()
        proc.communicate = AsyncMock()
        with patch("router.providers.github_copilot.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)), \
             patch("router.providers.github_copilot.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with pytest.raises(ProviderError, match="timed out"):
                await provider._run_copilot("suggest", "prompt")

    @pytest.mark.asyncio
    async def test_complete_uses_explain_command(self):
        provider = GitHubCopilotProvider()
        with patch.object(provider, "_run_copilot", new=AsyncMock(return_value="explained")) as mock_run:
            response = await provider.complete(
                _request(_message("user", "why?"), model="copilot-explain")
            )
        mock_run.assert_awaited_once()
        assert response.content == "explained"

    @pytest.mark.asyncio
    async def test_complete_requires_user_message(self):
        provider = GitHubCopilotProvider()
        with pytest.raises(ProviderError, match="No user message"):
            await provider.complete(_request(_message("assistant", "hi")))

    @pytest.mark.asyncio
    async def test_stream_yields_single_response(self):
        provider = GitHubCopilotProvider()
        with patch.object(provider, "complete", new=AsyncMock(return_value=MagicMock(content="ok", model="m", provider="github_copilot", usage={}, cost=0.0, latency_ms=1))):
            chunks = [chunk async for chunk in provider.stream(_request(_message("user", "hi")))]
        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_health_check_unavailable(self):
        provider = GitHubCopilotProvider()
        with patch.object(provider, "_check_copilot_installed", new=AsyncMock(return_value=False)):
            status = await provider.health_check()
        assert status.available is False

    @pytest.mark.asyncio
    async def test_install_helper(self):
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        with patch("router.providers.github_copilot.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            assert await install_copilot_extension() is True
