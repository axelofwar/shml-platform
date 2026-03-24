"""Unit tests for ray_compute/api/training.py.

Tests:
- Pydantic model validation: TechniqueConfig, TrainingHyperparameters,
  ComputeConfig, TrainingJobRequest, TrainingJobResponse, TrainingJobStatus
- Helper functions: check_tier_access(), check_resource_quota(), generate_training_script()
- Endpoints: GET /models, GET /techniques, GET /tiers, GET /quota,
             GET /queue, POST /jobs, GET /jobs/{id}, GET /jobs/{id}/logs,
             DELETE /jobs/{id}
"""
from __future__ import annotations

import sys
import types
import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_RC_ROOT = _ROOT / "ray_compute"
for _p in [str(_ROOT), str(_RC_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Stub modules that training.py imports but aren't in conftest
# ---------------------------------------------------------------------------
if "ray_compute.api.database" not in sys.modules:
    _db_mod = types.ModuleType("ray_compute.api.database")
    _db_mod.get_db = lambda: iter([MagicMock()])
    _db_mod.SessionLocal = MagicMock()
    _db_mod.engine = MagicMock()
    sys.modules["ray_compute.api.database"] = _db_mod

_prev_audit_mod = sys.modules.get("ray_compute.api.audit")
_audit_mod = types.ModuleType("ray_compute.api.audit")
_audit_mod.log_audit_event = AsyncMock(return_value=None)
sys.modules["ray_compute.api.audit"] = _audit_mod

_prev_ut_mod = sys.modules.get("ray_compute.api.usage_tracking")
_ut_mod = types.ModuleType("ray_compute.api.usage_tracking")
_ut_mod.enforce_quota = MagicMock(return_value=None)
_ut_mod.get_user_quota_remaining = MagicMock(return_value={
    "gpu_hours_used": 1.0,
    "gpu_hours_limit": 48.0,
    "gpu_hours_remaining": 47.0,
    "cpu_hours_used": 2.0,
    "cpu_hours_limit": 96.0,
    "cpu_hours_remaining": 94.0,
    "concurrent_jobs": 0,
    "concurrent_jobs_limit": 5,
    "percent_used": 2.1,
})
_ut_mod.get_tier_limits = MagicMock(return_value={
    "name": "Free",
    "max_gpu_hours_per_day": 4,
    "max_cpu_hours_per_day": 8,
    "max_concurrent_jobs": 2,
    "max_gpu_fraction": 0.25,
    "max_job_timeout_hours": 12,
    "techniques_allowed": False,
    "can_use_custom_docker": False,
    "priority_weight": 1,
})
_ut_mod.update_job_usage = MagicMock(return_value=None)
_ut_mod.record_job_completion = MagicMock(return_value=None)
sys.modules["ray_compute.api.usage_tracking"] = _ut_mod

_prev_sched_mod = sys.modules.get("ray_compute.api.scheduler")
_sched_mod = types.ModuleType("ray_compute.api.scheduler")
_mock_scheduler = MagicMock()
_mock_scheduler.return_value.get_queue_overview.return_value = {
    "total": 2, "running": 1, "pending": 1,
    "gpu": {"rtx3090": {"allocated": 0.5, "jobs": {"job-1": 0.5}}},
}
_mock_scheduler.return_value.get_job_status.return_value = {
    "position": 1, "estimated_start": None,
}
_sched_mod.TrainingScheduler = _mock_scheduler
_sched_mod.get_queue_position = MagicMock(return_value=1)
_sched_mod.estimate_start_time = MagicMock(return_value=None)
_sched_mod.get_queue_stats = MagicMock(return_value={})
sys.modules["ray_compute.api.scheduler"] = _sched_mod

# ---------------------------------------------------------------------------
# Import training module after stubs are in place
# ---------------------------------------------------------------------------
import ray_compute.api.training as _tr  # noqa: E402

# Restore prior modules immediately after import so later test files are not
# affected, while training.py keeps the symbols it already imported.
for _stub_key, _previous_mod in [
    ("ray_compute.api.audit", _prev_audit_mod),
    ("ray_compute.api.usage_tracking", _prev_ut_mod),
    ("ray_compute.api.scheduler", _prev_sched_mod),
]:
    if _previous_mod is None:
        if sys.modules.get(_stub_key) in (_audit_mod, _ut_mod, _sched_mod):
            del sys.modules[_stub_key]
    else:
        sys.modules[_stub_key] = _previous_mod

# Grab dependency callables
from ray_compute.api.database import get_db as _database_get_db  # noqa: E402
from ray_compute.api.auth import get_current_user as _auth_get_current_user  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(role: str = "admin") -> MagicMock:
    user = MagicMock()
    user.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    user.username = "tester"
    user.email = "tester@test.local"
    user.role = role
    user.is_active = True
    user.is_suspended = False
    return user


def _make_quota(max_gpu_fraction=0.5, max_job_timeout_hours=48) -> MagicMock:
    quota = MagicMock()
    quota.max_gpu_fraction = max_gpu_fraction
    quota.max_job_timeout_hours = max_job_timeout_hours
    return quota


def _make_job(job_id: str = "training_abc123", user_id=None, status: str = "RUNNING") -> MagicMock:
    job = MagicMock()
    job.job_id = job_id
    job.ray_job_id = f"ray_{job_id}"
    job.user_id = user_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    job.name = f"Test Job {job_id}"
    job.status = status
    job.created_at = datetime(2024, 1, 1, 12, 0, 0)
    job.started_at = datetime(2024, 1, 1, 12, 0, 0)
    job.ended_at = None
    job.error_message = None
    job.gpu_time_seconds = 3600.0
    job.cpu_time_seconds = 7200.0
    job.metadata = {
        "mlflow_run_id": "run-abc",
        "mlflow_experiment": "test-exp",
        "hyperparameters": {"epochs": 100},
        "current_epoch": 50,
    }
    return job


def _make_db(job=None, quota=None) -> MagicMock:
    db = MagicMock()
    # Both job and quota can be returned via .filter().first()
    _query_chain = db.query.return_value.filter.return_value
    # First call returns job, second returns quota (using side_effect)
    results = []
    if job is not None:
        results.append(job)
    if quota is not None:
        results.append(quota)
    if len(results) == 0:
        _query_chain.first.return_value = None
    elif len(results) == 1:
        _query_chain.first.return_value = results[0]
    else:
        _query_chain.first.side_effect = results
    return db


def _make_client(user: MagicMock, db: MagicMock):
    """Build test app with training router."""
    test_app = FastAPI()
    test_app.include_router(_tr.router)
    test_app.dependency_overrides[_auth_get_current_user] = lambda: user
    test_app.dependency_overrides[_database_get_db] = lambda: db
    return test_app


# ===========================================================================
# Pydantic Model validation
# ===========================================================================

class TestTechniqueConfig:
    def test_valid_technique(self):
        tc = _tr.TechniqueConfig(name="sapo")
        assert tc.name == "sapo"
        assert tc.enabled is True
        assert tc.config == {}

    def test_all_valid_names(self):
        for name in ["sapo", "advantage_filter", "curriculum_learning"]:
            tc = _tr.TechniqueConfig(name=name)
            assert tc.name == name

    def test_invalid_name_raises(self):
        with pytest.raises(Exception):
            _tr.TechniqueConfig(name="invalid_technique")

    def test_disabled_technique(self):
        tc = _tr.TechniqueConfig(name="sapo", enabled=False)
        assert not tc.enabled

    def test_technique_with_config(self):
        tc = _tr.TechniqueConfig(name="sapo", config={"lr_factor": 0.1})
        assert tc.config == {"lr_factor": 0.1}


class TestTrainingHyperparameters:
    def test_defaults(self):
        hp = _tr.TrainingHyperparameters()
        assert hp.epochs == 100
        assert hp.batch_size == 16
        assert hp.learning_rate == 0.01
        assert hp.imgsz == 640

    def test_valid_imgsz_multiples_of_32(self):
        for sz in [320, 416, 640, 800, 1024, 1280]:
            hp = _tr.TrainingHyperparameters(imgsz=sz)
            assert hp.imgsz == sz

    def test_invalid_imgsz_not_multiple_of_32(self):
        with pytest.raises(Exception):
            _tr.TrainingHyperparameters(imgsz=500)

    def test_epoch_bounds(self):
        _tr.TrainingHyperparameters(epochs=1)
        _tr.TrainingHyperparameters(epochs=500)
        with pytest.raises(Exception):
            _tr.TrainingHyperparameters(epochs=0)
        with pytest.raises(Exception):
            _tr.TrainingHyperparameters(epochs=501)

    def test_batch_size_bounds(self):
        _tr.TrainingHyperparameters(batch_size=1)
        _tr.TrainingHyperparameters(batch_size=128)
        with pytest.raises(Exception):
            _tr.TrainingHyperparameters(batch_size=0)

    def test_optimizer_choices(self):
        for opt in ["SGD", "Adam", "AdamW"]:
            hp = _tr.TrainingHyperparameters(optimizer=opt)
            assert hp.optimizer == opt

    def test_invalid_optimizer(self):
        with pytest.raises(Exception):
            _tr.TrainingHyperparameters(optimizer="RMSprop")


class TestComputeConfig:
    def test_defaults(self):
        cc = _tr.ComputeConfig()
        assert cc.gpu_fraction == 0.25
        assert cc.cpu_cores == 4
        assert cc.timeout_hours == 24
        assert cc.priority == "normal"

    def test_valid_priority_values(self):
        for priority in ["low", "normal", "high"]:
            cc = _tr.ComputeConfig(priority=priority)
            assert cc.priority == priority

    def test_invalid_priority(self):
        with pytest.raises(Exception):
            _tr.ComputeConfig(priority="critical")

    def test_gpu_fraction_bounds(self):
        _tr.ComputeConfig(gpu_fraction=0.0)
        _tr.ComputeConfig(gpu_fraction=1.0)
        with pytest.raises(Exception):
            _tr.ComputeConfig(gpu_fraction=1.1)


class TestTrainingJobRequest:
    def _base_request(self, **kwargs) -> dict:
        return {
            "name": "Test Job",
            "model": "yolov8n",
            "dataset": "wider_face",
            **kwargs,
        }

    def test_minimal_valid_request(self):
        req = _tr.TrainingJobRequest(**self._base_request())
        assert req.name == "Test Job"
        assert req.model == _tr.ModelArchitecture.YOLOV8N
        assert req.dataset == _tr.DatasetSource.WIDER_FACE

    def test_custom_dataset_requires_url(self):
        with pytest.raises(Exception):
            _tr.TrainingJobRequest(**self._base_request(dataset="custom_gcs"))

    def test_custom_dataset_with_valid_gs_url(self):
        req = _tr.TrainingJobRequest(**self._base_request(
            dataset="custom_gcs", dataset_url="gs://my-bucket/dataset"
        ))
        assert req.dataset_url == "gs://my-bucket/dataset"

    def test_custom_dataset_with_invalid_url_scheme(self):
        with pytest.raises(Exception):
            _tr.TrainingJobRequest(**self._base_request(
                dataset="custom_s3", dataset_url="ftp://invalid"
            ))

    def test_custom_dataset_with_http_url(self):
        req = _tr.TrainingJobRequest(**self._base_request(
            dataset="custom_http", dataset_url="https://example.com/data.zip"
        ))
        assert req.dataset_url.startswith("https://")

    def test_techniques_list_adds_to_request(self):
        req = _tr.TrainingJobRequest(**self._base_request(
            techniques=[{"name": "sapo", "enabled": True}]
        ))
        assert len(req.techniques) == 1
        assert req.techniques[0].name == "sapo"


# ===========================================================================
# check_tier_access
# ===========================================================================

class TestCheckTierAccess:
    def test_no_techniques_any_role_passes(self):
        for role in ["user", "premium", "admin"]:
            user = _make_user(role=role)
            _tr.check_tier_access(user, [])

    def test_user_role_with_techniques_raises_403(self):
        user = _make_user(role="user")
        techniques = [_tr.TechniqueConfig(name="sapo")]
        with pytest.raises(HTTPException) as exc_info:
            _tr.check_tier_access(user, techniques)
        assert exc_info.value.status_code == 403

    def test_premium_role_with_techniques_passes(self):
        user = _make_user(role="premium")
        techniques = [_tr.TechniqueConfig(name="sapo")]
        _tr.check_tier_access(user, techniques)  # should not raise

    def test_admin_role_with_techniques_passes(self):
        user = _make_user(role="admin")
        techniques = [_tr.TechniqueConfig(name="advantage_filter")]
        _tr.check_tier_access(user, techniques)  # should not raise

    def test_user_role_upgrade_message_present(self):
        user = _make_user(role="user")
        techniques = [_tr.TechniqueConfig(name="curriculum_learning")]
        with pytest.raises(HTTPException) as exc_info:
            _tr.check_tier_access(user, techniques)
        assert "Pro" in exc_info.value.detail or "upgrade" in exc_info.value.detail.lower()


# ===========================================================================
# check_resource_quota
# ===========================================================================

class TestCheckResourceQuota:
    def _call(self, user, quota, compute=None, hp=None, db=None):
        compute = compute or _tr.ComputeConfig()
        hp = hp or _tr.TrainingHyperparameters()
        db = db or MagicMock()
        _tr.check_resource_quota(user, quota, compute, hp, db)

    def test_gpu_fraction_exceeded_raises_403(self):
        user = _make_user()
        quota = _make_quota(max_gpu_fraction=0.25)
        compute = _tr.ComputeConfig(gpu_fraction=0.5)
        with pytest.raises(HTTPException) as exc_info:
            self._call(user, quota, compute=compute)
        assert exc_info.value.status_code == 403
        assert "GPU fraction" in exc_info.value.detail

    def test_timeout_exceeded_raises_403(self):
        user = _make_user()
        quota = _make_quota(max_job_timeout_hours=12)
        compute = _tr.ComputeConfig(timeout_hours=24)
        with pytest.raises(HTTPException) as exc_info:
            self._call(user, quota, compute=compute)
        assert exc_info.value.status_code == 403
        assert "Timeout" in exc_info.value.detail

    def test_within_quota_calls_enforce_quota(self):
        user = _make_user()
        quota = _make_quota(max_gpu_fraction=1.0, max_job_timeout_hours=168)
        db = MagicMock()
        _ut_mod.enforce_quota.reset_mock()
        self._call(user, quota, db=db)
        _ut_mod.enforce_quota.assert_called_once()

    def test_enforce_quota_called_with_correct_args(self):
        user = _make_user()
        quota = _make_quota(max_gpu_fraction=1.0, max_job_timeout_hours=168)
        compute = _tr.ComputeConfig(gpu_fraction=0.5, timeout_hours=10, cpu_cores=4)
        hp = _tr.TrainingHyperparameters(epochs=50)
        db = MagicMock()
        _ut_mod.enforce_quota.reset_mock()
        self._call(user, quota, compute=compute, hp=hp, db=db)
        call_kwargs = _ut_mod.enforce_quota.call_args.kwargs
        assert call_kwargs["user"] is user
        assert call_kwargs["quota"] is quota


# ===========================================================================
# generate_training_script
# ===========================================================================

class TestGenerateTrainingScript:
    def _make_request(self):
        return _tr.TrainingJobRequest(
            name="test-train",
            model="yolov8n",
            dataset="wider_face",
        )

    def test_returns_string(self):
        req = self._make_request()
        user = _make_user()
        script = _tr.generate_training_script(req, user, "job_abc", "run_def")
        assert isinstance(script, str)

    def test_script_contains_job_id(self):
        req = self._make_request()
        user = _make_user()
        script = _tr.generate_training_script(req, user, "job_abc123", "run_xyz")
        assert "job_abc123" in script

    def test_script_contains_model_name(self):
        req = self._make_request()
        user = _make_user()
        script = _tr.generate_training_script(req, user, "job_1", "run_1")
        assert "yolov8n" in script

    def test_script_with_technique(self):
        req = _tr.TrainingJobRequest(
            name="test-sapo",
            model="yolov8s",
            dataset="wider_face",
            techniques=[_tr.TechniqueConfig(name="sapo", enabled=True)],
        )
        user = _make_user(role="premium")
        script = _tr.generate_training_script(req, user, "job_sapo", "run_sapo")
        assert isinstance(script, str)


# ===========================================================================
# Endpoint tests via TestClient
# ===========================================================================

class TestListAvailableModels:
    def test_returns_all_5_models(self):
        user = _make_user()
        db = MagicMock()
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert len(data["models"]) == 5

    def test_model_has_expected_fields(self):
        user = _make_user()
        db = MagicMock()
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/models")
        model = resp.json()["models"][0]
        assert "name" in model
        assert "recommended_batch_size" in model


class TestListAvailableTechniques:
    def test_admin_sees_all_available(self):
        user = _make_user(role="admin")
        db = MagicMock()
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/techniques")
        assert resp.status_code == 200
        data = resp.json()
        # admin role — all techniques available
        assert all(t["available"] for t in data["techniques"])

    def test_free_user_sees_unavailable_techniques(self):
        user = _make_user(role="user")
        db = MagicMock()
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/techniques")
        assert resp.status_code == 200
        data = resp.json()
        assert all(not t["available"] for t in data["techniques"])
        assert data["message"] is not None

    def test_premium_user_sees_techniques_available(self):
        user = _make_user(role="premium")
        db = MagicMock()
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/techniques")
        data = resp.json()
        assert all(t["available"] for t in data["techniques"])

    def test_response_includes_user_tier(self):
        user = _make_user(role="user")
        db = MagicMock()
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/techniques")
        assert resp.json()["user_tier"] == "user"


class TestListTiers:
    def test_returns_three_tiers(self):
        user = _make_user()
        db = MagicMock()
        _ut_mod.get_tier_limits.reset_mock()
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/tiers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tiers"]) == 3

    def test_tiers_have_expected_fields(self):
        user = _make_user()
        db = MagicMock()
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/tiers")
        tier = resp.json()["tiers"][0]
        assert "tier" in tier
        assert "pricing" in tier
        assert "limits" in tier
        assert "features" in tier


class TestGetQuotaStatus:
    def test_invalid_period_returns_400(self):
        user = _make_user()
        db = MagicMock()
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/quota?period=week")
        assert resp.status_code == 400

    def test_quota_not_found_returns_404(self):
        user = _make_user()
        db = _make_db(quota=None)
        db.query.return_value.filter.return_value.first.return_value = None
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/quota?period=day")
        assert resp.status_code == 404

    def test_valid_day_period_returns_200(self):
        user = _make_user()
        quota = _make_quota()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = quota
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/quota?period=day")
        assert resp.status_code == 200
        data = resp.json()
        assert "gpu" in data
        assert "cpu" in data

    def test_valid_month_period_returns_200(self):
        user = _make_user()
        quota = _make_quota()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = quota
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/quota?period=month")
        assert resp.status_code == 200


class TestGetQueueOverview:
    def test_admin_gets_full_overview(self):
        user = _make_user(role="admin")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/queue")
        assert resp.status_code == 200

    def test_user_gets_filtered_overview(self):
        user = _make_user(role="user")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert "user_filter" in data


class TestGetJobQueueStatus:
    def test_job_not_found_returns_404(self):
        user = _make_user()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/queue/nonexistent-job")
        assert resp.status_code == 404

    def test_access_denied_for_other_users_job(self):
        user = _make_user(role="user")
        other_uid = uuid.UUID("00000000-0000-0000-0000-000000000099")
        job = _make_job("job-xyz", user_id=other_uid)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/queue/job-xyz")
        assert resp.status_code == 403

    def test_owner_can_get_queue_status(self):
        user = _make_user(role="user")
        job = _make_job("job-own", user_id=user.user_id)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app)
        resp = client.get("/training/queue/job-own")
        assert resp.status_code == 200


class TestGetTrainingJobStatus:
    def test_job_not_found_returns_404(self):
        user = _make_user()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        app = _make_client(user, db)
        client = TestClient(app)
        with patch.object(_tr, "job_client") as mock_jc:
            resp = client.get("/training/jobs/no-job")
        assert resp.status_code == 404

    def test_access_denied_for_other_user(self):
        user = _make_user(role="user")
        other_uid = uuid.UUID("00000000-0000-0000-0000-000000000099")
        job = _make_job("job-abc", user_id=other_uid)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app)
        with patch.object(_tr, "job_client"):
            resp = client.get("/training/jobs/job-abc")
        assert resp.status_code == 403

    def test_admin_can_see_any_job(self):
        user = _make_user(role="admin")
        job = _make_job("job-x")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app)
        with patch.object(_tr, "job_client") as mock_jc:
            mock_jc.get_job_status.return_value = "RUNNING"
            mock_jc.get_job_info.return_value = MagicMock()
            resp = client.get("/training/jobs/job-x")
        assert resp.status_code == 200

    def test_owner_can_see_own_job(self):
        user = _make_user(role="user")
        job = _make_job("job-mine", user_id=user.user_id)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app)
        with patch.object(_tr, "job_client") as mock_jc:
            mock_jc.get_job_status.return_value = "RUNNING"
            mock_jc.get_job_info.return_value = None
            resp = client.get("/training/jobs/job-mine")
        assert resp.status_code == 200

    def test_ray_failure_still_returns_status(self):
        user = _make_user(role="admin")
        job = _make_job("job-err")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app)
        with patch.object(_tr, "job_client") as mock_jc:
            mock_jc.get_job_status.side_effect = Exception("Ray down")
            resp = client.get("/training/jobs/job-err")
        assert resp.status_code == 200


class TestGetTrainingJobLogs:
    def test_job_not_found_returns_404(self):
        user = _make_user()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        app = _make_client(user, db)
        client = TestClient(app)
        with patch.object(_tr, "job_client"):
            resp = client.get("/training/jobs/no-job/logs")
        assert resp.status_code == 404

    def test_access_denied_for_other_user(self):
        user = _make_user(role="user")
        other_uid = uuid.UUID("00000000-0000-0000-0000-000000000099")
        job = _make_job("job-other", user_id=other_uid)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app)
        with patch.object(_tr, "job_client"):
            resp = client.get("/training/jobs/job-other/logs")
        assert resp.status_code == 403

    def test_returns_logs_for_owner(self):
        user = _make_user(role="user")
        job = _make_job("job-mine", user_id=user.user_id)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app)
        with patch.object(_tr, "job_client") as mock_jc:
            mock_jc.get_job_logs.return_value = "line1\nline2\nline3"
            resp = client.get("/training/jobs/job-mine/logs?tail=2")
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data

    def test_ray_log_error_returns_500(self):
        user = _make_user(role="admin")
        job = _make_job("job-fail")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app, raise_server_exceptions=False)
        with patch.object(_tr, "job_client") as mock_jc:
            mock_jc.get_job_logs.side_effect = Exception("Log service down")
            resp = client.get("/training/jobs/job-fail/logs")
        assert resp.status_code == 500


class TestCancelTrainingJob:
    def test_job_not_found_returns_404(self):
        user = _make_user()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        app = _make_client(user, db)
        client = TestClient(app)
        with patch.object(_tr, "job_client"):
            resp = client.delete("/training/jobs/no-job")
        assert resp.status_code == 404

    def test_access_denied_for_other_user(self):
        user = _make_user(role="user")
        other_uid = uuid.UUID("00000000-0000-0000-0000-000000000099")
        job = _make_job("job-other", user_id=other_uid)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app)
        with patch.object(_tr, "job_client"):
            resp = client.delete("/training/jobs/job-other")
        assert resp.status_code == 403

    def test_cancel_success(self):
        user = _make_user(role="admin")
        job = _make_job("job-ok")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app)
        with patch.object(_tr, "job_client") as mock_jc:
            mock_jc.stop_job.return_value = True
            resp = client.delete("/training/jobs/job-ok")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "CANCELLED"

    def test_cancel_failure_returns_500(self):
        user = _make_user(role="admin")
        job = _make_job("job-nope")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app, raise_server_exceptions=False)
        with patch.object(_tr, "job_client") as mock_jc:
            mock_jc.stop_job.return_value = False
            resp = client.delete("/training/jobs/job-nope")
        assert resp.status_code == 500

    def test_ray_exception_returns_500(self):
        user = _make_user(role="admin")
        job = _make_job("job-ex")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = job
        app = _make_client(user, db)
        client = TestClient(app, raise_server_exceptions=False)
        with patch.object(_tr, "job_client") as mock_jc:
            mock_jc.stop_job.side_effect = Exception("Ray error")
            resp = client.delete("/training/jobs/job-ex")
        assert resp.status_code == 500
