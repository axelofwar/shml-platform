"""
Integration tests for user lifecycle - create, update, verify, delete.

These tests create test users with specific roles:
- Bob Doe: Platform Admin (admin role, platform-admins group, all service groups)
- Alice Doe: Developer (developer role, service user groups)
- John Doe: Viewer (viewer role, viewer groups only)
"""

import pytest
import logging
import sys
import os
from typing import Dict, Any

# Add conftest to path
sys.path.insert(0, os.path.dirname(__file__))

from conftest import (
    rate_limiter,
    FusionAuthError,
    TEST_USERS,
    REQUIRED_OAUTH_ROLES,
    REQUIRED_GROUPS,
    check_response,
)

logger = logging.getLogger("platform_admin.tests.users")


# =============================================================================
# User Creation Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.order(1)
class TestUserCreation:
    """Tests for creating test users."""

    def test_create_bob_doe_admin(self, admin, oauth_app, groups, test_user_manager):
        """Create Bob Doe as platform admin."""
        # TestUserManager.create_user() handles registration and group membership
        user = test_user_manager.create_user("bob")
        assert user is not None
        assert user["email"] == TEST_USERS["bob"]["email"]
        logger.info(f"✓ Created Bob Doe: {user['id']}")

    def test_create_alice_doe_developer(
        self, admin, oauth_app, groups, test_user_manager
    ):
        """Create Alice Doe as developer."""
        user = test_user_manager.create_user("alice")
        assert user is not None
        assert user["email"] == TEST_USERS["alice"]["email"]
        logger.info(f"✓ Created Alice Doe: {user['id']}")

    def test_create_john_doe_viewer(self, admin, oauth_app, groups, test_user_manager):
        """Create John Doe as viewer."""
        user = test_user_manager.create_user("john")
        assert user is not None
        assert user["email"] == TEST_USERS["john"]["email"]
        logger.info(f"✓ Created John Doe: {user['id']}")


# =============================================================================
# User Verification Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.order(2)
class TestUserVerification:
    """Verify test users were created correctly."""

    def test_verify_bob_exists(self, admin, test_user_manager):
        """Verify Bob Doe exists and has correct data."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["bob"]["email"])

        assert response.success, f"Bob not found: {response.error}"
        user = response.data.get("user", {})

        assert user.get("firstName") == "Bob"
        assert user.get("lastName") == "Doe"
        assert user.get("email") == TEST_USERS["bob"]["email"]
        logger.info(f"✓ Bob Doe verified: {user['id']}")

    def test_verify_alice_exists(self, admin, test_user_manager):
        """Verify Alice Doe exists and has correct data."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["alice"]["email"])

        assert response.success, f"Alice not found: {response.error}"
        user = response.data.get("user", {})

        assert user.get("firstName") == "Alice"
        assert user.get("lastName") == "Doe"
        assert user.get("email") == TEST_USERS["alice"]["email"]
        logger.info(f"✓ Alice Doe verified: {user['id']}")

    def test_verify_john_exists(self, admin, test_user_manager):
        """Verify John Doe exists and has correct data."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["john"]["email"])

        assert response.success, f"John not found: {response.error}"
        user = response.data.get("user", {})

        assert user.get("firstName") == "John"
        assert user.get("lastName") == "Doe"
        assert user.get("email") == TEST_USERS["john"]["email"]
        logger.info(f"✓ John Doe verified: {user['id']}")


# =============================================================================
# Group Membership Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.order(3)
class TestGroupMemberships:
    """Verify users have correct group memberships."""

    def test_bob_group_memberships(self, admin, groups, test_user_manager):
        """Verify Bob has all admin groups."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["bob"]["email"])
        assert response.success, f"Could not find Bob: {response.error}"
        user = response.data.get("user", {})

        user_groups = user.get("memberships", [])
        user_group_ids = [m["groupId"] for m in user_groups]

        expected_groups = TEST_USERS["bob"]["groups"]
        for group_name in expected_groups:
            if group_name in groups:
                expected_id = groups[group_name]["id"]
                assert expected_id in user_group_ids, f"Bob missing group: {group_name}"
                logger.info(f"  ✓ Bob in group: {group_name}")

    def test_alice_group_memberships(self, admin, groups, test_user_manager):
        """Verify Alice has developer groups."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["alice"]["email"])
        assert response.success, f"Could not find Alice: {response.error}"
        user = response.data.get("user", {})

        user_groups = user.get("memberships", [])
        user_group_ids = [m["groupId"] for m in user_groups]

        expected_groups = TEST_USERS["alice"]["groups"]
        for group_name in expected_groups:
            if group_name in groups:
                expected_id = groups[group_name]["id"]
                assert (
                    expected_id in user_group_ids
                ), f"Alice missing group: {group_name}"
                logger.info(f"  ✓ Alice in group: {group_name}")

        # Alice should NOT be in platform-admins
        if "platform-admins" in groups:
            assert (
                groups["platform-admins"]["id"] not in user_group_ids
            ), "Alice should NOT be in platform-admins"
            logger.info("  ✓ Alice correctly NOT in platform-admins")

    def test_john_group_memberships(self, admin, groups, test_user_manager):
        """Verify John has only viewer groups."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["john"]["email"])
        assert response.success, f"Could not find John: {response.error}"
        user = response.data.get("user", {})

        user_groups = user.get("memberships", [])
        user_group_ids = [m["groupId"] for m in user_groups]

        expected_groups = TEST_USERS["john"]["groups"]
        for group_name in expected_groups:
            if group_name in groups:
                expected_id = groups[group_name]["id"]
                assert (
                    expected_id in user_group_ids
                ), f"John missing group: {group_name}"
                logger.info(f"  ✓ John in group: {group_name}")

        # John should NOT be in user groups (only viewers)
        user_groups_to_check = ["mlflow-users", "ray-users", "grafana-users"]
        for group_name in user_groups_to_check:
            if group_name in groups:
                assert (
                    groups[group_name]["id"] not in user_group_ids
                ), f"John should NOT be in {group_name}"
        logger.info("  ✓ John correctly NOT in user groups")


# =============================================================================
# Role Assignment Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.order(4)
class TestRoleAssignments:
    """Verify users have correct OAuth2-Proxy roles."""

    def test_bob_has_admin_role(self, admin, oauth_app, test_user_manager):
        """Verify Bob has admin role."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["bob"]["email"])
        assert response.success, f"Could not find Bob: {response.error}"
        user = response.data.get("user", {})

        registrations = user.get("registrations", [])
        oauth_reg = next(
            (r for r in registrations if r["applicationId"] == oauth_app["id"]), None
        )

        assert oauth_reg is not None, "Bob not registered to OAuth2-Proxy"
        roles = oauth_reg.get("roles", [])
        assert "admin" in roles, f"Bob missing admin role. Has: {roles}"
        logger.info(f"✓ Bob has admin role: {roles}")

    def test_alice_has_developer_role(self, admin, oauth_app, test_user_manager):
        """Verify Alice has developer role but not admin."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["alice"]["email"])
        assert response.success, f"Could not find Alice: {response.error}"
        user = response.data.get("user", {})

        registrations = user.get("registrations", [])
        oauth_reg = next(
            (r for r in registrations if r["applicationId"] == oauth_app["id"]), None
        )

        assert oauth_reg is not None, "Alice not registered to OAuth2-Proxy"
        roles = oauth_reg.get("roles", [])
        assert "developer" in roles, f"Alice missing developer role. Has: {roles}"
        assert "admin" not in roles, f"Alice should NOT have admin role. Has: {roles}"
        logger.info(f"✓ Alice has developer role (not admin): {roles}")

    def test_john_has_viewer_role(self, admin, oauth_app, test_user_manager):
        """Verify John has only viewer role."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["john"]["email"])
        assert response.success, f"Could not find John: {response.error}"
        user = response.data.get("user", {})

        registrations = user.get("registrations", [])
        oauth_reg = next(
            (r for r in registrations if r["applicationId"] == oauth_app["id"]), None
        )

        assert oauth_reg is not None, "John not registered to OAuth2-Proxy"
        roles = oauth_reg.get("roles", [])
        assert "viewer" in roles, f"John missing viewer role. Has: {roles}"
        assert "admin" not in roles, f"John should NOT have admin role. Has: {roles}"
        assert (
            "developer" not in roles
        ), f"John should NOT have developer role. Has: {roles}"
        logger.info(f"✓ John has viewer role only: {roles}")


# =============================================================================
# User Update Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.order(5)
class TestUserUpdates:
    """Test updating user information."""

    def test_update_bob_mobile_phone(self, admin, test_user_manager):
        """Test updating Bob's mobile phone."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["bob"]["email"])
        assert response.success, f"Could not find Bob: {response.error}"
        user = response.data.get("user", {})

        rate_limiter.wait()
        update_response = admin.users.update(user["id"], mobile_phone="+1-555-123-4567")

        assert update_response.success, f"Failed to update Bob: {update_response.error}"

        # Verify update
        rate_limiter.wait()
        verify_response = admin.users.get(user_id=user["id"])
        assert verify_response.success
        updated_user = verify_response.data.get("user", {})
        assert updated_user.get("mobilePhone") == "+1-555-123-4567"
        logger.info("✓ Bob's mobile phone updated")

    def test_update_alice_full_name(self, admin, test_user_manager):
        """Test updating Alice's full name."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["alice"]["email"])
        assert response.success, f"Could not find Alice: {response.error}"
        user = response.data.get("user", {})

        rate_limiter.wait()
        update_response = admin.users.update(user["id"], full_name="Alice Marie Doe")

        assert (
            update_response.success
        ), f"Failed to update Alice: {update_response.error}"

        # Verify update
        rate_limiter.wait()
        verify_response = admin.users.get(user_id=user["id"])
        assert verify_response.success
        updated_user = verify_response.data.get("user", {})
        assert updated_user.get("fullName") == "Alice Marie Doe"
        logger.info("✓ Alice's full name updated")


# =============================================================================
# Search and Filter Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.order(6)
class TestSearchAndFilter:
    """Test search and filter functionality with test users."""

    def test_search_doe_family(self, admin, test_user_manager):
        """Search for all Doe family members."""
        rate_limiter.wait()
        response = admin.users.search("Doe")

        assert response.success, f"Search failed: {response.error}"
        users = response.data.get("users", [])

        # Should find Bob, Alice, and John
        emails = [u.get("email", "") for u in users]
        test_emails = [
            TEST_USERS["bob"]["email"],
            TEST_USERS["alice"]["email"],
            TEST_USERS["john"]["email"],
        ]

        found_count = sum(1 for e in test_emails if e in emails)
        assert (
            found_count >= 3
        ), f"Expected at least 3 Doe users, found {found_count}. Emails: {emails}"
        logger.info(f"✓ Found {found_count} Doe family members")

    def test_search_by_first_name(self, admin, test_user_manager):
        """Search for users by first name."""
        rate_limiter.wait()
        response = admin.users.search("Bob")

        assert response.success, f"Search failed: {response.error}"
        users = response.data.get("users", [])

        # Should find Bob
        emails = [u.get("email", "") for u in users]
        assert TEST_USERS["bob"]["email"] in emails, f"Bob not found. Emails: {emails}"
        logger.info("✓ Found Bob by first name")

    def test_search_by_partial_email(self, admin, test_user_manager):
        """Search for users by partial email."""
        rate_limiter.wait()
        # Search for test user domain
        response = admin.users.search("doe.test")

        assert response.success, f"Search failed: {response.error}"
        users = response.data.get("users", [])

        # Should find test users
        assert len(users) >= 3, f"Expected at least 3 users, found {len(users)}"
        logger.info(f"✓ Found {len(users)} users by email pattern")
