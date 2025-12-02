"""
Unit tests for Platform SDK services (with mocked HTTP).
"""

import pytest
from unittest.mock import MagicMock, patch

from platform_sdk.models import APIResponse, Permission, Role
from platform_sdk.permissions import PermissionContext
from platform_sdk.exceptions import PermissionDeniedError


class TestUsersService:
    """Tests for UsersService."""

    def test_list_users_as_admin(self, users_service, mock_http_client):
        """Test listing users with admin permissions."""
        mock_http_client.get_sync.return_value = APIResponse.ok(
            data={"users": [{"id": "1", "email": "user@test.com"}]}
        )

        response = users_service.list()

        assert response.success
        assert len(response.data["users"]) == 1
        mock_http_client.get_sync.assert_called_once()

    def test_list_users_as_viewer(self, mock_http_client, viewer_context):
        """Test listing users with viewer permissions."""
        from platform_sdk.services import UsersService

        service = UsersService(
            http_client=mock_http_client,
            permission_context=viewer_context,
        )

        mock_http_client.get_sync.return_value = APIResponse.ok(data={"users": []})

        # Viewer can read
        response = service.list()
        assert response.success

    def test_create_user_denied_for_viewer(self, mock_http_client, viewer_context):
        """Test creating user denied for viewer."""
        from platform_sdk.services import UsersService

        service = UsersService(
            http_client=mock_http_client,
            permission_context=viewer_context,
        )

        with pytest.raises(PermissionDeniedError):
            service.create(
                email="test@test.com",
                password="Password123!",
            )

    def test_create_user_allowed_for_admin(self, users_service, mock_http_client):
        """Test creating user allowed for admin."""
        mock_http_client.post_sync.return_value = APIResponse.ok(
            data={"user": {"id": "new-id", "email": "test@test.com"}}
        )

        response = users_service.create(
            email="test@test.com",
            password="Password123!",
            first_name="Test",
            last_name="User",
        )

        assert response.success
        assert response.data["user"]["email"] == "test@test.com"

    def test_get_user(self, users_service, mock_http_client):
        """Test getting user by ID."""
        mock_http_client.get_sync.return_value = APIResponse.ok(
            data={"user": {"id": "user-123", "email": "user@test.com"}}
        )

        response = users_service.get("user-123")

        assert response.success
        assert response.data["user"]["id"] == "user-123"
        mock_http_client.get_sync.assert_called_with("/api/user/user-123")

    def test_delete_user_denied_for_developer(
        self, mock_http_client, developer_context
    ):
        """Test deleting user denied for developer."""
        from platform_sdk.services import UsersService

        service = UsersService(
            http_client=mock_http_client,
            permission_context=developer_context,
        )

        with pytest.raises(PermissionDeniedError):
            service.delete("user-123")

    def test_search_users(self, users_service, mock_http_client):
        """Test searching users."""
        mock_http_client.post_sync.return_value = APIResponse.ok(
            data={"users": [{"id": "1"}], "total": 1}
        )

        response = users_service.search(query="test@")

        assert response.success
        mock_http_client.post_sync.assert_called_once()


class TestGroupsService:
    """Tests for GroupsService."""

    def test_list_groups(self, groups_service, mock_http_client):
        """Test listing groups."""
        mock_http_client.get_sync.return_value = APIResponse.ok(
            data={"groups": [{"id": "g1", "name": "Admins"}]}
        )

        response = groups_service.list()

        assert response.success
        assert len(response.data["groups"]) == 1

    def test_create_group_as_admin(self, groups_service, mock_http_client):
        """Test creating group as admin."""
        mock_http_client.post_sync.return_value = APIResponse.ok(
            data={"group": {"id": "new-group", "name": "New Group"}}
        )

        response = groups_service.create(name="New Group", description="Test group")

        assert response.success
        assert response.data["group"]["name"] == "New Group"

    def test_create_group_denied_for_viewer(self, mock_http_client, viewer_context):
        """Test creating group denied for viewer."""
        from platform_sdk.services import GroupsService

        service = GroupsService(
            http_client=mock_http_client,
            permission_context=viewer_context,
        )

        with pytest.raises(PermissionDeniedError):
            service.create(name="New Group")

    def test_add_member(self, groups_service, mock_http_client):
        """Test adding member to group."""
        mock_http_client.post_sync.return_value = APIResponse.ok(data={"members": {}})

        response = groups_service.add_member(
            group_id="group-123",
            user_id="user-456",
        )

        assert response.success
        # Verify the correct API format
        call_args = mock_http_client.post_sync.call_args
        assert call_args[0][0] == "/api/group/member"
        assert "members" in call_args[1]["json"]
        assert "group-123" in call_args[1]["json"]["members"]


class TestApplicationsService:
    """Tests for ApplicationsService."""

    def test_list_applications(self, applications_service, mock_http_client):
        """Test listing applications."""
        mock_http_client.get_sync.return_value = APIResponse.ok(
            data={"applications": [{"id": "app1", "name": "Test App"}]}
        )

        response = applications_service.list()

        assert response.success
        assert len(response.data["applications"]) == 1

    def test_create_application_as_admin(self, applications_service, mock_http_client):
        """Test creating application as admin."""
        mock_http_client.post_sync.return_value = APIResponse.ok(
            data={"application": {"id": "new-app", "name": "New App"}}
        )

        response = applications_service.create(
            name="New App",
            roles=[{"name": "user"}, {"name": "admin"}],
        )

        assert response.success

    def test_create_application_denied_for_developer(
        self, mock_http_client, developer_context
    ):
        """Test creating application denied for developer."""
        from platform_sdk.services import ApplicationsService

        service = ApplicationsService(
            http_client=mock_http_client,
            permission_context=developer_context,
        )

        with pytest.raises(PermissionDeniedError):
            service.create(name="New App")

    def test_add_role(self, applications_service, mock_http_client):
        """Test adding role to application."""
        mock_http_client.post_sync.return_value = APIResponse.ok(
            data={"role": {"id": "role-123", "name": "editor"}}
        )

        response = applications_service.add_role(
            application_id="app-123",
            name="editor",
            description="Can edit content",
        )

        assert response.success


class TestRegistrationsService:
    """Tests for RegistrationsService."""

    def test_create_registration_as_developer(
        self, mock_http_client, developer_context
    ):
        """Test creating registration as developer."""
        from platform_sdk.services import RegistrationsService

        service = RegistrationsService(
            http_client=mock_http_client,
            permission_context=developer_context,
        )

        mock_http_client.post_sync.return_value = APIResponse.ok(
            data={"registration": {"applicationId": "app-123", "roles": ["user"]}}
        )

        response = service.create(
            user_id="user-123",
            app_id="app-123",
            roles=["user"],
        )

        assert response.success

    def test_get_registration(self, registrations_service, mock_http_client):
        """Test getting registration."""
        mock_http_client.get_sync.return_value = APIResponse.ok(
            data={"registration": {"applicationId": "app-123", "roles": ["user"]}}
        )

        response = registrations_service.get(
            user_id="user-123",
            application_id="app-123",
        )

        assert response.success
        mock_http_client.get_sync.assert_called_with(
            "/api/user/registration/user-123/app-123"
        )

    def test_add_roles(self, registrations_service, mock_http_client):
        """Test adding roles to registration."""
        # First call to get current registration
        mock_http_client.get_sync.return_value = APIResponse.ok(
            data={"registration": {"applicationId": "app-123", "roles": ["user"]}}
        )

        # Second call to update
        mock_http_client.patch_sync.return_value = APIResponse.ok(
            data={
                "registration": {"applicationId": "app-123", "roles": ["user", "admin"]}
            }
        )

        response = registrations_service.add_roles(
            user_id="user-123",
            application_id="app-123",
            role_names=["admin"],
        )

        assert response.success


class TestAPIKeysService:
    """Tests for APIKeysService."""

    def test_list_api_keys(self, api_keys_service, mock_http_client):
        """Test listing API keys."""
        mock_http_client.get_sync.return_value = APIResponse.ok(
            data={"apiKeys": [{"id": "key-1", "description": "Test key"}]}
        )

        response = api_keys_service.list()

        assert response.success
        assert len(response.data["apiKeys"]) == 1

    def test_create_admin_key(self, api_keys_service, mock_http_client):
        """Test creating admin API key."""
        mock_http_client.post_sync.return_value = APIResponse.ok(
            data={"apiKey": {"id": "new-key", "key": "secret-key-value"}}
        )

        response = api_keys_service.create_admin_key(
            description="Admin key for CI",
        )

        assert response.success

    def test_create_developer_key(self, api_keys_service, mock_http_client):
        """Test creating developer API key."""
        mock_http_client.post_sync.return_value = APIResponse.ok(
            data={"apiKey": {"id": "new-key", "key": "dev-key-value"}}
        )

        response = api_keys_service.create_developer_key(
            description="Developer key for testing",
        )

        assert response.success

        # Verify the key has limited permissions
        call_args = mock_http_client.post_sync.call_args
        assert "permissions" in call_args[1]["json"]["apiKey"]

    def test_create_viewer_key(self, api_keys_service, mock_http_client):
        """Test creating viewer API key."""
        mock_http_client.post_sync.return_value = APIResponse.ok(
            data={"apiKey": {"id": "new-key", "key": "viewer-key-value"}}
        )

        response = api_keys_service.create_viewer_key(
            description="Viewer key for dashboard",
        )

        assert response.success

    def test_create_api_key_denied_for_viewer(self, mock_http_client, viewer_context):
        """Test creating API key denied for viewer."""
        from platform_sdk.services import APIKeysService

        service = APIKeysService(
            http_client=mock_http_client,
            permission_context=viewer_context,
        )

        with pytest.raises(PermissionDeniedError):
            service.create(description="New key")

    def test_introspect_no_permission_required(
        self, api_keys_service, mock_http_client
    ):
        """Test that introspect doesn't require special permissions."""
        # introspect() is special - it doesn't have @requires_permission
        mock_http_client.get_sync.return_value = APIResponse.ok(
            data={"apiKeys": [{"id": "current-key"}]}
        )

        response = api_keys_service.introspect()

        assert response.success

    def test_get_role_from_metadata(self, api_keys_service):
        """Test extracting role from API key metadata."""
        key_data = {
            "id": "key-1",
            "metaData": {"role": "developer"},
        }

        role = api_keys_service.get_role_from_metadata(key_data)
        assert role == "developer"

    def test_has_super_permissions(self, api_keys_service):
        """Test detecting super (admin) permissions."""
        # Super key has no endpoint restrictions
        super_key = {"id": "key-1", "permissions": {"endpoints": {}}}
        assert api_keys_service.has_super_permissions(super_key)

        # Limited key has endpoint restrictions
        limited_key = {
            "id": "key-2",
            "permissions": {"endpoints": {"/api/user": ["GET"]}},
        }
        assert not api_keys_service.has_super_permissions(limited_key)
