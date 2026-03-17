"""Base configuration for inference services.

Provides common settings that all inference services share.
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings


def get_postgres_password() -> str:
    """Read PostgreSQL password from file or environment."""
    password_file = os.getenv("POSTGRES_PASSWORD_FILE")
    if password_file and os.path.exists(password_file):
        with open(password_file) as f:
            return f.read().strip()
    return os.getenv("POSTGRES_PASSWORD", "")


class BaseInferenceSettings(BaseSettings):
    """Base settings shared by all inference services."""

    # Service settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # PostgreSQL connection (shared across services)
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "inference-postgres")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "inference_gateway")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "inference")
    POSTGRES_PASSWORD: str = ""

    # Redis connection (shared across services)
    REDIS_HOST: str = os.getenv("REDIS_HOST", "inference-redis")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")

    # FusionAuth integration
    FUSIONAUTH_URL: str = os.getenv("FUSIONAUTH_URL", "http://fusionauth:9011")
    FUSIONAUTH_API_KEY: str = os.getenv("FUSIONAUTH_API_KEY", "")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.POSTGRES_PASSWORD = get_postgres_password()

    @property
    def database_url(self) -> str:
        """Construct async PostgreSQL URL."""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def redis_url(self) -> str:
        """Construct Redis URL."""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}"

    class Config:
        env_file = ".env"
