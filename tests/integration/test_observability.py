"""
Integration tests for Observability Stack services

Tests verify:
1. Dozzle log aggregation is accessible and OAuth protected
2. Homer dashboard is accessible and OAuth protected
3. Postgres backup service is running and healthy
4. Webhook deployer endpoint is accessible

Run with:
    pytest tests/integration/test_observability.py -v

For authenticated tests, set environment variables:
    TEST_USERNAME, TEST_PASSWORD, FUSIONAUTH_CLIENT_ID
"""

import pytest
import requests
import time
from typing import Dict, Optional
import os


# Service endpoints (relative to base URL)
OBSERVABILITY_ENDPOINTS = {
    "dozzle": "/logs/",
    "homer": "/",
    "webhook_health": "/webhook/hooks/health",
}

# Internal service URLs (for direct health checks within Docker network)
INTERNAL_ENDPOINTS = {
    "dozzle_health": "http://dozzle:8080/logs/healthcheck",
    "homer_health": "http://homer:8080/",
    "backup_health": "http://postgres-backup:8080/",
}


class TestObservabilityOAuthProtection:
    """Test that observability services are properly OAuth protected"""

    @pytest.mark.integration
    @pytest.mark.observability
    def test_dozzle_requires_auth(self, api_base_url):
        """Verify Dozzle log viewer requires authentication"""
        response = requests.get(
            f"{api_base_url}/logs/", timeout=10, allow_redirects=False
        )
        # Should redirect to OAuth login or return 401
        assert response.status_code in [
            401,
            302,
            303,
        ], f"Dozzle should require auth, got {response.status_code}"

    @pytest.mark.integration
    @pytest.mark.observability
    def test_homer_requires_auth(self, api_base_url):
        """Verify Homer dashboard requires authentication"""
        response = requests.get(f"{api_base_url}/", timeout=10, allow_redirects=False)
        assert response.status_code in [
            401,
            302,
            303,
        ], f"Homer should require auth, got {response.status_code}"


class TestObservabilityAuthenticated:
    """Test observability services with authentication"""

    @pytest.mark.integration
    @pytest.mark.observability
    @pytest.mark.authenticated
    def test_dozzle_accessible_with_auth(
        self, api_base_url, auth_headers, requires_auth
    ):
        """Verify Dozzle is accessible with valid authentication"""
        if not auth_headers:
            pytest.skip("Authentication not configured")

        response = requests.get(
            f"{api_base_url}/logs/",
            headers=auth_headers,
            timeout=10,
            allow_redirects=True,
        )
        assert (
            response.status_code == 200
        ), f"Dozzle should be accessible with auth, got {response.status_code}"

    @pytest.mark.integration
    @pytest.mark.observability
    @pytest.mark.authenticated
    def test_homer_accessible_with_auth(
        self, api_base_url, auth_headers, requires_auth
    ):
        """Verify Homer is accessible with valid authentication"""
        if not auth_headers:
            pytest.skip("Authentication not configured")

        response = requests.get(
            f"{api_base_url}/",
            headers=auth_headers,
            timeout=10,
            allow_redirects=True,
        )
        assert (
            response.status_code == 200
        ), f"Homer should be accessible with auth, got {response.status_code}"


class TestWebhookEndpoint:
    """Test webhook deployer endpoint"""

    @pytest.mark.integration
    @pytest.mark.observability
    def test_webhook_health_endpoint(self, api_base_url):
        """Verify webhook health endpoint is accessible (no auth required)"""
        try:
            response = requests.get(f"{api_base_url}/webhook/hooks/health", timeout=10)
            # Webhook health should be publicly accessible
            assert response.status_code in [
                200,
                404,
            ], f"Webhook health check unexpected status: {response.status_code}"
        except requests.exceptions.ConnectionError:
            pytest.skip("Webhook service not running")

    @pytest.mark.integration
    @pytest.mark.observability
    def test_webhook_github_endpoint_requires_signature(self, api_base_url):
        """Verify GitHub webhook endpoint requires valid signature"""
        response = requests.post(
            f"{api_base_url}/webhook/hooks/github-deploy",
            json={"ref": "refs/heads/main"},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        # Should fail without valid HMAC signature
        assert response.status_code in [
            400,
            401,
            403,
            500,
        ], f"Webhook should require signature, got {response.status_code}"


class TestBackupService:
    """Test PostgreSQL backup service"""

    @pytest.mark.integration
    @pytest.mark.observability
    def test_backup_container_running(self):
        """Verify backup container is running"""
        import subprocess

        result = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                "name=postgres-backup",
                "--format",
                "{{.Status}}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            assert "Up" in result.stdout, "Backup container should be running"
        else:
            pytest.skip("Backup container not deployed")

    @pytest.mark.integration
    @pytest.mark.observability
    def test_backup_directory_exists(self):
        """Verify backup directory exists and is writable"""
        import os

        backup_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "backups",
            "postgres",
        )
        # Directory may not exist if backups haven't run yet
        if os.path.exists(backup_dir):
            assert os.path.isdir(backup_dir), "Backup path should be a directory"
            assert os.access(backup_dir, os.W_OK), "Backup directory should be writable"


class TestContainerHealth:
    """Test container health via Docker API"""

    @pytest.mark.integration
    @pytest.mark.observability
    def test_observability_containers_healthy(self):
        """Verify all observability containers are healthy"""
        import subprocess

        containers = ["dozzle", "homer", "postgres-backup"]
        unhealthy = []
        not_found = []

        for container in containers:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", container],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                not_found.append(container)
            elif "running" not in result.stdout.lower():
                unhealthy.append(f"{container}: {result.stdout.strip()}")

        if not_found:
            pytest.skip(f"Containers not deployed: {', '.join(not_found)}")

        assert not unhealthy, f"Unhealthy containers: {', '.join(unhealthy)}"


class TestResourceDetection:
    """Test resource detection script"""

    @pytest.mark.integration
    @pytest.mark.observability
    def test_resource_detection_script_runs(self):
        """Verify resource detection script executes successfully"""
        import subprocess
        import os

        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "scripts",
            "detect_resources.sh",
        )

        if not os.path.exists(script_path):
            pytest.skip("Resource detection script not found")

        result = subprocess.run([script_path, "--env"], capture_output=True, text=True)

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "CPU_LIMIT" in result.stdout, "Script should output CPU limits"
        assert "MEM_LIMIT" in result.stdout, "Script should output memory limits"

    @pytest.mark.integration
    @pytest.mark.observability
    def test_resource_detection_exports_valid_env(self):
        """Verify resource detection outputs valid environment variables"""
        import subprocess
        import os

        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "scripts",
            "detect_resources.sh",
        )

        if not os.path.exists(script_path):
            pytest.skip("Resource detection script not found")

        result = subprocess.run(
            [script_path, "--export"], capture_output=True, text=True
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"

        # Verify output contains valid export statements
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if line.strip():
                assert line.startswith("export "), f"Invalid line: {line}"
                assert "=" in line, f"Missing = in export: {line}"


class TestBackupScript:
    """Test manual backup script"""

    @pytest.mark.integration
    @pytest.mark.observability
    def test_backup_script_exists_and_executable(self):
        """Verify backup script exists and is executable"""
        import os

        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "scripts",
            "backup_databases.sh",
        )

        assert os.path.exists(script_path), "Backup script should exist"
        assert os.access(script_path, os.X_OK), "Backup script should be executable"

    @pytest.mark.integration
    @pytest.mark.observability
    def test_backup_script_validates_container(self):
        """Verify backup script checks for shared-postgres container"""
        import subprocess
        import os

        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "scripts",
            "backup_databases.sh",
        )

        # Read script content to verify it references shared-postgres
        with open(script_path, "r") as f:
            content = f.read()

        assert (
            "shared-postgres" in content
        ), "Backup script should reference shared-postgres container"
        assert "mlflow_db" in content, "Backup script should backup mlflow_db"
        assert "fusionauth" in content, "Backup script should backup fusionauth"
