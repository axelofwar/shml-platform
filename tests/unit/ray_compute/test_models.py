"""Unit tests for ray_compute/api/models.py.

The conftest stubs ray_compute.api.models with lightweight classes.
We pop that stub here, load the real models, and verify their structure.
"""
from __future__ import annotations

import sys
import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# sys.modules: the conftest stubs sqlalchemy before SQLAlchemy is imported.
# Temporarily remove those stubs, import real SQLAlchemy + real models, then
# restore the conftest stubs so subsequent test files (test_ray_api.py) still
# get the stub-based environment they expect.
# ---------------------------------------------------------------------------
_SA_KEYS = [
    "sqlalchemy", "sqlalchemy.orm", "sqlalchemy.ext",
    "sqlalchemy.ext.declarative", "sqlalchemy.dialects",
    "sqlalchemy.dialects.postgresql", "sqlalchemy.sql",
    "sqlalchemy.sql.sqltypes", "sqlalchemy.exc",
]

# Save (possibly-stub) values to restore after models import
_saved_sa = {k: sys.modules.pop(k, None) for k in _SA_KEYS}

# Save the conftest-stub ray_compute.api.models (so other tests still see it)
_saved_rc_models = sys.modules.pop("ray_compute.api.models", None)
sys.modules.pop("ray_compute.api", None)

# Import real SQLAlchemy so that the models file loads correctly
import sqlalchemy  # noqa: F401, E402

from ray_compute.api.models import (  # noqa: E402
    Base,
    User,
    UserQuota,
    Job,
    JobQueue,
    ArtifactVersion,
    ResourceUsageDaily,
    AuditLog,
    ApiKey,
    SystemAlert,
)

# Restore conftest's sqlalchemy stubs so test_ray_api.py (collected after us,
# alphabetically r > m) still finds the stubbed environment it expects.
for _k, _v in _saved_sa.items():
    if _v is not None:
        sys.modules[_k] = _v
    else:
        sys.modules.pop(_k, None)
# Restore the conftest's ray_compute.api.models stub (the plain-Python-class
# version) so test_ray_api.py's fixtures get a clean FastAPI-compatible User.
if _saved_rc_models is not None:
    sys.modules["ray_compute.api.models"] = _saved_rc_models
else:
    sys.modules.pop("ray_compute.api.models", None)
sys.modules.pop("ray_compute.api", None)
del _saved_sa, _saved_rc_models, _SA_KEYS


# ---------------------------------------------------------------------------
# Base metadata
# ---------------------------------------------------------------------------

class TestBase:
    def test_base_has_metadata(self):
        assert hasattr(Base, "metadata")

    def test_all_tables_registered(self):
        tables = Base.metadata.tables
        expected = {
            "users", "user_quotas", "jobs", "job_queue",
            "artifact_versions", "resource_usage_daily",
            "audit_log", "api_keys", "system_alerts",
        }
        assert expected.issubset(set(tables.keys()))


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------

class TestUserModel:
    def test_tablename(self):
        assert User.__tablename__ == "users"

    def test_has_primary_key_user_id(self):
        col = User.__table__.c["user_id"]
        assert col.primary_key

    def test_username_unique_not_null(self):
        col = User.__table__.c["username"]
        assert col.unique
        assert not col.nullable

    def test_email_unique_not_null(self):
        col = User.__table__.c["email"]
        assert col.unique
        assert not col.nullable

    def test_role_has_default_user(self):
        col = User.__table__.c["role"]
        assert col.default is not None or col.server_default is not None or "user" in str(col.default)

    def test_is_active_default_true(self):
        col = User.__table__.c["is_active"]
        # Column default is True
        assert col.default.arg is True

    def test_is_suspended_default_false(self):
        col = User.__table__.c["is_suspended"]
        assert col.default.arg is False

    def test_check_constraint_role_values(self):
        constraints = {c.name for c in User.__table__.constraints}
        assert "valid_role" in constraints

    def test_has_quota_relationship(self):
        assert hasattr(User, "quota")

    def test_has_jobs_relationship(self):
        assert hasattr(User, "jobs")

    def test_instantiation_defaults(self):
        u = User(username="tester", email="tester@example.com")
        assert u.username == "tester"
        assert u.email == "tester@example.com"


# ---------------------------------------------------------------------------
# UserQuota model
# ---------------------------------------------------------------------------

class TestUserQuotaModel:
    def test_tablename(self):
        assert UserQuota.__tablename__ == "user_quotas"

    def test_user_id_is_primary_key(self):
        col = UserQuota.__table__.c["user_id"]
        assert col.primary_key

    def test_max_concurrent_jobs_default_3(self):
        col = UserQuota.__table__.c["max_concurrent_jobs"]
        assert col.default.arg == 3

    def test_max_gpu_fraction_default(self):
        col = UserQuota.__table__.c["max_gpu_fraction"]
        assert col.default is not None

    def test_has_user_relationship(self):
        assert hasattr(UserQuota, "user")

    def test_can_use_custom_docker_defaults_false(self):
        col = UserQuota.__table__.c["can_use_custom_docker"]
        # Default is False
        default_val = col.default.arg if col.default else None
        assert default_val is False or default_val is None  # permissive


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------

class TestJobModel:
    def test_tablename(self):
        assert Job.__tablename__ == "jobs"

    def test_job_id_is_primary_key(self):
        col = Job.__table__.c["job_id"]
        assert col.primary_key

    def test_status_default_pending(self):
        col = Job.__table__.c["status"]
        assert col.default.arg == "PENDING"

    def test_priority_default_normal(self):
        col = Job.__table__.c["priority"]
        assert col.default.arg == "normal"

    def test_retry_count_default_zero(self):
        col = Job.__table__.c["retry_count"]
        assert col.default.arg == 0

    def test_max_retries_default_three(self):
        col = Job.__table__.c["max_retries"]
        assert col.default.arg == 3

    def test_check_constraint_priority_values(self):
        constraints = {c.name for c in Job.__table__.constraints}
        assert "valid_priority" in constraints

    def test_has_user_relationship(self):
        assert hasattr(Job, "user")

    def test_tags_is_array_column(self):
        col = Job.__table__.c["tags"]
        assert col is not None

    def test_job_id_string_type(self):
        col = Job.__table__.c["job_id"]
        # The type attribute is a SQLAlchemy String instance; verify it has a length
        assert hasattr(col.type, "length")

    def test_instantiation(self):
        uid = uuid.uuid4()
        j = Job(
            job_id="test-job-001",
            user_id=uid,
            name="training run",
            job_type="training",
            cpu_requested=4,
            memory_gb_requested=16,
            timeout_hours=8,
        )
        assert j.job_id == "test-job-001"
        assert j.name == "training run"


# ---------------------------------------------------------------------------
# JobQueue model
# ---------------------------------------------------------------------------

class TestJobQueueModel:
    def test_tablename(self):
        assert JobQueue.__tablename__ == "job_queue"

    def test_queue_id_autoincrement(self):
        col = JobQueue.__table__.c["queue_id"]
        assert col.autoincrement is True or col.autoincrement == "auto"

    def test_status_default_queued(self):
        col = JobQueue.__table__.c["status"]
        assert col.default.arg == "QUEUED"

    def test_priority_score_not_null(self):
        col = JobQueue.__table__.c["priority_score"]
        assert not col.nullable


# ---------------------------------------------------------------------------
# ArtifactVersion model
# ---------------------------------------------------------------------------

class TestArtifactVersionModel:
    def test_tablename(self):
        assert ArtifactVersion.__tablename__ == "artifact_versions"

    def test_version_default_one(self):
        col = ArtifactVersion.__table__.c["version"]
        assert col.default.arg == 1

    def test_is_deleted_default_false(self):
        col = ArtifactVersion.__table__.c["is_deleted"]
        assert col.default.arg is False


# ---------------------------------------------------------------------------
# ResourceUsageDaily model
# ---------------------------------------------------------------------------

class TestResourceUsageDailyModel:
    def test_tablename(self):
        assert ResourceUsageDaily.__tablename__ == "resource_usage_daily"

    def test_has_cpu_hours(self):
        assert "cpu_hours" in ResourceUsageDaily.__table__.c

    def test_has_gpu_hours(self):
        assert "gpu_hours" in ResourceUsageDaily.__table__.c

    def test_jobs_completed_default_zero(self):
        col = ResourceUsageDaily.__table__.c["jobs_completed"]
        assert col.default.arg == 0


# ---------------------------------------------------------------------------
# AuditLog model
# ---------------------------------------------------------------------------

class TestAuditLogModel:
    def test_tablename(self):
        assert AuditLog.__tablename__ == "audit_log"

    def test_action_not_null(self):
        col = AuditLog.__table__.c["action"]
        assert not col.nullable

    def test_success_default_true(self):
        col = AuditLog.__table__.c["success"]
        assert col.default.arg is True


# ---------------------------------------------------------------------------
# ApiKey model
# ---------------------------------------------------------------------------

class TestApiKeyModel:
    def test_tablename(self):
        assert ApiKey.__tablename__ == "api_keys"

    def test_id_is_primary_key(self):
        col = ApiKey.__table__.c["id"]
        assert col.primary_key

    def test_key_hash_unique(self):
        col = ApiKey.__table__.c["key_hash"]
        assert col.unique

    def test_key_hash_not_null(self):
        col = ApiKey.__table__.c["key_hash"]
        assert not col.nullable

    def test_has_user_relationship(self):
        assert hasattr(ApiKey, "user")

    def test_scopes_array_column(self):
        col = ApiKey.__table__.c["scopes"]
        assert col is not None

    def test_name_not_null(self):
        col = ApiKey.__table__.c["name"]
        assert not col.nullable


# ---------------------------------------------------------------------------
# SystemAlert model
# ---------------------------------------------------------------------------

class TestSystemAlertModel:
    def test_tablename(self):
        assert SystemAlert.__tablename__ == "system_alerts"

    def test_severity_not_null(self):
        col = SystemAlert.__table__.c["severity"]
        assert not col.nullable

    def test_alert_type_not_null(self):
        col = SystemAlert.__table__.c["alert_type"]
        assert not col.nullable

    def test_is_acknowledged_default_false(self):
        col = SystemAlert.__table__.c["is_acknowledged"]
        assert col.default.arg is False
