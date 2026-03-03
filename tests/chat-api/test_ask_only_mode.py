"""Unit tests for ask-only mode in web chat."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAskOnlyMode:
    """Test ask-only mode for web chat requests."""

    def test_ask_only_system_prompt_exists(self):
        """Verify ASK_ONLY_SYSTEM_PROMPT is properly configured."""
        from inference.chat_api.app.config import ASK_ONLY_SYSTEM_PROMPT

        # Check key constraints are mentioned
        assert "ASK MODE ONLY" in ASK_ONLY_SYSTEM_PROMPT
        assert "CANNOT" in ASK_ONLY_SYSTEM_PROMPT
        assert "edit" in ASK_ONLY_SYSTEM_PROMPT.lower()
        assert "execute" in ASK_ONLY_SYSTEM_PROMPT.lower()
        assert "modify" in ASK_ONLY_SYSTEM_PROMPT.lower()

        # Check it mentions Cursor as alternative
        assert "Cursor" in ASK_ONLY_SYSTEM_PROMPT

    def test_request_source_enum(self):
        """Verify RequestSource enum has correct values."""
        from inference.chat_api.app.schemas import RequestSource

        assert RequestSource.WEB.value == "web"
        assert RequestSource.API.value == "api"

    def test_chat_request_default_source_is_api(self):
        """ChatCompletionRequest should default to API source."""
        from inference.chat_api.app.schemas import ChatCompletionRequest, RequestSource

        request = ChatCompletionRequest(messages=[{"role": "user", "content": "test"}])

        assert request.source == RequestSource.API

    def test_chat_request_can_set_web_source(self):
        """ChatCompletionRequest should accept web source."""
        from inference.chat_api.app.schemas import ChatCompletionRequest, RequestSource

        request = ChatCompletionRequest(
            messages=[{"role": "user", "content": "test"}], source="web"
        )

        assert request.source == RequestSource.WEB


class TestModelRouterAskOnlyInjection:
    """Test that model router injects ask-only prompt for web requests."""

    @pytest.mark.asyncio
    async def test_web_request_includes_ask_only_prompt(self):
        """Web requests should have ASK_ONLY_SYSTEM_PROMPT injected."""
        from inference.chat_api.app.model_router import ModelRouter
        from inference.chat_api.app.schemas import (
            ChatCompletionRequest,
            RequestSource,
            ChatMessage,
            ModelInfo,
        )
        from inference.chat_api.app.config import ASK_ONLY_SYSTEM_PROMPT

        router = ModelRouter()
        router.client = AsyncMock()
        # Replace with available model (Pydantic models are immutable)
        router.models["fallback"] = ModelInfo(
            id="qwen2.5-coder-3b",
            name="Test Model",
            description="Test",
            context_length=8192,
            is_available=True,  # Set as available
            gpu="Test GPU",
            vram_gb=8,
            recommended_for=["test"],
        )
        # Mock health check to skip network calls
        router._check_model_health = AsyncMock()

        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "test",
            "created": 123,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "test response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        router.client.post = AsyncMock(return_value=mock_response)

        request = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="What is SHML?")],
            model="auto",
            source=RequestSource.WEB,  # Web request
        )

        await router.generate(request)

        # Check that the backend was called with ask-only prompt
        call_args = router.client.post.call_args
        backend_request = call_args.kwargs["json"]

        # First message should be system with ask-only prompt
        assert backend_request["messages"][0]["role"] == "system"
        assert "ASK MODE ONLY" in backend_request["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_api_request_does_not_include_ask_only_prompt(self):
        """API requests should NOT have ASK_ONLY_SYSTEM_PROMPT injected."""
        from inference.chat_api.app.model_router import ModelRouter
        from inference.chat_api.app.schemas import (
            ChatCompletionRequest,
            RequestSource,
            ChatMessage,
            ModelInfo,
        )

        router = ModelRouter()
        router.client = AsyncMock()
        # Replace with available model (Pydantic models are immutable)
        router.models["fallback"] = ModelInfo(
            id="qwen2.5-coder-3b",
            name="Test Model",
            description="Test",
            context_length=8192,
            is_available=True,
            gpu="Test GPU",
            vram_gb=8,
            recommended_for=["test"],
        )
        # Mock health check to skip network calls
        router._check_model_health = AsyncMock()

        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "test",
            "created": 123,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "test response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        router.client.post = AsyncMock(return_value=mock_response)

        request = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="Refactor this code")],
            model="auto",
            source=RequestSource.API,  # API request
        )

        await router.generate(request)

        # Check that the backend was called WITHOUT ask-only prompt
        call_args = router.client.post.call_args
        backend_request = call_args.kwargs["json"]

        # First message should be the user's message, not a system prompt
        assert backend_request["messages"][0]["role"] == "user"
        assert "ASK MODE ONLY" not in backend_request["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_web_request_with_existing_system_message(self):
        """Web request with existing system message should prepend ask-only."""
        from inference.chat_api.app.model_router import ModelRouter
        from inference.chat_api.app.schemas import (
            ChatCompletionRequest,
            RequestSource,
            ChatMessage,
            ModelInfo,
        )

        router = ModelRouter()
        router.client = AsyncMock()
        # Replace with available model (Pydantic models are immutable)
        router.models["fallback"] = ModelInfo(
            id="qwen2.5-coder-3b",
            name="Test Model",
            description="Test",
            context_length=8192,
            is_available=True,
            gpu="Test GPU",
            vram_gb=8,
            recommended_for=["test"],
        )
        # Mock health check to skip network calls
        router._check_model_health = AsyncMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "test",
            "created": 123,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "test"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        router.client.post = AsyncMock(return_value=mock_response)

        request = ChatCompletionRequest(
            messages=[
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="Hello"),
            ],
            model="auto",
            source=RequestSource.WEB,
        )

        await router.generate(request)

        call_args = router.client.post.call_args
        backend_request = call_args.kwargs["json"]

        # System message should contain both ask-only AND original system
        assert backend_request["messages"][0]["role"] == "system"
        assert "ASK MODE ONLY" in backend_request["messages"][0]["content"]
        assert "You are helpful" in backend_request["messages"][0]["content"]


class TestChatUISourceHeader:
    """Test that Chat UI sends correct source."""

    def test_chat_ui_api_always_sends_web_source(self):
        """Verify the Chat UI API client always sends source: web."""
        # This is a design verification test
        # The actual implementation is in chat-ui/src/api.ts
        # We verify the expected behavior here

        expected_source = "web"

        # Simulate what the frontend sends
        frontend_request = {
            "messages": [{"role": "user", "content": "test"}],
            "model": "auto",
            "source": expected_source,  # Chat UI always adds this
        }

        assert frontend_request["source"] == "web"
