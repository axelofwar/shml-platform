"""
Unit tests for Platform Admin SDK components.

These tests use mocking to test SDK components in isolation
without requiring a live FusionAuth instance.
"""

import pytest
import sys
import os
import json
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from typing import Any, Dict, Optional
from io import BytesIO
from urllib.error import HTTPError, URLError

# Add the SDK to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from platform_admin import Config, PlatformAdminClient
from platform_admin.client import APIResponse


# =============================================================================
# Config Unit Tests
# =============================================================================


@pytest.mark.unit
class TestConfig:
    """Unit tests for Config class."""

    def test_config_from_env(self, monkeypatch):
        """Test Config loading from environment variables."""
        monkeypatch.setenv("FUSIONAUTH_URL", "http://test-server:9011")
        monkeypatch.setenv("FUSIONAUTH_API_KEY", "test-api-key")

        config = Config()

        assert config.fusionauth_url == "http://test-server:9011"
        assert config.api_key == "test-api-key"

    def test_config_defaults(self):
        """Test Config default values."""
        # Use explicit values to avoid env interference
        config = Config(fusionauth_url="http://localhost:9011", api_key="test")

        assert "localhost" in config.fusionauth_url or "9011" in config.fusionauth_url

    def test_config_custom_values(self):
        """Test Config with custom values."""
        config = Config(fusionauth_url="http://custom:9999", api_key="custom-key")

        assert config.fusionauth_url == "http://custom:9999"
        assert config.api_key == "custom-key"


# =============================================================================
# APIResponse Unit Tests
# =============================================================================


@pytest.mark.unit
class TestAPIResponse:
    """Unit tests for APIResponse dataclass."""

    def test_success_response(self):
        """Test successful API response."""
        response = APIResponse(
            success=True,
            status_code=200,
            data={"user": {"id": "123", "email": "test@test.com"}},
            error=None,
        )

        assert response.success is True
        assert response.status_code == 200
        assert response.data["user"]["id"] == "123"
        assert response.error is None

    def test_error_response(self):
        """Test error API response."""
        response = APIResponse(
            success=False, status_code=404, data={}, error="User not found"
        )

        assert response.success is False
        assert response.status_code == 404
        assert response.error == "User not found"

    def test_empty_data(self):
        """Test response with empty data."""
        response = APIResponse(success=True, status_code=200, data={}, error=None)

        assert response.success is True
        assert response.data == {}

    def test_to_json(self):
        """Test JSON serialization."""
        response = APIResponse(
            success=True, status_code=200, data={"test": "value"}, error=None
        )

        json_str = response.to_json()
        parsed = json.loads(json_str)

        assert parsed["success"] is True
        assert parsed["status_code"] == 200
        assert parsed["data"]["test"] == "value"


# =============================================================================
# PlatformAdminClient Unit Tests
# =============================================================================


@pytest.mark.unit
class TestPlatformAdminClient:
    """Unit tests for PlatformAdminClient."""

    def test_client_initialization(self):
        """Test client can be initialized."""
        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        assert client is not None
        assert client._config == config

    def test_client_has_services(self):
        """Test client has expected service properties."""
        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        # Access services - they should be created lazily
        assert hasattr(client, "users")
        assert hasattr(client, "groups")
        assert hasattr(client, "applications")
        assert hasattr(client, "roles")
        assert hasattr(client, "registrations")

    def test_service_types(self):
        """Test that services are of correct types."""
        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        assert type(client.users).__name__ == "UsersService"
        assert type(client.groups).__name__ == "GroupsService"
        assert type(client.applications).__name__ == "ApplicationsService"
        assert type(client.roles).__name__ == "RolesService"
        assert type(client.registrations).__name__ == "RegistrationsService"

    def test_client_requires_api_key(self):
        """Test that client requires API key."""
        config = Config(fusionauth_url="http://test:9011", api_key=None)

        # Note: The SDK may not raise if api_key becomes empty string from env
        # This is more of a documentation test
        if not config.api_key:
            with pytest.raises(ValueError) as excinfo:
                PlatformAdminClient(config)

            assert "API key" in str(excinfo.value)
        else:
            # If env vars provide a key, just verify client can be created
            client = PlatformAdminClient(config)
            assert client is not None


# =============================================================================
# HTTP Mocking Helper
# =============================================================================


def mock_urlopen_response(data: dict, status_code: int = 200):
    """Create a mock response for urlopen."""
    mock_response = Mock()
    mock_response.getcode.return_value = status_code
    mock_response.read.return_value = json.dumps(data).encode("utf-8")
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    return mock_response


def mock_http_error(code: int, reason: str, data: dict = None):
    """Create a mock HTTPError."""
    error = HTTPError(
        url="http://test",
        code=code,
        msg=reason,
        hdrs={},
        fp=BytesIO(json.dumps(data or {}).encode("utf-8")),
    )
    return error


# =============================================================================
# UsersService Unit Tests
# =============================================================================


@pytest.mark.unit
class TestUsersServiceUnit:
    """Unit tests for UsersService with mocked HTTP."""

    @patch("platform_admin.client.urlopen")
    def test_list_users(self, mock_urlopen):
        """Test listing users."""
        mock_urlopen.return_value = mock_urlopen_response(
            {
                "users": [
                    {"id": "1", "email": "user1@test.com"},
                    {"id": "2", "email": "user2@test.com"},
                ]
            }
        )

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.users.list()

        assert result.success is True
        assert len(result.data.get("users", [])) == 2

    @patch("platform_admin.client.urlopen")
    def test_get_user_by_email(self, mock_urlopen):
        """Test getting user by email."""
        mock_urlopen.return_value = mock_urlopen_response(
            {"user": {"id": "123", "email": "test@test.com"}}
        )

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.users.get(email="test@test.com")

        assert result.success is True
        assert result.data.get("user", {}).get("email") == "test@test.com"

    @patch("platform_admin.client.urlopen")
    def test_get_user_not_found(self, mock_urlopen):
        """Test getting non-existent user."""
        mock_urlopen.side_effect = mock_http_error(404, "Not found")

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.users.get(email="nonexistent@test.com")

        assert result.success is False
        assert result.status_code == 404

    @patch("platform_admin.client.urlopen")
    def test_create_user(self, mock_urlopen):
        """Test creating a user."""
        mock_urlopen.return_value = mock_urlopen_response(
            {"user": {"id": "new-id", "email": "new@test.com"}}
        )

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.users.create(
            email="new@test.com",
            password="changeme",  # noqa: S106 - test fixture only
        )

        assert result.success is True

    @patch("platform_admin.client.urlopen")
    def test_delete_user(self, mock_urlopen):
        """Test deleting a user."""
        mock_urlopen.return_value = mock_urlopen_response({})

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.users.delete("user-id", hard_delete=True)

        assert result.success is True

    def test_get_user_requires_id_or_email(self):
        """Test that get requires either user_id or email."""
        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.users.get()

        assert result.success is False
        assert "user_id or email" in result.error.lower()


# =============================================================================
# GroupsService Unit Tests
# =============================================================================


@pytest.mark.unit
class TestGroupsServiceUnit:
    """Unit tests for GroupsService with mocked HTTP."""

    @patch("platform_admin.client.urlopen")
    def test_list_groups(self, mock_urlopen):
        """Test listing groups."""
        mock_urlopen.return_value = mock_urlopen_response(
            {
                "groups": [
                    {"id": "1", "name": "group1"},
                    {"id": "2", "name": "group2"},
                ]
            }
        )

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.groups.list()

        assert result.success is True
        assert len(result.data.get("groups", [])) == 2

    @patch("platform_admin.client.urlopen")
    def test_get_group_by_id(self, mock_urlopen):
        """Test getting group by ID."""
        mock_urlopen.return_value = mock_urlopen_response(
            {"group": {"id": "123", "name": "test-group"}}
        )

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.groups.get("123")

        assert result.success is True

    @patch("platform_admin.client.urlopen")
    def test_get_group_by_name(self, mock_urlopen):
        """Test getting group by name."""
        mock_urlopen.return_value = mock_urlopen_response(
            {
                "groups": [
                    {"id": "1", "name": "other-group"},
                    {"id": "2", "name": "test-group"},
                ]
            }
        )

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.groups.get_by_name("test-group")

        assert result.success is True
        assert result.data.get("group", {}).get("name") == "test-group"


# =============================================================================
# ApplicationsService Unit Tests
# =============================================================================


@pytest.mark.unit
class TestApplicationsServiceUnit:
    """Unit tests for ApplicationsService with mocked HTTP."""

    @patch("platform_admin.client.urlopen")
    def test_list_applications(self, mock_urlopen):
        """Test listing applications."""
        mock_urlopen.return_value = mock_urlopen_response(
            {
                "applications": [
                    {"id": "1", "name": "App1", "roles": []},
                    {"id": "2", "name": "App2", "roles": []},
                ]
            }
        )

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.applications.list()

        assert result.success is True
        assert len(result.data.get("applications", [])) == 2

    @patch("platform_admin.client.urlopen")
    def test_get_application_with_roles(self, mock_urlopen):
        """Test getting application with roles."""
        mock_urlopen.return_value = mock_urlopen_response(
            {
                "application": {
                    "id": "123",
                    "name": "OAuth2-Proxy",
                    "roles": [
                        {"id": "r1", "name": "admin"},
                        {"id": "r2", "name": "developer"},
                        {"id": "r3", "name": "viewer"},
                    ],
                }
            }
        )

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.applications.get("123")

        assert result.success is True
        app = result.data.get("application", {})
        assert app["name"] == "OAuth2-Proxy"
        assert len(app["roles"]) == 3


# =============================================================================
# RegistrationsService Unit Tests
# =============================================================================


@pytest.mark.unit
class TestRegistrationsServiceUnit:
    """Unit tests for RegistrationsService with mocked HTTP."""

    @patch("platform_admin.client.urlopen")
    def test_create_registration(self, mock_urlopen):
        """Test creating a registration."""
        mock_urlopen.return_value = mock_urlopen_response(
            {
                "registration": {
                    "applicationId": "app-123",
                    "userId": "user-123",
                    "roles": ["admin"],
                }
            }
        )

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.registrations.create("user-123", "app-123", roles=["admin"])

        assert result.success is True

    @patch("platform_admin.client.urlopen")
    def test_get_registration(self, mock_urlopen):
        """Test getting a registration."""
        mock_urlopen.return_value = mock_urlopen_response(
            {
                "registration": {
                    "applicationId": "app-123",
                    "userId": "user-123",
                    "roles": ["developer"],
                }
            }
        )

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.registrations.get("user-123", "app-123")

        assert result.success is True


# =============================================================================
# Error Handling Unit Tests
# =============================================================================


@pytest.mark.unit
class TestErrorHandling:
    """Unit tests for error handling."""

    @patch("platform_admin.client.urlopen")
    def test_connection_error(self, mock_urlopen):
        """Test handling of connection errors."""
        mock_urlopen.side_effect = URLError("Connection refused")

        config = Config(fusionauth_url="http://unreachable:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        result = client.validate()

        assert result.success is False
        assert "Connection" in str(result.error)

    @patch("platform_admin.client.urlopen")
    def test_http_error(self, mock_urlopen):
        """Test handling of HTTP errors."""
        mock_urlopen.side_effect = mock_http_error(
            401, "Unauthorized", {"message": "Invalid API key"}
        )

        config = Config(fusionauth_url="http://test:9011", api_key="invalid")
        client = PlatformAdminClient(config)

        result = client.validate()

        assert result.success is False
        assert result.status_code == 401

    @patch("platform_admin.client.urlopen")
    def test_invalid_json_response(self, mock_urlopen):
        """Test handling of invalid JSON responses."""
        mock_response = Mock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = b"Not JSON"
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        config = Config(fusionauth_url="http://test:9011", api_key="test-key")
        client = PlatformAdminClient(config)

        # Make a direct API call, not validate() which wraps the response
        result = client._api.get("/api/test")

        # Should handle gracefully
        assert result is not None
        assert result.success is True  # HTTP was successful
        assert "raw" in result.data  # Non-JSON stored in raw field
