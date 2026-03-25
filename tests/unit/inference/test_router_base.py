"""Unit tests for inference/router/base.py and inference/router/router.py.

Covers: ModelCapability, ProviderType, ModelInfo, Message, CompletionRequest,
CompletionResponse, ProviderStatus, BaseProvider, all exception classes,
RoutingStrategy, RouterConfig, UsageTracker.

No external providers needed — base.py has no external deps;
router.py's UsageTracker/RouterConfig/RoutingStrategy are pure dataclasses.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure inference/router is importable
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ROUTER = _ROOT / "inference" / "router"
for _p in [str(_ROOT), str(_ROUTER), str(_ROOT / "inference")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Stub provider modules before importing router (they have heavy deps)
def _stub_providers():
    fake_provider = MagicMock()
    fake_provider.GeminiProvider = MagicMock
    fake_provider.GitHubCopilotProvider = MagicMock
    fake_provider.OpenRouterProvider = MagicMock
    fake_provider.LocalProvider = MagicMock
    sys.modules.setdefault("inference.router.providers", fake_provider)
    sys.modules.setdefault("router.providers", fake_provider)
    # Stub individual provider submodules
    for mod in ("gemini", "github_copilot", "openrouter", "local"):
        sys.modules.setdefault(f"router.providers.{mod}", MagicMock())
        sys.modules.setdefault(f"inference.router.providers.{mod}", MagicMock())

_stub_providers()


# ===========================================================================
# inference/router/base.py — enums / dataclasses / exceptions
# ===========================================================================


class TestModelCapabilityEnum:
    def test_all_values(self):
        from base import ModelCapability
        assert ModelCapability.REASONING.value == "reasoning"
        assert ModelCapability.CODING.value == "coding"
        assert ModelCapability.VISION.value == "vision"
        assert ModelCapability.EMBEDDING.value == "embedding"
        assert ModelCapability.CHAT.value == "chat"
        assert ModelCapability.TOOL_USE.value == "tool_use"

    def test_member_count(self):
        from base import ModelCapability
        assert len(ModelCapability) == 6


class TestProviderTypeEnum:
    def test_all_values(self):
        from base import ProviderType
        assert ProviderType.CLOUD_FRONTIER.value == "cloud_frontier"
        assert ProviderType.CLOUD_BUDGET.value == "cloud_budget"
        assert ProviderType.LOCAL_GPU.value == "local_gpu"
        assert ProviderType.LOCAL_CPU.value == "local_cpu"


class TestModelInfo:
    def _make_model(self, **kwargs):
        from base import ModelInfo, ModelCapability, ProviderType
        defaults = dict(
            id="model-1",
            name="Test Model",
            provider="test",
            capabilities=[ModelCapability.CHAT],
            provider_type=ProviderType.LOCAL_GPU,
            context_window=4096,
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
        )
        defaults.update(kwargs)
        return ModelInfo(**defaults)

    def test_is_free_when_zero_cost(self):
        m = self._make_model()
        assert m.is_free is True

    def test_not_free_when_has_cost(self):
        m = self._make_model(cost_per_1k_input=0.001)
        assert m.is_free is False

    def test_is_local_gpu(self):
        from base import ProviderType
        m = self._make_model(provider_type=ProviderType.LOCAL_GPU)
        assert m.is_local is True

    def test_is_local_cpu(self):
        from base import ProviderType
        m = self._make_model(provider_type=ProviderType.LOCAL_CPU)
        assert m.is_local is True

    def test_not_local_cloud(self):
        from base import ProviderType
        m = self._make_model(provider_type=ProviderType.CLOUD_FRONTIER)
        assert m.is_local is False

    def test_stream_and_tools_defaults(self):
        m = self._make_model()
        assert m.supports_streaming is True
        assert m.supports_tools is False
        assert m.max_output_tokens == 4096


class TestMessage:
    def test_minimal(self):
        from base import Message
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.images is None
        assert msg.tool_calls is None
        assert msg.tool_results is None

    def test_with_images(self):
        from base import Message
        msg = Message(role="user", content="describe", images=["base64data"])
        assert len(msg.images) == 1


class TestCompletionRequest:
    def test_defaults(self):
        from base import CompletionRequest, Message
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        assert req.model is None
        assert req.temperature == pytest.approx(0.7)
        assert req.max_tokens == 4096
        assert req.stream is False
        assert req.tools is None
        assert req.required_capabilities == []
        assert req.max_cost is None
        assert req.prefer_local is False

    def test_with_capabilities(self):
        from base import CompletionRequest, Message, ModelCapability
        req = CompletionRequest(
            messages=[Message(role="user", content="code")],
            required_capabilities=[ModelCapability.CODING],
            prefer_local=True,
        )
        assert ModelCapability.CODING in req.required_capabilities
        assert req.prefer_local is True


class TestCompletionResponse:
    def test_creation(self):
        from base import CompletionResponse
        resp = CompletionResponse(
            content="Hello there!",
            model="qwen3",
            provider="local",
            usage={"input_tokens": 10, "output_tokens": 5},
            cost=0.0,
            latency_ms=250,
        )
        assert resp.finish_reason == "stop"
        assert resp.is_partial is False
        assert resp.tool_calls is None


class TestProviderStatus:
    def test_available_defaults(self):
        from base import ProviderStatus
        status = ProviderStatus(available=True)
        assert status.latency_ms is None
        assert status.error is None
        assert status.remaining_quota is None
        assert status.rate_limit_remaining is None

    def test_unavailable_with_error(self):
        from base import ProviderStatus
        status = ProviderStatus(available=False, error="Timeout", latency_ms=30000)
        assert status.available is False
        assert status.error == "Timeout"


class TestBaseProviderConcrete:
    """Test BaseProvider via a minimal concrete subclass."""

    def _make_provider(self, models=None):
        from base import BaseProvider, ModelInfo, ModelCapability, ProviderType, ProviderStatus, CompletionResponse

        class FakeProvider(BaseProvider):
            name = "fake"

            def __init__(self):
                self._models = models or []

            async def complete(self, request):
                return CompletionResponse(
                    content="ok",
                    model="fake-model",
                    provider="fake",
                    usage={"input_tokens": 1, "output_tokens": 1},
                    cost=0,
                    latency_ms=10,
                )

            async def stream(self, request):
                yield CompletionResponse(
                    content="ok",
                    model="fake-model",
                    provider="fake",
                    usage={"input_tokens": 1, "output_tokens": 1},
                    cost=0,
                    latency_ms=10,
                    is_partial=True,
                )

            async def health_check(self):
                return ProviderStatus(available=True)

            def list_models(self):
                return self._models

            def get_model(self, model_id):
                return next((m for m in self._models if m.id == model_id), None)

        return FakeProvider()

    def test_estimate_cost_free_model(self):
        from base import ModelInfo, ModelCapability, ProviderType, CompletionRequest, Message
        provider = self._make_provider()
        model = ModelInfo(
            id="free",
            name="Free",
            provider="local",
            capabilities=[ModelCapability.CHAT],
            provider_type=ProviderType.LOCAL_GPU,
            context_window=4096,
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
        )
        req = CompletionRequest(messages=[Message(role="user", content="hello")])
        cost = provider.estimate_cost(req, model)
        assert cost == pytest.approx(0.0)

    def test_estimate_cost_paid_model(self):
        from base import ModelInfo, ModelCapability, ProviderType, CompletionRequest, Message
        provider = self._make_provider()
        model = ModelInfo(
            id="paid",
            name="Paid",
            provider="cloud",
            capabilities=[ModelCapability.CODING],
            provider_type=ProviderType.CLOUD_FRONTIER,
            context_window=128000,
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
        )
        req = CompletionRequest(
            messages=[Message(role="user", content="x" * 4000)],  # 1000 tokens
            max_tokens=100,
        )
        cost = provider.estimate_cost(req, model)
        assert cost > 0.0

    def test_supports_capability_when_model_has_it(self):
        from base import ModelInfo, ModelCapability, ProviderType
        model = ModelInfo(
            id="m1",
            name="Vision Model",
            provider="local",
            capabilities=[ModelCapability.VISION, ModelCapability.CHAT],
            provider_type=ProviderType.LOCAL_GPU,
            context_window=8192,
        )
        provider = self._make_provider(models=[model])
        assert provider.supports_capability(ModelCapability.VISION) is True
        assert provider.supports_capability(ModelCapability.CODING) is False

    def test_get_model_found(self):
        from base import ModelInfo, ModelCapability, ProviderType
        model = ModelInfo(
            id="target",
            name="Target",
            provider="local",
            capabilities=[ModelCapability.CHAT],
            provider_type=ProviderType.LOCAL_GPU,
            context_window=4096,
        )
        provider = self._make_provider(models=[model])
        result = provider.get_model("target")
        assert result is not None
        assert result.id == "target"

    def test_get_model_not_found_returns_none(self):
        provider = self._make_provider()
        result = provider.get_model("nonexistent")
        assert result is None


class TestProviderExceptions:
    def test_provider_error(self):
        from base import ProviderError
        err = ProviderError("test error", "fake-provider", recoverable=True)
        assert err.provider == "fake-provider"
        assert err.recoverable is True
        assert "test error" in str(err)

    def test_provider_error_not_recoverable(self):
        from base import ProviderError
        err = ProviderError("permanent", "fake", recoverable=False)
        assert err.recoverable is False

    def test_rate_limit_error(self):
        from base import RateLimitError
        err = RateLimitError("fake", retry_after=60)
        assert err.provider == "fake"
        assert err.recoverable is True
        assert err.retry_after == 60
        assert isinstance(err, Exception)

    def test_rate_limit_error_no_retry_after(self):
        from base import RateLimitError
        err = RateLimitError("fake")
        assert err.retry_after is None

    def test_quota_exceeded_error(self):
        from base import QuotaExceededError, ProviderError
        err = QuotaExceededError("my-provider")
        assert err.provider == "my-provider"
        assert err.recoverable is False
        assert isinstance(err, ProviderError)

    def test_model_not_found_error(self):
        from base import ModelNotFoundError, ProviderError
        err = ModelNotFoundError("gpt-5", "openrouter")
        assert err.model_id == "gpt-5"
        assert err.provider == "openrouter"
        assert err.recoverable is False
        assert isinstance(err, ProviderError)


# ===========================================================================
# inference/router/router.py — RoutingStrategy, RouterConfig, UsageTracker
# ===========================================================================


class TestRoutingStrategy:
    def test_all_values(self):
        from router import router as router_module
        RoutingStrategy = router_module.RoutingStrategy
        assert RoutingStrategy.COST_OPTIMIZED.value == "cost_optimized"
        assert RoutingStrategy.LATENCY_OPTIMIZED.value == "latency_optimized"
        assert RoutingStrategy.QUALITY_OPTIMIZED.value == "quality_optimized"
        assert RoutingStrategy.LOCAL_FIRST.value == "local_first"
        assert RoutingStrategy.CLOUD_FIRST.value == "cloud_first"


class TestRouterConfig:
    def test_defaults(self):
        from router import router as router_module
        RouterConfig = router_module.RouterConfig
        RoutingStrategy = router_module.RoutingStrategy
        cfg = RouterConfig()
        assert cfg.google_api_key is None
        assert cfg.openrouter_api_key is None
        assert cfg.default_strategy == RoutingStrategy.COST_OPTIMIZED
        assert cfg.prefer_local_for_simple is True
        assert cfg.monthly_budget == pytest.approx(20.0)
        assert cfg.max_cost_per_request == pytest.approx(0.10)
        assert cfg.fallback_to_local is True
        assert cfg.retry_on_error is True
        assert cfg.max_retries == 2

    def test_custom_config(self):
        from router import router as router_module
        RouterConfig = router_module.RouterConfig
        RoutingStrategy = router_module.RoutingStrategy
        cfg = RouterConfig(
            google_api_key="gk-123",
            monthly_budget=50.0,
            default_strategy=RoutingStrategy.LOCAL_FIRST,
        )
        assert cfg.google_api_key == "gk-123"
        assert cfg.monthly_budget == pytest.approx(50.0)
        assert cfg.default_strategy == RoutingStrategy.LOCAL_FIRST


class TestUsageTracker:
    def test_initial_state(self):
        from router import router as router_module
        UsageTracker = router_module.UsageTracker
        tracker = UsageTracker()
        assert tracker.total_cost == pytest.approx(0.0)
        assert tracker.total_requests == 0
        assert tracker.costs_by_provider == {}
        assert tracker.requests_by_provider == {}

    def test_add_usage_accumulates(self):
        from router import router as router_module
        UsageTracker = router_module.UsageTracker
        tracker = UsageTracker()
        tracker.add_usage("gemini", 0.01)
        tracker.add_usage("gemini", 0.02)
        tracker.add_usage("openrouter", 0.05)
        assert tracker.total_cost == pytest.approx(0.08)
        assert tracker.total_requests == 3
        assert tracker.costs_by_provider["gemini"] == pytest.approx(0.03)
        assert tracker.costs_by_provider["openrouter"] == pytest.approx(0.05)
        assert tracker.requests_by_provider["gemini"] == 2
        assert tracker.requests_by_provider["openrouter"] == 1

    def test_remaining_budget_decreases(self):
        from router import router as router_module
        UsageTracker = router_module.UsageTracker
        tracker = UsageTracker()
        initial = tracker.remaining_budget
        tracker.add_usage("gemini", 5.0)
        assert tracker.remaining_budget == pytest.approx(initial - 5.0)

    def test_remaining_budget_not_negative(self):
        from router import router as router_module
        UsageTracker = router_module.UsageTracker
        tracker = UsageTracker()
        tracker.add_usage("gemini", 100.0)  # way over budget
        assert tracker.remaining_budget == pytest.approx(0.0)

    def test_add_usage_new_provider(self):
        from router import router as router_module
        UsageTracker = router_module.UsageTracker
        tracker = UsageTracker()
        tracker.add_usage("new-provider", 0.0)
        assert "new-provider" in tracker.requests_by_provider
        assert tracker.requests_by_provider["new-provider"] == 1
