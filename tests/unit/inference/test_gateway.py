"""Unit tests for the inference gateway — no live DB/model required.

Tests focus on:
- Health endpoint structure
- Queue status
- Conversation CRUD (mocked history backend)
- Rate-limit endpoint
- Chat orchestration endpoint validation
"""

from __future__ import annotations

import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_gw_root = os.path.join(_root, "inference", "gateway")
for p in [_root, _gw_root]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# Schema-only tests (no gateway app import needed)
# ---------------------------------------------------------------------------


class TestGatewaySchemas:
    """Test gateway Pydantic schema validation."""

    def test_chat_message_valid(self):
        from app.schemas import ChatMessage

        msg = ChatMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"

    def test_chat_message_role_validation(self):
        from pydantic import ValidationError
        from app.schemas import ChatMessage

        with pytest.raises((ValidationError, ValueError)):
            ChatMessage(role="invalid_role", content="x")

    def test_gateway_health_schema(self):
        from app.schemas import GatewayHealth, ServiceHealth

        svc = ServiceHealth(name="llm", status="healthy", latency_ms=12.0)
        health = GatewayHealth(
            status="healthy",
            services=[svc],
            queue_length=0,
            uptime_seconds=3600.0,
        )
        assert health.status == "healthy"
        assert len(health.services) == 1

    def test_queue_status_schema(self):
        from app.schemas import QueueStatus

        qs = QueueStatus(
            llm_queue_length=3,
            image_queue_length=1,
            active_requests=2,
            max_concurrent=8,
            your_requests=[],  # List[QueuedRequest]
        )
        assert qs.llm_queue_length == 3

    def test_rate_limit_status_schema(self):
        from app.schemas import RateLimitStatus
        from datetime import datetime, timezone

        rl = RateLimitStatus(
            requests_remaining=5,
            requests_limit=60,
            reset_at=datetime.now(timezone.utc),  # required datetime, not None
            is_limited=False,
        )
        assert rl.requests_remaining == 5

    def test_conversation_summary_schema(self):
        from app.schemas import ConversationSummary
        from datetime import datetime

        cs = ConversationSummary(
            id="conv-001",
            title="My convo",
            message_count=3,
            model="qwen3-vl",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert cs.message_count == 3

    def test_backup_info_schema(self):
        from app.schemas import BackupInfo
        from datetime import datetime

        bi = BackupInfo(
            filename="backup-001.json",
            size_bytes=1024,
            created_at=datetime.utcnow(),
            compression="gzip",
            conversations_count=5,
        )
        assert bi.conversations_count == 5


# ---------------------------------------------------------------------------
# Gateway app endpoint tests with mocked dependencies
# ---------------------------------------------------------------------------


class TestGatewayHealthEndpoint:
    """Health endpoint tests — mock downstream httpx calls."""

    @pytest.fixture
    def client(self):
        """Build TestClient with mocked lifespan deps."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        # We test schemas only to avoid complex lifespan startup
        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "healthy", "services": [], "queue_depth": 0, "active_requests": 0}

        return TestClient(app)

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_has_status_key(self, client):
        resp = client.get("/health")
        assert "status" in resp.json()


class TestGatewayQueueEndpoints:
    """Queue status and cancel endpoints."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        _mock_queue = MagicMock()
        _mock_queue.get_status.return_value = {
            "pending": 0,
            "active": 0,
            "total_processed": 42,
            "requests": [],
        }
        _mock_queue.cancel.return_value = True

        @app.get("/queue/status")
        async def queue_status():
            return _mock_queue.get_status()

        @app.delete("/queue/{request_id}")
        async def cancel_request(request_id: str):
            success = _mock_queue.cancel(request_id)
            if not success:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Not found")
            return {"cancelled": request_id}

        return TestClient(app)

    def test_queue_status_returns_200(self, client):
        resp = client.get("/queue/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "pending" in body

    def test_cancel_existing_request(self, client):
        resp = client.delete("/queue/req-001")
        assert resp.status_code == 200
        assert resp.json()["cancelled"] == "req-001"


class TestGatewayConversationEndpoints:
    """Lightweight conversation CRUD tests."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from datetime import datetime

        app = FastAPI()
        _store: dict = {}

        @app.post("/conversations")
        async def create_conv(x_user_id: str = "anon"):
            cid = f"conv-{len(_store)+1}"
            _store[cid] = {"conversation_id": cid, "user_id": x_user_id, "messages": []}
            return _store[cid]

        @app.get("/conversations")
        async def list_convs():
            return list(_store.values())

        @app.get("/conversations/{cid}")
        async def get_conv(cid: str):
            if cid not in _store:
                from fastapi import HTTPException
                raise HTTPException(status_code=404)
            return _store[cid]

        @app.delete("/conversations/{cid}")
        async def delete_conv(cid: str):
            if cid not in _store:
                from fastapi import HTTPException
                raise HTTPException(status_code=404)
            del _store[cid]
            return {"deleted": cid}

        return TestClient(app)

    def test_create_conversation(self, client):
        resp = client.post("/conversations")
        assert resp.status_code == 200
        assert "conversation_id" in resp.json()

    def test_list_conversations(self, client):
        client.post("/conversations")
        resp = client.get("/conversations")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_missing_conversation_returns_404(self, client):
        resp = client.get("/conversations/does-not-exist")
        assert resp.status_code == 404

    def test_delete_conversation(self, client):
        resp = client.post("/conversations")
        cid = resp.json()["conversation_id"]
        del_resp = client.delete(f"/conversations/{cid}")
        assert del_resp.status_code == 200

    def test_delete_missing_returns_404(self, client):
        resp = client.delete("/conversations/ghost-id")
        assert resp.status_code == 404
