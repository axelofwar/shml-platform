from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_client_root = _repo_root / "libs" / "client"
if str(_client_root) not in sys.path:
    sys.path.insert(0, str(_client_root))

from shml.admin.models import APIResponse, Role  # noqa: E402
from shml.admin.permissions import PermissionContext  # noqa: E402
from shml.admin.services.applications import ApplicationsService  # noqa: E402


def _admin_ctx() -> PermissionContext:
    return PermissionContext(role=Role.ADMIN)


def _service() -> ApplicationsService:
    http = MagicMock()
    http.get = AsyncMock()
    http.post = AsyncMock()
    http.patch = AsyncMock()
    http.delete = AsyncMock()
    return ApplicationsService(http_client=http, permission_context=_admin_ctx())


class TestApplicationsServiceSync:
    def test_list_without_inactive_uses_none_params(self):
        service = _service()
        service._http.get_sync.return_value = APIResponse.ok(data={"applications": []})

        result = service.list()

        assert result.success is True
        service._http.get_sync.assert_called_once_with("/api/application", params=None)

    def test_list_with_inactive_sets_query_param(self):
        service = _service()
        service._http.get_sync.return_value = APIResponse.ok(data={"applications": []})

        service.list(inactive=True)

        service._http.get_sync.assert_called_once_with(
            "/api/application",
            params={"inactive": "true"},
        )

    def test_get_calls_expected_endpoint(self):
        service = _service()
        service._http.get_sync.return_value = APIResponse.ok(data={"application": {"id": "app-1"}})

        result = service.get("app-1")

        assert result.success is True
        service._http.get_sync.assert_called_once_with("/api/application/app-1")

    def test_get_by_name_passthrough_failure(self):
        service = _service()
        failure = APIResponse.fail(error="boom", status_code=503)
        service.list = MagicMock(return_value=failure)

        result = service.get_by_name("portal")

        assert result is failure

    def test_get_by_name_returns_matching_application(self):
        service = _service()
        service.list = MagicMock(
            return_value=APIResponse.ok(data={"applications": [{"name": "portal", "id": "app-1"}]})
        )

        result = service.get_by_name("portal")

        assert result.success is True
        assert result.data == {"application": {"name": "portal", "id": "app-1"}}

    def test_get_by_name_returns_not_found_when_missing(self):
        service = _service()
        service.list = MagicMock(return_value=APIResponse.ok(data={"applications": [{"name": "other"}]}))

        result = service.get_by_name("portal")

        assert result.success is False
        assert result.status_code == 404
        assert result.error == "Application 'portal' not found"

    def test_search_builds_payload(self):
        service = _service()
        service._http.post_sync.return_value = APIResponse.ok(data={})

        service.search("portal*", limit=4, offset=2)

        service._http.post_sync.assert_called_once_with(
            "/api/application/search",
            json={"search": {"name": "portal*", "numberOfResults": 4, "startRow": 2}},
        )

    def test_create_without_optional_fields_uses_collection_endpoint(self):
        service = _service()
        service._http.post_sync.return_value = APIResponse.ok(data={})

        service.create("portal")

        service._http.post_sync.assert_called_once_with(
            "/api/application",
            json={"application": {"name": "portal"}},
        )

    def test_create_with_explicit_application_id(self):
        service = _service()
        service._http.post_sync.return_value = APIResponse.ok(data={})

        service.create(
            "portal",
            tenant_id="tenant-1",
            roles=[{"name": "reader"}],
            oauth_configuration={"enabled": True},
            data={"env": "prod"},
            application_id="app-1",
        )

        service._http.post_sync.assert_called_once_with(
            "/api/application/app-1",
            json={
                "application": {
                    "name": "portal",
                    "tenantId": "tenant-1",
                    "roles": [{"name": "reader"}],
                    "oauthConfiguration": {"enabled": True},
                    "data": {"env": "prod"},
                }
            },
        )

    def test_update_builds_partial_payload(self):
        service = _service()
        service._http.patch_sync.return_value = APIResponse.ok(data={})

        service.update(
            "app-1",
            name="new-name",
            roles=[{"name": "writer"}],
            oauth_configuration={"clientId": "abc"},
            data={"region": "us"},
            active=False,
        )

        service._http.patch_sync.assert_called_once_with(
            "/api/application/app-1",
            json={
                "application": {
                    "name": "new-name",
                    "roles": [{"name": "writer"}],
                    "oauthConfiguration": {"clientId": "abc"},
                    "data": {"region": "us"},
                    "active": False,
                }
            },
        )

    def test_deactivate_and_reactivate_delegate_to_update(self):
        service = _service()

        with patch.object(service, "update", return_value=APIResponse.ok(data={})) as mock_update:
            service.deactivate("app-1")
            service.reactivate("app-1")

        assert mock_update.call_args_list[0].args == ("app-1",)
        assert mock_update.call_args_list[0].kwargs == {"active": False}
        assert mock_update.call_args_list[1].args == ("app-1",)
        assert mock_update.call_args_list[1].kwargs == {"active": True}

    def test_delete_hard_delete_sets_query_param(self):
        service = _service()
        service._http.delete_sync.return_value = APIResponse.ok(data={})

        service.delete("app-1", hard_delete=True)

        service._http.delete_sync.assert_called_once_with(
            "/api/application/app-1",
            params={"hardDelete": "true"},
        )

    def test_delete_without_hard_delete_uses_none_params(self):
        service = _service()
        service._http.delete_sync.return_value = APIResponse.ok(data={})

        service.delete("app-1")

        service._http.delete_sync.assert_called_once_with(
            "/api/application/app-1",
            params=None,
        )

    def test_get_roles_extracts_roles(self):
        service = _service()
        service.get = MagicMock(
            return_value=APIResponse.ok(data={"application": {"roles": [{"name": "reader"}]}})
        )

        result = service.get_roles("app-1")

        assert result.data == {"roles": [{"name": "reader"}]}

    def test_get_roles_passthrough_failure(self):
        service = _service()
        failure = APIResponse.fail(error="missing", status_code=404)
        service.get = MagicMock(return_value=failure)

        assert service.get_roles("app-1") is failure

    def test_add_role_includes_optional_fields(self):
        service = _service()
        service._http.post_sync.return_value = APIResponse.ok(data={})

        service.add_role("app-1", "admin", description="All access", is_super_role=True)

        service._http.post_sync.assert_called_once_with(
            "/api/application/app-1/role",
            json={"role": {"name": "admin", "description": "All access", "isSuperRole": True}},
        )

    def test_add_role_minimal_payload_omits_optional_fields(self):
        service = _service()
        service._http.post_sync.return_value = APIResponse.ok(data={})

        service.add_role("app-1", "reader")

        service._http.post_sync.assert_called_once_with(
            "/api/application/app-1/role",
            json={"role": {"name": "reader"}},
        )

    def test_update_role_builds_partial_payload(self):
        service = _service()
        service._http.patch_sync.return_value = APIResponse.ok(data={})

        service.update_role("app-1", "role-1", name="writer", is_super_role=False)

        service._http.patch_sync.assert_called_once_with(
            "/api/application/app-1/role/role-1",
            json={"role": {"name": "writer", "isSuperRole": False}},
        )

    def test_delete_role_uses_expected_endpoint(self):
        service = _service()
        service._http.delete_sync.return_value = APIResponse.ok(data={})

        service.delete_role("app-1", "role-1")

        service._http.delete_sync.assert_called_once_with("/api/application/app-1/role/role-1")


class TestApplicationsServiceAsync:
    @pytest.mark.asyncio
    async def test_list_async_without_inactive_uses_none_params(self):
        service = _service()
        service._http.get.return_value = APIResponse.ok(data={"applications": []})

        await service.list_async()

        service._http.get.assert_awaited_once_with("/api/application", params=None)

    @pytest.mark.asyncio
    async def test_get_async_calls_expected_endpoint(self):
        service = _service()
        service._http.get.return_value = APIResponse.ok(data={"application": {"id": "app-1"}})

        result = await service.get_async("app-1")

        assert result.success is True
        service._http.get.assert_awaited_once_with("/api/application/app-1")

    @pytest.mark.asyncio
    async def test_list_async_with_inactive(self):
        service = _service()
        service._http.get.return_value = APIResponse.ok(data={"applications": []})

        result = await service.list_async(inactive=True)

        assert result.success is True
        service._http.get.assert_awaited_once_with("/api/application", params={"inactive": "true"})

    @pytest.mark.asyncio
    async def test_get_by_name_async_found(self):
        service = _service()
        service.list_async = AsyncMock(
            return_value=APIResponse.ok(data={"applications": [{"name": "portal", "id": "app-1"}]})
        )

        result = await service.get_by_name_async("portal")

        assert result.success is True
        assert result.data["application"]["id"] == "app-1"

    @pytest.mark.asyncio
    async def test_get_by_name_async_passthrough_failure(self):
        service = _service()
        failure = APIResponse.fail(error="boom", status_code=503)
        service.list_async = AsyncMock(return_value=failure)

        result = await service.get_by_name_async("portal")

        assert result is failure

    @pytest.mark.asyncio
    async def test_get_by_name_async_returns_not_found_when_missing(self):
        service = _service()
        service.list_async = AsyncMock(return_value=APIResponse.ok(data={"applications": [{"name": "other"}]}))

        result = await service.get_by_name_async("portal")

        assert result.success is False
        assert result.status_code == 404
        assert result.error == "Application 'portal' not found"

    @pytest.mark.asyncio
    async def test_search_async_builds_payload(self):
        service = _service()
        service._http.post.return_value = APIResponse.ok(data={})

        await service.search_async("portal*", limit=7, offset=3)

        service._http.post.assert_awaited_once_with(
            "/api/application/search",
            json={"search": {"name": "portal*", "numberOfResults": 7, "startRow": 3}},
        )

    @pytest.mark.asyncio
    async def test_create_async_without_optional_fields_uses_collection_endpoint(self):
        service = _service()
        service._http.post.return_value = APIResponse.ok(data={})

        await service.create_async("portal")

        service._http.post.assert_awaited_once_with(
            "/api/application",
            json={"application": {"name": "portal"}},
        )

    @pytest.mark.asyncio
    async def test_create_async_with_optional_fields_and_id(self):
        service = _service()
        service._http.post.return_value = APIResponse.ok(data={})

        await service.create_async(
            "portal",
            tenant_id="tenant-1",
            roles=[{"name": "reader"}],
            oauth_configuration={"enabled": True},
            data={"env": "prod"},
            application_id="app-1",
        )

        service._http.post.assert_awaited_once_with(
            "/api/application/app-1",
            json={
                "application": {
                    "name": "portal",
                    "tenantId": "tenant-1",
                    "roles": [{"name": "reader"}],
                    "oauthConfiguration": {"enabled": True},
                    "data": {"env": "prod"},
                }
            },
        )

    @pytest.mark.asyncio
    async def test_update_async_builds_full_payload(self):
        service = _service()
        service._http.patch.return_value = APIResponse.ok(data={})

        await service.update_async(
            "app-1",
            name="new-name",
            roles=[{"name": "writer"}],
            oauth_configuration={"clientId": "abc"},
            data={"region": "us"},
            active=True,
        )

        service._http.patch.assert_awaited_once_with(
            "/api/application/app-1",
            json={
                "application": {
                    "name": "new-name",
                    "roles": [{"name": "writer"}],
                    "oauthConfiguration": {"clientId": "abc"},
                    "data": {"region": "us"},
                    "active": True,
                }
            },
        )

    @pytest.mark.asyncio
    async def test_deactivate_and_reactivate_async_delegate_to_update_async(self):
        service = _service()

        with patch.object(service, "update_async", new=AsyncMock(return_value=APIResponse.ok(data={}))) as mock_update:
            await service.deactivate_async("app-1")
            await service.reactivate_async("app-1")

        assert mock_update.await_args_list[0].args == ("app-1",)
        assert mock_update.await_args_list[0].kwargs == {"active": False}
        assert mock_update.await_args_list[1].args == ("app-1",)
        assert mock_update.await_args_list[1].kwargs == {"active": True}

    @pytest.mark.asyncio
    async def test_get_roles_async_passthrough_failure(self):
        service = _service()
        failure = APIResponse.fail(error="nope", status_code=500)
        service.get_async = AsyncMock(return_value=failure)

        result = await service.get_roles_async("app-1")

        assert result is failure

    @pytest.mark.asyncio
    async def test_get_roles_async_extracts_roles(self):
        service = _service()
        service.get_async = AsyncMock(
            return_value=APIResponse.ok(data={"application": {"roles": [{"name": "reader"}]}})
        )

        result = await service.get_roles_async("app-1")

        assert result.success is True
        assert result.data == {"roles": [{"name": "reader"}]}

    @pytest.mark.asyncio
    async def test_delete_async_hard_delete_sets_query_param(self):
        service = _service()
        service._http.delete.return_value = APIResponse.ok(data={})

        await service.delete_async("app-1", hard_delete=True)

        service._http.delete.assert_awaited_once_with(
            "/api/application/app-1",
            params={"hardDelete": "true"},
        )

    @pytest.mark.asyncio
    async def test_delete_async_without_hard_delete_uses_none_params(self):
        service = _service()
        service._http.delete.return_value = APIResponse.ok(data={})

        await service.delete_async("app-1")

        service._http.delete.assert_awaited_once_with(
            "/api/application/app-1",
            params=None,
        )

    @pytest.mark.asyncio
    async def test_add_role_async_includes_optional_fields(self):
        service = _service()
        service._http.post.return_value = APIResponse.ok(data={})

        await service.add_role_async("app-1", "admin", description="All access", is_super_role=True)

        service._http.post.assert_awaited_once_with(
            "/api/application/app-1/role",
            json={"role": {"name": "admin", "description": "All access", "isSuperRole": True}},
        )

    @pytest.mark.asyncio
    async def test_update_role_async_includes_all_fields(self):
        service = _service()
        service._http.patch.return_value = APIResponse.ok(data={})

        await service.update_role_async(
            "app-1",
            "role-1",
            name="writer",
            description="Can edit",
            is_super_role=False,
        )

        service._http.patch.assert_awaited_once_with(
            "/api/application/app-1/role/role-1",
            json={"role": {"name": "writer", "description": "Can edit", "isSuperRole": False}},
        )

    @pytest.mark.asyncio
    async def test_add_update_and_delete_role_async(self):
        service = _service()
        service._http.post.return_value = APIResponse.ok(data={})
        service._http.patch.return_value = APIResponse.ok(data={})
        service._http.delete.return_value = APIResponse.ok(data={})

        await service.add_role_async("app-1", "reader")
        await service.update_role_async("app-1", "role-1", description="desc")
        await service.delete_role_async("app-1", "role-1")

        service._http.post.assert_awaited_once_with(
            "/api/application/app-1/role",
            json={"role": {"name": "reader"}},
        )
        service._http.patch.assert_awaited_once_with(
            "/api/application/app-1/role/role-1",
            json={"role": {"description": "desc"}},
        )
        service._http.delete.assert_awaited_once_with("/api/application/app-1/role/role-1")
