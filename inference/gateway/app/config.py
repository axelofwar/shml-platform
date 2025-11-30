"""Inference Gateway configuration."""
import os
from pathlib import Path

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Backend services
QWEN3_VL_URL = os.getenv("QWEN3_VL_URL", "http://qwen3-vl-api:8000")
Z_IMAGE_URL = os.getenv("Z_IMAGE_URL", "http://z-image-api:8000")

# Redis settings (queue)
REDIS_HOST = os.getenv("REDIS_HOST", "ml-platform-redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "2"))  # Separate from MLflow (0) and Ray (1)

# PostgreSQL settings (chat history)
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "shared-postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "inference")
POSTGRES_USER = os.getenv("POSTGRES_USER", "inference")
POSTGRES_PASSWORD_FILE = os.getenv("POSTGRES_PASSWORD_FILE", "/run/secrets/shared_db_password")

# Queue settings
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "20"))
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "3"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "300"))

# Rate limiting
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))  # Per minute
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

# Backup settings
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/backups"))
BACKUP_COMPRESSION = os.getenv("BACKUP_COMPRESSION", "zstd")  # zstd, gzip, none
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "90"))

# Paths
LOG_DIR = Path(os.getenv("LOG_DIR", "/app/logs"))
