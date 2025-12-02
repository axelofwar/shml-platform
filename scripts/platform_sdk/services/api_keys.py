"""
API Keys Service for FusionAuth API key management.

Provides operations for API keys with permission enforcement.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime

from .base import BaseService
from ..models import APIResponse, Permission
from ..permissions import requires_permission


class APIKeysService(BaseService):
    """
    Service for managing FusionAuth API keys.

    API keys authenticate SDK/API access and can have
    different permission levels.
    """

    # ========================================================================
    # Read Operations (API_KEYS_READ)
    # ========================================================================

    @requires_permission(Permission.API_KEYS_READ)
    def list(self) -> APIResponse:
        """
        List all API keys.

        Note: The actual key values are not returned for security.

        Returns:
            APIResponse with {"apiKeys": [...]}
        """
        return self._http.get_sync("/api/api-key")

    @requires_permission(Permission.API_KEYS_READ)
    async def list_async(self) -> APIResponse:
        """Async version of list()."""
        return await self._http.get("/api/api-key")

    @requires_permission(Permission.API_KEYS_READ)
    def get(self, api_key_id: str) -> APIResponse:
        """
        Get an API key by ID.

        Args:
            api_key_id: API key UUID (not the key itself)

        Returns:
            APIResponse with {"apiKey": {...}}
        """
        return self._http.get_sync(f"/api/api-key/{api_key_id}")

    @requires_permission(Permission.API_KEYS_READ)
    async def get_async(self, api_key_id: str) -> APIResponse:
        """Async version of get()."""
        return await self._http.get(f"/api/api-key/{api_key_id}")

    def introspect(self, api_key: Optional[str] = None) -> APIResponse:
        """
        Introspect an API key to get its permissions.

        This method does NOT require permissions - it's used
        to bootstrap permission detection.

        Args:
            api_key: The API key to introspect (uses current if not provided)

        Returns:
            APIResponse with {"apiKey": {...}}
        """
        # Use a temporary client if checking a different key
        if api_key and api_key != self._http._api_key:
            from ..http import HTTPClient

            temp_client = HTTPClient(
                base_url=self._http._base_url,
                api_key=api_key,
                timeout=self._http._timeout,
            )
            try:
                return temp_client.get_sync("/api/api-key")
            finally:
                temp_client.close()

        return self._http.get_sync("/api/api-key")

    async def introspect_async(self, api_key: Optional[str] = None) -> APIResponse:
        """Async version of introspect()."""
        if api_key and api_key != self._http._api_key:
            from ..http import HTTPClient

            temp_client = HTTPClient(
                base_url=self._http._base_url,
                api_key=api_key,
                timeout=self._http._timeout,
            )
            try:
                return await temp_client.get("/api/api-key")
            finally:
                await temp_client.close_async()

        return await self._http.get("/api/api-key")

    # ========================================================================
    # Create Operations (API_KEYS_CREATE)
    # ========================================================================

    @requires_permission(Permission.API_KEYS_CREATE)
    def create(
        self,
        description: str,
        permissions: Optional[Dict[str, List[str]]] = None,
        tenant_id: Optional[str] = None,
        key_id: Optional[str] = None,
        key: Optional[str] = None,
        ip_access_control_list_id: Optional[str] = None,
        meta_data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Create a new API key.

        Args:
            description: Human-readable description
            permissions: Endpoint permissions {"endpoint": ["METHOD"]}
            tenant_id: Restrict to a specific tenant
            key_id: Specific UUID for the key record
            key: Specific key value (generated if not provided)
            ip_access_control_list_id: IP whitelist to apply
            meta_data: Custom metadata for the key

        Returns:
            APIResponse with {"apiKey": {...}} including the actual key
        """
        key_data: Dict[str, Any] = {}

        if description:
            key_data["description"] = description
        if permissions:
            key_data["permissions"] = {"endpoints": permissions}
        if tenant_id:
            key_data["tenantId"] = tenant_id
        if key:
            key_data["key"] = key
        if ip_access_control_list_id:
            key_data["ipAccessControlListId"] = ip_access_control_list_id
        if meta_data:
            key_data["metaData"] = meta_data

        url = f"/api/api-key/{key_id}" if key_id else "/api/api-key"

        return self._http.post_sync(url, json={"apiKey": key_data})

    @requires_permission(Permission.API_KEYS_CREATE)
    async def create_async(
        self,
        description: str,
        permissions: Optional[Dict[str, List[str]]] = None,
        tenant_id: Optional[str] = None,
        key_id: Optional[str] = None,
        key: Optional[str] = None,
        ip_access_control_list_id: Optional[str] = None,
        meta_data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Async version of create()."""
        key_data: Dict[str, Any] = {}

        if description:
            key_data["description"] = description
        if permissions:
            key_data["permissions"] = {"endpoints": permissions}
        if tenant_id:
            key_data["tenantId"] = tenant_id
        if key:
            key_data["key"] = key
        if ip_access_control_list_id:
            key_data["ipAccessControlListId"] = ip_access_control_list_id
        if meta_data:
            key_data["metaData"] = meta_data

        url = f"/api/api-key/{key_id}" if key_id else "/api/api-key"

        return await self._http.post(url, json={"apiKey": key_data})

    @requires_permission(Permission.API_KEYS_CREATE)
    def create_admin_key(
        self,
        description: str,
        tenant_id: Optional[str] = None,
    ) -> APIResponse:
        """
        Create an admin (super) API key with all permissions.

        Args:
            description: Human-readable description
            tenant_id: Restrict to a specific tenant

        Returns:
            APIResponse with {"apiKey": {...}}
        """
        return self.create(
            description=f"[ADMIN] {description}",
            permissions=None,  # No restrictions = super key
            tenant_id=tenant_id,
            meta_data={"role": "admin", "created_by": "platform_sdk"},
        )

    @requires_permission(Permission.API_KEYS_CREATE)
    async def create_admin_key_async(
        self,
        description: str,
        tenant_id: Optional[str] = None,
    ) -> APIResponse:
        """Async version of create_admin_key()."""
        return await self.create_async(
            description=f"[ADMIN] {description}",
            permissions=None,
            tenant_id=tenant_id,
            meta_data={"role": "admin", "created_by": "platform_sdk"},
        )

    @requires_permission(Permission.API_KEYS_CREATE)
    def create_developer_key(
        self,
        description: str,
        tenant_id: Optional[str] = None,
    ) -> APIResponse:
        """
        Create a developer API key with read + limited write permissions.

        Args:
            description: Human-readable description
            tenant_id: Restrict to a specific tenant

        Returns:
            APIResponse with {"apiKey": {...}}
        """
        # Developer permissions: read all, limited write
        permissions = {
            # Users - read only
            "/api/user": ["GET"],
            "/api/user/search": ["POST"],
            # Groups - read only
            "/api/group": ["GET"],
            "/api/group/search": ["GET"],
            "/api/group/member/search": ["GET"],
            # Applications - read only
            "/api/application": ["GET"],
            "/api/application/search": ["POST"],
            # Registrations - read + create
            "/api/user/registration": ["GET", "POST"],
            # API keys - introspect only (read current key info)
            "/api/api-key": ["GET"],
        }

        return self.create(
            description=f"[DEVELOPER] {description}",
            permissions=permissions,
            tenant_id=tenant_id,
            meta_data={"role": "developer", "created_by": "platform_sdk"},
        )

    @requires_permission(Permission.API_KEYS_CREATE)
    async def create_developer_key_async(
        self,
        description: str,
        tenant_id: Optional[str] = None,
    ) -> APIResponse:
        """Async version of create_developer_key()."""
        permissions = {
            "/api/user": ["GET"],
            "/api/user/search": ["POST"],
            "/api/group": ["GET"],
            "/api/group/search": ["GET"],
            "/api/group/member/search": ["GET"],
            "/api/application": ["GET"],
            "/api/application/search": ["POST"],
            "/api/user/registration": ["GET", "POST"],
            "/api/api-key": ["GET"],
        }

        return await self.create_async(
            description=f"[DEVELOPER] {description}",
            permissions=permissions,
            tenant_id=tenant_id,
            meta_data={"role": "developer", "created_by": "platform_sdk"},
        )

    @requires_permission(Permission.API_KEYS_CREATE)
    def create_viewer_key(
        self,
        description: str,
        tenant_id: Optional[str] = None,
    ) -> APIResponse:
        """
        Create a viewer API key with read-only permissions.

        Args:
            description: Human-readable description
            tenant_id: Restrict to a specific tenant

        Returns:
            APIResponse with {"apiKey": {...}}
        """
        # Viewer permissions: read only
        permissions = {
            "/api/user": ["GET"],
            "/api/user/search": ["POST"],  # Search uses POST
            "/api/group": ["GET"],
            "/api/group/search": ["GET"],
            "/api/group/member/search": ["GET"],
            "/api/application": ["GET"],
            "/api/user/registration": ["GET"],
            "/api/api-key": ["GET"],
        }

        return self.create(
            description=f"[VIEWER] {description}",
            permissions=permissions,
            tenant_id=tenant_id,
            meta_data={"role": "viewer", "created_by": "platform_sdk"},
        )

    @requires_permission(Permission.API_KEYS_CREATE)
    async def create_viewer_key_async(
        self,
        description: str,
        tenant_id: Optional[str] = None,
    ) -> APIResponse:
        """Async version of create_viewer_key()."""
        permissions = {
            "/api/user": ["GET"],
            "/api/user/search": ["POST"],
            "/api/group": ["GET"],
            "/api/group/search": ["GET"],
            "/api/group/member/search": ["GET"],
            "/api/application": ["GET"],
            "/api/user/registration": ["GET"],
            "/api/api-key": ["GET"],
        }

        return await self.create_async(
            description=f"[VIEWER] {description}",
            permissions=permissions,
            tenant_id=tenant_id,
            meta_data={"role": "viewer", "created_by": "platform_sdk"},
        )

    # ========================================================================
    # Update Operations (API_KEYS_UPDATE)
    # ========================================================================

    @requires_permission(Permission.API_KEYS_UPDATE)
    def update(
        self,
        api_key_id: str,
        description: Optional[str] = None,
        permissions: Optional[Dict[str, List[str]]] = None,
        ip_access_control_list_id: Optional[str] = None,
        meta_data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Update an API key.

        Note: The key value cannot be changed.

        Args:
            api_key_id: API key UUID
            description: New description
            permissions: New endpoint permissions
            ip_access_control_list_id: New IP whitelist
            meta_data: New metadata

        Returns:
            APIResponse with {"apiKey": {...}}
        """
        key_data: Dict[str, Any] = {}

        if description is not None:
            key_data["description"] = description
        if permissions is not None:
            key_data["permissions"] = {"endpoints": permissions}
        if ip_access_control_list_id is not None:
            key_data["ipAccessControlListId"] = ip_access_control_list_id
        if meta_data is not None:
            key_data["metaData"] = meta_data

        return self._http.put_sync(
            f"/api/api-key/{api_key_id}", json={"apiKey": key_data}
        )

    @requires_permission(Permission.API_KEYS_UPDATE)
    async def update_async(
        self,
        api_key_id: str,
        description: Optional[str] = None,
        permissions: Optional[Dict[str, List[str]]] = None,
        ip_access_control_list_id: Optional[str] = None,
        meta_data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Async version of update()."""
        key_data: Dict[str, Any] = {}

        if description is not None:
            key_data["description"] = description
        if permissions is not None:
            key_data["permissions"] = {"endpoints": permissions}
        if ip_access_control_list_id is not None:
            key_data["ipAccessControlListId"] = ip_access_control_list_id
        if meta_data is not None:
            key_data["metaData"] = meta_data

        return await self._http.put(
            f"/api/api-key/{api_key_id}", json={"apiKey": key_data}
        )

    # ========================================================================
    # Delete Operations (API_KEYS_DELETE)
    # ========================================================================

    @requires_permission(Permission.API_KEYS_DELETE)
    def delete(self, api_key_id: str) -> APIResponse:
        """
        Delete an API key.

        Args:
            api_key_id: API key UUID

        Returns:
            APIResponse indicating success
        """
        return self._http.delete_sync(f"/api/api-key/{api_key_id}")

    @requires_permission(Permission.API_KEYS_DELETE)
    async def delete_async(self, api_key_id: str) -> APIResponse:
        """Async version of delete()."""
        return await self._http.delete(f"/api/api-key/{api_key_id}")

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def get_role_from_metadata(self, api_key_data: Dict[str, Any]) -> str:
        """
        Extract the role from API key metadata.

        Args:
            api_key_data: API key data from response

        Returns:
            Role string (admin, developer, viewer, or unknown)
        """
        meta_data = api_key_data.get("metaData", {})
        return meta_data.get("role", "unknown")

    def has_super_permissions(self, api_key_data: Dict[str, Any]) -> bool:
        """
        Check if an API key has super (unrestricted) permissions.

        Args:
            api_key_data: API key data from response

        Returns:
            True if key has no permission restrictions
        """
        permissions = api_key_data.get("permissions", {})
        endpoints = permissions.get("endpoints", {})

        # Empty endpoints means super key (all access)
        return len(endpoints) == 0

    def get_key_summary(self, api_key_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get a summary of an API key's configuration.

        Args:
            api_key_data: API key data from response

        Returns:
            Summary dict with role, permissions count, etc.
        """
        permissions = api_key_data.get("permissions", {})
        endpoints = permissions.get("endpoints", {})

        return {
            "id": api_key_data.get("id"),
            "description": api_key_data.get("description"),
            "role": self.get_role_from_metadata(api_key_data),
            "is_super_key": self.has_super_permissions(api_key_data),
            "endpoint_count": len(endpoints),
            "tenant_id": api_key_data.get("tenantId"),
            "insert_instant": api_key_data.get("insertInstant"),
        }
