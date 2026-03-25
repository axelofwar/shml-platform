from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
]:
    sys.modules.pop(_key, None)

from router.base import (  # noqa: E402
    CompletionRequest,
    CompletionResponse,
    Message,
    ModelCapability,
    ModelInfo,
    ProviderError,
    ProviderStatus,
    ProviderType,
    RateLimitError,
)
from router.router import ModelRouter, RouterConfig, RoutingStrategy, UsageTracker  # noqa: E402


def _request(*messages: Message, **kwargs) -> CompletionRequest:
    return CompletionRequest(messages=list(messages), **kwargs)


def _message(content: str) -> Message:
    return Message(role="user", content=content)


def _model(model_id: str, provider_type: ProviderType, cost_in: float = 0.0, cost_out: float = 0.0, capabilities=None) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        name=model_id,
        provider=model_id.split("-")[0],
        capabilities=capabilities or [ModelCapability.CHAT],
        provider_type=provider_type,
        context_window=8192,
        cost_per_1k_input=cost_in,
        cost_per_1k_output=cost_out,
        max_output_tokens=4096,
    )


class TestUsageTracker:
    def test_add_usage(self):
        tracker = UsageTracker()
        tracker.add_usage("gemini", 0.25)
        assert tracker.total_cost == 0.25
        assert tracker.requests_by_provider["gemini"] == 1

    def test_remaining_budget_resets_month(self):
        tracker = UsageTracker(total_cost=10.0)
        tracker.month_start = tracker.month_start.replace(year=tracker.month_start.year - 1)
        remaining = tracker.remaining_budget
        assert remaining == 20.0
        assert tracker.total_cost == 0


class TestModelRouterRuntime:
    def _provider(self, name: str, model: ModelInfo, complete_response: CompletionResponse | None = None):
        provider = MagicMock()
        provider.name = name
        provider.list_models.return_value = [model]
        provider.get_model.side_effect = lambda model_id: model if model_id == model.id else None
        provider.estimate_cost.side_effect = lambda request, selected_model: 0.01
        provider.complete = AsyncMock(return_value=complete_response or CompletionResponse(
            content=f"from-{name}",
            model=model.id,
            provider=name,
            usage={"input_tokens": 1, "output_tokens": 1},
            cost=0.01,
            latency_ms=5,
        ))
        provider.stream = AsyncMock()
        provider.health_check = AsyncMock(return_value=ProviderStatus(available=True, latency_ms=10))
        provider.close = AsyncMock()
        return provider

    @pytest.mark.asyncio
    async def test_initialize_adds_configured_and_local_providers(self):
        config = RouterConfig(google_api_key="g", openrouter_api_key="o")
        router = ModelRouter(config)
        with patch("router.router.GeminiProvider") as gemini_cls, \
             patch("router.router.OpenRouterProvider") as openrouter_cls, \
             patch("router.router.LocalProvider") as local_cls, \
             patch("router.router.GitHubCopilotProvider") as copilot_cls:
            gemini = self._provider("gemini", _model("gemini-1", ProviderType.CLOUD_FRONTIER))
            openrouter = self._provider("openrouter", _model("openrouter-1", ProviderType.CLOUD_FRONTIER))
            local = self._provider("local", _model("local-1", ProviderType.LOCAL_GPU))
            copilot = self._provider("github_copilot", _model("copilot-1", ProviderType.CLOUD_FRONTIER))
            copilot.health_check.return_value = ProviderStatus(available=True)
            gemini_cls.return_value = gemini
            openrouter_cls.return_value = openrouter
            local_cls.return_value = local
            copilot_cls.return_value = copilot
            await router.initialize()
        assert set(router.providers) == {"gemini", "openrouter", "local", "github_copilot"}

    @pytest.mark.asyncio
    async def test_refresh_status_records_exception(self):
        router = ModelRouter()
        provider = self._provider("local", _model("local-1", ProviderType.LOCAL_GPU))
        provider.health_check.side_effect = RuntimeError("boom")
        router.providers = {"local": provider}
        await router.refresh_status()
        assert router.provider_status["local"].available is False

    def test_get_available_providers(self):
        router = ModelRouter()
        router.provider_status = {
            "a": ProviderStatus(available=True),
            "b": ProviderStatus(available=False),
        }
        assert router.get_available_providers() == ["a"]

    def test_get_all_models(self):
        router = ModelRouter()
        router.providers = {
            "a": self._provider("a", _model("a-1", ProviderType.LOCAL_GPU)),
            "b": self._provider("b", _model("b-1", ProviderType.CLOUD_FRONTIER)),
        }
        assert len(router.get_all_models()) == 2

    def test_get_models_by_capability(self):
        router = ModelRouter()
        router.providers = {
            "a": self._provider("a", _model("a-1", ProviderType.LOCAL_GPU, capabilities=[ModelCapability.CHAT])),
            "b": self._provider("b", _model("b-1", ProviderType.CLOUD_FRONTIER, capabilities=[ModelCapability.VISION])),
        }
        models = router.get_models_by_capability(ModelCapability.VISION)
        assert [model.id for model in models] == ["b-1"]

    def test_select_provider_specific_model(self):
        router = ModelRouter()
        provider = self._provider("local", _model("local-1", ProviderType.LOCAL_GPU))
        router.providers = {"local": provider}
        selected_provider, selected_model = router._select_provider_and_model(
            _request(_message("hi"), model="local-1")
        )
        assert selected_provider.name == "local"
        assert selected_model.id == "local-1"

    def test_select_provider_fallback_to_local(self):
        router = ModelRouter()
        local_model = _model("local-1", ProviderType.LOCAL_GPU)
        local = self._provider("local", local_model)
        router.providers = {"local": local}
        router.provider_status = {"local": ProviderStatus(available=False)}
        provider, model = router._select_provider_and_model(_request(_message("hi")))
        assert provider.name == "local"
        assert model.id == "local-1"

    def test_select_provider_cost_optimized(self):
        router = ModelRouter()
        cheap_model = _model("cheap-1", ProviderType.CLOUD_BUDGET)
        expensive_model = _model("expensive-1", ProviderType.CLOUD_FRONTIER)
        cheap = self._provider("cheap", cheap_model)
        expensive = self._provider("expensive", expensive_model)
        cheap.estimate_cost.side_effect = lambda request, model: 0.01
        expensive.estimate_cost.side_effect = lambda request, model: 0.5
        router.providers = {"cheap": cheap, "expensive": expensive}
        router.provider_status = {
            "cheap": ProviderStatus(available=True, latency_ms=30),
            "expensive": ProviderStatus(available=True, latency_ms=10),
        }
        provider, _ = router._select_provider_and_model(_request(_message("hi")))
        assert provider.name == "cheap"

    def test_select_provider_latency_optimized(self):
        router = ModelRouter(RouterConfig(default_strategy=RoutingStrategy.LATENCY_OPTIMIZED))
        slow = self._provider("slow", _model("slow-1", ProviderType.CLOUD_BUDGET))
        fast = self._provider("fast", _model("fast-1", ProviderType.CLOUD_FRONTIER))
        router.providers = {"slow": slow, "fast": fast}
        router.provider_status = {
            "slow": ProviderStatus(available=True, latency_ms=100),
            "fast": ProviderStatus(available=True, latency_ms=5),
        }
        provider, _ = router._select_provider_and_model(_request(_message("hi")))
        assert provider.name == "fast"

    def test_select_provider_quality_optimized(self):
        router = ModelRouter(RouterConfig(default_strategy=RoutingStrategy.QUALITY_OPTIMIZED))
        local = self._provider("local", _model("local-1", ProviderType.LOCAL_GPU))
        frontier = self._provider("frontier", _model("frontier-1", ProviderType.CLOUD_FRONTIER))
        router.providers = {"local": local, "frontier": frontier}
        router.provider_status = {
            "local": ProviderStatus(available=True),
            "frontier": ProviderStatus(available=True),
        }
        provider, _ = router._select_provider_and_model(_request(_message("hi")))
        assert provider.name == "frontier"

    @pytest.mark.asyncio
    async def test_complete_success_tracks_usage(self):
        router = ModelRouter(RouterConfig(max_retries=0))
        provider = self._provider("local", _model("local-1", ProviderType.LOCAL_GPU))
        router.providers = {"local": provider}
        router.provider_status = {"local": ProviderStatus(available=True)}
        router._initialized = True
        response = await router.complete(_request(_message("hi")))
        assert response.provider == "local"
        assert router.usage.total_requests == 1

    @pytest.mark.asyncio
    async def test_complete_rate_limit_then_success(self):
        router = ModelRouter(RouterConfig(max_retries=1))
        first = self._provider("gemini", _model("gemini-1", ProviderType.CLOUD_FRONTIER))
        second = self._provider("local", _model("local-1", ProviderType.LOCAL_GPU))
        first.complete.side_effect = RateLimitError("gemini")
        router.providers = {"gemini": first, "local": second}
        router.provider_status = {
            "gemini": ProviderStatus(available=True),
            "local": ProviderStatus(available=True),
        }
        router._initialized = True
        response = await router.complete(_request(_message("hi")))
        assert response.provider == "local"
        assert router.provider_status["gemini"].available is False

    @pytest.mark.asyncio
    async def test_complete_nonrecoverable_error_propagates(self):
        router = ModelRouter(RouterConfig(max_retries=1))
        provider = self._provider("gemini", _model("gemini-1", ProviderType.CLOUD_FRONTIER))
        provider.complete.side_effect = ProviderError("fatal", "gemini", recoverable=False)
        router.providers = {"gemini": provider}
        router.provider_status = {"gemini": ProviderStatus(available=True)}
        router._initialized = True
        with pytest.raises(ProviderError, match="fatal"):
            await router.complete(_request(_message("hi")))

    @pytest.mark.asyncio
    async def test_complete_all_fail(self):
        router = ModelRouter(RouterConfig(max_retries=1))
        provider = self._provider("gemini", _model("gemini-1", ProviderType.CLOUD_FRONTIER))
        provider.complete.side_effect = ProviderError("recoverable", "gemini", recoverable=True)
        router.providers = {"gemini": provider}
        router.provider_status = {"gemini": ProviderStatus(available=True)}
        router._initialized = True
        with pytest.raises(ProviderError, match="All providers failed"):
            await router.complete(_request(_message("hi")))

    @pytest.mark.asyncio
    async def test_complete_stream(self):
        router = ModelRouter()
        provider = self._provider("local", _model("local-1", ProviderType.LOCAL_GPU))

        async def _stream(_request):
            yield CompletionResponse(content="a", model="local-1", provider="local", usage={}, cost=0.0, latency_ms=1, is_partial=True)
            yield CompletionResponse(content="ab", model="local-1", provider="local", usage={}, cost=0.0, latency_ms=2, is_partial=False)

        provider.stream = _stream
        router.providers = {"local": provider}
        router.provider_status = {"local": ProviderStatus(available=True)}
        router._initialized = True
        chunks = [chunk async for chunk in router.complete_stream(_request(_message("hi")))]
        assert [chunk.content for chunk in chunks] == ["a", "ab"]

    @pytest.mark.asyncio
    async def test_complete_with_reasoning_json_and_fallback_parse(self):
        router = ModelRouter()
        responses = [
            CompletionResponse(content='{"task_type":"coding","complexity":"simple","subtasks":["a"],"tools_needed":[],"parallel_safe":false,"estimated_tokens":100}', model="gemini-1", provider="gemini", usage={}, cost=0.01, latency_ms=10),
            CompletionResponse(content="execution-result", model="local-1", provider="local", usage={}, cost=0.0, latency_ms=5),
        ]

        async def _complete(*args, **kwargs):
            return responses.pop(0)

        with patch.object(router, "complete", side_effect=_complete):
            result = await router.complete_with_reasoning("Build a handler")
        assert result["execution"] == "execution-result"
        assert result["plan"]["task_type"] == "coding"

    @pytest.mark.asyncio
    async def test_complete_with_reasoning_invalid_json_fallback_plan(self):
        router = ModelRouter()
        responses = [
            CompletionResponse(content='not-json', model="gemini-1", provider="gemini", usage={}, cost=0.01, latency_ms=10),
            CompletionResponse(content="execution-result", model="local-1", provider="local", usage={}, cost=0.0, latency_ms=5),
        ]

        async def _complete(*args, **kwargs):
            return responses.pop(0)

        with patch.object(router, "complete", side_effect=_complete):
            result = await router.complete_with_reasoning("Build a handler")
        assert result["plan"]["complexity"] == "medium"

    @pytest.mark.asyncio
    async def test_close_calls_provider_close(self):
        router = ModelRouter()
        provider = self._provider("local", _model("local-1", ProviderType.LOCAL_GPU))
        router.providers = {"local": provider}
        await router.close()
        provider.close.assert_awaited_once()

    def test_get_usage_summary(self):
        router = ModelRouter()
        provider = self._provider("local", _model("local-1", ProviderType.LOCAL_GPU))
        router.providers = {"local": provider}
        router.usage.add_usage("local", 0.1)
        summary = router.get_usage_summary()
        assert summary["total_cost"] == 0.1
        assert summary["by_provider"]["local"]["requests"] == 1
