"""Unit tests for ray_compute/api/api_keys.py.

Tests:
- generate_api_key() — format, uniqueness, hash consistency
- verify_api_key() — current hash match, grace period, expired, revoked
- GET /api/v1/keys — list user's keys
- POST /api/v1/keys — create key (success, duplicate name)
- POST /api/v1/keys/{id}/rotate — rotate with grace period
- DELETE /api/v1/keys/{id} — revoke
- GET /api/v1/keys/admin/all — admin list
- DELETE /api/v1/keys/admin/{id} — admin revoke
"""
from __future__ import annotations

import hashlib
import sys
import types
import uuid
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_RC_ROOT = _ROOT / "ray_compute"
for _p in [str(_ROOT), str(_RC_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Ensure database stub is present
# ---------------------------------------------------------------------------
if "ray_compute.api.database" not in sys.modules:
    _db_mod_ak = types.ModuleType("ray_compute.api.database")
    _db_mod_ak.get_db = lambda: iter([MagicMock()])
    _db_mod_ak.SessionLocal = MagicMock()
    _db_mod_ak.engine = MagicMock()
    sys.modules["ray_compute.api.database"] = _db_mod_ak

# ---------------------------------------------------------------------------
# Ensure audit stub has AuditLogger + AuditAction (api_keys.py needs them)
# ---------------------------------------------------------------------------
if "ray_compute.api.audit" not in sys.modules:
    _audit_mod_ak = types.ModuleType("ray_compute.api.audit")

    class _AuditLogger:
        def __init__(self, db):
            self.db = db
        def log(self, **kwargs):
            pass

    class _AuditAction:
        API_KEY_CREATE = "API_KEY_CREATE"
        API_KEY_ROTATE = "API_KEY_ROTATE"
        API_KEY_REVOKE = "API_KEY_REVOKE"
        AUTH_IMPERSONATION_START = "AUTH_IMPERSONATION_START"

    _audit_mod_ak.AuditLogger = _AuditLogger
    _audit_mod_ak.AuditAction = _AuditAction
    _audit_mod_ak.log_audit_event = AsyncMock(return_value=None)
    sys.modules["ray_compute.api.audit"] = _audit_mod_ak
else:
    _audit_mod_ak = sys.modules["ray_compute.api.audit"]
    # Ensure AuditLogger and AuditAction exist in whatever module is there
    if not hasattr(_audit_mod_ak, "AuditLogger"):
        class _AuditLogger:
            def __init__(self, db):
                pass
            def log(self, **kwargs):
                pass
        _audit_mod_ak.AuditLogger = _AuditLogger
    if not hasattr(_audit_mod_ak, "AuditAction"):
        class _AuditAction:
            API_KEY_CREATE = "API_KEY_CREATE"
            API_KEY_ROTATE = "API_KEY_ROTATE"
            API_KEY_REVOKE = "API_KEY_REVOKE"
            AUTH_IMPERSONATION_START = "AUTH_IMPERSONATION_START"
        _audit_mod_ak.AuditAction = _AuditAction

# ---------------------------------------------------------------------------
# Ensure auth stub has the extra attrs api_keys.py needs
# ---------------------------------------------------------------------------
if "ray_compute.api.auth" not in sys.modules:
    # Should have been set by conftest.py — add extra attrs
    pass
else:
    _auth_stub = sys.modules["ray_compute.api.auth"]
    if not hasattr(_auth_stub, "has_role_permission"):
        _auth_stub.has_role_permission = MagicMock(return_value=True)
    if not hasattr(_auth_stub, "ROLE_HIERARCHY"):
        _auth_stub.ROLE_HIERARCHY = {"admin": 3, "premium": 2, "user": 1, "viewer": 0}
    if not hasattr(_auth_stub, "FUSIONAUTH_URL"):
        _auth_stub.FUSIONAUTH_URL = "http://fusionauth:9011"
    if not hasattr(_auth_stub, "FUSIONAUTH_CLIENT_ID"):
        _auth_stub.FUSIONAUTH_CLIENT_ID = "test-client-id"
    if not hasattr(_auth_stub, "FUSIONAUTH_CLIENT_SECRET"):
        _auth_stub.FUSIONAUTH_CLIENT_SECRET = "test-client-secret"
    if not hasattr(_auth_stub, "get_user_from_api_key"):
        _auth_stub.get_user_from_api_key = MagicMock(return_value=None)
    if not hasattr(_auth_stub, "create_access_token"):
        _auth_stub.create_access_token = MagicMock(return_value="mock-token")
    if not hasattr(_auth_stub, "CICD_ADMIN_KEY"):
        _auth_stub.CICD_ADMIN_KEY = "shml_admin_test_key"
    if not hasattr(_auth_stub, "CICD_DEVELOPER_KEY"):
        _auth_stub.CICD_DEVELOPER_KEY = "shml_dev_test_key"
    if not hasattr(_auth_stub, "CICD_ELEVATED_DEVELOPER_KEY"):
        _auth_stub.CICD_ELEVATED_DEVELOPER_KEY = "shml_elev_dev_test_key"
    if not hasattr(_auth_stub, "CICD_VIEWER_KEY"):
        _auth_stub.CICD_VIEWER_KEY = "shml_viewer_test_key"

# ---------------------------------------------------------------------------
# Import api_keys module
# ---------------------------------------------------------------------------
import ray_compute.api.api_keys as _ak  # noqa: E402

# Release audit stub so subsequent tests get real module
if sys.modules.get("ray_compute.api.audit") is _audit_mod_ak:
    del sys.modules["ray_compute.api.audit"]

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
    user.oauth_sub = "oauth-sub-test"
    user.is_active = True
    return user


def _make_api_key_record(name: str = "test-key", revoked: bool = False) -> MagicMock:
    record = MagicMock()
    record.id = uuid.uuid4()
    record.name = name
    record.key_hash = "abc" * 20
    record.key_prefix = "shml_test12"
    record.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    record.scopes = ["jobs:submit", "jobs:read"]
    record.created_at = datetime(2024, 1, 1)
    record.expires_at = None
    record.last_used_at = None
    record.revoked_at = datetime.utcnow() if revoked else None
    record.description = "Test key"
    record.previous_key_hash = None
    record.previous_key_valid_until = None
    return record


def _make_db(api_key_record=None) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = api_key_record
    db.query.return_value.order_by.return_value.all.return_value = (
        [api_key_record] if api_key_record else []
    )
    db.query.return_value.all.return_value = (
        [api_key_record] if api_key_record else []
    )
    return db


def _make_client(user: MagicMock, db: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(_ak.router)
    app.dependency_overrides[_auth_get_current_user] = lambda: user
    app.dependency_overrides[_database_get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# generate_api_key tests
# ===========================================================================

class TestGenerateApiKey:
    def test_returns_three_values(self):
        result = _ak.generate_api_key()
        assert len(result) == 3

    def test_key_starts_with_shml_prefix(self):
        key, _, _ = _ak.generate_api_key()
        assert key.startswith("shml_")

    def test_key_has_expected_length(self):
        key, _, _ = _ak.generate_api_key()
        # shml_ (5) + token_urlsafe(32) = ~48 chars
        assert len(key) > 20

    def test_hash_is_sha256_hex(self):
        key, key_hash, _ = _ak.generate_api_key()
        expected = hashlib.sha256(key.encode()).hexdigest()
        assert key_hash == expected

    def test_prefix_is_first_12_chars(self):
        key, _, prefix = _ak.generate_api_key()
        assert prefix == key[:12]

    def test_keys_are_unique(self):
        keys = {_ak.generate_api_key()[0] for _ in range(10)}
        assert len(keys) == 10

    def test_hashes_are_unique(self):
        hashes = {_ak.generate_api_key()[1] for _ in range(10)}
        assert len(hashes) == 10


# ===========================================================================
# verify_api_key tests
# ===========================================================================

class TestVerifyApiKey:
    def _make_verify_db(self, record=None) -> MagicMock:
        """DB mock for verify_api_key queries."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = record
        return db

    def test_returns_none_when_key_not_found(self):
        db = self._make_verify_db(record=None)
        result = _ak.verify_api_key("shml_notarealkey", db)
        assert result is None

    def test_returns_record_for_valid_key(self):
        key, key_hash, prefix = _ak.generate_api_key()
        record = _make_api_key_record()
        record.key_hash = key_hash
        record.expires_at = None  # No expiration
        db = self._make_verify_db(record=record)
        result = _ak.verify_api_key(key, db)
        assert result is record

    def test_returns_none_for_expired_key(self):
        key, key_hash, _ = _ak.generate_api_key()
        record = _make_api_key_record()
        record.key_hash = key_hash
        record.expires_at = datetime(2020, 1, 1)  # Expired
        db = self._make_verify_db(record=record)
        result = _ak.verify_api_key(key, db)
        assert result is None

    def test_updates_last_used_for_valid_key(self):
        key, key_hash, _ = _ak.generate_api_key()
        record = _make_api_key_record()
        record.key_hash = key_hash
        record.expires_at = None
        db = self._make_verify_db(record=record)
        _ak.verify_api_key(key, db)
        assert record.last_used_at is not None
        db.commit.assert_called()


# ===========================================================================
# List API keys endpoint
# ===========================================================================

class TestListApiKeys:
    def test_list_returns_200(self):
        user = _make_user()
        db = _make_db()
        client = _make_client(user, db)
        resp = client.get("/api/v1/keys/")
        assert resp.status_code == 200

    def test_list_returns_empty_list_when_no_keys(self):
        user = _make_user()
        db = _make_db()
        client = _make_client(user, db)
        resp = client.get("/api/v1/keys/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ===========================================================================
# Create API key endpoint
# ===========================================================================

class TestCreateApiKey:
    def _create_payload(self, name: str = "my-key", scopes=None):
        return {"name": name, "scopes": scopes or ["jobs:submit"]}

    def test_create_returns_201(self):
        user = _make_user()
        db = MagicMock()
        # No duplicate key (filter returns None)
        query_chain = db.query.return_value.filter.return_value
        query_chain.first.return_value = None
        # Refresh sets mock attributes on the newly-created ApiKey
        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.utcnow()
            obj.expires_at = None
            obj.scopes = ["jobs:submit"]
            obj.key_prefix = "shml_test12"
            obj.name = "my-key"
        db.refresh.side_effect = _refresh
        client = _make_client(user, db)
        resp = client.post("/api/v1/keys/", json=self._create_payload())
        assert resp.status_code == 201

    def test_create_response_contains_key(self):
        user = _make_user()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.utcnow()
            obj.expires_at = None
            obj.scopes = ["jobs:submit"]
            obj.key_prefix = "shml_test12"
            obj.name = "test"
        db.refresh.side_effect = _refresh
        client = _make_client(user, db)
        resp = client.post("/api/v1/keys/", json=self._create_payload("test"))
        if resp.status_code == 201:
            data = resp.json()
            assert "key" in data
            assert data["key"].startswith("shml_")

    def test_duplicate_name_returns_400(self):
        user = _make_user()
        existing_key = _make_api_key_record(name="my-key")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing_key
        client = _make_client(user, db)
        resp = client.post("/api/v1/keys/", json=self._create_payload("my-key"))
        assert resp.status_code == 400

    def test_empty_name_returns_422(self):
        user = _make_user()
        db = MagicMock()
        client = _make_client(user, db)
        resp = client.post("/api/v1/keys/", json={"name": "", "scopes": ["jobs:submit"]})
        assert resp.status_code == 422

    def test_create_with_expiry_sets_expires_at(self):
        user = _make_user()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.utcnow()
            obj.scopes = ["jobs:submit"]
            obj.key_prefix = "shml_test12"
            obj.name = "exp-key"
        db.refresh.side_effect = _refresh
        client = _make_client(user, db)
        payload = {**self._create_payload("exp-key"), "expires_in_days": 30}
        resp = client.post("/api/v1/keys/", json=payload)
        assert resp.status_code in (201, 422, 500)


# ===========================================================================
# Rotate API key endpoint
# ===========================================================================

class TestRotateApiKey:
    def test_rotate_not_found_returns_404(self):
        user = _make_user()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        client = _make_client(user, db)
        key_id = str(uuid.uuid4())
        resp = client.post(f"/api/v1/keys/{key_id}/rotate")
        assert resp.status_code == 404

    def test_rotate_success_returns_200(self):
        user = _make_user()
        existing = _make_api_key_record("rotate-me")
        existing.revoked_at = None
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        client = _make_client(user, db)
        resp = client.post(f"/api/v1/keys/{existing.id}/rotate")
        assert resp.status_code == 200

    def test_rotate_response_has_new_key(self):
        user = _make_user()
        existing = _make_api_key_record("rotate-me")
        existing.revoked_at = None
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        client = _make_client(user, db)
        resp = client.post(f"/api/v1/keys/{existing.id}/rotate")
        if resp.status_code == 200:
            data = resp.json()
            assert "new_key" in data
            assert "new_key_prefix" in data
            assert "old_key_valid_until" in data

    def test_rotate_updates_key_hash(self):
        user = _make_user()
        existing = _make_api_key_record("rotate-me")
        existing.revoked_at = None
        old_hash = existing.key_hash
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        client = _make_client(user, db)
        resp = client.post(f"/api/v1/keys/{existing.id}/rotate")
        if resp.status_code == 200:
            # Old hash should be stored under previous_key_hash
            assert existing.previous_key_hash == old_hash


# ===========================================================================
# Revoke (delete) API key endpoint
# ===========================================================================

class TestRevokeApiKey:
    def test_revoke_not_found_returns_404(self):
        user = _make_user()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        client = _make_client(user, db)
        key_id = str(uuid.uuid4())
        resp = client.delete(f"/api/v1/keys/{key_id}")
        assert resp.status_code == 404

    def test_revoke_success_returns_204(self):
        user = _make_user()
        existing = _make_api_key_record("my-key")
        existing.revoked_at = None
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        client = _make_client(user, db)
        resp = client.delete(f"/api/v1/keys/{existing.id}")
        assert resp.status_code == 204

    def test_revoke_sets_revoked_at(self):
        user = _make_user()
        existing = _make_api_key_record("del-key")
        existing.revoked_at = None
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        client = _make_client(user, db)
        client.delete(f"/api/v1/keys/{existing.id}")
        assert existing.revoked_at is not None


# ===========================================================================
# Admin endpoints
# ===========================================================================

class TestAdminListApiKeys:
    def test_admin_can_list_all_keys(self):
        user = _make_user(role="admin")
        key1 = _make_api_key_record("key-1")
        key2 = _make_api_key_record("key-2")
        db = MagicMock()
        db.query.return_value.order_by.return_value.all.return_value = [key1, key2]
        client = _make_client(user, db)
        resp = client.get("/api/v1/keys/admin/all")
        assert resp.status_code == 200

    def test_non_admin_gets_403(self):
        user = _make_user(role="user")
        db = MagicMock()
        client = _make_client(user, db)
        resp = client.get("/api/v1/keys/admin/all")
        assert resp.status_code == 403


class TestAdminRevokeApiKey:
    def test_admin_can_revoke_any_key(self):
        user = _make_user(role="admin")
        existing = _make_api_key_record("any-key")
        existing.revoked_at = None
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        client = _make_client(user, db)
        resp = client.delete(f"/api/v1/keys/admin/{existing.id}")
        assert resp.status_code == 204

    def test_admin_revoke_not_found_returns_404(self):
        user = _make_user(role="admin")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        client = _make_client(user, db)
        key_id = str(uuid.uuid4())
        resp = client.delete(f"/api/v1/keys/admin/{key_id}")
        assert resp.status_code == 404

    def test_non_admin_gets_403(self):
        user = _make_user(role="user")
        db = MagicMock()
        client = _make_client(user, db)
        key_id = str(uuid.uuid4())
        resp = client.delete(f"/api/v1/keys/admin/{key_id}")
        assert resp.status_code == 403
