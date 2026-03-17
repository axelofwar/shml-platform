"""
Unit tests for Platform SDK models.
"""

import pytest
from shml.admin.models import (
    Role,
    Permission,
    APIResponse,
    PaginatedResponse,
    get_permissions_for_role,
    role_has_permission,
)


class TestRole:
    """Tests for Role enum."""

    def test_role_values(self):
        """Test role string values."""
        assert Role.ADMIN.value == "admin"
        assert Role.DEVELOPER.value == "developer"
        assert Role.VIEWER.value == "viewer"
        assert Role.SERVICE_ACCOUNT.value == "service_account"

    def test_role_levels(self):
        """Test role permission levels."""
        assert Role.ADMIN.level == 100
        assert Role.DEVELOPER.level == 50
        assert Role.VIEWER.level == 10
        assert Role.SERVICE_ACCOUNT.level == 50

    def test_role_has_permission_hierarchy(self):
        """Test that higher roles have permission for lower roles."""
        # Admin has permission for all
        assert Role.ADMIN.has_permission(Role.ADMIN)
        assert Role.ADMIN.has_permission(Role.DEVELOPER)
        assert Role.ADMIN.has_permission(Role.VIEWER)

        # Developer has permission for developer and viewer
        assert not Role.DEVELOPER.has_permission(Role.ADMIN)
        assert Role.DEVELOPER.has_permission(Role.DEVELOPER)
        assert Role.DEVELOPER.has_permission(Role.VIEWER)

        # Viewer only has permission for viewer
        assert not Role.VIEWER.has_permission(Role.ADMIN)
        assert not Role.VIEWER.has_permission(Role.DEVELOPER)
        assert Role.VIEWER.has_permission(Role.VIEWER)

    def test_role_from_string(self):
        """Test parsing role from string."""
        assert Role.from_string("admin") == Role.ADMIN
        assert Role.from_string("ADMIN") == Role.ADMIN
        assert Role.from_string("developer") == Role.DEVELOPER
        assert Role.from_string("viewer") == Role.VIEWER
        assert Role.from_string("invalid") == Role.VIEWER  # Default to viewer


class TestPermission:
    """Tests for Permission enum."""

    def test_permission_categories(self):
        """Test permission categories."""
        # User permissions
        assert Permission.USERS_READ.value == "users:read"
        assert Permission.USERS_CREATE.value == "users:create"
        assert Permission.USERS_UPDATE.value == "users:update"
        assert Permission.USERS_DELETE.value == "users:delete"

        # Group permissions
        assert Permission.GROUPS_READ.value == "groups:read"
        assert Permission.GROUPS_MANAGE_MEMBERS.value == "groups:manage_members"

        # API key permissions
        assert Permission.API_KEYS_READ.value == "api_keys:read"
        assert Permission.API_KEYS_CREATE.value == "api_keys:create"
        assert Permission.API_KEYS_UPDATE.value == "api_keys:update"
        assert Permission.API_KEYS_DELETE.value == "api_keys:delete"

    def test_all_permissions_count(self):
        """Test that we have expected number of permissions."""
        assert len(Permission) >= 20  # At least 20 permissions


class TestRolePermissions:
    """Tests for role-to-permission mapping."""

    def test_admin_has_all_permissions(self):
        """Test that admin has all permissions."""
        admin_perms = get_permissions_for_role(Role.ADMIN)
        assert admin_perms == set(Permission)

    def test_developer_read_permissions(self):
        """Test developer has read permissions."""
        dev_perms = get_permissions_for_role(Role.DEVELOPER)
        assert Permission.USERS_READ in dev_perms
        assert Permission.GROUPS_READ in dev_perms
        assert Permission.APPLICATIONS_READ in dev_perms

    def test_developer_limited_write(self):
        """Test developer has limited write permissions."""
        dev_perms = get_permissions_for_role(Role.DEVELOPER)
        # Developer can create registrations
        assert Permission.REGISTRATIONS_CREATE in dev_perms
        # But cannot create users
        assert Permission.USERS_CREATE not in dev_perms

    def test_viewer_read_only(self):
        """Test viewer only has read permissions."""
        viewer_perms = get_permissions_for_role(Role.VIEWER)

        # Has read permissions
        assert Permission.USERS_READ in viewer_perms
        assert Permission.GROUPS_READ in viewer_perms

        # No write permissions
        assert Permission.USERS_CREATE not in viewer_perms
        assert Permission.USERS_UPDATE not in viewer_perms
        assert Permission.USERS_DELETE not in viewer_perms
        assert Permission.GROUPS_CREATE not in viewer_perms

    def test_role_has_permission_function(self):
        """Test role_has_permission helper function."""
        assert role_has_permission(Role.ADMIN, Permission.USERS_DELETE)
        assert not role_has_permission(Role.VIEWER, Permission.USERS_DELETE)


class TestAPIResponse:
    """Tests for APIResponse model."""

    def test_ok_response(self):
        """Test creating success response."""
        response = APIResponse.ok(
            data={"users": [{"id": "1"}]},
            status_code=200,
            request_id="abc123",
        )

        assert response.success is True
        assert response.data == {"users": [{"id": "1"}]}
        assert response.status_code == 200
        assert response.request_id == "abc123"
        assert response.error is None

    def test_fail_response(self):
        """Test creating failure response."""
        response = APIResponse.fail(
            error="User not found",
            status_code=404,
            request_id="xyz789",
        )

        assert response.success is False
        assert response.error == "User not found"
        assert response.status_code == 404
        assert response.request_id == "xyz789"

    def test_raise_for_status_success(self):
        """Test raise_for_status doesn't raise on success."""
        response = APIResponse.ok(data={})
        response.raise_for_status()  # Should not raise

    def test_raise_for_status_auth_error(self):
        """Test raise_for_status raises AuthenticationError."""
        from shml.admin.exceptions import AuthenticationError

        response = APIResponse.fail(error="Invalid API key", status_code=401)
        with pytest.raises(AuthenticationError):
            response.raise_for_status()

    def test_raise_for_status_permission_error(self):
        """Test raise_for_status raises PermissionDeniedError."""
        from shml.admin.exceptions import PermissionDeniedError

        response = APIResponse.fail(error="Forbidden", status_code=403)
        with pytest.raises(PermissionDeniedError):
            response.raise_for_status()

    def test_raise_for_status_rate_limit(self):
        """Test raise_for_status raises RateLimitError."""
        from shml.admin.exceptions import RateLimitError

        response = APIResponse.fail(error="Too many requests", status_code=429)
        with pytest.raises(RateLimitError):
            response.raise_for_status()

    def test_raise_for_status_validation_error(self):
        """Test raise_for_status raises ValidationError."""
        from shml.admin.exceptions import ValidationError

        response = APIResponse.fail(error="Invalid email", status_code=400)
        with pytest.raises(ValidationError):
            response.raise_for_status()


class TestPaginatedResponse:
    """Tests for PaginatedResponse model."""

    def test_paginated_response_defaults(self):
        """Test default values for paginated response."""
        response = PaginatedResponse()

        assert response.items == []
        assert response.total == 0
        assert response.page == 1
        assert response.page_size == 25
        assert response.has_more is False

    def test_paginated_response_with_data(self):
        """Test paginated response with data."""
        items = [{"id": "1"}, {"id": "2"}]
        response = PaginatedResponse(
            items=items,
            total=100,
            page=2,
            page_size=10,
            has_more=True,
        )

        assert len(response.items) == 2
        assert response.total == 100
        assert response.page == 2
        assert response.page_size == 10
        assert response.has_more is True
