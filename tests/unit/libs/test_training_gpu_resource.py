from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_ROOT = Path(__file__).resolve().parents[3]
_TRAINING_ROOT = _ROOT / "libs" / "training"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if str(_TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAINING_ROOT))


class TestHttpHelpers:
    def test_http_request_supports_dry_run_and_json_decode(self):
        from shml_training.core.gpu_resource import GPUResourceManager

        manager = GPUResourceManager(dry_run=True)
        success, response, error = manager._http_request("http://example.com")

        assert success is True
        assert response == {"status": "dry_run"}
        assert error is None

    def test_http_request_handles_http_and_url_errors(self):
        import urllib.error

        from shml_training.core.gpu_resource import GPUResourceManager

        manager = GPUResourceManager(dry_run=False)
        http_error = urllib.error.HTTPError(
            url="http://example.com",
            code=503,
            msg="unavailable",
            hdrs=None,
            fp=None,
        )

        with patch("urllib.request.urlopen", side_effect=http_error):
            success, response, error = manager._http_request("http://example.com")
        assert success is False
        assert response is None
        assert error == "HTTP 503: "

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            success, response, error = manager._http_request("http://example.com")
        assert success is False
        assert response is None
        assert error == "Connection error: offline"


class TestGPUResourceManager:
    def test_endpoint_filters_and_fallback_lookup(self):
        from shml_training.core.gpu_resource import GPUResourceManager

        manager = GPUResourceManager()

        gpu0 = manager._get_endpoints_for_gpu(0)
        gpu1 = manager._get_endpoints_for_gpu(1)
        fallback = manager._find_fallback_endpoint("nemotron-manager", 0)

        assert len(gpu0) >= 1
        assert gpu1 == []
        assert fallback is not None
        assert "nemotron-manager" in fallback.name

    def test_yield_gpu_for_training_updates_state_and_tries_fallback(self):
        from shml_training.core.gpu_resource import GPUResourceManager, GPUState, ServiceEndpoint

        primary = ServiceEndpoint(
            name="svc",
            yield_url="http://primary/yield",
            reclaim_url="http://primary/reclaim",
            status_url="http://primary/status",
            gpu_id=0,
            priority=10,
            required=True,
        )
        fallback = ServiceEndpoint(
            name="svc-fallback",
            yield_url="http://fallback/yield",
            reclaim_url="http://fallback/reclaim",
            status_url="http://fallback/status",
            gpu_id=0,
            priority=10,
        )

        manager = GPUResourceManager(endpoints=[primary], use_fallback=False)
        manager.fallback_endpoints = [fallback]

        with patch.object(
            manager,
            "_yield_service",
            side_effect=[
                {"success": False, "required": True, "endpoint": "svc", "error": "down"},
                {"success": True, "required": False, "endpoint": "svc-fallback", "error": None},
            ],
        ):
            result = manager.yield_gpu_for_training(gpu_id=0, job_id="job-123")

        assert result["success"] is True
        assert manager._gpu_states[0] == GPUState.TRAINING
        assert manager._active_jobs[0] == "job-123"
        assert result["services"]["svc"]["success"] is False
        assert result["services"]["svc-fallback"]["success"] is True
        assert manager.get_yield_history()[-1]["action"] == "yield"

    def test_yield_gpu_for_training_records_required_failure(self):
        from shml_training.core.gpu_resource import GPUResourceManager, ServiceEndpoint

        endpoint = ServiceEndpoint(
            name="svc",
            yield_url="http://primary/yield",
            reclaim_url="http://primary/reclaim",
            status_url="http://primary/status",
            gpu_id=0,
            required=True,
        )
        manager = GPUResourceManager(endpoints=[endpoint], use_fallback=False)

        with patch.object(
            manager,
            "_yield_service",
            return_value={"success": False, "required": True, "endpoint": "svc", "error": "down"},
        ):
            result = manager.yield_gpu_for_training(gpu_id=0, job_id="job-123")

        assert result["success"] is False
        assert "Required service svc failed to yield" in result["errors"]

    def test_reclaim_gpu_after_training_clears_state_and_softens_failures(self):
        from shml_training.core.gpu_resource import GPUResourceManager, GPUState, ServiceEndpoint

        endpoint = ServiceEndpoint(
            name="svc",
            yield_url="http://primary/yield",
            reclaim_url="http://primary/reclaim",
            status_url="http://primary/status",
            gpu_id=0,
            priority=5,
        )
        manager = GPUResourceManager(endpoints=[endpoint], use_fallback=False)
        manager._gpu_states[0] = GPUState.TRAINING
        manager._active_jobs[0] = "job-123"

        with patch.object(
            manager,
            "_reclaim_service",
            return_value={"success": True, "required": False, "endpoint": "svc", "error": None},
        ):
            result = manager.reclaim_gpu_after_training(gpu_id=0)

        assert result["job_id"] == "job-123"
        assert manager._gpu_states[0] == GPUState.IDLE
        assert 0 not in manager._active_jobs
        assert manager.get_yield_history()[-1]["action"] == "reclaim"

    def test_reclaim_service_never_propagates_failure(self):
        from shml_training.core.gpu_resource import GPUResourceManager, ServiceEndpoint

        endpoint = ServiceEndpoint(
            name="svc",
            yield_url="http://primary/yield",
            reclaim_url="http://primary/reclaim",
            status_url="http://primary/status",
            gpu_id=0,
            required=True,
        )
        manager = GPUResourceManager(endpoints=[endpoint], use_fallback=False)

        with patch.object(manager, "_http_request", return_value=(False, None, "offline")):
            result = manager._reclaim_service(endpoint, "job-123")

        assert result["success"] is True
        assert result["required"] is True
        assert result["error"] == "offline"

    def test_get_gpu_status_queries_services(self):
        from shml_training.core.gpu_resource import GPUResourceManager, GPUState

        manager = GPUResourceManager(use_fallback=False)
        manager._gpu_states[0] = GPUState.TRAINING
        manager._active_jobs[0] = "job-123"

        with patch.object(manager, "_http_request", return_value=(True, {"state": "ok"}, None)) as http_request:
            result = manager.get_gpu_status(0)

        assert result["state"] == "training"
        assert result["active_job"] == "job-123"
        assert http_request.call_count == len(manager._get_endpoints_for_gpu(0))


class TestContextsAndConvenienceHelpers:
    def test_training_context_yields_and_reclaims(self):
        from shml_training.core.gpu_resource import TrainingContext

        manager = MagicMock()
        manager.yield_gpu_for_training.return_value = {"success": True}
        manager.reclaim_gpu_after_training.return_value = {"success": True}

        with patch("shml_training.core.gpu_resource.GPUResourceManager", return_value=manager), patch(
            "shml_training.core.gpu_resource.time.sleep"
        ):
            with TrainingContext(job_id="job-123", gpu_id=1, memory_required_gb=12.0) as ctx:
                assert ctx["job_id"] == "job-123"
                assert ctx["gpu_id"] == 1
                assert ctx["yield_result"] == {"success": True}

        manager.yield_gpu_for_training.assert_called_once_with(
            gpu_id=1,
            job_id="job-123",
            estimated_duration_hours=2.0,
            memory_required_gb=12.0,
        )
        manager.reclaim_gpu_after_training.assert_called_once_with(gpu_id=1, job_id="job-123")

    @pytest.mark.asyncio
    async def test_async_training_context_uses_executor_for_yield_and_reclaim(self):
        from shml_training.core.gpu_resource import AsyncTrainingContext

        manager = MagicMock()
        manager.yield_gpu_for_training.return_value = {"success": True}
        manager.reclaim_gpu_after_training.return_value = {"success": True}

        class FakeLoop:
            async def run_in_executor(self, executor, func):
                return func()

        with patch("shml_training.core.gpu_resource.GPUResourceManager", return_value=manager), patch(
            "shml_training.core.gpu_resource.asyncio.get_event_loop",
            return_value=FakeLoop(),
        ), patch("shml_training.core.gpu_resource.asyncio.sleep"):
            async with AsyncTrainingContext(job_id="job-123", gpu_id=2) as ctx:
                assert ctx["job_id"] == "job-123"
                assert ctx["gpu_id"] == 2

        manager.yield_gpu_for_training.assert_called_once()
        manager.reclaim_gpu_after_training.assert_called_once_with(gpu_id=2, job_id="job-123")

    def test_ensure_gpu_available_for_training_respects_required_flag(self):
        from shml_training.core.gpu_resource import ensure_gpu_available_for_training

        manager = MagicMock()
        manager.yield_gpu_for_training.return_value = {
            "services": {
                "svc": {"success": False, "required": True},
                "optional": {"success": False, "required": False},
            }
        }

        with patch("shml_training.core.gpu_resource.GPUResourceManager", return_value=manager):
            assert ensure_gpu_available_for_training(gpu_id=0, job_id="job-123") is False

    def test_release_gpu_after_training_invokes_manager(self):
        from shml_training.core.gpu_resource import release_gpu_after_training

        manager = MagicMock()
        with patch("shml_training.core.gpu_resource.GPUResourceManager", return_value=manager):
            release_gpu_after_training(gpu_id=0, job_id="job-123")

        manager.reclaim_gpu_after_training.assert_called_once_with(gpu_id=0, job_id="job-123")


class TestGPUResourceCoverage:
    def test_http_request_handles_timeout_and_generic_exception(self):
        from shml_training.core.gpu_resource import GPUResourceManager

        manager = GPUResourceManager(dry_run=False)

        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            success, response, error = manager._http_request("http://example.com", timeout=7.0)
        assert success is False
        assert response is None
        assert error == "Timeout after 7.0s"

        with patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
            success, response, error = manager._http_request("http://example.com")
        assert success is False
        assert response is None
        assert error == "boom"

    def test_http_request_reads_http_error_body_when_present(self):
        import io
        import urllib.error

        from shml_training.core.gpu_resource import GPUResourceManager

        manager = GPUResourceManager(dry_run=False)
        http_error = urllib.error.HTTPError(
            url="http://example.com",
            code=500,
            msg="broken",
            hdrs=None,
            fp=io.BytesIO(b"backend down"),
        )

        with patch("urllib.request.urlopen", side_effect=http_error):
            success, response, error = manager._http_request("http://example.com")

        assert success is False
        assert response is None
        assert error == "HTTP 500: backend down"

    def test_yield_gpu_for_training_without_endpoints_returns_warning(self):
        from shml_training.core.gpu_resource import GPUResourceManager

        manager = GPUResourceManager(endpoints=[], use_fallback=False)
        result = manager.yield_gpu_for_training(gpu_id=9, job_id="job-no-ep")

        assert result["success"] is True
        assert result["warnings"] == ["No endpoints configured"]

    def test_yield_service_success_and_failure_paths(self):
        from shml_training.core.gpu_resource import GPUResourceManager, ServiceEndpoint

        endpoint = ServiceEndpoint(
            name="svc",
            yield_url="http://svc/yield",
            reclaim_url="http://svc/reclaim",
            status_url="http://svc/status",
            gpu_id=0,
            required=True,
        )
        manager = GPUResourceManager(endpoints=[endpoint], use_fallback=False)

        with patch.object(manager, "_http_request", return_value=(True, {"ok": True}, None)):
            success_result = manager._yield_service(endpoint, "job-1", 2.0, 20.0)
        assert success_result["success"] is True
        assert success_result["response"] == {"ok": True}

        with patch.object(manager, "_http_request", return_value=(False, None, "offline")):
            failure_result = manager._yield_service(endpoint, "job-1", 2.0, 20.0)
        assert failure_result["success"] is False
        assert failure_result["error"] == "offline"

    def test_find_fallback_endpoint_returns_none_when_no_match(self):
        from shml_training.core.gpu_resource import GPUResourceManager

        manager = GPUResourceManager(use_fallback=True)
        assert manager._find_fallback_endpoint("not-a-service", 0) is None

    def test_reclaim_gpu_after_training_uses_fallback_and_unknown_job(self):
        from shml_training.core.gpu_resource import GPUResourceManager, GPUState, ServiceEndpoint

        endpoint = ServiceEndpoint(
            name="svc",
            yield_url="http://svc/yield",
            reclaim_url="http://svc/reclaim",
            status_url="http://svc/status",
            gpu_id=0,
            priority=5,
        )
        fallback = ServiceEndpoint(
            name="svc-fallback",
            yield_url="http://svc-fallback/yield",
            reclaim_url="http://svc-fallback/reclaim",
            status_url="http://svc-fallback/status",
            gpu_id=0,
            priority=5,
        )
        manager = GPUResourceManager(endpoints=[endpoint], use_fallback=False)
        manager.fallback_endpoints = [fallback]

        with patch.object(
            manager,
            "_reclaim_service",
            side_effect=[
                {"success": False, "endpoint": "svc", "error": "down", "required": False},
                {"success": True, "endpoint": "svc-fallback", "error": None, "required": False},
            ],
        ):
            result = manager.reclaim_gpu_after_training(gpu_id=0, job_id=None)

        assert result["job_id"] == "unknown"
        assert result["services"]["svc-fallback"]["success"] is True
        assert manager._gpu_states[0] == GPUState.IDLE

    def test_reclaim_service_success_path_preserves_success(self):
        from shml_training.core.gpu_resource import GPUResourceManager, ServiceEndpoint

        endpoint = ServiceEndpoint(
            name="svc",
            yield_url="http://svc/yield",
            reclaim_url="http://svc/reclaim",
            status_url="http://svc/status",
            gpu_id=0,
        )
        manager = GPUResourceManager(endpoints=[endpoint], use_fallback=False)

        with patch.object(manager, "_http_request", return_value=(True, {"ok": True}, None)):
            result = manager._reclaim_service(endpoint, "job-1")

        assert result["success"] is True
        assert result["response"] == {"ok": True}

    def test_training_context_warns_on_yield_failure(self):
        from shml_training.core.gpu_resource import TrainingContext

        manager = MagicMock()
        manager.yield_gpu_for_training.return_value = {"success": False}
        manager.reclaim_gpu_after_training.return_value = {"success": True}

        with patch("shml_training.core.gpu_resource.GPUResourceManager", return_value=manager), patch(
            "shml_training.core.gpu_resource.time.sleep"
        ), patch("shml_training.core.gpu_resource.logger.warning") as warning:
            with TrainingContext(job_id="job-warn", gpu_id=0):
                pass

        assert warning.called

    @pytest.mark.asyncio
    async def test_async_training_context_warns_on_yield_failure(self):
        from shml_training.core.gpu_resource import AsyncTrainingContext

        manager = MagicMock()
        manager.yield_gpu_for_training.return_value = {"success": False}
        manager.reclaim_gpu_after_training.return_value = {"success": True}

        class FakeLoop:
            async def run_in_executor(self, executor, func):
                return func()

        with patch("shml_training.core.gpu_resource.GPUResourceManager", return_value=manager), patch(
            "shml_training.core.gpu_resource.asyncio.get_event_loop",
            return_value=FakeLoop(),
        ), patch("shml_training.core.gpu_resource.asyncio.sleep"), patch(
            "shml_training.core.gpu_resource.logger.warning"
        ) as warning:
            async with AsyncTrainingContext(job_id="job-warn", gpu_id=0):
                pass

        assert warning.called
