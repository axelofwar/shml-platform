"""
OpenAI-compatible API endpoint for agent-service.

This module provides OpenAI-compatible /v1/chat/completions endpoint
to enable integration with Cursor, Continue.dev, and other IDE tools.

Differences from chat-api:
- Uses agent-service's model loading (shares with ACE workflow)
- Simple mode: No ACE workflow, no tool execution
- Streaming via SSE (Server-Sent Events)
- OAuth2 authentication (no API keys)
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)


# =============================================================================
# OpenAI Schema Definitions
# =============================================================================


class OpenAIMessage:
    """OpenAI-compatible message format."""

    def __init__(self, role: str, content: str, name: Optional[str] = None):
        self.role = role
        self.content = content
        self.name = name

    def to_dict(self) -> Dict[str, Any]:
        msg = {"role": self.role, "content": self.content}
        if self.name:
            msg["name"] = self.name
        return msg


class OpenAIChatCompletionRequest:
    """OpenAI chat completion request schema."""

    def __init__(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        top_p: float = 1.0,
        frequency_penalty: float = 0.0,
        presence_penalty: float = 0.0,
        stop: Optional[List[str]] = None,
        n: int = 1,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
    ):
        self.model = model
        self.messages = messages
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stream = stream
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.presence_penalty = presence_penalty
        self.stop = stop
        self.n = n
        self.tools = tools
        self.tool_choice = tool_choice


class OpenAIChatCompletionResponse:
    """OpenAI chat completion response schema."""

    def __init__(
        self,
        id: str,
        model: str,
        choices: List[Dict[str, Any]],
        created: int,
        usage: Dict[str, int],
    ):
        self.id = id
        self.object = "chat.completion"
        self.model = model
        self.choices = choices
        self.created = created
        self.usage = usage

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "object": self.object,
            "created": self.created,
            "model": self.model,
            "choices": self.choices,
            "usage": self.usage,
        }


# =============================================================================
# OpenAI Compatibility Layer
# =============================================================================


class OpenAICompatibilityLayer:
    """Converts between OpenAI format and agent-service internal format."""

    def __init__(self, model_client):
        """
        Initialize with model client for inference.

        Args:
            model_client: Client for calling inference models (coding-model, etc.)
        """
        self.model_client = model_client

    async def generate_completion(
        self,
        request: OpenAIChatCompletionRequest,
        user_id: str,
        user_roles: List[str],
    ) -> OpenAIChatCompletionResponse:
        """
        Generate non-streaming chat completion.

        Args:
            request: OpenAI-compatible request
            user_id: Authenticated user ID
            user_roles: User's roles

        Returns:
            OpenAI-compatible response
        """
        start_time = time.time()

        # Convert to internal format
        messages = self._convert_messages(request.messages)

        # Call model
        response_data, model_used = await self._call_model(
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            model_preference=request.model,
            tools=request.tools,
            tool_choice=request.tool_choice,
        )

        # Unpack response — may contain tool_calls
        response_text = response_data.get("content") or ""
        tool_calls = response_data.get("tool_calls")
        finish_reason = "tool_calls" if tool_calls else "stop"

        # Calculate tokens (approximate)
        prompt_tokens = sum(len(m.get("content", "").split()) for m in request.messages)
        completion_tokens = len(response_text.split())

        # Build message dict — include tool_calls when present
        message_dict: Dict[str, Any] = {"role": "assistant", "content": response_text or None}
        if tool_calls:
            message_dict["tool_calls"] = tool_calls

        # Build OpenAI response
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        response = OpenAIChatCompletionResponse(
            id=completion_id,
            model=model_used,
            created=int(time.time()),
            choices=[
                {
                    "index": 0,
                    "message": message_dict,
                    "finish_reason": finish_reason,
                }
            ],
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )

        latency_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"OpenAI completion: user={user_id}, model={model_used}, "
            f"tokens={prompt_tokens + completion_tokens}, latency={latency_ms}ms"
        )

        return response

    async def generate_stream(
        self,
        request: OpenAIChatCompletionRequest,
        user_id: str,
        user_roles: List[str],
    ) -> AsyncGenerator[str, None]:
        """
        Generate streaming chat completion (SSE format).

        Args:
            request: OpenAI-compatible request
            user_id: Authenticated user ID
            user_roles: User's roles

        Yields:
            Server-sent events in OpenAI format
        """
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        created_at = int(time.time())

        # Convert to internal format
        messages = self._convert_messages(request.messages)

        # When tools are present, use non-streaming path and emit SSE from the result.
        # Tool calls must be complete before Hermes can execute them — no benefit to streaming.
        if request.tools:
            response_data, model_name = await self._call_model(
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                model_preference=request.model,
                tools=request.tools,
                tool_choice=request.tool_choice,
            )
            tool_calls = response_data.get("tool_calls")
            content = response_data.get("content") or ""

            if tool_calls:
                # Emit role chunk
                role_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_at,
                    "model": model_name,
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": None}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(role_chunk)}\n\n"

                # Emit each tool call as a delta chunk per OpenAI spec
                for i, tc in enumerate(tool_calls):
                    tc_chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created_at,
                        "model": model_name,
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "tool_calls": [{
                                    "index": i,
                                    "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                                    "type": "function",
                                    "function": {
                                        "name": tc["function"]["name"],
                                        "arguments": tc["function"].get("arguments", ""),
                                    },
                                }]
                            },
                            "finish_reason": None,
                        }],
                    }
                    yield f"data: {json.dumps(tc_chunk)}\n\n"

                # Final finish chunk
                finish_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_at,
                    "model": model_name,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                }
                yield f"data: {json.dumps(finish_chunk)}\n\n"
            else:
                # No tool calls — stream the content as text
                async for chunk in self._stream_words(content, model_name, completion_id, created_at):
                    yield chunk

            yield "data: [DONE]\n\n"
            return

        # Stream from model (no tools)
        async for chunk in self._stream_model(
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            model_preference=request.model,
        ):
            # Format as OpenAI streaming chunk
            stream_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_at,
                "model": chunk.get("model", "qwen-coder"),
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": chunk.get("content", ""),
                        },
                        "finish_reason": chunk.get("finish_reason"),
                    }
                ],
            }

            # Yield as SSE
            yield f"data: {json.dumps(stream_chunk)}\n\n"

        # Send [DONE] marker
        yield "data: [DONE]\n\n"

    async def _stream_words(
        self,
        content: str,
        model_name: str,
        completion_id: str,
        created_at: int,
    ) -> AsyncGenerator[str, None]:
        """Yield content word-by-word as SSE chunks."""
        words = content.split()
        chunk_size = 3
        for i in range(0, len(words), chunk_size):
            chunk_text = " ".join(words[i: i + chunk_size])
            if i + chunk_size < len(words):
                chunk_text += " "
            stream_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_at,
                "model": model_name,
                "choices": [{"index": 0, "delta": {"content": chunk_text}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(stream_chunk)}\n\n"
            await asyncio.sleep(0.01)
        done_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_at,
            "model": model_name,
            "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(done_chunk)}\n\n"

    def _convert_messages(
        self, openai_messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI messages to internal format, preserving tool call fields."""
        result = []
        for msg in openai_messages:
            m: Dict[str, Any] = {
                "role": msg.get("role"),
                "content": msg.get("content") if msg.get("content") is not None else "",
            }
            if msg.get("name"):
                m["name"] = msg["name"]
            # Preserve tool calling fields for multi-turn tool use
            if msg.get("tool_calls"):
                m["tool_calls"] = msg["tool_calls"]
            if msg.get("tool_call_id"):
                m["tool_call_id"] = msg["tool_call_id"]
            result.append(m)
        return result

    def _resolve_endpoint(
        self, model_preference: str, prompt: str = ""
    ) -> tuple[str, str]:
        """Resolve model endpoint using hybrid router when available.

        Falls back to hardcoded mapping if router unavailable.

        Returns:
            (endpoint_url, model_display_name)
        """
        try:
            from .hybrid_router import get_hybrid_router

            router = get_hybrid_router()
            selection = router.route(
                prompt=prompt, request_id=f"openai-compat-{uuid.uuid4().hex[:6]}"
            )
            # Map model_type to endpoint
            model_type = selection.model_type.value
            endpoint_map = {
                "qwopus-coding": "http://qwopus-coding:8000/v1/chat/completions",
                "qwen-coder": "http://qwopus-coding:8000/v1/chat/completions",  # legacy alias
                "qwen3-vl": "http://qwen3-vl-api:8000/v1/chat/completions",
                "z-image": "http://z-image-api:8000/v1/images/generations",
            }
            endpoint = endpoint_map.get(
                model_type, "http://qwopus-coding:8000/v1/chat/completions"
            )
            logger.info(
                f"Hybrid router resolved: {model_type} → {endpoint} "
                f"(conf={selection.confidence:.2f})"
            )
            return endpoint, model_type
        except Exception as e:
            logger.warning(f"Hybrid router unavailable, using fallback: {e}")

        # Fallback: hardcoded mapping
        if "30b" in model_preference.lower() or "quality" in model_preference.lower():
            return (
                "http://qwopus-coding:8000/v1/chat/completions",
                "qwopus-coding",
            )
        elif "vision" in model_preference.lower() or "vl" in model_preference.lower():
            return (
                "http://qwen3-vl-api:8000/v1/chat/completions",
                "qwen3-vl",
            )
        return (
            "http://qwopus-coding:8000/v1/chat/completions",
            "qwopus-coding",
        )

    async def _call_model(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: Optional[int],
        model_preference: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
    ) -> tuple[Dict[str, Any], str]:
        """
        Call inference model (non-streaming) via hybrid router.

        Returns:
            (response_dict with content and optional tool_calls, model_used)
        """
        # Extract prompt for routing decision
        prompt = ""
        if messages:
            last_user = next(
                (m["content"] for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            prompt = last_user if isinstance(last_user, str) else str(last_user)

        model_endpoint, model_name = self._resolve_endpoint(model_preference, prompt)

        import httpx

        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                body: Dict[str, Any] = {
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens or 2048,
                    "stream": False,
                }
                if tools:
                    body["tools"] = tools
                if tool_choice is not None:
                    body["tool_choice"] = tool_choice

                resp = await client.post(model_endpoint, json=body)

                if resp.status_code != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Model service error: {resp.text}",
                    )

                data = resp.json()
                msg = data["choices"][0]["message"]
                response_data: Dict[str, Any] = {
                    "content": msg.get("content") or "",
                    "tool_calls": msg.get("tool_calls"),
                }

                return response_data, model_name

            except httpx.RequestError as e:
                logger.error(f"HTTP request failed: {e}")
                raise HTTPException(
                    status_code=503,
                    detail=f"Model service unavailable: {str(e)}",
                )

    async def _stream_model(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: Optional[int],
        model_preference: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream from inference model.

        IMPLEMENTATION NOTE:
        The coding-model service doesn't support true streaming yet (vLLM limitation).
        Instead, we implement "chunked streaming" - get complete response and yield it
        in chunks for better UX and compatibility with streaming clients.

        This approach:
        - Works with non-streaming backends
        - Provides progressive feedback to users
        - Compatible with OpenAI streaming format
        - Lower latency than true streaming (for short responses)

        Yields:
            Chunks with content, model, finish_reason
        """
        # Resolve endpoint via hybrid router
        prompt = ""
        if messages:
            last_user = next(
                (m["content"] for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            prompt = last_user if isinstance(last_user, str) else str(last_user)

        model_endpoint, model_name = self._resolve_endpoint(model_preference, prompt)

        import httpx

        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                # First, try requesting with stream=true to check if backend supports it
                async with client.stream(
                    "POST",
                    model_endpoint,
                    json={
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens or 2048,
                        "stream": True,
                    },
                ) as resp:
                    if resp.status_code != 200:
                        error_text = await resp.aread()
                        raise HTTPException(
                            status_code=502,
                            detail=f"Model service error ({resp.status_code}): {error_text.decode()}",
                        )

                    # Check content type to determine if it's SSE or JSON
                    content_type = resp.headers.get("content-type", "")

                    if "text/event-stream" in content_type:
                        # Backend supports true SSE streaming
                        logger.debug(f"Using true SSE streaming for {model_name}")
                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue

                            if line == "data: [DONE]":
                                break

                            try:
                                data = json.loads(line[6:])
                                if "choices" in data and data["choices"]:
                                    choice = data["choices"][0]
                                    delta = choice.get("delta", {})
                                    content = delta.get("content", "")
                                    finish_reason = choice.get("finish_reason")

                                    if content or finish_reason:
                                        yield {
                                            "content": content,
                                            "model": model_name,
                                            "finish_reason": finish_reason,
                                        }
                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to parse SSE: {e}")
                                continue
                    else:
                        # Backend returned complete JSON response (no streaming support)
                        # Implement "chunked streaming" for better UX
                        logger.debug(
                            f"Backend doesn't support streaming, using chunked mode for {model_name}"
                        )
                        response_bytes = await resp.aread()
                        data = json.loads(response_bytes)

                        # Extract the complete response
                        if "choices" in data and data["choices"]:
                            content = data["choices"][0]["message"]["content"]

                            # Chunk the response (word-by-word for natural feel)
                            # SOTA: Yield every 3-5 tokens for good balance of:
                            # - Responsiveness (users see progress)
                            # - Efficiency (not too many events)
                            # - Natural reading pace
                            words = content.split()
                            chunk_size = 3  # Words per chunk

                            for i in range(0, len(words), chunk_size):
                                chunk_words = words[i : i + chunk_size]
                                chunk_text = " ".join(chunk_words)

                                # Add space after chunk unless it's the last one
                                if i + chunk_size < len(words):
                                    chunk_text += " "

                                yield {
                                    "content": chunk_text,
                                    "model": model_name,
                                    "finish_reason": None,
                                }

                                # Small delay for natural streaming feel (10ms per chunk)
                                await asyncio.sleep(0.01)

                            # Send final chunk with finish_reason
                            yield {
                                "content": "",
                                "model": model_name,
                                "finish_reason": "stop",
                            }

            except httpx.RequestError as e:
                logger.error(f"Streaming request failed: {e}")
                raise HTTPException(
                    status_code=503,
                    detail=f"Model service unavailable: {str(e)}",
                )
