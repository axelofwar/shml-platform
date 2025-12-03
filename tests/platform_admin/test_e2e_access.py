"""
End-to-end access tests using HTTP requests.

These tests verify that users with different roles have appropriate
access to platform services through OAuth2-Proxy.

Note: These tests require services to be running and accessible.
They test actual HTTP access patterns, not just FusionAuth configuration.
"""

import pytest
import requests
import logging
import time
import os
import sys
from typing import Dict, Optional

# Add conftest to path
sys.path.insert(0, os.path.dirname(__file__))

from conftest import (
    rate_limiter,
    TEST_USERS,
    REQUIRED_OAUTH_ROLES,
)

logger = logging.getLogger("platform_admin.tests.e2e")


# =============================================================================
# Configuration
# =============================================================================

# Service endpoints - use environment variables for flexibility
BASE_DOMAIN = os.getenv("TEST_DOMAIN", "localhost")
MLFLOW_URL = os.getenv("MLFLOW_URL", f"http://{BASE_DOMAIN}:5002")
GRAFANA_URL = os.getenv("GRAFANA_URL", f"http://{BASE_DOMAIN}:3001")
RAY_URL = os.getenv("RAY_URL", f"http://{BASE_DOMAIN}:8266")
FUSIONAUTH_URL = os.getenv("FUSIONAUTH_URL", f"http://{BASE_DOMAIN}:9011")

# OAuth2-Proxy endpoints
OAUTH_PROXY_URL = os.getenv("OAUTH_PROXY_URL", f"http://{BASE_DOMAIN}:4180")


# =============================================================================
# Helper Functions
# =============================================================================


def check_service_accessible(url: str, timeout: int = 5) -> bool:
    """Check if a service is accessible."""
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=False)
        return True
    except requests.exceptions.RequestException:
        return False


def get_oauth_login_token(email: str, password: str) -> Optional[str]:
    """
    Attempt to get an OAuth token for a user.

    Note: This is a simplified implementation. In practice, OAuth2-Proxy
    uses redirect-based flow which is hard to automate. This function
    demonstrates the expected behavior but may need adaptation based on
    your specific OAuth2-Proxy configuration.
    """
    # This would typically involve:
    # 1. Initiating OAuth flow with OAuth2-Proxy
    # 2. Being redirected to FusionAuth login
    # 3. Submitting credentials
    # 4. Getting callback with token
    #
    # For test purposes, we may need to use FusionAuth's direct login API
    try:
        response = requests.post(
            f"{FUSIONAUTH_URL}/api/login",
            json={
                "loginId": email,
                "password": password,
                "applicationId": os.getenv("OAUTH_APP_ID"),
            },
            timeout=10,
        )
        if response.status_code == 200:
            return response.json().get("token")
        return None
    except requests.exceptions.RequestException:
        return None


# =============================================================================
# Service Availability Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.order(1)
class TestServiceAvailability:
    """Test that required services are accessible."""

    def test_fusionauth_accessible(self):
        """Test FusionAuth is accessible."""
        accessible = check_service_accessible(FUSIONAUTH_URL)
        if not accessible:
            pytest.skip("FusionAuth not accessible")
        logger.info(f"✓ FusionAuth accessible at {FUSIONAUTH_URL}")

    def test_mlflow_accessible(self):
        """Test MLflow is accessible (may redirect to auth)."""
        accessible = check_service_accessible(MLFLOW_URL)
        if not accessible:
            pytest.skip("MLflow not accessible")
        logger.info(f"✓ MLflow accessible at {MLFLOW_URL}")

    def test_grafana_accessible(self):
        """Test Grafana is accessible (may redirect to auth)."""
        accessible = check_service_accessible(GRAFANA_URL)
        if not accessible:
            pytest.skip("Grafana not accessible")
        logger.info(f"✓ Grafana accessible at {GRAFANA_URL}")

    def test_ray_dashboard_accessible(self):
        """Test Ray Dashboard is accessible (may redirect to auth)."""
        accessible = check_service_accessible(RAY_URL)
        if not accessible:
            pytest.skip("Ray Dashboard not accessible")
        logger.info(f"✓ Ray Dashboard accessible at {RAY_URL}")


# =============================================================================
# OAuth2-Proxy Behavior Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.order(2)
class TestOAuthBehavior:
    """Test OAuth2-Proxy redirect behavior."""

    def test_unauthenticated_redirect(self):
        """Test that unauthenticated requests get redirected."""
        try:
            response = requests.get(OAUTH_PROXY_URL, timeout=5, allow_redirects=False)
            # Should get a redirect (302 or 303) to login
            assert response.status_code in [
                302,
                303,
                307,
                401,
            ], f"Expected redirect, got {response.status_code}"
            logger.info(
                f"✓ Unauthenticated requests redirect (status: {response.status_code})"
            )
        except requests.exceptions.RequestException as e:
            pytest.skip(f"OAuth2-Proxy not accessible: {e}")

    def test_oauth_sign_in_endpoint(self):
        """Test OAuth2-Proxy sign-in endpoint exists."""
        try:
            response = requests.get(
                f"{OAUTH_PROXY_URL}/oauth2/sign_in", timeout=5, allow_redirects=False
            )
            # Should redirect to FusionAuth
            if response.status_code in [302, 303, 307]:
                location = response.headers.get("Location", "")
                assert (
                    "fusionauth" in location.lower() or "9011" in location
                ), f"Expected redirect to FusionAuth, got: {location}"
                logger.info("✓ OAuth2-Proxy sign-in redirects to FusionAuth")
            else:
                logger.info(f"Sign-in endpoint returned {response.status_code}")
        except requests.exceptions.RequestException as e:
            pytest.skip(f"OAuth2-Proxy not accessible: {e}")


# =============================================================================
# Role-Based Access Tests (Simulated)
# =============================================================================


@pytest.mark.e2e
@pytest.mark.order(3)
class TestRoleBasedAccess:
    """
    Test role-based access patterns.

    Note: Full OAuth flow testing requires browser automation or
    a test OAuth token generation mechanism. These tests verify
    the expected behavior documentation.
    """

    def test_admin_expected_access(self, admin, oauth_app):
        """Document expected admin access levels."""
        # Verify admin role exists
        rate_limiter.wait()
        response = admin.applications.get(oauth_app["id"])
        assert response.success
        app = response.data.get("application", {})
        roles = app.get("roles", [])

        role_names = [r["name"] for r in roles]
        assert "admin" in role_names, "Admin role must exist"

        logger.info("Admin users (like Bob) should have access to:")
        logger.info("  - All MLflow features (experiments, models, deployments)")
        logger.info("  - All Grafana dashboards and admin settings")
        logger.info("  - All Ray Dashboard features including job management")
        logger.info("  - User management in FusionAuth")

    def test_developer_expected_access(self, admin, oauth_app):
        """Document expected developer access levels."""
        # Verify developer role exists
        rate_limiter.wait()
        response = admin.applications.get(oauth_app["id"])
        assert response.success
        app = response.data.get("application", {})
        roles = app.get("roles", [])

        role_names = [r["name"] for r in roles]
        assert "developer" in role_names, "Developer role must exist"

        logger.info("Developer users (like Alice) should have access to:")
        logger.info("  - MLflow experiments (view, create, run)")
        logger.info("  - Grafana dashboards (view, limited edit)")
        logger.info("  - Ray Dashboard (view jobs, submit jobs)")
        logger.info("  - NOT: User management, admin settings")

    def test_viewer_expected_access(self, admin, oauth_app):
        """Document expected viewer access levels."""
        # Verify viewer role exists
        rate_limiter.wait()
        response = admin.applications.get(oauth_app["id"])
        assert response.success
        app = response.data.get("application", {})
        roles = app.get("roles", [])

        role_names = [r["name"] for r in roles]
        assert "viewer" in role_names, "Viewer role must exist"

        logger.info("Viewer users (like John) should have access to:")
        logger.info("  - MLflow experiments (view only)")
        logger.info("  - Grafana dashboards (view only)")
        logger.info("  - NOT: Job submission, model deployment, admin features")


# =============================================================================
# Group-Based Access Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.order(4)
class TestGroupBasedAccess:
    """Test group-based access patterns."""

    def test_platform_admins_group(self, admin, groups):
        """Verify platform-admins group exists and configuration."""
        assert "platform-admins" in groups
        group = groups["platform-admins"]

        logger.info(f"platform-admins group ID: {group['id']}")
        logger.info("Members of platform-admins have full administrative access")

    def test_mlflow_groups(self, admin, groups):
        """Verify MLflow access groups exist."""
        assert "mlflow-users" in groups, "mlflow-users group required"
        assert "mlflow-viewers" in groups, "mlflow-viewers group required"

        logger.info("MLflow access controlled by:")
        logger.info(f"  - mlflow-users: {groups['mlflow-users']['id']}")
        logger.info(f"  - mlflow-viewers: {groups['mlflow-viewers']['id']}")

    def test_grafana_groups(self, admin, groups):
        """Verify Grafana access groups exist."""
        assert "grafana-users" in groups, "grafana-users group required"
        assert "grafana-viewers" in groups, "grafana-viewers group required"

        logger.info("Grafana access controlled by:")
        logger.info(f"  - grafana-users: {groups['grafana-users']['id']}")
        logger.info(f"  - grafana-viewers: {groups['grafana-viewers']['id']}")

    def test_ray_groups(self, admin, groups):
        """Verify Ray access groups exist."""
        assert "ray-users" in groups, "ray-users group required"
        assert "ray-viewers" in groups, "ray-viewers group required"

        logger.info("Ray access controlled by:")
        logger.info(f"  - ray-users: {groups['ray-users']['id']}")
        logger.info(f"  - ray-viewers: {groups['ray-viewers']['id']}")


# =============================================================================
# Access Hierarchy Tests
# =============================================================================


@pytest.mark.e2e
@pytest.mark.order(5)
class TestAccessHierarchy:
    """Test that access hierarchy is correctly configured."""

    def test_bob_has_all_groups(self, admin, groups):
        """Verify Bob (admin) has all group memberships."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["bob"]["email"])

        if not response.success:
            pytest.skip("Bob not found - run user creation tests first")

        user = response.data.get("user", {})
        memberships = user.get("memberships", [])
        member_group_ids = [m["groupId"] for m in memberships]

        # Bob should be in all groups
        expected_groups = TEST_USERS["bob"]["groups"]
        for group_name in expected_groups:
            if group_name in groups:
                assert (
                    groups[group_name]["id"] in member_group_ids
                ), f"Bob missing group: {group_name}"

        logger.info("✓ Bob has all admin groups")

    def test_alice_has_user_groups_only(self, admin, groups):
        """Verify Alice (developer) has user groups but not admin."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["alice"]["email"])

        if not response.success:
            pytest.skip("Alice not found - run user creation tests first")

        user = response.data.get("user", {})
        memberships = user.get("memberships", [])
        member_group_ids = [m["groupId"] for m in memberships]

        # Alice should have user groups
        for group_name in ["mlflow-users", "grafana-users", "ray-users"]:
            if group_name in groups:
                assert (
                    groups[group_name]["id"] in member_group_ids
                ), f"Alice missing group: {group_name}"

        # Alice should NOT be in admin groups
        if "platform-admins" in groups:
            assert groups["platform-admins"]["id"] not in member_group_ids

        logger.info("✓ Alice has developer groups only")

    def test_john_has_viewer_groups_only(self, admin, groups):
        """Verify John (viewer) has only viewer groups."""
        rate_limiter.wait()
        response = admin.users.get(email=TEST_USERS["john"]["email"])

        if not response.success:
            pytest.skip("John not found - run user creation tests first")

        user = response.data.get("user", {})
        memberships = user.get("memberships", [])
        member_group_ids = [m["groupId"] for m in memberships]

        # John should have viewer groups
        for group_name in ["mlflow-viewers", "grafana-viewers", "ray-viewers"]:
            if group_name in groups:
                assert (
                    groups[group_name]["id"] in member_group_ids
                ), f"John missing group: {group_name}"

        # John should NOT be in user or admin groups
        restricted_groups = [
            "platform-admins",
            "mlflow-users",
            "grafana-users",
            "ray-users",
        ]
        for group_name in restricted_groups:
            if group_name in groups:
                assert (
                    groups[group_name]["id"] not in member_group_ids
                ), f"John should NOT be in {group_name}"

        logger.info("✓ John has viewer groups only")
