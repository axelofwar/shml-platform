"""
Platform SDK Configuration.

Handles configuration loading from environment variables, files, and direct input.
Follows 12-factor app principles with sensible defaults.
"""

import os
from typing import Optional
from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv


class SDKConfig(BaseModel):
    """
    SDK Configuration with validation.

    Configuration sources (in priority order):
    1. Direct initialization parameters
    2. Environment variables
    3. .env file
    4. Default values

    Example:
        # From environment
        config = SDKConfig()

        # Direct configuration
        config = SDKConfig(
            api_key="your-key",
            fusionauth_url="http://localhost:9011"
        )
    """

    # Authentication
    api_key: str = Field(
        default="", description="FusionAuth API key for authentication"
    )

    # FusionAuth settings
    fusionauth_url: str = Field(
        default="http://localhost:9011", description="FusionAuth server URL"
    )
    fusionauth_tenant_id: Optional[str] = Field(
        default=None, description="FusionAuth tenant ID (optional for single-tenant)"
    )

    # HTTP settings
    timeout: float = Field(
        default=30.0, ge=1.0, le=300.0, description="Request timeout in seconds"
    )
    max_retries: int = Field(
        default=3, ge=0, le=10, description="Maximum retry attempts for failed requests"
    )
    retry_delay: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Initial delay between retries (exponential backoff)",
    )

    # Rate limiting
    rate_limit_calls: int = Field(
        default=10, ge=1, le=100, description="Maximum API calls per rate_limit_period"
    )
    rate_limit_period: float = Field(
        default=1.0, ge=0.1, le=60.0, description="Rate limit period in seconds"
    )

    # Connection pool
    max_connections: int = Field(
        default=10, ge=1, le=100, description="Maximum concurrent connections"
    )

    # Logging
    log_level: str = Field(
        default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )

    model_config = {
        "extra": "ignore",  # Ignore unknown fields
        "validate_assignment": True,  # Validate on attribute assignment
    }

    @field_validator("api_key", mode="before")
    @classmethod
    def load_api_key(cls, v: str) -> str:
        """Load API key from environment if not provided."""
        if v:
            return v
        return os.environ.get("FUSIONAUTH_API_KEY", "")

    @field_validator("fusionauth_url", mode="before")
    @classmethod
    def load_fusionauth_url(cls, v: str) -> str:
        """Load FusionAuth URL from environment if not provided."""
        if v and v != "http://localhost:9011":
            return v.rstrip("/")
        url = os.environ.get("FUSIONAUTH_URL", v)
        return url.rstrip("/") if url else "http://localhost:9011"

    @field_validator("fusionauth_tenant_id", mode="before")
    @classmethod
    def load_tenant_id(cls, v: Optional[str]) -> Optional[str]:
        """Load tenant ID from environment if not provided."""
        if v:
            return v
        return os.environ.get("FUSIONAUTH_TENANT_ID")

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate and normalize log level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v = (v or "INFO").upper()
        if v not in valid_levels:
            v = "INFO"
        return v

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "SDKConfig":
        """
        Create config from environment variables.

        Args:
            env_file: Path to .env file (optional)

        Returns:
            SDKConfig instance
        """
        # Load .env file if specified or exists
        if env_file:
            load_dotenv(env_file)
        else:
            # Try common locations
            for path in [".env", "../.env", "../../.env"]:
                if Path(path).exists():
                    load_dotenv(path)
                    break

        # Explicitly pass environment values to bypass default field values
        return cls(
            api_key=os.environ.get("FUSIONAUTH_API_KEY", ""),
            fusionauth_url=os.environ.get("FUSIONAUTH_URL", "http://localhost:9011"),
            fusionauth_tenant_id=os.environ.get("FUSIONAUTH_TENANT_ID"),
            timeout=float(os.environ.get("SDK_TIMEOUT", "30.0")),
            log_level=os.environ.get("SDK_LOG_LEVEL", "INFO"),
        )

    def validate_connection(self) -> bool:
        """
        Validate that required configuration is present.

        Returns:
            True if configuration is valid

        Raises:
            ValueError if configuration is invalid
        """
        if not self.api_key:
            raise ValueError(
                "API key is required. Set FUSIONAUTH_API_KEY environment variable "
                "or pass api_key parameter."
            )

        if not self.fusionauth_url:
            raise ValueError(
                "FusionAuth URL is required. Set FUSIONAUTH_URL environment variable "
                "or pass fusionauth_url parameter."
            )

        return True

    def __repr__(self) -> str:
        """Safe representation that hides sensitive data."""
        api_key_display = f"{self.api_key[:8]}..." if self.api_key else "NOT SET"
        return (
            f"SDKConfig("
            f"api_key='{api_key_display}', "
            f"fusionauth_url='{self.fusionauth_url}', "
            f"timeout={self.timeout})"
        )
