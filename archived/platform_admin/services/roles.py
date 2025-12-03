"""
Roles service module for FusionAuth role management.

Roles are defined per-application and assigned to users via registrations.
"""

from typing import Optional, List, Dict, Any


class RolesService:
    """
    Service for managing FusionAuth roles.

    Note: Roles in FusionAuth are scoped to applications. This service
    provides convenience methods for role management across applications.
    All methods return APIResponse objects for consistent error handling.
    """

    def __init__(self, api):
        """
        Initialize the roles service.

        Args:
            api: FusionAuthClient instance
        """
        self._api = api

    def list_for_application(self, app_id: str):
        """
        List all roles for an application.

        Args:
            app_id: Application UUID

        Returns:
            APIResponse with {"roles": [...]} data
        """
        from ..client import APIResponse

        response = self._api.get(f"/api/application/{app_id}")
        if not response.success:
            return response

        app = response.data.get("application", {})
        roles = app.get("roles", [])

        return APIResponse(
            success=True,
            status_code=200,
            data={"roles": roles, "applicationId": app_id},
        )

    def get(self, app_id: str, role_id: str):
        """
        Get a specific role from an application.

        Args:
            app_id: Application UUID
            role_id: Role UUID

        Returns:
            APIResponse with {"role": {...}} data
        """
        from ..client import APIResponse

        response = self.list_for_application(app_id)
        if not response.success:
            return response

        roles = response.data.get("roles", [])
        for role in roles:
            if role.get("id") == role_id:
                return APIResponse(success=True, status_code=200, data={"role": role})

        return APIResponse(
            success=False,
            status_code=404,
            error=f"Role '{role_id}' not found in application '{app_id}'",
        )

    def get_by_name(self, app_id: str, role_name: str):
        """
        Get a role by name from an application.

        Args:
            app_id: Application UUID
            role_name: Role name

        Returns:
            APIResponse with {"role": {...}} data
        """
        from ..client import APIResponse

        response = self.list_for_application(app_id)
        if not response.success:
            return response

        roles = response.data.get("roles", [])
        for role in roles:
            if role.get("name") == role_name:
                return APIResponse(success=True, status_code=200, data={"role": role})

        return APIResponse(
            success=False,
            status_code=404,
            error=f"Role '{role_name}' not found in application '{app_id}'",
        )

    def create(
        self,
        app_id: str,
        name: str,
        description: Optional[str] = None,
        is_default: bool = False,
        is_super_role: bool = False,
    ):
        """
        Create a new role for an application.

        Args:
            app_id: Application UUID
            name: Role name
            description: Optional description
            is_default: Assign to new registrations by default
            is_super_role: Is this a super-admin role

        Returns:
            APIResponse with {"role": {...}} data
        """
        role_data = {
            "name": name,
            "isDefault": is_default,
            "isSuperRole": is_super_role,
        }

        if description:
            role_data["description"] = description

        return self._api.post(f"/api/application/{app_id}/role", {"role": role_data})

    def update(
        self,
        app_id: str,
        role_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_default: Optional[bool] = None,
        is_super_role: Optional[bool] = None,
    ):
        """
        Update an existing role.

        Args:
            app_id: Application UUID
            role_id: Role UUID
            name: New role name
            description: New description
            is_default: New default status
            is_super_role: New super-role status

        Returns:
            APIResponse with {"role": {...}} data
        """
        role_data = {}

        if name is not None:
            role_data["name"] = name
        if description is not None:
            role_data["description"] = description
        if is_default is not None:
            role_data["isDefault"] = is_default
        if is_super_role is not None:
            role_data["isSuperRole"] = is_super_role

        return self._api.patch(
            f"/api/application/{app_id}/role/{role_id}", {"role": role_data}
        )

    def delete(self, app_id: str, role_id: str):
        """
        Delete a role from an application.

        Args:
            app_id: Application UUID
            role_id: Role UUID

        Returns:
            APIResponse indicating success or failure
        """
        return self._api.delete(f"/api/application/{app_id}/role/{role_id}")
