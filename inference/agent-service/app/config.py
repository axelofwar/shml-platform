"""Configuration for Agent Service."""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Agent service configuration."""

    # Service settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Gateway URLs
    GATEWAY_URL: str = os.getenv("GATEWAY_URL", "http://inference-gateway:8000")
    FALLBACK_MODEL_URL: str = os.getenv(
        "FALLBACK_MODEL_URL", "http://coding-model-fallback:8000"
    )
    ORCHESTRATOR_URL: str = f"{GATEWAY_URL}/v1/orchestrate/chat"

    # Redis for state management
    REDIS_HOST: str = os.getenv("REDIS_HOST", "inference-redis")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")

    # PostgreSQL for audit logging and agent data
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "inference-postgres")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "inference_gateway")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "inference")
    POSTGRES_PASSWORD: str = ""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Read password from file if PASSWORD_FILE is set
        password_file = os.getenv("POSTGRES_PASSWORD_FILE")
        if password_file and os.path.exists(password_file):
            with open(password_file) as f:
                self.POSTGRES_PASSWORD = f.read().strip()
        else:
            self.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

    @property
    def database_url(self) -> str:
        """Construct async PostgreSQL URL."""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Sandbox settings (Using runc with strong isolation since KVM not available)
    # Note: Kata Containers requires KVM which is not available on this system
    # Using runc with network isolation, memory limits, and read-only root filesystem
    KATA_RUNTIME: str = "runc"  # Changed from "kata" to "runc"
    MAX_SANDBOXES: int = 10
    SANDBOX_TIMEOUT_SECONDS: int = 600  # 10 minutes
    SANDBOX_DISK_LIMIT_GB: int = 10
    SANDBOX_MEMORY_LIMIT_GB: int = 4  # Per sandbox

    # Agent settings
    MAX_AGENT_ITERATIONS: int = 15
    AGENT_THINKING_TIMEOUT: int = 300  # 5 minutes per step

    # FusionAuth for GitHub token storage
    FUSIONAUTH_URL: str = os.getenv("FUSIONAUTH_URL", "http://fusionauth:9011")
    FUSIONAUTH_API_KEY: str = os.getenv("FUSIONAUTH_API_KEY", "")

    # Role permissions
    CODE_EXEC_ROLES: list[str] = ["elevated-developer", "admin"]
    GITHUB_WRITE_ROLES: list[str] = ["elevated-developer", "admin"]
    GITHUB_READ_ROLES: list[str] = [
        "viewer",
        "developer",
        "elevated-developer",
        "admin",
    ]

    class Config:
        env_file = ".env"


settings = Settings()
