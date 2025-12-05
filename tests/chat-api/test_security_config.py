"""Configuration verification tests for Chat API security.

These tests verify the docker-compose and config files are correctly set up
for authentication, without needing the actual application modules.
"""

import pytest
import yaml
import os


def load_compose(filename):
    """Load a docker-compose file."""
    compose_path = os.path.join(os.path.dirname(__file__), f"../../{filename}")
    with open(compose_path) as f:
        return yaml.safe_load(f)


def get_labels(compose, service_name):
    """Get labels from a service in compose file."""
    return compose.get("services", {}).get(service_name, {}).get("labels", [])


class TestChatUISecurityConfig:
    """Test Chat UI has correct security configuration."""

    def test_chat_ui_requires_oauth(self):
        """Chat UI must require OAuth authentication."""
        compose = load_compose("chat-ui/docker-compose.yml")
        labels = get_labels(compose, "chat-ui")

        middlewares = [l for l in labels if "middlewares=" in l]
        assert len(middlewares) > 0, "No middleware configured"

        middleware_str = middlewares[0]
        assert "oauth2-auth" in middleware_str, "OAuth not required for Chat UI"

    def test_chat_ui_requires_developer_role(self):
        """Chat UI must require developer role."""
        compose = load_compose("chat-ui/docker-compose.yml")
        labels = get_labels(compose, "chat-ui")

        middlewares = [l for l in labels if "middlewares=" in l]
        middleware_str = middlewares[0]

        assert (
            "role-auth-developer" in middleware_str
        ), "Developer role not required for Chat UI"


class TestChatAPISecurityConfig:
    """Test Chat API has correct security configuration."""

    def test_chat_api_browser_route_requires_oauth(self):
        """Chat API browser route (/chat) must require OAuth."""
        compose = load_compose("inference/chat-api/docker-compose.yml")
        labels = get_labels(compose, "chat-api")

        # Find main router (not direct)
        main_middlewares = [
            l
            for l in labels
            if "chat-api.middlewares=" in l and "chat-api-direct" not in l
        ]
        assert len(main_middlewares) > 0, "Main router middleware not found"

        middleware_str = main_middlewares[0]
        assert "oauth2-auth" in middleware_str, "OAuth not required for browser route"

    def test_chat_api_browser_route_requires_developer_role(self):
        """Chat API browser route must require developer role."""
        compose = load_compose("inference/chat-api/docker-compose.yml")
        labels = get_labels(compose, "chat-api")

        main_middlewares = [
            l
            for l in labels
            if "chat-api.middlewares=" in l and "chat-api-direct" not in l
        ]
        middleware_str = main_middlewares[0]

        assert (
            "role-auth-developer" in middleware_str
        ), "Developer role not required for browser route"

    def test_chat_api_direct_route_exists(self):
        """Direct API route (/api/chat) should exist for API key auth."""
        compose = load_compose("inference/chat-api/docker-compose.yml")
        labels = get_labels(compose, "chat-api")

        direct_rules = [l for l in labels if "chat-api-direct.rule=" in l]
        assert len(direct_rules) > 0, "Direct API route not configured"

        # Verify it matches /api/chat
        assert any(
            "/api/chat" in l for l in direct_rules
        ), "Direct route should match /api/chat"

    def test_chat_api_direct_route_no_traefik_oauth(self):
        """Direct API route should NOT have Traefik OAuth (handled by service)."""
        compose = load_compose("inference/chat-api/docker-compose.yml")
        labels = get_labels(compose, "chat-api")

        direct_middlewares = [l for l in labels if "chat-api-direct.middlewares=" in l]
        if direct_middlewares:
            middleware_str = direct_middlewares[0]
            # Should not have oauth2-auth - service handles API key auth
            assert (
                "oauth2-auth" not in middleware_str
            ), "Direct route should not have OAuth (API key auth handled by service)"


class TestCodingModelSecurityConfig:
    """Test Coding Model has correct security configuration."""

    def test_coding_model_primary_requires_oauth(self):
        """Primary coding model must require OAuth."""
        compose = load_compose("inference/coding-model/docker-compose.yml")
        labels = get_labels(compose, "coding-model-primary")

        middlewares = [l for l in labels if "middlewares=" in l]
        assert len(middlewares) > 0, "No middleware configured"

        middleware_str = middlewares[0]
        assert "oauth2-auth" in middleware_str, "OAuth not required for primary model"

    def test_coding_model_primary_requires_developer_role(self):
        """Primary coding model must require developer role."""
        compose = load_compose("inference/coding-model/docker-compose.yml")
        labels = get_labels(compose, "coding-model-primary")

        middlewares = [l for l in labels if "middlewares=" in l]
        middleware_str = middlewares[0]

        assert (
            "role-auth-developer" in middleware_str
        ), "Developer role not required for primary model"

    def test_coding_model_fallback_requires_oauth(self):
        """Fallback coding model must require OAuth."""
        compose = load_compose("inference/coding-model/docker-compose.yml")
        labels = get_labels(compose, "coding-model-fallback")

        middlewares = [l for l in labels if "middlewares=" in l]
        assert len(middlewares) > 0, "No middleware configured"

        middleware_str = middlewares[0]
        assert "oauth2-auth" in middleware_str, "OAuth not required for fallback model"

    def test_coding_model_fallback_requires_developer_role(self):
        """Fallback coding model must require developer role."""
        compose = load_compose("inference/coding-model/docker-compose.yml")
        labels = get_labels(compose, "coding-model-fallback")

        middlewares = [l for l in labels if "middlewares=" in l]
        middleware_str = middlewares[0]

        assert (
            "role-auth-developer" in middleware_str
        ), "Developer role not required for fallback model"


class TestConfigValues:
    """Test configuration values are correct."""

    def test_rate_limits_configured(self):
        """Verify rate limit environment variables are set."""
        compose = load_compose("inference/chat-api/docker-compose.yml")
        env = compose["services"]["chat-api"]["environment"]

        # Find rate limit configs
        rate_limits = {
            "developer": None,
            "viewer": None,
            "admin": None,
        }

        for item in env:
            if "RATE_LIMIT_DEVELOPER=" in item:
                rate_limits["developer"] = int(item.split("=")[1])
            elif "RATE_LIMIT_VIEWER=" in item:
                rate_limits["viewer"] = int(item.split("=")[1])
            elif "RATE_LIMIT_ADMIN=" in item:
                rate_limits["admin"] = int(item.split("=")[1])

        assert rate_limits["developer"] == 100, "Developer rate limit should be 100"
        assert rate_limits["viewer"] == 20, "Viewer rate limit should be 20"
        assert rate_limits["admin"] == 0, "Admin rate limit should be 0 (unlimited)"


class TestAccessMatrix:
    """Verify complete access control matrix."""

    def test_all_chat_interfaces_require_auth(self):
        """All chat interfaces must require authentication."""
        interfaces = [
            ("chat-ui/docker-compose.yml", "chat-ui"),
            ("inference/chat-api/docker-compose.yml", "chat-api"),
            ("inference/coding-model/docker-compose.yml", "coding-model-primary"),
            ("inference/coding-model/docker-compose.yml", "coding-model-fallback"),
        ]

        for compose_file, service in interfaces:
            compose = load_compose(compose_file)
            labels = get_labels(compose, service)

            # Must have either oauth2-auth in Traefik OR be API-key protected
            has_oauth = any("oauth2-auth" in l for l in labels)
            is_direct_api = "chat-api-direct" in str(labels)

            assert (
                has_oauth or is_direct_api
            ), f"{service} in {compose_file} must require authentication"

    def test_non_admin_services_require_developer_role(self):
        """Chat services should require at least developer role."""
        services_requiring_developer = [
            ("chat-ui/docker-compose.yml", "chat-ui"),
            ("inference/chat-api/docker-compose.yml", "chat-api"),
            ("inference/coding-model/docker-compose.yml", "coding-model-primary"),
            ("inference/coding-model/docker-compose.yml", "coding-model-fallback"),
        ]

        for compose_file, service in services_requiring_developer:
            compose = load_compose(compose_file)
            labels = get_labels(compose, service)

            # Find middleware for main router (not direct API)
            main_middlewares = [
                l for l in labels if ".middlewares=" in l and "-direct" not in l
            ]

            if main_middlewares:
                middleware_str = main_middlewares[0]
                assert (
                    "role-auth-developer" in middleware_str
                ), f"{service} should require developer role"


class TestDockerComposeIntegrity:
    """Test docker-compose files are valid."""

    def test_chat_ui_compose_valid(self):
        """Chat UI compose file should be valid YAML."""
        compose = load_compose("chat-ui/docker-compose.yml")
        assert "services" in compose
        assert "chat-ui" in compose["services"]

    def test_chat_api_compose_valid(self):
        """Chat API compose file should be valid YAML."""
        compose = load_compose("inference/chat-api/docker-compose.yml")
        assert "services" in compose
        assert "chat-api" in compose["services"]

    def test_coding_model_compose_valid(self):
        """Coding model compose file should be valid YAML."""
        compose = load_compose("inference/coding-model/docker-compose.yml")
        assert "services" in compose
        assert "coding-model-primary" in compose["services"]
        assert "coding-model-fallback" in compose["services"]

    def test_main_compose_includes_chat_services(self):
        """Main compose should include chat services."""
        compose_path = os.path.join(
            os.path.dirname(__file__), "../../docker-compose.yml"
        )
        with open(compose_path) as f:
            content = f.read()

        assert "chat-api" in content.lower() or "inference/chat-api" in content
        assert "chat-ui" in content.lower()
