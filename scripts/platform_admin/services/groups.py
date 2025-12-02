"""
Groups service module for FusionAuth group management.

Groups are used to organize users and can be mapped to
application roles for access control.
"""

from typing import Optional, List, Dict, Any


class GroupsService:
    """
    Service for managing FusionAuth groups.

    Provides listing, creation, updating, and member management for groups.
    All methods return APIResponse objects for consistent error handling.
    """

    def __init__(self, api):
        """
        Initialize the groups service.

        Args:
            api: FusionAuthClient instance
        """
        self._api = api
        self._cache: Optional[Dict[str, Dict]] = None

    def list(self):
        """
        List all groups.

        Returns:
            APIResponse with {"groups": [...]} data
        """
        response = self._api.get("/api/group")
        if response.success and response.data:
            self._update_cache(response.data)
        return response

    def _update_cache(self, data: Dict) -> None:
        """Update internal cache of groups."""
        if data and "groups" in data:
            self._cache = {g["name"]: g for g in data["groups"]}

    def get_by_name(self, name: str):
        """
        Get a group by name.

        Args:
            name: Group name

        Returns:
            APIResponse with {"group": {...}} data
        """
        from ..client import APIResponse

        # Try cache first
        if self._cache and name in self._cache:
            return APIResponse(
                success=True, status_code=200, data={"group": self._cache[name]}
            )

        # Fetch all and search
        response = self.list()
        if not response.success:
            return response

        groups = response.data.get("groups", [])
        for group in groups:
            if group.get("name") == name:
                return APIResponse(success=True, status_code=200, data={"group": group})

        return APIResponse(
            success=False, status_code=404, error=f"Group '{name}' not found"
        )

    def get(self, group_id: str):
        """
        Get a group by ID.

        Args:
            group_id: Group UUID

        Returns:
            APIResponse with {"group": {...}} data
        """
        return self._api.get(f"/api/group/{group_id}")

    def create(
        self,
        name: str,
        description: Optional[str] = None,
        role_ids: Optional[List[str]] = None,
    ):
        """
        Create a new group.

        Args:
            name: Group name
            description: Optional description
            role_ids: Optional list of role IDs to assign to group members

        Returns:
            APIResponse with {"group": {...}} data
        """
        group_data = {"name": name}

        if description:
            group_data["data"] = {"description": description}

        request_body = {"group": group_data}

        if role_ids:
            request_body["roleIds"] = role_ids

        response = self._api.post("/api/group", request_body)

        # Invalidate cache on successful create
        if response.success:
            self._cache = None

        return response

    def update(
        self,
        group_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        role_ids: Optional[List[str]] = None,
    ):
        """
        Update an existing group.

        Args:
            group_id: Group UUID
            name: New group name
            description: New description
            role_ids: New list of role IDs

        Returns:
            APIResponse with {"group": {...}} data
        """
        group_data = {}

        if name is not None:
            group_data["name"] = name
        if description is not None:
            group_data["data"] = {"description": description}

        request_body = {"group": group_data}

        if role_ids is not None:
            request_body["roleIds"] = role_ids

        response = self._api.patch(f"/api/group/{group_id}", request_body)

        # Invalidate cache on successful update
        if response.success:
            self._cache = None

        return response

    def delete(self, group_id: str):
        """
        Delete a group.

        Args:
            group_id: Group UUID

        Returns:
            APIResponse indicating success or failure
        """
        response = self._api.delete(f"/api/group/{group_id}")

        # Invalidate cache on successful delete
        if response.success:
            self._cache = None

        return response

    def add_member(self, group_id: str, user_id: str):
        """
        Add a user to a group.

        Args:
            group_id: Group UUID
            user_id: User UUID to add

        Returns:
            APIResponse indicating success or failure
        """
        # FusionAuth expects: {"members": {"group_id": [{"userId": "user_id"}]}}
        return self._api.post(
            "/api/group/member", {"members": {group_id: [{"userId": user_id}]}}
        )

    def add_member_by_name(self, group_name: str, user_id: str):
        """
        Add a user to a group by group name.

        Args:
            group_name: Group name
            user_id: User UUID to add

        Returns:
            APIResponse indicating success or failure
        """
        # Get group ID
        response = self.get_by_name(group_name)
        if not response.success:
            return response

        group = response.data.get("group", {})
        group_id = group.get("id")
        if not group_id:
            from ..client import APIResponse

            return APIResponse(
                success=False, status_code=404, error=f"Group '{group_name}' not found"
            )

        return self.add_member(group_id, user_id)

    def remove_member(self, group_id: str, user_id: str):
        """
        Remove a user from a group.

        Args:
            group_id: Group UUID
            user_id: User UUID to remove

        Returns:
            APIResponse indicating success or failure
        """
        return self._api.delete(
            f"/api/group/member", params={"groupId": group_id, "userId": user_id}
        )

    def get_members(self, group_id: str):
        """
        Get all members of a group.

        Args:
            group_id: Group UUID

        Returns:
            APIResponse with member list
        """
        return self._api.get(f"/api/group/{group_id}/member")
