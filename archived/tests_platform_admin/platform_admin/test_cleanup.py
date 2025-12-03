"""
Cleanup tests - remove test users after all other tests complete.

These tests should run last and clean up all test resources.
"""

import pytest
import logging
import time
import sys
import os

# Add conftest to path
sys.path.insert(0, os.path.dirname(__file__))

from conftest import (
    rate_limiter,
    TEST_USERS,
    FusionAuthError,
)

logger = logging.getLogger("platform_admin.tests.cleanup")


# =============================================================================
# Test User Cleanup
# =============================================================================


@pytest.mark.cleanup
@pytest.mark.order(100)  # Run last
class TestUserCleanup:
    """Clean up test users created during testing."""

    def test_delete_bob_doe(self, admin, test_user_manager):
        """Delete Bob Doe test user."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["bob"]["email"])

        if not response.success:
            logger.info("Bob Doe not found - already deleted or never created")
            return

        user = response.data.get("user", {})
        user_id = user["id"]

        rate_limiter.wait()
        delete_response = admin.users.delete(user_id, hard_delete=True)

        assert delete_response.success, f"Failed to delete Bob: {delete_response.error}"

        # Verify deletion
        rate_limiter.wait()
        verify_response = admin.users.get(email=TEST_USERS["bob"]["email"])
        assert not verify_response.success or not verify_response.data.get(
            "user"
        ), "Bob still exists after deletion"

        logger.info(f"✓ Deleted Bob Doe: {user_id}")

    def test_delete_alice_doe(self, admin, test_user_manager):
        """Delete Alice Doe test user."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["alice"]["email"])

        if not response.success:
            logger.info("Alice Doe not found - already deleted or never created")
            return

        user = response.data.get("user", {})
        user_id = user["id"]

        rate_limiter.wait()
        delete_response = admin.users.delete(user_id, hard_delete=True)

        assert (
            delete_response.success
        ), f"Failed to delete Alice: {delete_response.error}"

        # Verify deletion
        rate_limiter.wait()
        verify_response = admin.users.get(email=TEST_USERS["alice"]["email"])
        assert not verify_response.success or not verify_response.data.get(
            "user"
        ), "Alice still exists after deletion"

        logger.info(f"✓ Deleted Alice Doe: {user_id}")

    def test_delete_john_doe(self, admin, test_user_manager):
        """Delete John Doe test user."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["john"]["email"])

        if not response.success:
            logger.info("John Doe not found - already deleted or never created")
            return

        user = response.data.get("user", {})
        user_id = user["id"]

        rate_limiter.wait()
        delete_response = admin.users.delete(user_id, hard_delete=True)

        assert (
            delete_response.success
        ), f"Failed to delete John: {delete_response.error}"

        # Verify deletion
        rate_limiter.wait()
        verify_response = admin.users.get(email=TEST_USERS["john"]["email"])
        assert not verify_response.success or not verify_response.data.get(
            "user"
        ), "John still exists after deletion"

        logger.info(f"✓ Deleted John Doe: {user_id}")


# =============================================================================
# Verification After Cleanup
# =============================================================================


@pytest.mark.cleanup
@pytest.mark.order(101)
class TestCleanupVerification:
    """Verify cleanup was successful."""

    def test_no_test_users_remain(self, admin):
        """Verify all test users have been deleted."""
        for name, config in TEST_USERS.items():
            rate_limiter.wait()
            response = admin.users.get(email=config["email"])

            if response.success and response.data.get("user"):
                pytest.fail(f"Test user {name} ({config['email']}) still exists!")

        logger.info("✓ All test users successfully removed")

    def test_search_no_test_domain(self, admin):
        """Verify no users with test domain remain."""
        rate_limiter.wait()
        response = admin.users.search("test.ml-platform.local")

        assert response.success
        users = response.data.get("users", [])

        test_emails = [
            u["email"] for u in users if "test.ml-platform.local" in u.get("email", "")
        ]

        if test_emails:
            logger.warning(f"Found remaining test users: {test_emails}")
            # Don't fail - there might be legitimate test users
        else:
            logger.info("✓ No test.ml-platform.local users found")


# =============================================================================
# Force Cleanup (can be run manually)
# =============================================================================


@pytest.mark.cleanup
@pytest.mark.manual
class TestForceCleanup:
    """Force cleanup of all test users - run manually if needed."""

    def test_force_delete_all_test_users(self, admin):
        """
        Force delete all users matching test patterns.

        WARNING: This will delete ANY user matching the test patterns!
        """
        deleted = []

        # Search for test users
        rate_limiter.wait()
        response = admin.users.search("test.ml-platform.local")

        if not response.success:
            logger.info("No test users found")
            return

        users = response.data.get("users", [])

        for user in users:
            if "test.ml-platform.local" in user.get("email", ""):
                rate_limiter.wait()
                delete_response = admin.users.delete(user["id"], hard_delete=True)

                if delete_response.success:
                    deleted.append(user["email"])
                    logger.info(f"  Deleted: {user['email']}")
                else:
                    logger.warning(
                        f"  Failed to delete: {user['email']}: {delete_response.error}"
                    )

        logger.info(f"✓ Force deleted {len(deleted)} test users")


# =============================================================================
# Final State Report
# =============================================================================


@pytest.mark.cleanup
@pytest.mark.order(102)
class TestFinalStateReport:
    """Generate final state report."""

    def test_user_count(self, admin):
        """Report final user count."""
        rate_limiter.wait()
        response = admin.users.list()

        assert response.success
        users = response.data.get("users", [])
        logger.info(f"Final user count: {len(users)}")

        for user in users[:5]:  # Show first 5
            logger.info(f"  - {user.get('email')}")

        if len(users) > 5:
            logger.info(f"  ... and {len(users) - 5} more")

    def test_group_count(self, admin):
        """Report final group count."""
        rate_limiter.wait()
        response = admin.groups.list()

        assert response.success
        groups = response.data.get("groups", [])
        logger.info(f"Final group count: {len(groups)}")

        for group in groups:
            logger.info(f"  - {group.get('name')}")

    def test_application_count(self, admin):
        """Report final application count."""
        rate_limiter.wait()
        response = admin.applications.list()

        assert response.success
        apps = response.data.get("applications", [])
        logger.info(f"Final application count: {len(apps)}")

        for app in apps:
            logger.info(f"  - {app.get('name')}")
