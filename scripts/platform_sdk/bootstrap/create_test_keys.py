"""
Bootstrap script to create test API keys for CI/CD.

This script creates admin, developer, and viewer API keys
in FusionAuth for testing the Platform SDK.
"""

import os
import sys
import httpx

# FusionAuth configuration
FUSIONAUTH_URL = os.environ.get("FUSIONAUTH_URL", "http://localhost:9011")
SETUP_API_KEY = os.environ.get("FUSIONAUTH_SETUP_KEY", "")


def create_api_key(
    description: str,
    permissions: dict = None,
    meta_data: dict = None,
) -> dict:
    """Create an API key in FusionAuth."""
    url = f"{FUSIONAUTH_URL}/api/api-key"

    headers = {
        "Content-Type": "application/json",
    }

    # If we have a setup key, use it
    if SETUP_API_KEY:
        headers["Authorization"] = SETUP_API_KEY

    key_data = {
        "apiKey": {
            "description": description,
        }
    }

    if permissions:
        key_data["apiKey"]["permissions"] = {"endpoints": permissions}

    if meta_data:
        key_data["apiKey"]["metaData"] = meta_data

    response = httpx.post(url, headers=headers, json=key_data, timeout=30)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error creating key: {response.status_code}")
        print(response.text)
        return None


def main():
    """Create test API keys."""
    print("=" * 60)
    print("Platform SDK - Test API Key Bootstrap")
    print("=" * 60)
    print(f"FusionAuth URL: {FUSIONAUTH_URL}")
    print()

    # Check FusionAuth is available
    try:
        status_response = httpx.get(f"{FUSIONAUTH_URL}/api/status", timeout=10)
        if status_response.status_code != 200:
            print(f"FusionAuth not ready: {status_response.status_code}")
            sys.exit(1)
        print("✓ FusionAuth is available")
    except Exception as e:
        print(f"Cannot connect to FusionAuth: {e}")
        sys.exit(1)

    # Create Admin Key (no restrictions)
    print("\n1. Creating Admin API Key...")
    admin_result = create_api_key(
        description="[CI/CD] Admin API Key for Platform SDK Tests",
        meta_data={"role": "admin", "created_by": "bootstrap"},
    )

    if admin_result:
        admin_key = admin_result.get("apiKey", {}).get("key", "")
        admin_id = admin_result.get("apiKey", {}).get("id", "")
        print(f"   ✓ Created: {admin_id}")
        print(f"   Key: {admin_key[:8]}...{admin_key[-4:]}")

    # Create Developer Key (limited permissions)
    print("\n2. Creating Developer API Key...")
    developer_permissions = {
        "/api/user": ["GET"],
        "/api/user/search": ["POST"],
        "/api/group": ["GET"],
        "/api/group/search": ["GET"],
        "/api/group/member/search": ["GET"],
        "/api/application": ["GET"],
        "/api/application/search": ["POST"],
        "/api/user/registration": ["GET", "POST"],
        "/api/api-key": ["GET"],
    }

    developer_result = create_api_key(
        description="[CI/CD] Developer API Key for Platform SDK Tests",
        permissions=developer_permissions,
        meta_data={"role": "developer", "created_by": "bootstrap"},
    )

    if developer_result:
        dev_key = developer_result.get("apiKey", {}).get("key", "")
        dev_id = developer_result.get("apiKey", {}).get("id", "")
        print(f"   ✓ Created: {dev_id}")
        print(f"   Key: {dev_key[:8]}...{dev_key[-4:]}")

    # Create Viewer Key (read-only)
    print("\n3. Creating Viewer API Key...")
    viewer_permissions = {
        "/api/user": ["GET"],
        "/api/user/search": ["POST"],
        "/api/group": ["GET"],
        "/api/group/search": ["GET"],
        "/api/group/member/search": ["GET"],
        "/api/application": ["GET"],
        "/api/user/registration": ["GET"],
        "/api/api-key": ["GET"],
    }

    viewer_result = create_api_key(
        description="[CI/CD] Viewer API Key for Platform SDK Tests",
        permissions=viewer_permissions,
        meta_data={"role": "viewer", "created_by": "bootstrap"},
    )

    if viewer_result:
        viewer_key = viewer_result.get("apiKey", {}).get("key", "")
        viewer_id = viewer_result.get("apiKey", {}).get("id", "")
        print(f"   ✓ Created: {viewer_id}")
        print(f"   Key: {viewer_key[:8]}...{viewer_key[-4:]}")

    # Output for GitHub Actions
    print("\n" + "=" * 60)
    print("GitHub Actions Secrets to Set:")
    print("=" * 60)

    if admin_result:
        admin_key = admin_result.get("apiKey", {}).get("key", "")
        print(f"FUSIONAUTH_API_KEY={admin_key}")

    if developer_result:
        dev_key = developer_result.get("apiKey", {}).get("key", "")
        print(f"FUSIONAUTH_DEVELOPER_KEY={dev_key}")

    if viewer_result:
        viewer_key = viewer_result.get("apiKey", {}).get("key", "")
        print(f"FUSIONAUTH_VIEWER_KEY={viewer_key}")

    print("\n✓ Bootstrap complete!")


if __name__ == "__main__":
    main()
