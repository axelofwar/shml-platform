"""Model selection and routing logic."""

import time
import logging
from typing import Optional, Dict, Any, List, AsyncIterator
import json

import httpx

from .config import (
    PRIMARY_MODEL_URL,
    FALLBACK_MODEL_URL,
    MODEL_AUTO_THRESHOLD_TOKENS,
    ASK_ONLY_SYSTEM_PROMPT,
)
from .schemas import (
    ModelSelection,
    ModelInfo,
    ChatMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatCompletionUsage,
    RequestSource,
)

logger = logging.getLogger(__name__)


class ModelRouter:
    """Routes requests to the appropriate model based on selection."""

    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None

        # Model metadata
        self.models = {
            "primary": ModelInfo(
                id="qwen3-coder-30b",
                name="Qwen3 Coder 30B (AWQ 4-bit)",
                description="High-quality code generation model. Best for complex tasks.",
                context_length=16384,
                is_available=False,
                gpu="RTX 3090 Ti",
                vram_gb=24,
                recommended_for=[
                    "complex refactoring",
                    "architecture design",
                    "code review",
                    "long context",
                ],
            ),
            "fallback": ModelInfo(
                id="qwen2.5-coder-3b",
                name="Qwen2.5 Coder 3B (AWQ)",
                description="Fast code generation model. Best for simple tasks and quick responses.",
                context_length=8192,
                is_available=False,
                gpu="RTX 2070",
                vram_gb=8,
                recommended_for=[
                    "code completion",
                    "simple edits",
                    "quick questions",
                    "low latency",
                ],
            ),
        }

        self.urls = {
            "primary": PRIMARY_MODEL_URL,
            "fallback": FALLBACK_MODEL_URL,
        }

    async def connect(self):
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(timeout=300.0)
        await self._check_model_health()

    async def close(self):
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()

    async def _check_model_health(self):
        """Check which models are available."""
        for model_key, url in self.urls.items():
            try:
                resp = await self.client.get(f"{url}/health", timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    self.models[model_key].is_available = (
                        data.get("status") == "healthy"
                    )
                else:
                    self.models[model_key].is_available = False
            except Exception as e:
                logger.warning(f"Model {model_key} health check failed: {e}")
                self.models[model_key].is_available = False

    async def get_model_status(self) -> Dict[str, ModelInfo]:
        """Get status of all models."""
        await self._check_model_health()
        return self.models

    def _estimate_tokens(self, messages: List[ChatMessage]) -> int:
        """Estimate token count from messages (rough approximation)."""
        total_chars = sum(len(m.content) for m in messages)
        # Rough estimate: 4 chars per token
        return total_chars // 4

    def _select_model(
        self,
        selection: ModelSelection,
        messages: List[ChatMessage],
    ) -> str:
        """Select which model to use based on selection and query complexity."""
        # Handle aliases
        if selection == ModelSelection.QUALITY:
            selection = ModelSelection.PRIMARY
        elif selection == ModelSelection.FAST:
            selection = ModelSelection.FALLBACK

        # Direct selection
        if selection == ModelSelection.PRIMARY:
            if self.models["primary"].is_available:
                return "primary"
            logger.warning("Primary model requested but unavailable, falling back")
            return "fallback"

        if selection == ModelSelection.FALLBACK:
            return "fallback"

        # Auto selection based on complexity
        if selection == ModelSelection.AUTO:
            estimated_tokens = self._estimate_tokens(messages)

            # Use primary for complex queries (>1000 tokens)
            if estimated_tokens > MODEL_AUTO_THRESHOLD_TOKENS:
                if self.models["primary"].is_available:
                    logger.info(
                        f"Auto-selected primary model ({estimated_tokens} tokens)"
                    )
                    return "primary"

            # Check if primary is available for any auto query
            # Prefer fallback for speed unless query is complex
            if self.models["fallback"].is_available:
                logger.info(f"Auto-selected fallback model ({estimated_tokens} tokens)")
                return "fallback"

            # Fall through to primary if fallback unavailable
            if self.models["primary"].is_available:
                return "primary"

        # Last resort - return whatever is available
        if self.models["fallback"].is_available:
            return "fallback"
        if self.models["primary"].is_available:
            return "primary"

        raise RuntimeError("No models available")

    async def generate(
        self,
        request: ChatCompletionRequest,
        user_instructions: Optional[str] = None,
    ) -> tuple[ChatCompletionResponse, str, int]:
        """
        Generate a chat completion.

        Returns:
            tuple: (response, model_used, latency_ms)
        """
        # Refresh model health
        await self._check_model_health()

        # Parse model selection
        try:
            selection = ModelSelection(request.model.lower())
        except ValueError:
            # If specific model ID provided, try to match
            if "30b" in request.model.lower() or "primary" in request.model.lower():
                selection = ModelSelection.PRIMARY
            elif "3b" in request.model.lower() or "fallback" in request.model.lower():
                selection = ModelSelection.FALLBACK
            else:
                selection = ModelSelection.AUTO

        # Select model
        model_key = self._select_model(selection, request.messages)
        url = self.urls[model_key]
        model_info = self.models[model_key]

        # Prepare messages with instructions
        messages = []

        # Build the system prompt based on source and user instructions
        system_prompt_parts = []

        # For web requests, always prepend the ask-only constraint
        if request.source == RequestSource.WEB:
            system_prompt_parts.append(ASK_ONLY_SYSTEM_PROMPT)

        # Add user instructions if provided
        if user_instructions and request.include_instructions:
            system_prompt_parts.append(user_instructions)

        combined_system = (
            "\n\n".join(system_prompt_parts) if system_prompt_parts else None
        )

        # Build messages list
        if combined_system:
            # Check if first message is already a system message
            if request.messages and request.messages[0].role == "system":
                # Prepend our system prompt to existing system message
                combined_content = f"{combined_system}\n\n{request.messages[0].content}"
                messages.append({"role": "system", "content": combined_content})
                messages.extend([m.model_dump() for m in request.messages[1:]])
            else:
                # Add new system message
                messages.append({"role": "system", "content": combined_system})
                messages.extend([m.model_dump() for m in request.messages])
        else:
            messages = [m.model_dump() for m in request.messages]

        # Build request for backend
        backend_request = {
            "messages": messages,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
            "stream": False,  # Handle streaming separately
            "stop": request.stop,
        }

        start_time = time.time()

        try:
            resp = await self.client.post(
                f"{url}/v1/chat/completions",
                json=backend_request,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Model {model_key} returned error: {e.response.text}")
            raise RuntimeError(f"Model error: {e.response.text}")
        except Exception as e:
            logger.error(f"Failed to call model {model_key}: {e}")
            raise

        latency_ms = int((time.time() - start_time) * 1000)

        # Build response
        response = ChatCompletionResponse(
            id=data.get("id", f"chatcmpl-{model_key}"),
            created=data.get("created", int(time.time())),
            model=model_info.id,
            choices=[
                ChatCompletionChoice(
                    index=c["index"],
                    message=ChatMessage(
                        role=c["message"]["role"],
                        content=c["message"]["content"],
                    ),
                    finish_reason=c.get("finish_reason"),
                )
                for c in data.get("choices", [])
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                total_tokens=data.get("usage", {}).get("total_tokens", 0),
            ),
            model_selection=model_key,
        )

        return response, model_key, latency_ms

    async def generate_stream(
        self,
        request: ChatCompletionRequest,
        user_instructions: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Generate a streaming chat completion."""
        # Similar to generate but with streaming
        await self._check_model_health()

        try:
            selection = ModelSelection(request.model.lower())
        except ValueError:
            selection = ModelSelection.AUTO

        model_key = self._select_model(selection, request.messages)
        url = self.urls[model_key]

        # Build system prompt based on source and user instructions
        system_prompt_parts = []

        # For web requests, always prepend the ask-only constraint
        if request.source == RequestSource.WEB:
            system_prompt_parts.append(ASK_ONLY_SYSTEM_PROMPT)

        # Add user instructions if provided
        if user_instructions and request.include_instructions:
            system_prompt_parts.append(user_instructions)

        combined_system = (
            "\n\n".join(system_prompt_parts) if system_prompt_parts else None
        )

        # Build messages list
        messages = []
        if combined_system:
            if request.messages and request.messages[0].role == "system":
                combined_content = f"{combined_system}\n\n{request.messages[0].content}"
                messages.append({"role": "system", "content": combined_content})
                messages.extend([m.model_dump() for m in request.messages[1:]])
            else:
                messages.append({"role": "system", "content": combined_system})
                messages.extend([m.model_dump() for m in request.messages])
        else:
            messages = [m.model_dump() for m in request.messages]

        backend_request = {
            "messages": messages,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
            "stream": True,
            "stop": request.stop,
        }

        async with self.client.stream(
            "POST",
            f"{url}/v1/chat/completions",
            json=backend_request,
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    yield line + "\n\n"


# Global instance
model_router = ModelRouter()
