"""
Unit tests for inference stack utility functions

Tests queue management, rate limiting, history, and backup utilities
without requiring GPU access.

Run with:
    pytest tests/unit/inference/test_utils.py -v
"""
import pytest
from datetime import datetime, timedelta
from typing import Dict, List
import json
import hashlib


class TestQueueManagement:
    """Test request queue management utilities"""
    
    def test_request_id_generation(self):
        """Test unique request ID generation"""
        def generate_request_id(user_id: str, timestamp: datetime) -> str:
            """Generate unique request ID"""
            data = f"{user_id}:{timestamp.isoformat()}"
            return f"req-{hashlib.sha256(data.encode()).hexdigest()[:16]}"
        
        id1 = generate_request_id("user1", datetime.now())
        id2 = generate_request_id("user2", datetime.now())
        
        assert id1 != id2
        assert id1.startswith("req-")
        assert len(id1) == 20  # "req-" + 16 chars
    
    def test_queue_priority_ordering(self):
        """Test queue priority ordering"""
        queue = [
            {"id": "1", "priority": 2, "created_at": "2024-01-01T00:00:00"},
            {"id": "2", "priority": 1, "created_at": "2024-01-01T00:00:01"},
            {"id": "3", "priority": 1, "created_at": "2024-01-01T00:00:00"},
        ]
        
        # Sort by priority (lower first), then by created_at
        sorted_queue = sorted(queue, key=lambda x: (x["priority"], x["created_at"]))
        
        assert sorted_queue[0]["id"] == "3"  # Priority 1, earliest
        assert sorted_queue[1]["id"] == "2"  # Priority 1, later
        assert sorted_queue[2]["id"] == "1"  # Priority 2
    
    def test_queue_size_limits(self):
        """Test queue size limit enforcement"""
        max_size = 1000
        queue = []
        
        def add_to_queue(item, max_size=max_size):
            if len(queue) >= max_size:
                return False, "Queue full"
            queue.append(item)
            return True, None
        
        # Should succeed
        success, error = add_to_queue({"id": "1"})
        assert success
        assert error is None
        
        # Simulate full queue
        queue.extend([{"id": str(i)} for i in range(2, max_size + 1)])
        
        success, error = add_to_queue({"id": "overflow"})
        assert not success
        assert "full" in error.lower()
    
    def test_request_timeout_detection(self):
        """Test request timeout detection"""
        timeout_seconds = 300
        
        def is_timed_out(created_at: datetime, timeout: int = timeout_seconds) -> bool:
            return datetime.now() - created_at > timedelta(seconds=timeout)
        
        # Recent request - not timed out
        recent = datetime.now() - timedelta(seconds=10)
        assert not is_timed_out(recent)
        
        # Old request - timed out
        old = datetime.now() - timedelta(seconds=400)
        assert is_timed_out(old)
    
    def test_request_status_transitions(self):
        """Test valid status transitions"""
        valid_transitions = {
            "pending": ["processing", "cancelled"],
            "processing": ["completed", "failed"],
            "completed": [],
            "failed": ["pending"],  # Allow retry
            "cancelled": []
        }
        
        def can_transition(from_status: str, to_status: str) -> bool:
            return to_status in valid_transitions.get(from_status, [])
        
        assert can_transition("pending", "processing")
        assert can_transition("processing", "completed")
        assert not can_transition("completed", "pending")
        assert can_transition("failed", "pending")  # Retry


class TestRateLimiting:
    """Test rate limiting utilities"""
    
    def test_sliding_window_counter(self):
        """Test sliding window rate limiting"""
        class SlidingWindowCounter:
            def __init__(self, limit: int, window_seconds: int):
                self.limit = limit
                self.window_seconds = window_seconds
                self.requests: List[datetime] = []
            
            def is_allowed(self) -> bool:
                now = datetime.now()
                cutoff = now - timedelta(seconds=self.window_seconds)
                
                # Remove old requests
                self.requests = [r for r in self.requests if r > cutoff]
                
                if len(self.requests) >= self.limit:
                    return False
                
                self.requests.append(now)
                return True
            
            def remaining(self) -> int:
                now = datetime.now()
                cutoff = now - timedelta(seconds=self.window_seconds)
                active_requests = len([r for r in self.requests if r > cutoff])
                return max(0, self.limit - active_requests)
        
        counter = SlidingWindowCounter(limit=3, window_seconds=60)
        
        assert counter.is_allowed()
        assert counter.is_allowed()
        assert counter.is_allowed()
        assert not counter.is_allowed()  # Limit reached
        assert counter.remaining() == 0
    
    def test_rate_limit_headers(self):
        """Test rate limit response headers"""
        def create_rate_limit_headers(limit: int, remaining: int, reset_at: datetime) -> Dict:
            return {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(int(reset_at.timestamp()))
            }
        
        headers = create_rate_limit_headers(
            limit=60,
            remaining=45,
            reset_at=datetime.now() + timedelta(minutes=1)
        )
        
        assert headers["X-RateLimit-Limit"] == "60"
        assert headers["X-RateLimit-Remaining"] == "45"
        assert "X-RateLimit-Reset" in headers
    
    def test_user_identification(self):
        """Test user identification for rate limiting"""
        def get_user_id(request_headers: Dict, client_ip: str) -> str:
            # Prefer authorization header, fall back to IP
            auth = request_headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
                # Extract user from token (simplified)
                return f"token:{hashlib.sha256(token.encode()).hexdigest()[:8]}"
            return f"ip:{client_ip}"
        
        # Authenticated user
        headers_auth = {"Authorization": "Bearer abc123"}
        user_id = get_user_id(headers_auth, "192.168.1.1")
        assert user_id.startswith("token:")
        
        # Anonymous user
        headers_anon = {}
        user_id = get_user_id(headers_anon, "192.168.1.1")
        assert user_id == "ip:192.168.1.1"


class TestConversationHistory:
    """Test conversation history utilities"""
    
    def test_conversation_creation(self):
        """Test conversation creation"""
        def create_conversation(user_id: str, title: str = None) -> Dict:
            conv_id = f"conv-{hashlib.sha256(f'{user_id}:{datetime.now().isoformat()}'.encode()).hexdigest()[:12]}"
            return {
                "id": conv_id,
                "user_id": user_id,
                "title": title or "New Conversation",
                "messages": [],
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "total_tokens": 0
            }
        
        conv = create_conversation("user@example.com", "Planning Session")
        
        assert conv["id"].startswith("conv-")
        assert conv["user_id"] == "user@example.com"
        assert conv["title"] == "Planning Session"
        assert len(conv["messages"]) == 0
    
    def test_message_appending(self):
        """Test message appending to conversation"""
        def add_message(conversation: Dict, role: str, content: str, tokens: int = 0) -> Dict:
            message = {
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "tokens": tokens
            }
            conversation["messages"].append(message)
            conversation["total_tokens"] += tokens
            conversation["updated_at"] = datetime.now().isoformat()
            return conversation
        
        conv = {
            "id": "conv-123",
            "messages": [],
            "total_tokens": 0,
            "updated_at": None
        }
        
        conv = add_message(conv, "user", "Hello", tokens=5)
        conv = add_message(conv, "assistant", "Hi there!", tokens=10)
        
        assert len(conv["messages"]) == 2
        assert conv["total_tokens"] == 15
        assert conv["messages"][0]["role"] == "user"
        assert conv["messages"][1]["role"] == "assistant"
    
    def test_conversation_title_generation(self):
        """Test automatic title generation from first message"""
        def generate_title(first_message: str, max_length: int = 50) -> str:
            # Truncate and clean
            title = first_message.strip()[:max_length]
            if len(first_message) > max_length:
                title = title.rsplit(" ", 1)[0] + "..."
            return title
        
        short_msg = "Hello, how are you?"
        assert generate_title(short_msg) == "Hello, how are you?"
        
        long_msg = "I need help with planning the architecture for a large-scale distributed system with multiple microservices"
        title = generate_title(long_msg)
        assert len(title) <= 53  # 50 + "..."
        assert title.endswith("...")
    
    def test_conversation_search(self):
        """Test conversation search functionality"""
        conversations = [
            {"id": "1", "title": "Python coding help", "messages": [{"content": "How to use decorators"}]},
            {"id": "2", "title": "Architecture planning", "messages": [{"content": "Design patterns for microservices"}]},
            {"id": "3", "title": "Python testing", "messages": [{"content": "pytest fixtures tutorial"}]},
        ]
        
        def search_conversations(query: str, convs: List[Dict]) -> List[Dict]:
            query = query.lower()
            results = []
            for conv in convs:
                if query in conv["title"].lower():
                    results.append(conv)
                    continue
                for msg in conv["messages"]:
                    if query in msg["content"].lower():
                        results.append(conv)
                        break
            return results
        
        results = search_conversations("python", conversations)
        assert len(results) == 2
        
        results = search_conversations("microservices", conversations)
        assert len(results) == 1


class TestBackupUtilities:
    """Test backup utility functions"""
    
    def test_backup_filename_generation(self):
        """Test backup filename generation"""
        def generate_backup_filename(prefix: str = "backup") -> str:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return f"{prefix}_{timestamp}.sql.zst"
        
        filename = generate_backup_filename("conversations")
        
        assert filename.startswith("conversations_")
        assert filename.endswith(".sql.zst")
    
    def test_retention_policy(self):
        """Test backup retention policy"""
        retention_days = 90
        
        def should_delete(backup_date: datetime, retention: int = retention_days) -> bool:
            return datetime.now() - backup_date > timedelta(days=retention)
        
        # Recent backup - keep
        recent = datetime.now() - timedelta(days=30)
        assert not should_delete(recent)
        
        # Old backup - delete
        old = datetime.now() - timedelta(days=100)
        assert should_delete(old)
    
    def test_compression_estimation(self):
        """Test compression ratio estimation"""
        def estimate_compressed_size(original_size: int, compression_ratio: float = 0.35) -> int:
            return int(original_size * compression_ratio)
        
        original = 1000000  # 1MB
        compressed = estimate_compressed_size(original)
        
        assert compressed < original
        assert compressed == 350000
    
    def test_backup_manifest_creation(self):
        """Test backup manifest creation"""
        def create_manifest(backup_files: List[str], metadata: Dict) -> Dict:
            return {
                "version": "1.0",
                "created_at": datetime.now().isoformat(),
                "files": backup_files,
                "metadata": metadata,
                "checksum": hashlib.sha256(json.dumps(backup_files).encode()).hexdigest()
            }
        
        manifest = create_manifest(
            ["conversations.sql.zst", "preferences.sql.zst"],
            {"row_count": 1500, "compression": "zstd"}
        )
        
        assert "checksum" in manifest
        assert len(manifest["files"]) == 2


class TestGPUYieldManagement:
    """Test GPU yield management for training priority"""
    
    def test_yield_request_structure(self):
        """Test yield request structure"""
        request = {
            "action": "yield",
            "service": "z-image-api",
            "reason": "training_job_start",
            "expected_duration_minutes": 120,
            "requested_by": "ray-compute-api"
        }
        
        assert request["action"] == "yield"
        assert "expected_duration_minutes" in request
    
    def test_reclaim_request_structure(self):
        """Test reclaim request structure"""
        request = {
            "action": "reclaim",
            "service": "z-image-api",
            "reason": "training_job_complete",
            "requested_by": "ray-compute-api"
        }
        
        assert request["action"] == "reclaim"
        assert "reason" in request
    
    def test_yield_state_machine(self):
        """Test GPU yield state transitions"""
        valid_states = ["loaded", "unloading", "unloaded", "loading"]
        
        valid_transitions = {
            "loaded": ["unloading"],
            "unloading": ["unloaded"],
            "unloaded": ["loading"],
            "loading": ["loaded"]
        }
        
        def can_transition(from_state: str, to_state: str) -> bool:
            return to_state in valid_transitions.get(from_state, [])
        
        assert can_transition("loaded", "unloading")
        assert can_transition("unloaded", "loading")
        assert not can_transition("loaded", "loading")
    
    def test_idle_timeout_calculation(self):
        """Test idle timeout for auto-unload"""
        idle_timeout_seconds = 300  # 5 minutes
        
        def should_auto_unload(last_request: datetime, timeout: int = idle_timeout_seconds) -> bool:
            return datetime.now() - last_request > timedelta(seconds=timeout)
        
        # Recent activity - don't unload
        recent = datetime.now() - timedelta(seconds=60)
        assert not should_auto_unload(recent)
        
        # Idle for too long - unload
        idle = datetime.now() - timedelta(seconds=400)
        assert should_auto_unload(idle)


class TestHealthChecks:
    """Test health check utilities"""
    
    def test_health_status_determination(self):
        """Test health status determination logic"""
        def determine_health_status(
            model_loaded: bool,
            gpu_available: bool,
            redis_connected: bool,
            postgres_connected: bool
        ) -> str:
            if not redis_connected or not postgres_connected:
                return "unhealthy"
            if not gpu_available:
                return "unhealthy"
            if not model_loaded:
                return "degraded"
            return "healthy"
        
        # All good
        assert determine_health_status(True, True, True, True) == "healthy"
        
        # Model not loaded (on-demand service)
        assert determine_health_status(False, True, True, True) == "degraded"
        
        # Infrastructure failure
        assert determine_health_status(True, True, False, True) == "unhealthy"
    
    def test_gpu_memory_threshold(self):
        """Test GPU memory usage threshold"""
        def check_gpu_memory(used_mb: int, total_mb: int, threshold: float = 0.95) -> Dict:
            usage = used_mb / total_mb
            return {
                "used_mb": used_mb,
                "total_mb": total_mb,
                "usage_percent": round(usage * 100, 2),
                "warning": usage > threshold,
                "message": "High GPU memory usage" if usage > threshold else "OK"
            }
        
        # Normal usage
        result = check_gpu_memory(6000, 8192)
        assert not result["warning"]
        
        # High usage
        result = check_gpu_memory(7900, 8192)
        assert result["warning"]
    
    def test_service_dependency_check(self):
        """Test service dependency health check"""
        dependencies = {
            "qwen3-vl-api": ["inference-postgres", "ml-platform network"],
            "z-image-api": ["inference-postgres", "ml-platform network"],
            "inference-gateway": ["inference-postgres", "inference-redis", "qwen3-vl-api", "z-image-api"]
        }
        
        def check_dependencies(service: str, available_services: List[str]) -> Dict:
            deps = dependencies.get(service, [])
            missing = [d for d in deps if d not in available_services]
            return {
                "service": service,
                "dependencies": deps,
                "missing": missing,
                "ready": len(missing) == 0
            }
        
        available = ["inference-postgres", "inference-redis", "ml-platform network"]
        
        result = check_dependencies("qwen3-vl-api", available)
        assert result["ready"]
        
        result = check_dependencies("inference-gateway", available)
        assert not result["ready"]  # Missing backend APIs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
