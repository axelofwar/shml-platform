"""
Intelligent Model Router

Routes requests to the best available provider based on:
- Required capabilities
- Cost constraints
- Latency requirements
- Provider availability
"""

import asyncio
import logging
import os
from typing import List, Optional, Dict, Any, Tuple, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .base import (
    BaseProvider,
    ModelInfo,
    ModelCapability,
    ProviderType,
    CompletionRequest,
    CompletionResponse,
    ProviderStatus,
    ProviderError,
    RateLimitError,
)
from .providers import (
    GeminiProvider,
    GitHubCopilotProvider,
    OpenRouterProvider,
    LocalProvider,
)

logger = logging.getLogger(__name__)


class RoutingStrategy(Enum):
    """How to select providers"""

    COST_OPTIMIZED = "cost_optimized"  # Cheapest first
    LATENCY_OPTIMIZED = "latency_optimized"  # Fastest first
    QUALITY_OPTIMIZED = "quality_optimized"  # Best model first
    LOCAL_FIRST = "local_first"  # Local models preferred
    CLOUD_FIRST = "cloud_first"  # Cloud models preferred


@dataclass
class RouterConfig:
    """Router configuration"""

    # Provider API keys
    google_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None

    # Default behavior
    default_strategy: RoutingStrategy = RoutingStrategy.COST_OPTIMIZED
    prefer_local_for_simple: bool = True

    # Cost controls
    monthly_budget: float = 20.0  # $ per month
    max_cost_per_request: float = 0.10  # $ per request

    # Fallback behavior
    fallback_to_local: bool = True
    retry_on_error: bool = True
    max_retries: int = 2


@dataclass
class UsageTracker:
    """Track API usage and costs"""

    total_cost: float = 0.0
    total_requests: int = 0
    costs_by_provider: Dict[str, float] = field(default_factory=dict)
    requests_by_provider: Dict[str, int] = field(default_factory=dict)
    month_start: datetime = field(default_factory=datetime.now)

    def add_usage(self, provider: str, cost: float):
        """Record usage"""
        self.total_cost += cost
        self.total_requests += 1
        self.costs_by_provider[provider] = (
            self.costs_by_provider.get(provider, 0) + cost
        )
        self.requests_by_provider[provider] = (
            self.requests_by_provider.get(provider, 0) + 1
        )

    @property
    def remaining_budget(self) -> float:
        """Get remaining monthly budget"""
        # Reset monthly if needed
        now = datetime.now()
        if now.month != self.month_start.month or now.year != self.month_start.year:
            self.total_cost = 0
            self.month_start = now
        return max(0, 20.0 - self.total_cost)  # Default $20 budget


class ModelRouter:
    """
    Intelligent model router with fallback support.

    Usage:
        router = ModelRouter(RouterConfig(google_api_key="..."))
        await router.initialize()

        # Simple completion
        response = await router.complete(
            CompletionRequest(messages=[...])
        )

        # With specific model
        response = await router.complete(
            CompletionRequest(messages=[...], model="gemini-2.0-flash-exp")
        )
    """

    def __init__(self, config: Optional[RouterConfig] = None):
        self.config = config or RouterConfig()
        self.providers: Dict[str, BaseProvider] = {}
        self.provider_status: Dict[str, ProviderStatus] = {}
        self.usage = UsageTracker()
        self._initialized = False

    async def initialize(self):
        """Initialize all providers and check availability"""
        if self._initialized:
            return

        # Initialize providers based on available credentials
        if self.config.google_api_key:
            self.providers["gemini"] = GeminiProvider(
                api_key=self.config.google_api_key
            )

        if self.config.openrouter_api_key:
            self.providers["openrouter"] = OpenRouterProvider(
                api_key=self.config.openrouter_api_key
            )

        # Always add local provider
        self.providers["local"] = LocalProvider()

        # Try GitHub Copilot
        copilot = GitHubCopilotProvider()
        copilot_status = await copilot.health_check()
        if copilot_status.available:
            self.providers["github_copilot"] = copilot

        # Check all providers
        await self.refresh_status()

        self._initialized = True
        logger.info(f"Router initialized with providers: {list(self.providers.keys())}")

    async def refresh_status(self):
        """Refresh availability status of all providers"""
        tasks = {
            name: provider.health_check() for name, provider in self.providers.items()
        }

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                self.provider_status[name] = ProviderStatus(
                    available=False, error=str(result)
                )
            else:
                self.provider_status[name] = result

    def get_available_providers(self) -> List[str]:
        """Get list of available providers"""
        return [
            name for name, status in self.provider_status.items() if status.available
        ]

    def get_all_models(self) -> List[ModelInfo]:
        """Get all available models across providers"""
        models = []
        for provider in self.providers.values():
            models.extend(provider.list_models())
        return models

    def get_models_by_capability(self, capability: ModelCapability) -> List[ModelInfo]:
        """Get models that support a specific capability"""
        return [
            model for model in self.get_all_models() if capability in model.capabilities
        ]

    def _select_provider_and_model(
        self,
        request: CompletionRequest,
        strategy: Optional[RoutingStrategy] = None,
    ) -> Tuple[BaseProvider, ModelInfo]:
        """Select best provider and model for request"""
        strategy = strategy or self.config.default_strategy

        # If model specified, find it
        if request.model:
            for provider in self.providers.values():
                model = provider.get_model(request.model)
                if model:
                    return provider, model

        # Filter by required capabilities
        candidates = []
        for name, provider in self.providers.items():
            if name not in self.get_available_providers():
                continue

            for model in provider.list_models():
                # Check capabilities
                if request.required_capabilities:
                    if not all(
                        cap in model.capabilities
                        for cap in request.required_capabilities
                    ):
                        continue

                # Check cost constraint
                estimated_cost = provider.estimate_cost(request, model)
                if request.max_cost and estimated_cost > request.max_cost:
                    continue

                if self.usage.remaining_budget < estimated_cost:
                    continue

                candidates.append((provider, model, estimated_cost))

        if not candidates:
            # Fallback to local
            if self.config.fallback_to_local and "local" in self.providers:
                local = self.providers["local"]
                model = local.list_models()[0]
                return local, model
            raise ProviderError(
                "No suitable provider found", "router", recoverable=False
            )

        # Sort by strategy
        if strategy == RoutingStrategy.COST_OPTIMIZED:
            candidates.sort(key=lambda x: x[2])  # By cost
        elif strategy == RoutingStrategy.LATENCY_OPTIMIZED:
            candidates.sort(
                key=lambda x: self.provider_status.get(
                    x[0].name, ProviderStatus(available=True)
                ).latency_ms
                or 9999
            )
        elif strategy == RoutingStrategy.QUALITY_OPTIMIZED:
            # Prefer frontier models
            candidates.sort(
                key=lambda x: (
                    1 if x[1].provider_type == ProviderType.CLOUD_FRONTIER else 0,
                    x[1].context_window,
                ),
                reverse=True,
            )
        elif strategy == RoutingStrategy.LOCAL_FIRST:
            candidates.sort(key=lambda x: 0 if x[1].is_local else 1)
        elif strategy == RoutingStrategy.CLOUD_FIRST:
            candidates.sort(key=lambda x: 1 if x[1].is_local else 0)

        return candidates[0][0], candidates[0][1]

    async def complete(
        self,
        request: CompletionRequest,
        strategy: Optional[RoutingStrategy] = None,
    ) -> CompletionResponse:
        """
        Generate completion with automatic routing and fallback.

        Args:
            request: The completion request
            strategy: Override default routing strategy

        Returns:
            CompletionResponse from best available provider
        """
        if not self._initialized:
            await self.initialize()

        errors = []
        tried_providers = set()
        original_model = request.model

        for attempt in range(self.config.max_retries + 1):
            try:
                provider, model = self._select_provider_and_model(request, strategy)

                if provider.name in tried_providers:
                    # Skip already failed providers
                    continue

                tried_providers.add(provider.name)

                logger.info(f"Routing to {provider.name}/{model.id}")

                # Override request model
                request.model = model.id

                response = await provider.complete(request)

                # Track usage
                self.usage.add_usage(provider.name, response.cost)

                return response

            except RateLimitError as e:
                logger.warning(f"Rate limit on {e.provider}, trying next")
                errors.append(str(e))
                request.model = original_model
                # Mark provider as temporarily unavailable
                self.provider_status[e.provider] = ProviderStatus(
                    available=False, error="Rate limited"
                )

            except ProviderError as e:
                logger.warning(f"Provider error: {e}")
                errors.append(str(e))
                request.model = original_model

                if not e.recoverable:
                    raise

        # All attempts failed
        raise ProviderError(
            f"All providers failed: {'; '.join(errors)}", "router", recoverable=False
        )

    async def complete_stream(
        self,
        request: CompletionRequest,
        strategy: Optional[RoutingStrategy] = None,
    ) -> AsyncIterator[CompletionResponse]:
        """
        Generate streaming completion with automatic routing.

        Yields:
            CompletionResponse chunks from provider
        """
        from typing import AsyncIterator

        if not self._initialized:
            await self.initialize()

        # Select provider
        provider, model = self._select_provider_and_model(request, strategy)
        logger.info(f"Streaming from {provider.name}/{model.id}")

        # Override request model and enable streaming
        request.model = model.id
        request.stream = True

        async for chunk in provider.stream(request):
            yield chunk

    async def complete_with_reasoning(
        self,
        task: str,
        context: Optional[str] = None,
        reasoning_model: Optional[str] = None,
        execution_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Two-phase completion: reasoning then execution.

        1. Use frontier model for planning/reasoning
        2. Use local model for code execution

        Args:
            task: User's task description
            context: Additional context
            reasoning_model: Override reasoning model (default: gemini-2.0-flash-exp)
            execution_model: Override execution model (default: nemotron-mini-4b)

        Returns:
            Dict with plan and execution results
        """
        from .base import Message

        # Phase 1: Reasoning (cloud)
        reasoning_prompt = f"""Analyze this task and create an execution plan.

Task: {task}

{f"Context: {context}" if context else ""}

Output a JSON plan with:
{{
    "task_type": "coding|research|system|chat",
    "complexity": "simple|medium|complex",
    "subtasks": ["list", "of", "subtasks"],
    "tools_needed": ["ShellSkill", "RayJobSkill", etc.],
    "parallel_safe": true/false,
    "estimated_tokens": 1000
}}

Be concise. Output only valid JSON."""

        plan_response = await self.complete(
            CompletionRequest(
                messages=[Message(role="user", content=reasoning_prompt)],
                model=reasoning_model or "gemini-2.0-flash-exp",
                temperature=0.1,
                max_tokens=500,
            ),
            strategy=RoutingStrategy.CLOUD_FIRST,
        )

        # Parse plan
        import json

        try:
            plan = json.loads(plan_response.content)
        except json.JSONDecodeError:
            # Fallback plan
            plan = {
                "task_type": "coding",
                "complexity": "medium",
                "subtasks": [task],
                "tools_needed": [],
                "parallel_safe": False,
            }

        # Phase 2: Execution (local)
        execution_prompt = f"""Execute this task:

Task: {task}
Plan: {json.dumps(plan, indent=2)}

{f"Context: {context}" if context else ""}

Provide a complete solution."""

        execution_response = await self.complete(
            CompletionRequest(
                messages=[Message(role="user", content=execution_prompt)],
                model=execution_model or os.getenv("CODING_MODEL_ALIAS", "nemotron-coding"),
                temperature=0.7,
                max_tokens=4096,
            ),
            strategy=RoutingStrategy.LOCAL_FIRST,
        )

        return {
            "plan": plan,
            "reasoning_model": plan_response.model,
            "reasoning_cost": plan_response.cost,
            "execution": execution_response.content,
            "execution_model": execution_response.model,
            "total_cost": plan_response.cost + execution_response.cost,
            "total_latency_ms": plan_response.latency_ms
            + execution_response.latency_ms,
        }

    async def close(self):
        """Close all provider connections"""
        for provider in self.providers.values():
            if hasattr(provider, "close"):
                await provider.close()

    def get_usage_summary(self) -> Dict[str, Any]:
        """Get usage statistics"""
        return {
            "total_cost": self.usage.total_cost,
            "remaining_budget": self.usage.remaining_budget,
            "total_requests": self.usage.total_requests,
            "by_provider": {
                name: {
                    "cost": self.usage.costs_by_provider.get(name, 0),
                    "requests": self.usage.requests_by_provider.get(name, 0),
                }
                for name in self.providers.keys()
            },
        }
