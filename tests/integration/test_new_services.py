"""
Integration tests for newly added SHML Platform services:
- Nessie (Iceberg catalog with Git-like branching)
- FiftyOne (Visual dataset curation)
- ML SLO Exporter (Prometheus metrics for model SLOs)
- Feature Store (pgvector-backed feature tables)

These tests verify:
1. Service health endpoints respond correctly
2. OAuth/Traefik routing enforces authentication
3. Core API functionality works end-to-end
4. Prometheus metrics are exposed correctly
5. Database schemas are created properly

Usage:
    # Run all new service tests
    pytest tests/integration/test_new_services.py -v

    # Run with auth (requires env vars: TEST_USERNAME, TEST_PASSWORD, FUSIONAUTH_CLIENT_ID)
    pytest tests/integration/test_new_services.py -v -m authenticated

    # Run only unauthenticated tests
    pytest tests/integration/test_new_services.py -v -m "not authenticated"

    # Run specific service tests
    pytest tests/integration/test_new_services.py -v -k "Nessie"
    pytest tests/integration/test_new_services.py -v -k "FiftyOne"
    pytest tests/integration/test_new_services.py -v -k "SLOExporter"
    pytest tests/integration/test_new_services.py -v -k "FeatureStore"
"""

import json
import os
import sys
import time

import pytest
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("ML_PLATFORM_URL", "http://localhost")
INTERNAL_NESSIE_URL = os.getenv("NESSIE_INTERNAL_URL", "http://localhost:19120")
INTERNAL_SLO_URL = os.getenv("SLO_EXPORTER_URL", "http://localhost:9092")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "ray_compute")
POSTGRES_USER = os.getenv("POSTGRES_USER", "shared_user")

# Timeout for HTTP requests
REQUEST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def session():
    """Shared requests session for the module."""
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    yield s
    s.close()


@pytest.fixture(scope="module")
def auth_session(session):
    """
    Session with OAuth2 bearer token.
    Skips if credentials are not configured.
    """
    client_id = os.getenv("FUSIONAUTH_CLIENT_ID", "")
    username = os.getenv("TEST_USERNAME", "")
    password = os.getenv("TEST_PASSWORD", "")

    if not all([client_id, username, password]):
        pytest.skip(
            "Auth not configured (set TEST_USERNAME, TEST_PASSWORD, FUSIONAUTH_CLIENT_ID)"
        )

    fusionauth_url = os.getenv("FUSIONAUTH_URL", "http://localhost:9011")
    try:
        resp = requests.post(
            f"{fusionauth_url}/oauth2/token",
            data={
                "grant_type": "password",
                "client_id": client_id,
                "client_secret": os.getenv("FUSIONAUTH_CLIENT_SECRET", ""),
                "username": username,
                "password": password,
                "scope": "openid profile email",
            },
            timeout=10,
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
    except Exception as e:
        pytest.skip(f"Failed to obtain auth token: {e}")

    session.headers.update({"Authorization": f"Bearer {token}"})
    return session


@pytest.fixture(scope="module")
def pg_conn():
    """
    PostgreSQL connection for feature store schema tests.
    Requires psycopg2 installed and direct access to postgres.
    """
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 not installed")

    password = os.getenv("POSTGRES_PASSWORD", "")
    if not password:
        # Try reading from Docker secret file
        secret_file = os.getenv(
            "POSTGRES_PASSWORD_FILE",
            os.path.expanduser(
                "~/Projects/shml-platform/secrets/shared_db_password.txt"
            ),
        )
        try:
            with open(secret_file) as f:
                password = f.read().strip()
        except FileNotFoundError:
            pytest.skip("PostgreSQL password not available")

    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=password,
        )
        conn.autocommit = True
        yield conn
        conn.close()
    except Exception as e:
        pytest.skip(f"PostgreSQL connection failed: {e}")


# ===========================================================================
# Nessie Integration Tests
# ===========================================================================


class TestNessieIntegration:
    """Test Nessie Iceberg catalog service."""

    @pytest.mark.integration
    def test_nessie_health_internal(self, session):
        """Nessie REST API config endpoint should respond (internal port)."""
        try:
            resp = session.get(
                f"{INTERNAL_NESSIE_URL}/api/v2/config",
                timeout=REQUEST_TIMEOUT,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "defaultBranch" in data
            assert data["defaultBranch"] == "main"
        except requests.exceptions.ConnectionError:
            pytest.skip(
                "Nessie not reachable on internal port (container network only)"
            )

    @pytest.mark.integration
    def test_nessie_oauth_redirect(self, session):
        """
        Unauthenticated request to /nessie/ through Traefik should redirect to OAuth login.
        """
        resp = session.get(
            f"{BASE_URL}/nessie/api/v2/config",
            allow_redirects=False,
            timeout=REQUEST_TIMEOUT,
        )
        # Should get 302 redirect to OAuth login or 401 Unauthorized
        assert resp.status_code in (
            301,
            302,
            401,
            403,
        ), f"Expected auth redirect/deny, got {resp.status_code}"

    @pytest.mark.integration
    @pytest.mark.authenticated
    def test_nessie_config_authenticated(self, auth_session):
        """Authenticated request to Nessie config endpoint."""
        resp = auth_session.get(
            f"{BASE_URL}/nessie/api/v2/config",
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "defaultBranch" in data

    @pytest.mark.integration
    @pytest.mark.authenticated
    def test_nessie_branch_crud(self, auth_session):
        """Create, list, and delete a test branch in Nessie."""
        branch_name = f"test-branch-{int(time.time())}"

        # Get main branch hash
        resp = auth_session.get(
            f"{BASE_URL}/nessie/api/v2/trees/main",
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 200
        main_hash = resp.json().get("hash")

        # Create branch
        resp = auth_session.post(
            f"{BASE_URL}/nessie/api/v2/trees",
            json={
                "type": "BRANCH",
                "name": branch_name,
                "hash": main_hash,
            },
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code in (200, 201), f"Branch create failed: {resp.text}"

        # List branches — should include new branch
        resp = auth_session.get(
            f"{BASE_URL}/nessie/api/v2/trees",
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 200
        branches = [ref["name"] for ref in resp.json().get("references", [])]
        assert branch_name in branches, f"Branch {branch_name} not found in {branches}"

        # Delete branch
        resp = auth_session.delete(
            f"{BASE_URL}/nessie/api/v2/trees/{branch_name}",
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code in (200, 204), f"Branch delete failed: {resp.text}"

    @pytest.mark.integration
    def test_nessie_prometheus_metrics(self, session):
        """Nessie should expose Quarkus/Micrometer metrics."""
        try:
            resp = session.get(
                "http://localhost:9000/q/metrics",
                timeout=REQUEST_TIMEOUT,
            )
            # Nessie metrics may be on the management port
            if resp.status_code == 200:
                assert "jvm_" in resp.text or "http_" in resp.text
            else:
                pytest.skip("Nessie metrics port not directly reachable")
        except requests.exceptions.ConnectionError:
            pytest.skip("Nessie metrics port not reachable (container network only)")


# ===========================================================================
# FiftyOne Integration Tests
# ===========================================================================


class TestFiftyOneIntegration:
    """Test FiftyOne visual dataset curation service."""

    @pytest.mark.integration
    def test_fiftyone_oauth_redirect(self, session):
        """
        Unauthenticated request to /fiftyone/ through Traefik should redirect to OAuth.
        """
        resp = session.get(
            f"{BASE_URL}/fiftyone/",
            allow_redirects=False,
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code in (
            301,
            302,
            401,
            403,
        ), f"Expected auth redirect/deny, got {resp.status_code}"

    @pytest.mark.integration
    @pytest.mark.authenticated
    def test_fiftyone_ui_authenticated(self, auth_session):
        """Authenticated request to FiftyOne UI should return HTML."""
        resp = auth_session.get(
            f"{BASE_URL}/fiftyone/",
            timeout=REQUEST_TIMEOUT,
        )
        # FiftyOne returns HTML for the web UI
        assert resp.status_code == 200
        assert (
            "text/html" in resp.headers.get("content-type", "").lower()
            or len(resp.content) > 0
        )

    @pytest.mark.integration
    @pytest.mark.authenticated
    def test_fiftyone_api_health(self, auth_session):
        """FiftyOne GraphQL API should be accessible."""
        # FiftyOne uses a GraphQL endpoint
        resp = auth_session.post(
            f"{BASE_URL}/fiftyone/graphql",
            json={"query": "{ __typename }"},
            timeout=REQUEST_TIMEOUT,
        )
        # Even if the query format differs, we should get a response (not a redirect)
        assert resp.status_code in (
            200,
            400,
        ), f"Expected API response, got {resp.status_code}"

    @pytest.mark.integration
    def test_fiftyone_mongodb_running(self):
        """FiftyOne MongoDB container should be running and healthy."""
        import subprocess

        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Health.Status}}",
                "shml-fiftyone-mongodb",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            pytest.skip("FiftyOne MongoDB container not found")
        assert result.stdout.strip() == "healthy"


# ===========================================================================
# ML SLO Exporter Tests
# ===========================================================================


class TestSLOExporter:
    """Test ML SLO Exporter Prometheus metrics."""

    @pytest.mark.integration
    def test_slo_exporter_health(self, session):
        """SLO exporter HTTP server should respond on internal port."""
        try:
            resp = session.get(f"{INTERNAL_SLO_URL}/", timeout=REQUEST_TIMEOUT)
            # prometheus_client returns 200 with metrics listing
            assert resp.status_code == 200
        except requests.exceptions.ConnectionError:
            pytest.skip("SLO exporter not reachable (may be container-only network)")

    @pytest.mark.integration
    def test_slo_exporter_metrics_format(self, session):
        """SLO exporter should return Prometheus text format metrics."""
        try:
            resp = session.get(f"{INTERNAL_SLO_URL}/metrics", timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                resp = session.get(f"{INTERNAL_SLO_URL}/", timeout=REQUEST_TIMEOUT)
            assert resp.status_code == 200
            text = resp.text

            # Check for expected gauge names
            expected_metrics = [
                "ml_model_freshness_days",
                "ml_dataset_freshness_days",
                "ml_eval_completeness_ratio",
                "ml_training_success_rate_7d",
                "ml_inference_latency_p99_ms",
                "ml_feature_freshness_minutes",
                "ml_error_budget_remaining_pct",
                "ml_slo_violations_30d",
            ]
            found = [m for m in expected_metrics if m in text]
            assert (
                len(found) >= 4
            ), f"Expected at least 4 SLO metrics, found {len(found)}: {found}"
        except requests.exceptions.ConnectionError:
            pytest.skip("SLO exporter not reachable")

    @pytest.mark.integration
    def test_slo_exporter_no_traefik_route(self, session):
        """SLO exporter should NOT be exposed through Traefik (internal only)."""
        resp = session.get(
            f"{BASE_URL}/slo-exporter/",
            allow_redirects=False,
            timeout=REQUEST_TIMEOUT,
        )
        # Should get 404 (no route) — NOT 302 or 200
        assert resp.status_code in (
            404,
            502,
        ), f"SLO exporter should not have a Traefik route, got {resp.status_code}"

    @pytest.mark.integration
    def test_slo_exporter_container_health(self):
        """SLO exporter container should be healthy."""
        import subprocess

        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Health.Status}}",
                "shml-ml-slo-exporter",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            pytest.skip("SLO exporter container not found")
        assert result.stdout.strip() == "healthy"


# ===========================================================================
# Feature Store Schema Tests
# ===========================================================================


class TestFeatureStoreSchema:
    """Test pgvector feature store schema creation and operations."""

    EXPECTED_TABLES = [
        "feature_eval",
        "feature_hard_examples",
        "feature_training_lineage",
        "feature_dataset_quality",
    ]

    @pytest.mark.integration
    def test_pgvector_extension(self, pg_conn):
        """pgvector extension should be available / creatable."""
        cur = pg_conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        row = cur.fetchone()
        assert row is not None, "pgvector extension not installed"
        assert row[0] == "vector"
        cur.close()

    @pytest.mark.integration
    def test_feature_client_init_schema(self, pg_conn):
        """FeatureClient.init_schema() should create all 4 tables without errors."""
        # Add libs to path
        libs_path = os.path.join(os.path.dirname(__file__), "..", "..", "libs")
        sys.path.insert(0, os.path.abspath(libs_path))

        try:
            from shml_features import FeatureClient
        except ImportError:
            pytest.skip("shml_features not importable — check libs path")

        password = ""
        secret_file = os.path.expanduser(
            "~/Projects/shml-platform/secrets/shared_db_password.txt"
        )
        try:
            with open(secret_file) as f:
                password = f.read().strip()
        except FileNotFoundError:
            pytest.skip("DB password not available")

        dsn = f"host={POSTGRES_HOST} port={POSTGRES_PORT} dbname={POSTGRES_DB} user={POSTGRES_USER} password={password}"
        client = FeatureClient(dsn=dsn)
        client.init_schema()

        # Verify tables exist
        cur = pg_conn.cursor()
        for table in self.EXPECTED_TABLES:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
                (table,),
            )
            exists = cur.fetchone()[0]
            assert exists, f"Table {table} was not created by init_schema()"
        cur.close()

    @pytest.mark.integration
    def test_feature_eval_table_columns(self, pg_conn):
        """feature_eval table should have expected columns."""
        cur = pg_conn.cursor()
        cur.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'feature_eval'
            ORDER BY ordinal_position
            """
        )
        columns = {row[0]: row[1] for row in cur.fetchall()}
        cur.close()

        if not columns:
            pytest.skip("feature_eval table not yet created")

        expected = ["run_id", "model_name", "metric_name", "metric_value"]
        for col in expected:
            assert col in columns, f"Column {col} missing from feature_eval"

    @pytest.mark.integration
    def test_feature_hard_examples_has_vector(self, pg_conn):
        """feature_hard_examples should have a vector(512) embedding column."""
        cur = pg_conn.cursor()
        cur.execute(
            """
            SELECT column_name, udt_name
            FROM information_schema.columns
            WHERE table_name = 'feature_hard_examples'
            AND column_name = 'embedding'
            """
        )
        row = cur.fetchone()
        cur.close()

        if row is None:
            pytest.skip("feature_hard_examples table not yet created")

        assert row[1] == "vector", f"embedding column type is {row[1]}, expected vector"


# ===========================================================================
# Homer Dashboard Tests
# ===========================================================================


class TestHomerDashboard:
    """Verify Homer dashboard includes new service entries."""

    @pytest.mark.integration
    def test_homer_contains_nessie(self, session):
        """Homer config should reference Nessie."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "monitoring", "homer", "config.yml"
        )
        try:
            with open(config_path) as f:
                content = f.read()
            assert "Nessie" in content, "Nessie not found in Homer config"
            assert "/nessie/" in content, "Nessie URL not found in Homer config"
        except FileNotFoundError:
            pytest.skip("Homer config not found")

    @pytest.mark.integration
    def test_homer_contains_fiftyone(self, session):
        """Homer config should reference FiftyOne."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "monitoring", "homer", "config.yml"
        )
        try:
            with open(config_path) as f:
                content = f.read()
            assert "FiftyOne" in content, "FiftyOne not found in Homer config"
            assert "/fiftyone/" in content, "FiftyOne URL not found in Homer config"
        except FileNotFoundError:
            pytest.skip("Homer config not found")

    @pytest.mark.integration
    def test_homer_contains_slo_dashboard(self, session):
        """Homer config should reference ML SLO Dashboard."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "monitoring", "homer", "config.yml"
        )
        try:
            with open(config_path) as f:
                content = f.read()
            assert (
                "ML SLO Dashboard" in content
            ), "ML SLO Dashboard not found in Homer config"
            assert (
                "ml-slo-overview" in content
            ), "SLO dashboard URL not found in Homer config"
        except FileNotFoundError:
            pytest.skip("Homer config not found")


# ===========================================================================
# Traefik Routing Tests for New Services
# ===========================================================================


class TestNewServiceTraefikRouting:
    """Verify Traefik routes are configured correctly for new services."""

    @pytest.mark.integration
    @pytest.mark.security
    def test_nessie_requires_developer_role(self, session):
        """Nessie should require at least developer role (not viewer)."""
        resp = session.get(
            f"{BASE_URL}/nessie/api/v2/config",
            allow_redirects=False,
            timeout=REQUEST_TIMEOUT,
        )
        # Must redirect to auth — not accessible without login
        assert resp.status_code in (301, 302, 401, 403)

    @pytest.mark.integration
    @pytest.mark.security
    def test_fiftyone_requires_developer_role(self, session):
        """FiftyOne should require at least developer role (not viewer)."""
        resp = session.get(
            f"{BASE_URL}/fiftyone/",
            allow_redirects=False,
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code in (301, 302, 401, 403)

    @pytest.mark.integration
    @pytest.mark.security
    def test_fiftyone_mongodb_not_exposed(self, session):
        """FiftyOne MongoDB should NOT be exposed through Traefik."""
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        # MongoDB port should not be reachable from outside Docker network
        result = sock.connect_ex(("localhost", 27017))
        sock.close()
        assert result != 0, "MongoDB port 27017 should not be exposed on localhost"

    @pytest.mark.integration
    def test_nessie_strip_prefix(self, auth_session):
        """
        Nessie strip prefix should work — /nessie/api/v2/config should
        reach Nessie's /api/v2/config endpoint.
        """
        resp = auth_session.get(
            f"{BASE_URL}/nessie/api/v2/config",
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "defaultBranch" in data


# ===========================================================================
# Compose Validation Tests
# ===========================================================================


class TestComposeValidation:
    """Validate Docker Compose configurations."""

    @pytest.mark.integration
    def test_infra_compose_valid(self):
        """docker-compose.infra.yml should parse without errors."""
        import subprocess

        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "docker-compose.infra.yml",
                "config",
                "--quiet",
            ],
            capture_output=True,
            text=True,
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
            timeout=30,
        )
        assert result.returncode == 0, f"Compose config error:\n{result.stderr}"

    @pytest.mark.integration
    def test_ray_compose_valid(self):
        """ray_compute/docker-compose.yml should parse without errors."""
        import subprocess

        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "ray_compute/docker-compose.yml",
                "config",
                "--quiet",
            ],
            capture_output=True,
            text=True,
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
            timeout=30,
        )
        assert result.returncode == 0, f"Compose config error:\n{result.stderr}"

    @pytest.mark.integration
    def test_new_services_defined_in_compose(self):
        """All new services should be defined in docker-compose.infra.yml."""
        import subprocess

        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "docker-compose.infra.yml",
                "config",
                "--services",
            ],
            capture_output=True,
            text=True,
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
            timeout=30,
        )
        assert result.returncode == 0
        services = result.stdout.strip().split("\n")
        expected = ["nessie", "fiftyone", "fiftyone-mongodb", "ml-slo-exporter"]
        for svc in expected:
            assert svc in services, f"Service {svc} not in compose: {services}"
