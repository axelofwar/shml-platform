"""
Tests to validate current usage patterns before implementing Copilot suggestions.

These tests document and validate the current behavior so we can safely
make improvements without breaking existing functionality.

Copilot Suggestions Being Evaluated:
1. server_v2.py: Unused import 'get_current_admin_user'
2. entrypoint.sh: --disable-security-middleware security concern
3. tailscale-funnel.service: Public exposure without auth

Run from test container:
    ./tests/run_tests_container.sh unit -k "copilot"

Or with docker compose directly:
    docker compose -f tests/docker/docker-compose.test.yml run --rm test \
        /workspace/tests/unit/test_copilot_suggestions.py -v -s
"""

import pytest
import ast
import os
import re
from pathlib import Path
from unittest.mock import patch, MagicMock


def get_project_root():
    """Get project root - works in test container, ray container, or on host"""
    # Test container mounts to /workspace
    if Path("/workspace").exists() and Path("/workspace/ray_compute").exists():
        return Path("/workspace")
    # Ray container has /app
    if Path("/app").exists() and Path("/app/ray_compute").exists():
        return Path("/app")
    # Fall back to relative path from test file
    return Path(__file__).parent.parent.parent


# ============================================================================
# Test 1: Validate server_v2.py import usage
# Copilot flags 'get_current_admin_user' as unused
# ============================================================================


class TestServerV2Imports:
    """Test that validates import usage in server_v2.py"""

    @pytest.fixture
    def server_v2_path(self):
        """Path to server_v2.py"""
        return get_project_root() / "ray_compute" / "api" / "server_v2.py"

    @pytest.fixture
    def server_v2_source(self, server_v2_path):
        """Load server_v2.py source code"""
        with open(server_v2_path, "r") as f:
            return f.read()

    @pytest.fixture
    def server_v2_ast(self, server_v2_source):
        """Parse server_v2.py AST"""
        return ast.parse(server_v2_source)

    def test_auth_imports_exist(self, server_v2_source):
        """Verify the auth imports exist as expected"""
        # NOTE: get_current_admin_user was removed as unused (PR #7 fix)
        expected_imports = [
            "get_current_user",
            "log_audit_event",
            "can_submit_jobs",
            "PUBLIC_AUTH_URL",
            "ADMIN_CONTACT",
        ]
        for imp in expected_imports:
            assert imp in server_v2_source, f"Expected import '{imp}' not found"

    def test_get_current_user_is_used(self, server_v2_source):
        """Verify get_current_user is actively used (not just imported)"""
        # Should be used in Depends() calls
        usage_pattern = r"Depends\s*\(\s*get_current_user\s*\)"
        matches = re.findall(usage_pattern, server_v2_source)
        assert len(matches) > 0, "get_current_user should be used in Depends()"
        # Count actual usages
        print(f"get_current_user is used {len(matches)} times in Depends()")

    def test_get_current_admin_user_removed(self, server_v2_source):
        """
        Verify get_current_admin_user is NOT imported (unused import removed).

        Previously this import was flagged by Copilot as unused.
        As part of PR #7 fixes, this unused import was removed.
        This test verifies the cleanup was done correctly.
        """
        # get_current_admin_user should NOT be in imports anymore
        assert (
            "get_current_admin_user" not in server_v2_source
        ), "get_current_admin_user should have been removed as unused import"

    def test_can_submit_jobs_is_used(self, server_v2_source):
        """Verify can_submit_jobs is used for authorization"""
        assert "can_submit_jobs(" in server_v2_source, "can_submit_jobs should be used"
        # Count usages
        matches = re.findall(r"can_submit_jobs\s*\(", server_v2_source)
        print(f"can_submit_jobs is used {len(matches)} times")
        assert (
            len(matches) >= 2
        ), "Should be used in submit_job and cancel_job endpoints"

    def test_admin_role_check_exists(self, server_v2_source):
        """Verify admin role checks exist even without get_current_admin_user"""
        # The code does manual admin checks like: current_user.role != "admin"
        admin_checks = re.findall(
            r'current_user\.role\s*[!=]=\s*["\']admin["\']', server_v2_source
        )
        print(f"Found {len(admin_checks)} manual admin role checks")
        assert len(admin_checks) > 0, "Should have admin role checks for authorization"


# ============================================================================
# Test 2: Validate MLflow entrypoint.sh security configuration
# Copilot flags --disable-security-middleware as a security concern
# ============================================================================


class TestMLflowSecurityConfig:
    """Test MLflow security configuration in entrypoint.sh"""

    @pytest.fixture
    def entrypoint_path(self):
        """Path to entrypoint.sh"""
        return (
            get_project_root() / "mlflow-server" / "docker" / "mlflow" / "entrypoint.sh"
        )

    @pytest.fixture
    def entrypoint_source(self, entrypoint_path):
        """Load entrypoint.sh source"""
        with open(entrypoint_path, "r") as f:
            return f.read()

    def test_disable_security_middleware_present(self, entrypoint_source):
        """
        Document that --disable-security-middleware is currently used.

        CURRENT STATE: Security middleware is disabled for internal Docker networking.
        Copilot suggests this is a security risk for public exposure.
        """
        assert (
            "--disable-security-middleware" in entrypoint_source
        ), "Expected --disable-security-middleware to be present (current state)"

        print("\n⚠️  FINDING: --disable-security-middleware is currently enabled")
        print("   RATIONALE: Internal Docker network communication")
        print("   EXTERNAL SECURITY: Traefik reverse proxy handles authentication")
        print("   ")
        print("   COPILOT SUGGESTION: Re-enable security middleware with:")
        print("   --allowed-hosts and --cors-allowed-origins")

    def test_allowed_hosts_config_present(self, entrypoint_source):
        """Check if allowed hosts configuration exists"""
        has_allowed_hosts_env = "MLFLOW_ALLOWED_HOSTS" in entrypoint_source
        has_allowed_hosts_flag = "--allowed-hosts" in entrypoint_source

        print(f"\n   MLFLOW_ALLOWED_HOSTS env reference: {has_allowed_hosts_env}")
        print(f"   --allowed-hosts flag used: {has_allowed_hosts_flag}")

        # Current state: env is referenced in echo but not used in command
        assert has_allowed_hosts_env, "MLFLOW_ALLOWED_HOSTS should be referenced"

    def test_cors_config_present(self, entrypoint_source):
        """Check if CORS configuration exists"""
        has_cors_env = "MLFLOW_CORS_ALLOWED_ORIGINS" in entrypoint_source
        has_cors_flag = "--cors-allowed-origins" in entrypoint_source

        print(f"\n   MLFLOW_CORS_ALLOWED_ORIGINS env reference: {has_cors_env}")
        print(f"   --cors-allowed-origins flag used: {has_cors_flag}")

        # Current state: env is referenced in echo but not used in command
        assert has_cors_env, "MLFLOW_CORS_ALLOWED_ORIGINS should be referenced"

    def test_traefik_auth_assumption(self):
        """
        Document the assumption that Traefik handles external authentication.

        This test validates that if we disable MLflow's security,
        Traefik must be providing authentication for public access.
        """
        # Check if Traefik middleware configuration exists
        traefik_config_paths = [
            get_project_root() / "deploy/compose/docker-compose.infra.yml",
        ]

        found_traefik_auth = False
        for config_path in traefik_config_paths:
            if config_path.exists():
                with open(config_path, "r") as f:
                    content = f.read()
                    # Look for auth middleware references
                    if "forwardauth" in content.lower() or "oauth" in content.lower():
                        found_traefik_auth = True
                        break

        print(f"\n   Traefik auth middleware configured: {found_traefik_auth}")
        if not found_traefik_auth:
            print("   ⚠️  WARNING: No Traefik auth middleware found!")
            print("   Consider adding OAuth2 proxy or forward auth")


# ============================================================================
# Test 3: Validate Tailscale Funnel service security
# Copilot flags public exposure without auth enforcement
# ============================================================================


class TestTailscaleFunnelSecurity:
    """Test Tailscale Funnel service configuration security"""

    @pytest.fixture
    def funnel_service_path(self):
        """Path to tailscale-funnel.service"""
        return get_project_root() / "scripts" / "tailscale-funnel.service"

    @pytest.fixture
    def funnel_service_source(self, funnel_service_path):
        """Load tailscale-funnel.service source"""
        with open(funnel_service_path, "r") as f:
            return f.read()

    def test_funnel_exposes_port_80(self, funnel_service_source):
        """Document that funnel exposes HTTP port 80 to HTTPS 443"""
        assert (
            "http://127.0.0.1:80" in funnel_service_source
        ), "Expected funnel to forward to localhost:80"
        assert (
            "--https=443" in funnel_service_source
        ), "Expected funnel to use HTTPS on 443"

        print("\n⚠️  FINDING: Tailscale Funnel exposes localhost:80 publicly via HTTPS")
        print("   This means ALL services on Traefik (port 80) are publicly accessible")
        print("   ")
        print("   SERVICES POTENTIALLY EXPOSED:")
        print("   - MLflow (experiment/artifact APIs)")
        print("   - Ray Dashboard (cluster operations)")
        print("   - Grafana (metrics dashboards)")
        print("   ")
        print("   COPILOT SUGGESTION: Ensure all exposed services have authentication")

    def test_funnel_forwards_to_traefik(self, funnel_service_source):
        """Verify funnel forwards to Traefik (port 80)"""
        # Traefik typically listens on port 80/443
        assert (
            "127.0.0.1:80" in funnel_service_source
        ), "Funnel should forward to Traefik on port 80"

    def test_document_exposed_services(self):
        """
        Document what services are exposed through Traefik.

        This helps understand the security implications of the Funnel.
        """
        # Check deploy/compose/docker-compose.infra.yml for Traefik routes
        infra_config_path = get_project_root() / "deploy/compose/docker-compose.infra.yml"

        exposed_services = []
        if infra_config_path.exists():
            with open(infra_config_path, "r") as f:
                content = f.read()

                # Find traefik router rules
                router_patterns = [
                    (r"PathPrefix\(`([^`]+)`\)", "path prefix"),
                    (r"Host\(`([^`]+)`\)", "host"),
                ]

                for pattern, desc in router_patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        exposed_services.append(f"{desc}: {match}")

        print("\n   EXPOSED ROUTES (via Traefik):")
        for svc in exposed_services:
            print(f"   - {svc}")

        if not exposed_services:
            print("   (Could not parse Traefik routes)")

    def test_oauth_proxy_configured(self):
        """Check if OAuth2 proxy is configured for authentication"""
        infra_config_path = get_project_root() / "deploy/compose/docker-compose.infra.yml"

        has_oauth_proxy = False
        oauth_protected_routes = []

        if infra_config_path.exists():
            with open(infra_config_path, "r") as f:
                content = f.read()
                has_oauth_proxy = "oauth2-proxy" in content.lower()

                # Look for forwardAuth middleware
                if "forwardauth" in content.lower():
                    oauth_protected_routes.append("Some routes use forwardAuth")

        print(f"\n   OAuth2 Proxy service exists: {has_oauth_proxy}")
        print(f"   Protected routes: {oauth_protected_routes or 'Unknown'}")

        if not has_oauth_proxy:
            print("   ⚠️  WARNING: No OAuth2 proxy found!")
            print("   Public Funnel access may be unauthenticated")


# ============================================================================
# Integration test: Verify the complete security chain
# ============================================================================


class TestSecurityChainIntegration:
    """Test the complete security chain from public access to services"""

    def test_document_security_architecture(self):
        """
        Document the current security architecture.

        This test doesn't assert anything - it documents the current state
        to help evaluate the Copilot suggestions.
        """
        print("\n" + "=" * 60)
        print("CURRENT SECURITY ARCHITECTURE")
        print("=" * 60)
        print(
            """
        EXTERNAL REQUEST
              │
              ▼
        ┌─────────────────┐
        │ Tailscale Funnel│ (HTTPS termination)
        │   :443 → :80    │
        └────────┬────────┘
                 │
                 ▼
        ┌─────────────────┐
        │    Traefik      │ (Reverse proxy + routing)
        │     :80         │
        └────────┬────────┘
                 │
        ┌────────┴────────┐
        │                 │
        ▼                 ▼
    ┌─────────┐    ┌─────────────┐
    │ MLflow  │    │OAuth2 Proxy │
    │(no auth)│    │(FusionAuth) │
    └─────────┘    └──────┬──────┘
                         │
                    ┌────┴────┐
                    │         │
                    ▼         ▼
               ┌───────┐ ┌───────┐
               │ Ray   │ │Grafana│
               │  API  │ │       │
               └───────┘ └───────┘

        FINDINGS:
        1. MLflow may be accessible without auth if not behind OAuth proxy
        2. --disable-security-middleware removes MLflow's own protections
        3. Tailscale Funnel makes everything on port 80 public
        """
        )

    def test_security_recommendations(self):
        """Document security recommendations based on Copilot suggestions"""
        print("\n" + "=" * 60)
        print("SECURITY RECOMMENDATIONS")
        print("=" * 60)
        print(
            """
        1. server_v2.py - UNUSED IMPORT
           Action: Remove get_current_admin_user if not planning admin endpoints
           OR: Add admin-only endpoints (user management, system config, etc.)
           Risk: LOW (code cleanliness, not security)

        2. entrypoint.sh - SECURITY MIDDLEWARE DISABLED
           Action: Consider re-enabling with proper configuration:
             --allowed-hosts "mlflow,localhost,*.yourdomain.com"
             --cors-allowed-origins "https://yourdomain.com"
           Risk: MEDIUM (depends on Traefik auth configuration)
           Mitigation: Ensure OAuth proxy covers MLflow routes

        3. tailscale-funnel.service - PUBLIC EXPOSURE
           Action: Audit all routes behind Traefik
           Ensure: OAuth proxy protects sensitive endpoints
           Consider: Restrict Funnel to specific paths only
           Risk: HIGH (if auth is not properly configured)
        """
        )


# ============================================================================
# Run tests when executed directly
# ============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
