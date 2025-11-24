"""
Pytest configuration and shared fixtures for ML Platform tests
"""
import pytest
import os
import tempfile
from typing import Dict, List

# Test environment configuration
TEST_HOSTS = {
    "local": "http://localhost",
    "lan": "http://localhost",
    "vpn": "http://${TAILSCALE_IP}"
}

# Set MLflow artifact directory to a temp directory accessible to tests
# This prevents permission issues when trying to write to /mlflow
os.environ.setdefault("MLFLOW_ARTIFACT_ROOT", tempfile.gettempdir() + "/mlflow-test-artifacts")
os.makedirs(os.environ["MLFLOW_ARTIFACT_ROOT"], exist_ok=True)

@pytest.fixture(scope="session")
def test_hosts() -> Dict[str, str]:
    """Provide test host URLs for local, LAN, and VPN access"""
    return TEST_HOSTS

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
    return {
        "test": "true",
        "environment": "testing",
        "developer": "automated-test"
    }

@pytest.fixture(scope="session")
def incomplete_tags() -> Dict[str, str]:
    """Incomplete tags to test schema validation warnings"""
    return {
        "test": "true"
        # Missing: developer, environment, etc.
    }

def pytest_addoption(parser):
    """Add custom command line options"""
    parser.addoption(
        "--host",
        action="store",
        default="lan",
        choices=["local", "lan", "vpn", "all"],
        help="Which host to test against: local, lan, vpn, or all"
    )
    parser.addoption(
        "--skip-slow",
        action="store_true",
        default=False,
        help="Skip slow integration tests"
    )

def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "unit: mark test as unit test")
    config.addinivalue_line("markers", "local: test local access")
    config.addinivalue_line("markers", "lan: test LAN access")
    config.addinivalue_line("markers", "vpn: test VPN access")

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
