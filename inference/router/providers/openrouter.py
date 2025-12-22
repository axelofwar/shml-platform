"""
OpenRouter Provider (Future)

Universal API for all models - Claude, GPT, Llama, Mistral, etc.
https://openrouter.ai/
"""

import os
import httpx
import logging
from typing import List, Optional, AsyncIterator, Dict
from datetime import datetime
import json

from ..base import (
    BaseProvider,
    ProviderType,
    ModelInfo,
    ModelCapability,
    CompletionRequest,
    CompletionResponse,
    ProviderStatus,
    Message,
    ProviderError,
    RateLimitError,
)

logger = logging.getLogger(__name__)


class OpenRouterProvider(BaseProvider):
    """
    OpenRouter - Universal LLM API

    Provides access to:
    - Anthropic (Claude)
    - OpenAI (GPT-4)
    - Meta (Llama)
    - Mistral
    - Google (Gemini)
    - And many more

    Setup:
    1. Get API key from https://openrouter.ai/keys
    2. Set OPENROUTER_API_KEY environment variable

    Pricing: Pay per token, varies by model
    """

    name = "openrouter"
    provider_type = ProviderType.CLOUD_FRONTIER

    BASE_URL = "https://openrouter.ai/api/v1"

    # Popular models (partial list - full catalog via API)
    MODELS = {
        "anthropic/claude-3.5-sonnet": ModelInfo(
            id="anthropic/claude-3.5-sonnet",
            name="Claude 3.5 Sonnet",
            provider="openrouter",
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODING,
                ModelCapability.VISION,
                ModelCapability.CHAT,
                ModelCapability.TOOL_USE,
            ],
            provider_type=ProviderType.CLOUD_FRONTIER,
            context_window=200_000,
            cost_per_1k_input=0.003,
            cost_per_1k_output=0.015,
            supports_streaming=True,
            supports_tools=True,
            max_output_tokens=8192,
        ),
        "openai/gpt-4o": ModelInfo(
            id="openai/gpt-4o",
            name="GPT-4o",
            provider="openrouter",
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODING,
                ModelCapability.VISION,
                ModelCapability.CHAT,
                ModelCapability.TOOL_USE,
            ],
            provider_type=ProviderType.CLOUD_FRONTIER,
            context_window=128_000,
            cost_per_1k_input=0.005,
            cost_per_1k_output=0.015,
            supports_streaming=True,
            supports_tools=True,
            max_output_tokens=4096,
        ),
        "openai/gpt-4o-mini": ModelInfo(
            id="openai/gpt-4o-mini",
            name="GPT-4o Mini",
            provider="openrouter",
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODING,
                ModelCapability.CHAT,
            ],
            provider_type=ProviderType.CLOUD_BUDGET,
            context_window=128_000,
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.0006,
            supports_streaming=True,
            supports_tools=True,
            max_output_tokens=16384,
        ),
        "meta-llama/llama-3.1-70b-instruct": ModelInfo(
            id="meta-llama/llama-3.1-70b-instruct",
            name="Llama 3.1 70B",
            provider="openrouter",
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODING,
                ModelCapability.CHAT,
            ],
            provider_type=ProviderType.CLOUD_BUDGET,
            context_window=131_072,
            cost_per_1k_input=0.00035,
            cost_per_1k_output=0.0004,
            supports_streaming=True,
            supports_tools=False,
            max_output_tokens=4096,
        ),
        "deepseek/deepseek-r1": ModelInfo(
            id="deepseek/deepseek-r1",
            name="DeepSeek R1 (Reasoning)",
            provider="openrouter",
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODING,
            ],
            provider_type=ProviderType.CLOUD_FRONTIER,
            context_window=64_000,
            cost_per_1k_input=0.00055,
            cost_per_1k_output=0.00219,
            supports_streaming=True,
            supports_tools=False,
            max_output_tokens=8192,
        ),
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "openai/gpt-4o-mini",
        site_url: str = "https://shml-platform.local",
        site_name: str = "SHML Platform",
    ):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.default_model = default_model
        self.site_url = site_url
        self.site_name = site_name
        self._client: Optional[httpx.AsyncClient] = None

        if not self.api_key:
            logger.warning("No OpenRouter API key. Set OPENROUTER_API_KEY env var.")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=120.0,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "HTTP-Referer": self.site_url,
                    "X-Title": self.site_name,
                },
            )
        return self._client

    def _format_messages(self, messages: List[Message]) -> List[Dict]:
        """Convert to OpenAI format"""
        result = []
        for msg in messages:
            formatted = {"role": msg.role, "content": msg.content}

            if msg.images:
                content = [{"type": "text", "text": msg.content}]
                for img in msg.images:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img}"},
                        }
                    )
                formatted["content"] = content

            result.append(formatted)
        return result

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate completion via OpenRouter"""
        if not self.api_key:
            raise ProviderError("No API key configured", self.name, recoverable=False)

        model_id = request.model or self.default_model
        model_info = self.get_model(model_id) or self.MODELS[self.default_model]

        client = await self._get_client()

        body = {
            "model": model_id,
            "messages": self._format_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": min(request.max_tokens, model_info.max_output_tokens),
        }

        if request.tools and model_info.supports_tools:
            body["tools"] = request.tools

        start_time = datetime.now()

        try:
            response = await client.post(f"{self.BASE_URL}/chat/completions", json=body)

            if response.status_code == 429:
                raise RateLimitError(self.name)
            elif response.status_code != 200:
                raise ProviderError(
                    f"API error: {response.status_code} - {response.text}", self.name
                )

            data = response.json()

            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            # Calculate cost
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            cost = (input_tokens / 1000) * model_info.cost_per_1k_input + (
                output_tokens / 1000
            ) * model_info.cost_per_1k_output

            return CompletionResponse(
                content=content,
                model=model_id,
                provider=self.name,
                usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
                cost=cost,
                latency_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                finish_reason=data["choices"][0].get("finish_reason", "stop"),
                tool_calls=data["choices"][0]["message"].get("tool_calls"),
            )

        except httpx.TimeoutException:
            raise ProviderError("Request timed out", self.name, recoverable=True)

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncIterator[CompletionResponse]:
        """Stream completion via OpenRouter"""
        if not self.api_key:
            raise ProviderError("No API key configured", self.name, recoverable=False)

        model_id = request.model or self.default_model
        model_info = self.get_model(model_id) or self.MODELS[self.default_model]

        client = await self._get_client()

        body = {
            "model": model_id,
            "messages": self._format_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": min(request.max_tokens, model_info.max_output_tokens),
            "stream": True,
        }

        start_time = datetime.now()
        total_content = ""

        try:
            async with client.stream(
                "POST", f"{self.BASE_URL}/chat/completions", json=body
            ) as response:
                if response.status_code != 200:
                    raise ProviderError(f"API error: {response.status_code}", self.name)

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        if line == "data: [DONE]":
                            break

                        try:
                            data = json.loads(line[6:])
                            delta = data["choices"][0].get("delta", {})

                            if "content" in delta:
                                chunk = delta["content"]
                                total_content += chunk

                                yield CompletionResponse(
                                    content=chunk,
                                    model=model_id,
                                    provider=self.name,
                                    usage={"input_tokens": 0, "output_tokens": 0},
                                    cost=0.0,
                                    latency_ms=int(
                                        (datetime.now() - start_time).total_seconds()
                                        * 1000
                                    ),
                                    is_partial=True,
                                )
                        except json.JSONDecodeError:
                            continue

            # Final response with estimated cost
            output_tokens = len(total_content) // 4
            cost = (output_tokens / 1000) * model_info.cost_per_1k_output

            yield CompletionResponse(
                content=total_content,
                model=model_id,
                provider=self.name,
                usage={"input_tokens": 0, "output_tokens": output_tokens},
                cost=cost,
                latency_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                is_partial=False,
            )

        except httpx.TimeoutException:
            raise ProviderError("Stream timed out", self.name)

    async def health_check(self) -> ProviderStatus:
        """Check OpenRouter availability"""
        if not self.api_key:
            return ProviderStatus(available=False, error="No API key")

        try:
            client = await self._get_client()
            start = datetime.now()
            response = await client.get(f"{self.BASE_URL}/models")
            latency = int((datetime.now() - start).total_seconds() * 1000)

            if response.status_code == 200:
                return ProviderStatus(available=True, latency_ms=latency)
            else:
                return ProviderStatus(
                    available=False, error=f"API returned {response.status_code}"
                )
        except Exception as e:
            return ProviderStatus(available=False, error=str(e))

    async def fetch_models(self) -> List[ModelInfo]:
        """Fetch full model catalog from OpenRouter"""
        if not self.api_key:
            return list(self.MODELS.values())

        try:
            client = await self._get_client()
            response = await client.get(f"{self.BASE_URL}/models")

            if response.status_code == 200:
                data = response.json()
                # Update MODELS with fresh data
                # (simplified - full implementation would parse all fields)
                return list(self.MODELS.values())
        except Exception:
            pass

        return list(self.MODELS.values())

    def list_models(self) -> List[ModelInfo]:
        return list(self.MODELS.values())

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        return self.MODELS.get(model_id)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
