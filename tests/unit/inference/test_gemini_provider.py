"""Unit tests for inference/router/providers/gemini.py.

Pure method tests — no HTTP calls. Covers:
- Class attributes and model catalog
- __init__ with and without API key
- _format_messages() conversion (system, user, images)
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

# Stub sibling providers that we don't need for gemini tests.
# test_gemini_provider.py (g) is collected after test_executor.py (e) and
# test_gateway.py (g... actually 'em' < 'ew' so gemini < gateway? No: 'ga' < 'ge')
# alphabetical: gateway < gemini. Ensure router.providers.gemini is fresh.
for _key in [
    "router.providers.gemini",
    "inference.router.providers.gemini",
]:
    sys.modules.pop(_key, None)

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
    _providers_pkg.OpenRouterProvider = MagicMock()
    sys.modules["router.providers"] = _providers_pkg

for _mod in [
    "router.providers.github_copilot", "router.providers.local",
    "router.providers.openrouter",
    "inference.router.providers.github_copilot",
    "inference.router.providers.local",
    "inference.router.providers.openrouter",
]:
    sys.modules.setdefault(_mod, MagicMock())

from router.providers.gemini import GeminiProvider  # noqa: E402
from router.base import (  # noqa: E402
    ModelCapability, ProviderType, Message, CompletionRequest, ModelInfo,
    ProviderError,
)


# ---------------------------------------------------------------------------
# Class attributes
# ---------------------------------------------------------------------------

class TestGeminiClass:
    def test_name(self):
        assert GeminiProvider.name == "gemini"

    def test_provider_type(self):
        assert GeminiProvider.provider_type == ProviderType.CLOUD_FRONTIER

    def test_base_url(self):
        assert "generativelanguage.googleapis.com" in GeminiProvider.BASE_URL

    def test_models_not_empty(self):
        assert len(GeminiProvider.MODELS) > 0

    def test_flash_in_models(self):
        assert "gemini-2.0-flash-exp" in GeminiProvider.MODELS

    def test_pro_in_models(self):
        assert "gemini-1.5-pro" in GeminiProvider.MODELS

    def test_flash_15_in_models(self):
        assert "gemini-1.5-flash" in GeminiProvider.MODELS


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestGeminiInit:
    def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        g = GeminiProvider()
        assert g.api_key is None

    def test_explicit_api_key(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        g = GeminiProvider(api_key="gai-test-key")
        assert g.api_key == "gai-test-key"

    def test_env_api_key(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "gai-env-key")
        g = GeminiProvider()
        assert g.api_key == "gai-env-key"

    def test_default_model(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        g = GeminiProvider()
        assert g.default_model == "gemini-2.0-flash-exp"

    def test_custom_default_model(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        g = GeminiProvider(default_model="gemini-1.5-pro")
        assert g.default_model == "gemini-1.5-pro"

    def test_client_initially_none(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        g = GeminiProvider()
        assert g._client is None

    def test_explicit_key_takes_priority(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "env-key")
        g = GeminiProvider(api_key="explicit-key")
        assert g.api_key == "explicit-key"


# ---------------------------------------------------------------------------
# list_models / get_model
# ---------------------------------------------------------------------------

class TestGeminiModels:
    def setup_method(self):
        os.environ.pop("GOOGLE_API_KEY", None)
        self.g = GeminiProvider()

    def test_list_models_returns_all(self):
        models = self.g.list_models()
        assert len(models) == len(GeminiProvider.MODELS)

    def test_list_models_are_model_info(self):
        for m in self.g.list_models():
            assert isinstance(m, ModelInfo)

    def test_get_model_found(self):
        m = self.g.get_model("gemini-1.5-pro")
        assert m is not None
        assert m.id == "gemini-1.5-pro"

    def test_get_model_not_found(self):
        m = self.g.get_model("gemini-99.0-ultra")
        assert m is None

    def test_flash_exp_is_free(self):
        m = self.g.get_model("gemini-2.0-flash-exp")
        assert m.cost_per_1k_input == 0.0
        assert m.cost_per_1k_output == 0.0

    def test_pro_context_window(self):
        m = self.g.get_model("gemini-1.5-pro")
        assert m.context_window == 2_000_000

    def test_flash_exp_tool_support(self):
        m = self.g.get_model("gemini-2.0-flash-exp")
        assert m.supports_tools is True

    def test_flash_15_provider_budget(self):
        m = self.g.get_model("gemini-1.5-flash")
        assert m.provider_type == ProviderType.CLOUD_BUDGET

    def test_exp_1206_is_free(self):
        m = self.g.get_model("gemini-exp-1206")
        assert m is not None
        assert m.cost_per_1k_input == 0.0


# ---------------------------------------------------------------------------
# _format_messages
# ---------------------------------------------------------------------------

class TestGeminiFormatMessages:
    def setup_method(self):
        os.environ.pop("GOOGLE_API_KEY", None)
        self.g = GeminiProvider()

    def test_single_user_message(self):
        msgs = [Message(role="user", content="Hello")]
        result = self.g._format_messages(msgs)
        assert "contents" in result
        assert len(result["contents"]) == 1
        assert result["contents"][0]["role"] == "user"
        text_parts = [p for p in result["contents"][0]["parts"] if "text" in p]
        assert text_parts[0]["text"] == "Hello"

    def test_system_message_extracted(self):
        msgs = [
            Message(role="system", content="You are an expert coder."),
            Message(role="user", content="Write a function."),
        ]
        result = self.g._format_messages(msgs)
        # System message should be in system_instruction, NOT in contents
        assert "system_instruction" in result
        assert result["system_instruction"]["parts"][0]["text"] == "You are an expert coder."
        # Only user message in contents
        assert len(result["contents"]) == 1

    def test_no_system_no_system_instruction(self):
        msgs = [Message(role="user", content="Hi")]
        result = self.g._format_messages(msgs)
        assert "system_instruction" not in result

    def test_assistant_maps_to_model_role(self):
        msgs = [
            Message(role="user", content="Hi"),
            Message(role="assistant", content="Hello!"),
        ]
        result = self.g._format_messages(msgs)
        assert result["contents"][1]["role"] == "model"

    def test_user_message_with_image(self):
        msgs = [Message(role="user", content="What's this?", images=["b64data"])]
        result = self.g._format_messages(msgs)
        parts = result["contents"][0]["parts"]
        image_parts = [p for p in parts if "inline_data" in p]
        assert len(image_parts) == 1
        assert image_parts[0]["inline_data"]["data"] == "b64data"

    def test_multiple_images(self):
        msgs = [Message(role="user", content="Compare", images=["img1", "img2"])]
        result = self.g._format_messages(msgs)
        parts = result["contents"][0]["parts"]
        image_parts = [p for p in parts if "inline_data" in p]
        assert len(image_parts) == 2

    def test_empty_messages(self):
        result = self.g._format_messages([])
        assert result["contents"] == []

    def test_multiturn_conversation(self):
        msgs = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
            Message(role="user", content="How are you?"),
        ]
        result = self.g._format_messages(msgs)
        assert len(result["contents"]) == 3
        roles = [c["role"] for c in result["contents"]]
        assert roles == ["user", "model", "user"]


# ---------------------------------------------------------------------------
# health_check with no API key
# ---------------------------------------------------------------------------

class TestGeminiHealthNoKey:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_unavailable(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        g = GeminiProvider()
        status = await g.health_check()
        assert status.available is False
        assert "key" in (status.error or "").lower()
