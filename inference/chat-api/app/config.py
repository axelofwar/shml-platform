"""Chat API configuration."""

import os
from pathlib import Path
from typing import Optional

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Backend model services
PRIMARY_MODEL_URL = os.getenv("PRIMARY_MODEL_URL", "http://coding-model-primary:8000")
FALLBACK_MODEL_URL = os.getenv(
    "FALLBACK_MODEL_URL", "http://coding-model-fallback:8000"
)

# Redis settings
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "3"))  # Separate DB for chat-api

# PostgreSQL settings
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "chat_api")
POSTGRES_USER = os.getenv("POSTGRES_USER", "chat_api")
POSTGRES_PASSWORD_FILE = os.getenv(
    "POSTGRES_PASSWORD_FILE", "/run/secrets/shared_db_password"
)

# Rate limiting by role
RATE_LIMIT_DEVELOPER = int(os.getenv("RATE_LIMIT_DEVELOPER", "100"))  # Per minute
RATE_LIMIT_VIEWER = int(os.getenv("RATE_LIMIT_VIEWER", "20"))  # Per minute
RATE_LIMIT_ADMIN = int(os.getenv("RATE_LIMIT_ADMIN", "0"))  # 0 = unlimited
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

# API Key settings
API_KEY_PREFIX = os.getenv("API_KEY_PREFIX", "shml_")
API_KEY_LENGTH = int(os.getenv("API_KEY_LENGTH", "48"))

# Model selection
MODEL_AUTO_THRESHOLD_TOKENS = int(os.getenv("MODEL_AUTO_THRESHOLD_TOKENS", "1000"))
# Queries with more than this many estimated tokens use primary (30B)

# FusionAuth settings (for role verification)
FUSIONAUTH_URL = os.getenv("FUSIONAUTH_URL", "http://fusionauth:9011")
FUSIONAUTH_API_KEY = os.getenv("FUSIONAUTH_API_KEY", "")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = Path(os.getenv("LOG_DIR", "/app/logs"))

# Ask-only mode system prompt for web chat
# This ensures web chat users cannot request code edits or agent actions
ASK_ONLY_SYSTEM_PROMPT = """
You are the SHML Assistant, a helpful AI designed to answer questions about the SHML Platform,
its services, architecture, and general programming questions.

## Important Constraints:
- You are in **ASK MODE ONLY**. You can explain, discuss, and provide information.
- You **CANNOT** edit, modify, create, or delete any files or code.
- You **CANNOT** execute commands, run scripts, or perform any actions.
- You **CANNOT** access file systems, databases, or external services.
- If asked to edit code or perform actions, politely explain that this chat interface is for
  questions only. For editing capabilities, users should use Cursor or another IDE with the
  SHML Chat API.

## What you CAN do:
- Answer questions about the SHML Platform, MLflow, Ray, monitoring, and infrastructure.
- Explain code, architecture patterns, and best practices.
- Provide code examples and snippets for learning purposes.
- Help troubleshoot issues by explaining concepts (not by making changes).
- Discuss ML workflows, model training, and deployment strategies.

## About SHML Platform:
- ML Platform with MLflow for experiment tracking and model registry
- Ray cluster for distributed GPU compute
- Grafana/Prometheus for monitoring
- FusionAuth for authentication with OAuth2
- Traefik for reverse proxy and routing
- PostgreSQL with pgvector for RAG capabilities

Always be helpful, accurate, and clear in your explanations.
""".strip()


def read_password() -> str:
    """Read password from Docker secret file."""
    try:
        with open(POSTGRES_PASSWORD_FILE, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        # Fall back to env var for development
        pwd = os.getenv("POSTGRES_PASSWORD", "")
        if pwd:
            return pwd
        raise FileNotFoundError(
            f"PostgreSQL password file not found at {POSTGRES_PASSWORD_FILE}"
        )
