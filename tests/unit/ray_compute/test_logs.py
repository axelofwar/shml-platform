"""Unit tests for ray_compute/api/logs.py.

Tests:
- get_job_log_path() helper (filesystem search)
- check_job_access() ownership helper
- GET /{job_id} — get_job_logs endpoint
- GET /{job_id}/files — list_job_log_files endpoint
"""
from __future__ import annotations

import os
import sys
import uuid
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path setup (conftest already ran — stubs are in sys.modules)
# ---------------------------------------------------------------------------
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
_RC_ROOT = os.path.join(_ROOT, "ray_compute")
for _p in [_ROOT, _RC_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Ensure ray_compute.api.database is stubbed (logs.py imports it via auth)
if "ray_compute.api.database" not in sys.modules:
    import types as _types
    _db_mod = _types.ModuleType("ray_compute.api.database")
    _db_mod.get_db = lambda: iter([MagicMock()])
    _db_mod.SessionLocal = MagicMock()
    _db_mod.engine = MagicMock()
    sys.modules["ray_compute.api.database"] = _db_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Import get_db from the actual database module (used as dependency key by logs.py)
from ray_compute.api.database import get_db as _database_get_db  # noqa: E402
# Import get_current_user from auth stub (also used as dependency key by logs.py)
from ray_compute.api.auth import get_current_user as _auth_get_current_user  # noqa: E402


def _make_app_for_logs(user, db):
    """Create a minimal FastAPI app with logs router + auth/db overrides."""
    from ray_compute.api.logs import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_auth_get_current_user] = lambda: user
    app.dependency_overrides[_database_get_db] = lambda: db
    return app

def _make_test_user(role: str = "user") -> MagicMock:
    user = MagicMock()
    user.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    user.username = "tester"
    user.email = "tester@test.local"
    user.role = role
    user.is_active = True
    user.is_suspended = False
    return user


def _make_job(job_id: str, user_id=None, ray_job_id: str = None) -> MagicMock:
    job = MagicMock()
    job.job_id = job_id
    job.ray_job_id = ray_job_id or job_id
    job.user_id = user_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    return job


def _make_db(job: MagicMock | None = None):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = job
    return db


# ===========================================================================
# get_job_log_path TESTS
# ===========================================================================


class TestGetJobLogPath:
    def test_exact_path_exists(self, tmp_path):
        from ray_compute.api.logs import get_job_log_path

        log_file = tmp_path / "job-driver-myjob123.log"
        log_file.write_text("log line 1\n")

        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)):
            result = get_job_log_path("myjob123")

        assert result == log_file

    def test_raysubmit_path_found(self, tmp_path):
        from ray_compute.api.logs import get_job_log_path

        log_file = tmp_path / "job-driver-raysubmit_abc123.log"
        log_file.write_text("log data\n")

        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)):
            result = get_job_log_path("abc123")

        assert result == log_file

    def test_glob_match_fallback(self, tmp_path):
        from ray_compute.api.logs import get_job_log_path

        log_file = tmp_path / "job-driver-extra_xyz789_suffix.log"
        log_file.write_text("data\n")

        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)):
            result = get_job_log_path("xyz789")

        assert result is not None
        assert "xyz789" in result.name

    def test_returns_none_when_no_match(self, tmp_path):
        from ray_compute.api.logs import get_job_log_path

        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)):
            result = get_job_log_path("nonexistent-job-id")

        assert result is None


# ===========================================================================
# check_job_access TESTS
# ===========================================================================


class TestCheckJobAccess:
    def test_admin_can_access_any_job(self):
        from ray_compute.api.logs import check_job_access

        admin = _make_test_user("admin")
        other_uid = uuid.UUID("00000000-0000-0000-0000-000000000002")
        job = _make_job("job-1", user_id=other_uid)
        db = _make_db(job)

        result = check_job_access("job-1", admin, db)
        assert result is job

    def test_owner_can_access_own_job(self):
        from ray_compute.api.logs import check_job_access

        user = _make_test_user("user")
        job = _make_job("job-2", user_id=user.user_id)
        db = _make_db(job)

        result = check_job_access("job-2", user, db)
        assert result is job

    def test_non_owner_raises_403(self):
        from ray_compute.api.logs import check_job_access
        import fastapi

        user = _make_test_user("user")
        other_uid = uuid.UUID("00000000-0000-0000-0000-000000000099")
        job = _make_job("job-3", user_id=other_uid)
        db = _make_db(job)

        with pytest.raises(fastapi.HTTPException) as exc_info:
            check_job_access("job-3", user, db)
        assert exc_info.value.status_code == 403

    def test_job_not_found_raises_404(self):
        from ray_compute.api.logs import check_job_access
        import fastapi

        user = _make_test_user()
        db = _make_db(None)  # no job

        with pytest.raises(fastapi.HTTPException) as exc_info:
            check_job_access("missing-job", user, db)
        assert exc_info.value.status_code == 404


# ===========================================================================
# FastAPI endpoint tests
# ===========================================================================


@pytest.fixture
def client_and_user():
    """Build a TestClient for logs.py endpoints with auth overridden."""
    from ray_compute.api.logs import router
    from ray_compute.api.auth import get_current_user, get_db

    user = _make_test_user("admin")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: iter([_make_db()])
    return TestClient(app, raise_server_exceptions=False), user



class TestGetJobLogsEndpoint:
    def test_job_not_found_returns_404(self):
        user = _make_test_user("admin")
        db = _make_db(None)
        client = TestClient(_make_app_for_logs(user, db), raise_server_exceptions=False)
        resp = client.get("/logs/job-xyz")
        assert resp.status_code == 404

    def test_logs_returned_from_file(self, tmp_path):
        user = _make_test_user("admin")
        job = _make_job("job-file-1", user_id=user.user_id, ray_job_id="raysubmit_file1")
        db = _make_db(job)
        log_file = tmp_path / "job-driver-raysubmit_file1.log"
        log_file.write_text("line1\nline2\nline3\n")
        client = TestClient(_make_app_for_logs(user, db), raise_server_exceptions=False)
        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)):
            resp = client.get("/logs/job-file-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "file"
        assert "line1" in data["lines"]
        assert data["total_lines"] == 3

    def test_logs_no_file_returns_empty(self, tmp_path):
        user = _make_test_user("admin")
        job = _make_job("job-nofile", user_id=user.user_id, ray_job_id="raysubmit_nofile")
        db = _make_db(job)
        client = TestClient(_make_app_for_logs(user, db), raise_server_exceptions=False)
        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)):
            with patch("ray_compute.api.logs.get_job_log_path", return_value=None):
                # Make Ray API also fail so we fall through to "none" source
                with patch("ray.job_submission.JobSubmissionClient",
                           side_effect=Exception("Ray not available")):
                    resp = client.get("/logs/job-nofile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "none"
        assert data["lines"] == []

    def test_logs_tail_parameter(self, tmp_path):
        user = _make_test_user("admin")
        job = _make_job("job-tail", user_id=user.user_id, ray_job_id="raysubmit_tail")
        db = _make_db(job)
        log_file = tmp_path / "job-driver-raysubmit_tail.log"
        log_file.write_text("\n".join(f"line{i}" for i in range(20)) + "\n")
        client = TestClient(_make_app_for_logs(user, db), raise_server_exceptions=False)
        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)):
            resp = client.get("/logs/job-tail?tail=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["lines"]) == 5
        assert data["truncated"] is True

    def test_logs_non_owner_gets_403(self):
        user = _make_test_user("user")
        other_uid = uuid.UUID("00000000-0000-0000-0000-000000000099")
        job = _make_job("job-403", user_id=other_uid)
        db = _make_db(job)
        client = TestClient(_make_app_for_logs(user, db), raise_server_exceptions=False)
        resp = client.get("/logs/job-403")
        assert resp.status_code == 403


class TestListJobLogFilesEndpoint:
    def test_lists_files_from_directory(self, tmp_path):
        user = _make_test_user("admin")
        job = _make_job("job-files", user_id=user.user_id, ray_job_id="raysubmit_filelist")
        db = _make_db(job)
        (tmp_path / "job-driver-raysubmit_filelist.log").write_text("log content")
        (tmp_path / "worker-raysubmit_filelist.log").write_text("worker log")
        client = TestClient(_make_app_for_logs(user, db), raise_server_exceptions=False)
        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)):
            resp = client.get("/logs/job-files/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job-files"
        assert data["total"] == len(data["files"])

    def test_returns_empty_when_no_files(self, tmp_path):
        user = _make_test_user("admin")
        job = _make_job("job-nofiles", user_id=user.user_id, ray_job_id="raysubmit_nofiles")
        db = _make_db(job)
        client = TestClient(_make_app_for_logs(user, db), raise_server_exceptions=False)
        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)):
            resp = client.get("/logs/job-nofiles/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["files"] == []
