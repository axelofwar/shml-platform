"""
Platform SDK Client - Main entry point for SDK operations.

Provides unified access to all platform services with automatic
permission detection and enforcement.
"""

import logging
from typing import Optional, Dict, Any, Set

from .config import SDKConfig
from .exceptions import (
    AuthenticationError,
    PermissionDeniedError,
    PlatformSDKError,
)
from .http import HTTPClient
from .models import Permission, Role, APIResponse
from .permissions import PermissionContext
from .services import (
    UsersService,
    GroupsService,
    ApplicationsService,
    RegistrationsService,
    APIKeysService,
)


logger = logging.getLogger("platform_sdk")


class PlatformSDK:
    """
    Main SDK client for accessing platform services.

    Automatically detects API key permissions and enforces
    role-based access control on all operations.

    Usage:
        # Basic initialization
        sdk = PlatformSDK(api_key="your-api-key")

        # From environment
        sdk = PlatformSDK.from_env()

        # With custom config
        config = SDKConfig(
            fusionauth_url="http://localhost:9011",
            api_key="your-key",
        )
        sdk = PlatformSDK(config=config)

    Services:
        sdk.users         - User management
        sdk.groups        - Group management
        sdk.applications  - Application management
        sdk.registrations - User-app registrations
        sdk.api_keys      - API key management
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        fusionauth_url: Optional[str] = None,
        config: Optional[SDKConfig] = None,
        auto_introspect: bool = True,
        role_override: Optional[Role] = None,
    ):
        """
        Initialize the Platform SDK.

        Args:
            api_key: FusionAuth API key
            fusionauth_url: FusionAuth server URL
            config: Full SDK configuration
            auto_introspect: Auto-detect permissions from API key
            role_override: Force a specific role (for testing)
        """
        # Load configuration
        if config:
            self._config = config
        else:
            self._config = SDKConfig.from_env()
            if api_key:
                self._config.api_key = api_key
            if fusionauth_url:
                self._config.fusionauth_url = fusionauth_url

        # Validate we have an API key
        if not self._config.api_key:
            raise AuthenticationError("API key is required")

        # Initialize HTTP client with config
        self._http = HTTPClient(self._config)

        # Permission context (will be populated by introspection)
        self._permissions: Set[Permission] = set()
        self._role: Role = Role.VIEWER  # Default to lowest privilege
        self._api_key_id: Optional[str] = None
        self._api_key_metadata: Dict[str, Any] = {}

        # Role override for testing
        if role_override:
            self._role = role_override
            self._permissions = self._get_permissions_for_role(role_override)
            auto_introspect = False

        # Create permission context
        self._permission_context = PermissionContext(
            permissions=self._permissions,
            role=self._role,
        )

        # Auto-detect permissions
        if auto_introspect:
            self._introspect_api_key()

        # Initialize services (lazy loading)
        self._users: Optional[UsersService] = None
        self._groups: Optional[GroupsService] = None
        self._applications: Optional[ApplicationsService] = None
        self._registrations: Optional[RegistrationsService] = None
        self._api_keys: Optional[APIKeysService] = None

        logger.info(f"PlatformSDK initialized with role: {self._role.value}")

    @classmethod
    def from_env(cls) -> "PlatformSDK":
        """
        Create SDK instance from environment variables.

        Environment variables:
            FUSIONAUTH_API_KEY - API key
            FUSIONAUTH_URL - Server URL (default: http://localhost:9011)
            SDK_TIMEOUT - Request timeout in seconds
            SDK_LOG_LEVEL - Logging level

        Returns:
            PlatformSDK instance
        """
        config = SDKConfig.from_env()
        return cls(config=config)

    @classmethod
    def for_admin(
        cls,
        api_key: str,
        fusionauth_url: str = "http://localhost:9011",
    ) -> "PlatformSDK":
        """
        Create SDK instance with admin role.

        Use only when you know the API key has admin permissions.

        Args:
            api_key: Admin API key
            fusionauth_url: Server URL

        Returns:
            PlatformSDK with admin permissions
        """
        return cls(
            api_key=api_key,
            fusionauth_url=fusionauth_url,
            role_override=Role.ADMIN,
        )

    @classmethod
    def for_developer(
        cls,
        api_key: str,
        fusionauth_url: str = "http://localhost:9011",
    ) -> "PlatformSDK":
        """
        Create SDK instance with developer role.

        Args:
            api_key: Developer API key
            fusionauth_url: Server URL

        Returns:
            PlatformSDK with developer permissions
        """
        return cls(
            api_key=api_key,
            fusionauth_url=fusionauth_url,
            role_override=Role.DEVELOPER,
        )

    @classmethod
    def for_viewer(
        cls,
        api_key: str,
        fusionauth_url: str = "http://localhost:9011",
    ) -> "PlatformSDK":
        """
        Create SDK instance with viewer role.

        Args:
            api_key: Viewer API key
            fusionauth_url: Server URL

        Returns:
            PlatformSDK with viewer permissions
        """
        return cls(
            api_key=api_key,
            fusionauth_url=fusionauth_url,
            role_override=Role.VIEWER,
        )

    def _introspect_api_key(self) -> None:
        """
        Introspect the API key to determine permissions.

        Queries FusionAuth to get the key's permission configuration
        and maps it to SDK permissions.
        """
        try:
            response = self._http.get_sync("/api/api-key")

            if not response.success:
                logger.warning(f"Failed to introspect API key: {response.error}")
                # Default to viewer on failure
                self._role = Role.VIEWER
                self._permissions = self._get_permissions_for_role(Role.VIEWER)
                return

            api_keys = response.data.get("apiKeys", [])

            # Find the key matching ours (we can't see the actual key value,
            # but we can check for super keys and metadata)
            for key in api_keys:
                permissions = key.get("permissions", {})
                endpoints = permissions.get("endpoints", {})
                meta_data = key.get("metaData", {})

                # Check metadata for role hint
                role_hint = meta_data.get("role", "").lower()

                if role_hint == "admin" or len(endpoints) == 0:
                    # Super key or explicitly admin
                    self._role = Role.ADMIN
                    self._api_key_id = key.get("id")
                    self._api_key_metadata = meta_data
                    break
                elif role_hint == "developer":
                    self._role = Role.DEVELOPER
                    self._api_key_id = key.get("id")
                    self._api_key_metadata = meta_data
                elif role_hint == "viewer":
                    self._role = Role.VIEWER
                    self._api_key_id = key.get("id")
                    self._api_key_metadata = meta_data

            # If we couldn't determine from metadata, analyze endpoints
            if self._role == Role.VIEWER and not self._api_key_id:
                # Check if we have write access (POST/PUT/DELETE to user/group)
                for key in api_keys:
                    permissions = key.get("permissions", {})
                    endpoints = permissions.get("endpoints", {})

                    has_write = any(
                        method in ["POST", "PUT", "DELETE", "PATCH"]
                        for methods in endpoints.values()
                        for method in (methods if isinstance(methods, list) else [])
                    )

                    if not endpoints:
                        # Super key
                        self._role = Role.ADMIN
                        self._api_key_id = key.get("id")
                        break
                    elif has_write:
                        self._role = Role.DEVELOPER
                        self._api_key_id = key.get("id")
                        break

            # Set permissions based on determined role
            self._permissions = self._get_permissions_for_role(self._role)

            # Update permission context
            self._permission_context = PermissionContext(
                permissions=self._permissions,
                role=self._role,
            )

            logger.info(f"Introspected API key, detected role: {self._role.value}")

        except Exception as e:
            logger.error(f"Error introspecting API key: {e}")
            # Default to most restrictive on error
            self._role = Role.VIEWER
            self._permissions = self._get_permissions_for_role(Role.VIEWER)

    def _get_permissions_for_role(self, role: Role) -> Set[Permission]:
        """
        Get the set of permissions for a role.

        Args:
            role: The role

        Returns:
            Set of Permission values
        """
        if role == Role.ADMIN:
            # Admin gets all permissions
            return set(Permission)

        elif role == Role.DEVELOPER:
            # Developer: read all + limited write
            return {
                # Users
                Permission.USERS_READ,
                # Groups
                Permission.GROUPS_READ,
                # Applications
                Permission.APPLICATIONS_READ,
                # Registrations - developers can register users
                Permission.REGISTRATIONS_READ,
                Permission.REGISTRATIONS_CREATE,
                # API keys - read only
                Permission.API_KEYS_READ,
            }

        elif role == Role.VIEWER:
            # Viewer: read only
            return {
                Permission.USERS_READ,
                Permission.GROUPS_READ,
                Permission.APPLICATIONS_READ,
                Permission.REGISTRATIONS_READ,
            }

        elif role == Role.SERVICE_ACCOUNT:
            # Service accounts get specific permissions based on their purpose
            # Default to developer-level for now
            return self._get_permissions_for_role(Role.DEVELOPER)

        return set()

    # =========================================================================
    # Service Properties (Lazy Loading)
    # =========================================================================

    @property
    def users(self) -> UsersService:
        """Get the Users service."""
        if self._users is None:
            self._users = UsersService(
                http_client=self._http,
                permission_context=self._permission_context,
            )
        return self._users

    @property
    def groups(self) -> GroupsService:
        """Get the Groups service."""
        if self._groups is None:
            self._groups = GroupsService(
                http_client=self._http,
                permission_context=self._permission_context,
            )
        return self._groups

    @property
    def applications(self) -> ApplicationsService:
        """Get the Applications service."""
        if self._applications is None:
            self._applications = ApplicationsService(
                http_client=self._http,
                permission_context=self._permission_context,
            )
        return self._applications

    @property
    def registrations(self) -> RegistrationsService:
        """Get the Registrations service."""
        if self._registrations is None:
            self._registrations = RegistrationsService(
                http_client=self._http,
                permission_context=self._permission_context,
            )
        return self._registrations

    @property
    def api_keys(self) -> APIKeysService:
        """Get the API Keys service."""
        if self._api_keys is None:
            self._api_keys = APIKeysService(
                http_client=self._http,
                permission_context=self._permission_context,
            )
        return self._api_keys

    # =========================================================================
    # SDK Info & Utilities
    # =========================================================================

    @property
    def role(self) -> Role:
        """Get the current role."""
        return self._role

    @property
    def permissions(self) -> Set[Permission]:
        """Get the current permissions."""
        return self._permissions.copy()

    @property
    def config(self) -> SDKConfig:
        """Get the SDK configuration."""
        return self._config

    def has_permission(self, permission: Permission) -> bool:
        """
        Check if SDK has a specific permission.

        Args:
            permission: Permission to check

        Returns:
            True if permission is granted
        """
        return permission in self._permissions

    def can(self, *permissions: Permission) -> bool:
        """
        Check if SDK has all specified permissions.

        Args:
            *permissions: Permissions to check

        Returns:
            True if all permissions are granted
        """
        return all(p in self._permissions for p in permissions)

    def health_check(self) -> APIResponse:
        """
        Check connectivity to FusionAuth.

        Returns:
            APIResponse indicating health status
        """
        try:
            response = self._http.get_sync("/api/status")
            return response
        except Exception as e:
            return APIResponse.fail(
                error=f"Health check failed: {e}",
                status_code=503,
            )

    async def health_check_async(self) -> APIResponse:
        """Async version of health_check()."""
        try:
            response = await self._http.get("/api/status")
            return response
        except Exception as e:
            return APIResponse.fail(
                error=f"Health check failed: {e}",
                status_code=503,
            )

    def get_info(self) -> Dict[str, Any]:
        """
        Get SDK information.

        Returns:
            Dict with role, permissions, and config info
        """
        return {
            "role": self._role.value,
            "permissions": [p.value for p in self._permissions],
            "permission_count": len(self._permissions),
            "api_key_id": self._api_key_id,
            "fusionauth_url": self._config.fusionauth_url,
            "timeout": self._config.timeout,
        }

    def close(self) -> None:
        """Close the SDK and release resources."""
        if self._http:
            self._http.close_sync()

    async def close_async(self) -> None:
        """Async version of close()."""
        if self._http:
            await self._http.close()

    def __enter__(self) -> "PlatformSDK":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()

    async def __aenter__(self) -> "PlatformSDK":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close_async()

    def __repr__(self) -> str:
        return (
            f"PlatformSDK(role={self._role.value}, url={self._config.fusionauth_url})"
        )
