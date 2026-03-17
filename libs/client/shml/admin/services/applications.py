"""
Applications Service for FusionAuth application management.

Provides CRUD operations for applications with permission enforcement.
"""

from typing import Optional, List, Dict, Any

from .base import BaseService
from ..models import APIResponse, Permission
from ..permissions import requires_permission


class ApplicationsService(BaseService):
    """
    Service for managing FusionAuth applications.

    Applications represent client applications that can authenticate
    users and have their own roles.
    """

    # ========================================================================
    # Read Operations (APPLICATIONS_READ)
    # ========================================================================

    @requires_permission(Permission.APPLICATIONS_READ)
    def list(self, inactive: bool = False) -> APIResponse:
        """
        List all applications.

        Args:
            inactive: Include inactive applications

        Returns:
            APIResponse with {"applications": [...]}
        """
        params = {}
        if inactive:
            params["inactive"] = "true"

        return self._http.get_sync("/api/application", params=params or None)

    @requires_permission(Permission.APPLICATIONS_READ)
    async def list_async(self, inactive: bool = False) -> APIResponse:
        """Async version of list()."""
        params = {}
        if inactive:
            params["inactive"] = "true"

        return await self._http.get("/api/application", params=params or None)

    @requires_permission(Permission.APPLICATIONS_READ)
    def get(self, application_id: str) -> APIResponse:
        """
        Get an application by ID.

        Args:
            application_id: Application UUID

        Returns:
            APIResponse with {"application": {...}}
        """
        return self._http.get_sync(f"/api/application/{application_id}")

    @requires_permission(Permission.APPLICATIONS_READ)
    async def get_async(self, application_id: str) -> APIResponse:
        """Async version of get()."""
        return await self._http.get(f"/api/application/{application_id}")

    @requires_permission(Permission.APPLICATIONS_READ)
    def get_by_name(self, name: str) -> APIResponse:
        """
        Get an application by name.

        Args:
            name: Application name

        Returns:
            APIResponse with {"application": {...}}
        """
        response = self.list()
        if not response.success:
            return response

        apps = response.data.get("applications", [])
        for app in apps:
            if app.get("name") == name:
                return APIResponse.ok(
                    data={"application": app},
                    status_code=200,
                )

        return APIResponse.fail(
            error=f"Application '{name}' not found",
            status_code=404,
        )

    @requires_permission(Permission.APPLICATIONS_READ)
    async def get_by_name_async(self, name: str) -> APIResponse:
        """Async version of get_by_name()."""
        response = await self.list_async()
        if not response.success:
            return response

        apps = response.data.get("applications", [])
        for app in apps:
            if app.get("name") == name:
                return APIResponse.ok(
                    data={"application": app},
                    status_code=200,
                )

        return APIResponse.fail(
            error=f"Application '{name}' not found",
            status_code=404,
        )

    @requires_permission(Permission.APPLICATIONS_READ)
    def search(
        self,
        name: str,
        limit: int = 25,
        offset: int = 0,
    ) -> APIResponse:
        """
        Search applications by name.

        Args:
            name: Name pattern (supports wildcards *)
            limit: Maximum results
            offset: Pagination offset

        Returns:
            APIResponse with {"applications": [...], "total": int}
        """
        return self._http.post_sync(
            "/api/application/search",
            json={
                "search": {
                    "name": name,
                    "numberOfResults": limit,
                    "startRow": offset,
                }
            },
        )

    @requires_permission(Permission.APPLICATIONS_READ)
    async def search_async(
        self,
        name: str,
        limit: int = 25,
        offset: int = 0,
    ) -> APIResponse:
        """Async version of search()."""
        return await self._http.post(
            "/api/application/search",
            json={
                "search": {
                    "name": name,
                    "numberOfResults": limit,
                    "startRow": offset,
                }
            },
        )

    # ========================================================================
    # Create Operations (APPLICATIONS_CREATE)
    # ========================================================================

    @requires_permission(Permission.APPLICATIONS_CREATE)
    def create(
        self,
        name: str,
        tenant_id: Optional[str] = None,
        roles: Optional[List[Dict[str, Any]]] = None,
        oauth_configuration: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        application_id: Optional[str] = None,
    ) -> APIResponse:
        """
        Create a new application.

        Args:
            name: Application name
            tenant_id: Tenant UUID (uses default if not specified)
            roles: List of roles to create for this application
            oauth_configuration: OAuth2/OIDC configuration
            data: Custom application data
            application_id: Optional UUID (generated if not provided)

        Returns:
            APIResponse with {"application": {...}}
        """
        app_data: Dict[str, Any] = {"name": name}

        if tenant_id:
            app_data["tenantId"] = tenant_id
        if roles:
            app_data["roles"] = roles
        if oauth_configuration:
            app_data["oauthConfiguration"] = oauth_configuration
        if data:
            app_data["data"] = data

        url = (
            f"/api/application/{application_id}"
            if application_id
            else "/api/application"
        )

        return self._http.post_sync(url, json={"application": app_data})

    @requires_permission(Permission.APPLICATIONS_CREATE)
    async def create_async(
        self,
        name: str,
        tenant_id: Optional[str] = None,
        roles: Optional[List[Dict[str, Any]]] = None,
        oauth_configuration: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        application_id: Optional[str] = None,
    ) -> APIResponse:
        """Async version of create()."""
        app_data: Dict[str, Any] = {"name": name}

        if tenant_id:
            app_data["tenantId"] = tenant_id
        if roles:
            app_data["roles"] = roles
        if oauth_configuration:
            app_data["oauthConfiguration"] = oauth_configuration
        if data:
            app_data["data"] = data

        url = (
            f"/api/application/{application_id}"
            if application_id
            else "/api/application"
        )

        return await self._http.post(url, json={"application": app_data})

    # ========================================================================
    # Update Operations (APPLICATIONS_UPDATE)
    # ========================================================================

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    def update(
        self,
        application_id: str,
        name: Optional[str] = None,
        roles: Optional[List[Dict[str, Any]]] = None,
        oauth_configuration: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        active: Optional[bool] = None,
    ) -> APIResponse:
        """
        Update an application.

        Args:
            application_id: Application UUID
            name: New name
            roles: Updated roles
            oauth_configuration: Updated OAuth configuration
            data: Updated custom data
            active: Set active status

        Returns:
            APIResponse with {"application": {...}}
        """
        app_data: Dict[str, Any] = {}

        if name is not None:
            app_data["name"] = name
        if roles is not None:
            app_data["roles"] = roles
        if oauth_configuration is not None:
            app_data["oauthConfiguration"] = oauth_configuration
        if data is not None:
            app_data["data"] = data
        if active is not None:
            app_data["active"] = active

        return self._http.patch_sync(
            f"/api/application/{application_id}", json={"application": app_data}
        )

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    async def update_async(
        self,
        application_id: str,
        name: Optional[str] = None,
        roles: Optional[List[Dict[str, Any]]] = None,
        oauth_configuration: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        active: Optional[bool] = None,
    ) -> APIResponse:
        """Async version of update()."""
        app_data: Dict[str, Any] = {}

        if name is not None:
            app_data["name"] = name
        if roles is not None:
            app_data["roles"] = roles
        if oauth_configuration is not None:
            app_data["oauthConfiguration"] = oauth_configuration
        if data is not None:
            app_data["data"] = data
        if active is not None:
            app_data["active"] = active

        return await self._http.patch(
            f"/api/application/{application_id}", json={"application": app_data}
        )

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    def deactivate(self, application_id: str) -> APIResponse:
        """
        Deactivate an application.

        Args:
            application_id: Application UUID

        Returns:
            APIResponse with {"application": {...}}
        """
        return self.update(application_id, active=False)

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    async def deactivate_async(self, application_id: str) -> APIResponse:
        """Async version of deactivate()."""
        return await self.update_async(application_id, active=False)

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    def reactivate(self, application_id: str) -> APIResponse:
        """
        Reactivate an application.

        Args:
            application_id: Application UUID

        Returns:
            APIResponse with {"application": {...}}
        """
        return self.update(application_id, active=True)

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    async def reactivate_async(self, application_id: str) -> APIResponse:
        """Async version of reactivate()."""
        return await self.update_async(application_id, active=True)

    # ========================================================================
    # Delete Operations (APPLICATIONS_DELETE)
    # ========================================================================

    @requires_permission(Permission.APPLICATIONS_DELETE)
    def delete(
        self,
        application_id: str,
        hard_delete: bool = False,
    ) -> APIResponse:
        """
        Delete an application.

        Args:
            application_id: Application UUID
            hard_delete: Permanently delete (vs soft delete)

        Returns:
            APIResponse indicating success
        """
        params = {}
        if hard_delete:
            params["hardDelete"] = "true"

        return self._http.delete_sync(
            f"/api/application/{application_id}", params=params or None
        )

    @requires_permission(Permission.APPLICATIONS_DELETE)
    async def delete_async(
        self,
        application_id: str,
        hard_delete: bool = False,
    ) -> APIResponse:
        """Async version of delete()."""
        params = {}
        if hard_delete:
            params["hardDelete"] = "true"

        return await self._http.delete(
            f"/api/application/{application_id}", params=params or None
        )

    # ========================================================================
    # Role Management (within application)
    # ========================================================================

    @requires_permission(Permission.APPLICATIONS_READ)
    def get_roles(self, application_id: str) -> APIResponse:
        """
        Get all roles for an application.

        Args:
            application_id: Application UUID

        Returns:
            APIResponse with {"application": {..., "roles": [...]}}
        """
        response = self.get(application_id)
        if not response.success:
            return response

        roles = response.data.get("application", {}).get("roles", [])
        return APIResponse.ok(
            data={"roles": roles},
            status_code=200,
        )

    @requires_permission(Permission.APPLICATIONS_READ)
    async def get_roles_async(self, application_id: str) -> APIResponse:
        """Async version of get_roles()."""
        response = await self.get_async(application_id)
        if not response.success:
            return response

        roles = response.data.get("application", {}).get("roles", [])
        return APIResponse.ok(
            data={"roles": roles},
            status_code=200,
        )

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    def add_role(
        self,
        application_id: str,
        name: str,
        description: Optional[str] = None,
        is_super_role: bool = False,
    ) -> APIResponse:
        """
        Add a role to an application.

        Args:
            application_id: Application UUID
            name: Role name
            description: Role description
            is_super_role: If true, grants all application permissions

        Returns:
            APIResponse with {"role": {...}}
        """
        role_data: Dict[str, Any] = {"name": name}

        if description:
            role_data["description"] = description
        if is_super_role:
            role_data["isSuperRole"] = True

        return self._http.post_sync(
            f"/api/application/{application_id}/role", json={"role": role_data}
        )

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    async def add_role_async(
        self,
        application_id: str,
        name: str,
        description: Optional[str] = None,
        is_super_role: bool = False,
    ) -> APIResponse:
        """Async version of add_role()."""
        role_data: Dict[str, Any] = {"name": name}

        if description:
            role_data["description"] = description
        if is_super_role:
            role_data["isSuperRole"] = True

        return await self._http.post(
            f"/api/application/{application_id}/role", json={"role": role_data}
        )

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    def update_role(
        self,
        application_id: str,
        role_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_super_role: Optional[bool] = None,
    ) -> APIResponse:
        """
        Update a role in an application.

        Args:
            application_id: Application UUID
            role_id: Role UUID
            name: New role name
            description: New role description
            is_super_role: Update super role status

        Returns:
            APIResponse with {"role": {...}}
        """
        role_data: Dict[str, Any] = {}

        if name is not None:
            role_data["name"] = name
        if description is not None:
            role_data["description"] = description
        if is_super_role is not None:
            role_data["isSuperRole"] = is_super_role

        return self._http.patch_sync(
            f"/api/application/{application_id}/role/{role_id}",
            json={"role": role_data},
        )

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    async def update_role_async(
        self,
        application_id: str,
        role_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_super_role: Optional[bool] = None,
    ) -> APIResponse:
        """Async version of update_role()."""
        role_data: Dict[str, Any] = {}

        if name is not None:
            role_data["name"] = name
        if description is not None:
            role_data["description"] = description
        if is_super_role is not None:
            role_data["isSuperRole"] = is_super_role

        return await self._http.patch(
            f"/api/application/{application_id}/role/{role_id}",
            json={"role": role_data},
        )

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    def delete_role(
        self,
        application_id: str,
        role_id: str,
    ) -> APIResponse:
        """
        Delete a role from an application.

        Args:
            application_id: Application UUID
            role_id: Role UUID

        Returns:
            APIResponse indicating success
        """
        return self._http.delete_sync(
            f"/api/application/{application_id}/role/{role_id}"
        )

    @requires_permission(Permission.APPLICATIONS_UPDATE)
    async def delete_role_async(
        self,
        application_id: str,
        role_id: str,
    ) -> APIResponse:
        """Async version of delete_role()."""
        return await self._http.delete(
            f"/api/application/{application_id}/role/{role_id}"
        )
