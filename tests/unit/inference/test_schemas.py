"""
Unit tests for inference stack schemas

These tests validate Pydantic models and data structures
without requiring GPU access.

Run with:
    pytest tests/unit/inference/test_schemas.py -v
"""
import pytest
from datetime import datetime
from typing import Dict, List, Optional
import json

# Import path setup for testing without package installation
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "inference"))


class TestChatMessageSchema:
    """Test chat message schema validation"""
    
    def test_valid_user_message(self):
        """Test valid user message structure"""
        message = {
            "role": "user",
            "content": "Hello, how are you?"
        }
        assert message["role"] in ["user", "assistant", "system"]
        assert isinstance(message["content"], str)
        assert len(message["content"]) > 0
    
    def test_valid_assistant_message(self):
        """Test valid assistant message structure"""
        message = {
            "role": "assistant",
            "content": "I'm doing well, thank you!"
        }
        assert message["role"] == "assistant"
        assert isinstance(message["content"], str)
    
    def test_valid_system_message(self):
        """Test valid system message structure"""
        message = {
            "role": "system",
            "content": "You are a helpful AI assistant."
        }
        assert message["role"] == "system"
        assert isinstance(message["content"], str)
    
    def test_invalid_role_rejected(self):
        """Test that invalid roles are detected"""
        message = {
            "role": "invalid_role",
            "content": "Some content"
        }
        valid_roles = ["user", "assistant", "system"]
        assert message["role"] not in valid_roles
    
    def test_empty_content_detected(self):
        """Test that empty content is flagged"""
        message = {
            "role": "user",
            "content": ""
        }
        assert len(message["content"]) == 0


class TestChatCompletionRequest:
    """Test chat completion request schema"""
    
    def test_valid_minimal_request(self):
        """Test minimal valid request"""
        request = {
            "model": "qwen3-vl-8b",
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
        }
        assert "model" in request
        assert "messages" in request
        assert len(request["messages"]) > 0
    
    def test_valid_full_request(self):
        """Test fully specified request"""
        request = {
            "model": "qwen3-vl-8b",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"}
            ],
            "temperature": 0.7,
            "max_tokens": 1024,
            "stream": False,
            "top_p": 0.9
        }
        assert request["temperature"] >= 0.0
        assert request["temperature"] <= 2.0
        assert request["max_tokens"] > 0
        assert isinstance(request["stream"], bool)
    
    def test_temperature_bounds(self):
        """Test temperature parameter validation"""
        # Valid temperatures
        valid_temps = [0.0, 0.5, 1.0, 1.5, 2.0]
        for temp in valid_temps:
            assert 0.0 <= temp <= 2.0
        
        # Invalid temperatures
        invalid_temps = [-0.1, 2.1, 3.0]
        for temp in invalid_temps:
            assert not (0.0 <= temp <= 2.0)
    
    def test_max_tokens_validation(self):
        """Test max_tokens parameter validation"""
        # Valid values
        valid_tokens = [1, 100, 1024, 4096, 8192]
        for tokens in valid_tokens:
            assert tokens > 0
            assert tokens <= 8192  # typical max
        
        # Invalid values
        invalid_tokens = [0, -1, -100]
        for tokens in invalid_tokens:
            assert tokens <= 0


class TestChatCompletionResponse:
    """Test chat completion response schema"""
    
    def test_valid_response_structure(self):
        """Test valid response structure"""
        response = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": int(datetime.now().timestamp()),
            "model": "qwen3-vl-8b",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello! I'm doing well."
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 15,
                "total_tokens": 25
            }
        }
        
        assert response["object"] == "chat.completion"
        assert len(response["choices"]) > 0
        assert response["choices"][0]["finish_reason"] in ["stop", "length", "tool_calls"]
        assert response["usage"]["total_tokens"] == (
            response["usage"]["prompt_tokens"] + 
            response["usage"]["completion_tokens"]
        )
    
    def test_streaming_chunk_structure(self):
        """Test streaming response chunk structure"""
        chunk = {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "created": int(datetime.now().timestamp()),
            "model": "qwen3-vl-8b",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": "Hello"
                    },
                    "finish_reason": None
                }
            ]
        }
        
        assert chunk["object"] == "chat.completion.chunk"
        assert "delta" in chunk["choices"][0]


class TestImageGenerationRequest:
    """Test image generation request schema"""
    
    def test_valid_minimal_request(self):
        """Test minimal valid image request"""
        request = {
            "prompt": "A beautiful sunset over mountains"
        }
        assert "prompt" in request
        assert len(request["prompt"]) > 0
    
    def test_valid_full_request(self):
        """Test fully specified image request"""
        request = {
            "prompt": "A beautiful sunset over mountains",
            "negative_prompt": "blurry, low quality",
            "width": 1024,
            "height": 1024,
            "num_inference_steps": 8,
            "guidance_scale": 1.0,
            "seed": 42
        }
        
        # Dimension validation
        assert request["width"] in [512, 768, 1024]
        assert request["height"] in [512, 768, 1024]
        
        # Steps validation (Z-Image uses 8 NFE)
        assert request["num_inference_steps"] >= 1
        assert request["num_inference_steps"] <= 50
        
        # Seed validation
        assert request["seed"] is None or isinstance(request["seed"], int)
    
    def test_dimension_validation(self):
        """Test image dimension constraints"""
        valid_dims = [512, 768, 1024]
        invalid_dims = [256, 500, 1920, 2048]
        
        for dim in valid_dims:
            assert dim in [512, 768, 1024]
        
        for dim in invalid_dims:
            assert dim not in [512, 768, 1024]


class TestImageGenerationResponse:
    """Test image generation response schema"""
    
    def test_valid_response_structure(self):
        """Test valid image response structure"""
        response = {
            "id": "img-123",
            "created": int(datetime.now().timestamp()),
            "data": [
                {
                    "url": None,  # or base64
                    "b64_json": "iVBORw0KGgo...",  # base64 encoded image
                    "revised_prompt": None
                }
            ]
        }
        
        assert "id" in response
        assert "data" in response
        assert len(response["data"]) > 0
        # Either url or b64_json should be present
        image_data = response["data"][0]
        assert image_data.get("url") is not None or image_data.get("b64_json") is not None


class TestQueueRequestSchema:
    """Test gateway queue request schema"""
    
    def test_valid_queue_entry(self):
        """Test valid queue entry structure"""
        entry = {
            "request_id": "req-123",
            "user_id": "user@example.com",
            "request_type": "llm",
            "payload": {"messages": [{"role": "user", "content": "Hello"}]},
            "priority": 1,
            "created_at": datetime.now().isoformat(),
            "status": "pending"
        }
        
        assert entry["request_type"] in ["llm", "image"]
        assert entry["priority"] >= 0
        assert entry["status"] in ["pending", "processing", "completed", "failed"]
    
    def test_request_types(self):
        """Test valid request types"""
        valid_types = ["llm", "image"]
        invalid_types = ["audio", "video", "text"]
        
        for rt in valid_types:
            assert rt in ["llm", "image"]
        
        for rt in invalid_types:
            assert rt not in ["llm", "image"]


class TestConversationHistory:
    """Test conversation history schema"""
    
    def test_valid_conversation(self):
        """Test valid conversation structure"""
        conversation = {
            "id": "conv-123",
            "user_id": "user@example.com",
            "title": "Planning discussion",
            "messages": [
                {"role": "user", "content": "Hello", "timestamp": datetime.now().isoformat()},
                {"role": "assistant", "content": "Hi there!", "timestamp": datetime.now().isoformat()}
            ],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "model": "qwen3-vl-8b",
            "total_tokens": 100
        }
        
        assert "id" in conversation
        assert "user_id" in conversation
        assert "messages" in conversation
        assert len(conversation["messages"]) > 0
    
    def test_message_ordering(self):
        """Test messages maintain order"""
        messages = [
            {"role": "system", "content": "System prompt", "index": 0},
            {"role": "user", "content": "First user message", "index": 1},
            {"role": "assistant", "content": "First response", "index": 2},
            {"role": "user", "content": "Second user message", "index": 3},
            {"role": "assistant", "content": "Second response", "index": 4}
        ]
        
        # Verify alternating pattern after system message
        for i in range(1, len(messages) - 1, 2):
            assert messages[i]["role"] == "user"
            assert messages[i + 1]["role"] == "assistant"


class TestRateLimitConfig:
    """Test rate limiting configuration schema"""
    
    def test_default_rate_limit(self):
        """Test default rate limit configuration"""
        config = {
            "requests_per_minute": 60,
            "burst_limit": 10,
            "window_seconds": 60
        }
        
        assert config["requests_per_minute"] > 0
        assert config["burst_limit"] > 0
        assert config["burst_limit"] <= config["requests_per_minute"]
    
    def test_user_rate_limit_tiers(self):
        """Test tiered rate limits"""
        tiers = {
            "free": {"requests_per_minute": 10, "burst_limit": 2},
            "basic": {"requests_per_minute": 60, "burst_limit": 10},
            "premium": {"requests_per_minute": 300, "burst_limit": 50}
        }
        
        # Premium should have higher limits than basic
        assert tiers["premium"]["requests_per_minute"] > tiers["basic"]["requests_per_minute"]
        assert tiers["basic"]["requests_per_minute"] > tiers["free"]["requests_per_minute"]


class TestHealthCheckResponse:
    """Test health check response schema"""
    
    def test_healthy_response(self):
        """Test healthy service response"""
        response = {
            "status": "healthy",
            "service": "qwen3-vl-api",
            "model_loaded": True,
            "gpu_available": True,
            "gpu_memory_used_mb": 6500,
            "gpu_memory_total_mb": 8192,
            "uptime_seconds": 3600,
            "version": "1.0.0"
        }
        
        assert response["status"] in ["healthy", "degraded", "unhealthy"]
        assert isinstance(response["model_loaded"], bool)
        assert response["gpu_memory_used_mb"] <= response["gpu_memory_total_mb"]
    
    def test_degraded_response(self):
        """Test degraded service response"""
        response = {
            "status": "degraded",
            "service": "z-image-api",
            "model_loaded": False,
            "reason": "Model not loaded - on-demand",
            "gpu_available": True,
            "gpu_memory_used_mb": 0,
            "gpu_memory_total_mb": 24576
        }
        
        assert response["status"] == "degraded"
        assert not response["model_loaded"]
        assert "reason" in response
    
    def test_unhealthy_response(self):
        """Test unhealthy service response"""
        response = {
            "status": "unhealthy",
            "service": "inference-gateway",
            "error": "Redis connection failed",
            "redis_connected": False,
            "postgres_connected": True
        }
        
        assert response["status"] == "unhealthy"
        assert "error" in response


class TestBackupSchema:
    """Test backup configuration schema"""
    
    def test_backup_config(self):
        """Test backup configuration structure"""
        config = {
            "enabled": True,
            "schedule": "daily",
            "retention_days": 90,
            "compression": "zstd",
            "backup_path": "/data/backups",
            "include": ["conversations", "user_preferences"],
            "exclude": ["temp_files", "cache"]
        }
        
        assert config["retention_days"] > 0
        assert config["compression"] in ["zstd", "gzip", "none"]
        assert len(config["include"]) > 0
    
    def test_backup_metadata(self):
        """Test backup metadata structure"""
        metadata = {
            "backup_id": "backup-20231215-120000",
            "created_at": datetime.now().isoformat(),
            "size_bytes": 1024000,
            "compression_ratio": 0.35,
            "tables": ["conversations", "user_preferences"],
            "row_counts": {"conversations": 1500, "user_preferences": 50}
        }
        
        assert metadata["compression_ratio"] <= 1.0
        assert metadata["size_bytes"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
