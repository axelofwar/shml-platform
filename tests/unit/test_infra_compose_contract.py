"""Regression tests for shared infrastructure compose contracts.

These tests parse the real infra compose file and validate security- and
routing-critical invariants for Traefik and FusionAuth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
INFRA_COMPOSE = REPO_ROOT / "deploy" / "compose" / "docker-compose.infra.yml"


def _load_compose() -> dict[str, Any]:
    with open(INFRA_COMPOSE, encoding="utf-8") as handle:
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


class TestInfraComposeStructure:
    def test_compose_file_exists(self):
        assert INFRA_COMPOSE.exists()

    def test_critical_services_exist(self, services: dict[str, Any]):
        for service_name in ["traefik", "fusionauth", "oauth2-proxy", "postgres", "redis"]:
            assert service_name in services

    def test_platform_network_exists(self, compose: dict[str, Any]):
        assert "platform" in compose.get("networks", {})


class TestTraefikContract:
    def test_dashboard_port_is_localhost_only(self, services: dict[str, Any]):
        ports = services["traefik"]["ports"]

        assert "127.0.0.1:8090:8080" in ports

    def test_dashboard_router_requires_admin_auth(self, services: dict[str, Any]):
        labels = _label_dict(services["traefik"])

        assert labels["traefik.http.routers.traefik.rule"] == "PathPrefix(`/traefik`)"
        assert labels["traefik.http.services.traefik.loadbalancer.server.port"] == "8080"
        assert labels["traefik.http.routers.traefik.middlewares"] == "oauth2-errors,oauth2-auth,role-auth-admin"


class TestFusionAuthContract:
    def test_admin_port_is_localhost_only(self, services: dict[str, Any]):
        ports = services["fusionauth"]["ports"]

        assert ports == ["127.0.0.1:9011:9011"]

    def test_auth_router_labels_are_present(self, services: dict[str, Any]):
        labels = _label_dict(services["fusionauth"])

        assert labels["traefik.http.routers.fusionauth.rule"] == "PathPrefix(`/auth`)"
        assert labels["traefik.http.middlewares.fusionauth-rewrite.replacepathregex.regex"] == "^/auth(.*)"
        assert labels["traefik.http.middlewares.fusionauth-rewrite.replacepathregex.replacement"] == "$$1"
        assert labels["traefik.http.services.fusionauth.loadbalancer.server.port"] == "9011"

    def test_admin_router_requires_platform_admin(self, services: dict[str, Any]):
        labels = _label_dict(services["fusionauth"])

        assert labels["traefik.http.routers.fusionauth-admin.rule"] == "PathPrefix(`/admin`)"
        assert labels["traefik.http.routers.fusionauth-admin.middlewares"] == (
            "oauth2-errors,oauth2-auth,role-auth-admin,fusionauth-headers"
        )
        assert labels["traefik.http.routers.fusionauth-admin.service"] == "fusionauth"

    def test_api_and_oauth_routes_are_explicitly_declared(self, services: dict[str, Any]):
        labels = _label_dict(services["fusionauth"])

        assert labels["traefik.http.routers.fusionauth-api.rule"] == "PathPrefix(`/api`)"
        assert labels["traefik.http.routers.fusionauth-oauth.rule"] == "PathPrefix(`/oauth2`)"
        assert labels["traefik.http.routers.fusionauth-well-known.rule"] == "PathPrefix(`/.well-known`)"
        assert labels["traefik.http.routers.fusionauth-registration.rule"] == "PathPrefix(`/registration`)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
