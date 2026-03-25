"""Unit tests for ray_compute/api/cluster.py.

Covers all cluster management endpoints (GET /cluster/status, /nodes, /gpus,
/actors, /resource-usage) by mocking the httpx client and auth dependency.
"""
from __future__ import annotations

import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
for _p in [str(_ROOT), str(_ROOT / "ray_compute")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# conftest.py has already stubbed ray_compute.api.auth and ray_compute.api.models
# Import the module under test now (will use those stubs)
import ray_compute.api.cluster as _cluster  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Return a fake httpx response."""
    r = MagicMock()
    r.status_code = status_code
    r.json = MagicMock(return_value=json_data)
    r.raise_for_status = MagicMock()
    return r


def _make_client() -> TestClient:
    """Build a TestClient with the cluster router."""
    from ray_compute.api.auth import get_current_user as _gcu

    _User = sys.modules["ray_compute.api.models"].User

    class _FakeAdmin(_User):
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        username = "admin"
        email = "admin@test.local"
        role = "admin"
        is_active = True
        is_suspended = False

    app = FastAPI()
    app.include_router(_cluster.router)
    app.dependency_overrides[_gcu] = lambda: _FakeAdmin()
    return TestClient(app)


_CLUSTER_STATUS_DATA = {
    "result": True,
    "data": {
        "loadMetricsReport": {
            "usage": {
                "CPU": [2.0, 8.0],
                "GPU": [1.0, 2.0],
                "memory": [8589934592, 34359738368],
                "objectStoreMemory": [0, 8589934592],
            }
        },
        "autoscalerReport": {"activeNodes": {"head": 1}},
    },
}

_VERSION_DATA = {"ray_version": "2.8.1"}

_NODES_DATA = {
    "data": {
        "summary": [
            {
                "ip": "10.0.0.1",
                "hostname": "node-1",
                "raylet": {"nodeId": "abc123", "isHeadNode": True, "state": "ALIVE"},
                "cpu": 50.0,
                "mem": [1073741824, 8589934592, 12.0],
                "gpus": [],
                "disk": {},
            }
        ]
    }
}

_NODES_WITH_GPUS_DATA = {
    "data": {
        "summary": [
            {
                "ip": "10.0.0.1",
                "hostname": "gpu-node",
                "raylet": {"nodeId": "gpu123"},
                "gpus": [
                    {
                        "index": 0,
                        "name": "RTX 2070",
                        "memoryTotal": 8192,
                        "memoryUsed": 2048,
                        "utilizationGpu": 50,
                        "temperatureGpu": 65,
                    }
                ],
            }
        ]
    }
}

_ACTORS_DATA = {
    "data": {
        "actors": {
            "actor123": {
                "actorClass": "MyActor",
                "state": "ALIVE",
                "pid": 1234,
                "address": {"rayletId": "abc123"},
                "numRestarts": 0,
            }
        }
    }
}


class TestGetClusterStatus:
    """Cover GET /cluster/status."""

    def test_returns_healthy_status(self):
        """Returns 200 with cluster status when Ray dashboard responds."""
        client = _make_client()
        with patch.object(
            _cluster,
            "http_client",
            **{"get": AsyncMock(side_effect=[
                _mock_response(_CLUSTER_STATUS_DATA),
                _mock_response(_VERSION_DATA),
            ])}
        ):
            resp = client.get("/cluster/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["ray_version"] == "2.8.1"
        assert data["total_nodes"] == 1

    def test_httpx_error_returns_503(self):
        """Returns 503 when Ray dashboard is unreachable."""
        import httpx as _httpx

        client = _make_client()
        mock_get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/status")
        assert resp.status_code == 503

    def test_generic_exception_returns_500(self):
        """Returns 500 for unexpected errors (lines 130-131)."""
        client = _make_client()
        mock_get = AsyncMock(side_effect=ValueError("unexpected"))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/status")
        assert resp.status_code == 500


class TestGetClusterNodes:
    """Cover GET /cluster/nodes."""

    def test_returns_node_list(self):
        """Returns list of nodes with parsed fields (lines 166-171)."""
        client = _make_client()
        mock_get = AsyncMock(return_value=_mock_response(_NODES_DATA))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["nodes"][0]["ip"] == "10.0.0.1"
        assert data["nodes"][0]["hostname"] == "node-1"

    def test_httpx_error_returns_503(self):
        """Returns 503 when Ray dashboard is unreachable (line 150)."""
        import httpx as _httpx

        client = _make_client()
        mock_get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/nodes")
        assert resp.status_code == 503

    def test_generic_exception_returns_500(self):
        """Returns 500 for unexpected errors."""
        client = _make_client()
        mock_get = AsyncMock(side_effect=ValueError("unexpected"))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/nodes")
        assert resp.status_code == 500


class TestGetGPUInfo:
    """Cover GET /cluster/gpus."""

    def test_returns_gpu_list(self):
        """Returns list of GPUs across nodes (lines 189-191)."""
        client = _make_client()
        mock_get = AsyncMock(return_value=_mock_response(_NODES_WITH_GPUS_DATA))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/gpus")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["gpus"][0]["name"] == "RTX 2070"
        assert data["gpus"][0]["memory_total_mb"] == 8192

    def test_empty_gpus_returns_empty_list(self):
        """Returns empty list when no GPUs in cluster."""
        client = _make_client()
        mock_get = AsyncMock(return_value=_mock_response(_NODES_DATA))  # no GPUs
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/gpus")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_httpx_error_returns_503(self):
        """Returns 503 when Ray dashboard is unreachable."""
        import httpx as _httpx

        client = _make_client()
        mock_get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/gpus")
        assert resp.status_code == 503


class TestGetActors:
    """Cover GET /cluster/actors."""

    def test_returns_actor_list(self):
        """Returns list of Ray actors (lines 208-213)."""
        client = _make_client()
        mock_get = AsyncMock(return_value=_mock_response(_ACTORS_DATA))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/actors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["actors"][0]["class_name"] == "MyActor"
        assert data["actors"][0]["state"] == "ALIVE"

    def test_empty_actors_returns_empty_list(self):
        """Returns empty list when no actors."""
        client = _make_client()
        mock_get = AsyncMock(return_value=_mock_response({"data": {"actors": {}}}))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/actors")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_httpx_error_returns_503(self):
        """Returns 503 when Ray dashboard is unreachable."""
        import httpx as _httpx

        client = _make_client()
        mock_get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/actors")
        assert resp.status_code == 503


class TestGetResourceUsage:
    """Cover GET /cluster/resource-usage (lines 263-292)."""

    def test_returns_resource_dict(self):
        """Returns resource usage dict from Ray dashboard."""
        client = _make_client()
        mock_get = AsyncMock(return_value=_mock_response(_CLUSTER_STATUS_DATA))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/resource-usage")
        assert resp.status_code == 200
        data = resp.json()
        assert "resources" in data
        assert "CPU" in data["resources"]
        assert data["resources"]["CPU"]["used"] == 2.0

    def test_httpx_error_returns_503(self):
        """Returns 503 when Ray dashboard is unreachable."""
        import httpx as _httpx

        client = _make_client()
        mock_get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/resource-usage")
        assert resp.status_code == 503

    def test_generic_exception_returns_500(self):
        """Returns 500 for unexpected errors."""
        client = _make_client()
        mock_get = AsyncMock(side_effect=ValueError("bad"))
        with patch.object(_cluster, "http_client", **{"get": mock_get}):
            resp = client.get("/cluster/resource-usage")
        assert resp.status_code == 500
