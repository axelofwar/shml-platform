"""
Pytest configuration for integration tests.

Registers custom markers and provides shared fixtures.
"""

import os
import pytest


def pytest_configure(config):
    """Register custom markers for test categorization."""
    config.addinivalue_line(
        "markers",
        "lan: Tests that run against LAN endpoints (requires local network access)",
    )
    config.addinivalue_line(
        "markers",
        "external: Tests that run against external endpoints (Tailscale Funnel)",
    )
    config.addinivalue_line(
        "markers",
        "security: Security-focused tests that verify authentication/authorization",
    )
    config.addinivalue_line(
        "markers", "integration: Full integration tests against live services"
    )


def pytest_collection_modifyitems(config, items):
    """
    Skip LAN tests when SKIP_LAN_TESTS is set (e.g., in CI environments).
    """
    skip_lan = os.getenv("SKIP_LAN_TESTS", "").lower() in ("true", "1", "yes")

    if skip_lan:
        skip_lan_marker = pytest.mark.skip(
            reason="LAN tests skipped (SKIP_LAN_TESTS=true)"
        )
        for item in items:
            if "lan" in item.keywords:
                item.add_marker(skip_lan_marker)


@pytest.fixture(scope="session")
def public_domain():
    """Get the public domain for external tests."""
    return os.getenv("PUBLIC_DOMAIN", "shml-platform.tail38b60a.ts.net")


@pytest.fixture(scope="session")
def lan_ip():
    """Get the LAN IP for internal tests."""
    return os.getenv("LAN_IP", "10.0.0.163")
