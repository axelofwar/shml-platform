"""
Intelligent Model Router - Hybrid Cloud/Local Architecture

This router implements a reasoning-first pattern:
1. Use frontier models (Gemini, Claude, GPT) for planning/reasoning
2. Route execution to local models (Nemotron, Qwen) based on plan
3. Support parallel execution with intelligent merge

Providers:
- Google Gemini (primary reasoning)
- GitHub Copilot (fallback, requires gh extension)
- OpenRouter (future, all models)
- Local (Nemotron, Qwen-VL)

Usage:
    from inference.router import ModelRouter, RouterConfig

    router = ModelRouter(RouterConfig(
        google_api_key="your-key",
    ))
    await router.initialize()

    # Simple completion
    response = await router.complete(request)

    # Two-phase (reasoning + execution)
    result = await router.complete_with_reasoning("Build a YOLO trainer")

    # Full parallel execution
    from inference.router import TaskPlanner
    planner = TaskPlanner(router)
    result = await planner.execute("Research SOTA and implement", parallel=True)

TUI:
    python -m inference.router.tui
"""

from .base import (
    ModelCapability,
    ProviderType,
    ModelInfo,
    Message,
    CompletionRequest,
    CompletionResponse,
    ProviderStatus,
    ProviderError,
    RateLimitError,
    QuotaExceededError,
)
from .router import ModelRouter, RouterConfig, RoutingStrategy, UsageTracker
from .executor import (
    ParallelExecutor,
    TaskPlanner,
    MergeStrategy,
    ExecutionPlan,
    Subtask,
)
from .providers import (
    GeminiProvider,
    GitHubCopilotProvider,
    OpenRouterProvider,
    LocalProvider,
)

__all__ = [
    # Core
    "ModelRouter",
    "RouterConfig",
    "RoutingStrategy",
    "UsageTracker",
    # Parallel execution
    "ParallelExecutor",
    "TaskPlanner",
    "MergeStrategy",
    "ExecutionPlan",
    "Subtask",
    # Types
    "ModelCapability",
    "ProviderType",
    "ModelInfo",
    "Message",
    "CompletionRequest",
    "CompletionResponse",
    "ProviderStatus",
    # Errors
    "ProviderError",
    "RateLimitError",
    "QuotaExceededError",
    # Providers
    "GeminiProvider",
    "GitHubCopilotProvider",
    "OpenRouterProvider",
    "LocalProvider",
]
