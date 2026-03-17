"""
Integration tests for MLflow API v1 endpoints

These tests verify:
1. OAuth2 protection is enforced (401 for unauthenticated requests)
2. Authenticated requests work correctly
3. API endpoints function properly across access methods

Run with:
    pytest tests/integration/test_api_endpoints.py -v

For authenticated tests, set environment variables:
    TEST_USERNAME, TEST_PASSWORD, FUSIONAUTH_CLIENT_ID
"""

import pytest
import requests
import time
from typing import Dict, Optional
import json
from pathlib import Path
import tempfile


class TestOAuth2Protection:
    """Test that OAuth2 protection is properly enforced"""

    @pytest.mark.integration
    def test_unauthenticated_health_returns_401(self, api_base_url):
        """Verify health endpoint requires authentication"""
        response = requests.get(f"{api_base_url}/api/v1/health", timeout=10)
        assert (
            response.status_code == 401
        ), "Health endpoint should require authentication"

    @pytest.mark.integration
    def test_unauthenticated_docs_returns_401(self, api_base_url):
        """Verify docs endpoint requires authentication"""
        response = requests.get(f"{api_base_url}/api/v1/docs", timeout=10)
        assert (
            response.status_code == 401
        ), "Docs endpoint should require authentication"

    @pytest.mark.integration
    def test_unauthenticated_schema_returns_401(self, api_v1_url):
        """Verify schema endpoint requires authentication"""
        response = requests.get(f"{api_v1_url}/schema", timeout=10)
        assert (
            response.status_code == 401
        ), "Schema endpoint should require authentication"

    @pytest.mark.integration
    def test_unauthenticated_experiments_returns_401(self, api_v1_url):
        """Verify experiments endpoint requires authentication"""
        response = requests.get(f"{api_v1_url}/experiments", timeout=10)
        assert (
            response.status_code == 401
        ), "Experiments endpoint should require authentication"

    @pytest.mark.integration
    def test_unauthenticated_runs_create_returns_401(self, api_v1_url):
        """Verify run creation requires authentication"""
        payload = {"experiment_name": "test", "tags": {"test": "true"}}
        response = requests.post(f"{api_v1_url}/runs/create", json=payload, timeout=10)
        assert response.status_code == 401, "Run creation should require authentication"

    @pytest.mark.integration
    def test_unauthenticated_models_returns_401(self, api_v1_url):
        """Verify models endpoint requires authentication"""
        response = requests.get(f"{api_v1_url}/models", timeout=10)
        assert (
            response.status_code == 401
        ), "Models endpoint should require authentication"

    @pytest.mark.integration
    def test_unauthenticated_storage_returns_401(self, api_v1_url):
        """Verify storage endpoint requires authentication"""
        response = requests.get(f"{api_v1_url}/storage/info", timeout=10)
        assert (
            response.status_code == 401
        ), "Storage endpoint should require authentication"


class TestPublicEndpoints:
    """Test endpoints that should be publicly accessible"""

    @pytest.mark.integration
    def test_auth_endpoint_accessible(self, api_base_url):
        """Verify FusionAuth endpoint is accessible without auth"""
        try:
            response = requests.get(f"{api_base_url}/auth/", timeout=10)
            # FusionAuth should respond (may redirect to login)
            assert response.status_code in [
                200,
                302,
                303,
            ], "Auth endpoint should be accessible"
        except requests.exceptions.ConnectionError:
            pytest.skip("Auth service not running")

    @pytest.mark.integration
    def test_well_known_endpoint_accessible(self, api_base_url):
        """Verify .well-known endpoint is accessible"""
        try:
            response = requests.get(
                f"{api_base_url}/.well-known/openid-configuration", timeout=10
            )
            # Should either return config or redirect
            assert response.status_code in [
                200,
                302,
                303,
                404,
            ], "Well-known should be accessible"
        except requests.exceptions.ConnectionError:
            pytest.skip("Auth service not running")


class TestAuthenticatedAPIHealth:
    """Test API health with authentication"""

    @pytest.mark.integration
    def test_health_endpoint_authenticated(
        self, api_base_url, auth_headers, requires_auth
    ):
        """Test /api/v1/health endpoint with auth"""
        response = requests.get(
            f"{api_base_url}/api/v1/health", headers=auth_headers, timeout=10
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "ok"]

    @pytest.mark.integration
    def test_swagger_docs_authenticated(
        self, api_base_url, auth_headers, requires_auth
    ):
        """Test Swagger documentation with auth"""
        response = requests.get(
            f"{api_base_url}/api/v1/docs", headers=auth_headers, timeout=10
        )
        assert response.status_code == 200


class TestAuthenticatedSchemaEndpoints:
    """Test schema validation endpoints with authentication"""

    @pytest.mark.integration
    def test_get_full_schema_authenticated(
        self, api_v1_url, auth_headers, requires_auth
    ):
        """Test GET /api/v1/schema with auth"""
        response = requests.get(
            f"{api_v1_url}/schema", headers=auth_headers, timeout=10
        )

        assert response.status_code == 200
        data = response.json()
        assert "experiments" in data or "schema" in data

    @pytest.mark.integration
    def test_validate_schema_authenticated(
        self, api_v1_url, auth_headers, test_tags, requires_auth
    ):
        """Test POST /api/v1/schema/validate with auth"""
        payload = {"experiment_name": "test-experiment", "tags": test_tags}

        response = requests.post(
            f"{api_v1_url}/schema/validate",
            json=payload,
            headers=auth_headers,
            timeout=10,
        )

        assert response.status_code in [200, 422]


class TestAuthenticatedExperimentEndpoints:
    """Test experiment management endpoints with authentication"""

    @pytest.mark.integration
    def test_list_experiments_authenticated(
        self, api_v1_url, auth_headers, requires_auth
    ):
        """Test GET /api/v1/experiments with auth"""
        response = requests.get(
            f"{api_v1_url}/experiments", headers=auth_headers, timeout=10
        )

        assert response.status_code == 200
        data = response.json()
        assert "experiments" in data
        assert isinstance(data["experiments"], list)


class TestAuthenticatedRunEndpoints:
    """Test run creation and management with authentication"""

    @pytest.mark.integration
    def test_create_run_authenticated(
        self, api_v1_url, auth_headers, test_experiment_name, test_tags, requires_auth
    ):
        """Test POST /api/v1/runs/create with auth"""
        payload = {
            "experiment_name": test_experiment_name,
            "tags": test_tags,
            "run_name": "test-run-auth",
            "validate_schema": True,
            "parameters": {"learning_rate": 0.001},
        }

        response = requests.post(
            f"{api_v1_url}/runs/create", json=payload, headers=auth_headers, timeout=10
        )

        # May succeed or fail depending on experiment existence
        assert response.status_code in [200, 404, 422]

        if response.status_code == 200:
            data = response.json()
            assert "run_id" in data

            # Cleanup
            try:
                requests.post(
                    f"{api_v1_url}/runs/{data['run_id']}/finish",
                    json={"status": "FINISHED"},
                    headers=auth_headers,
                    timeout=10,
                )
            except:
                pass


class TestAuthenticatedModelEndpoints:
    """Test model registry endpoints with authentication"""

    @pytest.mark.integration
    def test_list_models_authenticated(self, api_v1_url, auth_headers, requires_auth):
        """Test GET /api/v1/models with auth"""
        response = requests.get(
            f"{api_v1_url}/models", headers=auth_headers, timeout=10
        )

        assert response.status_code == 200


class TestAuthenticatedStorageEndpoints:
    """Test storage endpoints with authentication"""

    @pytest.mark.integration
    def test_storage_info_authenticated(self, api_v1_url, auth_headers, requires_auth):
        """Test GET /api/v1/storage/info with auth"""
        response = requests.get(
            f"{api_v1_url}/storage/info", headers=auth_headers, timeout=10
        )

        assert response.status_code == 200


class TestCrossHostOAuth2:
    """Verify OAuth2 protection across different access methods"""

    @pytest.mark.integration
    @pytest.mark.parametrize("host_key", ["local", "lan"])
    def test_oauth2_enforced_all_hosts(self, test_hosts, host_key):
        """Verify OAuth2 is enforced on all host access methods"""
        base_url = test_hosts[host_key]

        try:
            response = requests.get(f"{base_url}/api/v1/health", timeout=10)
            assert (
                response.status_code == 401
            ), f"OAuth2 should be enforced on {host_key}"
        except requests.exceptions.ConnectionError:
            pytest.skip(f"Cannot connect to {host_key} host")

    @pytest.mark.integration
    def test_oauth2_enforced_vpn(self, test_hosts):
        """Verify OAuth2 is enforced on VPN access"""
        base_url = test_hosts["vpn"]

        # Skip if VPN host is not properly configured
        if "${" in base_url or base_url == "http://localhost":
            pytest.skip("VPN host not configured")

        try:
            response = requests.get(f"{base_url}/api/v1/health", timeout=10)
            assert response.status_code == 401, "OAuth2 should be enforced on VPN"
        except requests.exceptions.ConnectionError:
            pytest.skip("Cannot connect to VPN host")
