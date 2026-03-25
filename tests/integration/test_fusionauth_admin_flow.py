"""FusionAuth admin-flow integration smoke tests.

These tests verify that the FusionAuth + OAuth2-Proxy + role-auth middleware chain
works correctly for admin-protected routes. They require live services and are
intended to run in CI pre-merge environments or locally.

Markers: @pytest.mark.integration, @pytest.mark.security
"""

from __future__ import annotations

import os

import pytest
import requests


BASE_URL = os.getenv("ML_PLATFORM_URL", "http://localhost")
FUSIONAUTH_API_KEY = os.getenv("FUSIONAUTH_API_KEY", "")
TIMEOUT = 10


pytestmark = [pytest.mark.integration, pytest.mark.security]


def _skip_if_unreachable():
    try:
        r = requests.get(f"{BASE_URL}/auth", timeout=TIMEOUT, allow_redirects=False)
        if r.status_code >= 500:
            pytest.skip("FusionAuth not reachable")
    except requests.ConnectionError:
        pytest.skip("Platform not reachable")


class TestFusionAuthAdminProtection:
    """Verify that FusionAuth admin routes redirect unauthenticated users."""

    def test_admin_route_requires_authentication(self):
        _skip_if_unreachable()
        r = requests.get(
            f"{BASE_URL}/admin",
            timeout=TIMEOUT,
            allow_redirects=False,
        )
        assert r.status_code in (302, 401, 403), (
            f"Expected auth redirect/deny for /admin, got {r.status_code}"
        )

    def test_admin_route_redirects_to_oauth_sign_in(self):
        _skip_if_unreachable()
        r = requests.get(
            f"{BASE_URL}/admin",
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        assert any(
            x in r.url
            for x in ("sign_in", "oauth2-proxy", "/auth/oauth2/authorize")
        ), f"Expected OAuth sign-in redirect, got: {r.url}"

    def test_auth_login_page_is_publicly_accessible(self):
        _skip_if_unreachable()
        r = requests.get(
            f"{BASE_URL}/auth",
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        assert r.status_code == 200, (
            f"Expected /auth to be public (200), got {r.status_code}"
        )


class TestFusionAuthAPIProtection:
    """Verify that FusionAuth API endpoints are accessible (for OIDC flows)."""

    def test_well_known_openid_is_accessible(self):
        _skip_if_unreachable()
        r = requests.get(
            f"{BASE_URL}/.well-known/openid-configuration",
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        data = r.json()
        assert "issuer" in data
        assert "authorization_endpoint" in data

    def test_oauth2_token_endpoint_rejects_bad_credentials(self):
        _skip_if_unreachable()
        r = requests.post(
            f"{BASE_URL}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "nonexistent",
                "client_secret": "invalid",
            },
            timeout=TIMEOUT,
        )
        assert r.status_code in (400, 401, 403), (
            f"Expected rejection for bad credentials, got {r.status_code}"
        )


class TestFusionAuthStatusAPI:
    """Verify FusionAuth status endpoint works (if API key available)."""

    def test_api_status_with_key(self):
        _skip_if_unreachable()
        if not FUSIONAUTH_API_KEY:
            pytest.skip("FUSIONAUTH_API_KEY not set")
        r = requests.get(
            f"{BASE_URL}/api/status",
            headers={"Authorization": FUSIONAUTH_API_KEY},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200


class TestTraefikDashboardProtection:
    """Verify Traefik dashboard requires admin auth."""

    def test_traefik_dashboard_requires_authentication(self):
        _skip_if_unreachable()
        r = requests.get(
            f"{BASE_URL}/traefik",
            timeout=TIMEOUT,
            allow_redirects=False,
        )
        assert r.status_code in (302, 401, 403), (
            f"Expected auth redirect/deny for /traefik, got {r.status_code}"
        )
