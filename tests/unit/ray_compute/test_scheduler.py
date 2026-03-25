from __future__ import annotations

import asyncio
import sys
import types
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest


_orig_usage_tracking = sys.modules.get("ray_compute.api.usage_tracking")
_usage_tracking = types.ModuleType("ray_compute.api.usage_tracking")
_usage_tracking.get_tier_limits = MagicMock(return_value={"priority_weight": 1})
sys.modules["ray_compute.api.usage_tracking"] = _usage_tracking

import ray_compute.api.scheduler as scheduler

if _orig_usage_tracking is None:
    if sys.modules.get("ray_compute.api.usage_tracking") is _usage_tracking:
        del sys.modules["ray_compute.api.usage_tracking"]
else:
    sys.modules["ray_compute.api.usage_tracking"] = _orig_usage_tracking


def _user(role: str = "user"):
    return types.SimpleNamespace(user_id=uuid.uuid4(), username=role, role=role)


def _job(**overrides):
    job = types.SimpleNamespace(
        job_id="job-1",
        timeout_hours=4,
        priority="normal",
        gpu_requested=0.5,
        started_at=None,
        ended_at=None,
        status="QUEUED",
    )
    for key, value in overrides.items():
        setattr(job, key, value)
    return job


def _queue_entry(**overrides):
    entry = types.SimpleNamespace(
        job_id="job-1",
        user_id=uuid.uuid4(),
        priority_score=Decimal("1000"),
        queued_at=datetime(2024, 1, 1, 0, 0, 0),
        started_at=None,
        completed_at=None,
        status="QUEUED",
    )
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


class _Col:
    def in_(self, values):
        return MagicMock()

    def __eq__(self, other):
        return MagicMock()

    def __lt__(self, other):
        return MagicMock()

    def __ge__(self, other):
        return MagicMock()

    def isnot(self, other):
        return MagicMock()

    def asc(self):
        return MagicMock()

    def desc(self):
        return MagicMock()


class _JobQueueModel:
    job_id = _Col()
    user_id = _Col()
    status = _Col()
    priority_score = _Col()
    queued_at = _Col()

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


@pytest.fixture(autouse=True)
def reset_scheduler_state():
    original_user_id = getattr(scheduler.User, "user_id", None)
    original_job_id = getattr(scheduler.Job, "job_id", None)
    original_job_status = getattr(scheduler.Job, "status", None)
    original_job_started_at = getattr(scheduler.Job, "started_at", None)
    original_job_ended_at = getattr(scheduler.Job, "ended_at", None)
    original_job_queue = scheduler.JobQueue

    scheduler.get_tier_limits = MagicMock(return_value={"priority_weight": 1})
    scheduler.gpu_allocator = scheduler.GPUAllocation()
    scheduler.User.user_id = _Col()
    scheduler.Job.job_id = _Col()
    scheduler.Job.status = _Col()
    scheduler.Job.started_at = _Col()
    scheduler.Job.ended_at = _Col()
    scheduler.JobQueue = _JobQueueModel

    yield

    scheduler.User.user_id = original_user_id
    scheduler.Job.job_id = original_job_id
    scheduler.Job.status = original_job_status
    scheduler.Job.started_at = original_job_started_at
    scheduler.Job.ended_at = original_job_ended_at
    scheduler.JobQueue = original_job_queue


class TestPriorityScore:
    def test_priority_score_uses_tier_timeout_and_priority_adjustments(self):
        scheduler.get_tier_limits.return_value = {"priority_weight": 5}

        result = scheduler.get_priority_score(
            _user("premium"),
            _job(timeout_hours=2, priority="high"),
        )

        assert result == Decimal("370")

    def test_priority_score_defaults_unknown_role(self):
        result = scheduler.get_priority_score(
            _user("guest"),
            _job(timeout_hours=10, priority="low"),
        )

        assert result == Decimal("5100")


class TestQueueFunctions:
    def test_enqueue_job_adds_queue_entry(self):
        job = _job(job_id="job-99")
        user = _user("admin")
        db = MagicMock()
        query_job = MagicMock()
        query_job.filter.return_value.first.return_value = job
        query_user = MagicMock()
        query_user.filter.return_value.first.return_value = user
        db.query.side_effect = [query_job, query_user]
        db.refresh.side_effect = lambda entry: setattr(entry, "refreshed", True)

        entry = scheduler.enqueue_job("job-99", str(user.user_id), db)

        assert entry.job_id == "job-99"
        assert entry.user_id == str(user.user_id)
        assert entry.status == "QUEUED"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_enqueue_job_raises_for_missing_records(self):
        db = MagicMock()
        query = MagicMock()
        query.filter.return_value.first.return_value = None
        db.query.return_value = query

        with pytest.raises(ValueError, match="not found"):
            scheduler.enqueue_job("job-1", "user-1", db)

    def test_dequeue_next_job_marks_entry_running(self):
        entry = _queue_entry()
        db = MagicMock()
        query = MagicMock()
        query.filter.return_value.order_by.return_value.first.return_value = entry
        db.query.return_value = query

        result = scheduler.dequeue_next_job(db)

        assert result is entry
        assert entry.status == "RUNNING"
        assert entry.started_at is not None
        db.commit.assert_called_once()

    def test_get_queue_position_returns_none_when_missing(self):
        db = MagicMock()
        first_query = MagicMock()
        first_query.filter.return_value.first.return_value = None
        db.query.return_value = first_query

        assert scheduler.get_queue_position("job-1", db) is None

    def test_get_queue_position_is_count_plus_one(self):
        entry = _queue_entry(priority_score=Decimal("2000"))
        db = MagicMock()
        first_query = MagicMock()
        first_query.filter.return_value.first.return_value = entry
        second_query = MagicMock()
        second_query.filter.return_value.count.return_value = 3
        db.query.side_effect = [first_query, second_query]

        assert scheduler.get_queue_position("job-1", db) == 4

    def test_estimate_start_time_returns_none_if_not_queued(self, monkeypatch):
        monkeypatch.setattr(scheduler, "get_queue_position", MagicMock(return_value=None))

        assert scheduler.estimate_start_time("job-1", MagicMock()) is None

    def test_estimate_start_time_returns_now_if_first_and_no_running_jobs(self, monkeypatch):
        monkeypatch.setattr(scheduler, "get_queue_position", MagicMock(return_value=1))
        db = MagicMock()
        running_query = MagicMock()
        running_query.filter.return_value.all.return_value = []
        db.query.return_value = running_query

        result = scheduler.estimate_start_time("job-1", db)

        assert isinstance(result, datetime)

    def test_estimate_start_time_uses_running_job_finish(self, monkeypatch):
        monkeypatch.setattr(scheduler, "get_queue_position", MagicMock(return_value=1))
        started_at = datetime.utcnow() - timedelta(hours=1)
        running_job = _job(started_at=started_at, timeout_hours=4, status="RUNNING")
        db = MagicMock()
        running_query = MagicMock()
        running_query.filter.return_value.all.return_value = [running_job]
        db.query.return_value = running_query

        result = scheduler.estimate_start_time("job-1", db)

        assert result >= started_at + timedelta(hours=4)

    def test_estimate_start_time_uses_recent_average_duration(self, monkeypatch):
        monkeypatch.setattr(scheduler, "get_queue_position", MagicMock(return_value=3))
        recent_jobs = [
            _job(
                started_at=datetime(2024, 1, 1, 0, 0, 0),
                ended_at=datetime(2024, 1, 1, 2, 0, 0),
            ),
            _job(
                started_at=datetime(2024, 1, 1, 1, 0, 0),
                ended_at=datetime(2024, 1, 1, 4, 0, 0),
            ),
        ]
        db = MagicMock()
        completed_query = MagicMock()
        completed_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = recent_jobs
        db.query.return_value = completed_query

        result = scheduler.estimate_start_time("job-1", db)

        assert isinstance(result, datetime)

    def test_remove_from_queue_updates_status(self):
        entry = _queue_entry()
        db = MagicMock()
        query = MagicMock()
        query.filter.return_value.first.return_value = entry
        db.query.return_value = query

        scheduler.remove_from_queue("job-1", db, reason="cancelled")

        assert entry.status == "CANCELLED"
        assert entry.completed_at is not None
        db.commit.assert_called_once()

    def test_get_queue_stats_summarizes_counts_and_waits(self):
        queued = [
            _queue_entry(user_id="u1", queued_at=datetime.utcnow() - timedelta(minutes=20)),
            _queue_entry(user_id="u2", queued_at=datetime.utcnow() - timedelta(minutes=40)),
        ]
        running = [_queue_entry(status="RUNNING")]
        queued_query = MagicMock()
        queued_query.filter.return_value.all.return_value = queued
        running_query = MagicMock()
        running_query.filter.return_value.all.return_value = running
        user_query_1 = MagicMock()
        user_query_1.filter.return_value.first.return_value = _user("premium")
        user_query_2 = MagicMock()
        user_query_2.filter.return_value.first.return_value = _user("admin")
        db = MagicMock()
        db.query.side_effect = [queued_query, running_query, user_query_1, user_query_2]

        result = scheduler.get_queue_stats(db)

        assert result["queued_count"] == 2
        assert result["running_count"] == 1
        assert result["queued_by_tier"]["premium"] == 1
        assert result["queued_by_tier"]["admin"] == 1
        assert result["avg_wait_minutes"] > 0


class TestGPUAllocation:
    def test_allocate_and_deallocate(self):
        allocator = scheduler.GPUAllocation()

        assert allocator.can_allocate(0.5) is True
        assert allocator.allocate("job-1", 0.5) is True
        assert allocator.rtx3090_available == 0.5

        allocator.deallocate("job-1")

        assert allocator.rtx3090_available == 1.0

    def test_allocate_rejects_insufficient_capacity(self):
        allocator = scheduler.GPUAllocation()

        assert allocator.allocate("job-1", 1.1) is False

    def test_get_status_reports_allocations(self):
        allocator = scheduler.GPUAllocation()
        allocator.rtx2070_allocated = True
        allocator.allocate("job-1", 0.25)

        result = allocator.get_status()

        assert result["rtx2070"]["allocated"] == 1.0
        assert result["rtx3090"]["active_jobs"] == 1
        assert result["rtx3090"]["jobs"] == {"job-1": 0.25}


class TestTrainingScheduler:
    @pytest.mark.asyncio
    async def test_submit_job_starts_immediately_when_gpu_available(self, monkeypatch):
        db = MagicMock()
        sched = scheduler.TrainingScheduler(db)
        entry = _queue_entry(job_id="job-1")
        monkeypatch.setattr(scheduler, "enqueue_job", MagicMock(return_value=entry))
        sched.gpu_allocator = MagicMock()
        sched.gpu_allocator.can_allocate.return_value = True
        sched.gpu_allocator.allocate.return_value = True

        result = await sched.submit_job("job-1", "user-1", 0.5)

        assert result["status"] == "RUNNING"
        assert result["queue_position"] == 0
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_job_returns_queue_status_when_not_started(self, monkeypatch):
        db = MagicMock()
        sched = scheduler.TrainingScheduler(db)
        monkeypatch.setattr(scheduler, "enqueue_job", MagicMock(return_value=_queue_entry(job_id="job-2")))
        monkeypatch.setattr(scheduler, "get_queue_position", MagicMock(return_value=4))
        monkeypatch.setattr(
            scheduler,
            "estimate_start_time",
            MagicMock(return_value=datetime(2024, 1, 2, 3, 4, 5)),
        )
        sched.gpu_allocator = MagicMock()
        sched.gpu_allocator.can_allocate.return_value = False

        result = await sched.submit_job("job-2", "user-2", 0.75)

        assert result == {
            "job_id": "job-2",
            "status": "QUEUED",
            "queue_position": 4,
            "estimated_start_time": "2024-01-02T03:04:05",
            "message": "Job queued at position 4",
        }

    def test_cancel_job_removes_queue_releases_gpu_and_schedules_processing(self, monkeypatch):
        db = MagicMock()
        sched = scheduler.TrainingScheduler(db)
        sched.gpu_allocator = MagicMock()
        monkeypatch.setattr(scheduler, "remove_from_queue", MagicMock())

        def _consume(coro):
            coro.close()
            return MagicMock()

        monkeypatch.setattr(asyncio, "create_task", MagicMock(side_effect=_consume))

        assert sched.cancel_job("job-1") is True
        scheduler.remove_from_queue.assert_called_once_with("job-1", db, reason="cancelled")
        sched.gpu_allocator.deallocate.assert_called_once_with("job-1")
        asyncio.create_task.assert_called_once()

    def test_complete_job_releases_resources_and_processes_queue(self, monkeypatch):
        db = MagicMock()
        sched = scheduler.TrainingScheduler(db)
        sched.gpu_allocator = MagicMock()
        monkeypatch.setattr(scheduler, "remove_from_queue", MagicMock())

        def _consume(coro):
            coro.close()
            return MagicMock()

        monkeypatch.setattr(asyncio, "create_task", MagicMock(side_effect=_consume))

        sched.complete_job("job-1", "failed")

        scheduler.remove_from_queue.assert_called_once_with("job-1", db, reason="failed")
        sched.gpu_allocator.deallocate.assert_called_once_with("job-1")
        asyncio.create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_queue_starts_next_job(self, monkeypatch):
        db = MagicMock()
        sched = scheduler.TrainingScheduler(db)
        entry = _queue_entry(job_id="job-1")
        job = _job(job_id="job-1", gpu_requested=0.25)
        monkeypatch.setattr(
            scheduler,
            "dequeue_next_job",
            MagicMock(side_effect=[entry, None]),
        )
        sched.gpu_allocator = MagicMock()
        sched.gpu_allocator.can_allocate.return_value = True
        sched.gpu_allocator.allocate.return_value = True
        db.query.return_value.filter.return_value.first.return_value = job

        await sched.process_queue()

        sched.gpu_allocator.allocate.assert_called_once_with("job-1", 0.25)

    @pytest.mark.asyncio
    async def test_process_queue_requeues_when_resources_unavailable(self, monkeypatch):
        db = MagicMock()
        sched = scheduler.TrainingScheduler(db)
        entry = _queue_entry(job_id="job-1", status="RUNNING", started_at=datetime.utcnow())
        job = _job(job_id="job-1", gpu_requested=1.0)
        monkeypatch.setattr(
            scheduler,
            "dequeue_next_job",
            MagicMock(return_value=entry),
        )
        sched.gpu_allocator = MagicMock()
        sched.gpu_allocator.can_allocate.return_value = False
        db.query.return_value.filter.return_value.first.return_value = job

        await sched.process_queue()

        assert entry.status == "QUEUED"
        assert entry.started_at is None
        db.commit.assert_called_once()

    def test_get_job_status_returns_not_in_queue(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        sched = scheduler.TrainingScheduler(db)

        result = sched.get_job_status("missing")

        assert result["status"] == "NOT_IN_QUEUE"

    def test_get_job_status_returns_details(self, monkeypatch):
        entry = _queue_entry(started_at=datetime(2024, 1, 1, 2, 0, 0))
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = entry
        sched = scheduler.TrainingScheduler(db)
        monkeypatch.setattr(scheduler, "get_queue_position", MagicMock(return_value=2))
        monkeypatch.setattr(
            scheduler,
            "estimate_start_time",
            MagicMock(return_value=datetime(2024, 1, 1, 3, 0, 0)),
        )

        result = sched.get_job_status("job-1")

        assert result["status"] == "QUEUED"
        assert result["queue_position"] == 2
        assert result["estimated_start_time"] == "2024-01-01T03:00:00"

    def test_get_queue_overview_combines_queue_and_gpu_status(self, monkeypatch):
        db = MagicMock()
        sched = scheduler.TrainingScheduler(db)
        sched.gpu_allocator = MagicMock()
        sched.gpu_allocator.get_status.return_value = {"rtx3090": {"available": 0.5}}
        monkeypatch.setattr(
            scheduler,
            "get_queue_stats",
            MagicMock(return_value={"queued_count": 1, "running_count": 0}),
        )

        result = sched.get_queue_overview()

        assert result["queue"] == {"queued_count": 1, "running_count": 0}
        assert result["gpu"] == {"rtx3090": {"available": 0.5}}


class TestBackgroundAndNotifications:
    @pytest.mark.asyncio
    async def test_queue_processor_loop_runs_once_then_stops(self, monkeypatch):
        db = MagicMock()
        db_session_factory = MagicMock(return_value=db)
        process_queue = AsyncMock()

        class _Scheduler:
            def __init__(self, _db):
                self.db = _db

            async def process_queue(self):
                await process_queue()

        async def stop_after_first_sleep(_seconds):
            raise RuntimeError("stop")

        monkeypatch.setattr(scheduler, "TrainingScheduler", _Scheduler)
        monkeypatch.setattr(asyncio, "sleep", stop_after_first_sleep)

        with pytest.raises(RuntimeError, match="stop"):
            await scheduler.queue_processor_loop(db_session_factory)

        process_queue.assert_awaited_once()
        db.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_queue_notification_skips_when_no_webhook(self):
        await scheduler.send_queue_notification("job-1", "queued", {}, None)

    @pytest.mark.asyncio
    async def test_send_queue_notification_posts_payload(self, monkeypatch):
        session = MagicMock()
        response_ctx = MagicMock()
        response_ctx.__aenter__.return_value = types.SimpleNamespace(status=200)
        response_ctx.__aexit__.return_value = False
        session.post.return_value = response_ctx
        session_ctx = MagicMock()
        session_ctx.__aenter__.return_value = session
        session_ctx.__aexit__.return_value = False
        aiohttp_mod = types.ModuleType("aiohttp")
        aiohttp_mod.ClientSession = MagicMock(return_value=session_ctx)
        monkeypatch.setitem(sys.modules, "aiohttp", aiohttp_mod)

        await scheduler.send_queue_notification(
            "job-1",
            "job_started",
            {"queue_position": 1},
            "https://hooks.local/queue",
        )

        session.post.assert_called_once()
