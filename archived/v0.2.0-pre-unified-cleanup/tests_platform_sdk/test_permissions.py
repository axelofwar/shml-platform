"""
Unit tests for Platform SDK permission system.
"""

import pytest

from platform_sdk.models import Role, Permission
from platform_sdk.permissions import (
    PermissionContext,
    requires_permission,
)
from platform_sdk.exceptions import PermissionDeniedError


class TestPermissionContext:
    """Tests for PermissionContext class."""

    def test_admin_has_all_permissions(self):
        """Test admin context has all permissions."""
        ctx = PermissionContext(role=Role.ADMIN)

        for perm in Permission:
            assert ctx.has_permission(perm), f"Admin should have {perm}"

    def test_viewer_limited_permissions(self):
        """Test viewer context has limited permissions."""
        ctx = PermissionContext(role=Role.VIEWER)

        # Has read permissions
        assert ctx.has_permission(Permission.USERS_READ)
        assert ctx.has_permission(Permission.GROUPS_READ)

        # Doesn't have write permissions
        assert not ctx.has_permission(Permission.USERS_CREATE)
        assert not ctx.has_permission(Permission.USERS_DELETE)

    def test_explicit_permissions_override_role(self):
        """Test that explicit permissions override role-based permissions."""
        # Viewer with explicit admin permission for users
        ctx = PermissionContext(
            role=Role.VIEWER,
            permissions={Permission.USERS_DELETE},
        )

        # Has explicitly granted permission
        assert ctx.has_permission(Permission.USERS_DELETE)

        # Doesn't have role-based permission anymore
        assert not ctx.has_permission(Permission.USERS_READ)

    def test_has_any_permission(self):
        """Test has_any_permission method."""
        ctx = PermissionContext(role=Role.VIEWER)

        # Has at least one of these (users:read)
        assert ctx.has_any_permission(
            [
                Permission.USERS_READ,
                Permission.USERS_CREATE,
            ]
        )

        # Has none of these
        assert not ctx.has_any_permission(
            [
                Permission.USERS_CREATE,
                Permission.USERS_DELETE,
            ]
        )

    def test_has_all_permissions(self):
        """Test has_all_permissions method."""
        ctx = PermissionContext(role=Role.VIEWER)

        # Has all read permissions
        assert ctx.has_all_permissions(
            [
                Permission.USERS_READ,
                Permission.GROUPS_READ,
            ]
        )

        # Doesn't have all of these (missing create)
        assert not ctx.has_all_permissions(
            [
                Permission.USERS_READ,
                Permission.USERS_CREATE,
            ]
        )

    def test_check_permission_raises(self):
        """Test check_permission raises PermissionDeniedError."""
        ctx = PermissionContext(role=Role.VIEWER)

        with pytest.raises(PermissionDeniedError) as exc_info:
            ctx.check_permission(Permission.USERS_DELETE, operation="delete_user")

        assert "delete_user" in str(exc_info.value)

    def test_check_permission_passes(self):
        """Test check_permission doesn't raise for granted permission."""
        ctx = PermissionContext(role=Role.VIEWER)

        # Should not raise
        ctx.check_permission(Permission.USERS_READ, operation="list_users")


class TestRequiresPermissionDecorator:
    """Tests for @requires_permission decorator."""

    def test_decorator_allows_with_permission(self):
        """Test decorator allows call when permission granted."""

        class MockService:
            def __init__(self, permission_context):
                self._permission_context = permission_context

            @requires_permission(Permission.USERS_READ)
            def list_users(self):
                return "users"

        service = MockService(PermissionContext(role=Role.ADMIN))
        result = service.list_users()
        assert result == "users"

    def test_decorator_denies_without_permission(self):
        """Test decorator denies call when permission not granted."""

        class MockService:
            def __init__(self, permission_context):
                self._permission_context = permission_context

            @requires_permission(Permission.USERS_DELETE)
            def delete_user(self, user_id):
                return f"deleted {user_id}"

        service = MockService(PermissionContext(role=Role.VIEWER))

        with pytest.raises(PermissionDeniedError):
            service.delete_user("user-123")

    def test_decorator_multiple_permissions_all_required(self):
        """Test decorator requires all specified permissions."""

        class MockService:
            def __init__(self, permission_context):
                self._permission_context = permission_context

            @requires_permission(Permission.USERS_CREATE, Permission.USERS_UPDATE)
            def upsert_user(self, user_id=None):
                return "upserted"

        # Developer has neither CREATE nor UPDATE
        service = MockService(PermissionContext(role=Role.DEVELOPER))

        with pytest.raises(PermissionDeniedError):
            service.upsert_user()

        # Admin has both
        service = MockService(PermissionContext(role=Role.ADMIN))
        result = service.upsert_user()
        assert result == "upserted"

    def test_decorator_stores_permissions_metadata(self):
        """Test decorator stores permission metadata on function."""

        class MockService:
            def __init__(self, permission_context):
                self._permission_context = permission_context

            @requires_permission(Permission.USERS_READ, Permission.USERS_CREATE)
            def my_method(self):
                pass

        service = MockService(PermissionContext(role=Role.ADMIN))
        method = service.my_method

        assert hasattr(method, "_required_permissions")
        assert Permission.USERS_READ in method._required_permissions
        assert Permission.USERS_CREATE in method._required_permissions
        assert hasattr(method, "_is_permission_protected")
        assert method._is_permission_protected is True


class TestRoleBasedAccess:
    """Integration tests for role-based access patterns."""

    @pytest.fixture
    def service_class(self):
        """Create a test service class with various methods."""

        class TestService:
            def __init__(self, permission_context):
                self._permission_context = permission_context

            @requires_permission(Permission.USERS_READ)
            def list_users(self):
                return ["user1", "user2"]

            @requires_permission(Permission.USERS_CREATE)
            def create_user(self, email):
                return {"id": "new-id", "email": email}

            @requires_permission(Permission.USERS_UPDATE)
            def update_user(self, user_id, **kwargs):
                return {"id": user_id, **kwargs}

            @requires_permission(Permission.USERS_DELETE)
            def delete_user(self, user_id):
                return True

        return TestService

    def test_admin_can_do_all(self, service_class):
        """Test admin can perform all operations."""
        ctx = PermissionContext(role=Role.ADMIN)
        service = service_class(ctx)

        assert service.list_users() == ["user1", "user2"]
        assert service.create_user("test@test.com")["email"] == "test@test.com"
        assert service.update_user("id", name="New Name")["name"] == "New Name"
        assert service.delete_user("id") is True

    def test_viewer_read_only(self, service_class):
        """Test viewer can only read."""
        ctx = PermissionContext(role=Role.VIEWER)
        service = service_class(ctx)

        # Can read
        assert service.list_users() == ["user1", "user2"]

        # Cannot create/update/delete
        with pytest.raises(PermissionDeniedError):
            service.create_user("test@test.com")

        with pytest.raises(PermissionDeniedError):
            service.update_user("id", name="New Name")

        with pytest.raises(PermissionDeniedError):
            service.delete_user("id")

    def test_developer_intermediate(self, service_class):
        """Test developer has read but not write access."""
        ctx = PermissionContext(role=Role.DEVELOPER)
        service = service_class(ctx)

        # Can read
        assert service.list_users() == ["user1", "user2"]

        # Cannot create/update/delete users (only admin can)
        with pytest.raises(PermissionDeniedError):
            service.create_user("test@test.com")
