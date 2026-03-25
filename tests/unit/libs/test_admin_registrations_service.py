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
from shml.admin.services.registrations import RegistrationsService  # noqa: E402


def _admin_ctx() -> PermissionContext:
    return PermissionContext(role=Role.ADMIN)


def _service() -> RegistrationsService:
    http = MagicMock()
    http.get = AsyncMock()
    http.post = AsyncMock()
    http.patch = AsyncMock()
    http.delete = AsyncMock()
    return RegistrationsService(http_client=http, permission_context=_admin_ctx())


class TestRegistrationsServiceSync:
    def test_get_calls_expected_endpoint(self):
        service = _service()
        service._http.get_sync.return_value = APIResponse.ok(data={"registration": {"id": "r1"}})

        result = service.get("user-1", "app-1")

        assert result.success is True
        service._http.get_sync.assert_called_once_with("/api/user/registration/user-1/app-1")

    def test_search_without_filters_uses_wildcard_query(self):
        service = _service()
        service._http.post_sync.return_value = APIResponse.ok(data={})

        service.search(limit=5, offset=4)

        service._http.post_sync.assert_called_once_with(
            "/api/user/search",
            json={"search": {"queryString": "*", "numberOfResults": 5, "startRow": 4}},
        )

    def test_register_with_roles_delegates_to_create(self):
        service = _service()

        with patch.object(service, "create", return_value=APIResponse.ok(data={})) as mock_create:
            service.register_with_roles("user-1", "app-1", ["reader"], data={"team": "ml"})

        mock_create.assert_called_once_with(
            user_id="user-1",
            app_id="app-1",
            roles=["reader"],
            data={"team": "ml"},
        )

    def test_update_builds_payload(self):
        service = _service()
        service._http.patch_sync.return_value = APIResponse.ok(data={})

        service.update("user-1", "app-1", roles=["admin"], username="alice", data={"active": True})

        service._http.patch_sync.assert_called_once_with(
            "/api/user/registration/user-1",
            json={
                "registration": {
                    "applicationId": "app-1",
                    "roles": ["admin"],
                    "username": "alice",
                    "data": {"active": True},
                }
            },
        )

    def test_add_roles_merges_and_deduplicates(self):
        service = _service()
        service.get = MagicMock(
            return_value=APIResponse.ok(data={"registration": {"roles": ["reader", "writer"]}})
        )
        service.update = MagicMock(return_value=APIResponse.ok(data={}))

        service.add_roles("user-1", "app-1", ["writer", "admin"])

        merged_roles = service.update.call_args.kwargs["roles"]
        assert sorted(merged_roles) == ["admin", "reader", "writer"]

    def test_add_roles_passthrough_failure(self):
        service = _service()
        failure = APIResponse.fail(error="missing", status_code=404)
        service.get = MagicMock(return_value=failure)

        assert service.add_roles("user-1", "app-1", ["admin"]) is failure

    def test_remove_roles_filters_existing_roles(self):
        service = _service()
        service.get = MagicMock(
            return_value=APIResponse.ok(data={"registration": {"roles": ["reader", "writer", "admin"]}})
        )
        service.update = MagicMock(return_value=APIResponse.ok(data={}))

        service.remove_roles("user-1", "app-1", ["writer", "ghost"])

        service.update.assert_called_once_with("user-1", "app-1", roles=["reader", "admin"])

    def test_delete_calls_expected_endpoint(self):
        service = _service()
        service._http.delete_sync.return_value = APIResponse.ok(data={})

        service.delete("user-1", "app-1")

        service._http.delete_sync.assert_called_once_with("/api/user/registration/user-1/app-1")

    def test_bulk_register_collects_successes_and_failures(self):
        service = _service()
        service.create = MagicMock(
            side_effect=[
                APIResponse.ok(data={"registration": {"id": "r1"}}),
                APIResponse.fail(error="bad user", status_code=400),
            ]
        )

        result = service.bulk_register(["u1", "u2"], "app-1", roles=["reader"])

        assert result.success is True
        assert result.data["successful"] == 1
        assert result.data["failed"] == 1
        assert result.data["results"][0]["user_id"] == "u1"
        assert result.data["errors"][0]["user_id"] == "u2"


class TestRegistrationsServiceAsync:
    @pytest.mark.asyncio
    async def test_get_async_calls_expected_endpoint(self):
        service = _service()
        service._http.get.return_value = APIResponse.ok(data={"registration": {"id": "r1"}})

        result = await service.get_async("user-1", "app-1")

        assert result.success is True
        service._http.get.assert_awaited_once_with("/api/user/registration/user-1/app-1")

    @pytest.mark.asyncio
    async def test_list_for_user_async_passthrough_failure(self):
        service = _service()
        failure = APIResponse.fail(error="nope", status_code=500)
        service._http.get.return_value = failure

        result = await service.list_for_user_async("user-1")

        assert result is failure

    @pytest.mark.asyncio
    async def test_search_async_builds_combined_query(self):
        service = _service()
        service._http.post.return_value = APIResponse.ok(data={})

        await service.search_async(application_id="app-1", email="alice", username="alice1")

        payload = service._http.post.await_args.kwargs["json"]
        assert payload["search"]["queryString"] == "registrations.applicationId:app-1 AND email:alice AND username:alice1"

    @pytest.mark.asyncio
    async def test_register_with_roles_async_delegates_to_create_async(self):
        service = _service()

        with patch.object(service, "create_async", new=AsyncMock(return_value=APIResponse.ok(data={}))) as mock_create:
            await service.register_with_roles_async("user-1", "app-1", ["reader"])

        mock_create.assert_awaited_once_with(
            user_id="user-1",
            app_id="app-1",
            roles=["reader"],
            data=None,
        )

    @pytest.mark.asyncio
    async def test_add_roles_async_passthrough_failure(self):
        service = _service()
        failure = APIResponse.fail(error="missing", status_code=404)
        service.get_async = AsyncMock(return_value=failure)

        result = await service.add_roles_async("user-1", "app-1", ["admin"])

        assert result is failure

    @pytest.mark.asyncio
    async def test_remove_roles_async_filters_existing_roles(self):
        service = _service()
        service.get_async = AsyncMock(
            return_value=APIResponse.ok(data={"registration": {"roles": ["reader", "writer"]}})
        )
        service.update_async = AsyncMock(return_value=APIResponse.ok(data={}))

        await service.remove_roles_async("user-1", "app-1", ["writer"])

        service.update_async.assert_awaited_once_with("user-1", "app-1", roles=["reader"])

    @pytest.mark.asyncio
    async def test_delete_async_calls_expected_endpoint(self):
        service = _service()
        service._http.delete.return_value = APIResponse.ok(data={})

        await service.delete_async("user-1", "app-1")

        service._http.delete.assert_awaited_once_with("/api/user/registration/user-1/app-1")

    @pytest.mark.asyncio
    async def test_bulk_register_async_collects_success_failure_and_exception(self):
        service = _service()
        service.create_async = AsyncMock(
            side_effect=[
                APIResponse.ok(data={"registration": {"id": "r1"}}),
                APIResponse.fail(error="bad user", status_code=400),
                RuntimeError("network"),
            ]
        )

        result = await service.bulk_register_async(["u1", "u2", "u3"], "app-1", roles=["reader"])

        assert result.success is True
        assert result.data["successful"] == 1
        assert result.data["failed"] == 2
        assert result.data["results"][0]["user_id"] == "u1"
        assert result.data["errors"][0]["user_id"] == "u2"
        assert result.data["errors"][1]["error"] == "network"
