"""
Base Provider Interface and Common Types
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, AsyncIterator
from datetime import datetime


class ModelCapability(Enum):
    """What a model can do"""

    REASONING = "reasoning"  # Multi-step planning, complex logic
    CODING = "coding"  # Code generation, debugging
    VISION = "vision"  # Image understanding
    EMBEDDING = "embedding"  # Vector embeddings
    CHAT = "chat"  # General conversation
    TOOL_USE = "tool_use"  # Function calling


class ProviderType(Enum):
    """Provider categories"""

    CLOUD_FRONTIER = "cloud_frontier"  # Gemini, Claude, GPT-4
    CLOUD_BUDGET = "cloud_budget"  # GPT-4o-mini, Gemini Flash
    LOCAL_GPU = "local_gpu"  # Nemotron, Qwen
    LOCAL_CPU = "local_cpu"  # Small models on CPU


@dataclass
class ModelInfo:
    """Information about a model"""

    id: str
    name: str
    provider: str
    capabilities: List[ModelCapability]
    provider_type: ProviderType
    context_window: int
    cost_per_1k_input: float = 0.0  # $ per 1K input tokens
    cost_per_1k_output: float = 0.0  # $ per 1K output tokens
    supports_streaming: bool = True
    supports_tools: bool = False
    max_output_tokens: int = 4096

    @property
    def is_free(self) -> bool:
        return self.cost_per_1k_input == 0 and self.cost_per_1k_output == 0

    @property
    def is_local(self) -> bool:
        return self.provider_type in [ProviderType.LOCAL_GPU, ProviderType.LOCAL_CPU]


@dataclass
class Message:
    """Chat message"""

    role: str  # "system", "user", "assistant"
    content: str
    images: Optional[List[str]] = None  # Base64 encoded images
    tool_calls: Optional[List[Dict]] = None
    tool_results: Optional[List[Dict]] = None


@dataclass
class CompletionRequest:
    """Request to a model"""

    messages: List[Message]
    model: Optional[str] = None  # If None, router picks best
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = False
    tools: Optional[List[Dict]] = None
    required_capabilities: List[ModelCapability] = field(default_factory=list)

    # Cost controls
    max_cost: Optional[float] = None  # Max $ for this request
    prefer_local: bool = False  # Prefer local if capable


@dataclass
class CompletionResponse:
    """Response from a model"""

    content: str
    model: str
    provider: str
    usage: Dict[str, int]  # input_tokens, output_tokens
    cost: float  # Actual cost in $
    latency_ms: int
    finish_reason: str = "stop"
    tool_calls: Optional[List[Dict]] = None

    # For streaming
    is_partial: bool = False


@dataclass
class ProviderStatus:
    """Health status of a provider"""

    available: bool
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    remaining_quota: Optional[float] = None  # $ remaining
    rate_limit_remaining: Optional[int] = None


class BaseProvider(ABC):
    """Abstract base class for model providers"""

    name: str = "base"
    provider_type: ProviderType = ProviderType.CLOUD_FRONTIER

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate a completion"""
        pass

    @abstractmethod
    async def stream(
        self, request: CompletionRequest
    ) -> AsyncIterator[CompletionResponse]:
        """Stream a completion"""
        pass

    @abstractmethod
    async def health_check(self) -> ProviderStatus:
        """Check if provider is available"""
        pass

    @abstractmethod
    def list_models(self) -> List[ModelInfo]:
        """List available models"""
        pass

    @abstractmethod
    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        """Get info about a specific model"""
        pass

    def estimate_cost(self, request: CompletionRequest, model: ModelInfo) -> float:
        """Estimate cost for a request"""
        # Rough estimate: 4 chars per token
        input_tokens = sum(len(m.content) for m in request.messages) / 4
        output_tokens = request.max_tokens

        return (input_tokens / 1000) * model.cost_per_1k_input + (
            output_tokens / 1000
        ) * model.cost_per_1k_output

    def supports_capability(self, capability: ModelCapability) -> bool:
        """Check if any model supports a capability"""
        return any(capability in model.capabilities for model in self.list_models())


class ProviderError(Exception):
    """Base exception for provider errors"""

    def __init__(self, message: str, provider: str, recoverable: bool = True):
        super().__init__(message)
        self.provider = provider
        self.recoverable = recoverable


class RateLimitError(ProviderError):
    """Rate limit exceeded"""

    def __init__(self, provider: str, retry_after: Optional[int] = None):
        super().__init__(
            f"Rate limit exceeded for {provider}", provider, recoverable=True
        )
        self.retry_after = retry_after


class QuotaExceededError(ProviderError):
    """Quota/budget exceeded"""

    def __init__(self, provider: str):
        super().__init__(f"Quota exceeded for {provider}", provider, recoverable=False)


class ModelNotFoundError(ProviderError):
    """Model not available"""

    def __init__(self, model_id: str, provider: str):
        super().__init__(
            f"Model {model_id} not found in {provider}", provider, recoverable=False
        )
        self.model_id = model_id
