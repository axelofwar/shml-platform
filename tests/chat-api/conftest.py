"""Pytest configuration for Chat API tests."""

import pytest
import asyncio
from typing import AsyncGenerator, Dict, Any
from unittest.mock import AsyncMock, MagicMock


# We'll mock the database and redis for unit tests
@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db():
    """Mock database for unit tests."""
    mock = AsyncMock()

    # Setup default returns
    mock.validate_api_key.return_value = None
    mock.get_active_instructions.return_value = []
    mock.create_conversation.return_value = "conv_test123"
    mock.add_message.return_value = None
    mock.log_usage.return_value = None

    return mock


@pytest.fixture
def mock_redis():
    """Mock Redis for unit tests."""
    mock = AsyncMock()
    mock.check.return_value = {
        "remaining": 100,
        "limit": 100,
        "reset_at": None,
    }
    mock.record.return_value = True
    return mock


@pytest.fixture
def mock_model_router():
    """Mock model router for unit tests."""
    mock = AsyncMock()
    mock.get_model_status.return_value = {
        "primary": MagicMock(
            id="qwen3-coder-30b",
            name="Qwen3 Coder 30B",
            is_available=True,
            gpu="RTX 3090 Ti",
        ),
        "fallback": MagicMock(
            id="qwen2.5-coder-3b",
            name="Qwen2.5 Coder 3B",
            is_available=True,
            gpu="RTX 2070",
        ),
    }
    return mock


@pytest.fixture
def sample_user_developer():
    """Sample developer user."""
    import sys

    sys.path.insert(0, "/home/axelofwar/Projects/shml-platform/inference/chat-api")
    from app.schemas import User, UserRole

    return User(
        id="user_dev123",
        email="developer@example.com",
        name="Test Developer",
        role=UserRole.DEVELOPER,
        groups=["developer"],
        auth_method="oauth",
    )


@pytest.fixture
def sample_user_admin():
    """Sample admin user."""
    import sys

    sys.path.insert(0, "/home/axelofwar/Projects/shml-platform/inference/chat-api")
    from app.schemas import User, UserRole

    return User(
        id="user_admin123",
        email="admin@example.com",
        name="Test Admin",
        role=UserRole.ADMIN,
        groups=["admin"],
        auth_method="oauth",
    )


@pytest.fixture
def sample_user_viewer():
    """Sample viewer user."""
    import sys

    sys.path.insert(0, "/home/axelofwar/Projects/shml-platform/inference/chat-api")
    from app.schemas import User, UserRole

    return User(
        id="user_viewer123",
        email="viewer@example.com",
        name="Test Viewer",
        role=UserRole.VIEWER,
        groups=["viewer"],
        auth_method="oauth",
    )


@pytest.fixture
def sample_api_key_user():
    """Sample user authenticated via API key."""
    import sys

    sys.path.insert(0, "/home/axelofwar/Projects/shml-platform/inference/chat-api")
    from app.schemas import User, UserRole

    return User(
        id="user_apikey123",
        email=None,
        name=None,
        role=UserRole.DEVELOPER,
        groups=[],
        auth_method="api_key",
        api_key_id="key_test123",
    )


@pytest.fixture
def valid_chat_request():
    """Valid chat completion request."""
    return {
        "messages": [{"role": "user", "content": "Hello, how are you?"}],
        "model": "auto",
        "temperature": 0.7,
        "max_tokens": 1024,
    }


@pytest.fixture
def web_chat_request():
    """Chat request from web interface (ask-only mode)."""
    return {
        "messages": [
            {"role": "user", "content": "What is the architecture of SHML Platform?"}
        ],
        "model": "auto",
        "source": "web",
    }


@pytest.fixture
def api_chat_request():
    """Chat request from API (full capabilities)."""
    return {
        "messages": [
            {"role": "user", "content": "Refactor this function to use async/await"}
        ],
        "model": "auto",
        "source": "api",
    }
