"""
Integration tests for Platform Admin SDK listing functions.

These tests run against a live FusionAuth instance and verify:
- User listing and search
- Group listing
- Application listing
- Role listing
- Required infrastructure exists
"""

import pytest
import logging
import sys
import os

# Add conftest to path
sys.path.insert(0, os.path.dirname(__file__))

from conftest import (
    rate_limiter,
    REQUIRED_OAUTH_ROLES,
    REQUIRED_GROUPS,
    TEST_USERS,
    check_response,
    get_response_data,
    FusionAuthError,
)

logger = logging.getLogger("platform_admin.tests.integration")


# =============================================================================
# Infrastructure Validation Tests
# =============================================================================


@pytest.mark.integration
class TestInfrastructureRequirements:
    """Verify required FusionAuth infrastructure exists."""

    def test_fusionauth_connection(self, admin):
        """Test that we can connect to FusionAuth."""
        assert admin is not None
        response = admin.validate()
        assert response.success is True

    def test_oauth2_proxy_app_exists(self, oauth_app):
        """Test that OAuth2-Proxy application exists."""
        assert oauth_app is not None
        assert oauth_app.get("name") == "OAuth2-Proxy"
        assert oauth_app.get("active") is True
        logger.info(f"OAuth2-Proxy app ID: {oauth_app['id']}")

    def test_required_oauth_roles_exist(self, oauth_app, oauth_roles):
        """Test that all required OAuth roles exist."""
        role_names = [r["name"] for r in oauth_roles]

        for required_role in REQUIRED_OAUTH_ROLES:
            assert (
                required_role in role_names
            ), f"Missing required role: {required_role}"
            logger.info(f"✓ Found required role: {required_role}")

    def test_required_groups_exist(self, groups):
        """Test that all required groups exist."""
        for required_group in REQUIRED_GROUPS:
            assert required_group in groups, f"Missing required group: {required_group}"
            logger.info(f"✓ Found required group: {required_group}")

    def test_fusionauth_app_exists(self, all_apps):
        """Test that FusionAuth admin application exists."""
        app_names = [a["name"] for a in all_apps]
        assert "FusionAuth" in app_names, "FusionAuth application not found"


# =============================================================================
# User Listing Tests
# =============================================================================


@pytest.mark.integration
class TestUserListing:
    """Tests for user listing and search functionality."""

    def test_list_users_returns_list(self, admin):
        """Test that list_users returns a list."""
        rate_limiter.wait()
        response = admin.users.list()

        assert response.success
        users = response.data.get("users", [])
        assert isinstance(users, list)
        logger.info(f"Found {len(users)} users")

    def test_list_users_has_required_fields(self, admin):
        """Test that users have required fields."""
        rate_limiter.wait()
        response = admin.users.list()

        assert response.success
        users = response.data.get("users", [])

        if len(users) > 0:
            user = users[0]
            assert "id" in user
            assert "email" in user
            logger.info(f"Sample user: {user.get('email')}")

    def test_admin_user_exists(self, admin):
        """Test that admin user exists."""
        rate_limiter.wait()
        response = admin.users.get(email="admin@ml-platform.local")

        assert response.success, f"Admin user not found: {response.error}"
        user = response.data.get("user", {})
        assert user.get("email") == "admin@ml-platform.local"
        logger.info(f"Admin user ID: {user['id']}")

    def test_search_users(self, admin):
        """Test user search functionality."""
        rate_limiter.wait()
        response = admin.users.search("admin")

        assert response.success
        users = response.data.get("users", [])
        assert isinstance(users, list)

        emails = [u.get("email", "") for u in users]
        assert any(
            "admin" in e.lower() for e in emails
        ), f"Admin not found in search results: {emails}"

    def test_search_users_no_results(self, admin):
        """Test search with no results."""
        rate_limiter.wait()
        response = admin.users.search("nonexistent_user_xyz_12345")

        assert response.success
        users = response.data.get("users", [])
        assert isinstance(users, list)
        logger.info(f"Search for nonexistent user returned {len(users)} results")

    def test_get_user_by_id(self, admin):
        """Test getting user by ID."""
        rate_limiter.wait()
        # First get admin user by email
        admin_response = admin.users.get(email="admin@ml-platform.local")
        assert admin_response.success
        admin_user = admin_response.data.get("user", {})

        rate_limiter.wait()
        # Then get by ID
        response = admin.users.get(user_id=admin_user["id"])

        assert response.success
        user = response.data.get("user", {})
        assert user["id"] == admin_user["id"]
        assert user["email"] == "admin@ml-platform.local"


# =============================================================================
# Group Listing Tests
# =============================================================================


@pytest.mark.integration
class TestGroupListing:
    """Tests for group listing functionality."""

    def test_list_groups_returns_list(self, admin):
        """Test that list_groups returns a list."""
        rate_limiter.wait()
        response = admin.groups.list()

        assert response.success
        groups = response.data.get("groups", [])
        assert isinstance(groups, list)
        assert len(groups) >= len(REQUIRED_GROUPS)
        logger.info(f"Found {len(groups)} groups")

    def test_list_groups_has_required_fields(self, admin):
        """Test that groups have required fields."""
        rate_limiter.wait()
        response = admin.groups.list()

        assert response.success
        groups = response.data.get("groups", [])

        for group in groups:
            assert "id" in group
            assert "name" in group

    def test_get_group_by_name(self, admin):
        """Test getting group by name."""
        rate_limiter.wait()
        response = admin.groups.get_by_name("platform-admins")

        assert response.success
        group = response.data.get("group", response.data)
        assert group is not None
        assert group.get("name") == "platform-admins"
        logger.info(f"platform-admins group ID: {group['id']}")

    def test_get_group_by_id(self, admin, groups):
        """Test getting group by ID."""
        group_id = groups["platform-admins"]["id"]

        rate_limiter.wait()
        response = admin.groups.get(group_id)

        assert response.success
        group = response.data.get("group", {})
        assert group["id"] == group_id
        assert group["name"] == "platform-admins"


# =============================================================================
# Application Listing Tests
# =============================================================================


@pytest.mark.integration
class TestApplicationListing:
    """Tests for application listing functionality."""

    def test_list_applications_returns_list(self, admin):
        """Test that list_applications returns a list."""
        rate_limiter.wait()
        response = admin.applications.list()

        assert response.success
        apps = response.data.get("applications", [])
        assert isinstance(apps, list)
        assert len(apps) >= 1  # At least OAuth2-Proxy
        logger.info(f"Found {len(apps)} applications")

    def test_list_applications_has_required_fields(self, admin):
        """Test that applications have required fields."""
        rate_limiter.wait()
        response = admin.applications.list()

        assert response.success
        apps = response.data.get("applications", [])

        for app in apps:
            assert "id" in app
            assert "name" in app

    def test_get_application_by_name(self, admin):
        """Test getting application by name."""
        rate_limiter.wait()
        response = admin.applications.get_by_name("OAuth2-Proxy")

        assert response.success
        app = response.data.get("application", response.data)
        assert app is not None
        assert app.get("name") == "OAuth2-Proxy"

    def test_get_application_by_id(self, admin, oauth_app):
        """Test getting application by ID."""
        rate_limiter.wait()
        response = admin.applications.get(oauth_app["id"])

        assert response.success
        app = response.data.get("application", {})
        assert app["id"] == oauth_app["id"]
        assert app["name"] == "OAuth2-Proxy"

    def test_expected_applications_exist(self, admin, all_apps):
        """Test that expected applications exist."""
        app_names = [a["name"] for a in all_apps]

        expected = ["OAuth2-Proxy", "FusionAuth"]
        for name in expected:
            assert name in app_names, f"Expected application '{name}' not found"
            logger.info(f"✓ Found application: {name}")


# =============================================================================
# Role Listing Tests
# =============================================================================


@pytest.mark.integration
class TestRoleListing:
    """Tests for role listing functionality."""

    def test_list_roles_for_oauth_app(self, admin, oauth_app):
        """Test listing roles for OAuth2-Proxy."""
        rate_limiter.wait()
        response = admin.applications.get(oauth_app["id"])

        assert response.success
        app = response.data.get("application", {})
        roles = app.get("roles", [])

        assert isinstance(roles, list)
        assert len(roles) >= len(REQUIRED_OAUTH_ROLES)

        role_names = [r["name"] for r in roles]
        logger.info(f"OAuth2-Proxy roles: {role_names}")

    def test_oauth_roles_have_required_fields(self, admin, oauth_app):
        """Test that roles have required fields."""
        rate_limiter.wait()
        response = admin.applications.get(oauth_app["id"])

        assert response.success
        app = response.data.get("application", {})
        roles = app.get("roles", [])

        for role in roles:
            assert "id" in role
            assert "name" in role


# =============================================================================
# Registration Listing Tests
# =============================================================================


@pytest.mark.integration
class TestRegistrationListing:
    """Tests for registration listing functionality."""

    def test_get_admin_registrations(self, admin):
        """Test getting registrations for admin user."""
        rate_limiter.wait()
        admin_response = admin.users.get(email="admin@ml-platform.local")
        assert admin_response.success
        admin_user = admin_response.data.get("user", {})

        # Registrations are included in user data
        registrations = admin_user.get("registrations", [])

        assert isinstance(registrations, list)
        assert len(registrations) >= 1  # At least FusionAuth registration

        logger.info(f"Admin has {len(registrations)} registrations")
        for reg in registrations:
            logger.info(
                f"  App: {reg.get('applicationId')}, Roles: {reg.get('roles', [])}"
            )

    def test_get_specific_registration(self, admin, oauth_app):
        """Test getting a specific registration."""
        rate_limiter.wait()
        admin_response = admin.users.get(email="admin@ml-platform.local")
        assert admin_response.success
        admin_user = admin_response.data.get("user", {})

        rate_limiter.wait()
        response = admin.registrations.get(admin_user["id"], oauth_app["id"])

        # May or may not exist
        if response.success and response.data:
            reg = response.data.get("registration", {})
            assert reg.get("applicationId") == oauth_app["id"]
            logger.info(f"Admin OAuth2-Proxy roles: {reg.get('roles', [])}")
        else:
            logger.info("Admin not registered to OAuth2-Proxy")
