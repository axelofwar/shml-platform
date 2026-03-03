"""Tests for SHML SDK Client and Job classes."""

import pytest

from shml.client import Client, Job


# ── Job Tests ────────────────────────────────────────────────────────────


class TestJob:
    """Verify Job data container."""

    @pytest.mark.unit
    def test_construction(self):
        job = Job(job_id="abc-123", name="test-job", status="RUNNING")
        assert job.job_id == "abc-123"
        assert job.name == "test-job"
        assert job.status == "RUNNING"

    @pytest.mark.unit
    def test_extra_field(self):
        job = Job(job_id="x", name="y", status="PENDING", gpu=1)
        assert job.extra["gpu"] == 1


# ── Client Tests ─────────────────────────────────────────────────────────


class TestClient:
    """Verify Client construction and context manager."""

    @pytest.mark.unit
    def test_construction_defaults(self):
        client = Client()
        assert client is not None

    @pytest.mark.unit
    def test_context_manager(self):
        with Client() as client:
            assert client is not None

    @pytest.mark.unit
    def test_close_is_idempotent(self):
        client = Client()
        client.close()
        client.close()  # should not raise
