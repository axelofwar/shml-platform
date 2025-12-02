"""
Groups Service for FusionAuth group management.

Provides CRUD operations for groups with permission enforcement.
"""

from typing import Optional, List, Dict, Any

from .base import BaseService
from ..models import APIResponse, Permission
from ..permissions import requires_permission


class GroupsService(BaseService):
    """
    Service for managing FusionAuth groups.

    Groups organize users and can assign application roles
    to all members automatically.
    """

    # Cache for group lookups
    _cache: Optional[Dict[str, Dict[str, Any]]] = None

    def _invalidate_cache(self) -> None:
        """Invalidate the groups cache."""
        self._cache = None

    # ========================================================================
    # Read Operations (GROUPS_READ)
    # ========================================================================

    @requires_permission(Permission.GROUPS_READ)
    def list(self) -> APIResponse:
        """
        List all groups.

        Returns:
            APIResponse with {"groups": [...]}
        """
        return self._http.get_sync("/api/group")

    @requires_permission(Permission.GROUPS_READ)
    async def list_async(self) -> APIResponse:
        """Async version of list()."""
        return await self._http.get("/api/group")

    @requires_permission(Permission.GROUPS_READ)
    def get(self, group_id: str) -> APIResponse:
        """
        Get a group by ID.

        Args:
            group_id: Group UUID

        Returns:
            APIResponse with {"group": {...}}
        """
        return self._http.get_sync(f"/api/group/{group_id}")

    @requires_permission(Permission.GROUPS_READ)
    async def get_async(self, group_id: str) -> APIResponse:
        """Async version of get()."""
        return await self._http.get(f"/api/group/{group_id}")

    @requires_permission(Permission.GROUPS_READ)
    def get_by_name(self, name: str) -> APIResponse:
        """
        Get a group by name.

        Args:
            name: Group name

        Returns:
            APIResponse with {"group": {...}} or error if not found
        """
        response = self.list()
        if not response.success:
            return response

        groups = response.data.get("groups", [])
        for group in groups:
            if group.get("name") == name:
                return APIResponse.ok(
                    data={"group": group},
                    status_code=200,
                )

        return APIResponse.fail(
            error=f"Group '{name}' not found",
            status_code=404,
        )

    @requires_permission(Permission.GROUPS_READ)
    async def get_by_name_async(self, name: str) -> APIResponse:
        """Async version of get_by_name()."""
        response = await self.list_async()
        if not response.success:
            return response

        groups = response.data.get("groups", [])
        for group in groups:
            if group.get("name") == name:
                return APIResponse.ok(
                    data={"group": group},
                    status_code=200,
                )

        return APIResponse.fail(
            error=f"Group '{name}' not found",
            status_code=404,
        )

    @requires_permission(Permission.GROUPS_READ)
    def search(
        self,
        name: str,
        limit: int = 25,
        offset: int = 0,
    ) -> APIResponse:
        """
        Search groups by name.

        Args:
            name: Name pattern (supports wildcards *)
            limit: Maximum results
            offset: Pagination offset

        Returns:
            APIResponse with {"groups": [...], "total": int}
        """
        return self._http.get_sync(
            "/api/group/search",
            params={
                "name": name,
                "numberOfResults": limit,
                "startRow": offset,
            },
        )

    @requires_permission(Permission.GROUPS_READ)
    async def search_async(
        self,
        name: str,
        limit: int = 25,
        offset: int = 0,
    ) -> APIResponse:
        """Async version of search()."""
        return await self._http.get(
            "/api/group/search",
            params={
                "name": name,
                "numberOfResults": limit,
                "startRow": offset,
            },
        )

    @requires_permission(Permission.GROUPS_READ)
    def get_members(self, group_id: str) -> APIResponse:
        """
        Get all members of a group.

        Args:
            group_id: Group UUID

        Returns:
            APIResponse with {"members": [...]}
        """
        return self._http.get_sync(
            "/api/group/member/search", params={"groupId": group_id}
        )

    @requires_permission(Permission.GROUPS_READ)
    async def get_members_async(self, group_id: str) -> APIResponse:
        """Async version of get_members()."""
        return await self._http.get(
            "/api/group/member/search", params={"groupId": group_id}
        )

    # ========================================================================
    # Create Operations (GROUPS_CREATE)
    # ========================================================================

    @requires_permission(Permission.GROUPS_CREATE)
    def create(
        self,
        name: str,
        description: Optional[str] = None,
        role_ids: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Create a new group.

        Args:
            name: Group name
            description: Optional description
            role_ids: Application role IDs to assign
            data: Custom group data

        Returns:
            APIResponse with {"group": {...}}
        """
        group_data: Dict[str, Any] = {"name": name}

        if description or data:
            group_data["data"] = data or {}
            if description:
                group_data["data"]["description"] = description

        request_body: Dict[str, Any] = {"group": group_data}

        if role_ids:
            request_body["roleIds"] = role_ids

        response = self._http.post_sync("/api/group", json=request_body)

        if response.success:
            self._invalidate_cache()

        return response

    @requires_permission(Permission.GROUPS_CREATE)
    async def create_async(
        self,
        name: str,
        description: Optional[str] = None,
        role_ids: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Async version of create()."""
        group_data: Dict[str, Any] = {"name": name}

        if description or data:
            group_data["data"] = data or {}
            if description:
                group_data["data"]["description"] = description

        request_body: Dict[str, Any] = {"group": group_data}

        if role_ids:
            request_body["roleIds"] = role_ids

        response = await self._http.post("/api/group", json=request_body)

        if response.success:
            self._invalidate_cache()

        return response

    # ========================================================================
    # Update Operations (GROUPS_UPDATE)
    # ========================================================================

    @requires_permission(Permission.GROUPS_UPDATE)
    def update(
        self,
        group_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        role_ids: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Update a group.

        Args:
            group_id: Group UUID
            name: New name
            description: New description
            role_ids: New role assignments
            data: New custom data

        Returns:
            APIResponse with {"group": {...}}
        """
        group_data: Dict[str, Any] = {}

        if name is not None:
            group_data["name"] = name
        if description is not None or data is not None:
            group_data["data"] = data or {}
            if description is not None:
                group_data["data"]["description"] = description

        request_body: Dict[str, Any] = {"group": group_data}

        if role_ids is not None:
            request_body["roleIds"] = role_ids

        response = self._http.patch_sync(f"/api/group/{group_id}", json=request_body)

        if response.success:
            self._invalidate_cache()

        return response

    @requires_permission(Permission.GROUPS_UPDATE)
    async def update_async(
        self,
        group_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        role_ids: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Async version of update()."""
        group_data: Dict[str, Any] = {}

        if name is not None:
            group_data["name"] = name
        if description is not None or data is not None:
            group_data["data"] = data or {}
            if description is not None:
                group_data["data"]["description"] = description

        request_body: Dict[str, Any] = {"group": group_data}

        if role_ids is not None:
            request_body["roleIds"] = role_ids

        response = await self._http.patch(f"/api/group/{group_id}", json=request_body)

        if response.success:
            self._invalidate_cache()

        return response

    # ========================================================================
    # Delete Operations (GROUPS_DELETE)
    # ========================================================================

    @requires_permission(Permission.GROUPS_DELETE)
    def delete(self, group_id: str) -> APIResponse:
        """
        Delete a group.

        Args:
            group_id: Group UUID

        Returns:
            APIResponse indicating success
        """
        response = self._http.delete_sync(f"/api/group/{group_id}")

        if response.success:
            self._invalidate_cache()

        return response

    @requires_permission(Permission.GROUPS_DELETE)
    async def delete_async(self, group_id: str) -> APIResponse:
        """Async version of delete()."""
        response = await self._http.delete(f"/api/group/{group_id}")

        if response.success:
            self._invalidate_cache()

        return response

    # ========================================================================
    # Member Management (GROUPS_MANAGE_MEMBERS)
    # ========================================================================

    @requires_permission(Permission.GROUPS_MANAGE_MEMBERS)
    def add_member(
        self,
        group_id: str,
        user_id: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Add a user to a group.

        Args:
            group_id: Group UUID
            user_id: User UUID
            data: Optional member data

        Returns:
            APIResponse with {"members": {...}}
        """
        member_data: Dict[str, Any] = {"userId": user_id}
        if data:
            member_data["data"] = data

        return self._http.post_sync(
            "/api/group/member", json={"members": {group_id: [member_data]}}
        )

    @requires_permission(Permission.GROUPS_MANAGE_MEMBERS)
    async def add_member_async(
        self,
        group_id: str,
        user_id: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Async version of add_member()."""
        member_data: Dict[str, Any] = {"userId": user_id}
        if data:
            member_data["data"] = data

        return await self._http.post(
            "/api/group/member", json={"members": {group_id: [member_data]}}
        )

    @requires_permission(Permission.GROUPS_MANAGE_MEMBERS)
    def remove_member(
        self,
        group_id: str,
        user_id: str,
    ) -> APIResponse:
        """
        Remove a user from a group.

        Args:
            group_id: Group UUID
            user_id: User UUID

        Returns:
            APIResponse indicating success
        """
        return self._http.delete_sync(
            "/api/group/member", params={"groupId": group_id, "userId": user_id}
        )

    @requires_permission(Permission.GROUPS_MANAGE_MEMBERS)
    async def remove_member_async(
        self,
        group_id: str,
        user_id: str,
    ) -> APIResponse:
        """Async version of remove_member()."""
        return await self._http.delete(
            "/api/group/member", params={"groupId": group_id, "userId": user_id}
        )

    @requires_permission(Permission.GROUPS_MANAGE_MEMBERS)
    def add_member_by_name(
        self,
        group_name: str,
        user_id: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Add a user to a group by group name.

        Args:
            group_name: Group name
            user_id: User UUID
            data: Optional member data

        Returns:
            APIResponse with {"members": {...}}
        """
        group_response = self.get_by_name(group_name)
        if not group_response.success:
            return group_response

        group_id = group_response.data.get("group", {}).get("id")
        if not group_id:
            return APIResponse.fail(
                error=f"Group '{group_name}' not found",
                status_code=404,
            )

        return self.add_member(group_id, user_id, data)

    @requires_permission(Permission.GROUPS_MANAGE_MEMBERS)
    async def add_member_by_name_async(
        self,
        group_name: str,
        user_id: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Async version of add_member_by_name()."""
        group_response = await self.get_by_name_async(group_name)
        if not group_response.success:
            return group_response

        group_id = group_response.data.get("group", {}).get("id")
        if not group_id:
            return APIResponse.fail(
                error=f"Group '{group_name}' not found",
                status_code=404,
            )

        return await self.add_member_async(group_id, user_id, data)
