from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


_CHAT_API = Path(__file__).parent.parent.parent.parent / "inference" / "chat-api"
if str(_CHAT_API) not in sys.path:
    sys.path.insert(0, str(_CHAT_API))


from app.auth import get_current_user, require_admin, require_developer_or_admin, require_role
from app.schemas import User, UserRole


class DummyRequest:
    def __init__(self):
        self.headers = {}


@pytest.mark.asyncio
async def test_get_current_user_api_key_success():
    user = User(id="u1", email="u1@test.local", role=UserRole.ADMIN, groups=[], auth_method="api_key")
    with patch("app.auth.db.validate_api_key", AsyncMock(return_value=user)):
        result = await get_current_user(
            request=DummyRequest(),
            authorization=HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret"),
        )
    assert result.id == "u1"
    assert result.role == UserRole.ADMIN


@pytest.mark.asyncio
async def test_get_current_user_api_key_invalid_raises_401():
    with patch("app.auth.db.validate_api_key", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=DummyRequest(),
                authorization=HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad"),
            )
    assert exc_info.value.status_code == 401
    # Starlette HTTPException doesn't pass detail to Exception.__init__, so
    # pytest.raises(match=...) won't work — assert on .detail directly.
    assert exc_info.value.detail == "Invalid or expired API key"


@pytest.mark.asyncio
async def test_get_current_user_oauth_headers_map_roles():
    admin = await get_current_user(
        request=DummyRequest(),
        authorization=None,
        x_auth_request_user="admin-1",
        x_auth_request_email="admin@test.local",
        x_auth_request_groups="administrators,developers",
        x_forwarded_user=None,
    )
    developer = await get_current_user(
        request=DummyRequest(),
        authorization=None,
        x_auth_request_user="dev-1",
        x_auth_request_email="dev@test.local",
        x_auth_request_groups="developers",
        x_forwarded_user=None,
    )
    viewer = await get_current_user(
        request=DummyRequest(),
        authorization=None,
        x_auth_request_user=None,
        x_auth_request_email=None,
        x_auth_request_groups=None,
        x_forwarded_user="viewer-1",
    )

    assert admin.role == UserRole.ADMIN
    assert developer.role == UserRole.DEVELOPER
    assert viewer.role == UserRole.VIEWER


@pytest.mark.asyncio
async def test_get_current_user_requires_auth_when_missing():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(
            request=DummyRequest(),
            authorization=None,
            x_auth_request_user=None,
            x_auth_request_email=None,
            x_auth_request_groups=None,
            x_forwarded_user=None,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Authentication required"


@pytest.mark.asyncio
async def test_require_role_and_admin_helpers():
    admin_user = User(id="a1", email="a@test.local", role=UserRole.ADMIN, groups=[], auth_method="oauth")
    dev_user = User(id="d1", email="d@test.local", role=UserRole.DEVELOPER, groups=[], auth_method="oauth")
    viewer_user = User(id="v1", email="v@test.local", role=UserRole.VIEWER, groups=[], auth_method="oauth")

    checker = await require_role(UserRole.ADMIN, UserRole.DEVELOPER)
    assert await checker(admin_user) is admin_user
    assert await checker(dev_user) is dev_user

    with pytest.raises(HTTPException) as exc_info:
        await checker(viewer_user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"

    assert require_admin(admin_user) is admin_user
    assert require_developer_or_admin(admin_user) is admin_user
    assert require_developer_or_admin(dev_user) is dev_user

    with pytest.raises(HTTPException) as exc_info:
        require_admin(dev_user)
    assert exc_info.value.detail == "Admin access required"

    with pytest.raises(HTTPException) as exc_info:
        require_developer_or_admin(viewer_user)
    assert exc_info.value.detail == "Developer or admin access required"
