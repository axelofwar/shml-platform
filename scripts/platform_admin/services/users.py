"""
Users service module for FusionAuth user management.

Provides CRUD operations for FusionAuth users.
"""

from typing import Optional, List, Dict, Any

# Import from parent to avoid circular imports
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class UsersService:
    """
    Service for managing FusionAuth users.

    Provides listing, searching, creation, updating, and deletion of users.
    All methods return APIResponse objects for consistent error handling.
    """

    def __init__(self, api):
        """
        Initialize the users service.

        Args:
            api: FusionAuthClient instance
        """
        self._api = api

    def list(self, query: Optional[str] = None, limit: int = 25, offset: int = 0):
        """
        List users with optional search query.

        Args:
            query: Search query (email, username, name). Use "*" for all.
            limit: Maximum results to return
            offset: Pagination offset

        Returns:
            APIResponse with {"users": [...]} data
        """
        search_query = query if query else "*"

        return self._api.post(
            "/api/user/search",
            {
                "search": {
                    "queryString": search_query,
                    "numberOfResults": limit,
                    "startRow": offset,
                    "sortFields": [{"name": "email"}],
                }
            },
        )

    def search(self, query: str, limit: int = 25):
        """
        Search for users by query string.

        Args:
            query: Search query (matches email, name, username)
            limit: Maximum results

        Returns:
            APIResponse with {"users": [...]} data
        """
        return self.list(query=query, limit=limit)

    def get(self, user_id: Optional[str] = None, email: Optional[str] = None):
        """
        Get a user by ID or email.

        Args:
            user_id: User UUID
            email: User email address

        Returns:
            APIResponse with {"user": {...}} data
        """
        from ..client import APIResponse

        if user_id:
            return self._api.get(f"/api/user/{user_id}")
        elif email:
            return self._api.get("/api/user", params={"email": email})
        else:
            return APIResponse(
                success=False,
                status_code=400,
                error="Either user_id or email is required",
            )

    def create(
        self,
        email: str,
        password: str,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        send_set_password_email: bool = False,
        skip_verification: bool = True,
    ):
        """
        Create a new user.

        Args:
            email: User email address
            password: Initial password
            username: Optional username
            first_name: Optional first name
            last_name: Optional last name
            send_set_password_email: Send password setup email
            skip_verification: Skip email verification

        Returns:
            APIResponse with {"user": {...}} data
        """
        user_data = {
            "email": email,
            "password": password,
        }

        if username:
            user_data["username"] = username
        if first_name:
            user_data["firstName"] = first_name
        if last_name:
            user_data["lastName"] = last_name

        return self._api.post(
            "/api/user",
            {
                "user": user_data,
                "sendSetPasswordEmail": send_set_password_email,
                "skipVerification": skip_verification,
            },
        )

    def update(
        self,
        user_id: str,
        email: Optional[str] = None,
        password: Optional[str] = None,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        active: Optional[bool] = None,
        mobile_phone: Optional[str] = None,
        full_name: Optional[str] = None,
    ):
        """
        Update an existing user.

        Args:
            user_id: User UUID to update
            email: New email address
            password: New password
            username: New username
            first_name: New first name
            last_name: New last name
            active: Account active status
            mobile_phone: Mobile phone number
            full_name: Full name

        Returns:
            APIResponse with {"user": {...}} data
        """
        from ..client import APIResponse

        user_data = {}

        if email is not None:
            user_data["email"] = email
        if password is not None:
            user_data["password"] = password
        if username is not None:
            user_data["username"] = username
        if first_name is not None:
            user_data["firstName"] = first_name
        if last_name is not None:
            user_data["lastName"] = last_name
        if active is not None:
            user_data["active"] = active
        if mobile_phone is not None:
            user_data["mobilePhone"] = mobile_phone
        if full_name is not None:
            user_data["fullName"] = full_name

        if not user_data:
            return APIResponse(
                success=False, status_code=400, error="No update fields provided"
            )

        return self._api.patch(f"/api/user/{user_id}", {"user": user_data})

    def delete(self, user_id: str, hard_delete: bool = False):
        """
        Delete a user.

        Args:
            user_id: User UUID to delete
            hard_delete: If True, permanently delete. If False, soft delete.

        Returns:
            APIResponse indicating success or failure
        """
        params = {}
        if hard_delete:
            params["hardDelete"] = "true"

        return self._api.delete(
            f"/api/user/{user_id}", params=params if params else None
        )

    def deactivate(self, user_id: str):
        """
        Deactivate a user account.

        Args:
            user_id: User UUID

        Returns:
            APIResponse indicating success or failure
        """
        return self._api.delete(f"/api/user/{user_id}")

    def reactivate(self, user_id: str):
        """
        Reactivate a previously deactivated user.

        Args:
            user_id: User UUID

        Returns:
            APIResponse indicating success or failure
        """
        return self._api.put(f"/api/user/{user_id}?reactivate=true", {})
