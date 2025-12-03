"""
Platform Admin SDK for FusionAuth management.

This package provides a modular SDK and CLI for managing users, groups,
applications, and roles in FusionAuth.

Usage as SDK:
    from platform_admin import PlatformAdminClient, Config

    # Load config from environment
    client = PlatformAdminClient()

    # Or with explicit config
    config = Config(fusionauth_url="http://localhost:9011", api_key="your-api-key")
    client = PlatformAdminClient(config)

    # List all users
    response = client.users.list()
    if response.success:
        for user in response.data.get("users", []):
            print(user["email"])

    # Create a user
    response = client.users.create(
        email="user@example.com",
        password="SecurePass123!",
        first_name="John",
        last_name="Doe"
    )

    # Add user to a group
    response = client.groups.add_member(group_id, user_id)

Usage as CLI:
    python -m platform_admin              # Interactive mode
    python -m platform_admin user list    # Direct command
    python -m platform_admin --help       # Help
"""

__version__ = "0.1.0"
__author__ = "ML Platform Team"

from .config import Config
from .client import PlatformAdminClient, APIResponse, FusionAuthClient, FusionAuthError
from .services import (
    UsersService,
    GroupsService,
    ApplicationsService,
    RolesService,
    RegistrationsService,
)


# Backwards compatibility alias
PlatformAdmin = PlatformAdminClient


__all__ = [
    # Main client
    "PlatformAdminClient",
    "PlatformAdmin",  # Alias
    # Configuration
    "Config",
    # Low-level client and response types
    "FusionAuthClient",
    "APIResponse",
    "FusionAuthError",
    # Services
    "UsersService",
    "GroupsService",
    "ApplicationsService",
    "RolesService",
    "RegistrationsService",
]
