"""
Users Service for FusionAuth user management.

Provides CRUD operations for users with permission enforcement.
"""

from typing import Optional, Dict, Any

from .base import BaseService
from ..models import APIResponse, Permission
from ..permissions import requires_permission


class UsersService(BaseService):
    """
    Service for managing FusionAuth users.

    Methods are protected by permission decorators that check
    the user's role before allowing the operation.

    Example:
        # List users (requires USERS_READ)
        users = sdk.users.list()

        # Create user (requires USERS_CREATE)
        user = sdk.users.create(email="user@example.com", password="secret")
    """

    # ========================================================================
    # Read Operations (USERS_READ)
    # ========================================================================

    @requires_permission(Permission.USERS_READ)
    def list(
        self,
        limit: int = 25,
        offset: int = 0,
    ) -> APIResponse:
        """
        List all users.

        Args:
            limit: Maximum users to return (default 25)
            offset: Offset for pagination

        Returns:
            APIResponse with {"users": [...], "total": int}
        """
        response = self._http.get_sync(
            "/api/user/search",
            params={
                "queryString": "*",
                "numberOfResults": limit,
                "startRow": offset,
            },
        )
        return response

    @requires_permission(Permission.USERS_READ)
    async def list_async(
        self,
        limit: int = 25,
        offset: int = 0,
    ) -> APIResponse:
        """Async version of list()."""
        response = await self._http.get(
            "/api/user/search",
            params={
                "queryString": "*",
                "numberOfResults": limit,
                "startRow": offset,
            },
        )
        return response

    @requires_permission(Permission.USERS_READ)
    def get(
        self,
        user_id: Optional[str] = None,
        email: Optional[str] = None,
    ) -> APIResponse:
        """
        Get a user by ID or email.

        Args:
            user_id: User UUID
            email: User email address

        Returns:
            APIResponse with {"user": {...}}
        """
        if not user_id and not email:
            return APIResponse.fail("Either user_id or email is required")

        if user_id:
            return self._http.get_sync(f"/api/user/{user_id}")
        else:
            return self._http.get_sync("/api/user", params={"email": email})

    @requires_permission(Permission.USERS_READ)
    async def get_async(
        self,
        user_id: Optional[str] = None,
        email: Optional[str] = None,
    ) -> APIResponse:
        """Async version of get()."""
        if not user_id and not email:
            return APIResponse.fail("Either user_id or email is required")

        if user_id:
            return await self._http.get(f"/api/user/{user_id}")
        else:
            return await self._http.get("/api/user", params={"email": email})

    @requires_permission(Permission.USERS_READ)
    def search(
        self,
        query: str,
        limit: int = 25,
        offset: int = 0,
    ) -> APIResponse:
        """
        Search users by query string.

        Args:
            query: Search query (supports wildcards)
            limit: Maximum results
            offset: Pagination offset

        Returns:
            APIResponse with {"users": [...], "total": int}
        """
        return self._http.post_sync(
            "/api/user/search",
            json={
                "search": {
                    "queryString": f"*{query}*",
                    "numberOfResults": limit,
                    "startRow": offset,
                }
            },
        )

    @requires_permission(Permission.USERS_READ)
    async def search_async(
        self,
        query: str,
        limit: int = 25,
        offset: int = 0,
    ) -> APIResponse:
        """Async version of search()."""
        return await self._http.post(
            "/api/user/search",
            json={
                "search": {
                    "queryString": f"*{query}*",
                    "numberOfResults": limit,
                    "startRow": offset,
                }
            },
        )

    # ========================================================================
    # Create Operations (USERS_CREATE)
    # ========================================================================

    @requires_permission(Permission.USERS_CREATE)
    def create(
        self,
        email: str,
        password: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        username: Optional[str] = None,
        send_set_password_email: bool = False,
        skip_verification: bool = True,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Create a new user.

        Args:
            email: User email address (required)
            password: User password (optional if send_set_password_email=True)
            first_name: First name
            last_name: Last name
            username: Username
            send_set_password_email: Send password setup email
            skip_verification: Skip email verification
            data: Custom user data

        Returns:
            APIResponse with {"user": {...}}
        """
        user_data: Dict[str, Any] = {"email": email}

        if password:
            user_data["password"] = password
        if first_name:
            user_data["firstName"] = first_name
        if last_name:
            user_data["lastName"] = last_name
        if username:
            user_data["username"] = username
        if data:
            user_data["data"] = data

        return self._http.post_sync(
            "/api/user",
            json={
                "user": user_data,
                "sendSetPasswordEmail": send_set_password_email,
                "skipVerification": skip_verification,
            },
        )

    @requires_permission(Permission.USERS_CREATE)
    async def create_async(
        self,
        email: str,
        password: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        username: Optional[str] = None,
        send_set_password_email: bool = False,
        skip_verification: bool = True,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Async version of create()."""
        user_data: Dict[str, Any] = {"email": email}

        if password:
            user_data["password"] = password
        if first_name:
            user_data["firstName"] = first_name
        if last_name:
            user_data["lastName"] = last_name
        if username:
            user_data["username"] = username
        if data:
            user_data["data"] = data

        return await self._http.post(
            "/api/user",
            json={
                "user": user_data,
                "sendSetPasswordEmail": send_set_password_email,
                "skipVerification": skip_verification,
            },
        )

    # ========================================================================
    # Update Operations (USERS_UPDATE)
    # ========================================================================

    @requires_permission(Permission.USERS_UPDATE)
    def update(
        self,
        user_id: str,
        email: Optional[str] = None,
        password: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        full_name: Optional[str] = None,
        mobile_phone: Optional[str] = None,
        active: Optional[bool] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Update an existing user.

        Args:
            user_id: User UUID (required)
            email: New email address
            password: New password
            first_name: New first name
            last_name: New last name
            full_name: Full name
            mobile_phone: Mobile phone number
            active: Account active status
            data: Custom data to merge

        Returns:
            APIResponse with {"user": {...}}
        """
        user_data: Dict[str, Any] = {}

        if email is not None:
            user_data["email"] = email
        if password is not None:
            user_data["password"] = password
        if first_name is not None:
            user_data["firstName"] = first_name
        if last_name is not None:
            user_data["lastName"] = last_name
        if full_name is not None:
            user_data["fullName"] = full_name
        if mobile_phone is not None:
            user_data["mobilePhone"] = mobile_phone
        if active is not None:
            user_data["active"] = active
        if data is not None:
            user_data["data"] = data

        if not user_data:
            return APIResponse.fail("No update fields provided")

        return self._http.patch_sync(f"/api/user/{user_id}", json={"user": user_data})

    @requires_permission(Permission.USERS_UPDATE)
    async def update_async(
        self,
        user_id: str,
        email: Optional[str] = None,
        password: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        full_name: Optional[str] = None,
        mobile_phone: Optional[str] = None,
        active: Optional[bool] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Async version of update()."""
        user_data: Dict[str, Any] = {}

        if email is not None:
            user_data["email"] = email
        if password is not None:
            user_data["password"] = password
        if first_name is not None:
            user_data["firstName"] = first_name
        if last_name is not None:
            user_data["lastName"] = last_name
        if full_name is not None:
            user_data["fullName"] = full_name
        if mobile_phone is not None:
            user_data["mobilePhone"] = mobile_phone
        if active is not None:
            user_data["active"] = active
        if data is not None:
            user_data["data"] = data

        if not user_data:
            return APIResponse.fail("No update fields provided")

        return await self._http.patch(f"/api/user/{user_id}", json={"user": user_data})

    # ========================================================================
    # Delete Operations (USERS_DELETE)
    # ========================================================================

    @requires_permission(Permission.USERS_DELETE)
    def delete(
        self,
        user_id: str,
        hard_delete: bool = False,
    ) -> APIResponse:
        """
        Delete a user.

        Args:
            user_id: User UUID
            hard_delete: If True, permanently delete. If False, soft delete.

        Returns:
            APIResponse indicating success
        """
        params = {}
        if hard_delete:
            params["hardDelete"] = "true"

        return self._http.delete_sync(
            f"/api/user/{user_id}", params=params if params else None
        )

    @requires_permission(Permission.USERS_DELETE)
    async def delete_async(
        self,
        user_id: str,
        hard_delete: bool = False,
    ) -> APIResponse:
        """Async version of delete()."""
        params = {}
        if hard_delete:
            params["hardDelete"] = "true"

        return await self._http.delete(
            f"/api/user/{user_id}", params=params if params else None
        )
