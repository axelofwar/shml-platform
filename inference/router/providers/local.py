"""
Local Model Provider

Routes to local inference services (Nemotron, Qwen-VL).
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
)

logger = logging.getLogger(__name__)


class LocalProvider(BaseProvider):
    """
    Local GPU Model Provider

    Routes to local inference services:
    - Nemotron-Mini-4B (RTX 3090, coding)
    - Qwen3-VL-8B (RTX 2070, vision + chat)

    Uses OpenAI-compatible API format.
    """

    name = "local"
    provider_type = ProviderType.LOCAL_GPU

    def __init__(
        self,
        nemotron_url: str = "http://localhost:8010",
        qwen_url: str = "http://localhost/api/llm",  # Via Traefik (needs auth) or docker network
    ):
        self.nemotron_url = nemotron_url
        self.qwen_url = qwen_url
        self._client: Optional[httpx.AsyncClient] = None

        # Model catalog
        self.MODELS = {
            "nemotron-mini-4b": ModelInfo(
                id="nemotron-mini-4b",
                name="Nemotron-Mini-4B (Local)",
                provider="local",
                capabilities=[ModelCapability.CODING],
                provider_type=ProviderType.LOCAL_GPU,
                context_window=8192,
                cost_per_1k_input=0.0,
                cost_per_1k_output=0.0,
                supports_streaming=True,
                supports_tools=False,
                max_output_tokens=4096,
            ),
            "qwen3-vl-8b": ModelInfo(
                id="qwen3-vl-8b",
                name="Qwen3-VL-8B (Local)",
                provider="local",
                capabilities=[
                    ModelCapability.VISION,
                    ModelCapability.CHAT,
                    ModelCapability.CODING,
                ],
                provider_type=ProviderType.LOCAL_GPU,
                context_window=32768,
                cost_per_1k_input=0.0,
                cost_per_1k_output=0.0,
                supports_streaming=True,
                supports_tools=False,
                max_output_tokens=4096,
            ),
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=300.0)  # Long timeout for local
        return self._client

    def _get_url_for_model(self, model_id: str) -> str:
        """Get the service URL for a model"""
        if "qwen" in model_id.lower() or "vl" in model_id.lower():
            return self.qwen_url
        return self.nemotron_url

    def _format_messages(self, messages: List[Message]) -> List[Dict]:
        """Convert to OpenAI format"""
        result = []
        for msg in messages:
            formatted = {"role": msg.role, "content": msg.content}

            # Handle vision content
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
        """Generate completion from local model"""
        # Auto-select model based on capabilities needed
        model_id = request.model

        if not model_id:
            # Choose based on required capabilities
            if ModelCapability.VISION in request.required_capabilities:
                model_id = "qwen3-vl-8b"
            else:
                model_id = "nemotron-mini-4b"

        # Check if any message has images
        has_images = any(msg.images for msg in request.messages)
        if has_images and "qwen" not in model_id.lower():
            model_id = "qwen3-vl-8b"
            logger.info("Auto-switching to Qwen-VL for image processing")

        model_info = self.get_model(model_id)
        if not model_info:
            model_id = "nemotron-mini-4b"
            model_info = self.MODELS[model_id]

        url = self._get_url_for_model(model_id)
        client = await self._get_client()

        body = {
            "model": model_id,
            "messages": self._format_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }

        start_time = datetime.now()

        try:
            response = await client.post(f"{url}/v1/chat/completions", json=body)

            if response.status_code != 200:
                raise ProviderError(
                    f"Local API error: {response.status_code} - {response.text}",
                    self.name,
                )

            data = response.json()

            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            return CompletionResponse(
                content=content,
                model=model_id,
                provider=self.name,
                usage={
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                },
                cost=0.0,  # Free - local
                latency_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                finish_reason=data["choices"][0].get("finish_reason", "stop"),
            )

        except httpx.TimeoutException:
            raise ProviderError("Local model timed out", self.name, recoverable=True)
        except httpx.RequestError as e:
            raise ProviderError(
                f"Local model unavailable: {e}", self.name, recoverable=True
            )

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncIterator[CompletionResponse]:
        """Stream completion from local model"""
        model_id = request.model or "nemotron-mini-4b"

        has_images = any(msg.images for msg in request.messages)
        if has_images:
            model_id = "qwen3-vl-8b"

        model_info = self.get_model(model_id) or self.MODELS["nemotron-mini-4b"]
        url = self._get_url_for_model(model_id)
        client = await self._get_client()

        body = {
            "model": model_id,
            "messages": self._format_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }

        start_time = datetime.now()
        total_content = ""

        try:
            async with client.stream(
                "POST", f"{url}/v1/chat/completions", json=body
            ) as response:
                if response.status_code != 200:
                    raise ProviderError(
                        f"Local API error: {response.status_code}", self.name
                    )

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        if line == "data: [DONE]":
                            break

                        try:
                            data = json.loads(line[6:])
                            delta = data["choices"][0].get("delta", {})
                            chunk = delta.get("content")

                            if chunk:  # Only yield if there's actual content
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

            # Final response
            yield CompletionResponse(
                content=total_content,
                model=model_id,
                provider=self.name,
                usage={
                    "input_tokens": len(total_content) // 4,
                    "output_tokens": len(total_content) // 4,
                },
                cost=0.0,
                latency_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                is_partial=False,
            )

        except httpx.TimeoutException:
            raise ProviderError("Stream timed out", self.name)

    async def health_check(self) -> ProviderStatus:
        """Check if local models are available"""
        client = await self._get_client()
        errors = []
        latencies = []

        for model_id, model in self.MODELS.items():
            url = self._get_url_for_model(model_id)
            try:
                start = datetime.now()
                response = await client.get(f"{url}/health", timeout=5.0)
                latency = int((datetime.now() - start).total_seconds() * 1000)

                if response.status_code == 200:
                    latencies.append(latency)
                else:
                    errors.append(f"{model_id}: HTTP {response.status_code}")
            except Exception as e:
                errors.append(f"{model_id}: {str(e)}")

        if latencies:
            return ProviderStatus(
                available=True,
                latency_ms=min(latencies),
                error="; ".join(errors) if errors else None,
            )
        else:
            return ProviderStatus(available=False, error="; ".join(errors))

    def list_models(self) -> List[ModelInfo]:
        return list(self.MODELS.values())

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        return self.MODELS.get(model_id)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
