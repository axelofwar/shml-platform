"""conftest.py for tests/unit/ray_compute/.

Stubs `ray` and other optional deps at the sys.modules level before any test
module in this directory is imported by pytest.
"""
from __future__ import annotations

import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Stub ray and child namespaces (idempotent — only if not already present)
# ---------------------------------------------------------------------------
if "ray" not in sys.modules:
    _ray = MagicMock(name="ray")
    _ray_job = MagicMock(name="ray.job_submission")
    _ray_job.JobSubmissionClient = MagicMock(return_value=MagicMock())

    class _JobStatus:  # noqa: N801
        PENDING = "PENDING"
        RUNNING = "RUNNING"
        SUCCEEDED = "SUCCEEDED"
        FAILED = "FAILED"
        STOPPED = "STOPPED"

    _ray_job.JobStatus = _JobStatus
    sys.modules["ray"] = _ray
    sys.modules["ray.job_submission"] = _ray_job
    sys.modules["ray.dashboard"] = MagicMock()
    sys.modules["ray.dashboard.modules"] = MagicMock()
    sys.modules["ray.dashboard.modules.job"] = MagicMock()
    sys.modules["ray.dashboard.modules.job.common"] = MagicMock()
    sys.modules["ray.runtime_env"] = MagicMock()

# Stub python-jose (JWT library used by auth.py)
if "jose" not in sys.modules:
    _jose = MagicMock(name="jose")
    _jose.JWTError = Exception
    _jose.jwt = MagicMock()
    _jose.jwt.decode = MagicMock(return_value={"sub": "testuser"})
    sys.modules["jose"] = _jose
    sys.modules["jose.exceptions"] = MagicMock()

# Stub passlib (password hashing used by auth modules)
if "passlib" not in sys.modules:
    sys.modules["passlib"] = MagicMock()
    sys.modules["passlib.context"] = MagicMock()
    sys.modules["passlib.hash"] = MagicMock()

# ---------------------------------------------------------------------------
# Stub SQLAlchemy with proper class types so that `Optional[Session]` and
# `Optional[User]` type annotations in auth.py don't crash at eval time.
# Python evaluates annotations eagerly at function definition — MagicMock
# objects passed to typing.Optional fail because Optional tries to validate
# the type, and MagicMock.__args__ etc. don't behave like types.
# ---------------------------------------------------------------------------
if "sqlalchemy" not in sys.modules:
    # Create real (empty) stub classes that look like types
    class _Session:  # noqa: N801
        pass

    class _DeclarativeBase:  # noqa: N801
        pass

    _sa = MagicMock(name="sqlalchemy")
    _sa_orm = MagicMock(name="sqlalchemy.orm")
    _sa_orm.Session = _Session
    _sa_orm.DeclarativeBase = _DeclarativeBase
    _sa.orm = _sa_orm
    _sa.Column = MagicMock()
    _sa.String = MagicMock(return_value=MagicMock())
    _sa.Integer = MagicMock()
    _sa.Boolean = MagicMock()
    _sa.DateTime = MagicMock()
    _sa.ForeignKey = MagicMock()
    _sa.create_engine = MagicMock()
    _sa.inspect = MagicMock()
    sys.modules["sqlalchemy"] = _sa
    sys.modules["sqlalchemy.orm"] = _sa_orm
    sys.modules["sqlalchemy.ext"] = MagicMock()
    sys.modules["sqlalchemy.ext.declarative"] = MagicMock()
    sys.modules["sqlalchemy.dialects"] = MagicMock()
    sys.modules["sqlalchemy.dialects.postgresql"] = MagicMock()
    sys.modules["sqlalchemy.sql"] = MagicMock()
    sys.modules["sqlalchemy.exc"] = MagicMock()

# ---------------------------------------------------------------------------
# Stub ray_compute.api.models with real Python classes so type annotations
# like `Optional[User]` work correctly at function definition time.
# ---------------------------------------------------------------------------
if "ray_compute.api.models" not in sys.modules:
    import types as _types

    _models_mod = _types.ModuleType("ray_compute.api.models")

    class Base:  # noqa: N801
        pass

    class User:  # noqa: N801
        __tablename__ = "users"
        user_id = None
        username: str = ""
        email: str = ""
        role: str = "user"
        is_active: bool = True
        is_suspended: bool = False

    class UserQuota:  # noqa: N801
        __tablename__ = "user_quotas"
        max_concurrent_jobs: int = 5
        max_gpu_hours_per_day: int = 48

    class Job:  # noqa: N801
        __tablename__ = "jobs"
        job_id = None
        status: str = "PENDING"

    class ApiKey:  # noqa: N801
        __tablename__ = "api_keys"
        key_hash: str = ""
        is_active: bool = True

    class AuditLog:  # noqa: N801
        __tablename__ = "audit_logs"

    class JobQueue:  # noqa: N801
        __tablename__ = "job_queue"

    _models_mod.Base = Base  # type: ignore[attr-defined]
    _models_mod.User = User  # type: ignore[attr-defined]
    _models_mod.UserQuota = UserQuota  # type: ignore[attr-defined]
    _models_mod.Job = Job  # type: ignore[attr-defined]
    _models_mod.ApiKey = ApiKey  # type: ignore[attr-defined]
    _models_mod.AuditLog = AuditLog  # type: ignore[attr-defined]
    _models_mod.JobQueue = JobQueue  # type: ignore[attr-defined]
    sys.modules["ray_compute.api.models"] = _models_mod

# ---------------------------------------------------------------------------
# Stub the ray_compute.api.auth module entirely so cluster.py imports don't
# cascade through the JWT+SQLAlchemy dependency chain.
# The `get_current_user` and `get_db` deps are overridden per-test anyway.
# ---------------------------------------------------------------------------
if "ray_compute.api.auth" not in sys.modules:
    # Use the User class from the models stub above
    _User = sys.modules["ray_compute.api.models"].User  # type: ignore[attr-defined]

    class _FakeUser(_User):  # noqa: N801
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        username = "testuser"
        email = "test@test.local"
        role = "admin"
        is_active = True
        is_suspended = False
        quota = MagicMock(max_concurrent_jobs=5, max_gpu_hours_per_day=48)

    _auth_mod = MagicMock(name="ray_compute.api.auth")
    _auth_mod.get_current_user = AsyncMock(return_value=_FakeUser())
    _auth_mod.get_current_active_user = AsyncMock(return_value=_FakeUser())
    _auth_mod.User = _User
    _auth_mod.get_db = MagicMock()
    sys.modules["ray_compute.api.auth"] = _auth_mod
