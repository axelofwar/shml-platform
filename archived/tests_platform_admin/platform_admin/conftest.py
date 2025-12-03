"""
Pytest configuration and fixtures for Platform Admin SDK tests.

Provides:
- Rate limiting utilities
- FusionAuth connection fixtures
- Test user management
- Cleanup handlers
"""

import os
import sys
import time
import logging
import pytest
from typing import Generator, Dict, Any, List, Optional
from functools import wraps

# Add scripts directory to path for platform_admin import
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts"
)
sys.path.insert(0, SCRIPTS_DIR)

from platform_admin import PlatformAdminClient, Config
from platform_admin.client import APIResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("platform_admin.tests")


# =============================================================================
# API Response Helpers
# =============================================================================


class FusionAuthError(Exception):
    """Exception wrapper for API errors."""

    def __init__(self, message: str, status_code: int = None, response: Dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


def check_response(
    response: APIResponse, operation: str = "operation"
) -> Dict[str, Any]:
    """
    Check API response and return data or raise error.

    Args:
        response: APIResponse from SDK
        operation: Description for error messages

    Returns:
        Response data dict

    Raises:
        FusionAuthError: If response indicates failure
    """
    if not response.success:
        raise FusionAuthError(
            f"{operation} failed: {response.error}",
            status_code=response.status_code,
            response=response.data,
        )
    return response.data or {}


def get_response_data(response: APIResponse, key: str = None) -> Any:
    """
    Extract data from API response.

    Args:
        response: APIResponse from SDK
        key: Optional key to extract from data

    Returns:
        Data or None if not successful
    """
    if not response.success or not response.data:
        return None
    if key:
        return response.data.get(key)
    return response.data


# =============================================================================
# Rate Limiting
# =============================================================================


class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, calls_per_second: float = 5.0):
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0.0

    def wait(self):
        """Wait if needed to respect rate limit."""
        now = time.time()
        elapsed = now - self.last_call
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.3f}s")
            time.sleep(sleep_time)
        self.last_call = time.time()


# Global rate limiter - 5 calls per second
rate_limiter = RateLimiter(calls_per_second=5.0)


def rate_limited(func):
    """Decorator to apply rate limiting to a function."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        rate_limiter.wait()
        return func(*args, **kwargs)

    return wrapper


# =============================================================================
# Test User Definitions
# =============================================================================

# Test passwords loaded from environment variable
# These are NOT real credentials - only used for test fixture creation
# Set TEST_USER_PASSWORD env var before running integration tests
_TEST_PASSWORD = os.environ.get("TEST_USER_PASSWORD", "changeme")

TEST_USERS = {
    "bob": {
        "email": "bob.doe.test@ml-platform.local",
        "password": _TEST_PASSWORD,
        "first_name": "Bob",
        "last_name": "Doe",
        "role": "admin",
        "oauth_roles": ["admin", "developer", "viewer"],
        "groups": ["platform-admins", "mlflow-users", "grafana-users", "ray-users"],
    },
    "alice": {
        "email": "alice.doe.test@ml-platform.local",
        "password": _TEST_PASSWORD,
        "first_name": "Alice",
        "last_name": "Doe",
        "role": "developer",
        "oauth_roles": ["developer", "viewer"],
        "groups": ["mlflow-users", "grafana-users", "ray-users"],
    },
    "john": {
        "email": "john.doe.test@ml-platform.local",
        "password": _TEST_PASSWORD,
        "first_name": "John",
        "last_name": "Doe",
        "role": "viewer",
        "oauth_roles": ["viewer"],
        "groups": ["mlflow-viewers", "grafana-viewers", "ray-viewers"],
    },
}


# =============================================================================
# Required Infrastructure
# =============================================================================

REQUIRED_OAUTH_ROLES = ["admin", "developer", "viewer"]

REQUIRED_GROUPS = [
    "platform-admins",
    "mlflow-users",
    "mlflow-viewers",
    "grafana-users",
    "grafana-viewers",
    "ray-users",
    "ray-viewers",
]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def config() -> Config:
    """Load configuration from .env file."""
    try:
        cfg = Config()
        if not cfg.validate():
            pytest.skip("Configuration invalid")
        logger.info(f"Loaded config: FusionAuth URL = {cfg.fusionauth_url}")
        return cfg
    except Exception as e:
        pytest.skip(f"Configuration not available: {e}")


@pytest.fixture(scope="session")
def admin(config: Config) -> PlatformAdminClient:
    """Create PlatformAdminClient instance with connection test."""
    try:
        admin_client = PlatformAdminClient(config)
        # Test connection
        response = admin_client.validate()
        if not response.success:
            pytest.skip(f"Cannot validate FusionAuth connection: {response.error}")
        logger.info("Successfully connected to FusionAuth")
        return admin_client
    except Exception as e:
        pytest.skip(f"Cannot connect to FusionAuth: {e}")


@pytest.fixture(scope="session")
def oauth_app(admin: PlatformAdminClient) -> Dict[str, Any]:
    """Get OAuth2-Proxy application, fail if not found."""
    rate_limiter.wait()
    response = admin.applications.get_by_name("OAuth2-Proxy")

    if not response.success or not response.data:
        pytest.fail(
            "OAuth2-Proxy application not found in FusionAuth. Please create it first."
        )

    app = response.data.get("application", response.data)
    logger.info(f"Found OAuth2-Proxy app: {app.get('id')}")
    return app


@pytest.fixture(scope="session")
def oauth_roles(
    admin: PlatformAdminClient, oauth_app: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Get OAuth2-Proxy roles, fail if required roles missing."""
    rate_limiter.wait()
    response = admin.applications.get(oauth_app["id"])

    if not response.success:
        pytest.fail(f"Cannot get OAuth2-Proxy application: {response.error}")

    app_data = response.data.get("application", response.data)
    roles = app_data.get("roles", [])
    role_names = [r["name"] for r in roles]

    missing = [r for r in REQUIRED_OAUTH_ROLES if r not in role_names]
    if missing:
        pytest.fail(
            f"Required OAuth2-Proxy roles missing: {missing}. Found: {role_names}"
        )

    logger.info(f"Found required OAuth roles: {role_names}")
    return roles


@pytest.fixture(scope="session")
def groups(admin: PlatformAdminClient) -> Dict[str, Dict[str, Any]]:
    """Get all groups, fail if required groups missing."""
    rate_limiter.wait()
    response = admin.groups.list()

    if not response.success:
        pytest.fail(f"Cannot list groups: {response.error}")

    all_groups = response.data.get("groups", [])
    group_map = {g["name"]: g for g in all_groups}

    missing = [g for g in REQUIRED_GROUPS if g not in group_map]
    if missing:
        pytest.fail(
            f"Required groups missing: {missing}. Found: {list(group_map.keys())}"
        )

    logger.info(f"Found {len(group_map)} groups including all required groups")
    return group_map


@pytest.fixture(scope="session")
def all_apps(admin: PlatformAdminClient) -> List[Dict[str, Any]]:
    """Get all applications."""
    rate_limiter.wait()
    response = admin.applications.list()

    if not response.success:
        pytest.skip(f"Cannot list applications: {response.error}")

    apps = response.data.get("applications", [])
    logger.info(f"Found {len(apps)} applications")
    return apps


# =============================================================================
# Test User Management Fixtures
# =============================================================================


class TestUserManager:
    """Manages test user lifecycle."""

    def __init__(self, admin: PlatformAdminClient, oauth_app: Dict, groups: Dict):
        self.admin = admin
        self.oauth_app = oauth_app
        self.groups = groups
        self.created_users: Dict[str, Dict[str, Any]] = {}

    def _get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email, return None if not found."""
        response = self.admin.users.get(email=email)
        if response.success and response.data:
            return response.data.get("user")
        return None

    def create_user(self, key: str) -> Dict[str, Any]:
        """Create a test user with proper roles and groups."""
        user_def = TEST_USERS[key]

        # Check if user already exists (from previous failed run)
        rate_limiter.wait()
        existing = self._get_user_by_email(user_def["email"])
        if existing:
            logger.warning(
                f"Test user {user_def['email']} already exists, cleaning up first"
            )
            self.delete_user(key, existing["id"])

        # Create user
        rate_limiter.wait()
        response = self.admin.users.create(
            email=user_def["email"],
            password=user_def["password"],
            first_name=user_def["first_name"],
            last_name=user_def["last_name"],
        )

        if not response.success:
            raise FusionAuthError(f"Failed to create user {key}: {response.error}")

        user = response.data.get("user", response.data)
        logger.info(f"Created test user: {user_def['email']} ({user['id']})")

        # Register to OAuth2-Proxy with roles
        rate_limiter.wait()
        reg_response = self.admin.registrations.create(
            user_id=user["id"],
            app_id=self.oauth_app["id"],
            roles=user_def["oauth_roles"],
        )

        if not reg_response.success:
            logger.error(f"Failed to register {key}: {reg_response.error}")
        else:
            logger.info(
                f"Registered {user_def['email']} with roles: {user_def['oauth_roles']}"
            )

        # Add to groups
        for group_name in user_def["groups"]:
            if group_name in self.groups:
                rate_limiter.wait()
                group_response = self.admin.groups.add_member(
                    self.groups[group_name]["id"], user["id"]
                )
                if group_response.success:
                    logger.info(f"Added {user_def['email']} to group: {group_name}")
                else:
                    logger.warning(
                        f"Failed to add to group {group_name}: {group_response.error}"
                    )
            else:
                logger.warning(f"Group {group_name} not found, skipping")

        self.created_users[key] = user
        return user

    def delete_user(self, key: str, user_id: str = None) -> bool:
        """Delete a test user."""
        user_def = TEST_USERS[key]
        uid = user_id or self.created_users.get(key, {}).get("id")

        if not uid:
            logger.warning(f"No user ID found for {key}")
            return False

        try:
            rate_limiter.wait()
            response = self.admin.users.delete(uid, hard_delete=True)

            if response.success:
                logger.info(f"Deleted test user: {user_def['email']} ({uid})")
                if key in self.created_users:
                    del self.created_users[key]
                return True
            else:
                logger.error(f"Failed to delete user {uid}: {response.error}")
                return False
        except Exception as e:
            logger.error(f"Exception deleting user {uid}: {e}")
            return False

    def cleanup_all(self):
        """Clean up all created test users."""
        logger.info("Cleaning up all test users...")
        for key in list(self.created_users.keys()):
            self.delete_user(key)

        # Also try to clean up by email in case of partial state
        for key, user_def in TEST_USERS.items():
            try:
                rate_limiter.wait()
                existing = self._get_user_by_email(user_def["email"])
                if existing:
                    logger.info(
                        f"Found orphaned test user {user_def['email']}, cleaning up"
                    )
                    rate_limiter.wait()
                    self.admin.users.delete(existing["id"], hard_delete=True)
            except Exception as e:
                logger.debug(f"Cleanup check for {user_def['email']}: {e}")


@pytest.fixture(scope="session")
def user_manager(
    admin: PlatformAdminClient, oauth_app: Dict, groups: Dict
) -> Generator[TestUserManager, None, None]:
    """Provide test user manager with cleanup."""
    manager = TestUserManager(admin, oauth_app, groups)
    yield manager
    # Cleanup after all tests
    manager.cleanup_all()


# Alias for backward compatibility with tests that use test_user_manager
@pytest.fixture(scope="session")
def test_user_manager(user_manager: TestUserManager) -> TestUserManager:
    """Alias for user_manager fixture."""
    return user_manager


@pytest.fixture(scope="module")
def test_users(user_manager: TestUserManager) -> Dict[str, Dict[str, Any]]:
    """Create all test users for integration tests."""
    users = {}
    for key in ["bob", "alice", "john"]:
        users[key] = user_manager.create_user(key)
    return users


# =============================================================================
# HTTP Session Fixtures for E2E Tests
# =============================================================================


@pytest.fixture(scope="session")
def base_url(config: Config) -> str:
    """Get the base URL for the platform."""
    # Try to get from environment or use default
    url = os.environ.get("PLATFORM_BASE_URL", "http://localhost")
    logger.info(f"Platform base URL: {url}")
    return url


@pytest.fixture(scope="session")
def public_domain() -> Optional[str]:
    """Get public domain if available (for Tailscale Funnel tests)."""
    domain = os.environ.get("PUBLIC_DOMAIN")
    if domain:
        logger.info(f"Public domain available: {domain}")
    else:
        logger.info("No public domain configured, skipping external access tests")
    return domain


# =============================================================================
# Markers
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (no external dependencies)")
    config.addinivalue_line(
        "markers", "integration: Integration tests (requires FusionAuth)"
    )
    config.addinivalue_line("markers", "e2e: End-to-end tests (requires full platform)")
    config.addinivalue_line("markers", "slow: Slow tests")
    config.addinivalue_line("markers", "cleanup: Cleanup tests (run last)")
    config.addinivalue_line("markers", "manual: Manual tests (skipped by default)")


# =============================================================================
# Hooks
# =============================================================================


def pytest_collection_modifyitems(config, items):
    """Add skip markers based on available infrastructure."""
    # Check if FusionAuth is available
    try:
        cfg = Config()
        if cfg.validate():
            admin = PlatformAdminClient(cfg)
            response = admin.validate()
            fusionauth_available = response.success
        else:
            fusionauth_available = False
    except Exception as e:
        logger.warning(f"FusionAuth check failed: {e}")
        fusionauth_available = False

    for item in items:
        # Skip integration tests if FusionAuth unavailable
        if "integration" in item.keywords and not fusionauth_available:
            item.add_marker(pytest.mark.skip(reason="FusionAuth not available"))

        # Skip E2E tests if platform not running
        if "e2e" in item.keywords:
            if not fusionauth_available:
                item.add_marker(
                    pytest.mark.skip(reason="Platform not available for E2E tests")
                )
