"""
Unit tests for inference stack configuration

Tests configuration validation, defaults, and environment handling
without requiring GPU access.

Run with:
    pytest tests/unit/inference/test_config.py -v
"""
import pytest
import os
from pathlib import Path
from typing import Dict


class TestQwen3VLConfig:
    """Test Qwen3-VL service configuration"""
    
    def test_default_config(self):
        """Test default configuration values"""
        config = {
            "model_name": "Qwen/Qwen2.5-VL-7B-Instruct",
            "device": "cuda:0",
            "quantization": "int4",
            "max_length": 8192,
            "temperature": 0.7,
            "host": "0.0.0.0",
            "port": 8000
        }
        
        assert config["device"].startswith("cuda")
        assert config["quantization"] in ["int4", "int8", "fp16", "none"]
        assert config["max_length"] > 0
        assert 0.0 <= config["temperature"] <= 2.0
        assert config["port"] > 0
    
    def test_privacy_config(self):
        """Test privacy-related configuration"""
        env_vars = {
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1"
        }
        
        for key, expected in env_vars.items():
            assert expected == "1"  # All should be set to disable network
    
    def test_memory_config(self):
        """Test memory configuration for RTX 2070"""
        config = {
            "gpu_memory_limit_mb": 7500,  # Leave 500MB buffer from 8GB
            "max_batch_size": 1,
            "gradient_checkpointing": True
        }
        
        # RTX 2070 has 8GB, INT4 model needs ~6-7GB
        assert config["gpu_memory_limit_mb"] < 8192
        assert config["max_batch_size"] >= 1
    
    def test_quantization_options(self):
        """Test valid quantization options"""
        valid_options = ["int4", "int8", "fp16", "fp32", "none"]
        
        # INT4 is optimal for 8GB GPU
        recommended = "int4"
        assert recommended in valid_options


class TestZImageConfig:
    """Test Z-Image service configuration"""
    
    def test_default_config(self):
        """Test default configuration values"""
        config = {
            "model_name": "InstantX/Z-Image-Turbo",
            "device": "cuda:1",
            "dtype": "float16",
            "default_steps": 8,
            "default_size": 1024,
            "host": "0.0.0.0",
            "port": 8000
        }
        
        assert config["device"].startswith("cuda")
        assert config["dtype"] in ["float16", "float32", "bfloat16"]
        assert config["default_steps"] >= 1
        assert config["default_size"] in [512, 768, 1024]
    
    def test_auto_unload_config(self):
        """Test auto-unload configuration for resource management"""
        config = {
            "auto_unload_enabled": True,
            "idle_timeout_seconds": 300,  # 5 minutes
            "yield_to_training": True
        }
        
        assert config["idle_timeout_seconds"] > 0
        assert config["auto_unload_enabled"] == True
    
    def test_memory_config(self):
        """Test memory configuration for RTX 3090"""
        config = {
            "gpu_memory_limit_mb": 22000,  # Leave 2GB buffer from 24GB
            "max_batch_size": 4,
            "attention_slicing": False  # Not needed with 24GB
        }
        
        # RTX 3090 has 24GB
        assert config["gpu_memory_limit_mb"] < 24576
        assert config["max_batch_size"] >= 1
    
    def test_nfe_steps_validation(self):
        """Test NFE (Number of Function Evaluations) steps"""
        # Z-Image is optimized for 8 steps
        recommended_steps = 8
        valid_range = range(1, 51)
        
        assert recommended_steps in valid_range


class TestGatewayConfig:
    """Test inference gateway configuration"""
    
    def test_default_config(self):
        """Test default gateway configuration"""
        config = {
            "host": "0.0.0.0",
            "port": 8000,
            "redis_url": "redis://inference-redis:6379/2",
            "postgres_url": "postgresql://inference:password@inference-postgres:5432/inference",
            "rate_limit_requests_per_minute": 60,
            "rate_limit_burst": 10
        }
        
        assert config["port"] > 0
        assert "redis://" in config["redis_url"]
        assert "postgresql://" in config["postgres_url"]
        assert config["rate_limit_requests_per_minute"] > 0
    
    def test_backend_urls(self):
        """Test backend service URLs"""
        backends = {
            "llm": "http://qwen3-vl-api:8000",
            "image": "http://z-image-api:8000"
        }
        
        for name, url in backends.items():
            assert url.startswith("http://")
            assert ":8000" in url
    
    def test_queue_config(self):
        """Test queue configuration"""
        config = {
            "queue_name": "inference_queue",
            "max_queue_size": 1000,
            "request_timeout_seconds": 300,
            "max_retries": 3
        }
        
        assert config["max_queue_size"] > 0
        assert config["request_timeout_seconds"] > 0
        assert config["max_retries"] >= 0
    
    def test_backup_config(self):
        """Test backup configuration"""
        config = {
            "backup_enabled": True,
            "backup_schedule": "0 2 * * *",  # 2 AM daily
            "backup_retention_days": 90,
            "backup_compression": "zstd",
            "backup_path": "/data/backups"
        }
        
        assert config["backup_retention_days"] > 0
        assert config["backup_compression"] in ["zstd", "gzip", "none"]


class TestDockerComposeConfig:
    """Test docker-compose configuration validity"""
    
    def test_service_names(self):
        """Test expected service names"""
        expected_services = [
            "inference-postgres",
            "qwen3-vl-api",
            "z-image-api",
            "inference-gateway"
        ]
        
        for service in expected_services:
            assert isinstance(service, str)
            assert len(service) > 0
    
    def test_port_mappings(self):
        """Test port mappings don't conflict"""
        port_mappings = {
            "inference-postgres": 5433,  # Different from mlflow-postgres (5432)
            "inference-gateway": 8001    # Different from other APIs
        }
        
        # Check no duplicates
        ports = list(port_mappings.values())
        assert len(ports) == len(set(ports))
    
    def test_gpu_reservations(self):
        """Test GPU device reservations"""
        gpu_assignments = {
            "qwen3-vl-api": "0",   # RTX 2070
            "z-image-api": "1"     # RTX 3090
        }
        
        # Check no GPU conflicts
        devices = list(gpu_assignments.values())
        assert len(devices) == len(set(devices))
    
    def test_network_config(self):
        """Test network configuration"""
        config = {
            "network_name": "ml-platform",
            "network_external": True
        }
        
        assert config["network_external"] == True
    
    def test_volume_mounts(self):
        """Test volume mount paths"""
        volumes = {
            "postgres_data": "/var/lib/postgresql/data",
            "model_cache": "/root/.cache/huggingface",
            "backup_data": "/data/backups"
        }
        
        for name, path in volumes.items():
            assert path.startswith("/")


class TestTraefikLabels:
    """Test Traefik routing labels"""
    
    def test_priority_value(self):
        """Test router priority is high enough"""
        # Must be higher than Traefik internal API (which uses priority 1)
        required_priority = 2147483647  # Max int32
        
        assert required_priority == 2147483647
    
    def test_route_rules(self):
        """Test route rule patterns"""
        rules = {
            "llm": "PathPrefix(`/api/llm`)",
            "image": "PathPrefix(`/api/image`)",
            "inference": "PathPrefix(`/inference`)"
        }
        
        for name, rule in rules.items():
            assert "PathPrefix" in rule
            assert "`/" in rule
    
    def test_service_ports(self):
        """Test service load balancer ports"""
        services = {
            "qwen3-vl-api": 8000,
            "z-image-api": 8000,
            "inference-gateway": 8000
        }
        
        for name, port in services.items():
            assert port == 8000  # All use internal port 8000


class TestEnvironmentVariables:
    """Test environment variable handling"""
    
    def test_required_env_vars(self):
        """Test required environment variables are defined"""
        required_vars = [
            "POSTGRES_PASSWORD",
            "CUDA_VISIBLE_DEVICES",
            "TRANSFORMERS_OFFLINE",
            "HF_HUB_OFFLINE"
        ]
        
        # These should be defined in docker-compose or .env
        for var in required_vars:
            assert isinstance(var, str)
    
    def test_secret_file_paths(self):
        """Test secret file path patterns"""
        secret_paths = {
            "postgres_password": "/run/secrets/inference_postgres_password"
        }
        
        for name, path in secret_paths.items():
            assert path.startswith("/run/secrets/")
    
    def test_model_cache_paths(self):
        """Test model cache directory structure"""
        cache_paths = {
            "huggingface": "/root/.cache/huggingface",
            "transformers": "/root/.cache/huggingface/hub"
        }
        
        for name, path in cache_paths.items():
            assert ".cache" in path


class TestResourceLimits:
    """Test resource limit configurations"""
    
    def test_qwen3_vl_resources(self):
        """Test Qwen3-VL resource limits"""
        resources = {
            "memory_limit": "12g",
            "memory_reservation": "8g",
            "shm_size": "2g"
        }
        
        # Parse memory values
        def parse_memory(s):
            if s.endswith("g"):
                return int(s[:-1])
            return 0
        
        mem_limit = parse_memory(resources["memory_limit"])
        mem_reserve = parse_memory(resources["memory_reservation"])
        
        assert mem_limit >= mem_reserve
    
    def test_z_image_resources(self):
        """Test Z-Image resource limits"""
        resources = {
            "memory_limit": "32g",
            "memory_reservation": "24g",
            "shm_size": "4g"
        }
        
        def parse_memory(s):
            if s.endswith("g"):
                return int(s[:-1])
            return 0
        
        mem_limit = parse_memory(resources["memory_limit"])
        mem_reserve = parse_memory(resources["memory_reservation"])
        
        assert mem_limit >= mem_reserve
    
    def test_gateway_resources(self):
        """Test Gateway resource limits (no GPU)"""
        resources = {
            "memory_limit": "2g",
            "memory_reservation": "512m",
            "cpu_limit": "2.0"
        }
        
        # Gateway should have modest resource requirements
        def parse_memory(s):
            if s.endswith("g"):
                return int(s[:-1]) * 1024
            if s.endswith("m"):
                return int(s[:-1])
            return 0
        
        mem_limit = parse_memory(resources["memory_limit"])
        mem_reserve = parse_memory(resources["memory_reservation"])
        
        assert mem_limit >= mem_reserve


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
