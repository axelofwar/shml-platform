"""Unit tests for ray_compute/api/audit.py"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_root = Path(__file__).resolve().parent.parent.parent.parent
for p in [str(_root), str(_root / "ray_compute")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Ensure ray_compute.api.database is stubbed before importing audit.py,
# which imports `engine` from database at module level.
if "ray_compute.api.database" not in sys.modules:
    import types as _types
    _db_mod = _types.ModuleType("ray_compute.api.database")
    _db_mod.engine = MagicMock()
    _db_mod.get_db = MagicMock()
    _db_mod.SessionLocal = MagicMock()
    sys.modules["ray_compute.api.database"] = _db_mod

# Import audit directly — conftest already stubs ray_compute.api.auth as a
# MagicMock (which auto-satisfies `from .auth import log_audit_event`).
# Importing WITHOUT patch.dict ensures audit.py's module object stays
# consistent in sys.modules so later patch() calls work correctly.
from ray_compute.api.audit import (  # type: ignore
    AuditAction,
    AuditLog,
    AuditLogger,
    get_audit_logger,
)


def _make_logger():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    return AuditLogger(db=db), db


class _FakeAuditLog:
    """Lightweight stand-in for the SQLAlchemy AuditLog model."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestAuditAction:
    """Enum value tests."""

    def test_job_submit_value(self):
        assert AuditAction.JOB_SUBMIT.value == "job.submit"

    def test_auth_login_value(self):
        assert AuditAction.AUTH_LOGIN.value == "auth.login"

    def test_api_key_create_value(self):
        assert AuditAction.API_KEY_CREATE.value == "api_key.create"


class TestAuditLogger:
    """Tests for AuditLogger.log() and convenience methods."""

    @pytest.fixture(autouse=True)
    def _patch_audit_log(self):
        """Patch AuditLog at test run time (not module import time)."""
        with patch("ray_compute.api.audit.AuditLog", _FakeAuditLog):
            yield

    def test_log_basic_action(self):
        logger, db = _make_logger()
        entry = logger.log(action=AuditAction.AUTH_LOGIN, auth_method="oauth")
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert entry is db.add.call_args[0][0]

    def test_log_with_user_object(self):
        """User with user_id attribute is extracted correctly."""
        logger, db = _make_logger()
        user = MagicMock()
        user.user_id = uuid.uuid4()
        user.email = "user@example.com"

        logger.log(
            action=AuditAction.JOB_SUBMIT,
            actual_user=user,
            auth_method="oauth",
        )
        entry = db.add.call_args[0][0]
        assert entry.actual_user_id == user.user_id
        assert entry.actual_user_email == "user@example.com"

    def test_log_with_dict_user(self):
        """Dict user is extracted via get('user_id')."""
        logger, db = _make_logger()
        uid = str(uuid.uuid4())
        user_dict = {"user_id": uid, "email": "dict@example.com"}

        logger.log(
            action=AuditAction.JOB_SUBMIT,
            actual_user=user_dict,
            auth_method="oauth",
        )
        entry = db.add.call_args[0][0]
        assert str(entry.actual_user_id) == uid
        assert entry.actual_user_email == "dict@example.com"

    def test_log_effective_user_defaults_to_actual_user(self):
        """When effective_user not provided, effective* equals actual*."""
        logger, db = _make_logger()
        user = MagicMock()
        user.user_id = uuid.uuid4()
        user.email = "actual@example.com"

        logger.log(
            action=AuditAction.AUTH_LOGIN,
            actual_user=user,
            auth_method="oauth",
        )
        entry = db.add.call_args[0][0]
        assert entry.effective_user_id == user.user_id

    def test_log_with_explicit_effective_user(self):
        """Explicit effective_user is set separately from actual_user."""
        logger, db = _make_logger()
        actual = MagicMock(user_id=uuid.uuid4(), email="actual@test.com")
        effective = MagicMock(user_id=uuid.uuid4(), email="service@test.com")

        logger.log(
            action=AuditAction.AUTH_IMPERSONATION_START,
            actual_user=actual,
            effective_user=effective,
            auth_method="impersonation",
        )
        entry = db.add.call_args[0][0]
        assert entry.actual_user_id == actual.user_id
        assert entry.effective_user_id == effective.user_id

    def test_log_extracts_request_metadata(self):
        """Request object provides ip, user_agent, path, method."""
        logger, db = _make_logger()
        request = MagicMock()
        request.headers.get = lambda k, d="": {
            "X-Forwarded-For": "10.0.0.1, 10.0.0.2",
            "User-Agent": "TestAgent/1.0",
        }.get(k, d)
        request.client = None
        request.url.path = "/api/v1/jobs"
        request.method = "POST"

        logger.log(
            action=AuditAction.JOB_SUBMIT,
            request=request,
            auth_method="oauth",
        )
        entry = db.add.call_args[0][0]
        assert entry.ip_address == "10.0.0.1"
        assert entry.user_agent == "TestAgent/1.0"
        assert entry.request_path == "/api/v1/jobs"
        assert entry.request_method == "POST"

    def test_log_falls_back_to_client_host(self):
        """When no X-Forwarded-For header, falls back to request.client.host."""
        logger, db = _make_logger()
        request = MagicMock()
        request.headers.get = lambda k, d="": d
        request.client.host = "192.168.1.5"
        request.url.path = "/test"
        request.method = "GET"

        logger.log(
            action=AuditAction.AUTH_LOGIN,
            request=request,
            auth_method="oauth",
        )
        entry = db.add.call_args[0][0]
        assert entry.ip_address == "192.168.1.5"

    def test_log_failure_sets_error_message(self):
        """Failed log entry includes error message."""
        logger, db = _make_logger()
        logger.log(
            action=AuditAction.JOB_SUBMIT,
            auth_method="oauth",
            success=False,
            error_message="GPU quota exceeded",
        )
        entry = db.add.call_args[0][0]
        assert entry.success == "false"
        assert entry.error_message == "GPU quota exceeded"

    def test_log_success_sets_true_string(self):
        """Successful log entry has success='true'."""
        logger, db = _make_logger()
        logger.log(action=AuditAction.AUTH_LOGIN, auth_method="oauth")
        entry = db.add.call_args[0][0]
        assert entry.success == "true"

    def test_log_with_api_key_id(self):
        """api_key_id is converted to UUID."""
        logger, db = _make_logger()
        key_id = str(uuid.uuid4())
        logger.log(
            action=AuditAction.AUTH_API_KEY_USED,
            auth_method="api_key",
            api_key_id=key_id,
        )
        entry = db.add.call_args[0][0]
        assert entry.api_key_id == uuid.UUID(key_id)

    def test_log_with_action_enum(self):
        """AuditAction enum value is stored as string."""
        logger, db = _make_logger()
        logger.log(action=AuditAction.JOB_CANCEL, auth_method="oauth")
        entry = db.add.call_args[0][0]
        assert entry.action == "job.cancel"

    def test_log_job_submission_convenience(self):
        """log_job_submission delegates to log() with correct resource type."""
        logger, db = _make_logger()
        user = MagicMock(user_id=uuid.uuid4(), email="u@test.com")
        request = MagicMock()
        request.headers.get = lambda k, d="": d
        request.client = None
        request.url.path = "/jobs"
        request.method = "POST"

        logger.log_job_submission(
            job_id="job-123",
            actual_user=user,
            effective_user=None,
            auth_method="oauth",
            request=request,
            job_details={"gpu": 0.5},
        )
        entry = db.add.call_args[0][0]
        assert entry.resource_type == "job"
        assert entry.resource_id == "job-123"
        assert entry.action == "job.submit"

    def test_log_impersonation_convenience(self):
        """log_impersonation delegates with impersonation auth method."""
        logger, db = _make_logger()
        actual = MagicMock(user_id=uuid.uuid4(), email="admin@test.com")
        effective = MagicMock(user_id=uuid.uuid4(), email="service@test.com")
        request = MagicMock()
        request.headers.get = lambda k, d="": d
        request.client = None
        request.url.path = "/impersonate"
        request.method = "POST"

        logger.log_impersonation(
            actual_user=actual,
            target_service_account="svc-acct",
            effective_user=effective,
            request=request,
        )
        entry = db.add.call_args[0][0]
        assert entry.auth_method == "impersonation"
        assert entry.resource_id == "svc-acct"

    def test_log_api_key_usage_convenience(self):
        """log_api_key_usage delegates to log()."""
        logger, db = _make_logger()
        key_id = str(uuid.uuid4())
        effective = MagicMock(user_id=uuid.uuid4(), email="svc@test.com")
        request = MagicMock()
        request.headers.get = lambda k, d="": d
        request.client = None
        request.url.path = "/jobs"
        request.method = "GET"

        logger.log_api_key_usage(
            api_key_id=key_id,
            effective_user=effective,
            request=request,
            action_performed="list_jobs",
        )
        entry = db.add.call_args[0][0]
        assert entry.auth_method == "api_key"
        assert entry.details == {"action_performed": "list_jobs"}

    def test_get_audit_logger_returns_instance(self):
        """get_audit_logger factory returns AuditLogger."""
        db = MagicMock()
        result = get_audit_logger(db)
        assert isinstance(result, AuditLogger)
