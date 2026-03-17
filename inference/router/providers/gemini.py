"""
Google Gemini Provider

Uses Google AI Studio API (generativelanguage.googleapis.com)
Supports Gemini Pro, Flash, and experimental models.
"""

import os
import httpx
import logging
from typing import List, Optional, AsyncIterator, Dict, Any
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
    QuotaExceededError,
)

logger = logging.getLogger(__name__)


class GeminiProvider(BaseProvider):
    """
    Google Gemini API Provider

    Setup:
    1. Get API key from https://makersuite.google.com/app/apikey
    2. Set GOOGLE_API_KEY environment variable or pass to constructor

    Models available:
    - gemini-2.0-flash-exp (free, fast reasoning)
    - gemini-1.5-pro (paid, best quality)
    - gemini-1.5-flash (paid, balanced)
    """

    name = "gemini"
    provider_type = ProviderType.CLOUD_FRONTIER

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    # Model catalog with pricing (as of Dec 2024)
    MODELS = {
        "gemini-2.0-flash-exp": ModelInfo(
            id="gemini-2.0-flash-exp",
            name="Gemini 2.0 Flash (Experimental)",
            provider="gemini",
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODING,
                ModelCapability.CHAT,
                ModelCapability.TOOL_USE,
            ],
            provider_type=ProviderType.CLOUD_FRONTIER,
            context_window=1_000_000,
            cost_per_1k_input=0.0,  # Free tier
            cost_per_1k_output=0.0,
            supports_streaming=True,
            supports_tools=True,
            max_output_tokens=8192,
        ),
        "gemini-1.5-pro": ModelInfo(
            id="gemini-1.5-pro",
            name="Gemini 1.5 Pro",
            provider="gemini",
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODING,
                ModelCapability.VISION,
                ModelCapability.CHAT,
                ModelCapability.TOOL_USE,
            ],
            provider_type=ProviderType.CLOUD_FRONTIER,
            context_window=2_000_000,
            cost_per_1k_input=0.00125,
            cost_per_1k_output=0.005,
            supports_streaming=True,
            supports_tools=True,
            max_output_tokens=8192,
        ),
        "gemini-1.5-flash": ModelInfo(
            id="gemini-1.5-flash",
            name="Gemini 1.5 Flash",
            provider="gemini",
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODING,
                ModelCapability.VISION,
                ModelCapability.CHAT,
            ],
            provider_type=ProviderType.CLOUD_BUDGET,
            context_window=1_000_000,
            cost_per_1k_input=0.000075,
            cost_per_1k_output=0.0003,
            supports_streaming=True,
            supports_tools=True,
            max_output_tokens=8192,
        ),
        "gemini-exp-1206": ModelInfo(
            id="gemini-exp-1206",
            name="Gemini Experimental (Dec 2024)",
            provider="gemini",
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODING,
                ModelCapability.VISION,
                ModelCapability.CHAT,
                ModelCapability.TOOL_USE,
            ],
            provider_type=ProviderType.CLOUD_FRONTIER,
            context_window=2_000_000,
            cost_per_1k_input=0.0,  # Experimental = free
            cost_per_1k_output=0.0,
            supports_streaming=True,
            supports_tools=True,
            max_output_tokens=8192,
        ),
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "gemini-2.0-flash-exp",
    ):
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("No Google API key found. Set GOOGLE_API_KEY env var.")

        self.default_model = default_model
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    def _format_messages(self, messages: List[Message]) -> Dict[str, Any]:
        """Convert messages to Gemini format"""
        contents = []
        system_instruction = None

        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content
                continue

            parts = []

            # Add text content
            if msg.content:
                parts.append({"text": msg.content})

            # Add images if present
            if msg.images:
                for img in msg.images:
                    # Assume base64 encoded
                    parts.append(
                        {"inline_data": {"mime_type": "image/jpeg", "data": img}}
                    )

            contents.append(
                {"role": "user" if msg.role == "user" else "model", "parts": parts}
            )

        result = {"contents": contents}
        if system_instruction:
            result["system_instruction"] = {"parts": [{"text": system_instruction}]}

        return result

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate a completion using Gemini API"""
        if not self.api_key:
            raise ProviderError("No API key configured", self.name, recoverable=False)

        model_id = request.model or self.default_model
        model_info = self.get_model(model_id)
        if not model_info:
            model_id = self.default_model
            model_info = self.MODELS[model_id]

        client = await self._get_client()

        # Build request body
        body = self._format_messages(request.messages)
        body["generationConfig"] = {
            "temperature": request.temperature,
            "maxOutputTokens": min(request.max_tokens, model_info.max_output_tokens),
        }

        # Add tools if provided
        if request.tools and model_info.supports_tools:
            body["tools"] = [{"function_declarations": request.tools}]

        url = f"{self.BASE_URL}/models/{model_id}:generateContent?key={self.api_key}"

        start_time = datetime.now()

        try:
            response = await client.post(url, json=body)

            if response.status_code == 429:
                raise RateLimitError(self.name)
            elif response.status_code == 403:
                raise QuotaExceededError(self.name)
            elif response.status_code != 200:
                raise ProviderError(
                    f"API error: {response.status_code} - {response.text}", self.name
                )

            data = response.json()

            # Extract content
            candidates = data.get("candidates", [])
            if not candidates:
                raise ProviderError("No response generated", self.name)

            content = ""
            tool_calls = None

            for part in candidates[0].get("content", {}).get("parts", []):
                if "text" in part:
                    content += part["text"]
                elif "functionCall" in part:
                    if tool_calls is None:
                        tool_calls = []
                    tool_calls.append(part["functionCall"])

            # Extract usage
            usage_meta = data.get("usageMetadata", {})
            input_tokens = usage_meta.get("promptTokenCount", 0)
            output_tokens = usage_meta.get("candidatesTokenCount", 0)

            # Calculate cost
            cost = (input_tokens / 1000) * model_info.cost_per_1k_input + (
                output_tokens / 1000
            ) * model_info.cost_per_1k_output

            latency = int((datetime.now() - start_time).total_seconds() * 1000)

            return CompletionResponse(
                content=content,
                model=model_id,
                provider=self.name,
                usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
                cost=cost,
                latency_ms=latency,
                finish_reason=candidates[0].get("finishReason", "STOP"),
                tool_calls=tool_calls,
            )

        except httpx.TimeoutException:
            raise ProviderError("Request timed out", self.name, recoverable=True)
        except httpx.RequestError as e:
            raise ProviderError(f"Request failed: {e}", self.name, recoverable=True)

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncIterator[CompletionResponse]:
        """Stream a completion (yields partial responses)"""
        if not self.api_key:
            raise ProviderError("No API key configured", self.name, recoverable=False)

        model_id = request.model or self.default_model
        model_info = self.get_model(model_id) or self.MODELS[self.default_model]

        client = await self._get_client()

        body = self._format_messages(request.messages)
        body["generationConfig"] = {
            "temperature": request.temperature,
            "maxOutputTokens": min(request.max_tokens, model_info.max_output_tokens),
        }

        url = f"{self.BASE_URL}/models/{model_id}:streamGenerateContent?key={self.api_key}&alt=sse"

        start_time = datetime.now()
        total_content = ""
        input_tokens = 0
        output_tokens = 0

        try:
            async with client.stream("POST", url, json=body) as response:
                if response.status_code != 200:
                    raise ProviderError(f"API error: {response.status_code}", self.name)

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])

                        for candidate in data.get("candidates", []):
                            for part in candidate.get("content", {}).get("parts", []):
                                if "text" in part:
                                    chunk = part["text"]
                                    total_content += chunk

                                    yield CompletionResponse(
                                        content=chunk,
                                        model=model_id,
                                        provider=self.name,
                                        usage={"input_tokens": 0, "output_tokens": 0},
                                        cost=0,
                                        latency_ms=int(
                                            (
                                                datetime.now() - start_time
                                            ).total_seconds()
                                            * 1000
                                        ),
                                        is_partial=True,
                                    )

                        # Update token counts
                        usage = data.get("usageMetadata", {})
                        input_tokens = usage.get("promptTokenCount", input_tokens)
                        output_tokens = usage.get("candidatesTokenCount", output_tokens)

            # Final response with full content and usage
            cost = (input_tokens / 1000) * model_info.cost_per_1k_input + (
                output_tokens / 1000
            ) * model_info.cost_per_1k_output

            yield CompletionResponse(
                content=total_content,
                model=model_id,
                provider=self.name,
                usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
                cost=cost,
                latency_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                is_partial=False,
            )

        except httpx.TimeoutException:
            raise ProviderError("Stream timed out", self.name, recoverable=True)

    async def health_check(self) -> ProviderStatus:
        """Check if Gemini API is available"""
        if not self.api_key:
            return ProviderStatus(available=False, error="No API key")

        try:
            client = await self._get_client()
            url = f"{self.BASE_URL}/models?key={self.api_key}"

            start = datetime.now()
            response = await client.get(url)
            latency = int((datetime.now() - start).total_seconds() * 1000)

            if response.status_code == 200:
                return ProviderStatus(available=True, latency_ms=latency)
            else:
                return ProviderStatus(
                    available=False, error=f"API returned {response.status_code}"
                )
        except Exception as e:
            return ProviderStatus(available=False, error=str(e))

    def list_models(self) -> List[ModelInfo]:
        """List available Gemini models"""
        return list(self.MODELS.values())

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        """Get info about a specific model"""
        return self.MODELS.get(model_id)

    async def close(self):
        """Close the HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None
