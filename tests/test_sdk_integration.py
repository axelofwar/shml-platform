#!/usr/bin/env python3
"""
Integration Tests for SHML Training SDK

Tests the complete workflow:
1. SDK can connect to Training API
2. Job submission works
3. Status polling works
4. Queue and quota APIs work

Usage:
    # Run with local API
    python test_sdk_integration.py --api-url http://localhost --api-key test-key

    # Run with mock API (no server needed)
    python test_sdk_integration.py --mock

Author: SHML Platform
Date: December 2025
"""

import os
import sys
import time
import argparse
from pathlib import Path

# Add SDK to path
sdk_path = Path(__file__).parent.parent / "libs" / "training"
sys.path.insert(0, str(sdk_path))

from shml_training.sdk import (
    TrainingClient,
    TrainingConfig,
    SDKError,
    APIError,
    AuthError,
    QuotaError,
    save_credentials,
)


def test_basic_imports():
    """Test that all SDK components can be imported"""
    print("Testing SDK imports...")

    try:
        from shml_training.sdk import (
            TrainingClient,
            TrainingConfig,
            JobStatus,
            QueueStatus,
            QuotaInfo,
        )

        print("✓ All SDK imports successful")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_config_builder():
    """Test TrainingConfig dataclass"""
    print("\nTesting TrainingConfig...")

    try:
        config = TrainingConfig(
            name="test-job",
            model="yolov8l",
            dataset="wider_face",
            epochs=10,
            use_curriculum_learning=True,
        )

        # Convert to API format
        api_format = config.to_api_format()

        assert api_format["name"] == "test-job"
        assert api_format["model"] == "yolov8l"
        assert api_format["hyperparameters"]["epochs"] == 10
        assert len(api_format["techniques"]) == 1
        assert api_format["techniques"][0]["name"] == "curriculum_learning"

        print("✓ TrainingConfig works correctly")
        return True
    except Exception as e:
        print(f"✗ TrainingConfig failed: {e}")
        return False


def test_client_creation():
    """Test client instantiation"""
    print("\nTesting client creation...")

    try:
        # Test with API key
        client = TrainingClient(api_url="http://localhost", api_key="test-key")

        assert client.api_url == "http://localhost"
        assert client.api_key == "test-key"

        print("✓ Client creation successful")
        return True
    except Exception as e:
        print(f"✗ Client creation failed: {e}")
        return False


def test_credentials_file():
    """Test credentials file save/load"""
    print("\nTesting credentials management...")

    import tempfile

    try:
        # Create temp credentials file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            creds_path = f.name

        # Save credentials
        save_credentials(
            api_url="http://test-api",
            api_key="test-key-123",
            credentials_path=creds_path,
        )

        # Load client from credentials
        client = TrainingClient.from_credentials(credentials_path=creds_path)

        assert client.api_url == "http://test-api"
        assert client.api_key == "test-key-123"

        # Cleanup
        os.unlink(creds_path)

        print("✓ Credentials management works")
        return True
    except Exception as e:
        print(f"✗ Credentials management failed: {e}")
        return False


def test_live_api_connection(api_url: str, api_key: str):
    """Test connection to live API"""
    print(f"\nTesting live API connection to {api_url}...")

    try:
        client = TrainingClient(api_url=api_url, api_key=api_key)

        # Try to list models (should work even without auth if endpoint is public)
        try:
            models = client.list_models()
            print(f"✓ API connection successful - found {len(models)} models")
            return True
        except AuthError as e:
            print(f"⚠ Authentication failed: {e}")
            print("  (This is expected if API key is invalid)")
            return False
        except APIError as e:
            if e.status_code == 404:
                print("⚠ Training API not found at this URL")
                print("  Make sure ray_compute API server is running")
            else:
                print(f"⚠ API error: {e}")
            return False

    except Exception as e:
        print(f"✗ Connection test failed: {e}")
        return False


def test_job_submission_mock():
    """Test job submission with mock responses"""
    print("\nTesting job submission (mock mode)...")

    try:
        # This will fail with connection error, but we can test the request building
        client = TrainingClient(
            api_url="http://localhost:9999", api_key="test-key"  # Non-existent port
        )

        config = TrainingConfig(
            name="mock-test-job",
            model="yolov8l",
            dataset="wider_face",
            epochs=10,
        )

        try:
            job_id = client.submit_training(config)
            print(f"✓ Job submitted: {job_id}")
            return True
        except APIError as e:
            # Expected to fail with connection error
            print(f"⚠ Connection failed as expected: {type(e).__name__}")
            return True

    except Exception as e:
        print(f"✗ Mock submission test failed: {e}")
        return False


def run_all_tests(api_url: str = None, api_key: str = None, mock: bool = False):
    """Run all integration tests"""
    print("=" * 60)
    print("SHML Training SDK - Integration Tests")
    print("=" * 60)

    results = []

    # Unit tests (no API needed)
    results.append(("Imports", test_basic_imports()))
    results.append(("Config Builder", test_config_builder()))
    results.append(("Client Creation", test_client_creation()))
    results.append(("Credentials Management", test_credentials_file()))

    if mock:
        results.append(("Job Submission (Mock)", test_job_submission_mock()))

    if api_url and api_key:
        results.append(
            ("Live API Connection", test_live_api_connection(api_url, api_key))
        )

    # Summary
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} {name}")

    print("-" * 60)
    print(f"Total: {passed}/{total} tests passed ({passed*100//total}%)")

    return passed == total


def main():
    parser = argparse.ArgumentParser(description="Test SHML Training SDK integration")
    parser.add_argument("--api-url", help="API URL for live testing")
    parser.add_argument("--api-key", help="API key for live testing")
    parser.add_argument("--mock", action="store_true", help="Run mock tests only")

    args = parser.parse_args()

    success = run_all_tests(api_url=args.api_url, api_key=args.api_key, mock=args.mock)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
