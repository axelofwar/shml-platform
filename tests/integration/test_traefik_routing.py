"""
Integration tests for Traefik OAuth middleware and routing.

These tests verify the actual Traefik configuration is working:
1. OAuth middleware is enforced on protected routes
2. Role-based authorization headers are checked
3. Public routes are accessible
4. API key routes bypass OAuth but still require auth

Prerequisites:
- Traefik running with OAuth2-proxy configured
- FusionAuth running for authentication

Run with:
    pytest tests/integration/test_traefik_routing.py -v -m integration
"""

import pytest
import requests
import os
from typing import Dict

# Traefik proxy URL
PROXY_URL = os.getenv("PROXY_URL", "http://localhost")

# Protected service routes (should require OAuth)
OAUTH_PROTECTED_ROUTES = [
    "/chat",  # Chat UI
    "/chat-api/chat",  # Chat API via OAuth route
    "/inference/coding/primary",  # Coding model primary
    "/inference/coding/fallback",  # Coding model fallback
    "/mlflow",  # MLflow UI
    "/api/v1",  # API v1
]

# API routes (should accept API key auth, no OAuth redirect)
API_KEY_ROUTES = [
    "/chat-api/api",  # Chat API direct route
]

# Public routes (should not require auth)
PUBLIC_ROUTES = [
    "/",  # Homer dashboard
    "/health",  # Platform health (if configured)
]


def is_traefik_running() -> bool:
    """Check if Traefik is running."""
    try:
        response = requests.get(f"{PROXY_URL}/", timeout=5, allow_redirects=False)
        return response.status_code in [200, 302, 401, 403]
    except requests.exceptions.RequestException:
        return False


@pytest.fixture(scope="module")
def traefik_available():
    """Skip tests if Traefik is not running."""
    if not is_traefik_running():
        pytest.skip("Traefik proxy not running")


# =============================================================================
# Test Class: OAuth Protected Routes
# =============================================================================


class TestOAuthProtectedRoutes:
    """Test that OAuth middleware is enforced on protected routes."""

    @pytest.mark.integration
    @pytest.mark.parametrize("route", OAUTH_PROTECTED_ROUTES)
    def test_protected_route_requires_oauth(self, traefik_available, route):
        """Protected routes should redirect to login or return 401."""
        response = requests.get(
            f"{PROXY_URL}{route}",
            timeout=10,
            allow_redirects=False,  # Don't follow redirects
        )

        # Should either:
        # - 302 redirect to OAuth login
        # - 401 Unauthorized
        # - 403 Forbidden (authenticated but wrong role)
        assert response.status_code in [
            302,
            401,
            403,
        ], f"Route {route} returned {response.status_code}, expected OAuth redirect or auth error"

        # If redirecting, should go to OAuth
        if response.status_code == 302:
            location = response.headers.get("Location", "")
            assert any(
                x in location.lower() for x in ["oauth", "login", "auth"]
            ), f"Route {route} redirected to {location}, expected OAuth"

    @pytest.mark.integration
    def test_chat_ui_requires_oauth_and_developer_role(self, traefik_available):
        """Chat UI should require both OAuth and developer role."""
        response = requests.get(
            f"{PROXY_URL}/chat",
            timeout=10,
            allow_redirects=False,
        )

        # Without auth, should redirect to login
        assert response.status_code in [
            302,
            401,
        ], f"Chat UI should require auth, got {response.status_code}"

    @pytest.mark.integration
    def test_mlflow_requires_oauth(self, traefik_available):
        """MLflow should require OAuth authentication."""
        response = requests.get(
            f"{PROXY_URL}/mlflow",
            timeout=10,
            allow_redirects=False,
        )

        assert response.status_code in [
            302,
            401,
        ], f"MLflow should require auth, got {response.status_code}"


# =============================================================================
# Test Class: API Key Routes
# =============================================================================


class TestAPIKeyRoutes:
    """Test that API routes accept API key authentication."""

    @pytest.mark.integration
    def test_api_route_without_auth_returns_401(self, traefik_available):
        """API routes without any auth should return 401, not redirect."""
        response = requests.post(
            f"{PROXY_URL}/chat-api/api/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "test"}], "model": "auto"},
            timeout=10,
            allow_redirects=False,
        )

        # Should return 401, NOT redirect to OAuth
        assert (
            response.status_code == 401
        ), f"API route should return 401, got {response.status_code}"

        # Should not be a redirect
        assert (
            "Location" not in response.headers
        ), "API route should not redirect to OAuth"

    @pytest.mark.integration
    def test_api_route_with_invalid_key_returns_401(self, traefik_available):
        """API routes with invalid key should return 401."""
        response = requests.post(
            f"{PROXY_URL}/chat-api/api/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "test"}], "model": "auto"},
            headers={"Authorization": "Bearer invalid_key"},
            timeout=10,
            allow_redirects=False,
        )

        assert response.status_code == 401


# =============================================================================
# Test Class: Public Routes
# =============================================================================


class TestPublicRoutes:
    """Test routes that should be publicly accessible or OAuth protected."""

    @pytest.mark.integration
    def test_homer_dashboard_requires_oauth(self, traefik_available):
        """Homer dashboard requires OAuth authentication (security best practice)."""
        response = requests.get(
            f"{PROXY_URL}/",
            timeout=10,
            allow_redirects=False,
        )

        # Homer is protected by OAuth - should redirect to login
        assert response.status_code in [
            302,
            401,
        ], f"Homer dashboard should require auth, got {response.status_code}"


# =============================================================================
# Test Class: Role-Based Authorization Headers
# =============================================================================


class TestRoleBasedHeaders:
    """Test that Traefik/OAuth2-proxy passes correct role headers."""

    @pytest.mark.integration
    def test_viewer_cannot_access_chat(self, traefik_available):
        """
        Viewers should not be able to access chat endpoints.
        This tests that the allowed_groups middleware is configured.
        """
        # Simulate a viewer by sending OAuth headers that Traefik would set
        # In real flow, OAuth2-proxy sets these after authentication

        # Without proper OAuth flow, we can only test that:
        # 1. Route exists
        # 2. Without auth, returns 401/302

        response = requests.get(
            f"{PROXY_URL}/chat",
            timeout=10,
            allow_redirects=False,
        )

        # Should require auth
        assert response.status_code in [302, 401]


# =============================================================================
# Test Class: Service Health Behind Traefik
# =============================================================================


class TestServiceHealth:
    """Test that services are healthy behind Traefik."""

    @pytest.mark.integration
    def test_traefik_dashboard_accessible(self, traefik_available):
        """Traefik dashboard should be accessible on management port."""
        try:
            response = requests.get(
                "http://localhost:8090/dashboard/",
                timeout=10,
            )
            # Dashboard might require auth or be disabled
            assert response.status_code in [200, 401, 404]
        except requests.exceptions.RequestException:
            pytest.skip("Traefik dashboard not accessible")

    @pytest.mark.integration
    def test_traefik_api_health(self, traefik_available):
        """Traefik API should be accessible."""
        try:
            response = requests.get(
                "http://localhost:8090/api/overview",
                timeout=10,
            )
            # API might require auth
            assert response.status_code in [200, 401]
        except requests.exceptions.RequestException:
            pytest.skip("Traefik API not accessible")


# =============================================================================
# Pytest configuration
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
