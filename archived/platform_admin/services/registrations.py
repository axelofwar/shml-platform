"""
Registrations service module for FusionAuth user-application registrations.

Registrations connect users to applications with specific roles.
"""

from typing import Optional, List, Dict, Any


class RegistrationsService:
    """
    Service for managing FusionAuth user registrations.

    Registrations define which applications a user can access
    and what roles they have within each application.
    All methods return APIResponse objects for consistent error handling.
    """

    def __init__(self, api):
        """
        Initialize the registrations service.

        Args:
            api: FusionAuthClient instance
        """
        self._api = api

    def get(self, user_id: str, app_id: str):
        """
        Get a user's registration for an application.

        Args:
            user_id: User UUID
            app_id: Application UUID

        Returns:
            APIResponse with {"registration": {...}} data
        """
        return self._api.get(f"/api/user/registration/{user_id}/{app_id}")

    def list_for_user(self, user_id: str):
        """
        List all registrations for a user.

        Args:
            user_id: User UUID

        Returns:
            APIResponse with {"registrations": [...]} data
        """
        from ..client import APIResponse

        response = self._api.get(f"/api/user/{user_id}")
        if response.success and response.data:
            user = response.data.get("user", {})
            registrations = user.get("registrations", [])
            return APIResponse(
                success=True,
                status_code=200,
                data={"registrations": registrations, "userId": user_id},
            )
        return response

    def create(
        self,
        user_id: str,
        app_id: str,
        roles: Optional[List[str]] = None,
        username: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        """
        Register a user to an application.

        Args:
            user_id: User UUID
            app_id: Application UUID
            roles: List of role names to assign
            username: Optional application-specific username
            data: Optional custom data

        Returns:
            APIResponse with {"registration": {...}} data
        """
        registration_data = {
            "applicationId": app_id,
        }

        if roles:
            registration_data["roles"] = roles
        if username:
            registration_data["username"] = username
        if data:
            registration_data["data"] = data

        return self._api.post(
            f"/api/user/registration/{user_id}", {"registration": registration_data}
        )

    def update(
        self,
        user_id: str,
        app_id: str,
        roles: Optional[List[str]] = None,
        username: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ):
        """
        Update a user's registration for an application.

        Args:
            user_id: User UUID
            app_id: Application UUID
            roles: New list of roles (replaces existing)
            username: New application-specific username
            data: New custom data

        Returns:
            APIResponse with {"registration": {...}} data
        """
        registration_data = {
            "applicationId": app_id,
        }

        if roles is not None:
            registration_data["roles"] = roles
        if username is not None:
            registration_data["username"] = username
        if data is not None:
            registration_data["data"] = data

        return self._api.patch(
            f"/api/user/registration/{user_id}/{app_id}",
            {"registration": registration_data},
        )

    def delete(self, user_id: str, app_id: str):
        """
        Delete a user's registration for an application.

        Args:
            user_id: User UUID
            app_id: Application UUID

        Returns:
            APIResponse indicating success or failure
        """
        return self._api.delete(f"/api/user/registration/{user_id}/{app_id}")

    def add_roles(
        self,
        user_id: str,
        app_id: str,
        roles: List[str],
    ):
        """
        Add roles to a user's existing registration.

        Args:
            user_id: User UUID
            app_id: Application UUID
            roles: Roles to add

        Returns:
            APIResponse with {"registration": {...}} data
        """
        # Get existing registration
        response = self.get(user_id, app_id)
        if not response.success:
            # If no registration exists, create one
            return self.create(user_id, app_id, roles=roles)

        reg = response.data.get("registration", {})
        existing_roles = set(reg.get("roles", []))
        new_roles = existing_roles | set(roles)

        return self.update(user_id, app_id, roles=list(new_roles))

    def remove_roles(
        self,
        user_id: str,
        app_id: str,
        roles: List[str],
    ):
        """
        Remove roles from a user's registration.

        Args:
            user_id: User UUID
            app_id: Application UUID
            roles: Roles to remove

        Returns:
            APIResponse with {"registration": {...}} data
        """
        # Get existing registration
        response = self.get(user_id, app_id)
        if not response.success:
            return response

        reg = response.data.get("registration", {})
        existing_roles = set(reg.get("roles", []))
        new_roles = existing_roles - set(roles)

        return self.update(user_id, app_id, roles=list(new_roles))

    def set_roles(
        self,
        user_id: str,
        app_id: str,
        roles: List[str],
    ):
        """
        Set roles for a user's registration (replaces existing).

        Args:
            user_id: User UUID
            app_id: Application UUID
            roles: Roles to set

        Returns:
            APIResponse with {"registration": {...}} data
        """
        # Check if registration exists
        response = self.get(user_id, app_id)
        if response.success:
            return self.update(user_id, app_id, roles=roles)
        else:
            return self.create(user_id, app_id, roles=roles)
