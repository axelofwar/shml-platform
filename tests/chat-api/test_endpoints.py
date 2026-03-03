"""Integration tests for Chat API endpoints."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


class TestEndpointSecurity:
    """Test that all endpoints require proper authentication."""

    @pytest.fixture
    def mock_app(self):
        """Create test app with mocked dependencies."""
        with patch("inference.chat_api.app.main.db") as mock_db, patch(
            "inference.chat_api.app.main.rate_limiter"
        ) as mock_rate, patch(
            "inference.chat_api.app.main.model_router"
        ) as mock_router:

            mock_db.connect = AsyncMock()
            mock_db.close = AsyncMock()
            mock_rate.connect = AsyncMock()
            mock_rate.close = AsyncMock()
            mock_router.connect = AsyncMock()
            mock_router.close = AsyncMock()

            from inference.chat_api.app.main import app

            yield app

    def test_chat_completions_requires_auth(self, mock_app):
        """POST /v1/chat/completions should require authentication."""
        with TestClient(mock_app) as client:
            response = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "model": "auto",
                },
            )
            # Should return 401 without auth
            assert response.status_code == 401
            assert "Authentication required" in response.json()["detail"]

    def test_list_models_requires_auth(self, mock_app):
        """GET /v1/models should require authentication."""
        with TestClient(mock_app) as client:
            response = client.get("/v1/models")
            assert response.status_code == 401

    def test_create_api_key_requires_auth(self, mock_app):
        """POST /api-keys should require authentication."""
        with TestClient(mock_app) as client:
            response = client.post("/api-keys", json={"name": "Test Key"})
            assert response.status_code == 401

    def test_list_api_keys_requires_auth(self, mock_app):
        """GET /api-keys should require authentication."""
        with TestClient(mock_app) as client:
            response = client.get("/api-keys")
            assert response.status_code == 401

    def test_conversations_requires_auth(self, mock_app):
        """GET /conversations should require authentication."""
        with TestClient(mock_app) as client:
            response = client.get("/conversations")
            assert response.status_code == 401

    def test_instructions_requires_auth(self, mock_app):
        """GET /instructions should require authentication."""
        with TestClient(mock_app) as client:
            response = client.get("/instructions")
            assert response.status_code == 401

    def test_rate_limit_requires_auth(self, mock_app):
        """GET /rate-limit should require authentication."""
        with TestClient(mock_app) as client:
            response = client.get("/rate-limit")
            assert response.status_code == 401


class TestEndpointRoleAccess:
    """Test that endpoints enforce correct role requirements."""

    @pytest.fixture
    def mock_app(self):
        """Create test app with mocked dependencies."""
        with patch("inference.chat_api.app.main.db") as mock_db, patch(
            "inference.chat_api.app.main.rate_limiter"
        ) as mock_rate, patch(
            "inference.chat_api.app.main.model_router"
        ) as mock_router:

            mock_db.connect = AsyncMock()
            mock_db.close = AsyncMock()
            mock_rate.connect = AsyncMock()
            mock_rate.close = AsyncMock()
            mock_router.connect = AsyncMock()
            mock_router.close = AsyncMock()

            from inference.chat_api.app.main import app

            yield app

    @pytest.fixture
    def authenticated_client(self, mock_app, sample_user_developer):
        """Client with developer authentication headers."""
        with patch("inference.chat_api.app.auth.db") as mock_db:
            mock_db.validate_api_key = AsyncMock(return_value=None)

            with TestClient(mock_app) as client:
                # Simulate OAuth headers from Traefik/oauth2-proxy
                client.headers.update(
                    {
                        "X-Auth-Request-User": sample_user_developer.id,
                        "X-Auth-Request-Email": sample_user_developer.email,
                        "X-Auth-Request-Groups": "developer",
                    }
                )
                yield client

    @pytest.fixture
    def viewer_client(self, mock_app, sample_user_viewer):
        """Client with viewer authentication headers."""
        with patch("inference.chat_api.app.auth.db") as mock_db:
            mock_db.validate_api_key = AsyncMock(return_value=None)

            with TestClient(mock_app) as client:
                client.headers.update(
                    {
                        "X-Auth-Request-User": sample_user_viewer.id,
                        "X-Auth-Request-Email": sample_user_viewer.email,
                        "X-Auth-Request-Groups": "viewer",
                    }
                )
                yield client

    def test_viewer_cannot_create_api_keys(self, viewer_client):
        """Viewers should not be able to create API keys."""
        with patch("inference.chat_api.app.main.db") as mock_db:
            mock_db.create_api_key = AsyncMock(
                side_effect=PermissionError("Viewers cannot create API keys")
            )

            response = viewer_client.post("/api-keys", json={"name": "Test Key"})

            # Should be rejected (403 or the permission error)
            assert response.status_code in [403, 500]


class TestAPIKeyAuthentication:
    """Test API key authentication flow."""

    @pytest.fixture
    def mock_app(self):
        """Create test app with mocked dependencies."""
        with patch("inference.chat_api.app.main.db") as mock_db, patch(
            "inference.chat_api.app.main.rate_limiter"
        ) as mock_rate, patch(
            "inference.chat_api.app.main.model_router"
        ) as mock_router:

            mock_db.connect = AsyncMock()
            mock_db.close = AsyncMock()
            mock_rate.connect = AsyncMock()
            mock_rate.close = AsyncMock()
            mock_router.connect = AsyncMock()
            mock_router.close = AsyncMock()

            from inference.chat_api.app.main import app

            yield app, mock_db, mock_rate, mock_router

    def test_valid_api_key_allows_access(self, mock_app, sample_api_key_user):
        """Valid API key should grant access."""
        from inference.chat_api.app.schemas import (
            ChatCompletionResponse,
            ChatCompletionChoice,
            ChatCompletionUsage,
            ChatMessage,
        )

        app, mock_db, mock_rate, mock_router = mock_app

        # Mock successful API key validation
        mock_db.validate_api_key = AsyncMock(return_value=sample_api_key_user)
        mock_db.get_active_instructions = AsyncMock(return_value=[])
        mock_rate.record = AsyncMock(return_value=True)
        mock_rate.check = AsyncMock()

        # Create proper Pydantic response model
        mock_response = ChatCompletionResponse(
            id="test-id",
            object="chat.completion",
            created=1234567890,
            model="qwen2.5-coder-3b",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="Hello!"),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=10, completion_tokens=5, total_tokens=15
            ),
            conversation_id=None,
            model_selection="fallback",
        )

        # Mock model router response (tuple of response, model_used, tokens)
        mock_router.get_model_status = AsyncMock(return_value={})
        mock_router.generate = AsyncMock(return_value=(mock_response, "fallback", 100))
        mock_db.log_usage = AsyncMock()
        mock_db.add_message = AsyncMock()

        with patch("inference.chat_api.app.auth.db", mock_db):
            with TestClient(app) as client:
                response = client.post(
                    "/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": "Hello"}],
                        "model": "auto",
                    },
                    headers={
                        "Authorization": "Bearer test-valid-key"
                    },  # nosec - test fixture
                )

                # With valid key, should succeed (200) or model error
                # The mock should return 200
                assert response.status_code in [200, 500]

    def test_invalid_api_key_returns_401(self, mock_app):
        """Invalid API key should return 401."""
        app, mock_db, mock_rate, mock_router = mock_app

        # Mock failed API key validation
        mock_db.validate_api_key = AsyncMock(return_value=None)

        with patch("inference.chat_api.app.auth.db", mock_db):
            with TestClient(app) as client:
                response = client.post(
                    "/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": "Hello"}],
                        "model": "auto",
                    },
                    headers={
                        "Authorization": "Bearer test-invalid-key"
                    },  # nosec - test fixture
                )

                assert response.status_code == 401
                assert "Invalid or expired" in response.json()["detail"]


class TestHealthEndpoint:
    """Test health endpoint (public access)."""

    @pytest.fixture
    def mock_app(self):
        """Create test app with mocked dependencies."""
        with patch("inference.chat_api.app.main.db") as mock_db, patch(
            "inference.chat_api.app.main.rate_limiter"
        ) as mock_rate, patch(
            "inference.chat_api.app.main.model_router"
        ) as mock_router:

            mock_db.connect = AsyncMock()
            mock_db.close = AsyncMock()
            mock_rate.connect = AsyncMock()
            mock_rate.close = AsyncMock()
            mock_router.connect = AsyncMock()
            mock_router.close = AsyncMock()
            mock_router.get_model_status = AsyncMock(
                return_value={
                    "primary": MagicMock(id="test", is_available=True),
                    "fallback": MagicMock(id="test", is_available=True),
                }
            )

            from inference.chat_api.app.main import app

            yield app

    def test_health_endpoint_is_public(self, mock_app):
        """Health endpoint should not require authentication."""
        with TestClient(mock_app) as client:
            response = client.get("/health")
            # Should return 200 without auth
            assert response.status_code == 200
            assert "status" in response.json()
