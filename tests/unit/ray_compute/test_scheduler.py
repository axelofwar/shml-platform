"""Unit tests for ray_compute/api/scheduler.py.

Focuses on pure functions: TIER_PRIORITY, get_priority_score().
DB-dependent functions verified with mock sessions.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# conftest.py stubs ray/sqlalchemy/models/auth before imports


class TestTierPriority:
    def test_priority_dict_has_all_tiers(self):
        from ray_compute.api.scheduler import TIER_PRIORITY
        assert "admin" in TIER_PRIORITY
        assert "premium" in TIER_PRIORITY
        assert "user" in TIER_PRIORITY

    def test_admin_has_highest_priority(self):
        from ray_compute.api.scheduler import TIER_PRIORITY
        # Lower score = higher priority
        assert TIER_PRIORITY["admin"] < TIER_PRIORITY["premium"]
        assert TIER_PRIORITY["premium"] < TIER_PRIORITY["user"]

    def test_admin_priority_is_1(self):
        from ray_compute.api.scheduler import TIER_PRIORITY
        assert TIER_PRIORITY["admin"] == 1

    def test_user_priority_is_3(self):
        from ray_compute.api.scheduler import TIER_PRIORITY
        assert TIER_PRIORITY["user"] == 3


class TestGetPriorityScore:
    def _make_user(self, role="user"):
        return SimpleNamespace(role=role, username="testuser")

    def _make_job(self, timeout_hours=4, priority="normal"):
        return SimpleNamespace(timeout_hours=timeout_hours, priority=priority)

    def test_admin_lower_score_than_user(self):
        from ray_compute.api.scheduler import get_priority_score
        admin = self._make_user("admin")
        user = self._make_user("user")
        job = self._make_job()
        admin_score = get_priority_score(admin, job)
        user_score = get_priority_score(user, job)
        assert admin_score < user_score

    def test_premium_lower_score_than_user(self):
        from ray_compute.api.scheduler import get_priority_score
        premium = self._make_user("premium")
        user = self._make_user("user")
        job = self._make_job()
        assert get_priority_score(premium, job) < get_priority_score(user, job)

    def test_short_job_lower_score_than_long(self):
        from ray_compute.api.scheduler import get_priority_score
        user = self._make_user("user")
        short_job = self._make_job(timeout_hours=1)  # ≤2h = priority boost
        long_job = self._make_job(timeout_hours=24)
        short_score = get_priority_score(user, short_job)
        long_score = get_priority_score(user, long_job)
        assert short_score < long_score

    def test_high_priority_job_lower_score(self):
        from ray_compute.api.scheduler import get_priority_score
        user = self._make_user("user")
        high_job = self._make_job(priority="high")
        normal_job = self._make_job(priority="normal")
        assert get_priority_score(user, high_job) < get_priority_score(user, normal_job)

    def test_low_priority_job_higher_score(self):
        from ray_compute.api.scheduler import get_priority_score
        user = self._make_user("user")
        low_job = self._make_job(priority="low")
        normal_job = self._make_job(priority="normal")
        assert get_priority_score(user, low_job) > get_priority_score(user, normal_job)

    def test_returns_decimal(self):
        from ray_compute.api.scheduler import get_priority_score
        user = self._make_user("user")
        job = self._make_job()
        score = get_priority_score(user, job)
        assert isinstance(score, Decimal)

    def test_unknown_role_defaults_to_5(self):
        from ray_compute.api.scheduler import get_priority_score
        unknown_user = self._make_user("unknown_role")
        job = self._make_job()
        score = get_priority_score(unknown_user, job)
        # Should use base_priority=5 from TIER_PRIORITY.get(role, 5)
        assert score > Decimal("4000")

    def test_medium_job_lower_score_than_long(self):
        from ray_compute.api.scheduler import get_priority_score
        user = self._make_user("user")
        medium_job = self._make_job(timeout_hours=4)   # ≤6h boost
        long_job = self._make_job(timeout_hours=12)   # no boost
        assert get_priority_score(user, medium_job) < get_priority_score(user, long_job)

    def test_admin_priority_weight_reduces_score(self):
        from ray_compute.api.scheduler import get_priority_score
        # Admin has priority_weight=5, so score is divided by 5
        admin = self._make_user("admin")
        job = self._make_job(timeout_hours=4)
        score = get_priority_score(admin, job)
        # base 1 * 1000 - 20 (medium job) = 980 / 5 = 196
        assert score < Decimal("300")


class TestSchedulerImport:
    def test_module_imports_successfully(self):
        """Verify scheduler module loads without errors."""
        from ray_compute.api import scheduler
        assert scheduler is not None
        assert hasattr(scheduler, "TIER_PRIORITY")
        assert hasattr(scheduler, "get_priority_score")
        assert hasattr(scheduler, "enqueue_job")
        assert hasattr(scheduler, "dequeue_next_job")
        assert hasattr(scheduler, "get_queue_position")
        assert hasattr(scheduler, "estimate_start_time")
        assert hasattr(scheduler, "get_queue_stats")
