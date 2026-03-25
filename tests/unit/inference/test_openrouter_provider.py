"""Unit tests for inference/router/providers/openrouter.py.

Pure method tests — no HTTP calls. Covers:
- Class attributes and model catalog
- __init__ with and without API key
- _format_messages() conversion
- list_models() / get_model()
- health_check() with no API key (no HTTP)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_INFERENCE = Path(__file__).parent.parent.parent.parent / "inference"
if str(_INFERENCE) not in sys.path:
    sys.path.insert(0, str(_INFERENCE))

# ---------------------------------------------------------------------------
# Stub router.providers.*  — clear any prior stubs from test_openrouter_provider
# being collected.  test_local_provider.py (l < o alphabetically) runs BEFORE
# this file.  test_local_provider.py may have already set router.providers as a
# real package, but it pops the sub-modules.  We make sure they are set.
# ---------------------------------------------------------------------------
for _key in [
    "router.providers.openrouter",
    "inference.router.providers.openrouter",
]:
    sys.modules.pop(_key, None)

# Ensure router.providers exists as a real package (with __path__) so Python
# can locate the filesystem submodule for openrouter.py.
if "router.providers" not in sys.modules or not hasattr(
    sys.modules["router.providers"], "__path__"
):
    import types as _types
    _providers_pkg = _types.ModuleType("router.providers")
    _providers_pkg.__path__ = [str(_INFERENCE / "router" / "providers")]
    _providers_pkg.__package__ = "router.providers"
    _providers_pkg.GeminiProvider = MagicMock()
    _providers_pkg.GitHubCopilotProvider = MagicMock()
    _providers_pkg.LocalProvider = MagicMock()
    _providers_pkg.OpenRouterProvider = MagicMock()  # placeholder
    sys.modules["router.providers"] = _providers_pkg

# Stub sibling heavy providers
for _mod in [
    "router.providers.gemini", "router.providers.github_copilot",
    "router.providers.local",
    "inference.router.providers.gemini",
    "inference.router.providers.github_copilot",
    "inference.router.providers.local",
]:
    sys.modules.setdefault(_mod, MagicMock())

# Load the real openrouter module
from router.providers.openrouter import OpenRouterProvider  # noqa: E402
from router.base import (  # noqa: E402
    ModelCapability, ProviderType, Message, CompletionRequest, ModelInfo,
    ProviderError,
)


# ---------------------------------------------------------------------------
# Class attributes
# ---------------------------------------------------------------------------

class TestOpenRouterClass:
    def test_name(self):
        assert OpenRouterProvider.name == "openrouter"

    def test_provider_type(self):
        assert OpenRouterProvider.provider_type == ProviderType.CLOUD_FRONTIER

    def test_base_url(self):
        assert "openrouter.ai" in OpenRouterProvider.BASE_URL

    def test_models_not_empty(self):
        assert len(OpenRouterProvider.MODELS) > 0

    def test_claude_in_models(self):
        assert "anthropic/claude-3.5-sonnet" in OpenRouterProvider.MODELS

    def test_gpt4o_in_models(self):
        assert "openai/gpt-4o" in OpenRouterProvider.MODELS

    def test_deepseek_in_models(self):
        assert "deepseek/deepseek-r1" in OpenRouterProvider.MODELS


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestOpenRouterInit:
    def test_no_api_key_env(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        p = OpenRouterProvider()
        assert p.api_key is None

    def test_explicit_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        p = OpenRouterProvider(api_key="or-test-key")
        assert p.api_key == "or-test-key"

    def test_env_api_key(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-env-key")
        p = OpenRouterProvider()
        assert p.api_key == "or-env-key"

    def test_default_model(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        p = OpenRouterProvider()
        assert p.default_model == "openai/gpt-4o-mini"

    def test_custom_default_model(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        p = OpenRouterProvider(default_model="deepseek/deepseek-r1")
        assert p.default_model == "deepseek/deepseek-r1"

    def test_explicit_api_key_takes_priority(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
        p = OpenRouterProvider(api_key="explicit-key")
        assert p.api_key == "explicit-key"

    def test_client_initially_none(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        p = OpenRouterProvider()
        assert p._client is None


# ---------------------------------------------------------------------------
# list_models / get_model
# ---------------------------------------------------------------------------

class TestOpenRouterModels:
    def setup_method(self):
        os.environ.pop("OPENROUTER_API_KEY", None)
        self.p = OpenRouterProvider()

    def test_list_models_returns_all(self):
        models = self.p.list_models()
        assert len(models) == len(OpenRouterProvider.MODELS)

    def test_list_models_are_model_info(self):
        for m in self.p.list_models():
            assert isinstance(m, ModelInfo)

    def test_get_model_found(self):
        m = self.p.get_model("openai/gpt-4o")
        assert m is not None
        assert m.id == "openai/gpt-4o"

    def test_get_model_not_found(self):
        m = self.p.get_model("nonexistent/model")
        assert m is None

    def test_claude_has_vision_capability(self):
        m = self.p.get_model("anthropic/claude-3.5-sonnet")
        assert ModelCapability.VISION in m.capabilities

    def test_gpt4o_mini_provider_type(self):
        m = self.p.get_model("openai/gpt-4o-mini")
        assert m.provider_type == ProviderType.CLOUD_BUDGET

    def test_deepseek_no_tool_support(self):
        m = self.p.get_model("deepseek/deepseek-r1")
        assert m.supports_tools is False

    def test_claude_supports_tools(self):
        m = self.p.get_model("anthropic/claude-3.5-sonnet")
        assert m.supports_tools is True


# ---------------------------------------------------------------------------
# _format_messages
# ---------------------------------------------------------------------------

class TestOpenRouterFormatMessages:
    def setup_method(self):
        os.environ.pop("OPENROUTER_API_KEY", None)
        self.p = OpenRouterProvider()

    def test_single_user_message(self):
        msgs = [Message(role="user", content="Hello")]
        result = self.p._format_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"

    def test_system_message_preserved(self):
        msgs = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="Hi"),
        ]
        result = self.p._format_messages(msgs)
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    def test_assistant_message_preserved(self):
        msgs = [
            Message(role="user", content="Say hi"),
            Message(role="assistant", content="Hi!"),
        ]
        result = self.p._format_messages(msgs)
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == "Hi!"

    def test_message_with_images(self):
        msgs = [Message(role="user", content="What is this?", images=["base64data"])]
        result = self.p._format_messages(msgs)
        # With images, content should be a list
        assert isinstance(result[0]["content"], list)
        text_parts = [p for p in result[0]["content"] if p.get("type") == "text"]
        image_parts = [p for p in result[0]["content"] if p.get("type") == "image_url"]
        assert len(text_parts) == 1
        assert len(image_parts) == 1
        assert "base64data" in image_parts[0]["image_url"]["url"]

    def test_multiple_images_per_message(self):
        msgs = [Message(role="user", content="Compare", images=["img1", "img2"])]
        result = self.p._format_messages(msgs)
        image_parts = [p for p in result[0]["content"] if p.get("type") == "image_url"]
        assert len(image_parts) == 2

    def test_empty_messages(self):
        result = self.p._format_messages([])
        assert result == []


# ---------------------------------------------------------------------------
# health_check with no API key (sync path only)
# ---------------------------------------------------------------------------

class TestOpenRouterHealthNoKey:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_unavailable(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        p = OpenRouterProvider()
        status = await p.health_check()
        assert status.available is False
        assert "key" in (status.error or "").lower()
