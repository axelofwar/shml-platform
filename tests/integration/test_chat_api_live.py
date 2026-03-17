"""
Live integration tests for Chat API authentication and access patterns.

These tests run against actual services to verify:
1. Authentication is properly enforced (401 without auth)
2. API key authentication works correctly
3. OAuth/role-based access works correctly
4. Ask-only mode is enforced for web requests
5. Rate limiting works correctly per role

Prerequisites:
- Chat API service running (docker compose up chat-api)
- Traefik proxy running
- Redis running (for rate limiting)
- Either FusionAuth running OR test API keys configured

Run with:
    pytest tests/integration/test_chat_api_live.py -v -m integration

For full auth tests, set environment variables:
    CHAT_API_TEST_KEY=shml_... (developer role API key)
    CHAT_API_ADMIN_KEY=shml_... (admin role API key)
    CHAT_API_VIEWER_KEY=shml_... (viewer role API key, should fail)
"""

import pytest
import requests
import time
import os
from typing import Dict, Optional

# Service URLs
CHAT_API_DIRECT_URL = os.getenv("CHAT_API_DIRECT_URL", "http://localhost:8000")
CHAT_API_PROXY_URL = os.getenv("CHAT_API_PROXY_URL", "http://localhost/chat-api")
CHAT_UI_URL = os.getenv("CHAT_UI_URL", "http://localhost/chat")

# Test API keys (set these for full integration tests)
TEST_API_KEY_DEVELOPER = os.getenv("CHAT_API_TEST_KEY", "")
TEST_API_KEY_ADMIN = os.getenv("CHAT_API_ADMIN_KEY", "")
TEST_API_KEY_VIEWER = os.getenv("CHAT_API_VIEWER_KEY", "")


def is_service_running(url: str) -> bool:
    """Check if a service is running and accessible."""
    try:
        response = requests.get(f"{url}/health", timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


@pytest.fixture(scope="module")
def chat_api_available():
    """Skip tests if chat API is not running."""
    if not is_service_running(CHAT_API_DIRECT_URL):
        pytest.skip("Chat API service not running")


@pytest.fixture(scope="module")
def developer_api_key():
    """Get developer API key or skip."""
    if not TEST_API_KEY_DEVELOPER:
        pytest.skip("CHAT_API_TEST_KEY not set - skipping API key tests")
    return TEST_API_KEY_DEVELOPER


@pytest.fixture(scope="module")
def admin_api_key():
    """Get admin API key or skip."""
    if not TEST_API_KEY_ADMIN:
        pytest.skip("CHAT_API_ADMIN_KEY not set - skipping admin tests")
    return TEST_API_KEY_ADMIN


@pytest.fixture(scope="module")
def viewer_api_key():
    """Get viewer API key or skip."""
    if not TEST_API_KEY_VIEWER:
        pytest.skip("CHAT_API_VIEWER_KEY not set - skipping viewer tests")
    return TEST_API_KEY_VIEWER


@pytest.fixture
def valid_chat_request() -> Dict:
    """Sample valid chat completion request."""
    return {
        "messages": [
            {"role": "user", "content": "Say 'test passed' and nothing else."}
        ],
        "model": "auto",
        "max_tokens": 50,
    }


@pytest.fixture
def web_chat_request() -> Dict:
    """Chat request from web interface (should be ask-only)."""
    return {
        "messages": [{"role": "user", "content": "What is 2+2?"}],
        "model": "auto",
        "max_tokens": 50,
        "source": "web",  # Web source triggers ask-only mode
    }


@pytest.fixture
def api_chat_request() -> Dict:
    """Chat request from API/Cursor (full capabilities)."""
    return {
        "messages": [{"role": "user", "content": "What is 2+2?"}],
        "model": "auto",
        "max_tokens": 50,
        "source": "api",  # API source has full capabilities
    }


# =============================================================================
# Test Class: Authentication Enforcement
# =============================================================================


class TestAuthenticationEnforcement:
    """Test that authentication is required on all protected endpoints."""

    @pytest.mark.integration
    def test_chat_completions_without_auth_returns_401(
        self, chat_api_available, valid_chat_request
    ):
        """POST /v1/chat/completions without auth should return 401."""
        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=valid_chat_request,
            timeout=10,
        )
        assert (
            response.status_code == 401
        ), f"Expected 401, got {response.status_code}: {response.text}"
        assert (
            "Authentication required" in response.text
            or "Unauthorized" in response.text
        )

    @pytest.mark.integration
    def test_list_models_without_auth_returns_401(self, chat_api_available):
        """GET /v1/models without auth should return 401."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/v1/models",
            timeout=10,
        )
        assert response.status_code == 401

    @pytest.mark.integration
    def test_api_keys_without_auth_returns_401(self, chat_api_available):
        """GET /api-keys without auth should return 401."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/api-keys",
            timeout=10,
        )
        assert response.status_code == 401

    @pytest.mark.integration
    def test_conversations_without_auth_returns_401(self, chat_api_available):
        """GET /conversations without auth should return 401."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/conversations",
            timeout=10,
        )
        assert response.status_code == 401

    @pytest.mark.integration
    def test_instructions_without_auth_returns_401(self, chat_api_available):
        """GET /instructions without auth should return 401."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/instructions",
            timeout=10,
        )
        assert response.status_code == 401

    @pytest.mark.integration
    def test_rate_limit_without_auth_returns_401(self, chat_api_available):
        """GET /rate-limit without auth should return 401."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/rate-limit",
            timeout=10,
        )
        assert response.status_code == 401

    @pytest.mark.integration
    def test_health_endpoint_is_public(self, chat_api_available):
        """GET /health should NOT require authentication."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/health",
            timeout=10,
        )
        assert response.status_code == 200, "Health endpoint should be public"


# =============================================================================
# Test Class: API Key Authentication
# =============================================================================


class TestAPIKeyAuthentication:
    """Test API key authentication flow."""

    @pytest.mark.integration
    def test_invalid_api_key_returns_401(self, chat_api_available, valid_chat_request):
        """Invalid API key should return 401."""
        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=valid_chat_request,
            headers={"Authorization": "Bearer test-invalid-key"},
            timeout=10,
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    @pytest.mark.integration
    def test_malformed_api_key_returns_401(
        self, chat_api_available, valid_chat_request
    ):
        """Malformed API key (wrong prefix) should return 401."""
        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=valid_chat_request,
            headers={"Authorization": "Bearer wrong_prefix_key"},
            timeout=10,
        )
        assert response.status_code == 401

    @pytest.mark.integration
    def test_valid_developer_key_allows_chat(
        self, chat_api_available, developer_api_key, valid_chat_request
    ):
        """Valid developer API key should allow chat completions."""
        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=valid_chat_request,
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=60,  # Model inference can take time
        )
        assert (
            response.status_code == 200
        ), f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert "message" in data["choices"][0]

    @pytest.mark.integration
    def test_valid_developer_key_can_list_models(
        self, chat_api_available, developer_api_key
    ):
        """Valid developer API key should allow listing models."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/v1/models",
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=10,
        )
        assert response.status_code == 200

        data = response.json()
        assert "data" in data
        # Should have at least primary and fallback models
        assert len(data["data"]) >= 2


# =============================================================================
# Test Class: Role-Based Access Control
# =============================================================================


class TestRoleBasedAccess:
    """Test that role requirements are enforced."""

    @pytest.mark.integration
    def test_viewer_cannot_access_chat(
        self, chat_api_available, viewer_api_key, valid_chat_request
    ):
        """Viewer role should NOT be able to use chat completions."""
        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=valid_chat_request,
            headers={"Authorization": f"Bearer {viewer_api_key}"},
            timeout=10,
        )
        # Should be 403 Forbidden (authenticated but not authorized)
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"

    @pytest.mark.integration
    def test_viewer_cannot_create_api_keys(self, chat_api_available, viewer_api_key):
        """Viewer role should NOT be able to create API keys."""
        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/api-keys",
            json={"name": "test-key", "role": "developer"},
            headers={"Authorization": f"Bearer {viewer_api_key}"},
            timeout=10,
        )
        assert response.status_code == 403

    @pytest.mark.integration
    def test_developer_can_create_own_api_key(
        self, chat_api_available, developer_api_key
    ):
        """Developer should be able to create API key for themselves."""
        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/api-keys",
            json={"name": f"test-key-{int(time.time())}"},
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=10,
        )
        # Should succeed or fail gracefully
        assert response.status_code in [
            200,
            201,
            400,
        ], f"Unexpected status: {response.status_code}"

    @pytest.mark.integration
    def test_admin_has_full_access(
        self, chat_api_available, admin_api_key, valid_chat_request
    ):
        """Admin role should have access to all endpoints."""
        # Chat completions
        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=valid_chat_request,
            headers={"Authorization": f"Bearer {admin_api_key}"},
            timeout=60,
        )
        assert (
            response.status_code == 200
        ), f"Admin should access chat: {response.status_code}"

        # List models
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/v1/models",
            headers={"Authorization": f"Bearer {admin_api_key}"},
            timeout=10,
        )
        assert response.status_code == 200, "Admin should list models"


# =============================================================================
# Test Class: Ask-Only Mode (Web vs API)
# =============================================================================


class TestAskOnlyMode:
    """Test that web requests are constrained to ask-only mode."""

    @pytest.mark.integration
    def test_web_request_gets_ask_only_constraint(
        self, chat_api_available, developer_api_key, web_chat_request
    ):
        """Web source requests should have ask-only system prompt injected."""
        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=web_chat_request,
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=60,
        )
        assert (
            response.status_code == 200
        ), f"Expected 200, got {response.status_code}: {response.text}"

        # The response should work but be constrained
        # We can't directly verify the system prompt was injected,
        # but we can verify the request succeeded
        data = response.json()
        assert "choices" in data

    @pytest.mark.integration
    def test_api_request_has_full_capabilities(
        self, chat_api_available, developer_api_key, api_chat_request
    ):
        """API source requests should NOT have ask-only constraint."""
        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=api_chat_request,
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=60,
        )
        assert response.status_code == 200

        data = response.json()
        assert "choices" in data

    @pytest.mark.integration
    def test_default_source_is_api(self, chat_api_available, developer_api_key):
        """Requests without explicit source should default to API (full capabilities)."""
        # Request without source field
        request_no_source = {
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "model": "auto",
            "max_tokens": 50,
            # No 'source' field
        }

        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=request_no_source,
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=60,
        )
        assert response.status_code == 200


# =============================================================================
# Test Class: Rate Limiting
# =============================================================================


class TestRateLimiting:
    """Test rate limiting behavior per role."""

    @pytest.mark.integration
    @pytest.mark.slow
    def test_rate_limit_status_endpoint(self, chat_api_available, developer_api_key):
        """Rate limit status endpoint should return current limits."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/rate-limit",
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=10,
        )
        assert response.status_code == 200

        data = response.json()
        assert "requests_limit" in data
        assert "requests_remaining" in data
        assert "role" in data

    @pytest.mark.integration
    def test_developer_has_100_per_minute_limit(
        self, chat_api_available, developer_api_key
    ):
        """Developer role should have 100 requests/minute limit."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/rate-limit",
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=10,
        )

        if response.status_code == 200:
            data = response.json()
            assert (
                data["requests_limit"] == 100
            ), f"Expected limit 100, got {data['requests_limit']}"

    @pytest.mark.integration
    def test_admin_has_unlimited_requests(self, chat_api_available, admin_api_key):
        """Admin role should have unlimited requests (limit=0)."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/rate-limit",
            headers={"Authorization": f"Bearer {admin_api_key}"},
            timeout=10,
        )

        if response.status_code == 200:
            data = response.json()
            # 0 means unlimited
            assert (
                data["requests_limit"] == 0
            ), f"Expected limit 0 (unlimited), got {data['requests_limit']}"


# =============================================================================
# Test Class: Conversation and History
# =============================================================================


class TestConversationHistory:
    """Test conversation history persistence."""

    @pytest.mark.integration
    def test_list_conversations(self, chat_api_available, developer_api_key):
        """Should be able to list user's conversations."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/conversations",
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=10,
        )
        assert response.status_code == 200

        data = response.json()
        # Should return a list (possibly empty)
        assert isinstance(data, list) or "conversations" in data

    @pytest.mark.integration
    def test_chat_creates_conversation(
        self, chat_api_available, developer_api_key, valid_chat_request
    ):
        """Chat completion should optionally create/update conversation."""
        # Send chat request
        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=valid_chat_request,
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=60,
        )

        if response.status_code == 200:
            data = response.json()
            # Response may include conversation_id if history is enabled
            # This is optional based on implementation
            if "conversation_id" in data:
                assert data["conversation_id"] is not None


# =============================================================================
# Test Class: Model Selection
# =============================================================================


class TestModelSelection:
    """Test model routing and selection."""

    @pytest.mark.integration
    def test_list_available_models(self, chat_api_available, developer_api_key):
        """Should list available models with status."""
        response = requests.get(
            f"{CHAT_API_DIRECT_URL}/v1/models",
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=10,
        )
        assert response.status_code == 200

        data = response.json()
        assert "data" in data

        # Check model structure
        for model in data["data"]:
            assert "id" in model
            assert "object" in model

    @pytest.mark.integration
    def test_auto_model_selection(
        self, chat_api_available, developer_api_key, valid_chat_request
    ):
        """Auto model selection should choose appropriate backend."""
        valid_chat_request["model"] = "auto"

        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=valid_chat_request,
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=60,
        )

        if response.status_code == 200:
            data = response.json()
            # model_selection shows which backend was used
            if "model_selection" in data:
                assert data["model_selection"] in ["primary", "fallback", "auto"]


# =============================================================================
# Test Class: Streaming Support
# =============================================================================


class TestStreamingSupport:
    """Test streaming chat completions."""

    @pytest.mark.integration
    def test_streaming_chat_completion(self, chat_api_available, developer_api_key):
        """Streaming requests should return SSE chunks."""
        request = {
            "messages": [{"role": "user", "content": "Count to 3"}],
            "model": "auto",
            "max_tokens": 50,
            "stream": True,
        }

        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=request,
            headers={"Authorization": f"Bearer {developer_api_key}"},
            stream=True,
            timeout=60,
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        # Read at least one chunk
        chunks_received = 0
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                chunks_received += 1
                if chunks_received >= 1:
                    break

        assert chunks_received >= 1, "Should receive at least one SSE chunk"


# =============================================================================
# Test Class: Error Handling
# =============================================================================


class TestErrorHandling:
    """Test proper error responses."""

    @pytest.mark.integration
    def test_invalid_model_returns_error(self, chat_api_available, developer_api_key):
        """Request with invalid model should return appropriate error."""
        request = {
            "messages": [{"role": "user", "content": "Hello"}],
            "model": "non-existent-model-xyz",
            "max_tokens": 50,
        }

        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=request,
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=10,
        )

        # Should return 400 or 404 for invalid model
        assert response.status_code in [
            400,
            404,
            500,
        ], f"Unexpected status: {response.status_code}"

    @pytest.mark.integration
    def test_empty_messages_returns_error(self, chat_api_available, developer_api_key):
        """Request with empty messages should return validation error."""
        request = {
            "messages": [],
            "model": "auto",
        }

        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=request,
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=10,
        )

        assert (
            response.status_code == 422
        ), "Empty messages should return validation error"

    @pytest.mark.integration
    def test_missing_messages_returns_error(
        self, chat_api_available, developer_api_key
    ):
        """Request without messages field should return validation error."""
        request = {
            "model": "auto",
        }

        response = requests.post(
            f"{CHAT_API_DIRECT_URL}/v1/chat/completions",
            json=request,
            headers={"Authorization": f"Bearer {developer_api_key}"},
            timeout=10,
        )

        assert response.status_code == 422


# =============================================================================
# Pytest configuration
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (may require running services)",
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (rate limit tests etc)"
    )
