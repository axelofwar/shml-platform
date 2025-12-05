"""Unit tests for Chat API authentication."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


# Test authentication module
class TestAuthentication:
    """Test authentication flows."""

    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self, mock_db):
        """Requests without authentication should return 401."""
        from inference.chat_api.app.auth import get_current_user
        from fastapi import Request

        request = MagicMock(spec=Request)

        with patch("inference.chat_api.app.auth.db", mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    request=request,
                    authorization=None,
                    x_auth_request_user=None,
                    x_auth_request_email=None,
                    x_auth_request_groups=None,
                    x_forwarded_user=None,
                )

            assert exc_info.value.status_code == 401
            assert "Authentication required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_401(self, mock_db):
        """Invalid API key should return 401."""
        from inference.chat_api.app.auth import get_current_user
        from fastapi import Request
        from fastapi.security import HTTPAuthorizationCredentials

        mock_db.validate_api_key.return_value = None  # Invalid key

        request = MagicMock(spec=Request)
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-invalid-key"
        )

        with patch("inference.chat_api.app.auth.db", mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    request=request,
                    authorization=credentials,
                    x_auth_request_user=None,
                    x_auth_request_email=None,
                    x_auth_request_groups=None,
                    x_forwarded_user=None,
                )

            assert exc_info.value.status_code == 401
            assert "Invalid or expired API key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_api_key_returns_user(self, mock_db, sample_api_key_user):
        """Valid API key should return user."""
        from inference.chat_api.app.auth import get_current_user
        from fastapi import Request
        from fastapi.security import HTTPAuthorizationCredentials

        mock_db.validate_api_key.return_value = sample_api_key_user

        request = MagicMock(spec=Request)
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-valid-key"
        )

        with patch("inference.chat_api.app.auth.db", mock_db):
            user = await get_current_user(
                request=request,
                authorization=credentials,
                x_auth_request_user=None,
                x_auth_request_email=None,
                x_auth_request_groups=None,
                x_forwarded_user=None,
            )

            assert user.id == sample_api_key_user.id
            assert user.auth_method == "api_key"

    @pytest.mark.asyncio
    async def test_oauth_headers_developer_role(self, mock_db):
        """OAuth headers with developer group should return developer role."""
        from inference.chat_api.app.auth import get_current_user
        from inference.chat_api.app.schemas import UserRole
        from fastapi import Request

        request = MagicMock(spec=Request)

        with patch("inference.chat_api.app.auth.db", mock_db):
            user = await get_current_user(
                request=request,
                authorization=None,
                x_auth_request_user="user123",
                x_auth_request_email="dev@example.com",
                x_auth_request_groups="developer",
                x_forwarded_user=None,
            )

            assert user.id == "user123"
            assert user.role == UserRole.DEVELOPER
            assert user.auth_method == "oauth"

    @pytest.mark.asyncio
    async def test_oauth_headers_admin_role(self, mock_db):
        """OAuth headers with admin group should return admin role."""
        from inference.chat_api.app.auth import get_current_user
        from inference.chat_api.app.schemas import UserRole
        from fastapi import Request

        request = MagicMock(spec=Request)

        with patch("inference.chat_api.app.auth.db", mock_db):
            user = await get_current_user(
                request=request,
                authorization=None,
                x_auth_request_user="admin123",
                x_auth_request_email="admin@example.com",
                x_auth_request_groups="admin,developer",
                x_forwarded_user=None,
            )

            assert user.id == "admin123"
            assert user.role == UserRole.ADMIN

    @pytest.mark.asyncio
    async def test_oauth_headers_no_groups_defaults_to_viewer(self, mock_db):
        """OAuth headers without groups should default to viewer role."""
        from inference.chat_api.app.auth import get_current_user
        from inference.chat_api.app.schemas import UserRole
        from fastapi import Request

        request = MagicMock(spec=Request)

        with patch("inference.chat_api.app.auth.db", mock_db):
            user = await get_current_user(
                request=request,
                authorization=None,
                x_auth_request_user="viewer123",
                x_auth_request_email="viewer@example.com",
                x_auth_request_groups=None,
                x_forwarded_user=None,
            )

            assert user.id == "viewer123"
            assert user.role == UserRole.VIEWER


class TestRoleRequirements:
    """Test role-based access control."""

    @pytest.mark.asyncio
    async def test_require_admin_allows_admin(self, sample_user_admin):
        """Admin should pass require_admin check."""
        from inference.chat_api.app.auth import require_admin

        # Directly call with admin user
        result = require_admin(user=sample_user_admin)
        assert result.role.value == "admin"

    @pytest.mark.asyncio
    async def test_require_admin_rejects_developer(self, sample_user_developer):
        """Developer should fail require_admin check."""
        from inference.chat_api.app.auth import require_admin

        with pytest.raises(HTTPException) as exc_info:
            require_admin(user=sample_user_developer)

        assert exc_info.value.status_code == 403
        assert "Admin access required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_admin_rejects_viewer(self, sample_user_viewer):
        """Viewer should fail require_admin check."""
        from inference.chat_api.app.auth import require_admin

        with pytest.raises(HTTPException) as exc_info:
            require_admin(user=sample_user_viewer)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_developer_allows_developer(self, sample_user_developer):
        """Developer should pass require_developer_or_admin check."""
        from inference.chat_api.app.auth import require_developer_or_admin

        result = require_developer_or_admin(user=sample_user_developer)
        assert result.role.value == "developer"

    @pytest.mark.asyncio
    async def test_require_developer_allows_admin(self, sample_user_admin):
        """Admin should pass require_developer_or_admin check."""
        from inference.chat_api.app.auth import require_developer_or_admin

        result = require_developer_or_admin(user=sample_user_admin)
        assert result.role.value == "admin"

    @pytest.mark.asyncio
    async def test_require_developer_rejects_viewer(self, sample_user_viewer):
        """Viewer should fail require_developer_or_admin check."""
        from inference.chat_api.app.auth import require_developer_or_admin

        with pytest.raises(HTTPException) as exc_info:
            require_developer_or_admin(user=sample_user_viewer)

        assert exc_info.value.status_code == 403
        assert "Developer or admin access required" in exc_info.value.detail


class TestAPIKeyPermissions:
    """Test API key creation permissions."""

    @pytest.mark.asyncio
    async def test_viewer_cannot_create_api_key(self, sample_user_viewer):
        """Viewers should not be able to create API keys."""
        from inference.chat_api.app.database import Database
        from inference.chat_api.app.schemas import APIKeyCreate

        db = Database()
        db.pool = AsyncMock()

        request = APIKeyCreate(name="Test Key")

        with pytest.raises(PermissionError) as exc_info:
            await db.create_api_key(sample_user_viewer, request)

        assert "Viewers cannot create API keys" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_developer_cannot_create_key_for_others(self, sample_user_developer):
        """Developers should not be able to create keys for other users."""
        from inference.chat_api.app.database import Database
        from inference.chat_api.app.schemas import APIKeyCreate

        db = Database()
        db.pool = AsyncMock()

        request = APIKeyCreate(
            name="Test Key", target_user_id="other_user123"  # Different user
        )

        with pytest.raises(PermissionError) as exc_info:
            await db.create_api_key(sample_user_developer, request)

        assert "Developers can only create keys for themselves" in str(exc_info.value)
