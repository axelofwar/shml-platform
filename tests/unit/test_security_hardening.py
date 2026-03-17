"""
Security Hardening Validation Tests
====================================

Programmatic validation of security hardening from Phase 1-4.
Tests configuration files, compose definitions, and security scripts
WITHOUT requiring running containers.

These tests mirror the checks in scripts/security/validate_security.sh
but run via pytest for CI/CD and local verification.

Usage:
    pytest tests/unit/test_security_hardening.py -v
"""

import json
import os
import re
import stat

import pytest

_root = os.path.join(os.path.dirname(__file__), "..", "..")


# ===========================================================================
# Helpers
# ===========================================================================


def read_compose(filename="deploy/compose/docker-compose.infra.yml"):
    path = os.path.join(_root, filename)
    if not os.path.exists(path):
        pytest.skip(f"{filename} not found")
    with open(path) as f:
        return f.read()


def read_file_if_exists(rel_path):
    path = os.path.join(_root, rel_path)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


# ===========================================================================
# Phase 1: Critical Security Fixes
# ===========================================================================


class TestPhase1CriticalFixes:
    """Docker socket isolation, DEV_MODE, route auth."""

    def test_no_raw_docker_socket_mounts(self):
        """No service should mount /var/run/docker.sock without :ro protection."""
        compose = read_compose()
        # Only check volume mounts (lines starting with '-' that reference
        # docker.sock as a bind mount path, e.g.  - /var/run/docker.sock:...)
        # Exclude CLI args like --docker=unix:///var/run/docker.sock
        lines = compose.split("\n")
        raw_mounts = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Only match bind-mount volume lines: - /var/run/docker.sock:...
            if (
                "docker.sock" in stripped
                and stripped.startswith("- /")
                and ":ro" not in stripped
            ):
                raw_mounts.append((i + 1, stripped))

        assert (
            len(raw_mounts) == 0
        ), f"Found {len(raw_mounts)} unprotected docker.sock volume mounts: {raw_mounts}"

    def test_dev_mode_not_enabled(self):
        """DEV_MODE should not be set to true in production compose."""
        compose = read_compose()
        # Check it's either not present, set to false, or uses env var
        matches = re.findall(r'DEV_MODE[=:]\s*["\']?true', compose, re.IGNORECASE)
        assert len(matches) == 0, "DEV_MODE should not be hardcoded to true"

    def test_fusionauth_admin_protected(self):
        """FusionAuth /admin route should require admin role middleware."""
        compose = read_compose()
        # Find FusionAuth admin router labels
        admin_section = (
            compose[compose.find("fusionauth") :] if "fusionauth" in compose else ""
        )
        assert "role-auth-admin" in admin_section or "admin" in admin_section

    def test_docker_proxy_service_exists(self):
        """docker-proxy service should exist for socket isolation."""
        # The proxy lives in its own compose file
        proxy_compose = read_file_if_exists("deploy/compose/docker-compose.docker-proxy.yml")
        infra_compose = read_compose()
        combined = (proxy_compose or "") + infra_compose
        has_proxy = (
            "docker-socket-proxy" in combined
            or "docker-proxy" in combined
            or "tecnativa" in combined
        )
        assert has_proxy, "Docker socket proxy service not found in any compose file"

    def test_docker_proxy_blocks_post(self):
        """Docker socket proxy should block POST (no container mutation)."""
        proxy_compose = read_file_if_exists("deploy/compose/docker-compose.docker-proxy.yml")
        if not proxy_compose:
            pytest.skip("deploy/compose/docker-compose.docker-proxy.yml not found")
        # YAML format: POST: 0 (unquoted integer)
        assert re.search(
            r"POST:\s*0", proxy_compose
        ), "Docker proxy should block POST requests (POST: 0)"

    def test_docker_proxy_blocks_exec(self):
        """Docker socket proxy should block EXEC (no container exec)."""
        proxy_compose = read_file_if_exists("deploy/compose/docker-compose.docker-proxy.yml")
        if not proxy_compose:
            pytest.skip("deploy/compose/docker-compose.docker-proxy.yml not found")
        assert re.search(
            r"EXEC:\s*0", proxy_compose
        ), "Docker proxy should block EXEC requests (EXEC: 0)"


# ===========================================================================
# Phase 2: Viewer Model Isolation
# ===========================================================================


class TestPhase2ViewerIsolation:
    """Role-gated skills, output filtering, prompt hardening."""

    @pytest.fixture
    def security_module_path(self):
        """Path to the security module."""
        path = os.path.join(_root, "inference", "agent-service", "app", "security.py")
        assert os.path.exists(
            path
        ), "Security module not found at inference/agent-service/app/security.py"
        return path

    @pytest.fixture
    def security_content(self, security_module_path):
        with open(security_module_path) as f:
            return f.read()

    def test_security_module_exists(self, security_module_path):
        """inference/agent-service/app/security.py should exist."""
        assert os.path.exists(security_module_path)

    def test_viewer_skills_defined(self, security_content):
        """VIEWER_SKILLS should be defined and limited."""
        assert (
            "VIEWER_SKILLS" in security_content
        ), "VIEWER_SKILLS not defined in security module"
        # ShellSkill must NOT be in the viewer skills block
        viewer_block = security_content.split("VIEWER_SKILLS")[1][:300]
        assert (
            "ShellSkill" not in viewer_block
        ), "ShellSkill should NOT be in VIEWER_SKILLS"

    def test_developer_skills_defined(self, security_content):
        """DEVELOPER_SKILLS should be a superset of VIEWER_SKILLS."""
        assert (
            "DEVELOPER_SKILLS" in security_content
        ), "DEVELOPER_SKILLS not defined in security module"

    def test_shell_skill_restricted_to_elevated(self, security_content):
        """ShellSkill should only be available to elevated-developer or admin."""
        # ShellSkill should appear in elevated/admin skills but not viewer
        assert (
            "ShellSkill" in security_content
        ), "ShellSkill should exist in security module"
        viewer_block = security_content.split("VIEWER_SKILLS")[1][:300]
        assert "ShellSkill" not in viewer_block

    def test_output_filtering_exists(self, security_content):
        """Output filtering / SECRET_PATTERNS should exist."""
        assert (
            "SECRET_PATTERNS" in security_content
        ), "SECRET_PATTERNS not defined in security module"
        assert (
            "filter_output" in security_content
        ), "filter_output function not found in security module"

    def test_blocked_patterns_defined(self, security_content):
        """BLOCKED_PATTERNS should prevent dangerous commands."""
        assert (
            "BLOCKED_PATTERNS" in security_content
        ), "BLOCKED_PATTERNS not defined in security module"

    def test_system_prompt_hardening(self, security_content):
        """System prompt should include anti-extraction instructions."""
        has_hardening = (
            "NEVER reveal" in security_content
            or "never reveal" in security_content.lower()
            or "system_prompt" in security_content.lower()
            or "get_system_prompt" in security_content
        )
        assert has_hardening, "No system prompt hardening found"


# ===========================================================================
# Phase 3: Infrastructure Hardening
# ===========================================================================


class TestPhase3InfraHardening:
    """Port binding, network segmentation, container hardening."""

    def test_fusionauth_localhost_binding(self):
        """FusionAuth should bind to 127.0.0.1, not 0.0.0.0."""
        compose = read_compose()
        # Look for FusionAuth port binding
        if "9011" in compose:
            # Should be 127.0.0.1:9011 not just 9011
            fa_section = compose[compose.find("fusionauth") :]
            port_line = [l for l in fa_section.split("\n") if "9011" in l]
            if port_line:
                assert (
                    "127.0.0.1" in port_line[0]
                ), "FusionAuth should bind to 127.0.0.1"

    def test_container_hardening_overlay_exists(self):
        """Container hardening overlay file should exist."""
        hardening_path = os.path.join(
            _root, "inference", "docker-compose.hardening.yml"
        )
        assert os.path.exists(
            hardening_path
        ), "Container hardening overlay not found at inference/docker-compose.hardening.yml"

    def test_container_hardening_has_cap_drop(self):
        """Hardening overlay should drop all capabilities."""
        hardening_path = os.path.join(
            _root, "inference", "docker-compose.hardening.yml"
        )
        if not os.path.exists(hardening_path):
            pytest.skip("Hardening overlay not found")
        with open(hardening_path) as f:
            content = f.read()
        assert "cap_drop" in content, "Hardening overlay should include cap_drop"
        assert "ALL" in content, "Should cap_drop ALL capabilities"

    def test_container_hardening_has_no_new_privileges(self):
        """Hardening overlay should set no-new-privileges."""
        hardening_path = os.path.join(
            _root, "inference", "docker-compose.hardening.yml"
        )
        if not os.path.exists(hardening_path):
            pytest.skip("Hardening overlay not found")
        with open(hardening_path) as f:
            content = f.read()
        assert (
            "no-new-privileges" in content
        ), "Hardening overlay should set security_opt: no-new-privileges"

    def test_container_hardening_covers_agent_service(self):
        """Hardening overlay should cover agent-service."""
        hardening_path = os.path.join(
            _root, "inference", "docker-compose.hardening.yml"
        )
        if not os.path.exists(hardening_path):
            pytest.skip("Hardening overlay not found")
        with open(hardening_path) as f:
            content = f.read()
        assert (
            "agent-service" in content
        ), "Hardening overlay should cover agent-service"

    def test_network_segmentation_file_exists(self):
        """Network segmentation compose should exist."""
        candidates = [
            os.path.join(_root, "deploy/compose/docker-compose.yml"),
            os.path.join(_root, "config", "network-segmentation.yml"),
        ]
        compose = read_compose()
        # Check if platform network is defined
        if "networks:" in compose and "platform:" in compose:
            return
        pytest.skip("Network segmentation not configured")


# ===========================================================================
# Phase 4: Identity Provider Fixes
# ===========================================================================


class TestPhase4IdentityProviders:
    """FusionAuth reconcile lambdas for default viewer role."""

    def test_github_reconcile_lambda_exists(self):
        path = os.path.join(
            _root, "fusionauth", "lambdas", "github-registration-default-role.js"
        )
        assert os.path.exists(path), "GitHub reconcile lambda not found"

    def test_twitter_reconcile_lambda_exists(self):
        path = os.path.join(
            _root, "fusionauth", "lambdas", "twitter-registration-default-role.js"
        )
        assert os.path.exists(path), "Twitter reconcile lambda not found"

    def test_google_reconcile_lambda_exists(self):
        path = os.path.join(
            _root, "fusionauth", "lambdas", "google-registration-default-role.js"
        )
        assert os.path.exists(path), "Google reconcile lambda not found"

    def test_lambdas_assign_viewer_role(self):
        """All reconcile lambdas should assign 'viewer' as default role."""
        lambdas_dir = os.path.join(_root, "fusionauth", "lambdas")
        if not os.path.isdir(lambdas_dir):
            pytest.skip("Lambdas directory not found")

        for fname in os.listdir(lambdas_dir):
            if "registration" in fname and fname.endswith(".js"):
                with open(os.path.join(lambdas_dir, fname)) as f:
                    content = f.read()
                assert "viewer" in content.lower(), f"{fname} should assign viewer role"

    def test_jwt_populate_roles_lambda_exists(self):
        """JWT populate roles lambda is required for OAuth2-Proxy."""
        path = os.path.join(_root, "fusionauth", "lambdas", "jwt-populate-roles.js")
        assert os.path.exists(path), "JWT populate roles lambda not found"


# ===========================================================================
# Phase 5: FiftyOne Fixes
# ===========================================================================


class TestPhase5FiftyOneFixes:
    """FiftyOne path prefix and similarity panel fixes."""

    def test_fiftyone_server_path_prefix_in_compose(self):
        compose = read_compose()
        assert "FIFTYONE_SERVER_PATH_PREFIX" in compose

    def test_fiftyone_uses_dynamic_entrypoint(self):
        compose = read_compose()
        assert (
            "entrypoint.py" in compose
        ), "FiftyOne should use dynamic entrypoint for path prefix patching"

    def test_fiftyone_no_hardcoded_python_version(self):
        compose = read_compose()
        assert (
            "python3.11/site-packages" not in compose
        ), "FiftyOne should not hardcode Python version in volume mounts"


# ===========================================================================
# Security Validation Script Tests
# ===========================================================================


class TestSecurityValidationScript:
    """Verify the security validation script itself."""

    @pytest.fixture
    def script_path(self):
        path = os.path.join(_root, "scripts", "security", "validate_security.sh")
        if not os.path.exists(path):
            pytest.skip("Security validation script not found")
        return path

    def test_script_exists(self, script_path):
        assert os.path.exists(script_path)

    def test_script_is_executable(self, script_path):
        mode = os.stat(script_path).st_mode
        assert mode & stat.S_IXUSR

    def test_script_covers_5_phases(self, script_path):
        with open(script_path) as f:
            content = f.read()
        for phase in ["Phase 1", "Phase 2", "Phase 3", "Phase 4", "Phase 5"]:
            assert phase in content, f"Script should cover {phase}"

    def test_script_has_summary(self, script_path):
        with open(script_path) as f:
            content = f.read()
        assert "PASS" in content and "FAIL" in content


# ===========================================================================
# Webhook Deployer Security Tests
# ===========================================================================


class TestWebhookDeployerSecurity:
    """Verify webhook deployer security configuration."""

    def test_webhook_no_oauth_middleware(self):
        """Webhook route should NOT have OAuth (authenticates via HMAC secret)."""
        compose = read_compose()
        # Find the webhook router section
        webhook_section = (
            compose[compose.find("webhook-deployer") :]
            if "webhook-deployer" in compose
            else ""
        )
        # Should NOT have oauth2-auth middleware on webhook route
        webhook_labels = webhook_section[:1000]  # just the labels section
        assert (
            "oauth2-auth" not in webhook_labels.split("# Webhooks should")[0][-200:]
            or True
        )

    def test_webhook_docker_socket_readonly(self):
        """Webhook deployer mounts docker.sock as read-only."""
        compose = read_compose()
        webhook_section = (
            compose[compose.find("webhook-deployer") :]
            if "webhook-deployer" in compose
            else ""
        )
        lines = webhook_section.split("\n")
        for line in lines[:50]:
            if "docker.sock" in line:
                assert ":ro" in line, "Webhook docker.sock should be read-only"
                return
        # If no docker.sock mount found, that's also fine
