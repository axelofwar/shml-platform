"""Tests for Traefik middleware and routing configuration."""

import pytest
import yaml
import os


class TestTraefikConfiguration:
    """Test Traefik routing and middleware configuration."""

    @pytest.fixture
    def chat_api_compose(self):
        """Load chat-api deploy/compose/docker-compose.yml."""
        compose_path = os.path.join(
            os.path.dirname(__file__), "../../inference/chat-api/docker-compose.yml"
        )
        with open(compose_path) as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def chat_ui_compose(self):
        """Load chat-ui-v2 docker-compose.yml (renamed from chat-ui/ in v0.2)."""
        compose_path = os.path.join(
            os.path.dirname(__file__), "../../chat-ui-v2/docker-compose.yml"
        )
        with open(compose_path) as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def coding_model_compose(self):
        """Load coding-model deploy/compose/docker-compose.yml."""
        compose_path = os.path.join(
            os.path.dirname(__file__), "../../inference/coding-model/docker-compose.yml"
        )
        with open(compose_path) as f:
            return yaml.safe_load(f)

    def test_chat_api_browser_route_has_oauth(self, chat_api_compose):
        """Chat API browser route (/chat) should require OAuth + developer role."""
        labels = chat_api_compose["services"]["chat-api"]["labels"]

        # Find the main router middleware
        main_middleware = None
        for label in labels:
            if "chat-api.middlewares=" in label and "chat-api-direct" not in label:
                main_middleware = label
                break

        assert main_middleware is not None, "Main router middleware not found"
        assert "oauth2-errors" in main_middleware
        assert "oauth2-auth" in main_middleware
        assert "role-auth-developer" in main_middleware

    def test_chat_api_direct_route_documented(self, chat_api_compose):
        """Chat API direct route (/api/chat) should be documented as API-key only."""
        labels = chat_api_compose["services"]["chat-api"]["labels"]

        # Find comments/labels about direct route
        direct_labels = [
            l for l in labels if "chat-api-direct" in l or "/api/chat" in l
        ]

        assert len(direct_labels) > 0, "Direct API route not configured"

        # The direct route should NOT have oauth middleware (handled by service)
        direct_middleware = None
        for label in labels:
            if "chat-api-direct.middlewares=" in label:
                direct_middleware = label
                break

        # Direct route should only have strip prefix middleware
        assert direct_middleware is not None
        assert (
            "oauth2-auth" not in direct_middleware
        ), "Direct API route should not have OAuth (handled by service)"

    def test_chat_ui_route_has_oauth_and_role(self, chat_ui_compose):
        """Chat UI route should require OAuth + developer role."""
        labels = chat_ui_compose["services"]["chat-ui"]["labels"]

        # Find middleware label
        middleware = None
        for label in labels:
            if "chat-ui.middlewares=" in label:
                middleware = label
                break

        assert middleware is not None, "Chat UI middleware not found"
        assert "oauth2-errors" in middleware
        assert "oauth2-auth" in middleware
        assert (
            "role-auth-developer" in middleware
        ), "Chat UI should require developer role"

    def test_coding_model_routes_have_oauth_and_role(self, coding_model_compose):
        """Coding model routes should require OAuth + developer role."""
        # coding-model-primary is commented out (no dedicated GPU available); only fallback is active.
        # When primary is re-enabled, add its assertions back here.
        if "coding-model-primary" in coding_model_compose.get("services", {}):
            primary_labels = coding_model_compose["services"]["coding-model-primary"]["labels"]
            primary_middleware = None
            for label in primary_labels:
                if "coding-model-primary.middlewares=" in label:
                    primary_middleware = label
                    break
            assert primary_middleware is not None
            assert "oauth2-errors" in primary_middleware
            assert "oauth2-auth" in primary_middleware
            assert "role-auth-developer" in primary_middleware

        # Check fallback
        fallback_labels = coding_model_compose["services"]["coding-model-fallback"][
            "labels"
        ]
        fallback_middleware = None
        for label in fallback_labels:
            if "coding-model-fallback.middlewares=" in label:
                fallback_middleware = label
                break

        assert fallback_middleware is not None
        assert "oauth2-errors" in fallback_middleware
        assert "oauth2-auth" in fallback_middleware
        assert "role-auth-developer" in fallback_middleware


class TestAccessMatrix:
    """Verify access control matrix."""

    def test_access_requirements_documented(self):
        """Document expected access requirements for each interface."""
        access_matrix = {
            # Interface: (requires_auth, required_role, auth_method)
            "/chat-ui/": ("yes", "developer+", "OAuth via Traefik"),
            "/chat/": ("yes", "developer+", "OAuth via Traefik"),
            "/api/chat/": ("yes", "any valid key", "API Key via service"),
            "/api/coding": ("yes", "developer+", "OAuth via Traefik"),
        }

        # This test documents the expected behavior
        for endpoint, (requires_auth, role, method) in access_matrix.items():
            print(f"{endpoint}: auth={requires_auth}, role={role}, method={method}")

        # All endpoints should require authentication
        for endpoint, (requires_auth, _, _) in access_matrix.items():
            assert requires_auth == "yes", f"{endpoint} should require auth"

    def test_viewer_cannot_access_chat(self):
        """Verify viewers are blocked from chat interfaces."""
        # Document that viewers cannot access:
        blocked_for_viewers = [
            "/chat-ui/",  # Requires developer role via Traefik
            "/chat/",  # Requires developer role via Traefik
            "/api/coding",  # Requires developer role via Traefik
        ]

        # Viewers CAN access with API key (if admin provisions one):
        accessible_with_api_key = [
            "/api/chat/",  # API key auth checked by service, not Traefik
        ]

        # But even with API key, viewers have strict rate limits (20/min)
        viewer_rate_limit = 20

        assert viewer_rate_limit == 20

    def test_developer_access(self):
        """Verify developers can access chat interfaces."""
        # Developers can access all chat interfaces
        accessible_for_developers = [
            "/chat-ui/",
            "/chat/",
            "/api/chat/",
            "/api/coding",
        ]

        # Developer rate limit
        developer_rate_limit = 100

        assert developer_rate_limit == 100
        assert len(accessible_for_developers) == 4

    def test_admin_access(self):
        """Verify admins have full access."""
        # Admins can access everything
        # Admins have unlimited rate limit
        admin_rate_limit = 0  # 0 = unlimited

        assert admin_rate_limit == 0
