"""Unit tests for inference/router/providers/local.py — pure method logic.

Covers: LocalProvider init (model catalog), _get_url_for_model(),
_format_messages(), list_models(), get_model(), supports_capability().
No HTTP calls — all pure logic or synchronous accessors.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup: inference must be in sys.path so 'router' is found as a package
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_INFERENCE = _ROOT / "inference"

for _p in [str(_ROOT), str(_INFERENCE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# sys.modules isolation: clear any stubs set by earlier test files (e.g.
# test_executor.py stubs router.providers.local as MagicMock) so we can
# load the real local.py from the filesystem.
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock
import types

# Remove stubs that would block real loading of local.py
for _key in ["router.providers", "router.providers.local",
             "inference.router.providers", "inference.router.providers.local"]:
    sys.modules.pop(_key, None)

# Stub the heavy providers but keep router.providers as a real package with __path__
# so Python can find router.providers.local as a filesystem submodule.
_providers_pkg = types.ModuleType("router.providers")
_providers_pkg.__path__ = [str(_INFERENCE / "router" / "providers")]
_providers_pkg.__package__ = "router.providers"
_providers_pkg.GeminiProvider = MagicMock()
_providers_pkg.GitHubCopilotProvider = MagicMock()
_providers_pkg.OpenRouterProvider = MagicMock()
_providers_pkg.LocalProvider = MagicMock()  # placeholder; replaced below
sys.modules["router.providers"] = _providers_pkg

for _mod in [
    "router.providers.gemini", "inference.router.providers.gemini",
    "router.providers.github_copilot", "inference.router.providers.github_copilot",
    "router.providers.openrouter", "inference.router.providers.openrouter",
]:
    sys.modules.setdefault(_mod, MagicMock())

# Pre-import the REAL LocalProvider from the filesystem (router.base already
# loaded via test_executor.py, so relative imports in local.py will resolve)
from router.providers.local import LocalProvider
from router.base import (
    ModelCapability, ProviderType, Message, CompletionRequest, ModelInfo,
)


# ===========================================================================
# LocalProvider initialization
# ===========================================================================

class TestLocalProviderInit:
    def test_default_urls(self):
        lp = LocalProvider()
        assert lp.nemotron_url == "http://localhost:8010"
        assert "localhost" in lp.qwen_url

    def test_custom_urls(self):
        lp = LocalProvider(
            nemotron_url="http://nemotron:8010",
            qwen_url="http://qwen:8000",
        )
        assert lp.nemotron_url == "http://nemotron:8010"
        assert lp.qwen_url == "http://qwen:8000"

    def test_client_starts_none(self):
        lp = LocalProvider()
        assert lp._client is None

    def test_models_catalog_has_nemotron(self):
        lp = LocalProvider()
        assert "nemotron-mini-4b" in lp.MODELS

    def test_models_catalog_has_qwen(self):
        lp = LocalProvider()
        assert "qwen3-vl-8b" in lp.MODELS

    def test_models_catalog_size(self):
        lp = LocalProvider()
        assert len(lp.MODELS) == 2

    def test_provider_name(self):
        lp = LocalProvider()
        assert lp.name == "local"

    def test_provider_type(self):
        lp = LocalProvider()
        assert lp.provider_type == ProviderType.LOCAL_GPU


# ===========================================================================
# LocalProvider._get_url_for_model()
# ===========================================================================

class TestGetUrlForModel:
    def setup_method(self):
        self.lp = LocalProvider(
            nemotron_url="http://nemotron:8010",
            qwen_url="http://qwen:8000",
        )

    def test_qwen_model_id_returns_qwen_url(self):
        url = self.lp._get_url_for_model("qwen3-vl-8b")
        assert url == "http://qwen:8000"

    def test_vl_in_id_returns_qwen_url(self):
        url = self.lp._get_url_for_model("some-vl-model")
        assert url == "http://qwen:8000"

    def test_nemotron_returns_nemotron_url(self):
        url = self.lp._get_url_for_model("nemotron-mini-4b")
        assert url == "http://nemotron:8010"

    def test_unknown_model_returns_nemotron_url(self):
        url = self.lp._get_url_for_model("some-other-model")
        assert url == "http://nemotron:8010"

    def test_case_insensitive_qwen(self):
        url = self.lp._get_url_for_model("QWEN3-VL")
        assert url == "http://qwen:8000"


# ===========================================================================
# LocalProvider._format_messages()
# ===========================================================================

class TestFormatMessages:
    def setup_method(self):
        self.lp = LocalProvider()

    def test_simple_text_message(self):
        msg = Message(role="user", content="Hello")
        result = self.lp._format_messages([msg])
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"

    def test_multiple_messages(self):
        msgs = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hi"),
        ]
        result = self.lp._format_messages(msgs)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    def test_message_with_images_becomes_list_content(self):
        msg = Message(role="user", content="Describe this", images=["base64data"])
        result = self.lp._format_messages([msg])
        # When images present, content should be a list
        assert isinstance(result[0]["content"], list)

    def test_image_content_has_text_and_image_parts(self):
        msg = Message(role="user", content="Describe this", images=["base64img"])
        result = self.lp._format_messages([msg])
        content = result[0]["content"]
        types = [part["type"] for part in content]
        assert "text" in types
        assert "image_url" in types

    def test_image_url_contains_base64(self):
        msg = Message(role="user", content="Look", images=["abc123"])
        result = self.lp._format_messages([msg])
        content = result[0]["content"]
        image_parts = [p for p in content if p["type"] == "image_url"]
        assert len(image_parts) == 1
        assert "abc123" in image_parts[0]["image_url"]["url"]

    def test_multiple_images_each_get_image_part(self):
        msg = Message(role="user", content="Compare", images=["img1", "img2"])
        result = self.lp._format_messages([msg])
        content = result[0]["content"]
        image_parts = [p for p in content if p["type"] == "image_url"]
        assert len(image_parts) == 2

    def test_empty_messages_list(self):
        result = self.lp._format_messages([])
        assert result == []


# ===========================================================================
# LocalProvider.list_models() and get_model()
# ===========================================================================

class TestListAndGetModels:
    def setup_method(self):
        self.lp = LocalProvider()

    def test_list_models_returns_all(self):
        models = self.lp.list_models()
        assert len(models) == 2

    def test_list_models_all_are_model_info(self):
        models = self.lp.list_models()
        for m in models:
            assert isinstance(m, ModelInfo)

    def test_get_model_nemotron(self):
        m = self.lp.get_model("nemotron-mini-4b")
        assert m is not None
        assert m.id == "nemotron-mini-4b"

    def test_get_model_qwen(self):
        m = self.lp.get_model("qwen3-vl-8b")
        assert m is not None
        assert m.id == "qwen3-vl-8b"

    def test_get_model_unknown_returns_none(self):
        m = self.lp.get_model("nonexistent-model")
        assert m is None

    def test_nemotron_has_coding_capability(self):
        m = self.lp.get_model("nemotron-mini-4b")
        assert ModelCapability.CODING in m.capabilities

    def test_qwen_has_vision_capability(self):
        m = self.lp.get_model("qwen3-vl-8b")
        assert ModelCapability.VISION in m.capabilities

    def test_qwen_has_chat_capability(self):
        m = self.lp.get_model("qwen3-vl-8b")
        assert ModelCapability.CHAT in m.capabilities

    def test_local_models_are_free(self):
        for m in self.lp.list_models():
            assert m.cost_per_1k_input == 0.0
            assert m.cost_per_1k_output == 0.0

    def test_local_models_provider_type(self):
        for m in self.lp.list_models():
            assert m.provider_type == ProviderType.LOCAL_GPU


# ===========================================================================
# LocalProvider.supports_capability() — inherited from BaseProvider
# ===========================================================================

class TestSupportsCapability:
    def setup_method(self):
        self.lp = LocalProvider()

    def test_supports_coding(self):
        assert self.lp.supports_capability(ModelCapability.CODING) is True

    def test_supports_vision(self):
        assert self.lp.supports_capability(ModelCapability.VISION) is True

    def test_supports_chat(self):
        assert self.lp.supports_capability(ModelCapability.CHAT) is True

    def test_does_not_support_reasoning(self):
        # Neither local model has REASONING capability
        assert self.lp.supports_capability(ModelCapability.REASONING) is False

    def test_does_not_support_embedding(self):
        assert self.lp.supports_capability(ModelCapability.EMBEDDING) is False
