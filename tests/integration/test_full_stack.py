"""
Full Stack Integration Tests for SFML Platform

Tests all endpoints through Traefik reverse proxy via:
1. LAN (Host IP) - Internal network access
2. External (Tailscale Funnel) - Public HTTPS access

All protected endpoints MUST require authentication (401/403).
Only health endpoints are allowed without auth.

Run:
    ./start_all_dev.sh full-test
    pytest tests/integration/test_full_stack.py -v -s
"""

import pytest
import requests
import os
import time
from typing import Dict, Optional, Tuple


# ============================================================================
# Configuration
# ============================================================================


def get_lan_ip() -> str:
    """Get the host's LAN IP for testing through Traefik"""
    return os.getenv("LAN_IP", "127.0.0.1")


def get_config() -> Dict[str, str]:
    """Test configuration"""
    lan_ip = get_lan_ip()
    domain = os.getenv("PUBLIC_DOMAIN", "localhost")

    return {
        # LAN endpoints (Traefik on host IP)
        "lan_base": f"http://{lan_ip}",
        "mlflow_lan": f"http://{lan_ip}/mlflow",
        "ray_lan": f"http://{lan_ip}/ray",
        "ray_api_lan": f"http://{lan_ip}/api/ray",
        "grafana_lan": f"http://{lan_ip}/grafana",
        "prometheus_lan": f"http://{lan_ip}/prometheus",
        # External endpoints (Tailscale Funnel → Traefik)
        "external_base": f"https://{domain}",
        "mlflow_external": f"https://{domain}/mlflow",
        "ray_external": f"https://{domain}/ray",
        "ray_api_external": f"https://{domain}/api/ray",
        "grafana_external": f"https://{domain}/grafana",
        "prometheus_external": f"https://{domain}/prometheus",
    }


CONFIG = get_config()
TIMEOUT = 10


# ============================================================================
# Helpers
# ============================================================================


def safe_request(
    method: str, url: str, **kwargs
) -> Tuple[Optional[requests.Response], Optional[str]]:
    """Make a request and return (response, error)"""
    kwargs.setdefault("timeout", TIMEOUT)
    kwargs.setdefault(
        "allow_redirects", False
    )  # Don't follow redirects to detect OAuth redirects
    try:
        return requests.request(method, url, **kwargs), None
    except requests.exceptions.ConnectionError as e:
        return None, f"Connection error: {e}"
    except requests.exceptions.Timeout:
        return None, "Timeout"
    except Exception as e:
        return None, str(e)


def check_endpoint(url: str, method: str = "GET", **kwargs) -> Dict:
    """Check an endpoint and return detailed result"""
    start = time.time()
    response, error = safe_request(method, url, **kwargs)
    elapsed = (time.time() - start) * 1000

    result = {
        "url": url,
        "status": None,
        "error": error,
        "ms": round(elapsed, 1),
        "headers": {},
    }

    if response is not None:
        result["status"] = response.status_code
        result["headers"] = dict(response.headers)
        try:
            result["preview"] = response.text[:150]
        except:
            pass

    return result


def is_auth_required(result: Dict) -> bool:
    """Check if response indicates authentication is required"""
    if result["status"] in [401, 403]:
        return True
    # OAuth2 redirect to login
    if result["status"] in [302, 303]:
        location = result["headers"].get("Location", "")
        if "oauth2" in location or "login" in location or "auth" in location:
            return True
    return False


def is_protected(result: Dict) -> bool:
    """Check if endpoint is properly protected (requires auth)"""
    return is_auth_required(result)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def config():
    return CONFIG


# ============================================================================
# Health Endpoints (NO AUTH REQUIRED)
# ============================================================================


class TestHealthEndpoints:
    """Health endpoints should be accessible without authentication"""

    @pytest.mark.lan
    def test_mlflow_health_lan(self, config):
        """MLflow health should be public"""
        result = check_endpoint(f"{config['mlflow_lan']}/health")
        print(f"\n  MLflow Health LAN: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"LAN not reachable: {result['error']}")
        assert result["status"] == 200, f"Health endpoint should return 200: {result}"

    @pytest.mark.external
    def test_mlflow_health_external(self, config):
        """MLflow health via Tailscale"""
        result = check_endpoint(f"{config['mlflow_external']}/health")
        print(f"\n  MLflow Health External: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"Tailscale not reachable: {result['error']}")
        assert result["status"] == 200, f"Health endpoint should return 200: {result}"

    @pytest.mark.lan
    def test_grafana_health_lan(self, config):
        """Grafana API health should be public"""
        result = check_endpoint(f"{config['grafana_lan']}/api/health")
        print(f"\n  Grafana Health LAN: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"LAN not reachable: {result['error']}")
        # Grafana health may require auth when anonymous access is disabled
        assert result["status"] in [200, 401, 403, 302], f"Unexpected status: {result}"

    @pytest.mark.external
    def test_grafana_health_external(self, config):
        """Grafana health via Tailscale"""
        result = check_endpoint(f"{config['grafana_external']}/api/health")
        print(f"\n  Grafana Health External: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"Tailscale not reachable: {result['error']}")
        assert result["status"] in [200, 401, 403, 302], f"Unexpected status: {result}"


# ============================================================================
# Protected Endpoints - MLflow (MUST REQUIRE AUTH)
# ============================================================================


class TestMLflowProtection:
    """MLflow UI and API MUST require authentication"""

    @pytest.mark.lan
    @pytest.mark.security
    def test_mlflow_ui_protected_lan(self, config):
        """MLflow UI must require authentication"""
        result = check_endpoint(config["mlflow_lan"])
        print(f"\n  MLflow UI LAN: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"LAN not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: MLflow UI accessible without auth! Status: {result['status']}"

    @pytest.mark.lan
    @pytest.mark.security
    def test_mlflow_api_protected_lan(self, config):
        """MLflow API must require authentication"""
        result = check_endpoint(
            f"{config['mlflow_lan']}/api/2.0/mlflow/experiments/search"
        )
        print(f"\n  MLflow API LAN: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"LAN not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: MLflow API accessible without auth! Status: {result['status']}"

    @pytest.mark.external
    @pytest.mark.security
    def test_mlflow_ui_protected_external(self, config):
        """MLflow UI must require auth via Tailscale"""
        result = check_endpoint(config["mlflow_external"])
        print(f"\n  MLflow UI External: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"Tailscale not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: MLflow UI accessible without auth externally! Status: {result['status']}"

    @pytest.mark.external
    @pytest.mark.security
    def test_mlflow_api_protected_external(self, config):
        """MLflow API must require auth via Tailscale"""
        result = check_endpoint(
            f"{config['mlflow_external']}/api/2.0/mlflow/experiments/search"
        )
        print(f"\n  MLflow API External: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"Tailscale not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: MLflow API accessible without auth externally! Status: {result['status']}"


# ============================================================================
# Protected Endpoints - Ray (MUST REQUIRE AUTH)
# ============================================================================


class TestRayProtection:
    """Ray Dashboard and API MUST require authentication"""

    @pytest.mark.lan
    @pytest.mark.security
    def test_ray_dashboard_protected_lan(self, config):
        """Ray Dashboard must require authentication"""
        result = check_endpoint(config["ray_lan"])
        print(f"\n  Ray Dashboard LAN: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"LAN not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: Ray Dashboard accessible without auth! Status: {result['status']}"

    @pytest.mark.lan
    @pytest.mark.security
    def test_ray_api_protected_lan(self, config):
        """Ray Compute API must require authentication"""
        result = check_endpoint(f"{config['ray_api_lan']}/health")
        print(f"\n  Ray API LAN: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"LAN not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: Ray API accessible without auth! Status: {result['status']}"

    @pytest.mark.external
    @pytest.mark.security
    def test_ray_dashboard_protected_external(self, config):
        """Ray Dashboard must require auth via Tailscale"""
        result = check_endpoint(config["ray_external"])
        print(f"\n  Ray Dashboard External: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"Tailscale not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: Ray Dashboard accessible without auth externally! Status: {result['status']}"

    @pytest.mark.external
    @pytest.mark.security
    def test_ray_api_protected_external(self, config):
        """Ray API must require auth via Tailscale"""
        result = check_endpoint(f"{config['ray_api_external']}/health")
        print(f"\n  Ray API External: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"Tailscale not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: Ray API accessible without auth externally! Status: {result['status']}"


# ============================================================================
# Protected Endpoints - Grafana (MUST REQUIRE AUTH)
# ============================================================================


class TestGrafanaProtection:
    """Grafana UI and API MUST require authentication"""

    @pytest.mark.lan
    @pytest.mark.security
    def test_grafana_ui_protected_lan(self, config):
        """Grafana UI must require authentication"""
        result = check_endpoint(config["grafana_lan"])
        print(f"\n  Grafana UI LAN: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"LAN not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: Grafana UI accessible without auth! Status: {result['status']}"

    @pytest.mark.lan
    @pytest.mark.security
    def test_grafana_dashboards_protected_lan(self, config):
        """Grafana dashboards API must require authentication"""
        result = check_endpoint(f"{config['grafana_lan']}/api/dashboards/home")
        print(f"\n  Grafana Dashboards LAN: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"LAN not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: Grafana Dashboards accessible without auth! Status: {result['status']}"

    @pytest.mark.external
    @pytest.mark.security
    def test_grafana_ui_protected_external(self, config):
        """Grafana UI must require auth via Tailscale"""
        result = check_endpoint(config["grafana_external"])
        print(f"\n  Grafana UI External: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"Tailscale not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: Grafana UI accessible without auth externally! Status: {result['status']}"


# ============================================================================
# Protected Endpoints - Prometheus (MUST REQUIRE AUTH)
# ============================================================================


class TestPrometheusProtection:
    """Prometheus MUST require authentication"""

    @pytest.mark.lan
    @pytest.mark.security
    def test_prometheus_protected_lan(self, config):
        """Prometheus must require authentication"""
        result = check_endpoint(config["prometheus_lan"])
        print(f"\n  Prometheus LAN: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"LAN not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: Prometheus accessible without auth! Status: {result['status']}"

    @pytest.mark.external
    @pytest.mark.security
    def test_prometheus_protected_external(self, config):
        """Prometheus must require auth via Tailscale"""
        result = check_endpoint(config["prometheus_external"])
        print(f"\n  Prometheus External: {result['status']} ({result['ms']}ms)")

        if result["error"]:
            pytest.skip(f"Tailscale not reachable: {result['error']}")

        assert is_protected(
            result
        ), f"SECURITY VIOLATION: Prometheus accessible without auth externally! Status: {result['status']}"


# ============================================================================
# Security Audit Summary
# ============================================================================


class TestSecurityAudit:
    """Generate a comprehensive security audit report"""

    @pytest.mark.security
    def test_security_audit_report(self, config):
        """Generate security audit of all external endpoints"""
        endpoints = [
            ("MLflow Health", f"{config['mlflow_external']}/health", False),
            ("MLflow UI", config["mlflow_external"], True),
            (
                "MLflow API",
                f"{config['mlflow_external']}/api/2.0/mlflow/experiments/search",
                True,
            ),
            ("Ray Dashboard", config["ray_external"], True),
            ("Ray API", f"{config['ray_api_external']}/health", True),
            ("Grafana UI", config["grafana_external"], True),
            ("Grafana Health", f"{config['grafana_external']}/api/health", False),
            ("Prometheus", config["prometheus_external"], True),
        ]

        print("\n" + "=" * 70)
        print("EXTERNAL ENDPOINT SECURITY AUDIT")
        print("=" * 70)

        violations = []
        for name, url, should_be_protected in endpoints:
            result = check_endpoint(url)
            protected = is_protected(result)

            if should_be_protected:
                if protected:
                    status = "✓ PROTECTED"
                else:
                    status = "✗ VIOLATION - OPEN!"
                    violations.append(name)
            else:
                if result["status"] == 200:
                    status = "✓ PUBLIC (expected)"
                elif protected:
                    status = "⚠ PROTECTED (health endpoint)"
                else:
                    status = f"? Status {result['status']}"

            print(f"\n  {name}: {status}")
            print(f"    URL: {url}")
            print(f"    HTTP Status: {result['status']}")

        print("\n" + "=" * 70)

        if violations:
            print(f"\n  ✗ SECURITY VIOLATIONS FOUND: {', '.join(violations)}")
            print("     These endpoints are accessible without authentication!")
            pytest.fail(f"Security violations: {violations}")
        else:
            print("\n  ✓ All protected endpoints require authentication")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short", "-m", "security"])
