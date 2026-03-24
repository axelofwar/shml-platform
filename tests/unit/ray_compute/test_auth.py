"""Unit tests for ray_compute/api/auth.py pure functions and logic.

Loads the REAL auth module (popping the conftest stub) so coverage is tracked.
Restores the conftest stub afterwards to keep test_ray_api.py working.
"""
from __future__ import annotations

import asyncio
import sys
import os
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
_RC_ROOT = os.path.join(_ROOT, "ray_compute")
for _p in [_ROOT, _RC_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Extend the conftest models stub so User/UserQuota accept keyword-arg construction.
# The conftest creates them as bare classes; real auth.py calls User(..., role=...).
# ---------------------------------------------------------------------------
_models_mod = sys.modules.get("ray_compute.api.models")
if _models_mod is not None:
    # Replace User with one that accepts kwargs AND has class-level column descriptors
    # for SQLAlchemy-style filter expressions (User.email == "x").
    class _FUser:
        # Class-level MagicMocks used as column descriptors in filter expressions
        oauth_sub = MagicMock(name="User.oauth_sub")
        email = MagicMock(name="User.email")
        user_id = MagicMock(name="User.user_id")
        role = MagicMock(name="User.role")
        is_active = MagicMock(name="User.is_active")
        is_suspended = MagicMock(name="User.is_suspended")

        def __init__(self, **kwargs):
            # Set instance defaults first, then override with kwargs
            self.user_id = None
            self.username = ""
            self.email = ""
            self.role = "user"
            self.is_active = True
            self.is_suspended = False
            self.last_login = None
            self.suspension_reason = None
            self.oauth_sub = None
            for k, v in kwargs.items():
                setattr(self, k, v)

    class _FUserQuota:
        user_id = MagicMock(name="UserQuota.user_id")

        def __init__(self, **kwargs):
            self.user_id = None
            for k, v in kwargs.items():
                setattr(self, k, v)

    class _FAuditLog:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class _FApiKey:
        # Class-level descriptors for filter expressions
        key_hash = MagicMock(name="ApiKey.key_hash")
        previous_key_hash = MagicMock(name="ApiKey.previous_key_hash")
        revoked_at = MagicMock(name="ApiKey.revoked_at")
        expires_at = MagicMock(name="ApiKey.expires_at")
        previous_key_valid_until = MagicMock(name="ApiKey.previous_key_valid_until")
        user_id = MagicMock(name="ApiKey.user_id")

        def __init__(self, **kwargs):
            self.key_hash = ""
            self.previous_key_hash = None
            self.revoked_at = None
            self.expires_at = None
            self.previous_key_valid_until = None
            self.last_used_at = None
            self.user_id = None
            self.is_active = True
            for k, v in kwargs.items():
                setattr(self, k, v)

    _models_mod.User = _FUser
    _models_mod.UserQuota = _FUserQuota
    _models_mod.AuditLog = _FAuditLog
    _models_mod.ApiKey = _FApiKey

# ---------------------------------------------------------------------------
# Stub ray_compute.api.database (needed by auth.py, not stubbed by conftest)
# ---------------------------------------------------------------------------
if "ray_compute.api.database" not in sys.modules:
    import types as _types
    _db_mod = _types.ModuleType("ray_compute.api.database")

    def _get_db():
        yield MagicMock()

    _db_mod.get_db = _get_db
    _db_mod.SessionLocal = MagicMock()
    _db_mod.engine = MagicMock()
    sys.modules["ray_compute.api.database"] = _db_mod

# Make sure the ray_compute.api package exists in sys.modules
if "ray_compute" not in sys.modules:
    import types as _types
    _rc_pkg = _types.ModuleType("ray_compute")
    _rc_pkg.__path__ = [_RC_ROOT]  # type: ignore[attr-defined]  # MUST have __path__ to be a package
    sys.modules["ray_compute"] = _rc_pkg
if "ray_compute.api" not in sys.modules:
    import types as _types
    _api_pkg = _types.ModuleType("ray_compute.api")
    _api_pkg.__path__ = [_RC_ROOT + "/api"]  # type: ignore[attr-defined]
    sys.modules["ray_compute.api"] = _api_pkg

# ---------------------------------------------------------------------------
# Save the conftest auth stub, pop it, load the REAL module, then restore.
# ---------------------------------------------------------------------------
_saved_auth_stub = sys.modules.pop("ray_compute.api.auth", None)

from ray_compute.api.auth import (  # noqa: E402
    can_submit_jobs,
    has_role_permission,
    ROLE_HIERARCHY,
    create_access_token,
    verify_access_token,
    get_user_from_proxy_headers,
    get_user_from_api_key,
    get_current_user,
    get_current_active_user,
    get_current_admin_user,
    require_role,
    log_audit_event,
    AuthError,
    PROXY_AUTH_ENABLED,
)

# Save reference to the REAL module (before restoring stub).
# Tests must patch _real_auth_module, not "ray_compute.api.auth" (which points to stub after restore).
_real_auth_module = sys.modules["ray_compute.api.auth"]

# Restore the conftest's stub so test_ray_api.py keeps working
if _saved_auth_stub is not None:
    sys.modules["ray_compute.api.auth"] = _saved_auth_stub
del _saved_auth_stub


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_db(existing_user=None):
    """Build a mock DB session whose query chain returns existing_user (or None)."""
    db = MagicMock()
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = existing_user
    mock_query.filter.return_value = mock_filter
    db.query.return_value = mock_query
    return db


def _make_request(headers: dict | None = None):
    """Build a minimal mock FastAPI Request with the given headers."""
    req = MagicMock()
    req.headers = MagicMock()
    req.headers.get = lambda key, default=None: (headers or {}).get(key, default)
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    return req


# ===========================================================================
# ROLE HIERARCHY TESTS
# ===========================================================================


class TestRoleHierarchy:
    def test_hierarchy_values(self):
        assert ROLE_HIERARCHY["admin"] > ROLE_HIERARCHY["premium"]
        assert ROLE_HIERARCHY["premium"] > ROLE_HIERARCHY["user"]
        assert ROLE_HIERARCHY["user"] > ROLE_HIERARCHY["viewer"]

    def test_can_submit_jobs_admin(self):
        assert can_submit_jobs("admin") is True

    def test_can_submit_jobs_premium(self):
        assert can_submit_jobs("premium") is True

    def test_can_submit_jobs_user(self):
        assert can_submit_jobs("user") is True

    def test_can_submit_jobs_viewer(self):
        assert can_submit_jobs("viewer") is False

    def test_can_submit_jobs_unknown(self):
        assert can_submit_jobs("unknown") is False

    def test_has_role_permission_admin_over_all(self):
        for role in ["admin", "premium", "user", "viewer"]:
            assert has_role_permission("admin", role) is True

    def test_has_role_permission_premium_over_user(self):
        assert has_role_permission("premium", "user") is True
        assert has_role_permission("premium", "viewer") is True
        assert has_role_permission("premium", "premium") is True
        assert has_role_permission("premium", "admin") is False

    def test_has_role_permission_user_over_viewer(self):
        assert has_role_permission("user", "viewer") is True
        assert has_role_permission("user", "user") is True
        assert has_role_permission("user", "premium") is False
        assert has_role_permission("user", "admin") is False

    def test_has_role_permission_viewer_base(self):
        assert has_role_permission("viewer", "viewer") is True
        assert has_role_permission("viewer", "user") is False

    def test_has_role_permission_unknown_role(self):
        assert has_role_permission("ghost", "viewer") is False


# ===========================================================================
# TOKEN TESTS
# ===========================================================================


class TestTokenFunctions:
    def test_create_access_token_basic(self):
        # jose.jwt.encode is a MagicMock — call succeeds and returns something
        result = create_access_token({"sub": "user123"})
        # Just verify it was called (not None/exception)
        jose_jwt = sys.modules["jose"].jwt
        jose_jwt.encode.assert_called()

    def test_create_access_token_with_expires_delta(self):
        result = create_access_token({"sub": "u"}, expires_delta=timedelta(minutes=30))
        jose_jwt = sys.modules["jose"].jwt
        jose_jwt.encode.assert_called()

    def test_create_access_token_default_expiry(self):
        # Should add an "exp" key to the payload
        create_access_token({"role": "admin"})
        jose_jwt = sys.modules["jose"].jwt
        call_args = jose_jwt.encode.call_args
        assert call_args is not None
        payload = call_args[0][0]
        assert "exp" in payload

    def test_verify_access_token_returns_payload(self):
        # jose.jwt.decode returns {"sub": "testuser"} by default (conftest)
        result = verify_access_token("sometoken")
        assert isinstance(result, dict)

    def test_verify_access_token_raises_on_jwtError(self):
        import fastapi
        jose_jwt = sys.modules["jose"].jwt
        original = jose_jwt.decode.side_effect
        try:
            jose_jwt.decode.side_effect = Exception("bad token")
            with pytest.raises(fastapi.HTTPException) as exc_info:
                verify_access_token("badtoken")
            assert exc_info.value.status_code == 401
        finally:
            jose_jwt.decode.side_effect = original


# ===========================================================================
# PROXY HEADERS AUTH TESTS
# ===========================================================================


class TestGetUserFromProxyHeaders:
    def test_no_headers_returns_none(self):
        req = _make_request({})
        db = _make_db()
        result = asyncio.run(get_user_from_proxy_headers(req, db))
        assert result is None

    def test_existing_user_by_oauth_sub(self):
        from ray_compute.api import models as _m
        existing = _m.User(
            user_id="uid-1",
            username="alice",
            email="alice@example.com",
            oauth_sub="sub-alice",
            role="user",
            is_active=True,
            is_suspended=False,
        )
        db = _make_db(existing)
        req = _make_request({"X-Auth-Request-User": "sub-alice", "X-Auth-Request-Email": "alice@example.com"})
        result = asyncio.run(get_user_from_proxy_headers(req, db))
        assert result is existing

    def test_existing_user_by_email_updates_oauth_sub(self):
        from ray_compute.api import models as _m
        existing = _m.User(
            user_id="uid-2",
            email="bob@example.com",
            role="user",
            is_active=True,
            is_suspended=False,
        )
        existing.oauth_sub = None  # No oauth_sub yet

        # DB: first query (by oauth_sub) returns None, second (by email) returns existing
        db = MagicMock()
        call_count = [0]

        def _query_side_effect(*args):
            mock_q = MagicMock()

            def _filter_side_effect(*fargs):
                mock_f = MagicMock()
                call_count[0] += 1
                if call_count[0] == 1:
                    mock_f.first.return_value = None  # Not found by oauth_sub
                else:
                    mock_f.first.return_value = existing  # Found by email
                return mock_f

            mock_q.filter.side_effect = _filter_side_effect
            return mock_q

        db.query.side_effect = _query_side_effect
        req = _make_request({"X-Auth-Request-User": "new-sub", "X-Auth-Request-Email": "bob@example.com"})
        result = asyncio.run(get_user_from_proxy_headers(req, db))
        assert result is existing
        assert existing.oauth_sub == "new-sub"

    def test_no_user_creates_new_admin(self):
        from ray_compute.api import models as _m
        db = MagicMock()

        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = None
        db.query.return_value = mock_q

        created_users = []

        def _add(obj):
            if isinstance(obj, _m.User):
                created_users.append(obj)

        db.add.side_effect = _add
        req = _make_request({
            "X-Auth-Request-User": "admin-sub",
            "X-Auth-Request-Email": "admin@example.com",
            "X-Auth-Request-Groups": "admin,platform-admins",
        })
        result = asyncio.run(get_user_from_proxy_headers(req, db))
        assert len(created_users) >= 1
        assert created_users[0].role == "admin"

    def test_no_user_creates_developer_as_user(self):
        from ray_compute.api import models as _m
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = None
        db.query.return_value = mock_q

        created_users = []
        db.add.side_effect = lambda obj: (
            created_users.append(obj) if isinstance(obj, _m.User) else None
        )

        req = _make_request({
            "X-Auth-Request-User": "dev-sub",
            "X-Auth-Request-Email": "dev@example.com",
            "X-Auth-Request-Groups": "developer",
        })
        result = asyncio.run(get_user_from_proxy_headers(req, db))
        assert created_users[0].role == "user"  # developer maps to user role

    def test_elevated_developer_creates_user_role(self):
        from ray_compute.api import models as _m
        db = MagicMock()
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = None
        db.query.return_value = mock_q
        created = []
        db.add.side_effect = lambda obj: (
            created.append(obj) if isinstance(obj, _m.User) else None
        )
        req = _make_request({
            "X-Auth-Request-User": "eldev-sub",
            "X-Auth-Request-Email": "eldev@example.com",
            "X-Auth-Request-Groups": "elevated-developer",
        })
        asyncio.run(get_user_from_proxy_headers(req, db))
        assert created[0].role == "user"

    def test_existing_user_role_updated_to_admin(self):
        from ray_compute.api import models as _m
        existing = _m.User(oauth_sub="sub-3", email="x@x.com", role="user",
                           is_active=True, is_suspended=False)
        existing.last_login = None
        db = _make_db(existing)

        req = _make_request({
            "X-Auth-Request-User": "sub-3",
            "X-Auth-Request-Email": "x@x.com",
            "X-Auth-Request-Groups": "admin",
        })
        asyncio.run(get_user_from_proxy_headers(req, db))
        assert existing.role == "admin"

    def test_email_fallback_used_as_oauth_sub(self):
        """When no X-Auth-Request-User, email is used as oauth_sub."""
        from ray_compute.api import models as _m
        existing = _m.User(oauth_sub="alice@x.com", email="alice@x.com", role="viewer",
                           is_active=True, is_suspended=False)
        db = _make_db(existing)
        req = _make_request({"X-Auth-Request-Email": "alice@x.com"})  # no oauth_sub header
        result = asyncio.run(get_user_from_proxy_headers(req, db))
        assert result is existing


# ===========================================================================
# API KEY AUTH TESTS
# ===========================================================================


class TestGetUserFromApiKey:
    def test_no_matching_env_key_returns_none(self):
        db = MagicMock()
        # DB query raises exception (ApiKey table not exist)
        db.query.side_effect = Exception("no table")

        with patch.dict(os.environ, {}, clear=False):
            # Ensure CICD keys are not set
            for k in ["CICD_ADMIN_KEY", "CICD_DEVELOPER_KEY",
                      "CICD_ELEVATED_DEVELOPER_KEY", "CICD_VIEWER_KEY"]:
                os.environ.pop(k, None)
            result = get_user_from_api_key("invalid-key-xyz", db)
        assert result is None

    def test_cicd_admin_env_key_creates_service_account(self):
        from ray_compute.api import models as _m

        db = MagicMock()
        db.query.side_effect = Exception("no ApiKey table")

        # Make db.query(User).filter(...).first() return None (new user)
        db.query.side_effect = None
        mock_q = MagicMock()
        mock_q.filter.return_value.first.return_value = None
        db.query.return_value = mock_q

        created = []
        db.add.side_effect = lambda obj: created.append(obj)

        with patch.dict(os.environ, {"CICD_ADMIN_KEY": "test-admin-key"}):
            # Use _real_auth_module (module-level ref) — not sys.modules["ray_compute.api.auth"]
            # which after module setup points to the conftest stub (MagicMock).
            original = _real_auth_module.CICD_ADMIN_KEY
            _real_auth_module.CICD_ADMIN_KEY = "test-admin-key"
            try:
                result = get_user_from_api_key("test-admin-key", db)
            finally:
                _real_auth_module.CICD_ADMIN_KEY = original

        # Should have created a User with role "admin"
        # Use attribute check only — the User class reference may differ
        # between isolation runs (test_models.py swaps real ↔ stub models)
        assert any(
            getattr(obj, "role", None) == "admin"
            for obj in created
        )

    def test_db_api_key_found_returns_user(self):
        from ray_compute.api import models as _m
        import hashlib
        from datetime import datetime

        key = "db-api-key-123"
        key_hash = hashlib.sha256(key.encode()).hexdigest()

        owner = _m.User(user_id="owner-1", email="owner@x.com", role="user",
                        is_active=True, is_suspended=False)
        api_key_record = _m.ApiKey(
            key_hash=key_hash,
            revoked_at=None,
            expires_at=None,
            last_used_at=None,
            user_id="owner-1",
        )

        call_seq = [0]

        def _query_side(cls):
            call_seq[0] += 1
            mock_q = MagicMock()
            if call_seq[0] == 1:
                # First call: querying ApiKey
                mock_q.filter.return_value.first.return_value = api_key_record
            elif call_seq[0] == 2:
                # Second call: querying User by user_id
                mock_q.filter.return_value.first.return_value = owner
            else:
                mock_q.filter.return_value.first.return_value = None
            return mock_q

        db = MagicMock()
        db.query.side_effect = _query_side

        result = get_user_from_api_key(key, db)
        assert result is owner

    def test_db_api_key_expired_returns_none(self):
        from ray_compute.api import models as _m
        import hashlib
        from datetime import datetime

        key = "expired-key"
        key_hash = hashlib.sha256(key.encode()).hexdigest()

        api_key_record = _m.ApiKey(
            key_hash=key_hash,
            revoked_at=None,
            expires_at=datetime(2000, 1, 1),  # way in the past
            last_used_at=None,
            user_id="some-user",
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = api_key_record
        db.query.return_value.filter.return_value.filter.return_value.first.return_value = api_key_record

        result = get_user_from_api_key(key, db)
        assert result is None


# ===========================================================================
# GET CURRENT USER - CORE AUTH FLOW
# ===========================================================================


class TestGetCurrentUser:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_api_key_auth_success(self):
        from ray_compute.api import models as _m
        user = _m.User(user_id="uid", email="u@u.com", role="user",
                       is_active=True, is_suspended=False)

        req = _make_request({"X-API-Key": "valid-key"})
        db = _make_db()

        with patch.object(_real_auth_module, "get_user_from_api_key", return_value=user):
            result = self._run(get_current_user(req, None, db))
        assert result is user

    def test_api_key_invalid_falls_through(self):
        """Invalid API key falls through to proxy auth or bearer."""
        import fastapi
        req = _make_request({"X-API-Key": "bad-key"})
        db = _make_db()
        # With no proxy headers and no token, should raise 401
        with patch.object(_real_auth_module, "get_user_from_api_key", return_value=None):
            with patch.object(_real_auth_module, "get_user_from_proxy_headers",
                              new=AsyncMock(return_value=None)):
                with pytest.raises(fastapi.HTTPException) as exc_info:
                    self._run(get_current_user(req, None, db))
                assert exc_info.value.status_code == 401

    def test_proxy_auth_success(self):
        from ray_compute.api import models as _m
        user = _m.User(user_id="uid-2", email="p@p.com", role="user",
                       is_active=True, is_suspended=False)
        req = _make_request({})
        db = _make_db()

        with patch.object(_real_auth_module, "get_user_from_api_key", return_value=None):
            with patch.object(_real_auth_module, "get_user_from_proxy_headers",
                              new=AsyncMock(return_value=user)):
                result = self._run(get_current_user(req, None, db))
        assert result is user

    def test_proxy_auth_inactive_user_raises_403(self):
        from ray_compute.api import models as _m
        import fastapi
        user = _m.User(user_id="uid-3", email="x@x.com", role="user",
                       is_active=False, is_suspended=False)
        req = _make_request({})
        db = _make_db()

        with patch.object(_real_auth_module, "get_user_from_api_key", return_value=None):
            with patch.object(_real_auth_module, "get_user_from_proxy_headers",
                              new=AsyncMock(return_value=user)):
                with pytest.raises(fastapi.HTTPException) as exc_info:
                    self._run(get_current_user(req, None, db))
                assert exc_info.value.status_code == 403

    def test_proxy_auth_suspended_user_raises_403(self):
        from ray_compute.api import models as _m
        import fastapi
        user = _m.User(user_id="uid-4", email="s@s.com", role="user",
                       is_active=True, is_suspended=True)
        user.suspension_reason = "violation"
        req = _make_request({})
        db = _make_db()

        with patch.object(_real_auth_module, "get_user_from_api_key", return_value=None):
            with patch.object(_real_auth_module, "get_user_from_proxy_headers",
                              new=AsyncMock(return_value=user)):
                with pytest.raises(fastapi.HTTPException) as exc_info:
                    self._run(get_current_user(req, None, db))
                assert exc_info.value.status_code == 403

    def test_bearer_token_success(self):
        from ray_compute.api import models as _m
        user = _m.User(user_id="uid-5", email="b@b.com", role="user",
                       is_active=True, is_suspended=False)
        req = _make_request({})
        db = _make_db()

        with patch.object(_real_auth_module, "get_user_from_api_key", return_value=None):
            with patch.object(_real_auth_module, "get_user_from_proxy_headers",
                              new=AsyncMock(return_value=None)):
                with patch.object(_real_auth_module, "get_user_from_fusionauth",
                                  new=AsyncMock(return_value=user)):
                    result = self._run(get_current_user(req, "some-token", db))
        assert result is user

    def test_bearer_token_inactive_user_raises_403(self):
        from ray_compute.api import models as _m
        import fastapi
        user = _m.User(user_id="uid-6", email="i@i.com", role="user",
                       is_active=False, is_suspended=False)
        req = _make_request({})
        db = _make_db()

        with patch.object(_real_auth_module, "get_user_from_api_key", return_value=None):
            with patch.object(_real_auth_module, "get_user_from_proxy_headers",
                              new=AsyncMock(return_value=None)):
                with patch.object(_real_auth_module, "get_user_from_fusionauth",
                                  new=AsyncMock(return_value=user)):
                    with pytest.raises(fastapi.HTTPException) as exc_info:
                        self._run(get_current_user(req, "tok", db))
                    assert exc_info.value.status_code == 403

    def test_no_auth_raises_401(self):
        import fastapi
        req = _make_request({})
        db = _make_db()

        with patch.object(_real_auth_module, "get_user_from_api_key", return_value=None):
            with patch.object(_real_auth_module, "get_user_from_proxy_headers",
                              new=AsyncMock(return_value=None)):
                with pytest.raises(fastapi.HTTPException) as exc_info:
                    self._run(get_current_user(req, None, db))
                assert exc_info.value.status_code == 401

    def test_auth_error_raises_http_401(self):
        import fastapi
        req = _make_request({})
        db = _make_db()

        with patch.object(_real_auth_module, "get_user_from_api_key", return_value=None):
            with patch.object(_real_auth_module, "get_user_from_proxy_headers",
                              new=AsyncMock(side_effect=AuthError(401, "bad token"))):
                with pytest.raises(fastapi.HTTPException) as exc_info:
                    self._run(get_current_user(req, None, db))
                assert exc_info.value.status_code == 401


# ===========================================================================
# ROLE-BASED ACCESS CONTROL
# ===========================================================================


class TestAdminDependencies:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_get_current_active_user_returns_user(self):
        from ray_compute.api import models as _m
        user = _m.User(user_id="uid-a", email="a@a.com", role="user",
                       is_active=True, is_suspended=False)
        result = self._run(get_current_active_user(user))
        assert result is user

    def test_get_current_admin_user_with_admin(self):
        from ray_compute.api import models as _m
        admin = _m.User(user_id="uid-b", email="b@b.com", role="admin",
                        is_active=True, is_suspended=False)
        result = self._run(get_current_admin_user(admin))
        assert result is admin

    def test_get_current_admin_user_with_non_admin(self):
        import fastapi
        from ray_compute.api import models as _m
        user = _m.User(user_id="uid-c", email="c@c.com", role="user",
                       is_active=True, is_suspended=False)
        with pytest.raises(fastapi.HTTPException) as exc_info:
            self._run(get_current_admin_user(user))
        assert exc_info.value.status_code == 403


class TestRequireRole:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_require_role_allowed(self):
        from ray_compute.api import models as _m

        user = _m.User(user_id="uid-d", email="d@d.com", role="admin",
                       is_active=True, is_suspended=False)

        @require_role("admin", "premium")
        async def _handler(current_user=None):
            return current_user

        result = self._run(_handler(current_user=user))
        assert result is user

    def test_require_role_denied(self):
        import fastapi
        from ray_compute.api import models as _m

        user = _m.User(user_id="uid-e", email="e@e.com", role="viewer",
                       is_active=True, is_suspended=False)

        @require_role("admin", "premium")
        async def _handler(current_user=None):
            return current_user

        with pytest.raises(fastapi.HTTPException) as exc_info:
            self._run(_handler(current_user=user))
        assert exc_info.value.status_code == 403


# ===========================================================================
# LOG AUDIT EVENT
# ===========================================================================


class TestLogAuditEvent:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_log_audit_without_request(self):
        from ray_compute.api import models as _m
        db = MagicMock()
        created = []
        db.add.side_effect = lambda obj: created.append(obj)

        self._run(log_audit_event(
            db, user_id="user-1", action="test_action",
            resource_type="job", resource_id="job-1",
            details="test details", success=True,
        ))
        assert len(created) == 1
        assert isinstance(created[0], _m.AuditLog)
        assert created[0].action == "test_action"

    def test_log_audit_with_request_extracts_ip(self):
        from ray_compute.api import models as _m
        db = MagicMock()
        created = []
        db.add.side_effect = lambda obj: created.append(obj)

        req = _make_request({"user-agent": "TestBrowser/1.0"})
        req.client.host = "10.0.0.1"

        self._run(log_audit_event(
            db, user_id="user-2", action="login",
            request=req, success=True,
        ))
        assert created[0].ip_address == "10.0.0.1"

    def test_log_audit_failure_flag(self):
        from ray_compute.api import models as _m
        db = MagicMock()
        created = []
        db.add.side_effect = lambda obj: created.append(obj)

        self._run(log_audit_event(
            db, user_id="user-3", action="delete",
            success=False,
        ))
        assert created[0].success is False


# ===========================================================================
# AUTH ERROR CLASS
# ===========================================================================


class TestAuthError:
    def test_auth_error_attributes(self):
        err = AuthError(503, "Service unavailable")
        assert err.status_code == 503
        assert err.detail == "Service unavailable"

    def test_auth_error_is_exception(self):
        err = AuthError(401, "Unauthorized")
        assert isinstance(err, Exception)
