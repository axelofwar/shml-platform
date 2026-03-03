"""
Configuration management for SHML Client SDK.

Handles:
- Environment variables
- ~/.shml/credentials file
- Constructor overrides
"""

import os
from pathlib import Path
from typing import Optional
from configparser import ConfigParser
from dataclasses import dataclass


DEFAULT_BASE_URL = "https://shml-platform.tail38b60a.ts.net"
CREDENTIALS_FILE = Path.home() / ".shml" / "credentials"


@dataclass
class Config:
    """Client configuration."""

    base_url: str
    api_key: Optional[str] = None
    oauth_token: Optional[str] = None
    profile: str = "default"


def load_credentials_file(profile: str = "default") -> dict:
    """
    Load credentials from ~/.shml/credentials file.

    File format (INI):
        [default]
        api_key = shml_xxx
        base_url = https://...

        [dev]
        api_key = shml_yyy
        base_url = http://localhost:8000
    """
    if not CREDENTIALS_FILE.exists():
        return {}

    parser = ConfigParser()
    parser.read(CREDENTIALS_FILE)

    if profile not in parser:
        return {}

    return dict(parser[profile])


def save_credentials(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    oauth_token: Optional[str] = None,
    profile: str = "default",
):
    """
    Save credentials to ~/.shml/credentials file.

    Creates the file with 600 permissions if it doesn't exist.
    """
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)

    parser = ConfigParser()

    # Load existing config
    if CREDENTIALS_FILE.exists():
        parser.read(CREDENTIALS_FILE)

    # Update profile
    if profile not in parser:
        parser[profile] = {}

    if api_key:
        parser[profile]["api_key"] = api_key
    if base_url:
        parser[profile]["base_url"] = base_url
    if oauth_token:
        parser[profile]["oauth_token"] = oauth_token

    # Write with secure permissions
    with open(CREDENTIALS_FILE, "w") as f:
        parser.write(f)

    # Set file permissions to 600 (owner read/write only)
    CREDENTIALS_FILE.chmod(0o600)


def get_config(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    oauth_token: Optional[str] = None,
    profile: str = "default",
) -> Config:
    """
    Get configuration from all sources.

    Priority (highest to lowest):
    1. Constructor arguments
    2. Environment variables
    3. Credentials file
    4. Defaults
    """
    # Load from credentials file
    creds = load_credentials_file(profile)

    # Resolve each setting
    resolved_base_url = (
        base_url
        or os.getenv("SHML_BASE_URL")
        or creds.get("base_url")
        or DEFAULT_BASE_URL
    )

    resolved_api_key = api_key or os.getenv("SHML_API_KEY") or creds.get("api_key")

    resolved_oauth_token = (
        oauth_token or os.getenv("SHML_OAUTH_TOKEN") or creds.get("oauth_token")
    )

    return Config(
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        oauth_token=resolved_oauth_token,
        profile=profile,
    )
