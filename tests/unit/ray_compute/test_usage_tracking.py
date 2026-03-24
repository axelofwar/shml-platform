"""Unit tests for ray_compute/api/usage_tracking.py.

Focuses on pure functions (no DB) and verifies structure.
DB-dependent functions are tested with mocked Session objects.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# conftest.py stubs ray/sqlalchemy/models/auth before imports


class TestTierLimits:
    def test_user_tier_keys(self):
        from ray_compute.api.usage_tracking import TIER_LIMITS
        tier = TIER_LIMITS["user"]
        assert "max_gpu_hours_per_day" in tier
        assert "max_cpu_hours_per_day" in tier
        assert "max_concurrent_jobs" in tier
        assert "max_gpu_fraction" in tier
        assert "monthly_gpu_hours" in tier
        assert "monthly_cpu_hours" in tier

    def test_premium_tier_better_than_user(self):
        from ray_compute.api.usage_tracking import TIER_LIMITS
        assert TIER_LIMITS["premium"]["max_gpu_hours_per_day"] > TIER_LIMITS["user"]["max_gpu_hours_per_day"]
        assert TIER_LIMITS["premium"]["max_concurrent_jobs"] > TIER_LIMITS["user"]["max_concurrent_jobs"]

    def test_admin_tier_highest_limits(self):
        from ray_compute.api.usage_tracking import TIER_LIMITS
        assert TIER_LIMITS["admin"]["max_gpu_hours_per_day"] > TIER_LIMITS["premium"]["max_gpu_hours_per_day"]
        assert TIER_LIMITS["admin"]["max_concurrent_jobs"] > TIER_LIMITS["premium"]["max_concurrent_jobs"]

    def test_admin_unlimited_monthly(self):
        from ray_compute.api.usage_tracking import TIER_LIMITS
        assert TIER_LIMITS["admin"]["monthly_gpu_hours"] == "unlimited"
        assert TIER_LIMITS["admin"]["monthly_cpu_hours"] == "unlimited"

    def test_three_tiers_defined(self):
        from ray_compute.api.usage_tracking import TIER_LIMITS
        assert "user" in TIER_LIMITS
        assert "premium" in TIER_LIMITS
        assert "admin" in TIER_LIMITS

    def test_user_no_techniques(self):
        from ray_compute.api.usage_tracking import TIER_LIMITS
        assert TIER_LIMITS["user"]["techniques_allowed"] == []

    def test_admin_all_techniques(self):
        from ray_compute.api.usage_tracking import TIER_LIMITS
        assert TIER_LIMITS["admin"]["techniques_allowed"] == "*"

    def test_user_cannot_use_custom_docker(self):
        from ray_compute.api.usage_tracking import TIER_LIMITS
        assert TIER_LIMITS["user"]["can_use_custom_docker"] is False

    def test_admin_can_use_custom_docker(self):
        from ray_compute.api.usage_tracking import TIER_LIMITS
        assert TIER_LIMITS["admin"]["can_use_custom_docker"] is True


class TestGetTierLimits:
    def test_user_tier(self):
        from ray_compute.api.usage_tracking import get_tier_limits, TIER_LIMITS
        result = get_tier_limits("user")
        assert result == TIER_LIMITS["user"]

    def test_premium_tier(self):
        from ray_compute.api.usage_tracking import get_tier_limits, TIER_LIMITS
        result = get_tier_limits("premium")
        assert result == TIER_LIMITS["premium"]

    def test_admin_tier(self):
        from ray_compute.api.usage_tracking import get_tier_limits, TIER_LIMITS
        result = get_tier_limits("admin")
        assert result == TIER_LIMITS["admin"]

    def test_unknown_tier_defaults_to_user(self):
        from ray_compute.api.usage_tracking import get_tier_limits, TIER_LIMITS
        result = get_tier_limits("unknown_role")
        assert result == TIER_LIMITS["user"]

    def test_empty_string_defaults_to_user(self):
        from ray_compute.api.usage_tracking import get_tier_limits, TIER_LIMITS
        result = get_tier_limits("")
        assert result == TIER_LIMITS["user"]


class TestCalculateJobUsage:
    def _make_job(self, started_at=None, ended_at=None, gpu_requested=Decimal("1.00"), cpu_requested=Decimal("4")):
        job = SimpleNamespace(
            started_at=started_at,
            ended_at=ended_at,
            gpu_requested=gpu_requested,
            cpu_requested=cpu_requested,
        )
        return job

    def test_no_times_returns_zero(self):
        from ray_compute.api.usage_tracking import calculate_job_usage
        job = self._make_job()
        gpu_h, cpu_h = calculate_job_usage(job)
        assert gpu_h == Decimal("0.0")
        assert cpu_h == Decimal("0.0")

    def test_only_started_at_returns_zero(self):
        from ray_compute.api.usage_tracking import calculate_job_usage
        job = self._make_job(started_at=datetime(2024, 1, 1, 0, 0, 0))
        gpu_h, cpu_h = calculate_job_usage(job)
        assert gpu_h == Decimal("0.0")
        assert cpu_h == Decimal("0.0")

    def test_one_hour_full_gpu(self):
        from ray_compute.api.usage_tracking import calculate_job_usage
        start = datetime(2024, 1, 1, 0, 0, 0)
        end = datetime(2024, 1, 1, 1, 0, 0)  # 1 hour
        job = self._make_job(started_at=start, ended_at=end, gpu_requested=Decimal("1.00"), cpu_requested=Decimal("10"))
        gpu_h, cpu_h = calculate_job_usage(job)
        assert gpu_h == pytest.approx(Decimal("1.0"), rel=1e-4)
        assert cpu_h == pytest.approx(Decimal("1.0"), rel=1e-4)  # 1h * 10cores / 10

    def test_half_gpu_fraction(self):
        from ray_compute.api.usage_tracking import calculate_job_usage
        start = datetime(2024, 1, 1, 0, 0, 0)
        end = datetime(2024, 1, 1, 2, 0, 0)  # 2 hours
        job = self._make_job(started_at=start, ended_at=end, gpu_requested=Decimal("0.50"), cpu_requested=Decimal("4"))
        gpu_h, cpu_h = calculate_job_usage(job)
        assert gpu_h == pytest.approx(Decimal("1.0"), rel=1e-4)   # 2h * 0.5 = 1 GPU hour
        assert cpu_h == pytest.approx(Decimal("0.8"), rel=1e-4)   # 2h * (4/10) = 0.8

    def test_30_minute_job(self):
        from ray_compute.api.usage_tracking import calculate_job_usage
        start = datetime(2024, 1, 1, 10, 0, 0)
        end = datetime(2024, 1, 1, 10, 30, 0)  # 30 minutes
        job = self._make_job(started_at=start, ended_at=end, gpu_requested=Decimal("1.00"), cpu_requested=Decimal("4"))
        gpu_h, cpu_h = calculate_job_usage(job)
        assert gpu_h == pytest.approx(Decimal("0.5"), rel=1e-4)
        assert cpu_h == pytest.approx(Decimal("0.2"), rel=1e-4)

    def test_returns_tuple_of_decimals(self):
        from ray_compute.api.usage_tracking import calculate_job_usage
        start = datetime(2024, 1, 1, 0, 0, 0)
        end = datetime(2024, 1, 1, 1, 0, 0)
        job = self._make_job(started_at=start, ended_at=end)
        result = calculate_job_usage(job)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], Decimal)
        assert isinstance(result[1], Decimal)
