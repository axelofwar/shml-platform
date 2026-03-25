from __future__ import annotations

import base64
import sys
import types
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import APIRouter, HTTPException
from starlette.requests import Request


def _router_module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.router = APIRouter()
    return mod


_original_modules: dict[str, object | None] = {}


def _install_module(name: str, module: object) -> None:
    _original_modules[name] = sys.modules.get(name)
    sys.modules[name] = module


_auth_mod = types.ModuleType("ray_compute.api.auth")
_auth_mod.get_current_user = AsyncMock()
_auth_mod.log_audit_event = AsyncMock()
_auth_mod.can_submit_jobs = lambda role: role in {"admin", "premium", "user"}
_auth_mod.PUBLIC_AUTH_URL = "https://auth.local"
_auth_mod.ADMIN_CONTACT = "platform-admin"

_db_mod = types.ModuleType("ray_compute.api.database")


def _unused_get_db():
    yield MagicMock()


_db_mod.get_db = _unused_get_db
_db_mod.SessionLocal = MagicMock(return_value=MagicMock())

_mlflow_mod = types.ModuleType("ray_compute.api.mlflow_integration")
_mlflow_mod.create_mlflow_run_for_job = AsyncMock(return_value=("exp-1", "run-1"))
_mlflow_mod.update_mlflow_run_for_job = AsyncMock()
_mlflow_mod.is_mlflow_server_available = MagicMock(return_value=True)

for _name, _module in {
    "ray_compute.api.auth": _auth_mod,
    "ray_compute.api.database": _db_mod,
    "ray_compute.api.job_management": _router_module("ray_compute.api.job_management"),
    "ray_compute.api.cluster": _router_module("ray_compute.api.cluster"),
    "ray_compute.api.logs": _router_module("ray_compute.api.logs"),
    "ray_compute.api.api_keys": _router_module("ray_compute.api.api_keys"),
    "ray_compute.api.training": _router_module("ray_compute.api.training"),
    "ray_compute.api.mlflow_integration": _mlflow_mod,
}.items():
    _install_module(_name, _module)

import ray_compute.api.server_v2 as server_v2

for _name, _previous in _original_modules.items():
    if _previous is None:
        if sys.modules.get(_name) is not None and sys.modules[_name] in {
            _auth_mod,
            _db_mod,
            _mlflow_mod,
        }:
            del sys.modules[_name]
        elif _name in sys.modules and getattr(sys.modules[_name], "router", None) is not None:
            del sys.modules[_name]
    else:
        sys.modules[_name] = _previous


def _request(path: str = "/") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )


def _user(role: str = "admin", user_id: uuid.UUID | None = None):
    return types.SimpleNamespace(
        user_id=user_id or uuid.uuid4(),
        username=f"{role}-user",
        email=f"{role}@example.com",
        role=role,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        last_login=None,
        is_active=True,
    )


def _db_for_model(first_map: dict[object, object] | None = None) -> MagicMock:
    db = MagicMock()
    first_map = first_map or {}

    def query(model):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.offset.return_value = q
        q.limit.return_value = q
        q.first.return_value = first_map.get(model)
        return q

    db.query.side_effect = query
    return db


def _job_request(**overrides) -> server_v2.JobSubmitRequest:
    data = {
        "name": "demo-job",
        "job_type": "training",
        "code": "print('hi')",
        "cpu": 2,
        "memory_gb": 8,
        "gpu": 0.0,
    }
    data.update(overrides)
    return server_v2.JobSubmitRequest(**data)


class _SortableCol:
    def desc(self):
        return MagicMock()


@pytest.fixture(autouse=True)
def reset_server_state(monkeypatch):
    server_v2.log_audit_event = AsyncMock()
    server_v2.can_submit_jobs = MagicMock(side_effect=lambda role: role != "viewer")
    server_v2.create_mlflow_run_for_job = AsyncMock(return_value=("exp-1", "run-1"))
    server_v2.update_mlflow_run_for_job = AsyncMock()
    server_v2.is_mlflow_server_available = MagicMock(return_value=True)
    server_v2.job_client = MagicMock()
    server_v2.SessionLocal = MagicMock(return_value=MagicMock())
    server_v2.Job.created_at = _SortableCol()
    monkeypatch.delenv("DEBUG", raising=False)


class TestBasicEndpoints:
    @pytest.mark.asyncio
    async def test_root(self):
        result = await server_v2.root()

        assert result["name"] == "Ray Compute API"
        assert result["health"] == "/health"

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        db = MagicMock()
        db.bind.dialect.raw_execute.return_value = "SELECT 1"
        db.execute.return_value = 1

        result = await server_v2.health_check(db)

        assert result["status"] == "ok"
        assert result["database"] == "healthy"
        assert result["mlflow"] == "healthy"
        assert result["ray"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_fallback_and_degraded(self):
        db = MagicMock()
        del db.bind
        db.execute.side_effect = RuntimeError("db down")
        server_v2.is_mlflow_server_available = MagicMock(return_value=False)
        server_v2.job_client = None

        result = await server_v2.health_check(db)

        assert result["status"] == "degraded"
        assert result["database"].startswith("unhealthy:")
        assert result["mlflow"] == "unavailable"
        assert result["ray"] == "unavailable"

    @pytest.mark.asyncio
    async def test_get_current_user_profile_returns_user(self):
        user = _user("premium")

        result = await server_v2.get_current_user_profile(user)

        assert result is user


class TestQuotaAndGpuEndpoints:
    @pytest.mark.asyncio
    async def test_get_user_quota_returns_custom_quota(self):
        user = _user("admin")
        quota = types.SimpleNamespace(
            max_concurrent_jobs=12,
            max_gpu_hours_per_day=99,
            max_cpu_hours_per_day=150,
            max_storage_gb=800,
            max_job_timeout_hours=72,
            max_gpu_fraction=0.75,
            priority_weight=7,
            can_use_custom_docker=True,
            can_skip_validation=False,
            allow_no_timeout=True,
            allow_exclusive_gpu=True,
        )
        db = _db_for_model({server_v2.UserQuota: quota})

        result = await server_v2.get_user_quota(user, db)

        assert result.max_concurrent_jobs == 12
        assert result.max_job_timeout_hours is None
        assert result.max_gpu_fraction == 0.75

    @pytest.mark.asyncio
    async def test_get_user_quota_returns_role_defaults(self):
        user = _user("user")
        db = _db_for_model({server_v2.UserQuota: None})

        result = await server_v2.get_user_quota(user, db)

        assert result.max_concurrent_jobs == 3
        assert result.allow_no_timeout is False

    @pytest.mark.asyncio
    async def test_get_cluster_gpus_parses_nvidia_smi(self, monkeypatch):
        fake_result = types.SimpleNamespace(
            returncode=0,
            stdout="0, RTX 3090, 24576, 1024, 10\n1, RTX 2070, 8192, 4096, 95\n",
        )
        fake_subprocess = types.SimpleNamespace(run=MagicMock(return_value=fake_result))
        monkeypatch.setitem(sys.modules, "subprocess", fake_subprocess)

        result = await server_v2.get_cluster_gpus(_user("viewer"))

        assert result.total_gpus == 2
        assert result.available_gpus == 1
        assert result.gpus[0].name == "RTX 3090"
        assert result.gpus[1].available is False

    @pytest.mark.asyncio
    async def test_get_cluster_gpus_uses_fallback_on_failure(self, monkeypatch):
        monkeypatch.setattr(server_v2, "logger", MagicMock())

        class _BrokenSubprocess:
            @staticmethod
            def run(*args, **kwargs):
                raise RuntimeError("no nvidia-smi")

        monkeypatch.setitem(sys.modules, "subprocess", _BrokenSubprocess)

        result = await server_v2.get_cluster_gpus(_user("user"))

        assert result.total_gpus == 3
        assert all(gpu.available for gpu in result.gpus)


class TestSubmitJob:
    @pytest.mark.asyncio
    async def test_submit_job_rejects_viewer(self):
        server_v2.can_submit_jobs.return_value = False
        db = _db_for_model({server_v2.UserQuota: None})

        with pytest.raises(HTTPException) as exc:
            await server_v2.submit_job(
                _job_request(),
                _request("/api/v1/jobs"),
                _user("viewer"),
                db,
            )

        assert exc.value.status_code == 403
        server_v2.log_audit_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_job_rejects_unlimited_timeout_without_permission(self):
        user = _user("user")
        db = _db_for_model({server_v2.UserQuota: None})

        with pytest.raises(HTTPException) as exc:
            await server_v2.submit_job(
                _job_request(no_timeout=True),
                _request("/api/v1/jobs"),
                user,
                db,
            )

        assert exc.value.status_code == 403
        assert "does not allow unlimited timeout" in exc.value.detail

    @pytest.mark.asyncio
    async def test_submit_job_rejects_gpu_over_limit(self):
        user = _user("user")
        db = _db_for_model({server_v2.UserQuota: None})

        with pytest.raises(HTTPException) as exc:
            await server_v2.submit_job(
                _job_request(gpu=0.5),
                _request("/api/v1/jobs"),
                user,
                db,
            )

        assert exc.value.status_code == 403
        assert "exceeds your limit" in exc.value.detail

    @pytest.mark.asyncio
    async def test_submit_job_rejects_timeout_over_limit(self):
        user = _user("user")
        db = _db_for_model({server_v2.UserQuota: None})

        with pytest.raises(HTTPException) as exc:
            await server_v2.submit_job(
                _job_request(timeout_hours=80),
                _request("/api/v1/jobs"),
                user,
                db,
            )

        assert exc.value.status_code == 403
        assert "exceeds your limit" in exc.value.detail

    @pytest.mark.asyncio
    async def test_submit_job_requires_ray_cluster(self):
        server_v2.job_client = None
        db = _db_for_model({server_v2.UserQuota: None})

        with pytest.raises(HTTPException) as exc:
            await server_v2.submit_job(
                _job_request(),
                _request("/api/v1/jobs"),
                _user("admin"),
                db,
            )

        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_submit_job_requires_code_or_script_or_entrypoint(self):
        db = _db_for_model({server_v2.UserQuota: None})

        with pytest.raises(HTTPException) as exc:
            await server_v2.submit_job(
                _job_request(code=None),
                _request("/api/v1/jobs"),
                _user("admin"),
                db,
            )

        assert exc.value.status_code == 400
        assert "Must provide either" in exc.value.detail

    @pytest.mark.asyncio
    async def test_submit_job_rejects_invalid_script_content(self):
        db = _db_for_model({server_v2.UserQuota: None})

        with pytest.raises(HTTPException) as exc:
            await server_v2.submit_job(
                _job_request(code=None, script_content="not-base64", script_name="train.py"),
                _request("/api/v1/jobs"),
                _user("admin"),
                db,
            )

        assert exc.value.status_code == 400
        assert "Failed to decode script content" in exc.value.detail

    @pytest.mark.asyncio
    async def test_submit_job_success_with_inline_code_and_mlflow(self):
        db = _db_for_model({server_v2.UserQuota: None})
        server_v2.job_client.submit_job.return_value = "ray-job-1"
        user = _user("admin")

        result = await server_v2.submit_job(
            _job_request(mlflow_experiment="demo-exp", tags=["nightly"]),
            _request("/api/v1/jobs"),
            user,
            db,
        )

        assert result.ray_job_id == "ray-job-1"
        assert result.user_id == user.user_id
        assert result.mlflow_run_id == "run-1"
        db.add.assert_called_once()
        db.commit.assert_called_once()
        server_v2.create_mlflow_run_for_job.assert_awaited_once()
        server_v2.log_audit_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_job_success_with_entrypoint_and_working_dir_files(
        self, monkeypatch, tmp_path
    ):
        db = _db_for_model({server_v2.UserQuota: None})
        server_v2.job_client.submit_job.return_value = "ray-job-2"
        fake_tempfile = types.SimpleNamespace(mkdtemp=lambda prefix: str(tmp_path))
        monkeypatch.setitem(sys.modules, "tempfile", fake_tempfile)
        script_content = base64.b64encode(b"print('train')").decode("utf-8")
        extra_file = base64.b64encode(b"hello").decode("utf-8")

        result = await server_v2.submit_job(
            _job_request(
                code=None,
                entrypoint="python train.py --epochs 2",
                script_content=script_content,
                script_name="train.py",
                working_dir_files={"configs/params.txt": extra_file},
            ),
            _request("/api/v1/jobs"),
            _user("admin"),
            db,
        )

        runtime_env = server_v2.job_client.submit_job.call_args.kwargs["runtime_env"]
        assert result.ray_job_id == "ray-job-2"
        assert runtime_env["working_dir"] == str(tmp_path)
        assert (tmp_path / "train.py").read_text() == "print('train')"
        assert (tmp_path / "configs" / "params.txt").read_text() == "hello"

    @pytest.mark.asyncio
    async def test_submit_job_ray_failure_returns_500(self):
        db = _db_for_model({server_v2.UserQuota: None})
        server_v2.job_client.submit_job.side_effect = RuntimeError("ray down")

        with pytest.raises(HTTPException) as exc:
            await server_v2.submit_job(
                _job_request(),
                _request("/api/v1/jobs"),
                _user("admin"),
                db,
            )

        assert exc.value.status_code == 500
        server_v2.log_audit_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_job_mlflow_failure_does_not_fail_submission(self):
        db = _db_for_model({server_v2.UserQuota: None})
        server_v2.job_client.submit_job.return_value = "ray-job-3"
        server_v2.create_mlflow_run_for_job.side_effect = RuntimeError("mlflow down")

        result = await server_v2.submit_job(
            _job_request(mlflow_experiment="demo-exp"),
            _request("/api/v1/jobs"),
            _user("admin"),
            db,
        )

        assert result.mlflow_run_id is None


class TestJobEndpoints:
    @pytest.mark.asyncio
    async def test_list_jobs_filters_current_user(self):
        user = _user("user")
        query = MagicMock()
        query.filter.return_value = query
        query.order_by.return_value = query
        query.offset.return_value = query
        query.limit.return_value = query
        query.count.return_value = 2
        query.all.return_value = [types.SimpleNamespace(job_id="job-1")]
        db = MagicMock()
        db.query.return_value = query

        result = await server_v2.list_jobs(2, 10, "RUNNING", False, user, db)

        assert result == {
            "jobs": [types.SimpleNamespace(job_id="job-1")],
            "total": 2,
            "page": 2,
            "page_size": 10,
        }
        assert query.filter.call_count == 2

    @pytest.mark.asyncio
    async def test_get_job_not_found(self):
        db = _db_for_model({server_v2.Job: None})

        with pytest.raises(HTTPException) as exc:
            await server_v2.get_job("missing", _user("admin"), db)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_job_checks_ownership(self):
        owner = uuid.uuid4()
        job = types.SimpleNamespace(job_id="job-1", user_id=owner)
        db = _db_for_model({server_v2.Job: job})

        with pytest.raises(HTTPException) as exc:
            await server_v2.get_job("job-1", _user("user", uuid.uuid4()), db)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_job_returns_owned_job(self):
        owner = uuid.uuid4()
        user = _user("user", owner)
        job = types.SimpleNamespace(job_id="job-1", user_id=owner)
        db = _db_for_model({server_v2.Job: job})

        result = await server_v2.get_job("job-1", user, db)

        assert result is job

    @pytest.mark.asyncio
    async def test_cancel_job_rejects_viewer(self):
        server_v2.can_submit_jobs.return_value = False
        db = _db_for_model({server_v2.Job: None})

        with pytest.raises(HTTPException) as exc:
            await server_v2.cancel_job(
                "job-1",
                None,
                _request("/api/v1/jobs/job-1"),
                _user("viewer"),
                db,
            )

        assert exc.value.status_code == 403
        server_v2.log_audit_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_job_not_found(self):
        db = _db_for_model({server_v2.Job: None})

        with pytest.raises(HTTPException) as exc:
            await server_v2.cancel_job(
                "job-1",
                None,
                _request("/api/v1/jobs/job-1"),
                _user("admin"),
                db,
            )

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_job_rejects_wrong_owner(self):
        job = types.SimpleNamespace(job_id="job-1", user_id=uuid.uuid4(), status="RUNNING")
        db = _db_for_model({server_v2.Job: job})

        with pytest.raises(HTTPException) as exc:
            await server_v2.cancel_job(
                "job-1",
                None,
                _request("/api/v1/jobs/job-1"),
                _user("user"),
                db,
            )

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_cancel_job_rejects_terminal_status(self):
        owner = uuid.uuid4()
        job = types.SimpleNamespace(job_id="job-1", user_id=owner, status="SUCCEEDED")
        db = _db_for_model({server_v2.Job: job})

        with pytest.raises(HTTPException) as exc:
            await server_v2.cancel_job(
                "job-1",
                None,
                _request("/api/v1/jobs/job-1"),
                _user("user", owner),
                db,
            )

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_cancel_job_success(self):
        owner = uuid.uuid4()
        user = _user("user", owner)
        job = types.SimpleNamespace(job_id="job-1", user_id=owner, status="RUNNING")
        db = _db_for_model({server_v2.Job: job})

        result = await server_v2.cancel_job(
            "job-1",
            "because",
            _request("/api/v1/jobs/job-1"),
            user,
            db,
        )

        assert result == {"status": "cancelled", "job_id": "job-1"}
        assert job.status == "CANCELLED"
        assert job.cancelled_by == owner
        db.commit.assert_called_once()
        server_v2.log_audit_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_job_alias_delegates(self):
        server_v2.cancel_job = AsyncMock(return_value={"status": "cancelled", "job_id": "job-1"})

        result = await server_v2.stop_job_alias(
            "job-1",
            "reason",
            _request("/api/v1/jobs/job-1/cancel"),
            _user("admin"),
            MagicMock(),
        )

        assert result == {"status": "cancelled", "job_id": "job-1"}
        server_v2.cancel_job.assert_awaited_once()


class TestExceptionHandlers:
    @pytest.mark.asyncio
    async def test_http_exception_handler_adds_auth_guidance(self):
        response = await server_v2.http_exception_handler(
            _request("/api/v1/private"),
            HTTPException(status_code=401, detail="missing token"),
        )

        assert response.status_code == 401
        assert b"authentication" in response.body
        assert b"https://auth.local" in response.body

    @pytest.mark.asyncio
    async def test_http_exception_handler_adds_viewer_upgrade_guidance(self):
        response = await server_v2.http_exception_handler(
            _request("/api/v1/jobs"),
            HTTPException(status_code=403, detail="viewer cannot submit"),
        )

        assert response.status_code == 403
        assert b"authorization" in response.body
        assert b"viewer (read-only)" in response.body

    @pytest.mark.asyncio
    async def test_general_exception_handler_hides_detail_by_default(self):
        response = await server_v2.general_exception_handler(
            _request("/boom"),
            RuntimeError("secret detail"),
        )

        assert response.status_code == 500
        assert b"An unexpected error occurred" in response.body
        assert b"secret detail" not in response.body

    @pytest.mark.asyncio
    async def test_general_exception_handler_shows_detail_in_debug(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "true")

        response = await server_v2.general_exception_handler(
            _request("/boom"),
            RuntimeError("secret detail"),
        )

        assert response.status_code == 500
        assert b"secret detail" in response.body
