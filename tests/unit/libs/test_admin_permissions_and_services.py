from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_client_root = _repo_root / "libs" / "client"
if str(_client_root) not in sys.path:
    sys.path.insert(0, str(_client_root))

from shml.admin.exceptions import PermissionDeniedError  # noqa: E402
from shml.admin.models import APIResponse, Permission, Role  # noqa: E402
from shml.admin.permissions import (  # noqa: E402
    PermissionContext,
    requires_any_permission,
    requires_permission,
    requires_role,
)
from shml.admin.services.api_keys import APIKeysService  # noqa: E402
from shml.admin.services.applications import ApplicationsService  # noqa: E402
from shml.admin.services.base import BaseService  # noqa: E402
from shml.admin.services.groups import GroupsService  # noqa: E402
from shml.admin.services.registrations import RegistrationsService  # noqa: E402


class TestPermissionContext:
    def test_permissions_from_role(self):
        ctx = PermissionContext(role=Role.VIEWER)
        assert Permission.USERS_READ in ctx.permissions

    def test_permissions_explicit_override(self):
        ctx = PermissionContext(role=Role.VIEWER, permissions={Permission.API_KEYS_READ})
        assert ctx.permissions == {Permission.API_KEYS_READ}

    def test_has_permission(self):
        ctx = PermissionContext(role=Role.DEVELOPER)
        assert ctx.has_permission(Permission.REGISTRATIONS_CREATE) is True

    def test_has_any_permission(self):
        ctx = PermissionContext(role=Role.VIEWER)
        assert ctx.has_any_permission([Permission.USERS_DELETE, Permission.USERS_READ]) is True

    def test_has_all_permissions(self):
        ctx = PermissionContext(role=Role.DEVELOPER)
        assert ctx.has_all_permissions([Permission.USERS_READ, Permission.REGISTRATIONS_CREATE]) is True

    def test_check_permission_denied(self):
        ctx = PermissionContext(role=Role.VIEWER)
        with pytest.raises(PermissionDeniedError):
            ctx.check_permission(Permission.USERS_DELETE, operation="delete")

    def test_repr(self):
        ctx = PermissionContext(role=Role.ADMIN)
        assert "PermissionContext" in repr(ctx)


class TestPermissionDecorators:
    def test_requires_permission_sync(self):
        class Service:
            _permission_context = PermissionContext(role=Role.ADMIN)

            @requires_permission(Permission.USERS_READ)
            def run(self):
                return "ok"

        assert Service().run() == "ok"

    def test_requires_permission_missing_context(self):
        class Service:
            @requires_permission(Permission.USERS_READ)
            def run(self):
                return "ok"

        with pytest.raises(RuntimeError):
            Service().run()

    @pytest.mark.asyncio
    async def test_requires_permission_async(self):
        class Service:
            _permission_context = PermissionContext(role=Role.ADMIN)

            @requires_permission(Permission.USERS_READ)
            async def run(self):
                return "ok"

        assert await Service().run() == "ok"

    def test_requires_any_permission_sync(self):
        class Service:
            _permission_context = PermissionContext(role=Role.VIEWER)

            @requires_any_permission(Permission.USERS_DELETE, Permission.USERS_READ)
            def run(self):
                return "ok"

        assert Service().run() == "ok"

    @pytest.mark.asyncio
    async def test_requires_any_permission_async_denied(self):
        class Service:
            _permission_context = PermissionContext(role=Role.VIEWER)

            @requires_any_permission(Permission.USERS_DELETE, Permission.API_KEYS_DELETE)
            async def run(self):
                return "ok"

        with pytest.raises(PermissionDeniedError):
            await Service().run()

    def test_requires_role_sync(self):
        class Service:
            _permission_context = PermissionContext(role=Role.ADMIN)

            @requires_role(Role.DEVELOPER)
            def run(self):
                return "ok"

        assert Service().run() == "ok"

    @pytest.mark.asyncio
    async def test_requires_role_async_denied(self):
        class Service:
            _permission_context = PermissionContext(role=Role.VIEWER)

            @requires_role(Role.DEVELOPER)
            async def run(self):
                return "ok"

        with pytest.raises(PermissionDeniedError):
            await Service().run()


class TestBaseService:
    def test_base_service_properties(self):
        http = MagicMock()
        ctx = PermissionContext(role=Role.ADMIN)
        service = BaseService(http_client=http, permission_context=ctx)
        assert service.role == Role.ADMIN
        assert Permission.USERS_READ in service.permissions
        assert service.has_permission(Permission.USERS_READ) is True


def _admin_ctx() -> PermissionContext:
    return PermissionContext(role=Role.ADMIN)


class TestApplicationsService:
    def _service(self):
        return ApplicationsService(http_client=MagicMock(), permission_context=_admin_ctx())

    def test_list(self):
        service = self._service()
        service._http.get_sync.return_value = APIResponse.ok(data={"applications": []})
        assert service.list().success is True

    def test_list_inactive(self):
        service = self._service()
        service._http.get_sync.return_value = APIResponse.ok(data={"applications": []})
        service.list(inactive=True)
        assert service._http.get_sync.call_args.kwargs["params"] == {"inactive": "true"}

    def test_get_by_name_found(self):
        service = self._service()
        service.list = MagicMock(return_value=APIResponse.ok(data={"applications": [{"name": "portal"}]}))
        result = service.get_by_name("portal")
        assert result.success is True

    def test_get_by_name_not_found(self):
        service = self._service()
        service.list = MagicMock(return_value=APIResponse.ok(data={"applications": []}))
        result = service.get_by_name("portal")
        assert result.status_code == 404

    def test_search(self):
        service = self._service()
        service._http.post_sync.return_value = APIResponse.ok(data={})
        service.search("app*", limit=10, offset=5)
        payload = service._http.post_sync.call_args.kwargs["json"]
        assert payload["search"]["name"] == "app*"

    def test_create(self):
        service = self._service()
        service._http.post_sync.return_value = APIResponse.ok(data={})
        service.create("portal", tenant_id="t1", roles=[{"name": "reader"}], data={"x": 1})
        payload = service._http.post_sync.call_args.kwargs["json"]
        assert payload["application"]["name"] == "portal"
        assert payload["application"]["tenantId"] == "t1"


class TestGroupsService:
    def _service(self):
        return GroupsService(http_client=MagicMock(), permission_context=_admin_ctx())

    def test_invalidate_cache(self):
        service = self._service()
        service._cache = {"a": {}}
        service._invalidate_cache()
        assert service._cache is None

    def test_get_by_name_found(self):
        service = self._service()
        service.list = MagicMock(return_value=APIResponse.ok(data={"groups": [{"name": "admins"}]}))
        result = service.get_by_name("admins")
        assert result.success is True

    def test_get_by_name_not_found(self):
        service = self._service()
        service.list = MagicMock(return_value=APIResponse.ok(data={"groups": []}))
        result = service.get_by_name("admins")
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_by_name_async_found(self):
        service = self._service()
        service.list_async = AsyncMock(
            return_value=APIResponse.ok(data={"groups": [{"id": "g-1", "name": "admins"}]})
        )

        result = await service.get_by_name_async("admins")

        assert result.success is True
        assert result.data == {"group": {"id": "g-1", "name": "admins"}}

    @pytest.mark.asyncio
    async def test_get_by_name_async_not_found(self):
        service = self._service()
        service.list_async = AsyncMock(return_value=APIResponse.ok(data={"groups": []}))

        result = await service.get_by_name_async("admins")

        assert result.status_code == 404

    def test_search(self):
        service = self._service()
        service._http.get_sync.return_value = APIResponse.ok(data={})
        service.search("adm*", limit=3, offset=2)
        params = service._http.get_sync.call_args.kwargs["params"]
        assert params["name"] == "adm*"

    @pytest.mark.asyncio
    async def test_list_async(self):
        service = self._service()
        service._http.get = AsyncMock(return_value=APIResponse.ok(data={"groups": []}))

        result = await service.list_async()

        assert result.success is True
        service._http.get.assert_awaited_once_with("/api/group")

    def test_get(self):
        service = self._service()
        service._http.get_sync.return_value = APIResponse.ok(data={"group": {"id": "g-1"}})

        result = service.get("g-1")

        assert result.success is True
        service._http.get_sync.assert_called_once_with("/api/group/g-1")

    @pytest.mark.asyncio
    async def test_get_async(self):
        service = self._service()
        service._http.get = AsyncMock(return_value=APIResponse.ok(data={"group": {"id": "g-1"}}))

        result = await service.get_async("g-1")

        assert result.success is True
        service._http.get.assert_awaited_once_with("/api/group/g-1")

    @pytest.mark.asyncio
    async def test_search_async(self):
        service = self._service()
        service._http.get = AsyncMock(return_value=APIResponse.ok(data={"groups": []}))

        result = await service.search_async("adm*", limit=4, offset=3)

        assert result.success is True
        service._http.get.assert_awaited_once_with(
            "/api/group/search",
            params={"name": "adm*", "numberOfResults": 4, "startRow": 3},
        )

    def test_create_invalidates_cache_on_success(self):
        service = self._service()
        service._cache = {"admins": {}}
        service._http.post_sync.return_value = APIResponse.ok(data={"group": {"name": "admins"}})
        service.create("admins", description="desc", role_ids=["r1"], data={"env": "prod"})
        assert service._cache is None

    def test_create_preserves_existing_data_without_role_ids(self):
        service = self._service()
        service._http.post_sync.return_value = APIResponse.ok(data={})

        service.create("admins", data={"env": "prod"})

        payload = service._http.post_sync.call_args.kwargs["json"]
        assert payload == {"group": {"name": "admins", "data": {"env": "prod"}}}

    @pytest.mark.asyncio
    async def test_create_async_invalidates_cache_on_success(self):
        service = self._service()
        service._cache = {"admins": {}}
        service._http.post = AsyncMock(return_value=APIResponse.ok(data={"group": {"name": "admins"}}))

        result = await service.create_async("admins", description="desc", role_ids=["r1"], data={"env": "prod"})

        assert result.success is True
        assert service._cache is None
        service._http.post.assert_awaited_once()

    def test_update_invalidates_cache_and_builds_payload(self):
        service = self._service()
        service._cache = {"admins": {}}
        service._http.patch_sync.return_value = APIResponse.ok(data={"group": {"id": "g-1"}})

        result = service.update(
            "g-1",
            name="platform-admins",
            description="core team",
            role_ids=["r1", "r2"],
            data={"env": "prod"},
        )

        assert result.success is True
        assert service._cache is None
        assert service._http.patch_sync.call_args.args[0] == "/api/group/g-1"
        assert service._http.patch_sync.call_args.kwargs["json"] == {
            "group": {"name": "platform-admins", "data": {"env": "prod", "description": "core team"}},
            "roleIds": ["r1", "r2"],
        }

    @pytest.mark.asyncio
    async def test_update_async_failure_does_not_invalidate_cache(self):
        service = self._service()
        service._cache = {"admins": {}}
        failure = APIResponse.fail(error="nope", status_code=500)
        service._http.patch = AsyncMock(return_value=failure)

        result = await service.update_async("g-1", description="core team")

        assert result is failure
        assert service._cache == {"admins": {}}
        service._http.patch.assert_awaited_once_with(
            "/api/group/g-1",
            json={"group": {"data": {"description": "core team"}}},
        )

    def test_delete_invalidates_cache_on_success(self):
        service = self._service()
        service._cache = {"admins": {}}
        service._http.delete_sync.return_value = APIResponse.ok(data={})

        result = service.delete("g-1")

        assert result.success is True
        assert service._cache is None
        service._http.delete_sync.assert_called_once_with("/api/group/g-1")

    @pytest.mark.asyncio
    async def test_delete_async_failure_keeps_cache(self):
        service = self._service()
        service._cache = {"admins": {}}
        failure = APIResponse.fail(error="nope", status_code=500)
        service._http.delete = AsyncMock(return_value=failure)

        result = await service.delete_async("g-1")

        assert result is failure
        assert service._cache == {"admins": {}}
        service._http.delete.assert_awaited_once_with("/api/group/g-1")

    def test_get_members(self):
        service = self._service()
        service._http.get_sync.return_value = APIResponse.ok(data={"members": []})
        result = service.get_members("group-1")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_get_members_async(self):
        service = self._service()
        service._http.get = AsyncMock(return_value=APIResponse.ok(data={"members": []}))

        result = await service.get_members_async("group-1")

        assert result.success is True
        service._http.get.assert_awaited_once_with(
            "/api/group/member/search",
            params={"groupId": "group-1"},
        )

    def test_add_member(self):
        service = self._service()
        service._http.post_sync.return_value = APIResponse.ok(data={})

        result = service.add_member("group-1", "user-1", data={"source": "sync"})

        assert result.success is True
        assert service._http.post_sync.call_args.kwargs["json"] == {
            "members": {"group-1": [{"userId": "user-1", "data": {"source": "sync"}}]}
        }

    @pytest.mark.asyncio
    async def test_add_member_async(self):
        service = self._service()
        service._http.post = AsyncMock(return_value=APIResponse.ok(data={}))

        result = await service.add_member_async("group-1", "user-1")

        assert result.success is True
        service._http.post.assert_awaited_once_with(
            "/api/group/member",
            json={"members": {"group-1": [{"userId": "user-1"}]}},
        )

    def test_remove_member(self):
        service = self._service()
        service._http.delete_sync.return_value = APIResponse.ok(data={})

        result = service.remove_member("group-1", "user-1")

        assert result.success is True
        service._http.delete_sync.assert_called_once_with(
            "/api/group/member",
            params={"groupId": "group-1", "userId": "user-1"},
        )

    @pytest.mark.asyncio
    async def test_remove_member_async(self):
        service = self._service()
        service._http.delete = AsyncMock(return_value=APIResponse.ok(data={}))

        result = await service.remove_member_async("group-1", "user-1")

        assert result.success is True
        service._http.delete.assert_awaited_once_with(
            "/api/group/member",
            params={"groupId": "group-1", "userId": "user-1"},
        )

    def test_add_member_by_name_passes_through_lookup_failure(self):
        service = self._service()
        failure = APIResponse.fail(error="not found", status_code=404)
        service.get_by_name = MagicMock(return_value=failure)

        result = service.add_member_by_name("admins", "user-1")

        assert result is failure

    def test_add_member_by_name_requires_group_id(self):
        service = self._service()
        service.get_by_name = MagicMock(return_value=APIResponse.ok(data={"group": {"name": "admins"}}))

        result = service.add_member_by_name("admins", "user-1")

        assert result.status_code == 404

    def test_add_member_by_name_delegates_to_add_member(self):
        service = self._service()
        service.get_by_name = MagicMock(return_value=APIResponse.ok(data={"group": {"id": "group-1"}}))
        service.add_member = MagicMock(return_value=APIResponse.ok(data={"ok": True}))

        result = service.add_member_by_name("admins", "user-1", data={"source": "lookup"})

        assert result.success is True
        service.add_member.assert_called_once_with("group-1", "user-1", {"source": "lookup"})

    @pytest.mark.asyncio
    async def test_add_member_by_name_async_delegates_to_add_member_async(self):
        service = self._service()
        service.get_by_name_async = AsyncMock(return_value=APIResponse.ok(data={"group": {"id": "group-1"}}))
        service.add_member_async = AsyncMock(return_value=APIResponse.ok(data={"ok": True}))

        result = await service.add_member_by_name_async("admins", "user-1", data={"source": "lookup"})

        assert result.success is True
        service.add_member_async.assert_awaited_once_with("group-1", "user-1", {"source": "lookup"})


class TestRegistrationsService:
    def _service(self):
        return RegistrationsService(http_client=MagicMock(), permission_context=_admin_ctx())

    def test_list_for_user_extracts_registrations(self):
        service = self._service()
        service._http.get_sync.return_value = APIResponse.ok(data={"user": {"registrations": [{"id": 1}]}})
        result = service.list_for_user("user-1")
        assert result.data == {"registrations": [{"id": 1}]}

    def test_list_for_user_failure_passthrough(self):
        service = self._service()
        failure = APIResponse.fail(error="nope", status_code=404)
        service._http.get_sync.return_value = failure
        assert service.list_for_user("user-1") is failure

    def test_search_builds_query(self):
        service = self._service()
        service._http.post_sync.return_value = APIResponse.ok(data={})
        service.search(application_id="app-1", email="alice", username="alice1")
        payload = service._http.post_sync.call_args.kwargs["json"]
        assert "registrations.applicationId:app-1" in payload["search"]["queryString"]
        assert "email:alice" in payload["search"]["queryString"]

    def test_create(self):
        service = self._service()
        service._http.post_sync.return_value = APIResponse.ok(data={})
        service.create("user-1", "app-1", roles=["reader"], username="alice")
        payload = service._http.post_sync.call_args.kwargs["json"]
        assert payload["registration"]["applicationId"] == "app-1"
        assert payload["registration"]["roles"] == ["reader"]


class TestAPIKeysService:
    def _service(self):
        http = MagicMock()
        http.config = MagicMock(
            api_key="current-key",
            fusionauth_url="http://localhost:9011",
            fusionauth_tenant_id=None,
            timeout=30.0,
            max_retries=3,
            retry_delay=1.0,
            rate_limit_calls=100,
            rate_limit_period=60.0,
        )
        return APIKeysService(http_client=http, permission_context=_admin_ctx())

    def test_list(self):
        service = self._service()
        service._http.get_sync.return_value = APIResponse.ok(data={"apiKeys": []})
        assert service.list().success is True

    @pytest.mark.asyncio
    async def test_list_async(self):
        service = self._service()
        service._http.get = AsyncMock(return_value=APIResponse.ok(data={"apiKeys": []}))

        result = await service.list_async()

        assert result.success is True
        service._http.get.assert_awaited_once_with("/api/api-key")

    def test_get(self):
        service = self._service()
        service._http.get_sync.return_value = APIResponse.ok(data={"apiKey": {"id": "key-1"}})

        result = service.get("key-1")

        assert result.success is True
        service._http.get_sync.assert_called_once_with("/api/api-key/key-1")

    @pytest.mark.asyncio
    async def test_get_async(self):
        service = self._service()
        service._http.get = AsyncMock(return_value=APIResponse.ok(data={"apiKey": {"id": "key-1"}}))

        result = await service.get_async("key-1")

        assert result.success is True
        service._http.get.assert_awaited_once_with("/api/api-key/key-1")

    def test_introspect_current_key(self):
        service = self._service()
        service._http.get_sync.return_value = APIResponse.ok(data={"apiKeys": []})
        result = service.introspect()
        assert result.success is True

    def test_introspect_other_key_uses_temp_client(self):
        service = self._service()
        with patch("shml.admin.http.HTTPClient") as mock_http_client:
            temp = MagicMock()
            temp.__enter__.return_value = temp
            temp.get_sync.return_value = APIResponse.ok(data={"apiKeys": [{"id": "1"}]})
            mock_http_client.return_value = temp
            result = service.introspect(api_key="other-key")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_introspect_async_current_key(self):
        service = self._service()
        service._http.get = AsyncMock(return_value=APIResponse.ok(data={"apiKeys": []}))

        result = await service.introspect_async()

        assert result.success is True
        service._http.get.assert_awaited_once_with("/api/api-key")

    @pytest.mark.asyncio
    async def test_introspect_async_other_key_uses_temp_client(self):
        service = self._service()
        with patch("shml.admin.http.HTTPClient") as mock_http_client:
            temp = MagicMock()
            temp.__aenter__.return_value = temp
            temp.get = AsyncMock(return_value=APIResponse.ok(data={"apiKeys": [{"id": "1"}]}))
            mock_http_client.return_value = temp

            result = await service.introspect_async(api_key="other-key")

        assert result.success is True
        temp.get.assert_awaited_once_with("/api/api-key")

    def test_create(self):
        service = self._service()
        service._http.post_sync.return_value = APIResponse.ok(data={})
        service.create("desc", permissions={"/api/user": ["GET"]}, key_id="kid", meta_data={"role": "viewer"})
        assert service._http.post_sync.call_args.args[0] == "/api/api-key/kid"

    @pytest.mark.asyncio
    async def test_create_async_builds_payload(self):
        service = self._service()
        service._http.post = AsyncMock(return_value=APIResponse.ok(data={}))

        await service.create_async(
            "desc",
            permissions={"/api/user": ["GET"]},
            tenant_id="tenant-1",
            key_id="kid",
            key="secret",
            ip_access_control_list_id="acl-1",
            meta_data={"role": "viewer"},
        )

        assert service._http.post.await_args.args[0] == "/api/api-key/kid"
        payload = service._http.post.await_args.kwargs["json"]
        assert payload == {
            "apiKey": {
                "description": "desc",
                "permissions": {"endpoints": {"/api/user": ["GET"]}},
                "tenantId": "tenant-1",
                "key": "secret",
                "ipAccessControlListId": "acl-1",
                "metaData": {"role": "viewer"},
            }
        }

    def test_create_admin_key(self):
        service = self._service()
        with patch.object(service, "create", return_value=APIResponse.ok(data={})) as mock_create:
            service.create_admin_key("super")
        assert mock_create.called

    @pytest.mark.asyncio
    async def test_create_admin_key_async(self):
        service = self._service()
        with patch.object(service, "create_async", AsyncMock(return_value=APIResponse.ok(data={}))) as mock_create:
            await service.create_admin_key_async("super", tenant_id="tenant-1")

        mock_create.assert_awaited_once_with(
            description="[ADMIN] super",
            permissions=None,
            tenant_id="tenant-1",
            meta_data={"role": "admin", "created_by": "platform_sdk"},
        )

    def test_create_developer_key(self):
        service = self._service()
        with patch.object(service, "create", return_value=APIResponse.ok(data={})) as mock_create:
            service.create_developer_key("dev", tenant_id="tenant-1")

        payload = mock_create.call_args.kwargs
        assert payload["description"] == "[DEVELOPER] dev"
        assert payload["tenant_id"] == "tenant-1"
        assert payload["meta_data"] == {"role": "developer", "created_by": "platform_sdk"}
        assert payload["permissions"]["/api/user/registration"] == ["GET", "POST"]

    @pytest.mark.asyncio
    async def test_create_developer_key_async(self):
        service = self._service()
        with patch.object(service, "create_async", AsyncMock(return_value=APIResponse.ok(data={}))) as mock_create:
            await service.create_developer_key_async("dev")

        payload = mock_create.await_args.kwargs
        assert payload["description"] == "[DEVELOPER] dev"
        assert payload["meta_data"] == {"role": "developer", "created_by": "platform_sdk"}
        assert payload["permissions"]["/api/api-key"] == ["GET"]

    def test_create_viewer_key(self):
        service = self._service()
        with patch.object(service, "create", return_value=APIResponse.ok(data={})) as mock_create:
            service.create_viewer_key("viewer")

        payload = mock_create.call_args.kwargs
        assert payload["description"] == "[VIEWER] viewer"
        assert payload["meta_data"] == {"role": "viewer", "created_by": "platform_sdk"}
        assert payload["permissions"]["/api/user/registration"] == ["GET"]

    @pytest.mark.asyncio
    async def test_create_viewer_key_async(self):
        service = self._service()
        with patch.object(service, "create_async", AsyncMock(return_value=APIResponse.ok(data={}))) as mock_create:
            await service.create_viewer_key_async("viewer", tenant_id="tenant-1")

        payload = mock_create.await_args.kwargs
        assert payload["description"] == "[VIEWER] viewer"
        assert payload["tenant_id"] == "tenant-1"
        assert payload["permissions"]["/api/group"] == ["GET"]

    def test_update(self):
        service = self._service()
        service._http.put_sync.return_value = APIResponse.ok(data={})

        result = service.update(
            "key-1",
            description="updated",
            permissions={"/api/user": ["GET"]},
            ip_access_control_list_id="acl-1",
            meta_data={"role": "viewer"},
        )

        assert result.success is True
        service._http.put_sync.assert_called_once_with(
            "/api/api-key/key-1",
            json={
                "apiKey": {
                    "description": "updated",
                    "permissions": {"endpoints": {"/api/user": ["GET"]}},
                    "ipAccessControlListId": "acl-1",
                    "metaData": {"role": "viewer"},
                }
            },
        )

    @pytest.mark.asyncio
    async def test_update_async(self):
        service = self._service()
        service._http.put = AsyncMock(return_value=APIResponse.ok(data={}))

        result = await service.update_async("key-1", description="updated")

        assert result.success is True
        service._http.put.assert_awaited_once_with(
            "/api/api-key/key-1",
            json={"apiKey": {"description": "updated"}},
        )

    def test_delete(self):
        service = self._service()
        service._http.delete_sync.return_value = APIResponse.ok(data={})

        result = service.delete("key-1")

        assert result.success is True
        service._http.delete_sync.assert_called_once_with("/api/api-key/key-1")

    @pytest.mark.asyncio
    async def test_delete_async(self):
        service = self._service()
        service._http.delete = AsyncMock(return_value=APIResponse.ok(data={}))

        result = await service.delete_async("key-1")

        assert result.success is True
        service._http.delete.assert_awaited_once_with("/api/api-key/key-1")

    def test_get_role_from_metadata(self):
        service = self._service()
        assert service.get_role_from_metadata({"metaData": {"role": "admin"}}) == "admin"

    def test_has_super_permissions(self):
        service = self._service()
        assert service.has_super_permissions({"permissions": {"endpoints": {}}}) is True

    def test_has_super_permissions_false_when_endpoints_present(self):
        service = self._service()
        assert service.has_super_permissions({"permissions": {"endpoints": {"/api/user": ["GET"]}}}) is False

    def test_get_key_summary(self):
        service = self._service()
        summary = service.get_key_summary({
            "id": "1",
            "description": "desc",
            "permissions": {"endpoints": {"/api/user": ["GET"]}},
            "metaData": {"role": "developer"},
        })
        assert summary["role"] == "developer"

    def test_get_role_from_metadata_defaults_to_unknown(self):
        service = self._service()
        assert service.get_role_from_metadata({}) == "unknown"


class TestPermissionDecoratorsMissingPaths:
    """Cover decorator branches not tested in TestPermissionDecorators."""

    def test_requires_permission_sync_denied(self):
        """Sync wrapper raises PermissionDeniedError when permission missing."""

        class Service:
            _permission_context = PermissionContext(role=Role.VIEWER)

            @requires_permission(Permission.USERS_DELETE)
            def run(self):
                return "ok"

        with pytest.raises(PermissionDeniedError):
            Service().run()

    @pytest.mark.asyncio
    async def test_requires_permission_async_denied(self):
        """Async wrapper raises PermissionDeniedError when permission missing."""

        class Service:
            _permission_context = PermissionContext(role=Role.VIEWER)

            @requires_permission(Permission.USERS_DELETE)
            async def run(self):
                return "ok"

        with pytest.raises(PermissionDeniedError):
            await Service().run()

    @pytest.mark.asyncio
    async def test_requires_permission_async_missing_context(self):
        """Async wrapper raises RuntimeError when no permission context on class."""

        class Service:
            @requires_permission(Permission.USERS_READ)
            async def run(self):
                return "ok"

        with pytest.raises(RuntimeError):
            await Service().run()

    @pytest.mark.asyncio
    async def test_requires_any_permission_async_success(self):
        """Async wrapper succeeds when at least one permission is present."""

        class Service:
            _permission_context = PermissionContext(role=Role.VIEWER)

            @requires_any_permission(Permission.USERS_DELETE, Permission.USERS_READ)
            async def run(self):
                return "ok"

        assert await Service().run() == "ok"

    def test_requires_any_permission_sync_denied(self):
        """Sync wrapper raises PermissionDeniedError when no matching permission."""

        class Service:
            _permission_context = PermissionContext(role=Role.VIEWER)

            @requires_any_permission(Permission.USERS_DELETE, Permission.API_KEYS_DELETE)
            def run(self):
                return "ok"

        with pytest.raises(PermissionDeniedError):
            Service().run()

    def test_requires_any_permission_sync_no_context(self):
        """Sync wrapper raises RuntimeError when no permission context on class."""

        class Service:
            @requires_any_permission(Permission.USERS_READ)
            def run(self):
                return "ok"

        with pytest.raises(RuntimeError):
            Service().run()

    @pytest.mark.asyncio
    async def test_requires_any_permission_async_no_context(self):
        """Async wrapper raises RuntimeError when no permission context on class."""

        class Service:
            @requires_any_permission(Permission.USERS_READ)
            async def run(self):
                return "ok"

        with pytest.raises(RuntimeError):
            await Service().run()

    @pytest.mark.asyncio
    async def test_requires_role_async_success(self):
        """Async requires_role succeeds when role is sufficient."""

        class Service:
            _permission_context = PermissionContext(role=Role.ADMIN)

            @requires_role(Role.DEVELOPER)
            async def run(self):
                return "ok"

        assert await Service().run() == "ok"

    def test_requires_role_sync_denied(self):
        """Sync requires_role raises PermissionDeniedError when role too low."""

        class Service:
            _permission_context = PermissionContext(role=Role.VIEWER)

            @requires_role(Role.DEVELOPER)
            def run(self):
                return "ok"

        with pytest.raises(PermissionDeniedError):
            Service().run()

    def test_requires_role_sync_no_context(self):
        """Sync requires_role raises RuntimeError when no permission context."""

        class Service:
            @requires_role(Role.DEVELOPER)
            def run(self):
                return "ok"

        with pytest.raises(RuntimeError):
            Service().run()

    @pytest.mark.asyncio
    async def test_requires_role_async_no_context(self):
        """Async requires_role raises RuntimeError when no permission context."""

        class Service:
            @requires_role(Role.DEVELOPER)
            async def run(self):
                return "ok"

        with pytest.raises(RuntimeError):
            await Service().run()


class TestPermissionIntrospector:
    """Tests for PermissionIntrospector class."""

    def _import_introspector(self):
        from shml.admin.permissions import PermissionIntrospector  # noqa: E402

        return PermissionIntrospector

    @pytest.mark.asyncio
    async def test_introspect_viewer_on_failed_response(self):
        """Returns viewer role when API call fails (non-401)."""
        PermissionIntrospector = self._import_introspector()
        http = MagicMock()
        http.get = AsyncMock(
            return_value=MagicMock(success=False, status_code=500, data={})
        )
        introspector = PermissionIntrospector(http_client=http)
        ctx = await introspector.introspect()
        assert ctx.role == Role.VIEWER

    @pytest.mark.asyncio
    async def test_introspect_raises_on_401(self):
        """Raises AuthenticationError when API returns 401."""
        from shml.admin.exceptions import AuthenticationError  # noqa: E402

        PermissionIntrospector = self._import_introspector()
        http = MagicMock()
        http.get = AsyncMock(
            return_value=MagicMock(success=False, status_code=401, data={})
        )
        introspector = PermissionIntrospector(http_client=http)
        with pytest.raises(AuthenticationError):
            await introspector.introspect()

    @pytest.mark.asyncio
    async def test_introspect_viewer_when_no_api_keys(self):
        """Returns viewer when api key list is empty."""
        PermissionIntrospector = self._import_introspector()
        http = MagicMock()
        http.get = AsyncMock(
            return_value=MagicMock(success=True, data={"apiKeys": []})
        )
        introspector = PermissionIntrospector(http_client=http)
        ctx = await introspector.introspect()
        assert ctx.role == Role.VIEWER

    @pytest.mark.asyncio
    async def test_introspect_role_from_metadata(self):
        """Returns role when explicitly set in API key metadata."""
        PermissionIntrospector = self._import_introspector()
        http = MagicMock()
        http.get = AsyncMock(
            return_value=MagicMock(
                success=True,
                data={
                    "apiKeys": [
                        {
                            "permissionsObject": {},
                            "metaData": {"attributes": {"role": "developer"}},
                        }
                    ]
                },
            )
        )
        introspector = PermissionIntrospector(http_client=http)
        ctx = await introspector.introspect()
        assert ctx.role == Role.DEVELOPER

    @pytest.mark.asyncio
    async def test_introspect_admin_from_full_user_permissions(self):
        """Returns admin when key has full CRUD on /api/user."""
        PermissionIntrospector = self._import_introspector()
        http = MagicMock()
        http.get = AsyncMock(
            return_value=MagicMock(
                success=True,
                data={
                    "apiKeys": [
                        {
                            "permissionsObject": {
                                "endpoints": {
                                    "/api/user": ["GET", "POST", "PUT", "DELETE"]
                                }
                            },
                            "metaData": {"attributes": {}},
                        }
                    ]
                },
            )
        )
        introspector = PermissionIntrospector(http_client=http)
        ctx = await introspector.introspect()
        assert ctx.role == Role.ADMIN

    def test_introspect_sync_returns_viewer_on_failed_response(self):
        """Sync introspect returns viewer when /api/api-key fails."""
        PermissionIntrospector = self._import_introspector()
        http = MagicMock()
        http.get_sync.return_value = MagicMock(success=False, status_code=500, data={})
        introspector = PermissionIntrospector(http_client=http)
        ctx = introspector.introspect_sync()
        assert ctx.role == Role.VIEWER

    def test_introspect_sync_raises_on_401(self):
        """Sync introspect raises AuthenticationError for 401."""
        from shml.admin.exceptions import AuthenticationError  # noqa: E402

        PermissionIntrospector = self._import_introspector()
        http = MagicMock()
        http.get_sync.return_value = MagicMock(
            success=False, status_code=401, data={}
        )
        introspector = PermissionIntrospector(http_client=http)
        with pytest.raises(AuthenticationError):
            introspector.introspect_sync()

    def test_introspect_sync_viewer_when_no_keys(self):
        PermissionIntrospector = self._import_introspector()
        http = MagicMock()
        http.get_sync.return_value = MagicMock(success=True, data={"apiKeys": []})
        introspector = PermissionIntrospector(http_client=http)
        ctx = introspector.introspect_sync()
        assert ctx.role == Role.VIEWER

    def test_introspect_sync_developer_from_read_write_permissions(self):
        """Returns developer when key has GET+POST on /api/user."""
        PermissionIntrospector = self._import_introspector()
        http = MagicMock()
        http.get_sync.return_value = MagicMock(
            success=True,
            data={
                "apiKeys": [
                    {
                        "permissionsObject": {
                            "endpoints": {"/api/user": ["GET", "POST"]}
                        },
                        "metaData": {"attributes": {}},
                    }
                ]
            },
        )
        introspector = PermissionIntrospector(http_client=http)
        ctx = introspector.introspect_sync()
        assert ctx.role == Role.DEVELOPER

    def test_introspect_sync_viewer_from_read_only_permissions(self):
        """Returns viewer when key only has GET on /api/user."""
        PermissionIntrospector = self._import_introspector()
        http = MagicMock()
        http.get_sync.return_value = MagicMock(
            success=True,
            data={
                "apiKeys": [
                    {
                        "permissionsObject": {
                            "endpoints": {"/api/user": ["GET"]}
                        },
                        "metaData": {"attributes": {}},
                    }
                ]
            },
        )
        introspector = PermissionIntrospector(http_client=http)
        ctx = introspector.introspect_sync()
        assert ctx.role == Role.VIEWER
