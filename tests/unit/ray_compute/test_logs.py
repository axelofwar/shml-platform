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
def _make_app_for_logs(user, db):
    """Create a minimal FastAPI app with logs router + auth/db overrides."""
    import ray_compute.api.logs as _logs

    app = FastAPI()
    app.include_router(_logs.router)
    app.dependency_overrides[_logs.get_current_user] = lambda: user
    app.dependency_overrides[_logs.get_db] = lambda: db
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

    def test_session_subdirectories_return_most_recent_match(self, tmp_path):
        from ray_compute.api.logs import get_job_log_path

        older = tmp_path / "older-job-abc.log"
        newer = tmp_path / "newer-job-abc.log"
        older.write_text("old")
        newer.write_text("new")

        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)), patch(
            "ray_compute.api.logs.glob.glob",
            side_effect=[[], [str(older), str(newer)]],
        ), patch("ray_compute.api.logs.os.path.getmtime", side_effect=[1, 2]):
            result = get_job_log_path("abc")

        assert result == newer


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

    def test_logs_fallback_to_ray_api_success(self, tmp_path):
        user = _make_test_user("admin")
        job = _make_job("job-ray-api", user_id=user.user_id, ray_job_id="raysubmit_api")
        db = _make_db(job)
        client = TestClient(_make_app_for_logs(user, db), raise_server_exceptions=False)

        mock_job_client = MagicMock()
        mock_job_client.get_job_logs.return_value = "line1\nline2\nline3"

        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)), \
             patch("ray_compute.api.logs.get_job_log_path", return_value=None), \
             patch("ray.job_submission.JobSubmissionClient", return_value=mock_job_client):
            resp = client.get("/logs/job-ray-api?tail=2")

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "ray_api"
        assert data["lines"] == ["line2", "line3"]
        assert data["truncated"] is True

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

    def test_logs_ray_api_empty_returns_none_source(self, tmp_path):
        user = _make_test_user("admin")
        job = _make_job("job-empty-api", user_id=user.user_id, ray_job_id="raysubmit_empty")
        db = _make_db(job)
        client = TestClient(_make_app_for_logs(user, db), raise_server_exceptions=False)

        mock_job_client = MagicMock()
        mock_job_client.get_job_logs.return_value = ""

        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)), patch(
            "ray_compute.api.logs.get_job_log_path", return_value=None
        ), patch("ray.job_submission.JobSubmissionClient", return_value=mock_job_client):
            resp = client.get("/logs/job-empty-api")

        assert resp.status_code == 200
        assert resp.json()["source"] == "none"

    def test_logs_file_read_error_returns_500(self, tmp_path):
        user = _make_test_user("admin")
        job = _make_job("job-read-err", user_id=user.user_id, ray_job_id="raysubmit_read_err")
        db = _make_db(job)
        log_file = tmp_path / "job-driver-raysubmit_read_err.log"
        log_file.write_text("data")
        client = TestClient(_make_app_for_logs(user, db), raise_server_exceptions=False)

        with patch("ray_compute.api.logs.RAY_LOG_DIR", str(tmp_path)), patch(
            "builtins.open", side_effect=OSError("permission denied")
        ):
            resp = client.get("/logs/job-read-err")

        assert resp.status_code == 500
        assert "Error reading log file" in resp.json()["detail"]

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

    def test_deduplicates_same_file_from_multiple_patterns(self, tmp_path):
        user = _make_test_user("admin")
        job = _make_job("job-dupe", user_id=user.user_id, ray_job_id="dupeme")
        db = _make_db(job)
        log_file = tmp_path / "dupeme.log"
        log_file.write_text("same")
        client = TestClient(_make_app_for_logs(user, db), raise_server_exceptions=False)

        with patch("ray_compute.api.logs.glob.glob", side_effect=[[str(log_file)], [str(log_file)]]):
            resp = client.get("/logs/job-dupe/files")

        assert resp.status_code == 200
        assert resp.json()["total"] == 1


class TestStreamJobLogs:
    @pytest.mark.asyncio
    async def test_stream_job_logs_waits_then_reports_missing_file(self):
        from ray_compute.api.logs import stream_job_logs

        user = _make_test_user("admin")
        job = _make_job("job-stream", user_id=user.user_id, ray_job_id="raysubmit_stream")
        db = _make_db(job)

        with patch("ray_compute.api.logs.get_job_log_path", return_value=None), \
             patch("ray_compute.api.logs.asyncio.sleep", new=AsyncMock()):
            response = await stream_job_logs("job-stream", current_user=user, db=db)
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        body = "".join(chunks)
        assert "Waiting for log file to be created" in body
        assert "Log file not found after 30 seconds" in body

    @pytest.mark.asyncio
    async def test_stream_job_logs_returns_after_wait_when_path_disappears(self, tmp_path):
        from ray_compute.api.logs import stream_job_logs

        user = _make_test_user("admin")
        job = _make_job("job-stream-return", user_id=user.user_id, ray_job_id="raysubmit_stream_return")
        db = _make_db(job)
        log_file = tmp_path / "job-driver-raysubmit_stream_return.log"
        log_file.write_text("hello")

        with patch(
            "ray_compute.api.logs.get_job_log_path",
            side_effect=[None, log_file, None],
        ), patch("ray_compute.api.logs.asyncio.sleep", new=AsyncMock()):
            response = await stream_job_logs("job-stream-return", current_user=user, db=db)
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        assert chunks == ["data: Waiting for log file to be created...\n\n"]

    @pytest.mark.asyncio
    async def test_stream_job_logs_reports_read_error(self, tmp_path):
        from ray_compute.api.logs import stream_job_logs

        user = _make_test_user("admin")
        job = _make_job("job-stream-err", user_id=user.user_id, ray_job_id="raysubmit_stream_err")
        db = _make_db(job)
        log_file = tmp_path / "job-driver-raysubmit_stream_err.log"
        log_file.write_text("hello")

        with patch("ray_compute.api.logs.get_job_log_path", return_value=log_file), patch(
            "builtins.open", side_effect=OSError("read failed")
        ):
            response = await stream_job_logs("job-stream-err", current_user=user, db=db)
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        assert any("Error reading logs: read failed" in chunk for chunk in chunks)


class TestWebsocketLogs:
    @pytest.mark.asyncio
    async def test_websocket_logs_missing_job_sends_error_and_closes(self):
        from ray_compute.api.logs import websocket_logs

        websocket = AsyncMock()
        websocket.accept = AsyncMock()
        websocket.send_json = AsyncMock()
        websocket.close = AsyncMock()
        db = _make_db(None)

        await websocket_logs(websocket, "missing-job", db=db)

        websocket.accept.assert_awaited_once()
        websocket.send_json.assert_awaited_once_with(
            {"type": "error", "message": "Job missing-job not found"}
        )
        assert websocket.close.await_count >= 1

    @pytest.mark.asyncio
    async def test_websocket_logs_wait_timeout_sends_error(self):
        from ray_compute.api.logs import websocket_logs

        websocket = AsyncMock()
        websocket.accept = AsyncMock()
        websocket.send_json = AsyncMock()
        websocket.close = AsyncMock()
        db = _make_db(_make_job("job-ws-timeout", ray_job_id="job-ws-timeout"))

        with patch("ray_compute.api.logs.get_job_log_path", return_value=None), patch(
            "ray_compute.api.logs.asyncio.sleep", new=AsyncMock()
        ):
            await websocket_logs(websocket, "job-ws-timeout", db=db)

        sent = [call.args[0] for call in websocket.send_json.await_args_list]
        assert {"type": "status", "message": "Waiting for log file..."} in sent
        assert {"type": "error", "message": "Log file not found after 60 seconds"} in sent

    @pytest.mark.asyncio
    async def test_websocket_logs_handles_ping_and_live_line(self, tmp_path):
        from fastapi import WebSocketDisconnect
        from ray_compute.api.logs import websocket_logs

        websocket = AsyncMock()
        websocket.accept = AsyncMock()
        websocket.send_json = AsyncMock()
        websocket.close = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=["ping", WebSocketDisconnect()])

        log_file = tmp_path / "job-driver-job-live.log"
        log_file.write_text("hist1\nhist2\n")
        db = _make_db(_make_job("job-live", ray_job_id="job-live"))

        class _LiveFile:
            def __init__(self):
                self._calls = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def readlines(self):
                return ["hist1\n", "hist2\n"]

            def seek(self, *_args):
                return None

            def readline(self):
                self._calls += 1
                return "live-line\n" if self._calls == 1 else ""

        open_side_effect = [_LiveFile(), _LiveFile()]

        async def _fake_wait_for(coro, timeout):
            return await coro

        with patch("ray_compute.api.logs.get_job_log_path", return_value=log_file), patch(
            "builtins.open", side_effect=open_side_effect
        ), patch("ray_compute.api.logs.asyncio.wait_for", side_effect=_fake_wait_for), patch(
            "ray_compute.api.logs.asyncio.sleep", new=AsyncMock()
        ):
            await websocket_logs(websocket, "job-live", db=db)

        sent = [call.args[0] for call in websocket.send_json.await_args_list]
        assert {"type": "pong"} in sent
        assert any(msg.get("historical") is True for msg in sent if isinstance(msg, dict) and msg.get("type") == "log")
        assert any(msg.get("historical") is False for msg in sent if isinstance(msg, dict) and msg.get("type") == "log")
