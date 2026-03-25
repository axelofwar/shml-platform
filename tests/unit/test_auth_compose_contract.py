"""Regression tests for the auth layer compose contract.

These tests parse deploy/compose/docker-compose.auth.yml and validate
security-critical invariants for FusionAuth, OAuth2-Proxy, and role-auth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
AUTH_COMPOSE = REPO_ROOT / "deploy" / "compose" / "docker-compose.auth.yml"


def _load_compose() -> dict[str, Any]:
    with open(AUTH_COMPOSE, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _label_dict(service: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in service.get("labels", []):
        key, value = item.split("=", 1)
        result[key] = value
    return result


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return _load_compose()


@pytest.fixture(scope="module")
def services(compose: dict[str, Any]) -> dict[str, Any]:
    return compose["services"]


class TestAuthComposeStructure:
    def test_compose_file_exists(self):
        assert AUTH_COMPOSE.exists()

    def test_critical_services_exist(self, services: dict[str, Any]):
        for name in ["fusionauth", "oauth2-proxy", "role-auth"]:
            assert name in services, f"Missing critical auth service: {name}"


class TestFusionAuthContract:
    def test_admin_port_is_localhost_only(self, services: dict[str, Any]):
        ports = services["fusionauth"]["ports"]
        assert "127.0.0.1:9011:9011" in ports

    def test_auth_router_is_public(self, services: dict[str, Any]):
        labels = _label_dict(services["fusionauth"])
        assert labels["traefik.http.routers.fusionauth.rule"] == "PathPrefix(`/auth`)"
        assert "fusionauth-headers" in labels["traefik.http.routers.fusionauth.middlewares"]
        assert "fusionauth-rewrite" in labels["traefik.http.routers.fusionauth.middlewares"]

    def test_admin_router_requires_full_auth_chain(self, services: dict[str, Any]):
        labels = _label_dict(services["fusionauth"])
        mw = labels["traefik.http.routers.fusionauth-admin.middlewares"]
        assert "oauth2-errors" in mw
        assert "oauth2-auth" in mw
        assert "role-auth-admin" in mw
        assert "fusionauth-headers" in mw

    def test_admin_router_targets_fusionauth_service(self, services: dict[str, Any]):
        labels = _label_dict(services["fusionauth"])
        assert labels["traefik.http.routers.fusionauth-admin.service"] == "fusionauth"

    def test_api_and_oauth_routes_exist(self, services: dict[str, Any]):
        labels = _label_dict(services["fusionauth"])
        assert labels["traefik.http.routers.fusionauth-api.rule"] == "PathPrefix(`/api`)"
        assert labels["traefik.http.routers.fusionauth-oauth.rule"] == "PathPrefix(`/oauth2`)"
        assert labels["traefik.http.routers.fusionauth-well-known.rule"] == "PathPrefix(`/.well-known`)"
        assert labels["traefik.http.routers.fusionauth-registration.rule"] == "PathPrefix(`/registration`)"

    def test_rewrite_middleware_strips_auth_prefix(self, services: dict[str, Any]):
        labels = _label_dict(services["fusionauth"])
        assert labels["traefik.http.middlewares.fusionauth-rewrite.replacepathregex.regex"] == "^/auth(.*)"
        assert labels["traefik.http.middlewares.fusionauth-rewrite.replacepathregex.replacement"] == "$$1"

    def test_loadbalancer_port_matches_admin_port(self, services: dict[str, Any]):
        labels = _label_dict(services["fusionauth"])
        assert labels["traefik.http.services.fusionauth.loadbalancer.server.port"] == "9011"

    def test_depends_on_nothing_external(self, services: dict[str, Any]):
        fa = services["fusionauth"]
        assert "depends_on" not in fa or isinstance(fa.get("depends_on"), dict)

    def test_healthcheck_uses_api_status(self, services: dict[str, Any]):
        hc = services["fusionauth"]["healthcheck"]
        assert "http://localhost:9011/api/status" in " ".join(hc["test"])


class TestOAuth2ProxyContract:
    def test_forward_auth_middleware_defined(self, services: dict[str, Any]):
        labels = _label_dict(services["oauth2-proxy"])
        assert "traefik.http.middlewares.oauth2-auth.forwardauth.address" in labels
        assert "oauth2-proxy:4180" in labels["traefik.http.middlewares.oauth2-auth.forwardauth.address"]

    def test_forward_auth_trusts_headers(self, services: dict[str, Any]):
        labels = _label_dict(services["oauth2-proxy"])
        assert labels["traefik.http.middlewares.oauth2-auth.forwardauth.trustForwardHeader"] == "true"

    def test_error_middleware_redirects_to_sign_in(self, services: dict[str, Any]):
        labels = _label_dict(services["oauth2-proxy"])
        assert labels["traefik.http.middlewares.oauth2-errors.errors.status"] == "401"
        assert "sign_in" in labels["traefik.http.middlewares.oauth2-errors.errors.query"]

    def test_rbac_middlewares_defined(self, services: dict[str, Any]):
        labels = _label_dict(services["oauth2-proxy"])
        for role in ["developer", "elevated", "admin"]:
            key = f"traefik.http.middlewares.role-auth-{role}.forwardauth.address"
            assert key in labels, f"Missing RBAC middleware for role: {role}"
            assert f"role-auth:8080/auth/{role}" in labels[key] or \
                   f"role-auth:8080/auth/elevated-developer" in labels[key]

    def test_proxy_depends_on_fusionauth_healthy(self, services: dict[str, Any]):
        deps = services["oauth2-proxy"]["depends_on"]
        assert deps["fusionauth"]["condition"] == "service_healthy"

    def test_session_uses_redis(self, services: dict[str, Any]):
        env = services["oauth2-proxy"].get("environment", {})
        assert env.get("OAUTH2_PROXY_SESSION_STORE_TYPE") == "redis"

    def test_proxy_router_priority_is_high(self, services: dict[str, Any]):
        labels = _label_dict(services["oauth2-proxy"])
        priority = int(labels["traefik.http.routers.oauth2-proxy.priority"])
        assert priority >= 300


class TestRoleAuthContract:
    def test_role_auth_exists_and_has_healthcheck(self, services: dict[str, Any]):
        ra = services["role-auth"]
        assert "healthcheck" in ra

    def test_role_auth_on_platform_network(self, services: dict[str, Any]):
        networks = services["role-auth"]["networks"]
        assert "platform" in networks


class TestSharedSecurityInvariants:
    def test_admin_routes_always_require_oauth_and_role_check(self, services: dict[str, Any]):
        """The FusionAuth admin route and Traefik dashboard must both require
        the full auth chain: oauth2-errors, oauth2-auth, role-auth-admin."""
        labels = _label_dict(services["fusionauth"])
        admin_mw = labels["traefik.http.routers.fusionauth-admin.middlewares"]
        for required in ["oauth2-errors", "oauth2-auth", "role-auth-admin"]:
            assert required in admin_mw, f"FusionAuth admin missing {required}"

    def test_public_auth_route_has_no_oauth_middleware(self, services: dict[str, Any]):
        """The /auth route must be publicly accessible (login page)."""
        labels = _label_dict(services["fusionauth"])
        auth_mw = labels["traefik.http.routers.fusionauth.middlewares"]
        assert "oauth2-auth" not in auth_mw


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
