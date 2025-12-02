"""
Registrations Service for FusionAuth user-application registrations.

Provides CRUD operations for registrations with permission enforcement.
A registration links a user to an application and assigns application roles.
"""

from typing import Optional, List, Dict, Any

from .base import BaseService
from ..models import APIResponse, Permission
from ..permissions import requires_permission


class RegistrationsService(BaseService):
    """
    Service for managing FusionAuth user registrations.

    Registrations link users to applications and assign
    application-specific roles and data.
    """

    # ========================================================================
    # Read Operations (REGISTRATIONS_READ)
    # ========================================================================

    @requires_permission(Permission.REGISTRATIONS_READ)
    def get(
        self,
        user_id: str,
        application_id: str,
    ) -> APIResponse:
        """
        Get a user's registration for an application.

        Args:
            user_id: User UUID
            application_id: Application UUID

        Returns:
            APIResponse with {"registration": {...}}
        """
        return self._http.get_sync(f"/api/user/registration/{user_id}/{application_id}")

    @requires_permission(Permission.REGISTRATIONS_READ)
    async def get_async(
        self,
        user_id: str,
        application_id: str,
    ) -> APIResponse:
        """Async version of get()."""
        return await self._http.get(
            f"/api/user/registration/{user_id}/{application_id}"
        )

    @requires_permission(Permission.REGISTRATIONS_READ)
    def list_for_user(self, user_id: str) -> APIResponse:
        """
        List all registrations for a user.

        Args:
            user_id: User UUID

        Returns:
            APIResponse with user data including registrations
        """
        response = self._http.get_sync(f"/api/user/{user_id}")
        if not response.success:
            return response

        registrations = response.data.get("user", {}).get("registrations", [])
        return APIResponse.ok(
            data={"registrations": registrations},
            status_code=200,
        )

    @requires_permission(Permission.REGISTRATIONS_READ)
    async def list_for_user_async(self, user_id: str) -> APIResponse:
        """Async version of list_for_user()."""
        response = await self._http.get(f"/api/user/{user_id}")
        if not response.success:
            return response

        registrations = response.data.get("user", {}).get("registrations", [])
        return APIResponse.ok(
            data={"registrations": registrations},
            status_code=200,
        )

    @requires_permission(Permission.REGISTRATIONS_READ)
    def search(
        self,
        application_id: Optional[str] = None,
        email: Optional[str] = None,
        username: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> APIResponse:
        """
        Search registrations.

        Args:
            application_id: Filter by application
            email: Filter by user email (partial match)
            username: Filter by username (partial match)
            limit: Maximum results
            offset: Pagination offset

        Returns:
            APIResponse with {"users": [...], "total": int}
        """
        query_parts = []

        if application_id:
            query_parts.append(f"registrations.applicationId:{application_id}")
        if email:
            query_parts.append(f"email:{email}")
        if username:
            query_parts.append(f"username:{username}")

        query_string = " AND ".join(query_parts) if query_parts else "*"

        return self._http.post_sync(
            "/api/user/search",
            json={
                "search": {
                    "queryString": query_string,
                    "numberOfResults": limit,
                    "startRow": offset,
                }
            },
        )

    @requires_permission(Permission.REGISTRATIONS_READ)
    async def search_async(
        self,
        application_id: Optional[str] = None,
        email: Optional[str] = None,
        username: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> APIResponse:
        """Async version of search()."""
        query_parts = []

        if application_id:
            query_parts.append(f"registrations.applicationId:{application_id}")
        if email:
            query_parts.append(f"email:{email}")
        if username:
            query_parts.append(f"username:{username}")

        query_string = " AND ".join(query_parts) if query_parts else "*"

        return await self._http.post(
            "/api/user/search",
            json={
                "search": {
                    "queryString": query_string,
                    "numberOfResults": limit,
                    "startRow": offset,
                }
            },
        )

    # ========================================================================
    # Create Operations (REGISTRATIONS_CREATE)
    # ========================================================================

    @requires_permission(Permission.REGISTRATIONS_CREATE)
    def create(
        self,
        user_id: str,
        app_id: str,
        roles: Optional[List[str]] = None,
        username: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        skip_registration_verification: bool = True,
    ) -> APIResponse:
        """
        Create a registration for a user.

        Args:
            user_id: User UUID
            app_id: Application UUID
            roles: List of application role names to assign
            username: Application-specific username
            data: Custom registration data
            skip_registration_verification: Skip email verification

        Returns:
            APIResponse with {"registration": {...}}
        """
        reg_data: Dict[str, Any] = {
            "applicationId": app_id,
        }

        if roles:
            reg_data["roles"] = roles
        if username:
            reg_data["username"] = username
        if data:
            reg_data["data"] = data

        return self._http.post_sync(
            f"/api/user/registration/{user_id}",
            json={
                "registration": reg_data,
                "skipRegistrationVerification": skip_registration_verification,
            },
        )

    @requires_permission(Permission.REGISTRATIONS_CREATE)
    async def create_async(
        self,
        user_id: str,
        app_id: str,
        roles: Optional[List[str]] = None,
        username: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        skip_registration_verification: bool = True,
    ) -> APIResponse:
        """Async version of create()."""
        reg_data: Dict[str, Any] = {
            "applicationId": app_id,
        }

        if roles:
            reg_data["roles"] = roles
        if username:
            reg_data["username"] = username
        if data:
            reg_data["data"] = data

        return await self._http.post(
            f"/api/user/registration/{user_id}",
            json={
                "registration": reg_data,
                "skipRegistrationVerification": skip_registration_verification,
            },
        )

    @requires_permission(Permission.REGISTRATIONS_CREATE)
    def register_with_roles(
        self,
        user_id: str,
        app_id: str,
        role_names: List[str],
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Register a user with specific roles.

        Convenience method for creating a registration with roles.

        Args:
            user_id: User UUID
            app_id: Application UUID
            role_names: List of role names to assign
            data: Custom registration data

        Returns:
            APIResponse with {"registration": {...}}
        """
        return self.create(
            user_id=user_id,
            app_id=app_id,
            roles=role_names,
            data=data,
        )

    @requires_permission(Permission.REGISTRATIONS_CREATE)
    async def register_with_roles_async(
        self,
        user_id: str,
        app_id: str,
        role_names: List[str],
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Async version of register_with_roles()."""
        return await self.create_async(
            user_id=user_id,
            app_id=app_id,
            roles=role_names,
            data=data,
        )

    # ========================================================================
    # Update Operations (REGISTRATIONS_UPDATE)
    # ========================================================================

    @requires_permission(Permission.REGISTRATIONS_UPDATE)
    def update(
        self,
        user_id: str,
        application_id: str,
        roles: Optional[List[str]] = None,
        username: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Update a user's registration.

        Args:
            user_id: User UUID
            application_id: Application UUID
            roles: Updated role names
            username: Updated username
            data: Updated custom data

        Returns:
            APIResponse with {"registration": {...}}
        """
        reg_data: Dict[str, Any] = {
            "applicationId": application_id,
        }

        if roles is not None:
            reg_data["roles"] = roles
        if username is not None:
            reg_data["username"] = username
        if data is not None:
            reg_data["data"] = data

        return self._http.patch_sync(
            f"/api/user/registration/{user_id}", json={"registration": reg_data}
        )

    @requires_permission(Permission.REGISTRATIONS_UPDATE)
    async def update_async(
        self,
        user_id: str,
        application_id: str,
        roles: Optional[List[str]] = None,
        username: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Async version of update()."""
        reg_data: Dict[str, Any] = {
            "applicationId": application_id,
        }

        if roles is not None:
            reg_data["roles"] = roles
        if username is not None:
            reg_data["username"] = username
        if data is not None:
            reg_data["data"] = data

        return await self._http.patch(
            f"/api/user/registration/{user_id}", json={"registration": reg_data}
        )

    @requires_permission(Permission.REGISTRATIONS_UPDATE)
    def add_roles(
        self,
        user_id: str,
        application_id: str,
        role_names: List[str],
    ) -> APIResponse:
        """
        Add roles to a user's registration.

        Args:
            user_id: User UUID
            application_id: Application UUID
            role_names: Role names to add

        Returns:
            APIResponse with {"registration": {...}}
        """
        # Get current roles
        response = self.get(user_id, application_id)
        if not response.success:
            return response

        current_roles = response.data.get("registration", {}).get("roles", [])
        new_roles = list(set(current_roles + role_names))

        return self.update(user_id, application_id, roles=new_roles)

    @requires_permission(Permission.REGISTRATIONS_UPDATE)
    async def add_roles_async(
        self,
        user_id: str,
        application_id: str,
        role_names: List[str],
    ) -> APIResponse:
        """Async version of add_roles()."""
        response = await self.get_async(user_id, application_id)
        if not response.success:
            return response

        current_roles = response.data.get("registration", {}).get("roles", [])
        new_roles = list(set(current_roles + role_names))

        return await self.update_async(user_id, application_id, roles=new_roles)

    @requires_permission(Permission.REGISTRATIONS_UPDATE)
    def remove_roles(
        self,
        user_id: str,
        application_id: str,
        role_names: List[str],
    ) -> APIResponse:
        """
        Remove roles from a user's registration.

        Args:
            user_id: User UUID
            application_id: Application UUID
            role_names: Role names to remove

        Returns:
            APIResponse with {"registration": {...}}
        """
        # Get current roles
        response = self.get(user_id, application_id)
        if not response.success:
            return response

        current_roles = response.data.get("registration", {}).get("roles", [])
        new_roles = [r for r in current_roles if r not in role_names]

        return self.update(user_id, application_id, roles=new_roles)

    @requires_permission(Permission.REGISTRATIONS_UPDATE)
    async def remove_roles_async(
        self,
        user_id: str,
        application_id: str,
        role_names: List[str],
    ) -> APIResponse:
        """Async version of remove_roles()."""
        response = await self.get_async(user_id, application_id)
        if not response.success:
            return response

        current_roles = response.data.get("registration", {}).get("roles", [])
        new_roles = [r for r in current_roles if r not in role_names]

        return await self.update_async(user_id, application_id, roles=new_roles)

    # ========================================================================
    # Delete Operations (REGISTRATIONS_DELETE)
    # ========================================================================

    @requires_permission(Permission.REGISTRATIONS_DELETE)
    def delete(
        self,
        user_id: str,
        application_id: str,
    ) -> APIResponse:
        """
        Delete a user's registration.

        Args:
            user_id: User UUID
            application_id: Application UUID

        Returns:
            APIResponse indicating success
        """
        return self._http.delete_sync(
            f"/api/user/registration/{user_id}/{application_id}"
        )

    @requires_permission(Permission.REGISTRATIONS_DELETE)
    async def delete_async(
        self,
        user_id: str,
        application_id: str,
    ) -> APIResponse:
        """Async version of delete()."""
        return await self._http.delete(
            f"/api/user/registration/{user_id}/{application_id}"
        )

    # ========================================================================
    # Bulk Operations
    # ========================================================================

    @requires_permission(Permission.REGISTRATIONS_CREATE)
    def bulk_register(
        self,
        user_ids: List[str],
        app_id: str,
        roles: Optional[List[str]] = None,
    ) -> APIResponse:
        """
        Register multiple users to an application.

        Args:
            user_ids: List of user UUIDs
            app_id: Application UUID
            roles: Roles to assign to all users

        Returns:
            APIResponse with {"results": [...]}
        """
        results = []
        errors = []

        for user_id in user_ids:
            response = self.create(user_id, app_id, roles=roles)
            if response.success:
                results.append(
                    {
                        "user_id": user_id,
                        "success": True,
                        "registration": response.data.get("registration"),
                    }
                )
            else:
                errors.append(
                    {
                        "user_id": user_id,
                        "success": False,
                        "error": response.error,
                    }
                )

        return APIResponse.ok(
            data={
                "results": results,
                "errors": errors,
                "total": len(user_ids),
                "successful": len(results),
                "failed": len(errors),
            },
            status_code=200,
        )

    @requires_permission(Permission.REGISTRATIONS_CREATE)
    async def bulk_register_async(
        self,
        user_ids: List[str],
        app_id: str,
        roles: Optional[List[str]] = None,
    ) -> APIResponse:
        """Async version of bulk_register()."""
        import asyncio

        async def register_one(user_id: str):
            response = await self.create_async(user_id, app_id, roles=roles)
            return user_id, response

        tasks = [register_one(uid) for uid in user_ids]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        errors = []

        for item in completed:
            if isinstance(item, Exception):
                errors.append(
                    {
                        "success": False,
                        "error": str(item),
                    }
                )
            else:
                user_id, response = item
                if response.success:
                    results.append(
                        {
                            "user_id": user_id,
                            "success": True,
                            "registration": response.data.get("registration"),
                        }
                    )
                else:
                    errors.append(
                        {
                            "user_id": user_id,
                            "success": False,
                            "error": response.error,
                        }
                    )

        return APIResponse.ok(
            data={
                "results": results,
                "errors": errors,
                "total": len(user_ids),
                "successful": len(results),
                "failed": len(errors),
            },
            status_code=200,
        )
