from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_client_root = _repo_root / "libs" / "client"
if str(_client_root) not in sys.path:
    sys.path.insert(0, str(_client_root))

from shml.client import (  # noqa: E402
    AuthenticationError,
    Client,
    NotFoundError,
    PermissionError,
    SHMLError,
)
from shml.admin.config import SDKConfig  # noqa: E402
from shml.admin.http import HTTPClient, RateLimiter  # noqa: E402


def _config(api_key: str = "shml_test", oauth_token: str | None = None):
    return SimpleNamespace(
        base_url="http://localhost:8000",
        api_key=api_key,
        oauth_token=oauth_token,
    )


def _response(status_code: int, payload=None, text: str = "payload"):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload if payload is not None else {}
    response.is_success = 200 <= status_code < 300
    response.reason_phrase = "reason"
    response.content = text.encode() if text else b""
    return response


def _job_payload(job_id: str = "job-1", status: str = "RUNNING"):
    return {
        "job_id": job_id,
        "name": "example-job",
        "status": status,
        "priority": "normal",
        "created_at": datetime.now().isoformat(),
    }


def _user_payload():
    return {
        "user_id": str(uuid4()),
        "username": "alice",
        "email": "alice@example.com",
        "role": "developer",
        "created_at": datetime.now().isoformat(),
        "is_active": True,
    }


def _quota_payload():
    return {
        "max_concurrent_jobs": 3,
        "max_gpu_hours_per_day": 4.0,
        "max_cpu_hours_per_day": 12.0,
        "max_storage_gb": 50,
        "max_job_timeout_hours": 8,
        "max_gpu_fraction": 1.0,
        "priority_weight": 1,
        "can_use_custom_docker": False,
        "can_skip_validation": False,
        "allow_no_timeout": False,
        "allow_exclusive_gpu": False,
    }


def _api_key_payload():
    return {
        "id": str(uuid4()),
        "name": "default",
        "key_prefix": "shml_",
        "scopes": ["jobs:read"],
        "created_at": datetime.now().isoformat(),
    }


def _api_key_secret_payload():
    return {
        "id": str(uuid4()),
        "name": "default",
        "key": "shml_secret",
        "key_prefix": "shml_",
        "scopes": ["jobs:read"],
        "created_at": datetime.now().isoformat(),
    }


class TestMainClient:
    @patch("shml.client.get_config")
    def test_get_headers_uses_api_key(self, mock_get_config):
        mock_get_config.return_value = _config(api_key="abc")
        client = Client()
        assert client._get_headers()["X-API-Key"] == "abc"

    @patch("shml.client.get_config")
    def test_get_headers_uses_oauth_token(self, mock_get_config):
        mock_get_config.return_value = _config(api_key="", oauth_token="token")
        client = Client()
        assert client._get_headers()["Authorization"] == "Bearer token"

    @patch("shml.client.get_config")
    def test_client_property_lazy_initializes(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client(timeout=5.0)
        with patch("shml.client.httpx.Client") as mock_httpx_client:
            instance = MagicMock()
            mock_httpx_client.return_value = instance
            assert client.client is instance
            assert client.client is instance
            mock_httpx_client.assert_called_once()

    @patch("shml.client.get_config")
    def test_handle_response_401(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        with pytest.raises(AuthenticationError):
            client._handle_response(_response(401, {"detail": "bad"}))

    @patch("shml.client.get_config")
    def test_handle_response_403(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        with pytest.raises(PermissionError):
            client._handle_response(_response(403, {"detail": "forbidden"}))

    @patch("shml.client.get_config")
    def test_handle_response_404(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        with pytest.raises(NotFoundError):
            client._handle_response(_response(404, {"detail": "missing"}))

    @patch("shml.client.get_config")
    def test_handle_response_generic_error_with_json(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        with pytest.raises(SHMLError, match="boom"):
            client._handle_response(_response(500, {"detail": "boom"}))

    @patch("shml.client.get_config")
    def test_handle_response_generic_error_with_text_fallback(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        response = _response(500, text="server exploded")
        response.json.side_effect = ValueError("bad json")
        with pytest.raises(SHMLError, match="server exploded"):
            client._handle_response(response)

    @patch("shml.client.get_config")
    def test_handle_response_204(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        response = _response(204, payload={})
        assert client._handle_response(response) == {}

    @patch("shml.client.get_config")
    def test_submit_requires_mode(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        with pytest.raises(ValueError, match="Must provide one of"):
            client.submit()

    @patch("shml.client.get_config")
    def test_submit_with_code_posts_payload(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.post.return_value = _response(
            200, {"job_id": "job-1", "name": "demo", "status": "PENDING"}
        )
        result = client.submit(code="print('hi')", tags=["a"], requirements=["numpy"])
        assert result.job_id == "job-1"
        client._client.post.assert_called_once()

    @patch("shml.client.get_config")
    def test_submit_with_missing_script_path_raises(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        with pytest.raises(FileNotFoundError):
            client.submit(script_path="/missing/train.py")

    @patch("shml.client.get_config")
    def test_submit_with_script_and_additional_files(self, mock_get_config, tmp_path):
        mock_get_config.return_value = _config()
        script = tmp_path / "train.py"
        script.write_text("print('hello')")
        extra = tmp_path / "config.yaml"
        extra.write_text("epochs: 3")

        client = Client()
        client._client = MagicMock()
        client._client.post.return_value = _response(
            200, {"job_id": "job-2", "name": "demo", "status": "PENDING"}
        )

        result = client.submit(
            script_path=str(script),
            entrypoint_args=["--epochs", "3"],
            additional_files={"config.yaml": str(extra)},
        )
        assert result.job_id == "job-2"
        payload = client._client.post.call_args.kwargs["json"]
        assert payload["script_name"] == "train.py"
        assert "working_dir_files" in payload

    @patch("shml.client.get_config")
    def test_submit_script_delegates(self, mock_get_config, tmp_path):
        mock_get_config.return_value = _config()
        script = tmp_path / "train.py"
        script.write_text("print('hello')")
        client = Client()
        with patch.object(client, "submit", return_value=SimpleNamespace(job_id="x")) as mock_submit:
            client.submit_script(str(script), args=["--fast"])
            mock_submit.assert_called_once()

    @patch("shml.client.get_config")
    def test_status_returns_job(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.get.return_value = _response(200, _job_payload())
        result = client.status("job-1")
        assert result.job_id == "job-1"

    @patch("shml.client.get_config")
    def test_logs_returns_text(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.get.return_value = _response(200, {"logs": "line1\nline2"})
        assert client.logs("job-1") == "line1\nline2"

    @patch("shml.client.get_config")
    def test_cancel_posts_reason(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.post.return_value = _response(200, _job_payload(status="CANCELLED"))
        result = client.cancel("job-1", reason="user request")
        assert result.status == "CANCELLED"

    @patch("shml.client.get_config")
    def test_list_jobs_returns_models(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.get.return_value = _response(200, {"jobs": [_job_payload("job-a"), _job_payload("job-b")]})
        result = client.list_jobs(status="RUNNING")
        assert [job.job_id for job in result] == ["job-a", "job-b"]

    @patch("shml.client.get_config")
    def test_me_returns_user(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.get.return_value = _response(200, _user_payload())
        assert client.me().username == "alice"

    @patch("shml.client.get_config")
    def test_quota_returns_quota(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.get.return_value = _response(200, _quota_payload())
        assert client.quota().max_concurrent_jobs == 3

    @patch("shml.client.get_config")
    def test_list_api_keys_returns_models(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.get.return_value = _response(200, [_api_key_payload()])
        assert len(client.list_api_keys()) == 1

    @patch("shml.client.get_config")
    def test_create_api_key_returns_secret_model(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.post.return_value = _response(200, _api_key_secret_payload())
        result = client.create_api_key("new-key", description="desc", expires_in_days=7)
        assert result.key == "shml_secret"

    @patch("shml.client.get_config")
    def test_rotate_api_key_returns_dict(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.post.return_value = _response(200, {"key": "rotated"})
        assert client.rotate_api_key("k1")["key"] == "rotated"

    @patch("shml.client.get_config")
    def test_revoke_api_key(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.delete.return_value = _response(204, {})
        assert client.revoke_api_key("k1") is None

    @patch("shml.client.get_config")
    def test_impersonate_returns_new_client(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        client._client = MagicMock()
        client._client.post.return_value = _response(
            200,
            {
                "token": "oauth-2",
                "effective_user": "svc",
                "effective_role": "developer",
                "expires_at": datetime.now().isoformat(),
                "actual_user": "alice",
                "message": "ok",
            },
        )
        with patch("shml.client.get_config") as second_get_config:
            second_get_config.return_value = _config(api_key="", oauth_token="oauth-2")
            new_client = client.impersonate("developer")
        assert isinstance(new_client, Client)
        assert new_client.config.oauth_token == "oauth-2"

    @patch("shml.client.get_config")
    def test_close_and_context_manager(self, mock_get_config):
        mock_get_config.return_value = _config()
        client = Client()
        mock_http_client = MagicMock()
        client._client = mock_http_client
        with client as current:
            assert current is client
        mock_http_client.close.assert_called_once()
        assert client._client is None


class TestRateLimiter:
    def test_refill_caps_at_calls(self):
        limiter = RateLimiter(calls=5, period=10)
        limiter.tokens = 1
        limiter.last_update = 0
        with patch("shml.admin.http.time.monotonic", return_value=20):
            limiter._refill()
        assert limiter.tokens == 5

    def test_acquire_sync_sleeps_when_empty(self):
        limiter = RateLimiter(calls=2, period=10)
        limiter.tokens = 0
        with patch("shml.admin.http.time.sleep") as mock_sleep:
            limiter.acquire_sync()
        mock_sleep.assert_called_once()

    @pytest.mark.asyncio
    async def test_acquire_async_waits_when_empty(self):
        limiter = RateLimiter(calls=2, period=10)
        limiter.tokens = 0
        with patch("shml.admin.http.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await limiter.acquire()
        mock_sleep.assert_awaited()


class TestAdminHttpClient:
    def _sdk_config(self, tenant: str | None = None):
        return SDKConfig(api_key="api-key", fusionauth_tenant_id=tenant)

    def test_init_adds_tenant_header(self):
        client = HTTPClient(self._sdk_config(tenant="tenant-1"))
        assert client._headers["X-FusionAuth-TenantId"] == "tenant-1"

    def test_get_sync_client_lazy_initialization(self):
        client = HTTPClient(self._sdk_config())
        with patch("shml.admin.http.httpx.Client") as mock_client_cls:
            mock_instance = MagicMock(is_closed=False)
            mock_client_cls.return_value = mock_instance
            assert client._get_sync_client() is mock_instance
            assert client._get_sync_client() is mock_instance
            mock_client_cls.assert_called_once()

    def test_get_async_client_lazy_initialization(self):
        client = HTTPClient(self._sdk_config())
        with patch("shml.admin.http.httpx.AsyncClient") as mock_client_cls:
            mock_instance = MagicMock(is_closed=False)
            mock_client_cls.return_value = mock_instance
            assert client._get_async_client() is mock_instance
            assert client._get_async_client() is mock_instance
            mock_client_cls.assert_called_once()

    def test_generate_request_id(self):
        client = HTTPClient(self._sdk_config())
        assert len(client._generate_request_id()) == 8

    def test_handle_response_success(self):
        client = HTTPClient(self._sdk_config())
        response = _response(200, {"ok": True})
        result = client._handle_response(response, "req-1")
        assert result.success is True
        assert result.data == {"ok": True}

    def test_handle_response_field_errors(self):
        client = HTTPClient(self._sdk_config())
        response = _response(400, {"fieldErrors": {"email": [{"message": "invalid"}]}})
        result = client._handle_response(response, "req-1")
        assert result.success is False
        assert "email: invalid" in result.error

    def test_handle_response_message(self):
        client = HTTPClient(self._sdk_config())
        response = _response(400, {"message": "bad request"})
        result = client._handle_response(response, "req-1")
        assert result.error == "bad request"

    def test_handle_response_general_errors(self):
        client = HTTPClient(self._sdk_config())
        response = _response(400, {"generalErrors": [{"message": "nope"}]})
        result = client._handle_response(response, "req-1")
        assert result.error == "nope"

    def test_handle_response_non_json_fallback(self):
        client = HTTPClient(self._sdk_config())
        response = _response(500, text="raw text")
        response.json.side_effect = ValueError("bad json")
        result = client._handle_response(response, "req-1")
        assert result.success is False
        assert result.data == {"raw": "raw text"}

    def test_handle_exception_connect(self):
        client = HTTPClient(self._sdk_config())
        result = client._handle_exception(httpx.ConnectError("refused"), "req-1")
        assert result.status_code == 0
        assert "Connection failed" in result.error

    def test_handle_exception_timeout(self):
        client = HTTPClient(self._sdk_config())
        result = client._handle_exception(httpx.TimeoutException("slow"), "req-1")
        assert result.status_code == 504

    def test_handle_exception_generic(self):
        client = HTTPClient(self._sdk_config())
        result = client._handle_exception(RuntimeError("boom"), "req-1")
        assert result.error == "boom"

    def test_request_sync_success(self):
        client = HTTPClient(self._sdk_config())
        with patch.object(client, "_generate_request_id", return_value="req-1"), \
             patch.object(client.rate_limiter, "acquire_sync") as mock_acquire, \
             patch.object(client, "_get_sync_client") as mock_get_sync:
            sync_client = MagicMock()
            sync_client.request.return_value = _response(200, {"ok": True})
            mock_get_sync.return_value = sync_client
            result = client.request_sync("GET", "/health")
        mock_acquire.assert_called_once()
        assert result.success is True

    def test_request_sync_exception(self):
        client = HTTPClient(self._sdk_config())
        with patch.object(client, "_generate_request_id", return_value="req-1"), \
             patch.object(client.rate_limiter, "acquire_sync"), \
             patch.object(client, "_get_sync_client") as mock_get_sync:
            sync_client = MagicMock()
            sync_client.request.side_effect = RuntimeError("boom")
            mock_get_sync.return_value = sync_client
            result = client.request_sync("GET", "/health")
        assert result.success is False
        assert result.error == "boom"

    @pytest.mark.asyncio
    async def test_request_async_success(self):
        client = HTTPClient(self._sdk_config())
        async_client = MagicMock()
        async_client.request = AsyncMock(return_value=_response(200, {"ok": True}))
        with patch.object(client, "_generate_request_id", return_value="req-1"), \
             patch.object(client.rate_limiter, "acquire", new=AsyncMock()) as mock_acquire, \
             patch.object(client, "_get_async_client", return_value=async_client):
            result = await client.request("GET", "/health")
        mock_acquire.assert_awaited_once()
        assert result.success is True

    def test_sync_wrappers_delegate(self):
        client = HTTPClient(self._sdk_config())
        with patch.object(client, "request_sync", return_value=MagicMock()) as mock_request:
            client.get_sync("/a")
            client.post_sync("/a", json={"x": 1})
            client.put_sync("/a", json={"x": 1})
            client.patch_sync("/a", json={"x": 1})
            client.delete_sync("/a")
        assert mock_request.call_count == 5

    @pytest.mark.asyncio
    async def test_async_context_manager_close(self):
        client = HTTPClient(self._sdk_config())
        async_instance = MagicMock(is_closed=False)
        async_instance.aclose = AsyncMock()
        client._async_client = async_instance
        async with client:
            pass
        async_instance.aclose.assert_awaited_once()

    def test_sync_context_manager_close(self):
        client = HTTPClient(self._sdk_config())
        sync_instance = MagicMock(is_closed=False)
        client._sync_client = sync_instance
        with client:
            pass
        sync_instance.close.assert_called_once()
