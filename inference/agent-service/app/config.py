"""Configuration for Agent Service."""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Agent service configuration."""

    # Service settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Gateway URLs
    GATEWAY_URL: str = os.getenv("GATEWAY_URL", "http://qwen-coding:8000")
    FALLBACK_MODEL_URL: str = os.getenv(
        "FALLBACK_MODEL_URL", "http://coding-model-fallback:8000"
    )
    ORCHESTRATOR_URL: str = f"{GATEWAY_URL}/v1/orchestrate/chat"
    # Qwen manager for GPU yield (pause inference during training)
    QWEN_MANAGER_URL: str = os.getenv("QWEN_MANAGER_URL", "http://qwen-manager:8000")

    # Tier 0: shl-nano local nano-model (T8.4) — fast domain-specialized model
    # Set NANO_ENDPOINT to enable tier-0 routing before local Qwen/Nemotron
    NANO_ENDPOINT: str = os.getenv("NANO_ENDPOINT", "")   # e.g. http://shl-nano:8021
    NANO_CONFIDENCE_THRESHOLD: float = float(
        os.getenv("NANO_CONFIDENCE_THRESHOLD", "0.55")
    )
    # Max latency allowed for nano (ms) — bailout to tier-1 if exceeded
    NANO_LATENCY_THRESHOLD_MS: float = float(
        os.getenv("NANO_LATENCY_THRESHOLD_MS", "2000.0")
    )

    # Cloud failover (T5.1) — OpenAI-compatible endpoint for when local models fail
    CLOUD_FALLBACK_URL: str = os.getenv("CLOUD_FALLBACK_URL", "")
    CLOUD_API_KEY: str = os.getenv("CLOUD_API_KEY", "")
    CLOUD_FALLBACK_MODEL: str = os.getenv("CLOUD_FALLBACK_MODEL", "gpt-4o-mini")
    # Trigger handoff after N consecutive local failures (default 3)
    CLOUD_FAILOVER_THRESHOLD: int = int(os.getenv("CLOUD_FAILOVER_THRESHOLD", "3"))
    # Trigger handoff when observed latency exceeds this (seconds, default 30)
    CLOUD_LATENCY_THRESHOLD_SECONDS: float = float(
        os.getenv("CLOUD_LATENCY_THRESHOLD_SECONDS", "30.0")
    )

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

    # -------------------------------------------------------------------------
    # NemoClaw / OpenShell settings
    # -------------------------------------------------------------------------
    # Factory sidecar URL (sandbox lifecycle REST API)
    NEMOCLAW_FACTORY_URL: str = os.getenv(
        "NEMOCLAW_FACTORY_URL", "http://nemoclaw-sandbox-factory:9095"
    )
    # OpenShell gateway URL (policy engine + MCP proxy)
    NEMOCLAW_GATEWAY_URL: str = os.getenv(
        "NEMOCLAW_GATEWAY_URL", "http://openshell-gateway:9090"
    )
    # Path to blueprint directory (mounted into factory + gateway containers)
    NEMOCLAW_BLUEPRINTS_PATH: str = os.getenv(
        "NEMOCLAW_BLUEPRINTS_PATH", "/opt/shml-platform/nemoclaw-blueprint"
    )
    # When True, OpenShellSkill falls back to legacy SandboxSkill on factory unavailability
    NEMOCLAW_FALLBACK_TO_DOCKER: bool = os.getenv(
        "NEMOCLAW_FALLBACK_TO_DOCKER", "true"
    ).lower() == "true"
    # Cloud inference endpoint routed through NemoClaw (nimcloud profile)
    # Overrides CLOUD_FALLBACK_URL — NemoClaw intercepts and audits cloud calls
    NEMOCLAW_CLOUD_PROFILE_ENABLED: bool = os.getenv(
        "NEMOCLAW_CLOUD_PROFILE_ENABLED", "false"
    ).lower() == "true"
    # Health check timeout for factory sidecar (seconds)
    NEMOCLAW_FACTORY_TIMEOUT: int = int(os.getenv("NEMOCLAW_FACTORY_TIMEOUT", "60"))

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
