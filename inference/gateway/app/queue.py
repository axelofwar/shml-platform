"""Redis-based request queue with priority."""

import json
import time
import uuid
import asyncio
import logging
from typing import Optional, List, Callable, Any
from datetime import datetime

import redis.asyncio as redis

from .config import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    MAX_QUEUE_SIZE,
    MAX_CONCURRENT_REQUESTS,
    REQUEST_TIMEOUT_SECONDS,
)
from .schemas import QueuedRequest, QueueStatus

logger = logging.getLogger(__name__)


class RequestQueue:
    """Redis-based request queue with priority and rate limiting."""

    # Priority: lower = higher priority
    PRIORITY_LLM = 1
    PRIORITY_IMAGE = 2

    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.active_count = 0
        self._lock = asyncio.Lock()

    async def connect(self):
        """Connect to Redis."""
        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
        )
        await self.redis.ping()
        logger.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT} DB {REDIS_DB}")

    async def close(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()

    async def enqueue(
        self,
        user_id: str,
        service: str,
        request_data: dict,
    ) -> QueuedRequest:
        """Add request to queue. Returns queue position."""
        queue_key = f"queue:{service}"

        # Check queue size
        queue_len = await self.redis.llen(queue_key)
        if queue_len >= MAX_QUEUE_SIZE:
            raise Exception(f"Queue full ({queue_len}/{MAX_QUEUE_SIZE})")

        # Create request entry
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        entry = {
            "id": request_id,
            "user_id": user_id,
            "service": service,
            "data": request_data,
            "queued_at": datetime.now().isoformat(),
        }

        # Add to queue (RPUSH for FIFO)
        await self.redis.rpush(queue_key, json.dumps(entry))

        # Get position
        position = await self.redis.llen(queue_key)

        # Estimate wait time (rough: 30s per LLM, 10s per image)
        avg_time = 30 if service == "llm" else 10
        estimated_wait = position * avg_time

        return QueuedRequest(
            id=request_id,
            user_id=user_id,
            service=service,
            position=position,
            queued_at=datetime.fromisoformat(entry["queued_at"]),
            estimated_wait_seconds=estimated_wait,
        )

    async def dequeue(self, service: str) -> Optional[dict]:
        """Get next request from queue (if under concurrent limit)."""
        async with self._lock:
            if self.active_count >= MAX_CONCURRENT_REQUESTS:
                return None

            queue_key = f"queue:{service}"
            entry_json = await self.redis.lpop(queue_key)

            if not entry_json:
                return None

            self.active_count += 1
            return json.loads(entry_json)

    async def complete(self):
        """Mark request as complete."""
        async with self._lock:
            self.active_count = max(0, self.active_count - 1)

    async def get_status(self, user_id: Optional[str] = None) -> QueueStatus:
        """Get queue status."""
        llm_len = await self.redis.llen("queue:llm")
        image_len = await self.redis.llen("queue:image")

        user_requests = []
        if user_id:
            # Find user's requests in queues
            for service in ["llm", "image"]:
                queue_key = f"queue:{service}"
                entries = await self.redis.lrange(queue_key, 0, -1)
                for i, entry_json in enumerate(entries):
                    entry = json.loads(entry_json)
                    if entry["user_id"] == user_id:
                        user_requests.append(
                            QueuedRequest(
                                id=entry["id"],
                                user_id=entry["user_id"],
                                service=service,
                                position=i + 1,
                                queued_at=datetime.fromisoformat(entry["queued_at"]),
                            )
                        )

        return QueueStatus(
            llm_queue_length=llm_len,
            image_queue_length=image_len,
            active_requests=self.active_count,
            max_concurrent=MAX_CONCURRENT_REQUESTS,
            your_requests=user_requests,
        )

    async def cancel(self, request_id: str, user_id: str) -> bool:
        """Cancel a queued request."""
        for service in ["llm", "image"]:
            queue_key = f"queue:{service}"
            entries = await self.redis.lrange(queue_key, 0, -1)
            for entry_json in entries:
                entry = json.loads(entry_json)
                if entry["id"] == request_id and entry["user_id"] == user_id:
                    await self.redis.lrem(queue_key, 1, entry_json)
                    return True
        return False


# Global queue instance
request_queue = RequestQueue()
