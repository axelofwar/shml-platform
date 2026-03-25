"""
Pytest configuration and shared fixtures for ML Platform tests
"""

import pytest
import os
import tempfile
import requests
from typing import Dict, List, Optional

# Test environment configuration
TEST_HOSTS = {
    "local": "http://localhost",
    "lan": "http://localhost",
    "vpn": os.getenv("TAILSCALE_IP", "http://localhost"),  # Resolve from env
}

# OAuth2/FusionAuth configuration
FUSIONAUTH_URL = os.getenv("FUSIONAUTH_URL", "http://localhost:9011")
FUSIONAUTH_CLIENT_ID = os.getenv("FUSIONAUTH_CLIENT_ID", "")
FUSIONAUTH_CLIENT_SECRET = os.getenv("FUSIONAUTH_CLIENT_SECRET", "")
TEST_USERNAME = os.getenv("TEST_USERNAME", "")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "")

# Inference stack endpoints
INFERENCE_ENDPOINTS = {
    "gateway_health": "/inference/health",
    "llm_health": "/api/llm/health",
    "image_health": "/api/image/health",
    "llm_completions": "/api/llm/v1/chat/completions",
    "image_generate": "/api/image/v1/generate",
    "queue_status": "/inference/queue/status",
    "conversations": "/inference/conversations",
}

# Set MLflow artifact directory to a temp directory accessible to tests
# This prevents permission issues when trying to write to /mlflow
os.environ.setdefault(
    "MLFLOW_ARTIFACT_ROOT", tempfile.gettempdir() + "/mlflow-test-artifacts"
)
os.makedirs(os.environ["MLFLOW_ARTIFACT_ROOT"], exist_ok=True)


@pytest.fixture(scope="session")
def test_hosts() -> Dict[str, str]:
    """Provide test host URLs for local, LAN, and VPN access"""
    return TEST_HOSTS


@pytest.fixture(scope="session")
def auth_token() -> Optional[str]:
    """
    Get OAuth2 access token for authenticated tests.
    Returns None if credentials are not configured.
    """
    if not all([FUSIONAUTH_CLIENT_ID, TEST_USERNAME, TEST_PASSWORD]):
        return None

    try:
        # Try to get token from FusionAuth
        response = requests.post(
            f"{FUSIONAUTH_URL}/oauth2/token",
            data={
                "grant_type": "password",
                "client_id": FUSIONAUTH_CLIENT_ID,
                "client_secret": FUSIONAUTH_CLIENT_SECRET,
                "username": TEST_USERNAME,
                "password": TEST_PASSWORD,
                "scope": "openid profile email",
            },
            timeout=10,
        )
        if response.status_code == 200:
            return response.json().get("access_token")
    except requests.exceptions.RequestException:
        pass
    return None


@pytest.fixture(scope="session")
def auth_headers(auth_token: Optional[str]) -> Dict[str, str]:
    """Get authorization headers for authenticated requests"""
    if auth_token:
        return {"Authorization": f"Bearer {auth_token}"}
    return {}


@pytest.fixture(scope="session")
def requires_auth(auth_token: Optional[str]):
    """Skip test if authentication is not configured"""
    if not auth_token:
        pytest.skip(
            "Authentication not configured (set TEST_USERNAME, TEST_PASSWORD, FUSIONAUTH_CLIENT_ID)"
        )


@pytest.fixture(scope="session")
def api_base_url() -> str:
    """Get base API URL from environment or use default LAN"""
    return os.getenv("ML_PLATFORM_URL", TEST_HOSTS["lan"])


@pytest.fixture(scope="session")
def mlflow_tracking_uri(api_base_url: str) -> str:
    """Get MLflow tracking URI"""
    return f"{api_base_url}/mlflow"


@pytest.fixture(scope="session")
def api_v1_url(api_base_url: str) -> str:
    """Get API v1 base URL"""
    return f"{api_base_url}/api/v1"


@pytest.fixture(scope="session")
def test_experiment_name() -> str:
    """Test experiment name"""
    return "test-schema-validation"


@pytest.fixture(scope="session")
def test_tags() -> Dict[str, str]:
    """Standard test tags for run creation"""
    return {"test": "true", "environment": "testing", "developer": "automated-test"}


@pytest.fixture(scope="session")
def incomplete_tags() -> Dict[str, str]:
    """Incomplete tags to test schema validation warnings"""
    return {
        "test": "true"
        # Missing: developer, environment, etc.
    }


# ============================================================================
# Inference Stack Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def inference_base_url() -> str:
    """Get base URL for inference endpoints"""
    return os.getenv("INFERENCE_URL", TEST_HOSTS["local"])


@pytest.fixture(scope="session")
def inference_endpoints() -> Dict[str, str]:
    """Provide inference endpoint paths"""
    return INFERENCE_ENDPOINTS


@pytest.fixture(scope="session")
def llm_url(inference_base_url: str) -> str:
    """Get LLM API URL"""
    return f"{inference_base_url}/api/llm"


@pytest.fixture(scope="session")
def image_url(inference_base_url: str) -> str:
    """Get image generation API URL"""
    return f"{inference_base_url}/api/image"


@pytest.fixture(scope="session")
def gateway_url(inference_base_url: str) -> str:
    """Get inference gateway URL"""
    return f"{inference_base_url}/inference"


@pytest.fixture
def sample_chat_request() -> Dict:
    """Sample chat completion request"""
    return {
        "model": "qwen3-vl-8b",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, can you help me plan a project?"},
        ],
        "max_tokens": 256,
        "temperature": 0.7,
    }


@pytest.fixture
def sample_image_request() -> Dict:
    """Sample image generation request"""
    return {
        "prompt": "A beautiful sunset over mountains, photorealistic, 8k",
        "negative_prompt": "blurry, low quality, cartoon",
        "width": 1024,
        "height": 1024,
        "num_inference_steps": 8,
        "guidance_scale": 1.0,
    }


@pytest.fixture
def mock_chat_response() -> Dict:
    """Mock chat completion response for testing without GPU"""
    import time

    return {
        "id": "chatcmpl-mock-123",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "qwen3-vl-8b",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "I'd be happy to help you plan your project! Let's start by understanding the scope and goals.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 25, "completion_tokens": 20, "total_tokens": 45},
    }


@pytest.fixture
def mock_image_response() -> Dict:
    """Mock image generation response for testing without GPU"""
    import time
    import base64

    # 1x1 pixel transparent PNG
    mock_image = base64.b64encode(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    ).decode()

    return {
        "id": "img-mock-123",
        "created": int(time.time()),
        "data": [{"url": None, "b64_json": mock_image, "revised_prompt": None}],
    }


@pytest.fixture
def mock_health_response() -> Dict:
    """Mock healthy service response"""
    return {
        "status": "healthy",
        "service": "mock-service",
        "model_loaded": True,
        "gpu_available": True,
        "gpu_memory_used_mb": 6500,
        "gpu_memory_total_mb": 8192,
        "uptime_seconds": 3600,
        "version": "1.0.0",
    }


def pytest_addoption(parser):
    """Add custom command line options"""
    parser.addoption(
        "--host",
        action="store",
        default="lan",
        choices=["local", "lan", "vpn", "all"],
        help="Which host to test against: local, lan, vpn, or all",
    )
    parser.addoption(
        "--skip-slow",
        action="store_true",
        default=False,
        help="Skip slow integration tests",
    )


def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "unit: mark test as unit test")
    config.addinivalue_line("markers", "local: test local access")
    config.addinivalue_line("markers", "lan: test LAN access")
    config.addinivalue_line("markers", "vpn: test VPN access")
    config.addinivalue_line("markers", "inference: test inference stack")
    config.addinivalue_line("markers", "gpu: test requires GPU")
    config.addinivalue_line("markers", "security: security-related test")
    config.addinivalue_line("markers", "external: test requires external service")
    config.addinivalue_line("markers", "order: test execution order")
    config.addinivalue_line(
        "markers", "observability: test observability stack services"
    )
    config.addinivalue_line("markers", "authenticated: test requires authentication")
    config.addinivalue_line("markers", "chat_api: test Chat API service")


# =============================================================================
# Chat API Integration Fixtures
# =============================================================================

CHAT_API_URL = os.getenv("CHAT_API_URL", "http://localhost:8000")
CHAT_API_TEST_KEY = os.getenv("CHAT_API_TEST_KEY", "")
CHAT_API_ADMIN_KEY = os.getenv("CHAT_API_ADMIN_KEY", "")
CHAT_API_VIEWER_KEY = os.getenv("CHAT_API_VIEWER_KEY", "")


@pytest.fixture(scope="session")
def chat_api_url() -> str:
    """Get Chat API base URL."""
    return CHAT_API_URL


@pytest.fixture
def valid_chat_request() -> Dict:
    """Sample valid chat completion request."""
    return {
        "messages": [{"role": "user", "content": "Say 'test' and nothing else."}],
        "model": "auto",
        "max_tokens": 50,
    }


@pytest.fixture
def web_chat_request() -> Dict:
    """Chat request from web interface (triggers ask-only mode)."""
    return {
        "messages": [{"role": "user", "content": "What is 2+2?"}],
        "model": "auto",
        "max_tokens": 50,
        "source": "web",
    }


@pytest.fixture
def api_chat_request() -> Dict:
    """Chat request from API/Cursor (full capabilities)."""
    return {
        "messages": [{"role": "user", "content": "What is 2+2?"}],
        "model": "auto",
        "max_tokens": 50,
        "source": "api",
    }


@pytest.fixture(scope="session")
def authenticated_client():
    """Get HTTP client with developer API key auth if available."""
    import requests

    session = requests.Session()
    if CHAT_API_TEST_KEY:
        session.headers["Authorization"] = f"Bearer {CHAT_API_TEST_KEY}"
    return session


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on options"""
    if config.getoption("--skip-slow"):
        skip_slow = pytest.mark.skip(reason="--skip-slow option provided")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)

    # Filter by host if specified
    host_option = config.getoption("--host")
    if host_option != "all":
        skip_marker = pytest.mark.skip(reason=f"--host={host_option} specified")
        for item in items:
            # Skip tests that don't match the selected host
            if host_option == "local" and "lan" in item.keywords:
                item.add_marker(skip_marker)
            elif host_option == "local" and "vpn" in item.keywords:
                item.add_marker(skip_marker)
            elif host_option == "lan" and "vpn" in item.keywords:
                item.add_marker(skip_marker)
            elif host_option == "vpn" and "local" in item.keywords:
                item.add_marker(skip_marker)
            elif host_option == "vpn" and "lan" in item.keywords:
                item.add_marker(skip_marker)


# ===========================================================================
# Unit test fixtures — no live services required
# ===========================================================================

import sys
from unittest.mock import AsyncMock, MagicMock


def _ensure_asyncpg_mock() -> None:
    """Inject a lightweight asyncpg stub so DB-backed code can be imported."""
    if "asyncpg" not in sys.modules:
        mock = MagicMock()
        mock.Pool = MagicMock
        mock.create_pool = AsyncMock(return_value=MagicMock())
        sys.modules["asyncpg"] = mock


_ensure_asyncpg_mock()


@pytest.fixture
def mock_asyncpg_pool():
    """Async mock of an asyncpg connection pool; acts as async context manager."""
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchval = AsyncMock(return_value=None)
    pool.execute = AsyncMock(return_value="OK")
    pool.executemany = AsyncMock(return_value=None)
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=pool)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.fixture
def mock_ray_job_client():
    """Mock of ray.job_submission.JobSubmissionClient."""
    client = MagicMock()
    client.submit_job = MagicMock(return_value="test-job-00001")
    client.get_job_status = MagicMock(return_value=MagicMock(value="RUNNING"))
    client.get_job_info = MagicMock(return_value=MagicMock(
        job_id="test-job-00001", status=MagicMock(value="RUNNING"), message="", entrypoint="",
    ))
    client.list_jobs = MagicMock(return_value=[])
    client.stop_job = MagicMock(return_value=True)
    client.get_job_logs = MagicMock(return_value="")
    return client


@pytest.fixture
def mock_mlflow_client():
    """Mock of mlflow.MlflowClient — use for unit tests that reference MLflow."""
    client = MagicMock()
    client.search_experiments = MagicMock(return_value=[])
    client.get_experiment = MagicMock(return_value=MagicMock(name="test-exp"))
    client.create_experiment = MagicMock(return_value="1")
    client.create_run = MagicMock(return_value=MagicMock(info=MagicMock(run_id="run-001")))
    client.log_metric = MagicMock()
    client.log_param = MagicMock()
    client.set_terminated = MagicMock()
    return client
