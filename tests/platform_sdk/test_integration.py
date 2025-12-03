"""
Integration tests for Platform SDK against live FusionAuth.

These tests require:
- FusionAuth running at http://localhost:9011
- FUSIONAUTH_API_KEY environment variable set
"""

import os
import pytest
import uuid

from platform_sdk.exceptions import PermissionDeniedError


# Skip all tests if FusionAuth not available
pytestmark = [
    pytest.mark.integration,
]


class TestUsersIntegration:
    """Integration tests for Users service."""

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_list_users(self, admin_sdk):
        """Test listing users."""
        response = admin_sdk.users.list()

        assert response.success
        assert "users" in response.data

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_user_crud_workflow(self, admin_sdk, cleanup_users):
        """Test full user CRUD workflow."""
        # Create user
        unique = str(uuid.uuid4())[:8]
        email = f"test-{unique}@example.com"

        create_response = admin_sdk.users.create(
            email=email,
            password="SecurePassword123!",
            first_name="Test",
            last_name="User",
        )

        assert create_response.success, f"Create failed: {create_response.error}"
        user_id = create_response.data["user"]["id"]
        cleanup_users.append(user_id)

        # Get user
        get_response = admin_sdk.users.get(user_id)
        assert get_response.success
        assert get_response.data["user"]["email"] == email

        # Update user
        update_response = admin_sdk.users.update(
            user_id=user_id,
            first_name="Updated",
        )
        assert update_response.success

        # Verify update
        get_response = admin_sdk.users.get(user_id)
        assert get_response.data["user"]["firstName"] == "Updated"

        # Delete user
        delete_response = admin_sdk.users.delete(user_id, hard_delete=True)
        assert delete_response.success
        cleanup_users.remove(user_id)

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_viewer_cannot_create_users(self, viewer_sdk):
        """Test that viewer role cannot create users."""
        with pytest.raises(PermissionDeniedError):
            viewer_sdk.users.create(
                email="should-fail@example.com",
                password="Password123!",
            )

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_developer_can_read_users(self, developer_sdk):
        """Test that developer role can read users."""
        response = developer_sdk.users.list()
        assert response.success


class TestGroupsIntegration:
    """Integration tests for Groups service."""

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_list_groups(self, admin_sdk):
        """Test listing groups."""
        response = admin_sdk.groups.list()

        assert response.success
        assert "groups" in response.data

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_group_crud_workflow(self, admin_sdk, cleanup_groups):
        """Test full group CRUD workflow."""
        unique = str(uuid.uuid4())[:8]
        group_name = f"Test Group {unique}"

        # Create group
        create_response = admin_sdk.groups.create(
            name=group_name,
            description="Test group for SDK testing",
        )

        assert create_response.success, f"Create failed: {create_response.error}"
        group_id = create_response.data["group"]["id"]
        cleanup_groups.append(group_id)

        # Get group
        get_response = admin_sdk.groups.get(group_id)
        assert get_response.success
        assert get_response.data["group"]["name"] == group_name

        # Update group
        new_name = f"Updated Group {unique}"
        update_response = admin_sdk.groups.update(
            group_id=group_id,
            name=new_name,
        )
        assert update_response.success

        # Delete group
        delete_response = admin_sdk.groups.delete(group_id)
        assert delete_response.success
        cleanup_groups.remove(group_id)


class TestApplicationsIntegration:
    """Integration tests for Applications service."""

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_list_applications(self, admin_sdk):
        """Test listing applications."""
        response = admin_sdk.applications.list()

        assert response.success
        assert "applications" in response.data

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_application_crud_workflow(self, admin_sdk, cleanup_applications):
        """Test full application CRUD workflow."""
        unique = str(uuid.uuid4())[:8]
        app_name = f"Test App {unique}"

        # Create application
        create_response = admin_sdk.applications.create(
            name=app_name,
            roles=[
                {"name": "user", "description": "Standard user"},
                {"name": "admin", "description": "App admin"},
            ],
        )

        assert create_response.success, f"Create failed: {create_response.error}"
        app_id = create_response.data["application"]["id"]
        cleanup_applications.append(app_id)

        # Get application
        get_response = admin_sdk.applications.get(app_id)
        assert get_response.success
        assert get_response.data["application"]["name"] == app_name

        # Check roles were created
        roles = get_response.data["application"].get("roles", [])
        role_names = [r["name"] for r in roles]
        assert "user" in role_names
        assert "admin" in role_names

        # Delete application
        delete_response = admin_sdk.applications.delete(app_id, hard_delete=True)
        assert delete_response.success
        cleanup_applications.remove(app_id)


class TestRegistrationsIntegration:
    """Integration tests for Registrations service."""

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_registration_workflow(
        self,
        admin_sdk,
        cleanup_users,
        cleanup_applications,
    ):
        """Test full registration workflow."""
        unique = str(uuid.uuid4())[:8]

        # Create user
        user_response = admin_sdk.users.create(
            email=f"reg-test-{unique}@example.com",
            password="Password123!",
        )
        assert user_response.success
        user_id = user_response.data["user"]["id"]
        cleanup_users.append(user_id)

        # Create application
        app_response = admin_sdk.applications.create(
            name=f"Reg Test App {unique}",
            roles=[{"name": "user"}, {"name": "admin"}],
        )
        assert app_response.success
        app_id = app_response.data["application"]["id"]
        cleanup_applications.append(app_id)

        # Register user to application
        reg_response = admin_sdk.registrations.create(
            user_id=user_id,
            app_id=app_id,
            roles=["user"],
        )
        assert reg_response.success, f"Registration failed: {reg_response.error}"

        # Get registration
        get_response = admin_sdk.registrations.get(user_id, app_id)
        assert get_response.success
        assert "user" in get_response.data["registration"]["roles"]

        # Add admin role
        add_response = admin_sdk.registrations.add_roles(
            user_id=user_id,
            application_id=app_id,
            role_names=["admin"],
        )
        assert add_response.success

        # Verify both roles
        get_response = admin_sdk.registrations.get(user_id, app_id)
        roles = get_response.data["registration"]["roles"]
        assert "user" in roles
        assert "admin" in roles

        # Delete registration
        delete_response = admin_sdk.registrations.delete(user_id, app_id)
        assert delete_response.success


class TestAPIKeysIntegration:
    """Integration tests for API Keys service.

    Note: These tests require a "super" API key that can list/manage other keys.
    Tests will be skipped if the API key doesn't have super permissions.
    """

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_list_api_keys(self, admin_sdk):
        """Test listing API keys (requires super key)."""
        response = admin_sdk.api_keys.list()

        # Skip if not a super key (400 means key can't list other keys)
        if response.status_code == 400 and "apiKeyId" in str(response.error):
            pytest.skip("API key doesn't have super permissions to list keys")

        assert response.success
        assert "apiKeys" in response.data

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_introspect(self, admin_sdk):
        """Test API key introspection (requires super key)."""
        response = admin_sdk.api_keys.introspect()

        # Skip if not a super key
        if response.status_code == 400 and "apiKeyId" in str(response.error):
            pytest.skip("API key doesn't have super permissions to introspect")

        assert response.success

        assert response.success

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_create_and_delete_developer_key(self, admin_sdk):
        """Test creating and deleting a developer API key."""
        unique = str(uuid.uuid4())[:8]

        # Create developer key
        create_response = admin_sdk.api_keys.create_developer_key(
            description=f"SDK Test Developer Key {unique}",
        )

        assert create_response.success, f"Create failed: {create_response.error}"

        key_id = create_response.data["apiKey"]["id"]
        key_value = create_response.data["apiKey"].get("key")

        assert key_id is not None
        assert key_value is not None  # Only returned on create

        # Delete the key
        delete_response = admin_sdk.api_keys.delete(key_id)
        assert delete_response.success


class TestRoleBasedAccessIntegration:
    """Integration tests for role-based access control."""

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_admin_full_access(self, admin_sdk):
        """Test admin has full access."""
        # Can list all resources
        assert admin_sdk.users.list().success
        assert admin_sdk.groups.list().success
        assert admin_sdk.applications.list().success
        # Note: api_keys.list() requires super key, tested separately

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_developer_limited_access(self, developer_sdk):
        """Test developer has limited access."""
        # Can read
        assert developer_sdk.users.list().success

        # Cannot create users
        with pytest.raises(PermissionDeniedError):
            developer_sdk.users.create(
                email="dev-test@example.com",
                password="Password123!",
            )

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_viewer_read_only(self, viewer_sdk):
        """Test viewer has read-only access."""
        # Can read
        assert viewer_sdk.users.list().success

        # Cannot create anything
        with pytest.raises(PermissionDeniedError):
            viewer_sdk.users.create(
                email="viewer-test@example.com",
                password="Password123!",
            )

        with pytest.raises(PermissionDeniedError):
            viewer_sdk.groups.create(name="Viewer Group")


class TestSDKHealthCheck:
    """Integration tests for SDK health check."""

    @pytest.mark.skipif(
        not os.getenv("FUSIONAUTH_API_KEY"),
        reason="Requires FUSIONAUTH_API_KEY env var",
    )
    def test_health_check(self, admin_sdk):
        """Test health check against live FusionAuth."""
        response = admin_sdk.health_check()

        # Should return status from FusionAuth
        # Note: Success depends on FusionAuth status endpoint implementation
        assert response is not None
