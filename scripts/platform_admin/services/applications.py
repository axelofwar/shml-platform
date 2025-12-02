"""
Applications service module for FusionAuth application management.

Applications represent OAuth2 clients that users can authenticate to.
"""

from typing import Optional, List, Dict, Any


class ApplicationsService:
    """
    Service for managing FusionAuth applications (OAuth clients).

    Provides listing, creation, and role management for applications.
    All methods return APIResponse objects for consistent error handling.
    """

    def __init__(self, api):
        """
        Initialize the applications service.

        Args:
            api: FusionAuthClient instance
        """
        self._api = api
        self._cache: Optional[Dict[str, Dict]] = None

    def list(self):
        """
        List all applications.

        Returns:
            APIResponse with {"applications": [...]} data
        """
        response = self._api.get("/api/application")
        if response.success and response.data:
            self._update_cache(response.data)
        return response

    def _update_cache(self, data: Dict) -> None:
        """Update internal cache of applications."""
        if data and "applications" in data:
            self._cache = {app["name"]: app for app in data["applications"]}

    def get(self, app_id: str):
        """
        Get an application by ID.

        Args:
            app_id: Application UUID

        Returns:
            APIResponse with {"application": {...}} data
        """
        return self._api.get(f"/api/application/{app_id}")

    def get_by_name(self, name: str):
        """
        Get an application by name.

        Args:
            name: Application name

        Returns:
            APIResponse with {"application": {...}} data
        """
        from ..client import APIResponse

        # Try cache first
        if self._cache and name in self._cache:
            return APIResponse(
                success=True, status_code=200, data={"application": self._cache[name]}
            )

        # Fetch all and search
        response = self.list()
        if not response.success:
            return response

        apps = response.data.get("applications", [])
        for app in apps:
            if app.get("name") == name:
                return APIResponse(
                    success=True, status_code=200, data={"application": app}
                )

        return APIResponse(
            success=False, status_code=404, error=f"Application '{name}' not found"
        )

    def get_roles(self, app_id: str):
        """
        Get roles defined for an application.

        Args:
            app_id: Application UUID

        Returns:
            APIResponse with {"roles": [...]} data
        """
        from ..client import APIResponse

        response = self.get(app_id)
        if not response.success:
            return response

        app = response.data.get("application", {})
        roles = app.get("roles", [])

        return APIResponse(
            success=True,
            status_code=200,
            data={"roles": roles, "applicationId": app_id},
        )

    def create(
        self,
        name: str,
        roles: Optional[List[str]] = None,
        oauth_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Create a new application.

        Args:
            name: Application name
            roles: Optional list of role names to create
            oauth_config: Optional OAuth2 configuration

        Returns:
            APIResponse with {"application": {...}} data
        """
        app_data = {
            "name": name,
            "active": True,
        }

        if roles:
            app_data["roles"] = [{"name": r} for r in roles]

        if oauth_config:
            app_data["oauthConfiguration"] = oauth_config

        response = self._api.post("/api/application", {"application": app_data})

        # Invalidate cache on successful create
        if response.success:
            self._cache = None

        return response

    def update(
        self,
        app_id: str,
        name: Optional[str] = None,
        active: Optional[bool] = None,
        roles: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Update an existing application.

        Args:
            app_id: Application UUID
            name: New application name
            active: Active status
            roles: Updated roles list

        Returns:
            APIResponse with {"application": {...}} data
        """
        app_data = {}

        if name is not None:
            app_data["name"] = name
        if active is not None:
            app_data["active"] = active
        if roles is not None:
            app_data["roles"] = roles

        response = self._api.patch(
            f"/api/application/{app_id}", {"application": app_data}
        )

        # Invalidate cache on successful update
        if response.success:
            self._cache = None

        return response

    def delete(self, app_id: str):
        """
        Delete an application.

        Args:
            app_id: Application UUID

        Returns:
            APIResponse indicating success or failure
        """
        response = self._api.delete(f"/api/application/{app_id}")

        # Invalidate cache on successful delete
        if response.success:
            self._cache = None

        return response

    def add_role(self, app_id: str, role_name: str, description: Optional[str] = None):
        """
        Add a role to an application.

        Args:
            app_id: Application UUID
            role_name: Name of the role to add
            description: Optional role description

        Returns:
            APIResponse with {"role": {...}} data
        """
        role_data = {"name": role_name}
        if description:
            role_data["description"] = description

        return self._api.post(f"/api/application/{app_id}/role", {"role": role_data})

    def delete_role(self, app_id: str, role_id: str):
        """
        Delete a role from an application.

        Args:
            app_id: Application UUID
            role_id: Role UUID to delete

        Returns:
            APIResponse indicating success or failure
        """
        return self._api.delete(f"/api/application/{app_id}/role/{role_id}")
