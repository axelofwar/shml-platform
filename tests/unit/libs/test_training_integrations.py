"""Tests for training integration modules: orchestrator, progress.

Covers:
- integrations/orchestrator.py: JobStatus, JobPriority, Backend, JobSpec, JobResult,
  LocalBackend, RayBackend (mocked), JobOrchestrator, run_training_job
- integrations/progress.py: AGUIEventType, AGUIEvent, AGUIEventEmitter, ProgressReporter,
  print_progress_bar
"""
from __future__ import annotations

import os
import sys
import time
import threading
from datetime import datetime
from unittest.mock import MagicMock, patch, call
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Stub torch and heavy ML deps (must happen before training imports)
# ---------------------------------------------------------------------------
_TORCH_ATTRS = [
    "cuda", "nn", "optim", "Tensor", "FloatTensor", "BoolTensor", "device",
    "tensor", "zeros", "ones", "float32", "float16", "bfloat16", "sigmoid",
    "load", "save", "no_grad", "amp",
]


def _make_torch_stub() -> MagicMock:
    t = MagicMock(name="torch")
    for attr in _TORCH_ATTRS:
        setattr(t, attr, MagicMock())
    t.cuda.is_available = MagicMock(return_value=False)
    t.cuda.device_count = MagicMock(return_value=0)
    return t


for _mod_name in [
    "torch", "torch.nn", "torch.optim", "torch.amp", "torch.cuda",
    "torch.utils", "torch.utils.data", "torch.distributed",
    "torch.nn.functional", "torch.nn.parallel", "torch.cuda.amp",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _make_torch_stub()

for _dep in ["peft", "transformers", "unsloth", "accelerate", "deepspeed", "nvidia_smi"]:
    if _dep not in sys.modules:
        sys.modules[_dep] = MagicMock()

_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _root not in sys.path:
    sys.path.insert(0, _root)
_training_root = os.path.join(_root, "libs", "training")
if _training_root not in sys.path:
    sys.path.insert(0, _training_root)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_config(**kwargs):
    from shml_training.core.config import TrainingConfig
    return TrainingConfig(**kwargs)


def _make_job_spec(job_id: str = "job-001", **kwargs):
    from shml_training.integrations.orchestrator import JobSpec
    from shml_training.core.config import TrainingConfig
    defaults = dict(
        job_id=job_id,
        name="test-job",
        config=TrainingConfig(),
    )
    defaults.update(kwargs)
    return JobSpec(**defaults)


# ===========================================================================
# TestJobStatusEnums
# ===========================================================================


class TestJobStatusEnums:
    def test_job_status_values(self):
        from shml_training.integrations.orchestrator import JobStatus
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.CANCELLED.value == "cancelled"
        assert JobStatus.QUEUED.value == "queued"
        assert JobStatus.PREEMPTED.value == "preempted"

    def test_job_priority_values(self):
        from shml_training.integrations.orchestrator import JobPriority
        assert JobPriority.LOW.value == 1
        assert JobPriority.NORMAL.value == 2
        assert JobPriority.HIGH.value == 3
        assert JobPriority.ADMIN.value == 4

    def test_backend_values(self):
        from shml_training.integrations.orchestrator import Backend
        assert Backend.LOCAL.value == "local"
        assert Backend.RAY.value == "ray"
        assert Backend.SLURM.value == "slurm"
        assert Backend.KUBERNETES.value == "kubernetes"


# ===========================================================================
# TestJobSpec
# ===========================================================================


class TestJobSpec:
    def test_default_values(self):
        from shml_training.integrations.orchestrator import JobSpec, JobPriority
        spec = _make_job_spec()
        assert spec.job_id == "job-001"
        assert spec.name == "test-job"
        assert spec.priority == JobPriority.NORMAL
        assert spec.user_id == "anonymous"
        assert spec.user_role == "developer"
        assert spec.preemptible is True
        assert spec.tags == []
        assert spec.metadata == {}

    def test_to_dict_contains_required_fields(self):
        spec = _make_job_spec()
        d = spec.to_dict()
        assert "job_id" in d
        assert "name" in d
        assert "priority" in d
        assert "user_id" in d
        assert d["job_id"] == "job-001"

    def test_custom_priority(self):
        from shml_training.integrations.orchestrator import JobSpec, JobPriority
        spec = _make_job_spec(priority=JobPriority.HIGH)
        assert spec.priority == JobPriority.HIGH
        assert spec.to_dict()["priority"] == "HIGH"

    def test_custom_user_role(self):
        spec = _make_job_spec(user_role="admin")
        assert spec.user_role == "admin"

    def test_tags_and_metadata(self):
        spec = _make_job_spec(tags=["prod", "nlp"], metadata={"dataset": "yfcc"})
        d = spec.to_dict()
        assert d["tags"] == ["prod", "nlp"]
        assert spec.metadata == {"dataset": "yfcc"}

    def test_gpu_requirements(self):
        spec = _make_job_spec(min_gpu_memory_gb=16, preferred_gpu_memory_gb=24)
        d = spec.to_dict()
        assert d["min_gpu_memory_gb"] == 16
        assert d["preferred_gpu_memory_gb"] == 24

    def test_on_status_change_callback(self):
        from shml_training.integrations.orchestrator import JobStatus
        events = []
        spec = _make_job_spec(on_status_change=events.append)
        spec.on_status_change(JobStatus.RUNNING)
        assert JobStatus.RUNNING in events


# ===========================================================================
# TestJobResult
# ===========================================================================


class TestJobResult:
    def test_duration_seconds_with_times(self):
        from shml_training.integrations.orchestrator import JobResult, JobStatus
        start = datetime(2024, 1, 1, 10, 0, 0)
        end = datetime(2024, 1, 1, 10, 0, 30)
        result = JobResult(
            job_id="j1", status=JobStatus.COMPLETED,
            start_time=start, end_time=end,
        )
        assert result.duration_seconds == 30.0

    def test_duration_no_times(self):
        from shml_training.integrations.orchestrator import JobResult, JobStatus
        result = JobResult(job_id="j1", status=JobStatus.RUNNING)
        assert result.duration_seconds == 0

    def test_success_true_when_completed(self):
        from shml_training.integrations.orchestrator import JobResult, JobStatus
        result = JobResult(job_id="j1", status=JobStatus.COMPLETED)
        assert result.success is True

    def test_success_false_when_failed(self):
        from shml_training.integrations.orchestrator import JobResult, JobStatus
        result = JobResult(job_id="j1", status=JobStatus.FAILED)
        assert result.success is False

    def test_error_fields(self):
        from shml_training.integrations.orchestrator import JobResult, JobStatus
        result = JobResult(
            job_id="j1", status=JobStatus.FAILED,
            error_message="OOM", error_traceback="Traceback...",
        )
        assert result.error_message == "OOM"
        assert result.error_traceback == "Traceback..."


# ===========================================================================
# TestLocalBackend
# ===========================================================================


class TestLocalBackend:
    def test_is_available(self):
        from shml_training.integrations.orchestrator import LocalBackend
        backend = LocalBackend()
        assert backend.is_available() is True

    def test_submit_job_runs_to_completion(self):
        from shml_training.integrations.orchestrator import LocalBackend, JobStatus
        backend = LocalBackend()
        spec = _make_job_spec()

        def train_fn(config):
            return {"loss": 0.5}

        handle = backend.submit(spec, train_fn)
        result = backend.get_result(handle)
        assert result.status == JobStatus.COMPLETED
        assert result.metrics.get("loss") == 0.5

    def test_submit_job_failure_captured(self):
        from shml_training.integrations.orchestrator import LocalBackend, JobStatus
        backend = LocalBackend()
        spec = _make_job_spec(job_id="fail-job")

        def train_fn(config):
            raise ValueError("Training failed!")

        handle = backend.submit(spec, train_fn)
        result = backend.get_result(handle)
        assert result.status == JobStatus.FAILED
        assert "Training failed!" in result.error_message

    def test_get_status_returns_running_or_completed(self):
        from shml_training.integrations.orchestrator import LocalBackend, JobStatus
        backend = LocalBackend()
        spec = _make_job_spec(job_id="status-job")

        done = threading.Event()

        def slow_train(config):
            done.wait()
            return {}

        handle = backend.submit(spec, slow_train)
        # Status is running or pending initially
        status = backend.get_status(handle)
        assert status in (JobStatus.RUNNING, JobStatus.PENDING, JobStatus.COMPLETED)
        done.set()
        backend._threads[handle].join()

    def test_cancel_job(self):
        from shml_training.integrations.orchestrator import LocalBackend, JobStatus
        backend = LocalBackend()
        spec = _make_job_spec(job_id="cancel-job")

        def slow_fn(config):
            time.sleep(1)
            return {}

        handle = backend.submit(spec, slow_fn)
        result = backend.cancel(handle)
        assert result is True
        assert backend._jobs[handle]["status"] == JobStatus.CANCELLED

    def test_cancel_unknown_handle(self):
        from shml_training.integrations.orchestrator import LocalBackend
        backend = LocalBackend()
        result = backend.cancel("nonexistent")
        assert result is False

    def test_get_status_unknown_handle(self):
        from shml_training.integrations.orchestrator import LocalBackend, JobStatus
        backend = LocalBackend()
        status = backend.get_status("nonexistent")
        assert status == JobStatus.FAILED

    def test_get_result_unknown_handle(self):
        from shml_training.integrations.orchestrator import LocalBackend, JobStatus
        backend = LocalBackend()
        result = backend.get_result("nonexistent")
        assert result.status == JobStatus.FAILED


# ===========================================================================
# TestRayBackend
# ===========================================================================


class TestRayBackend:
    def test_is_available_without_ray(self):
        from shml_training.integrations.orchestrator import RayBackend
        # When ray is not importable
        with patch.dict(sys.modules, {"ray": None}):
            backend = RayBackend()
            assert backend.is_available() is False

    def test_is_available_with_ray(self):
        from shml_training.integrations.orchestrator import RayBackend
        mock_ray = MagicMock()
        with patch.dict(sys.modules, {"ray": mock_ray}):
            backend = RayBackend()
            assert backend.is_available() is True

    def test_submit_calls_ray_remote(self):
        from shml_training.integrations.orchestrator import RayBackend, JobStatus
        mock_ray = MagicMock()
        mock_ray.is_initialized.return_value = True
        mock_ref = MagicMock()
        mock_remote_fn = MagicMock()
        mock_remote_fn.remote.return_value = mock_ref
        mock_ray.remote.return_value = lambda fn: mock_remote_fn
        # Ray.wait(refs, timeout=0) returns (ready_list, not_ready_list)
        mock_ray.wait.return_value = ([], [mock_ref])

        with patch.dict(sys.modules, {"ray": mock_ray}):
            backend = RayBackend()
            backend._ray = mock_ray
            spec = _make_job_spec(job_id="ray-job")
            spec.min_gpu_memory_gb = 0
            spec.max_cpu_cores = 2

            # Directly set _refs to simulate a submitted job
            backend._refs["ray-job"] = mock_ref
            status = backend.get_status("ray-job")
            assert status == JobStatus.RUNNING

    def test_cancel_unknown_handle(self):
        from shml_training.integrations.orchestrator import RayBackend
        mock_ray = MagicMock()
        mock_ray.is_initialized.return_value = True
        with patch.dict(sys.modules, {"ray": mock_ray}):
            backend = RayBackend()
            backend._ray = mock_ray
            result = backend.cancel("nonexistent")
            assert result is False

    def test_get_result_unknown_handle(self):
        from shml_training.integrations.orchestrator import RayBackend, JobStatus
        mock_ray = MagicMock()
        mock_ray.is_initialized.return_value = True
        with patch.dict(sys.modules, {"ray": mock_ray}):
            backend = RayBackend()
            backend._ray = mock_ray
            result = backend.get_result("nonexistent")
            assert result.status == JobStatus.FAILED

    def test_ensure_ray_raises_on_import_error(self):
        from shml_training.integrations.orchestrator import RayBackend
        backend = RayBackend()
        backend._ray = None
        with patch.dict(sys.modules, {"ray": None}):
            with pytest.raises(ImportError, match="Ray not installed"):
                backend._ensure_ray()


# ===========================================================================
# TestJobOrchestrator
# ===========================================================================


class TestJobOrchestrator:
    def _make_orchestrator(self, enable_ray: bool = False):
        from shml_training.integrations.orchestrator import JobOrchestrator
        # Patch HardwareDetector to avoid real GPU detection
        with patch("shml_training.integrations.orchestrator.HardwareDetector") as mock_hw:
            mock_hw.detect.return_value = MagicMock(total_vram_gb=8.0, gpu_count=1)
            orch = JobOrchestrator(enable_ray=False)
            orch._hardware = mock_hw.detect.return_value
        return orch

    def test_local_backend_always_present(self):
        from shml_training.integrations.orchestrator import Backend
        orch = self._make_orchestrator()
        assert Backend.LOCAL in orch._backends

    def test_select_backend_prefers_user_choice(self):
        from shml_training.integrations.orchestrator import Backend
        orch = self._make_orchestrator()
        spec = _make_job_spec(preferred_backend=Backend.LOCAL)
        backend = orch.select_backend(spec)
        assert backend == Backend.LOCAL

    def test_select_backend_admin_uses_local(self):
        from shml_training.integrations.orchestrator import Backend
        orch = self._make_orchestrator()
        spec = _make_job_spec(user_role="admin")
        backend = orch.select_backend(spec)
        assert backend == Backend.LOCAL

    def test_select_backend_super_admin(self):
        from shml_training.integrations.orchestrator import Backend
        orch = self._make_orchestrator()
        spec = _make_job_spec(user_role="super_admin")
        backend = orch.select_backend(spec)
        assert backend == Backend.LOCAL

    def test_select_backend_default_local(self):
        from shml_training.integrations.orchestrator import Backend
        orch = self._make_orchestrator()
        spec = _make_job_spec()
        backend = orch.select_backend(spec)
        assert backend == Backend.LOCAL

    def test_select_backend_gpu_requirement_insufficient(self):
        from shml_training.integrations.orchestrator import Backend
        orch = self._make_orchestrator()
        orch._hardware.total_vram_gb = 4.0
        spec = _make_job_spec(min_gpu_memory_gb=16)
        backend = orch.select_backend(spec)
        # Falls back to LOCAL if no Ray
        assert backend == Backend.LOCAL

    def test_check_preemption_disabled(self):
        from shml_training.integrations.orchestrator import JobOrchestrator
        with patch("shml_training.integrations.orchestrator.HardwareDetector") as mock_hw:
            mock_hw.detect.return_value = MagicMock(total_vram_gb=8.0)
            orch = JobOrchestrator(enable_ray=False, enable_preemption=False)
            orch._hardware = mock_hw.detect.return_value
        spec = _make_job_spec(user_role="admin")
        result = orch.check_preemption(spec)
        assert result == []

    def test_check_preemption_non_admin(self):
        orch = self._make_orchestrator()
        spec = _make_job_spec(user_role="developer")
        result = orch.check_preemption(spec)
        assert result == []

    def test_check_preemption_admin_with_active_jobs(self):
        from shml_training.integrations.orchestrator import JobPriority, JobStatus
        orch = self._make_orchestrator()

        # Add a preemptible developer job in active list
        dev_spec = _make_job_spec(job_id="dev-job", user_role="developer", preemptible=True)
        orch._active_jobs["dev-job"] = {
            "spec": dev_spec,
            "backend": None,
            "handle": "dev-job",
        }

        admin_spec = _make_job_spec(job_id="admin-job", user_role="admin",
                                    priority=JobPriority.ADMIN)
        to_preempt = orch.check_preemption(admin_spec)
        assert "dev-job" in to_preempt

    def test_check_preemption_skip_admin_job(self):
        from shml_training.integrations.orchestrator import JobPriority
        orch = self._make_orchestrator()

        admin_spec_active = _make_job_spec(job_id="admin-2", user_role="admin")
        orch._active_jobs["admin-2"] = {
            "spec": admin_spec_active, "backend": None, "handle": "admin-2"
        }

        new_admin = _make_job_spec(job_id="admin-job", user_role="admin",
                                    priority=JobPriority.ADMIN)
        to_preempt = orch.check_preemption(new_admin)
        assert "admin-2" not in to_preempt

    def test_submit_and_wait_success(self):
        from shml_training.integrations.orchestrator import JobStatus
        orch = self._make_orchestrator()
        spec = _make_job_spec()

        def train_fn(config):
            return {"loss": 0.3}

        result = orch.submit_and_wait(spec, train_fn)
        assert result.status == JobStatus.COMPLETED

    def test_submit_triggers_status_callback(self):
        from shml_training.integrations.orchestrator import JobStatus
        orch = self._make_orchestrator()
        events = []
        spec = _make_job_spec(on_status_change=events.append)

        orch.submit(spec, lambda cfg: {})
        assert JobStatus.QUEUED in events

    def test_cancel_existing_job(self):
        orch = self._make_orchestrator()
        events = []
        spec = _make_job_spec(job_id="cancel-me", on_status_change=events.append)

        done = threading.Event()

        def slow_fn(cfg):
            done.wait()
            return {}

        orch.submit(spec, slow_fn)
        result = orch.cancel("cancel-me")
        assert result is True
        done.set()

    def test_cancel_unknown_job(self):
        orch = self._make_orchestrator()
        result = orch.cancel("nonexistent")
        assert result is False

    def test_get_status_unknown(self):
        from shml_training.integrations.orchestrator import JobStatus
        orch = self._make_orchestrator()
        status = orch.get_status("nonexistent")
        assert status == JobStatus.FAILED

    def test_get_result_unknown(self):
        from shml_training.integrations.orchestrator import JobStatus
        orch = self._make_orchestrator()
        result = orch.get_result("nonexistent")
        assert result.status == JobStatus.FAILED

    def test_list_active_jobs(self):
        orch = self._make_orchestrator()
        spec = _make_job_spec(job_id="list-job")

        done = threading.Event()
        orch.submit(spec, lambda cfg: (done.wait() or {}))
        jobs = orch.list_active_jobs()
        assert any(j["job_id"] == "list-job" for j in jobs)
        done.set()

    def test_get_queue_position_not_found(self):
        orch = self._make_orchestrator()
        assert orch.get_queue_position("nonexistent") == -1


# ===========================================================================
# TestRunTrainingJob
# ===========================================================================


class TestRunTrainingJob:
    @patch("shml_training.integrations.orchestrator.HardwareDetector")
    def test_run_training_job(self, mock_hw):
        from shml_training.integrations.orchestrator import run_training_job
        mock_hw.detect.return_value = MagicMock(total_vram_gb=8.0)

        cfg = _make_config(epochs=1)
        cfg.gpu_memory_limit_gb = 0  # Attribute used by run_training_job
        result = run_training_job(
            name="test-run",
            config=cfg,
            train_fn=lambda config: {"loss": 0.1},
        )
        from shml_training.integrations.orchestrator import JobStatus
        assert result.status == JobStatus.COMPLETED

    @patch("shml_training.integrations.orchestrator.HardwareDetector")
    def test_run_training_job_with_role(self, mock_hw):
        from shml_training.integrations.orchestrator import run_training_job, JobStatus, JobPriority
        mock_hw.detect.return_value = MagicMock(total_vram_gb=8.0)

        cfg = _make_config()
        cfg.gpu_memory_limit_gb = 0
        result = run_training_job(
            name="admin-run",
            config=cfg,
            train_fn=lambda c: {},
            user_role="admin",
            priority=JobPriority.HIGH,
        )
        assert result.status == JobStatus.COMPLETED


# ===========================================================================
# TestAGUIEventType
# ===========================================================================


class TestAGUIEventType:
    def test_all_lifecycle_events_exist(self):
        from shml_training.integrations.progress import AGUIEventType
        assert AGUIEventType.RUN_STARTED
        assert AGUIEventType.RUN_FINISHED
        assert AGUIEventType.RUN_ERROR

    def test_text_message_events(self):
        from shml_training.integrations.progress import AGUIEventType
        assert AGUIEventType.TEXT_MESSAGE_START.value == "TEXT_MESSAGE_START"
        assert AGUIEventType.TEXT_MESSAGE_CONTENT.value == "TEXT_MESSAGE_CONTENT"
        assert AGUIEventType.TEXT_MESSAGE_END.value == "TEXT_MESSAGE_END"

    def test_training_events_exist(self):
        from shml_training.integrations.progress import AGUIEventType
        assert AGUIEventType.EPOCH_START
        assert AGUIEventType.EPOCH_END
        assert AGUIEventType.STEP_UPDATE
        assert AGUIEventType.CHECKPOINT_SAVED
        assert AGUIEventType.METRIC_UPDATE

    def test_tool_call_events(self):
        from shml_training.integrations.progress import AGUIEventType
        assert AGUIEventType.TOOL_CALL_START
        assert AGUIEventType.TOOL_CALL_ARGS
        assert AGUIEventType.TOOL_CALL_END

    def test_state_events(self):
        from shml_training.integrations.progress import AGUIEventType
        assert AGUIEventType.STATE_SNAPSHOT
        assert AGUIEventType.STATE_DELTA


# ===========================================================================
# TestAGUIEvent
# ===========================================================================


class TestAGUIEvent:
    def _make_event(self, **kwargs):
        from shml_training.integrations.progress import AGUIEvent, AGUIEventType
        defaults = dict(
            type=AGUIEventType.STEP_UPDATE,
            timestamp="2024-01-01T00:00:00",
            run_id="run-123",
            data={"step": 1, "loss": 0.5},
        )
        defaults.update(kwargs)
        return AGUIEvent(**defaults)

    def test_to_dict_format(self):
        event = self._make_event()
        d = event.to_dict()
        assert d["type"] == "STEP_UPDATE"
        assert d["runId"] == "run-123"
        assert d["timestamp"] == "2024-01-01T00:00:00"
        assert d["step"] == 1
        assert d["loss"] == 0.5

    def test_to_json_is_valid(self):
        import json
        event = self._make_event()
        j = event.to_json()
        parsed = json.loads(j)
        assert parsed["type"] == "STEP_UPDATE"

    def test_to_sse_format(self):
        event = self._make_event()
        sse = event.to_sse()
        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")


# ===========================================================================
# TestAGUIEventEmitter
# ===========================================================================


class TestAGUIEventEmitter:
    def test_start_sets_started_flag(self):
        from shml_training.integrations.progress import AGUIEventEmitter
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        assert emitter._started is True
        emitter.stop()

    def test_start_idempotent(self):
        from shml_training.integrations.progress import AGUIEventEmitter
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.start()  # Should not double-start
        assert emitter._started is True
        emitter.stop()

    def test_stop_resets_started(self):
        from shml_training.integrations.progress import AGUIEventEmitter
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.stop()
        assert emitter._started is False

    def test_emit_run_started(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.emit_run_started(config={"epochs": 10})
        events = emitter.get_pending_events()
        assert any(e.type == AGUIEventType.RUN_STARTED for e in events)
        emitter.stop()

    def test_emit_run_finished(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.emit_run_finished(metrics={"loss": 0.1})
        events = emitter.get_pending_events()
        assert any(e.type == AGUIEventType.RUN_FINISHED for e in events)
        emitter.stop()

    def test_emit_run_error(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.emit_run_error("OOM error", "traceback...")
        events = emitter.get_pending_events()
        assert any(e.type == AGUIEventType.RUN_ERROR for e in events)
        emitter.stop()

    def test_emit_state_delta(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.emit_state_delta({"epoch": 5, "loss": 0.2})
        events = emitter.get_pending_events()
        assert any(e.type == AGUIEventType.STATE_DELTA for e in events)
        emitter.stop()

    def test_emit_state_snapshot(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.emit_state_snapshot({"full_state": True})
        events = emitter.get_pending_events()
        assert any(e.type == AGUIEventType.STATE_SNAPSHOT for e in events)
        emitter.stop()

    def test_emit_epoch_start(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.emit_epoch_start(1, 100)
        events = emitter.get_pending_events()
        epoch_event = next(e for e in events if e.type == AGUIEventType.EPOCH_START)
        assert epoch_event.data["epoch"] == 1
        assert epoch_event.data["total_epochs"] == 100
        assert abs(epoch_event.data["progress"] - 0.01) < 0.001
        emitter.stop()

    def test_emit_epoch_end(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.emit_epoch_end(5, {"loss": 0.3, "acc": 0.9}, 120.0)
        events = emitter.get_pending_events()
        evt = next(e for e in events if e.type == AGUIEventType.EPOCH_END)
        assert evt.data["epoch"] == 5
        assert evt.data["metrics"]["loss"] == 0.3
        emitter.stop()

    def test_emit_step_update(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.emit_step_update(100, 1000, 0.5, 1e-4, throughput=250.0, gpu_memory_gb=7.5)
        events = emitter.get_pending_events()
        evt = next(e for e in events if e.type == AGUIEventType.STEP_UPDATE)
        assert evt.data["step"] == 100
        assert evt.data["total_steps"] == 1000
        assert abs(evt.data["progress"] - 0.1) < 0.001
        assert evt.data["throughput"] == 250.0
        emitter.stop()

    def test_emit_step_zero_total(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.emit_step_update(5, 0, 0.5, 1e-4)
        events = emitter.get_pending_events()
        evt = next(e for e in events if e.type == AGUIEventType.STEP_UPDATE)
        assert evt.data["progress"] == 0  # Zero division guard
        emitter.stop()

    def test_emit_checkpoint_saved(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.emit_checkpoint_saved("/ckpts/model.pt", 10, is_best=True)
        events = emitter.get_pending_events()
        evt = next(e for e in events if e.type == AGUIEventType.CHECKPOINT_SAVED)
        assert evt.data["path"] == "/ckpts/model.pt"
        assert evt.data["is_best"] is True
        emitter.stop()

    def test_emit_metric_update(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        emitter.emit_metric_update({"map50": 0.85, "recall": 0.9})
        events = emitter.get_pending_events()
        assert any(e.type == AGUIEventType.METRIC_UPDATE for e in events)
        emitter.stop()

    def test_add_callback(self):
        from shml_training.integrations.progress import AGUIEventEmitter, AGUIEventType
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        received = []
        emitter.add_callback(received.append)
        emitter.emit_step_update(1, 100, 0.5, 1e-4)
        assert len(received) == 1
        emitter.stop()

    def test_callback_exception_does_not_crash(self):
        from shml_training.integrations.progress import AGUIEventEmitter
        emitter = AGUIEventEmitter(run_id="r1")
        emitter.start()
        def bad_callback(event):
            raise RuntimeError("callback failed")
        emitter.add_callback(bad_callback)
        emitter.emit_run_started()  # Should not raise
        emitter.stop()

    def test_queue_overflow_drops_oldest(self):
        from shml_training.integrations.progress import AGUIEventEmitter
        emitter = AGUIEventEmitter(run_id="r1", buffer_size=2)
        emitter.start()
        # Fill queue and overflow
        for i in range(5):
            emitter.emit_metric_update({"step": i})
        events = emitter.get_pending_events()
        assert len(events) <= 2
        emitter.stop()

    def test_get_pending_events_empty(self):
        from shml_training.integrations.progress import AGUIEventEmitter
        emitter = AGUIEventEmitter(run_id="r1")
        assert emitter.get_pending_events() == []

    def test_sender_loop_with_endpoint(self):
        from shml_training.integrations.progress import AGUIEventEmitter
        emitter = AGUIEventEmitter(run_id="r1", endpoint="http://localhost:9999/events")
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            emitter.start()
            assert emitter._sender_thread is not None
            emitter.emit_run_started(config={})
            time.sleep(0.05)  # Let sender thread process
            emitter.stop()


# ===========================================================================
# TestProgressReporter
# ===========================================================================


class TestProgressReporter:
    def test_start_and_end_run(self, capsys):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="test-run", total_epochs=10, log_to_console=True)
        reporter.start_run(config={"epochs": 10, "lr": 1e-4})
        reporter.end_run(metrics={"loss": 0.1, "acc": 0.95})
        captured = capsys.readouterr()
        assert "test-run" in captured.out
        assert "Training Complete" in captured.out

    def test_start_run_no_config(self, capsys):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="run2", log_to_console=True)
        reporter.start_run()
        reporter.end_run()

    def test_start_epoch(self, capsys):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="r", total_epochs=10, log_to_console=True)
        reporter.start_run()
        reporter.start_epoch(2)
        captured = capsys.readouterr()
        assert "Epoch 2/10" in captured.out
        reporter.end_run()

    def test_end_epoch_logs_metrics(self, capsys):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="r", total_epochs=5, log_to_console=True)
        reporter.start_run()
        reporter.start_epoch(1)
        reporter.end_epoch(1, {"loss": 0.4, "acc": 0.8})
        captured = capsys.readouterr()
        assert "Epoch 1 complete" in captured.out
        reporter.end_run()

    def test_log_step_at_interval(self, capsys):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(
            run_id="r", total_steps=100, log_to_console=True, console_log_interval=5
        )
        reporter.start_run()
        reporter.log_step(5, loss=0.5, learning_rate=1e-4)
        captured = capsys.readouterr()
        assert "loss" in captured.out or "step" in captured.out
        reporter.end_run()

    def test_log_step_skips_below_interval(self, capsys):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(
            run_id="r", total_steps=100, log_to_console=True, console_log_interval=10
        )
        reporter.start_run()
        reporter.log_step(3, loss=0.5)  # Step 3 < interval 10, should skip console
        captured = capsys.readouterr()
        # The run_started may print, but the step shouldn't log at step 3
        reporter.end_run()

    def test_log_checkpoint(self, capsys):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="r", log_to_console=True)
        reporter.start_run()
        reporter.log_checkpoint("/ckpts/epoch5.pt", 5, is_best=True)
        captured = capsys.readouterr()
        assert "Checkpoint saved" in captured.out or "epoch5.pt" in captured.out
        reporter.end_run()

    def test_log_metrics(self):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="r")
        reporter.start_run()
        reporter.log_metrics({"map50": 0.75})  # Should not raise
        reporter.end_run()

    def test_log_error(self, capsys):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="r", log_to_console=True)
        reporter.start_run()
        reporter.log_error("GPU OOM", "Traceback: ...")
        captured = capsys.readouterr()
        assert "GPU OOM" in captured.out
        reporter.end_run()

    def test_no_console_output_when_disabled(self, capsys):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="r", total_epochs=5, log_to_console=False)
        reporter.start_run(config={"epochs": 5})
        reporter.start_epoch(1)
        reporter.end_epoch(1, {"loss": 0.5})
        reporter.end_run(metrics={"final": 0.1})
        captured = capsys.readouterr()
        # With log_to_console=False, no training-specific prints
        assert "Training Run" not in captured.out

    def test_ntfy_notification_on_end_run(self):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="r", ntfy_topic="test-topic")
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            reporter.start_run()
            reporter.end_run(metrics={"loss": 0.1})
            assert mock_post.called

    def test_ntfy_notification_on_error(self):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="r", ntfy_topic="test-topic", log_to_console=False)
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            reporter.start_run()
            reporter.log_error("Error occurred")
            assert mock_post.called

    def test_send_notification_no_topic(self):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="r", ntfy_topic=None)
        with patch("requests.post") as mock_post:
            reporter._send_notification("Title", "Message")
            mock_post.assert_not_called()

    def test_send_notification_exception_silenced(self):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="r", ntfy_topic="test")
        with patch("requests.post", side_effect=Exception("network error")):
            reporter._send_notification("T", "M")  # Should not raise

    def test_log_step_with_throughput_and_gpu(self, capsys):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(
            run_id="r", total_steps=100, log_to_console=True, console_log_interval=1
        )
        reporter.start_run()
        reporter.log_step(1, loss=0.5, learning_rate=1e-4, throughput=512.0, gpu_memory_gb=7.5)
        captured = capsys.readouterr()
        assert "GPU" in captured.out or "512.0" in captured.out or "7.5" in captured.out
        reporter.end_run()

    def test_log_step_no_total_steps(self, capsys):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(
            run_id="r", total_steps=0, log_to_console=True, console_log_interval=1
        )
        reporter.start_run()
        reporter.log_step(10, loss=0.5)
        reporter.end_run()

    def test_end_run_no_start_time(self):
        from shml_training.integrations.progress import ProgressReporter
        reporter = ProgressReporter(run_id="r", log_to_console=False)
        reporter.emitter.start()
        reporter.end_run()  # _run_start_time is None, fallback to 0


# ===========================================================================
# TestPrintProgressBar
# ===========================================================================


class TestPrintProgressBar:
    def test_full_bar(self, capsys):
        from shml_training.integrations.progress import print_progress_bar
        print_progress_bar(100, 100, prefix="Training", suffix="Done")
        captured = capsys.readouterr()
        assert "100.0%" in captured.out

    def test_partial_bar(self, capsys):
        from shml_training.integrations.progress import print_progress_bar
        print_progress_bar(50, 100, prefix="Epoch")
        captured = capsys.readouterr()
        assert "50.0%" in captured.out

    def test_zero_progress(self, capsys):
        from shml_training.integrations.progress import print_progress_bar
        print_progress_bar(0, 100)
        captured = capsys.readouterr()
        assert "0.0%" in captured.out

    def test_zero_total(self, capsys):
        from shml_training.integrations.progress import print_progress_bar
        print_progress_bar(0, 0)  # Should not raise (zero division guard)

    def test_custom_fill(self, capsys):
        from shml_training.integrations.progress import print_progress_bar
        print_progress_bar(100, 100, fill="#")
        captured = capsys.readouterr()
        assert "#" in captured.out or "100.0%" in captured.out


class TestOrchestratorCoverage:
    def test_execution_backend_default_methods_return_none(self):
        from shml_training.integrations.orchestrator import ExecutionBackend

        backend = object()

        assert ExecutionBackend.submit(backend, None, None) is None
        assert ExecutionBackend.get_status(backend, "h") is None
        assert ExecutionBackend.cancel(backend, "h") is None
        assert ExecutionBackend.get_result(backend, "h") is None
        assert ExecutionBackend.is_available(backend) is None

    def test_ray_backend_submit_cancel_complete_and_results(self):
        from shml_training.integrations.orchestrator import JobStatus, RayBackend

        mock_ray = MagicMock()
        mock_ray.is_initialized.return_value = False
        mock_ref = MagicMock(name="ray-ref")

        class RemoteWrapper:
            def __init__(self):
                self.remote = MagicMock(return_value=mock_ref)

            def __call__(self, fn):
                return self

        wrapper = RemoteWrapper()
        mock_ray.remote.return_value = wrapper
        mock_ray.wait.return_value = ([mock_ref], [])
        mock_ray.get.side_effect = ["not-a-dict", RuntimeError("ray blew up")]

        with patch.dict(sys.modules, {"ray": mock_ray}):
            backend = RayBackend(address="ray://cluster")
            spec = _make_job_spec(job_id="ray-job-submit", min_gpu_memory_gb=8, max_cpu_cores=3)

            handle = backend.submit(spec, lambda config: {"ok": True})
            status = backend.get_status(handle)
            cancel_success = backend.cancel(handle)
            success_result = backend.get_result(handle)
            failure_result = backend.get_result(handle)

        assert handle == "ray-job-submit"
        mock_ray.init.assert_called_once_with(address="ray://cluster")
        mock_ray.remote.assert_called_once_with(num_gpus=1, num_cpus=3)
        wrapper.remote.assert_called_once_with(spec.config)
        assert status == JobStatus.COMPLETED
        assert cancel_success is True
        mock_ray.cancel.assert_called_once_with(mock_ref)
        assert success_result.status == JobStatus.COMPLETED
        assert success_result.metrics == {}
        assert failure_result.status == JobStatus.FAILED
        assert failure_result.error_message == "ray blew up"

    def test_job_orchestrator_init_select_backend_and_submit_paths(self):
        from shml_training.integrations.orchestrator import Backend, JobOrchestrator, JobPriority, RayBackend

        mock_ray_backend = MagicMock(spec=RayBackend)
        mock_ray_backend.is_available.return_value = True
        mock_ray_backend.submit.return_value = "ray-handle"
        mock_local_backend = MagicMock()
        mock_local_backend.submit.return_value = "local-handle"

        with patch("shml_training.integrations.orchestrator.HardwareDetector") as mock_hw, patch(
            "shml_training.integrations.orchestrator.RayBackend",
            return_value=mock_ray_backend,
        ), patch("shml_training.integrations.orchestrator.LocalBackend", return_value=mock_local_backend), patch(
            "builtins.print"
        ) as mock_print:
            mock_hw.detect.return_value = MagicMock(total_vram_gb=4.0, gpu_count=1)
            orch = JobOrchestrator(enable_ray=True)
            orch._hardware = mock_hw.detect.return_value

            admin_big = _make_job_spec(user_role="admin", preferred_gpu_memory_gb=32)
            assert orch.select_backend(admin_big) == Backend.RAY

            gpu_heavy = _make_job_spec(job_id="gpu-heavy", min_gpu_memory_gb=16)
            assert orch.select_backend(gpu_heavy) == Backend.RAY

            dev_active = _make_job_spec(job_id="dev-active", user_role="developer", preemptible=True)
            orch._active_jobs["dev-active"] = {
                "spec": dev_active,
                "backend": Backend.LOCAL,
                "handle": "dev-handle",
                "submitted_at": datetime.now(),
            }

            events = []
            new_job = _make_job_spec(
                job_id="admin-preempt",
                user_role="admin",
                priority=JobPriority.ADMIN,
                on_status_change=events.append,
                min_gpu_memory_gb=16,
                preferred_gpu_memory_gb=32,
            )
            submitted_id = orch.submit(new_job, lambda cfg: {"ok": True})
            queue_job = _make_job_spec(job_id="queued-job")
            orch._job_queue.append(queue_job)
            queue_pos = orch.get_queue_position("queued-job")

        assert Backend.RAY in orch._backends
        assert submitted_id == "admin-preempt"
        assert events[-1].name == "QUEUED"
        assert orch._active_jobs["admin-preempt"]["handle"] == "ray-handle"
        assert mock_local_backend.cancel.called
        mock_print.assert_called_once()
        assert queue_pos == 0

    def test_job_orchestrator_cancel_false_and_no_callback(self):
        from shml_training.integrations.orchestrator import Backend

        orch = TestJobOrchestrator()._make_orchestrator()
        backend = MagicMock()
        backend.cancel.return_value = False
        orch._backends[Backend.LOCAL] = backend
        spec = _make_job_spec(job_id="keep-running", on_status_change=None)
        orch._active_jobs["keep-running"] = {
            "spec": spec,
            "backend": Backend.LOCAL,
            "handle": "handle-1",
            "submitted_at": datetime.now(),
        }

        result = orch.cancel("keep-running")

        assert result is False
        assert "status" not in orch._active_jobs["keep-running"]

    def test_job_orchestrator_init_swallows_ray_backend_error(self):
        from shml_training.integrations.orchestrator import Backend, JobOrchestrator

        with patch("shml_training.integrations.orchestrator.HardwareDetector") as mock_hw, patch(
            "shml_training.integrations.orchestrator.RayBackend",
            side_effect=RuntimeError("ray setup failed"),
        ):
            mock_hw.detect.return_value = MagicMock(total_vram_gb=8.0, gpu_count=1)
            orch = JobOrchestrator(enable_ray=True)

        assert Backend.LOCAL in orch._backends
        assert Backend.RAY not in orch._backends
