"""Unit tests for ray_compute/api/job_management.py.

Tests:
- check_job_ownership() helper (DB query + ownership check)
- POST /jobs/{job_id}/restart — restart_job
- POST /jobs/{job_id}/start — start_job
- DELETE /jobs/{job_id} — delete_job_with_cleanup
- GET /jobs/{job_id}/download — download_job
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, call

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path setup — conftest already added ray_compute stubs to sys.modules
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_RC_ROOT = _ROOT / "ray_compute"
for _p in [str(_ROOT), str(_RC_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Ensure ray_compute.api.database is stubbed (job_management imports it)
if "ray_compute.api.database" not in sys.modules:
    import types as _types
    _db_mod = _types.ModuleType("ray_compute.api.database")
    _db_mod.get_db = lambda: iter([MagicMock()])
    _db_mod.SessionLocal = MagicMock()
    _db_mod.engine = MagicMock()
    sys.modules["ray_compute.api.database"] = _db_mod

# Import dependency callables from the same module objects job_management uses
from ray_compute.api.database import get_db as _database_get_db  # noqa: E402
from ray_compute.api.auth import get_current_user as _auth_get_current_user  # noqa: E402

# Import the job_management module (triggers module-level JobSubmissionClient creation)
import ray_compute.api.job_management as _jm  # noqa: E402

# Grab the mock JobStatus from the module namespace (it's from the mocked ray.job_submission)
_JobStatus = _jm.JobStatus


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_user(role: str = "user") -> MagicMock:
    user = MagicMock()
    user.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    user.username = "tester"
    user.email = "tester@test.local"
    user.role = role
    user.is_active = True
    user.is_suspended = False
    return user


def _make_job(job_id: str, user_id=None, metadata=None) -> MagicMock:
    job = MagicMock()
    job.job_id = job_id
    job.ray_job_id = job_id
    job.user_id = user_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    job.name = f"test-job-{job_id}"
    job.status = "RUNNING"
    job.metadata = metadata or {}
    return job


def _make_db(job: MagicMock | None = None) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = job
    return db


def _make_client(user: MagicMock, db: MagicMock, mock_job_client: MagicMock = None) -> TestClient:
    """Build a test FastAPI app with the job_management router."""
    if mock_job_client is None:
        mock_job_client = MagicMock()
    from ray_compute.api.job_management import router
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.dependency_overrides[_auth_get_current_user] = lambda: user
    test_app.dependency_overrides[_database_get_db] = lambda: db
    with patch.object(_jm, "job_client", mock_job_client):
        yield TestClient(test_app, raise_server_exceptions=False)


# ===========================================================================
# check_job_ownership tests
# ===========================================================================

class TestCheckJobOwnership:
    def test_job_not_found_raises_404(self):
        from ray_compute.api.job_management import check_job_ownership
        db = _make_db(job=None)
        user = _make_user(role="user")
        with pytest.raises(Exception) as exc_info:
            check_job_ownership("job-xyz", user, db)
        assert "404" in str(exc_info.value.status_code) or exc_info.value.status_code == 404

    def test_admin_can_access_any_job(self):
        from ray_compute.api.job_management import check_job_ownership
        other_uid = uuid.UUID("00000000-0000-0000-0000-000000000002")
        job = _make_job("job-abc", user_id=other_uid)
        db = _make_db(job=job)
        admin = _make_user(role="admin")
        result = check_job_ownership("job-abc", admin, db)
        assert result is job

    def test_owner_can_access_own_job(self):
        from ray_compute.api.job_management import check_job_ownership
        uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
        job = _make_job("job-abc", user_id=uid)
        db = _make_db(job=job)
        user = _make_user(role="user")
        user.user_id = uid
        result = check_job_ownership("job-abc", user, db)
        assert result is job

    def test_non_owner_raises_403(self):
        from ray_compute.api.job_management import check_job_ownership
        job = _make_job("job-abc", user_id=uuid.UUID("00000000-0000-0000-0000-000000000002"))
        db = _make_db(job=job)
        user = _make_user(role="user")
        user.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        with pytest.raises(Exception) as exc_info:
            check_job_ownership("job-abc", user, db)
        assert exc_info.value.status_code == 403


# ===========================================================================
# restart_job tests
# ===========================================================================

class TestRestartJob:
    def _make_client_for_restart(self, user, db, mock_jc):
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                yield c

    def test_restart_job_not_found_returns_404(self):
        user = _make_user()
        db = _make_db(job=None)
        mock_jc = MagicMock()
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.post("/jobs/job-missing/restart")
        assert resp.status_code == 404

    def test_restart_job_missing_metadata_returns_400(self):
        job = _make_job("job-1", metadata={})  # no submission_params
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.post("/jobs/job-1/restart")
        assert resp.status_code == 400
        assert "submission parameters" in resp.json()["detail"].lower()

    def test_restart_job_success(self):
        job = _make_job("job-1", metadata={
            "submission_params": {
                "entrypoint": "python train.py",
                "runtime_env": {"pip": ["torch"]},
                "metadata": {"experiment": "exp-1"},
            }
        })
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        mock_jc.submit_job.return_value = "new-job-2"
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.post("/jobs/job-1/restart")
        assert resp.status_code == 200
        data = resp.json()
        assert data["new_job_id"] == "new-job-2"
        assert data["status"] == "restarted"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_restart_job_ray_failure_returns_500(self):
        job = _make_job("job-1", metadata={
            "submission_params": {"entrypoint": "python train.py"}
        })
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        mock_jc.submit_job.side_effect = Exception("Ray unavailable")
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.post("/jobs/job-1/restart")
        assert resp.status_code == 500
        assert "Ray unavailable" in resp.json()["detail"]


# ===========================================================================
# start_job tests
# ===========================================================================

class TestStartJob:
    def _make_app(self, user, db, mock_jc):
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        return test_app, mock_jc

    def test_start_job_not_found(self):
        user = _make_user()
        db = _make_db(job=None)
        mock_jc = MagicMock()
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.post("/jobs/job-missing/start")
        assert resp.status_code == 404

    def test_start_job_wrong_status_returns_400(self):
        job = _make_job("job-1", metadata={})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        # Return a status that is NOT in [STOPPED, FAILED]
        mock_jc.get_job_status.return_value = _JobStatus.RUNNING
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.post("/jobs/job-1/start")
        assert resp.status_code == 400

    def test_start_stopped_job_calls_restart(self):
        job = _make_job("job-1", metadata={
            "submission_params": {"entrypoint": "python train.py"}
        })
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        # Status is STOPPED — job_management checks STOPPED/FAILED
        mock_jc.get_job_status.return_value = _JobStatus.STOPPED
        mock_jc.submit_job.return_value = "new-job-2"
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.post("/jobs/job-1/start")
        # Starts by calling restart, which either succeeds or 400s based on metadata
        # Since metadata has submission_params, it should succeed -> 200
        assert resp.status_code == 200


# ===========================================================================
# delete_job_with_cleanup tests
# ===========================================================================

class TestDeleteJobWithCleanup:
    def _make_test_client(self, user, db, mock_jc):
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        return test_app

    def test_delete_job_not_found(self):
        user = _make_user()
        db = _make_db(job=None)
        mock_jc = MagicMock()
        test_app = self._make_test_client(user, db, mock_jc)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.delete("/jobs/job-missing")
        assert resp.status_code == 404

    def test_delete_running_job_returns_400(self):
        job = _make_job("job-1")
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        mock_jc.get_job_status.return_value = _JobStatus.RUNNING
        test_app = self._make_test_client(user, db, mock_jc)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.delete("/jobs/job-1")
        assert resp.status_code == 400
        assert "stopped" in resp.json()["detail"].lower()

    def test_delete_succeeded_job_no_cleanup(self):
        job = _make_job("job-1", metadata={})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        mock_jc.get_job_status.return_value = _JobStatus.SUCCEEDED
        test_app = self._make_test_client(user, db, mock_jc)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.delete("/jobs/job-1?cleanup=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["cleanup"] == "skipped"
        mock_jc.delete_job.assert_called_once_with("job-1")
        db.delete.assert_called_once_with(job)
        db.commit.assert_called_once()

    def test_delete_with_cleanup_workspace(self, tmp_path):
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        (ws_dir / "model.pt").write_text("model data")

        job = _make_job("job-1", metadata={"workspace_dir": str(ws_dir)})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        mock_jc.get_job_status.return_value = _JobStatus.FAILED
        test_app = self._make_test_client(user, db, mock_jc)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.delete("/jobs/job-1?cleanup=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cleanup"]["workspace"] == "deleted"
        assert not ws_dir.exists()

    def test_delete_with_cleanup_checkpoints(self, tmp_path):
        ck_dir = tmp_path / "checkpoints"
        ck_dir.mkdir()
        (ck_dir / "epoch_10.ckpt").write_text("checkpoint")

        job = _make_job("job-1", metadata={"checkpoint_dir": str(ck_dir)})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        mock_jc.get_job_status.return_value = _JobStatus.SUCCEEDED
        test_app = self._make_test_client(user, db, mock_jc)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.delete("/jobs/job-1?cleanup=true")
        assert resp.status_code == 200
        assert resp.json()["cleanup"]["checkpoints"] == "deleted"
        assert not ck_dir.exists()

    def test_delete_ray_client_failure_returns_500(self):
        job = _make_job("job-1", metadata={})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        mock_jc.get_job_status.return_value = _JobStatus.SUCCEEDED
        mock_jc.delete_job.side_effect = Exception("Ray unavailable")
        test_app = self._make_test_client(user, db, mock_jc)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.delete("/jobs/job-1")
        assert resp.status_code == 500
        db.rollback.assert_called()


# ===========================================================================
# download_job tests
# ===========================================================================

class TestDownloadJob:
    def _make_test_client(self, user, db, mock_jc):
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        return test_app

    def test_download_not_found(self):
        user = _make_user()
        db = _make_db(job=None)
        mock_jc = MagicMock()
        test_app = self._make_test_client(user, db, mock_jc)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get("/jobs/job-missing/download")
        assert resp.status_code == 404

    def test_download_no_components_selected(self):
        job = _make_job("job-1")
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        test_app = self._make_test_client(user, db, mock_jc)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get(
                    "/jobs/job-1/download",
                    params={"workspace": False, "logs": False, "checkpoints": False, "mlflow": False},
                )
        assert resp.status_code == 400
        assert "At least one component" in resp.json()["detail"]

    def test_download_no_files_creates_readme(self):
        job = _make_job("job-1", metadata={})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        test_app = self._make_test_client(user, db, mock_jc)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get("/jobs/job-1/download?workspace=true&logs=false&checkpoints=false&mlflow=false")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/gzip"
        # Response should be a non-empty gzip archive
        assert len(resp.content) > 0

    def test_download_with_workspace_files(self, tmp_path):
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        (ws_dir / "output.json").write_text('{"result": 42}')

        job = _make_job("job-1", metadata={"workspace_dir": str(ws_dir)})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        test_app = self._make_test_client(user, db, mock_jc)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get("/jobs/job-1/download?workspace=true&logs=false&checkpoints=false&mlflow=false")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/gzip"
        # Verify it's a valid gzip with files
        import tarfile
        import io
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
            members = tar.getnames()
        assert any("workspace" in m for m in members)


# ===========================================================================
# start_job exception path (lines 144-145)
# ===========================================================================

class TestStartJobExceptionPath:
    def test_start_job_ray_exception_returns_500(self):
        """get_job_status raises non-HTTP exception → covers lines 144-145."""
        job = _make_job("job-err1", metadata={"submission_params": {}})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        mock_jc.get_job_status.side_effect = Exception("ray unavailable")
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.post("/jobs/job-err1/start")
        assert resp.status_code == 500
        assert "Failed to start job" in resp.json()["detail"]


# ===========================================================================
# delete_job false-branch + log-glob coverage
# (branches 183->188, 190->196; lines 200-203)
# ===========================================================================

class TestDeleteJobCleanupCoverage:
    def _make_app(self, user, db):
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        return test_app

    def test_delete_cleanup_workspace_not_on_disk(self):
        """workspace_dir in metadata but not on disk → covers branch 183->188 (exists=False)."""
        job = _make_job("job-ws-off", metadata={"workspace_dir": "/nonexistent/from/test"})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        mock_jc.get_job_status.return_value = _JobStatus.SUCCEEDED
        test_app = self._make_app(user, db)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.delete("/jobs/job-ws-off?cleanup=true")
        assert resp.status_code == 200
        assert resp.json()["cleanup"]["logs"] == "cleaned"

    def test_delete_cleanup_checkpoint_not_on_disk(self):
        """checkpoint_dir in metadata but not on disk → covers branch 190->196 (exists=False)."""
        job = _make_job("job-ck-off", metadata={"checkpoint_dir": "/nonexistent/ck/path"})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        mock_jc.get_job_status.return_value = _JobStatus.SUCCEEDED
        test_app = self._make_app(user, db)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.delete("/jobs/job-ck-off?cleanup=true")
        assert resp.status_code == 200
        assert resp.json()["cleanup"]["logs"] == "cleaned"

    def test_delete_cleanup_log_glob_hit_os_remove_error(self):
        """glob.glob returns path; os.remove raises (file gone) → covers lines 200-203."""
        job = _make_job("job-rm-err", metadata={})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        mock_jc.get_job_status.return_value = _JobStatus.SUCCEEDED
        test_app = self._make_app(user, db)
        with patch("glob.glob", return_value=["/tmp/fake_ray_log_job-rm-err.txt"]):
            with patch.object(_jm, "job_client", mock_jc):
                with TestClient(test_app, raise_server_exceptions=False) as c:
                    resp = c.delete("/jobs/job-rm-err?cleanup=true")
        assert resp.status_code == 200
        assert resp.json()["cleanup"]["logs"] == "cleaned"


# ===========================================================================
# download_job additional branches
# (260->265, 266-269, 273-290, 294-304, 341-349)
# ===========================================================================

class TestDownloadJobCoverage:
    def _make_app(self, user, db):
        from ray_compute.api.job_management import router
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.dependency_overrides[_auth_get_current_user] = lambda: user
        test_app.dependency_overrides[_database_get_db] = lambda: db
        return test_app

    def test_download_workspace_dir_not_on_disk(self):
        """workspace_dir in metadata but directory doesn't exist → covers branch 260->265."""
        job = _make_job("job-ws-disk", metadata={"workspace_dir": "/nonexistent/workspace/dir"})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        test_app = self._make_app(user, db)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get(
                    "/jobs/job-ws-disk/download",
                    params={"workspace": True, "logs": False, "checkpoints": False, "mlflow": False},
                )
        assert resp.status_code == 200  # README fallback

    def test_download_with_checkpoints(self, tmp_path):
        """checkpoints=True, checkpoint_dir exists → covers lines 266-269."""
        ck_dir = tmp_path / "checkpoints"
        ck_dir.mkdir()
        (ck_dir / "model.pt").write_text("weights")
        job = _make_job("job-ck-dl", metadata={"checkpoint_dir": str(ck_dir)})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        test_app = self._make_app(user, db)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get(
                    "/jobs/job-ck-dl/download",
                    params={"workspace": False, "logs": False, "checkpoints": True, "mlflow": False},
                )
        assert resp.status_code == 200
        import tarfile, io
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
            members = tar.getnames()
        assert any("checkpoint" in m for m in members)

    def test_download_with_logs_no_files(self):
        """logs=True but glob finds nothing → covers lines 273-282, 288 (empty log_dir branch)."""
        job = _make_job("job-log-empty", metadata={})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        test_app = self._make_app(user, db)
        with patch.object(_jm, "job_client", mock_jc):
            with TestClient(test_app, raise_server_exceptions=False) as c:
                resp = c.get(
                    "/jobs/job-log-empty/download",
                    params={"workspace": False, "logs": True, "checkpoints": False, "mlflow": False},
                )
        assert resp.status_code == 200  # README fallback (no log files found)

    def test_download_with_logs_glob_hit(self, tmp_path):
        """glob.glob returns real file → covers lines 283-290 (copy loop + tar add)."""
        log_file = tmp_path / "worker_job-log-hit_output.stdout"
        log_file.write_text("ray log line 1\nray log line 2")
        job = _make_job("job-log-hit", metadata={})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        test_app = self._make_app(user, db)
        with patch("glob.glob", return_value=[str(log_file)]):
            with patch.object(_jm, "job_client", mock_jc):
                with TestClient(test_app, raise_server_exceptions=False) as c:
                    resp = c.get(
                        "/jobs/job-log-hit/download",
                        params={"workspace": False, "logs": True, "checkpoints": False, "mlflow": False},
                    )
        assert resp.status_code == 200
        import tarfile, io
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
            members = tar.getnames()
        assert any("logs" in m for m in members)

    def test_download_with_mlflow_artifacts(self, tmp_path):
        """mlflow=True with existing run_dir → covers lines 294-304."""
        import os
        mlflow_run_id = "run-abc999"
        exp_id = "1"
        mlflow_root = tmp_path / "mlflow_root"
        run_dir = mlflow_root / exp_id / mlflow_run_id / "artifacts"
        run_dir.mkdir(parents=True)
        (run_dir / "model.pkl").write_text("weights")

        job = _make_job("job-mlf", metadata={})
        job.mlflow_run_id = mlflow_run_id
        job.mlflow_experiment_id = exp_id
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        test_app = self._make_app(user, db)
        with patch.dict(os.environ, {"MLFLOW_ARTIFACT_ROOT": str(mlflow_root)}):
            with patch.object(_jm, "job_client", mock_jc):
                with TestClient(test_app, raise_server_exceptions=False) as c:
                    resp = c.get(
                        "/jobs/job-mlf/download",
                        params={"workspace": False, "logs": False, "checkpoints": False, "mlflow": True},
                    )
        assert resp.status_code == 200
        import tarfile, io
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
            members = tar.getnames()
        assert any("mlflow" in m for m in members)

    def test_download_tarfile_error_returns_500(self):
        """tarfile.open raises → covers lines 341-344 (inner cleanup) and 348-349 (outer 500)."""
        job = _make_job("job-tar-err", metadata={"workspace_dir": "/some/path"})
        user = _make_user()
        db = _make_db(job=job)
        mock_jc = MagicMock()
        test_app = self._make_app(user, db)
        with patch("tarfile.open", side_effect=OSError("disk full")):
            with patch.object(_jm, "job_client", mock_jc):
                with TestClient(test_app, raise_server_exceptions=False) as c:
                    resp = c.get(
                        "/jobs/job-tar-err/download",
                        params={"workspace": True, "logs": False, "checkpoints": False, "mlflow": False},
                    )
        assert resp.status_code == 500
        assert "Failed to create download" in resp.json()["detail"]
