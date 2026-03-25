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
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestUserUsageAndQuota:
    def _patch_job_model(self):
        fake_job = type("Job", (), {})
        fake_job.user_id = MagicMock(name="Job.user_id")
        fake_job.created_at = MagicMock(name="Job.created_at")
        fake_job.status = MagicMock(name="Job.status")
        fake_job.job_id = MagicMock(name="Job.job_id")
        fake_job.status.in_ = MagicMock(return_value=MagicMock(name="Job.status.in_"))
        fake_job.created_at.__ge__ = MagicMock(return_value=MagicMock(name="Job.created_at.ge"))
        fake_job.user_id.__eq__ = MagicMock(return_value=MagicMock(name="Job.user_id.eq"))
        return patch("ray_compute.api.usage_tracking.Job", new=fake_job)

    def _make_job(
        self,
        started_at: datetime,
        ended_at: datetime,
        gpu_requested: Decimal = Decimal("1.0"),
        cpu_requested: int = 10,
        user_id: str = "user-1",
    ):
        return SimpleNamespace(
            started_at=started_at,
            ended_at=ended_at,
            gpu_requested=gpu_requested,
            cpu_requested=cpu_requested,
            user_id=user_id,
            job_id="job-1",
        )

    def _make_db(self, jobs=None, concurrent_count: int = 0):
        jobs = jobs or []
        db = MagicMock()
        query = MagicMock()
        filtered = MagicMock()
        filtered.all.return_value = jobs
        filtered.count.return_value = concurrent_count
        query.filter.return_value = filtered
        db.query.return_value = query
        return db

    def test_get_user_usage_day_aggregates_jobs(self):
        from ray_compute.api.usage_tracking import get_user_usage

        jobs = [
            self._make_job(datetime(2024, 1, 1, 0, 0, 0), datetime(2024, 1, 1, 1, 0, 0)),
            self._make_job(datetime(2024, 1, 1, 2, 0, 0), datetime(2024, 1, 1, 2, 30, 0), gpu_requested=Decimal("0.5"), cpu_requested=4),
        ]
        db = self._make_db(jobs=jobs)

        with self._patch_job_model():
            result = get_user_usage("user-1", db, period="day")

        assert result["job_count"] == 2
        assert result["gpu_hours"] == Decimal("1.25")
        assert result["cpu_hours"] == Decimal("1.2")
        assert result["period_start"].hour == 0

    def test_get_user_usage_month_starts_on_first_day(self):
        from ray_compute.api.usage_tracking import get_user_usage

        db = self._make_db(jobs=[])
        with self._patch_job_model():
            result = get_user_usage("user-1", db, period="month")

        assert result["period_start"].day == 1
        assert result["period_start"].hour == 0

    def test_get_user_usage_all_uses_fixed_epoch_start(self):
        from ray_compute.api.usage_tracking import get_user_usage

        db = self._make_db(jobs=[])
        with self._patch_job_model():
            result = get_user_usage("user-1", db, period="all")

        assert result["period_start"] == datetime(2020, 1, 1)

    def test_get_user_quota_remaining_day(self):
        from ray_compute.api.usage_tracking import get_user_quota_remaining

        user = SimpleNamespace(user_id="user-1", role="premium")
        quota = SimpleNamespace(
            max_gpu_hours_per_day=Decimal("5.0"),
            max_cpu_hours_per_day=Decimal("10.0"),
            max_concurrent_jobs=4,
        )
        db = self._make_db(concurrent_count=2)

        with patch("ray_compute.api.usage_tracking.get_user_usage", return_value={"gpu_hours": Decimal("1.5"), "cpu_hours": Decimal("3.0")}):
            result = get_user_quota_remaining(user, quota, db, period="day")

        assert result["gpu_hours_remaining"] == Decimal("3.5")
        assert result["cpu_hours_remaining"] == Decimal("7.0")
        assert result["concurrent_jobs"] == 2
        assert result["percent_used"] == 30.0

    def test_get_user_quota_remaining_month_unlimited_admin(self):
        from ray_compute.api.usage_tracking import get_user_quota_remaining

        user = SimpleNamespace(user_id="user-1", role="admin")
        quota = SimpleNamespace(
            max_gpu_hours_per_day=Decimal("100.0"),
            max_cpu_hours_per_day=Decimal("1000.0"),
            max_concurrent_jobs=20,
        )
        db = self._make_db(concurrent_count=1)

        with patch("ray_compute.api.usage_tracking.get_user_usage", return_value={"gpu_hours": Decimal("2.0"), "cpu_hours": Decimal("4.0")}):
            result = get_user_quota_remaining(user, quota, db, period="month")

        assert result["gpu_hours_limit"] == Decimal("999999.0")
        assert result["cpu_hours_limit"] == Decimal("999999.0")
        assert result["percent_used"] > 0

    def test_get_user_quota_remaining_zero_limits_guard_percent(self):
        from ray_compute.api.usage_tracking import get_user_quota_remaining

        user = SimpleNamespace(user_id="user-1", role="user")
        quota = SimpleNamespace(
            max_gpu_hours_per_day=Decimal("0.0"),
            max_cpu_hours_per_day=Decimal("0.0"),
            max_concurrent_jobs=1,
        )
        db = self._make_db(concurrent_count=0)

        with patch("ray_compute.api.usage_tracking.get_user_usage", return_value={"gpu_hours": Decimal("0.0"), "cpu_hours": Decimal("0.0")}):
            result = get_user_quota_remaining(user, quota, db, period="day")

        assert result["percent_used"] == 0


class TestQuotaEnforcement:
    def test_check_quota_available_gpu_exceeded(self):
        from ray_compute.api.usage_tracking import check_quota_available

        with patch(
            "ray_compute.api.usage_tracking.get_user_quota_remaining",
            return_value={
                "gpu_hours_remaining": Decimal("0.5"),
                "gpu_hours_limit": Decimal("1.0"),
                "cpu_hours_remaining": Decimal("5.0"),
                "cpu_hours_limit": Decimal("10.0"),
                "concurrent_jobs": 0,
                "concurrent_jobs_limit": 2,
            },
        ):
            allowed, reason = check_quota_available(MagicMock(), MagicMock(), MagicMock(), 1.0, 1.0)

        assert allowed is False
        assert "Insufficient GPU quota" in reason

    def test_check_quota_available_cpu_exceeded(self):
        from ray_compute.api.usage_tracking import check_quota_available

        with patch(
            "ray_compute.api.usage_tracking.get_user_quota_remaining",
            return_value={
                "gpu_hours_remaining": Decimal("5.0"),
                "gpu_hours_limit": Decimal("10.0"),
                "cpu_hours_remaining": Decimal("0.25"),
                "cpu_hours_limit": Decimal("1.0"),
                "concurrent_jobs": 0,
                "concurrent_jobs_limit": 2,
            },
        ):
            allowed, reason = check_quota_available(MagicMock(), MagicMock(), MagicMock(), 0.5, 1.0)

        assert allowed is False
        assert "Insufficient CPU quota" in reason

    def test_check_quota_available_concurrent_jobs_exceeded(self):
        from ray_compute.api.usage_tracking import check_quota_available

        with patch(
            "ray_compute.api.usage_tracking.get_user_quota_remaining",
            return_value={
                "gpu_hours_remaining": Decimal("5.0"),
                "gpu_hours_limit": Decimal("10.0"),
                "cpu_hours_remaining": Decimal("5.0"),
                "cpu_hours_limit": Decimal("10.0"),
                "concurrent_jobs": 2,
                "concurrent_jobs_limit": 2,
            },
        ):
            allowed, reason = check_quota_available(MagicMock(), MagicMock(), MagicMock(), 0.5, 1.0)

        assert allowed is False
        assert "Maximum concurrent jobs reached" in reason

    def test_check_quota_available_success(self):
        from ray_compute.api.usage_tracking import check_quota_available

        with patch(
            "ray_compute.api.usage_tracking.get_user_quota_remaining",
            return_value={
                "gpu_hours_remaining": Decimal("5.0"),
                "gpu_hours_limit": Decimal("10.0"),
                "cpu_hours_remaining": Decimal("5.0"),
                "cpu_hours_limit": Decimal("10.0"),
                "concurrent_jobs": 1,
                "concurrent_jobs_limit": 2,
            },
        ):
            allowed, reason = check_quota_available(MagicMock(), MagicMock(), MagicMock(), 0.5, 1.0)

        assert allowed is True
        assert reason is None

    def test_enforce_quota_raises_daily_limit(self):
        from ray_compute.api.usage_tracking import enforce_quota
        from fastapi import HTTPException

        user = SimpleNamespace(username="alice")
        with patch(
            "ray_compute.api.usage_tracking.check_quota_available",
            side_effect=[(False, "daily blocked")],
        ):
            with pytest.raises(HTTPException) as exc_info:
                enforce_quota(user, MagicMock(), MagicMock(), 1.0, 1.0, job_name="train")

        assert exc_info.value.status_code == 429
        assert exc_info.value.detail["period"] == "day"

    def test_enforce_quota_raises_monthly_limit(self):
        from ray_compute.api.usage_tracking import enforce_quota
        from fastapi import HTTPException

        user = SimpleNamespace(username="alice")
        with patch(
            "ray_compute.api.usage_tracking.check_quota_available",
            side_effect=[(True, None), (False, "monthly blocked")],
        ):
            with pytest.raises(HTTPException) as exc_info:
                enforce_quota(user, MagicMock(), MagicMock(), 1.0, 1.0, job_name="train")

        assert exc_info.value.status_code == 429
        assert exc_info.value.detail["period"] == "month"


class TestUsageUpdatesAndAnalytics:
    def _patch_models(self):
        fake_job = type("Job", (), {})
        fake_job.user_id = MagicMock(name="Job.user_id")
        fake_job.created_at = MagicMock(name="Job.created_at")
        fake_job.status = MagicMock(name="Job.status")
        fake_job.job_id = MagicMock(name="Job.job_id")
        fake_job.status.in_ = MagicMock(return_value=MagicMock(name="Job.status.in_"))
        fake_job.created_at.__ge__ = MagicMock(return_value=MagicMock(name="Job.created_at.ge"))
        fake_job.user_id.__eq__ = MagicMock(return_value=MagicMock(name="Job.user_id.eq"))
        fake_job.job_id.__eq__ = MagicMock(return_value=MagicMock(name="Job.job_id.eq"))

        fake_user = type("User", (), {})
        fake_user.user_id = MagicMock(name="User.user_id")
        fake_user.is_active = MagicMock(name="User.is_active")
        fake_user.user_id.__eq__ = MagicMock(return_value=MagicMock(name="User.user_id.eq"))
        fake_user.is_active.__eq__ = MagicMock(return_value=MagicMock(name="User.is_active.eq"))

        return patch("ray_compute.api.usage_tracking.Job", new=fake_job), patch(
            "ray_compute.api.usage_tracking.User", new=fake_user
        )

    def _make_db_for_first(self, obj):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = obj
        return db

    def test_update_job_usage_missing_job(self):
        from ray_compute.api.usage_tracking import update_job_usage

        db = self._make_db_for_first(None)
        job_patch, _ = self._patch_models()
        with job_patch:
            gpu_hours, cpu_hours = update_job_usage("missing-job", db)

        assert gpu_hours == Decimal("0.0")
        assert cpu_hours == Decimal("0.0")
        db.commit.assert_not_called()

    def test_update_job_usage_success(self):
        from ray_compute.api.usage_tracking import update_job_usage

        job = SimpleNamespace(
            job_id="job-1",
            started_at=datetime(2024, 1, 1, 0, 0, 0),
            ended_at=datetime(2024, 1, 1, 2, 0, 0),
            gpu_requested=Decimal("0.5"),
            cpu_requested=10,
        )
        db = self._make_db_for_first(job)

        job_patch, _ = self._patch_models()
        with job_patch:
            gpu_hours, cpu_hours = update_job_usage("job-1", db)

        assert gpu_hours == Decimal("1.0")
        assert cpu_hours == Decimal("2.0")
        assert job.gpu_used_hours == Decimal("1.0")
        assert job.cpu_used_hours == Decimal("2.0")
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_job_completion_no_job(self):
        from ray_compute.api.usage_tracking import record_job_completion

        db = self._make_db_for_first(None)

        job_patch, _ = self._patch_models()
        with job_patch, patch("ray_compute.api.usage_tracking.log_audit_event", new=AsyncMock()) as mock_audit:
            await record_job_completion("missing", "user-1", db, "FAILED")

        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_record_job_completion_updates_usage_and_audits(self):
        from ray_compute.api.usage_tracking import record_job_completion

        job = SimpleNamespace(
            job_id="job-1",
            started_at=datetime(2024, 1, 1, 0, 0, 0),
            ended_at=datetime(2024, 1, 1, 1, 0, 0),
            gpu_requested=Decimal("1.0"),
            cpu_requested=10,
        )
        db = self._make_db_for_first(job)

        job_patch, _ = self._patch_models()
        with job_patch, patch(
            "ray_compute.api.usage_tracking.update_job_usage",
            return_value=(Decimal("1.0"), Decimal("1.0")),
        ) as mock_update, patch(
            "ray_compute.api.usage_tracking.log_audit_event",
            new=AsyncMock(),
        ) as mock_audit:
            await record_job_completion("job-1", "user-1", db, "SUCCEEDED")

        mock_update.assert_called_once_with("job-1", db)
        mock_audit.assert_awaited_once()

    def test_reset_monthly_usage_returns_summary(self):
        from ray_compute.api.usage_tracking import reset_monthly_usage

        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = 7

        _, user_patch = self._patch_models()
        with user_patch:
            result = reset_monthly_usage(db)

        assert result["users_reset"] == 7
        assert result["jobs_processed"] == 0
        assert "calculated dynamically" in result["message"]

    def test_adjust_user_quota_updates_known_fields_only(self):
        from ray_compute.api.usage_tracking import adjust_user_quota

        quota = SimpleNamespace(max_concurrent_jobs=1, max_gpu_hours_per_day=Decimal("1.0"))
        db = self._make_db_for_first(quota)

        updated = adjust_user_quota(
            "user-1",
            db,
            max_concurrent_jobs=5,
            max_gpu_hours_per_day=Decimal("2.5"),
            nonexistent=123,
        )

        assert updated.max_concurrent_jobs == 5
        assert updated.max_gpu_hours_per_day == Decimal("2.5")
        assert not hasattr(updated, "nonexistent")
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(quota)

    def test_adjust_user_quota_not_found(self):
        from ray_compute.api.usage_tracking import adjust_user_quota
        from fastapi import HTTPException

        db = self._make_db_for_first(None)

        with pytest.raises(HTTPException) as exc_info:
            adjust_user_quota("user-1", db, max_concurrent_jobs=2)

        assert exc_info.value.status_code == 404

    def test_initialize_user_quota_uses_tier_limits(self):
        from ray_compute.api.usage_tracking import initialize_user_quota

        user = SimpleNamespace(user_id="user-1", username="alice", role="premium")
        db = MagicMock()

        with patch("ray_compute.api.usage_tracking.UserQuota") as mock_quota_cls:
            quota_instance = SimpleNamespace()
            mock_quota_cls.return_value = quota_instance
            result = initialize_user_quota(user, db)

        assert result is quota_instance
        mock_quota_cls.assert_called_once()
        kwargs = mock_quota_cls.call_args.kwargs
        assert kwargs["user_id"] == "user-1"
        assert kwargs["max_concurrent_jobs"] == 5
        db.add.assert_called_once_with(quota_instance)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(quota_instance)

    def test_get_platform_usage_stats_aggregates_jobs_and_tiers(self):
        from ray_compute.api.usage_tracking import get_platform_usage_stats

        jobs = [
            SimpleNamespace(
                job_id="job-1",
                user_id="user-1",
                started_at=datetime(2024, 1, 1, 0, 0, 0),
                ended_at=datetime(2024, 1, 1, 1, 0, 0),
                gpu_requested=Decimal("1.0"),
                cpu_requested=10,
            ),
            SimpleNamespace(
                job_id="job-2",
                user_id="user-2",
                started_at=datetime(2024, 1, 1, 0, 0, 0),
                ended_at=datetime(2024, 1, 1, 2, 0, 0),
                gpu_requested=Decimal("0.5"),
                cpu_requested=5,
            ),
        ]
        users = {
            "user-1": SimpleNamespace(user_id="user-1", role="premium"),
            "user-2": SimpleNamespace(user_id="user-2", role="admin"),
        }

        db = MagicMock()
        job_query = MagicMock()
        job_filter = MagicMock()
        job_filter.all.return_value = jobs
        job_query.filter.return_value = job_filter

        user_query = MagicMock()
        user_filter = MagicMock()
        user_filter.first.side_effect = [users["user-1"], users["user-2"]]
        user_query.filter.return_value = user_filter

        def _query_side_effect(model):
            model_name = getattr(model, "__name__", None)
            if model_name == "Job":
                return job_query
            if model_name == "User":
                return user_query
            return MagicMock()

        db.query.side_effect = _query_side_effect

        job_patch, user_patch = self._patch_models()
        with job_patch, user_patch:
            result = get_platform_usage_stats(db, days=7)

        assert result["total_jobs"] == 2
        assert result["active_users"] == 2
        assert result["total_gpu_hours"] == 2.0
        assert result["usage_by_tier"]["premium"] == 1
        assert result["usage_by_tier"]["admin"] == 1
        assert result["period_days"] == 7
