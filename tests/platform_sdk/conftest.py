"""
Pytest configuration for Platform SDK tests.

Provides fixtures for both unit and integration tests.
"""

import os
import pytest
import logging
from typing import Generator
from unittest.mock import MagicMock, AsyncMock

# Add scripts to path
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from platform_sdk import PlatformSDK, SDKConfig, Role, Permission
from platform_sdk.http import HTTPClient
from platform_sdk.permissions import PermissionContext
from platform_sdk.models import APIResponse


# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("platform_sdk.test")


# =============================================================================
# Environment Configuration
# =============================================================================


def get_test_api_key() -> str:
    """Get test API key from environment."""
    key = os.environ.get("FUSIONAUTH_API_KEY", "")
    if not key:
        pytest.skip("FUSIONAUTH_API_KEY environment variable not set")
    return key


def get_fusionauth_url() -> str:
    """Get FusionAuth URL from environment."""
    return os.environ.get("FUSIONAUTH_URL", "http://localhost:9011")


def is_fusionauth_available() -> bool:
    """Check if FusionAuth is accessible."""
    try:
        import httpx

        url = get_fusionauth_url()
        response = httpx.get(f"{url}/api/status", timeout=5.0)
        return response.status_code == 200
    except Exception:
        return False


def cleanup_test_resources(sdk: PlatformSDK) -> None:
    """
    Aggressively clean up all test resources from FusionAuth.

    This removes any users, groups, and applications created by tests.
    """
    logger.info("Starting aggressive test resource cleanup...")

    # Clean up test users (match various test patterns)
    test_patterns = ["*test*@example.com", "*cicd*@example.com", "*sdk*@example.com"]
    for pattern in test_patterns:
        try:
            response = sdk.users.search(query=pattern)
            if response.success:
                users = response.data.get("users", [])
                for user in users:
                    email = user.get("email", "")
                    user_id = user.get("id")
                    # Don't delete admin users
                    if "admin" not in email.lower() and user_id:
                        try:
                            sdk.users.delete(user_id, hard_delete=True)
                            logger.info(f"Cleaned up test user: {email}")
                        except Exception as e:
                            logger.warning(f"Failed to delete user {email}: {e}")
        except Exception as e:
            logger.warning(f"Failed to search for pattern {pattern}: {e}")

    # Clean up test groups
    try:
        response = sdk.groups.list()
        if response.success:
            groups = response.data.get("groups", [])
            for group in groups:
                name = group.get("name", "")
                group_id = group.get("id")
                if "test" in name.lower() and group_id:
                    try:
                        sdk.groups.delete(group_id)
                        logger.info(f"Cleaned up test group: {name}")
                    except Exception as e:
                        logger.warning(f"Failed to delete group {name}: {e}")
    except Exception as e:
        logger.warning(f"Failed to list groups for cleanup: {e}")

    # Clean up test applications
    try:
        response = sdk.applications.list()
        if response.success:
            apps = response.data.get("applications", [])
            for app in apps:
                name = app.get("name", "")
                app_id = app.get("id")
                if "test" in name.lower() and app_id:
                    try:
                        sdk.applications.delete(app_id, hard_delete=True)
                        logger.info(f"Cleaned up test application: {name}")
                    except Exception as e:
                        logger.warning(f"Failed to delete application {name}: {e}")
    except Exception as e:
        logger.warning(f"Failed to list applications for cleanup: {e}")

    logger.info("Test resource cleanup complete.")


# =============================================================================
# Session-Scoped Cleanup (runs at start and end of test session)
# =============================================================================


@pytest.fixture(scope="session", autouse=True)
def cleanup_before_and_after_tests():
    """
    Automatically clean up test resources before and after the entire test session.

    This ensures no orphaned test data remains from previous failed runs.
    """
    api_key = os.environ.get("FUSIONAUTH_API_KEY")
    if not api_key:
        yield  # Skip cleanup if no API key
        return

    try:
        sdk = PlatformSDK.for_admin(
            api_key=api_key,
            fusionauth_url=get_fusionauth_url(),
        )

        # Cleanup BEFORE tests run (remove orphans from previous runs)
        logger.info("=== PRE-TEST CLEANUP ===")
        cleanup_test_resources(sdk)

        yield  # Run all tests

        # Cleanup AFTER tests run (remove any stragglers)
        logger.info("=== POST-TEST CLEANUP ===")
        cleanup_test_resources(sdk)

        sdk.close()
    except Exception as e:
        logger.warning(f"Session cleanup failed: {e}")
        yield  # Still run tests even if cleanup fails


# =============================================================================
# Skip Markers
# =============================================================================

requires_fusionauth = pytest.mark.skipif(
    not is_fusionauth_available(), reason="FusionAuth not available"
)

requires_api_key = pytest.mark.skipif(
    not os.environ.get("FUSIONAUTH_API_KEY"), reason="FUSIONAUTH_API_KEY not set"
)


# =============================================================================
# Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_http_client():
    """Create a mock HTTP client for unit tests."""
    mock = MagicMock(spec=HTTPClient)

    # Default responses
    mock.get_sync.return_value = APIResponse.ok(data={"users": []})
    mock.post_sync.return_value = APIResponse.ok(data={"user": {"id": "test-id"}})
    mock.patch_sync.return_value = APIResponse.ok(data={"user": {"id": "test-id"}})
    mock.put_sync.return_value = APIResponse.ok(data={"user": {"id": "test-id"}})
    mock.delete_sync.return_value = APIResponse.ok()

    # Async versions
    mock.get = AsyncMock(return_value=APIResponse.ok(data={"users": []}))
    mock.post = AsyncMock(return_value=APIResponse.ok(data={"user": {"id": "test-id"}}))
    mock.patch = AsyncMock(
        return_value=APIResponse.ok(data={"user": {"id": "test-id"}})
    )
    mock.put = AsyncMock(return_value=APIResponse.ok(data={"user": {"id": "test-id"}}))
    mock.delete = AsyncMock(return_value=APIResponse.ok())

    return mock


@pytest.fixture
def admin_context():
    """Create admin permission context."""
    return PermissionContext(
        role=Role.ADMIN,
        permissions=set(Permission),
    )


@pytest.fixture
def developer_context():
    """Create developer permission context."""
    from platform_sdk.models import ROLE_PERMISSIONS

    return PermissionContext(
        role=Role.DEVELOPER,
        permissions=ROLE_PERMISSIONS[Role.DEVELOPER],
    )


@pytest.fixture
def viewer_context():
    """Create viewer permission context."""
    from platform_sdk.models import ROLE_PERMISSIONS

    return PermissionContext(
        role=Role.VIEWER,
        permissions=ROLE_PERMISSIONS[Role.VIEWER],
    )


@pytest.fixture
def mock_config():
    """Create a mock SDK config."""
    return SDKConfig(
        api_key="test-api-key-12345",
        fusionauth_url="http://localhost:9011",
        timeout=10.0,
    )


# =============================================================================
# Service Fixtures (with mocked HTTP)
# =============================================================================


@pytest.fixture
def users_service(mock_http_client, admin_context):
    """Create UsersService with mocked HTTP client."""
    from platform_sdk.services import UsersService

    return UsersService(
        http_client=mock_http_client,
        permission_context=admin_context,
    )


@pytest.fixture
def groups_service(mock_http_client, admin_context):
    """Create GroupsService with mocked HTTP client."""
    from platform_sdk.services import GroupsService

    return GroupsService(
        http_client=mock_http_client,
        permission_context=admin_context,
    )


@pytest.fixture
def applications_service(mock_http_client, admin_context):
    """Create ApplicationsService with mocked HTTP client."""
    from platform_sdk.services import ApplicationsService

    return ApplicationsService(
        http_client=mock_http_client,
        permission_context=admin_context,
    )


@pytest.fixture
def registrations_service(mock_http_client, admin_context):
    """Create RegistrationsService with mocked HTTP client."""
    from platform_sdk.services import RegistrationsService

    return RegistrationsService(
        http_client=mock_http_client,
        permission_context=admin_context,
    )


@pytest.fixture
def api_keys_service(mock_http_client, admin_context):
    """Create APIKeysService with mocked HTTP client."""
    from platform_sdk.services import APIKeysService

    return APIKeysService(
        http_client=mock_http_client,
        permission_context=admin_context,
    )


# =============================================================================
# Integration Test Fixtures
# =============================================================================


@pytest.fixture
def sdk_config():
    """Create real SDK config for integration tests."""
    return SDKConfig(
        api_key=get_test_api_key(),
        fusionauth_url=get_fusionauth_url(),
    )


@pytest.fixture
def admin_sdk():
    """Create SDK with admin privileges for integration tests."""
    try:
        sdk = PlatformSDK(
            api_key=get_test_api_key(),
            fusionauth_url=get_fusionauth_url(),
            role_override=Role.ADMIN,
        )
        yield sdk
        sdk.close()
    except Exception as e:
        pytest.skip(f"Could not create admin SDK: {e}")


@pytest.fixture
def developer_sdk():
    """Create SDK with developer privileges for integration tests."""
    try:
        sdk = PlatformSDK(
            api_key=get_test_api_key(),
            fusionauth_url=get_fusionauth_url(),
            role_override=Role.DEVELOPER,
        )
        yield sdk
        sdk.close()
    except Exception as e:
        pytest.skip(f"Could not create developer SDK: {e}")


@pytest.fixture
def viewer_sdk():
    """Create SDK with viewer privileges for integration tests."""
    try:
        sdk = PlatformSDK(
            api_key=get_test_api_key(),
            fusionauth_url=get_fusionauth_url(),
            role_override=Role.VIEWER,
        )
        yield sdk
        sdk.close()
    except Exception as e:
        pytest.skip(f"Could not create viewer SDK: {e}")


# =============================================================================
# Test Data Fixtures
# =============================================================================


@pytest.fixture
def test_user_data():
    """Sample user data for tests."""
    import uuid

    unique_id = str(uuid.uuid4())[:8]
    return {
        "email": f"test-user-{unique_id}@example.com",
        "password": "SecurePassword123!",
        "firstName": "Test",
        "lastName": "User",
    }


@pytest.fixture
def test_group_data():
    """Sample group data for tests."""
    import uuid

    unique_id = str(uuid.uuid4())[:8]
    return {
        "name": f"Test Group {unique_id}",
        "description": "A test group for SDK testing",
    }


@pytest.fixture
def test_application_data():
    """Sample application data for tests."""
    import uuid

    unique_id = str(uuid.uuid4())[:8]
    return {
        "name": f"Test App {unique_id}",
        "roles": [
            {"name": "user", "description": "Standard user"},
            {"name": "admin", "description": "Application admin"},
        ],
    }


# =============================================================================
# Cleanup Fixtures
# =============================================================================


@pytest.fixture
def cleanup_users(admin_sdk):
    """Track created users for cleanup."""
    created_user_ids = []

    yield created_user_ids

    # Cleanup after test
    for user_id in created_user_ids:
        try:
            admin_sdk.users.delete(user_id, hard_delete=True)
        except Exception as e:
            logger.warning(f"Failed to cleanup user {user_id}: {e}")


@pytest.fixture
def cleanup_groups(admin_sdk):
    """Track created groups for cleanup."""
    created_group_ids = []

    yield created_group_ids

    # Cleanup after test
    for group_id in created_group_ids:
        try:
            admin_sdk.groups.delete(group_id)
        except Exception as e:
            logger.warning(f"Failed to cleanup group {group_id}: {e}")


@pytest.fixture
def cleanup_applications(admin_sdk):
    """Track created applications for cleanup."""
    created_app_ids = []

    yield created_app_ids

    # Cleanup after test
    for app_id in created_app_ids:
        try:
            admin_sdk.applications.delete(app_id, hard_delete=True)
        except Exception as e:
            logger.warning(f"Failed to cleanup application {app_id}: {e}")
