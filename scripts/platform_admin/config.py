"""
Configuration management for Platform Admin SDK.

Loads configuration from environment variables or .env file.
"""

import os
from pathlib import Path
from typing import Optional


class Config:
    """Configuration for FusionAuth connection."""

    def __init__(
        self,
        fusionauth_url: Optional[str] = None,
        api_key: Optional[str] = None,
        env_file: Optional[str] = None,
    ):
        """
        Initialize configuration.

        Args:
            fusionauth_url: FusionAuth server URL (e.g., http://localhost:9011)
            api_key: FusionAuth API key
            env_file: Path to .env file (auto-detected if not specified)
        """
        # Try to load from .env if not provided
        if env_file is None:
            env_file = self._find_env_file()

        if env_file:
            self._load_env_file(env_file)

        # Set values with fallbacks
        self.fusionauth_url = (
            fusionauth_url
            or os.environ.get("FUSIONAUTH_URL")
            or os.environ.get("FUSIONAUTH_ISSUER")
            or "http://localhost:9011"
        )

        self.api_key = api_key or os.environ.get("FUSIONAUTH_API_KEY")

        # Clean up URL (remove trailing slash)
        self.fusionauth_url = self.fusionauth_url.rstrip("/")

    def _find_env_file(self) -> Optional[str]:
        """Find the .env file by searching up the directory tree."""
        current = Path(__file__).resolve().parent

        # Search patterns
        for _ in range(5):  # Max 5 levels up
            # Check common locations
            for name in [".env", "secrets/.env", "../.env"]:
                env_path = current / name
                if env_path.exists():
                    return str(env_path)
            current = current.parent

        return None

    def _load_env_file(self, path: str) -> None:
        """Load environment variables from a file."""
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        # Remove quotes if present
                        if value and value[0] in ('"', "'") and value[-1] == value[0]:
                            value = value[1:-1]
                        # Don't override existing env vars
                        if key not in os.environ:
                            os.environ[key] = value
        except Exception as e:
            print(f"Warning: Could not load {path}: {e}")

    def validate(self) -> bool:
        """Validate that required configuration is present."""
        return bool(self.fusionauth_url and self.api_key)

    def prompt_for_missing(self) -> None:
        """Interactively prompt for missing configuration values."""
        if not self.fusionauth_url:
            self.fusionauth_url = input(
                "FusionAuth URL [http://localhost:9011]: "
            ).strip()
            if not self.fusionauth_url:
                self.fusionauth_url = "http://localhost:9011"

        if not self.api_key:
            self.api_key = input("FusionAuth API Key: ").strip()

    def __repr__(self) -> str:
        api_key_display = f"{self.api_key[:8]}..." if self.api_key else "None"
        return f"Config(url={self.fusionauth_url}, api_key={api_key_display})"
