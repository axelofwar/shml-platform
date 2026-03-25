from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_client_root = _repo_root / "libs" / "client"
if str(_client_root) not in sys.path:
    sys.path.insert(0, str(_client_root))

from shml.admin.models import APIResponse, Role  # noqa: E402
from shml.admin.permissions import PermissionContext  # noqa: E402
from shml.admin.services.roles import RolesService  # noqa: E402
from shml.admin.services.users import UsersService  # noqa: E402


def _admin_ctx() -> PermissionContext:
    return PermissionContext(role=Role.ADMIN)


def _make_http() -> MagicMock:
    http = MagicMock()
    http.get = AsyncMock()
    http.post = AsyncMock()
    http.patch = AsyncMock()
    http.delete = AsyncMock()
    return http


def _users_service() -> UsersService:
    return UsersService(http_client=_make_http(), permission_context=_admin_ctx())


def _roles_service() -> RolesService:
    return RolesService(http_client=_make_http(), permission_context=_admin_ctx())


class TestUsersServiceSync:
    def test_list_builds_search_params(self):
        service = _users_service()
        service._http.get_sync.return_value = APIResponse.ok(data={"users": []})

        result = service.list(limit=10, offset=5)

        assert result.success is True
        service._http.get_sync.assert_called_once_with(
            "/api/user/search",
            params={"queryString": "*", "numberOfResults": 10, "startRow": 5},
        )

    def test_get_requires_user_id_or_email(self):
        service = _users_service()

        result = service.get()

        assert result.success is False
        assert result.error == "Either user_id or email is required"

    def test_get_prefers_user_id_endpoint(self):
        service = _users_service()
        service._http.get_sync.return_value = APIResponse.ok(data={"user": {"id": "user-1"}})

        result = service.get(user_id="user-1", email="user@example.com")

        assert result.success is True
        service._http.get_sync.assert_called_once_with("/api/user/user-1")

    def test_get_by_email_uses_query_param(self):
        service = _users_service()
        service._http.get_sync.return_value = APIResponse.ok(data={"user": {"email": "user@example.com"}})

        service.get(email="user@example.com")

        service._http.get_sync.assert_called_once_with("/api/user", params={"email": "user@example.com"})

    def test_list_uses_default_params(self):
        service = _users_service()
        service._http.get_sync.return_value = APIResponse.ok(data={"users": []})

        service.list()

        service._http.get_sync.assert_called_once_with(
            "/api/user/search",
            params={"queryString": "*", "numberOfResults": 25, "startRow": 0},
        )

    def test_search_wraps_query_with_wildcards(self):
        service = _users_service()
        service._http.post_sync.return_value = APIResponse.ok(data={})

        service.search("alice", limit=8, offset=2)

        service._http.post_sync.assert_called_once_with(
            "/api/user/search",
            json={"search": {"queryString": "*alice*", "numberOfResults": 8, "startRow": 2}},
        )

    def test_create_builds_full_payload(self):
        service = _users_service()
        service._http.post_sync.return_value = APIResponse.ok(data={})

        service.create(
            "user@example.com",
            password="secret",
            first_name="Alice",
            last_name="Doe",
            username="alice",
            send_set_password_email=True,
            skip_verification=False,
            data={"team": "ml"},
        )

        service._http.post_sync.assert_called_once_with(
            "/api/user",
            json={
                "user": {
                    "email": "user@example.com",
                    "password": "secret",
                    "firstName": "Alice",
                    "lastName": "Doe",
                    "username": "alice",
                    "data": {"team": "ml"},
                },
                "sendSetPasswordEmail": True,
                "skipVerification": False,
            },
        )

    def test_update_requires_fields(self):
        service = _users_service()

        result = service.update("user-1")

        assert result.success is False
        assert result.error == "No update fields provided"

    def test_update_builds_partial_payload(self):
        service = _users_service()
        service._http.patch_sync.return_value = APIResponse.ok(data={})

        service.update(
            "user-1",
            email="new@example.com",
            full_name="Alice Doe",
            mobile_phone="123",
            active=False,
            data={"region": "us"},
        )

        service._http.patch_sync.assert_called_once_with(
            "/api/user/user-1",
            json={
                "user": {
                    "email": "new@example.com",
                    "fullName": "Alice Doe",
                    "mobilePhone": "123",
                    "active": False,
                    "data": {"region": "us"},
                }
            },
        )

    def test_delete_uses_hard_delete_param(self):
        service = _users_service()
        service._http.delete_sync.return_value = APIResponse.ok(data={})

        service.delete("user-1", hard_delete=True)

        service._http.delete_sync.assert_called_once_with(
            "/api/user/user-1",
            params={"hardDelete": "true"},
        )

    def test_delete_without_hard_delete_uses_none_params(self):
        service = _users_service()
        service._http.delete_sync.return_value = APIResponse.ok(data={})

        service.delete("user-1")

        service._http.delete_sync.assert_called_once_with("/api/user/user-1", params=None)


class TestUsersServiceAsync:
    @pytest.mark.asyncio
    async def test_list_async_builds_search_params(self):
        service = _users_service()
        service._http.get.return_value = APIResponse.ok(data={"users": []})

        result = await service.list_async(limit=3, offset=1)

        assert result.success is True
        service._http.get.assert_awaited_once_with(
            "/api/user/search",
            params={"queryString": "*", "numberOfResults": 3, "startRow": 1},
        )

    @pytest.mark.asyncio
    async def test_get_async_requires_user_id_or_email(self):
        service = _users_service()

        result = await service.get_async()

        assert result.success is False
        assert result.error == "Either user_id or email is required"

    @pytest.mark.asyncio
    async def test_get_async_prefers_user_id_endpoint(self):
        service = _users_service()
        service._http.get.return_value = APIResponse.ok(data={"user": {"id": "user-1"}})

        result = await service.get_async(user_id="user-1", email="user@example.com")

        assert result.success is True
        service._http.get.assert_awaited_once_with("/api/user/user-1")

    @pytest.mark.asyncio
    async def test_get_async_by_email_uses_query_param(self):
        service = _users_service()
        service._http.get.return_value = APIResponse.ok(data={"user": {"email": "user@example.com"}})

        await service.get_async(email="user@example.com")

        service._http.get.assert_awaited_once_with("/api/user", params={"email": "user@example.com"})

    @pytest.mark.asyncio
    async def test_search_async_wraps_query_with_wildcards(self):
        service = _users_service()
        service._http.post.return_value = APIResponse.ok(data={})

        await service.search_async("bob")

        service._http.post.assert_awaited_once_with(
            "/api/user/search",
            json={"search": {"queryString": "*bob*", "numberOfResults": 25, "startRow": 0}},
        )

    @pytest.mark.asyncio
    async def test_create_async_minimal_payload(self):
        service = _users_service()
        service._http.post.return_value = APIResponse.ok(data={})

        await service.create_async("user@example.com")

        service._http.post.assert_awaited_once_with(
            "/api/user",
            json={
                "user": {"email": "user@example.com"},
                "sendSetPasswordEmail": False,
                "skipVerification": True,
            },
        )

    @pytest.mark.asyncio
    async def test_update_async_requires_fields(self):
        service = _users_service()

        result = await service.update_async("user-1")

        assert result.success is False
        assert result.error == "No update fields provided"

    @pytest.mark.asyncio
    async def test_update_async_builds_full_payload(self):
        service = _users_service()
        service._http.patch.return_value = APIResponse.ok(data={})

        await service.update_async(
            "user-1",
            email="new@example.com",
            password="secret",
            first_name="Alice",
            last_name="Doe",
            full_name="Alice Doe",
            mobile_phone="123",
            active=True,
            data={"region": "us"},
        )

        service._http.patch.assert_awaited_once_with(
            "/api/user/user-1",
            json={
                "user": {
                    "email": "new@example.com",
                    "password": "secret",
                    "firstName": "Alice",
                    "lastName": "Doe",
                    "fullName": "Alice Doe",
                    "mobilePhone": "123",
                    "active": True,
                    "data": {"region": "us"},
                }
            },
        )

    @pytest.mark.asyncio
    async def test_delete_async_with_hard_delete_uses_query_param(self):
        service = _users_service()
        service._http.delete.return_value = APIResponse.ok(data={})

        await service.delete_async("user-1", hard_delete=True)

        service._http.delete.assert_awaited_once_with(
            "/api/user/user-1",
            params={"hardDelete": "true"},
        )

    @pytest.mark.asyncio
    async def test_delete_async_without_hard_delete_uses_none_params(self):
        service = _users_service()
        service._http.delete.return_value = APIResponse.ok(data={})

        await service.delete_async("user-1")

        service._http.delete.assert_awaited_once_with("/api/user/user-1", params=None)


class TestRolesService:
    def test_list_for_application_extracts_roles(self):
        service = _roles_service()
        service._http.get_sync.return_value = APIResponse.ok(
            data={"application": {"roles": [{"id": "role-1", "name": "reader"}]}}
        )

        result = service.list_for_application("app-1")

        assert result.success is True
        assert result.data == {
            "roles": [{"id": "role-1", "name": "reader"}],
            "applicationId": "app-1",
        }

    def test_list_for_application_passthrough_failure(self):
        service = _roles_service()
        failure = APIResponse.fail(error="missing", status_code=404)
        service._http.get_sync.return_value = failure

        assert service.list_for_application("app-1") is failure

    def test_get_finds_role_by_id(self):
        service = _roles_service()
        service.list_for_application = MagicMock(
            return_value=APIResponse.ok(data={"roles": [{"id": "role-1", "name": "reader"}]})
        )

        result = service.get("app-1", "role-1")

        assert result.success is True
        assert result.data == {"role": {"id": "role-1", "name": "reader"}}

    def test_get_returns_not_found(self):
        service = _roles_service()
        service.list_for_application = MagicMock(return_value=APIResponse.ok(data={"roles": []}))

        result = service.get("app-1", "role-1")

        assert result.success is False
        assert result.status_code == 404

    def test_get_by_name_finds_matching_role(self):
        service = _roles_service()
        service.list_for_application = MagicMock(
            return_value=APIResponse.ok(data={"roles": [{"id": "role-1", "name": "reader"}]})
        )

        result = service.get_by_name("app-1", "reader")

        assert result.success is True
        assert result.data["role"]["id"] == "role-1"

    def test_create_builds_payload(self):
        service = _roles_service()
        service._http.post_sync.return_value = APIResponse.ok(data={})

        service.create("app-1", "reader", description="Read only", is_default=True, is_super_role=False)

        service._http.post_sync.assert_called_once_with(
            "/api/application/app-1/role",
            {"role": {"name": "reader", "isDefault": True, "isSuperRole": False, "description": "Read only"}},
        )

    def test_update_builds_partial_payload(self):
        service = _roles_service()
        service._http.patch_sync.return_value = APIResponse.ok(data={})

        service.update("app-1", "role-1", name="writer", is_super_role=True)

        service._http.patch_sync.assert_called_once_with(
            "/api/application/app-1/role/role-1",
            {"role": {"name": "writer", "isSuperRole": True}},
        )

    def test_delete_calls_expected_endpoint(self):
        service = _roles_service()
        service._http.delete_sync.return_value = APIResponse.ok(data={})

        service.delete("app-1", "role-1")

        service._http.delete_sync.assert_called_once_with("/api/application/app-1/role/role-1")
