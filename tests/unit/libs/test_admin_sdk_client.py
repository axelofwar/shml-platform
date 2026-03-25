from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_client_root = _repo_root / "libs" / "client"
if str(_client_root) not in sys.path:
    sys.path.insert(0, str(_client_root))

from shml.admin.client import PlatformSDK  # noqa: E402
from shml.admin.config import SDKConfig  # noqa: E402
from shml.admin.exceptions import AuthenticationError  # noqa: E402
from shml.admin.models import APIResponse, Permission, Role  # noqa: E402


def _config(api_key: str = "test-key") -> SDKConfig:
    return SDKConfig(api_key=api_key, fusionauth_url="http://localhost:9011")


class TestPlatformSDK:
    @patch("shml.admin.client.HTTPClient")
    def test_requires_api_key(self, mock_http_client):
        with pytest.raises(AuthenticationError):
            PlatformSDK(config=_config(api_key=""), auto_introspect=False)

    @patch("shml.admin.client.HTTPClient")
    def test_role_override_admin_skips_introspection(self, mock_http_client):
        sdk = PlatformSDK(config=_config(), auto_introspect=True, role_override=Role.ADMIN)
        assert sdk.role == Role.ADMIN
        assert Permission.USERS_READ in sdk.permissions

    @patch("shml.admin.client.SDKConfig")
    @patch("shml.admin.client.HTTPClient")
    def test_from_env(self, mock_http_client, mock_sdk_config):
        mock_sdk_config.from_env.return_value = _config()
        sdk = PlatformSDK.from_env()
        assert isinstance(sdk, PlatformSDK)

    @patch("shml.admin.client.HTTPClient")
    def test_for_admin(self, mock_http_client):
        sdk = PlatformSDK.for_admin("key")
        assert sdk.role == Role.ADMIN

    @patch("shml.admin.client.HTTPClient")
    def test_for_developer(self, mock_http_client):
        sdk = PlatformSDK.for_developer("key")
        assert sdk.role == Role.DEVELOPER

    @patch("shml.admin.client.HTTPClient")
    def test_for_viewer(self, mock_http_client):
        sdk = PlatformSDK.for_viewer("key")
        assert sdk.role == Role.VIEWER

    @patch("shml.admin.client.HTTPClient")
    def test_introspect_failure_defaults_to_viewer(self, mock_http_client):
        http_instance = MagicMock()
        http_instance.get_sync.return_value = APIResponse.fail(error="bad", status_code=401)
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=True)
        assert sdk.role == Role.VIEWER

    @patch("shml.admin.client.HTTPClient")
    def test_introspect_admin_from_metadata(self, mock_http_client):
        http_instance = MagicMock()
        http_instance.get_sync.return_value = APIResponse.ok(
            data={"apiKeys": [{"id": "1", "permissions": {"endpoints": {}}, "metaData": {"role": "admin"}}]}
        )
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=True)
        assert sdk.role == Role.ADMIN

    @patch("shml.admin.client.HTTPClient")
    def test_introspect_developer_from_metadata(self, mock_http_client):
        http_instance = MagicMock()
        http_instance.get_sync.return_value = APIResponse.ok(
            data={"apiKeys": [{"id": "1", "permissions": {"endpoints": {"/api/user": ["GET"]}}, "metaData": {"role": "developer"}}]}
        )
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=True)
        assert sdk.role == Role.DEVELOPER

    @patch("shml.admin.client.HTTPClient")
    def test_introspect_viewer_from_metadata(self, mock_http_client):
        http_instance = MagicMock()
        http_instance.get_sync.return_value = APIResponse.ok(
            data={"apiKeys": [{"id": "1", "permissions": {"endpoints": {"/api/user": ["GET"]}}, "metaData": {"role": "viewer"}}]}
        )
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=True)
        assert sdk.role == Role.VIEWER

    @patch("shml.admin.client.HTTPClient")
    def test_introspect_developer_from_write_endpoint(self, mock_http_client):
        http_instance = MagicMock()
        http_instance.get_sync.return_value = APIResponse.ok(
            data={"apiKeys": [{"id": "1", "permissions": {"endpoints": {"/api/user": ["POST"]}}, "metaData": {}}]}
        )
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=True)
        assert sdk.role == Role.DEVELOPER

    @patch("shml.admin.client.HTTPClient")
    def test_introspect_exception_defaults_to_viewer(self, mock_http_client):
        http_instance = MagicMock()
        http_instance.get_sync.side_effect = RuntimeError("boom")
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=True)
        assert sdk.role == Role.VIEWER

    @patch("shml.admin.client.HTTPClient")
    def test_get_permissions_for_role(self, mock_http_client):
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        assert Permission.USERS_READ in sdk._get_permissions_for_role(Role.ADMIN)
        assert Permission.REGISTRATIONS_CREATE in sdk._get_permissions_for_role(Role.DEVELOPER)
        assert Permission.USERS_READ in sdk._get_permissions_for_role(Role.VIEWER)
        assert sdk._get_permissions_for_role(Role.SERVICE_ACCOUNT)

    @patch("shml.admin.client.HTTPClient")
    def test_users_service_lazy_loaded(self, mock_http_client):
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        first = sdk.users
        second = sdk.users
        assert first is second

    @patch("shml.admin.client.HTTPClient")
    def test_groups_service_lazy_loaded(self, mock_http_client):
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        assert sdk.groups is sdk.groups

    @patch("shml.admin.client.HTTPClient")
    def test_applications_service_lazy_loaded(self, mock_http_client):
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        assert sdk.applications is sdk.applications

    @patch("shml.admin.client.HTTPClient")
    def test_registrations_service_lazy_loaded(self, mock_http_client):
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        assert sdk.registrations is sdk.registrations

    @patch("shml.admin.client.HTTPClient")
    def test_api_keys_service_lazy_loaded(self, mock_http_client):
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        assert sdk.api_keys is sdk.api_keys

    @patch("shml.admin.client.HTTPClient")
    def test_roles_service_lazy_loaded(self, mock_http_client):
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        assert sdk.roles is sdk.roles

    @patch("shml.admin.client.HTTPClient")
    def test_has_permission_and_can(self, mock_http_client):
        sdk = PlatformSDK(config=_config(), auto_introspect=False, role_override=Role.ADMIN)
        assert sdk.has_permission(Permission.USERS_READ) is True
        assert sdk.can(Permission.USERS_READ, Permission.GROUPS_READ) is True

    @patch("shml.admin.client.HTTPClient")
    def test_health_check_success(self, mock_http_client):
        http_instance = MagicMock()
        http_instance.get_sync.return_value = APIResponse.ok(data={"status": "ok"})
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        result = sdk.health_check()
        assert result.success is True

    @patch("shml.admin.client.HTTPClient")
    def test_health_check_failure(self, mock_http_client):
        http_instance = MagicMock()
        http_instance.get_sync.side_effect = RuntimeError("offline")
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        result = sdk.health_check()
        assert result.success is False
        assert result.status_code == 503

    @patch("shml.admin.client.HTTPClient")
    @pytest.mark.asyncio
    async def test_health_check_async(self, mock_http_client):
        http_instance = MagicMock()
        http_instance.get = AsyncMock(return_value=APIResponse.ok(data={"status": "ok"}))
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        result = await sdk.health_check_async()
        assert result.success is True

    @patch("shml.admin.client.HTTPClient")
    def test_get_info(self, mock_http_client):
        sdk = PlatformSDK(config=_config(), auto_introspect=False, role_override=Role.DEVELOPER)
        info = sdk.get_info()
        assert info["role"] == "developer"
        assert info["fusionauth_url"] == "http://localhost:9011"

    @patch("shml.admin.client.HTTPClient")
    def test_close_sync(self, mock_http_client):
        http_instance = MagicMock()
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        sdk.close()
        http_instance.close_sync.assert_called_once()

    @patch("shml.admin.client.HTTPClient")
    @pytest.mark.asyncio
    async def test_close_async(self, mock_http_client):
        http_instance = MagicMock()
        http_instance.close = AsyncMock()
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        await sdk.close_async()
        http_instance.close.assert_awaited_once()

    @patch("shml.admin.client.HTTPClient")
    def test_context_manager(self, mock_http_client):
        http_instance = MagicMock()
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        with sdk as current:
            assert current is sdk
        http_instance.close_sync.assert_called_once()

    @patch("shml.admin.client.HTTPClient")
    @pytest.mark.asyncio
    async def test_async_context_manager(self, mock_http_client):
        http_instance = MagicMock()
        http_instance.close = AsyncMock()
        mock_http_client.return_value = http_instance
        sdk = PlatformSDK(config=_config(), auto_introspect=False)
        async with sdk as current:
            assert current is sdk
        http_instance.close.assert_awaited_once()

    @patch("shml.admin.client.HTTPClient")
    def test_repr(self, mock_http_client):
        sdk = PlatformSDK(config=_config(), auto_introspect=False, role_override=Role.VIEWER)
        value = repr(sdk)
        assert "PlatformSDK" in value
        assert "viewer" in value
