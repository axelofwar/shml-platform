"""Compressed backup for chat history."""

import io
import os
import json
import logging
from typing import List
from datetime import datetime, timedelta
from pathlib import Path

from .config import BACKUP_DIR, BACKUP_COMPRESSION, BACKUP_RETENTION_DAYS
from .schemas import BackupInfo
from .history import chat_history

logger = logging.getLogger(__name__)


async def create_backup(user_id: str) -> BackupInfo:
    """Create compressed backup of user's chat history."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Export data
    data = await chat_history.export_user_data(user_id)
    json_data = json.dumps(data, indent=2, default=str)

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_filename = f"chat_history_{user_id}_{timestamp}"

    # Compress based on config
    if BACKUP_COMPRESSION == "zstd":
        import zstandard as zstd

        cctx = zstd.ZstdCompressor(level=19)  # High compression
        compressed = cctx.compress(json_data.encode())
        filename = f"{base_filename}.json.zst"
    elif BACKUP_COMPRESSION == "gzip":
        import gzip

        compressed = gzip.compress(json_data.encode(), compresslevel=9)
        filename = f"{base_filename}.json.gz"
    else:
        compressed = json_data.encode()
        filename = f"{base_filename}.json"

    # Write to file
    filepath = BACKUP_DIR / filename
    with open(filepath, "wb") as f:
        f.write(compressed)

    logger.info(f"Created backup: {filename} ({len(compressed)} bytes)")

    return BackupInfo(
        filename=filename,
        size_bytes=len(compressed),
        created_at=datetime.now(),
        compression=BACKUP_COMPRESSION,
        conversations_count=len(data["conversations"]),
    )


async def list_backups(user_id: str) -> List[BackupInfo]:
    """List backups for user."""
    backups = []

    if not BACKUP_DIR.exists():
        return backups

    pattern = f"chat_history_{user_id}_*"
    for filepath in BACKUP_DIR.glob(pattern):
        stat = filepath.stat()

        # Determine compression from extension
        compression = "none"
        if filepath.suffix == ".zst":
            compression = "zstd"
        elif filepath.suffix == ".gz":
            compression = "gzip"

        backups.append(
            BackupInfo(
                filename=filepath.name,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_ctime),
                compression=compression,
                conversations_count=-1,  # Unknown without reading
            )
        )

    return sorted(backups, key=lambda b: b.created_at, reverse=True)


async def restore_backup(filename: str) -> dict:
    """Restore data from backup file. Returns the data (doesn't auto-import)."""
    filepath = BACKUP_DIR / filename

    if not filepath.exists():
        raise FileNotFoundError(f"Backup not found: {filename}")

    with open(filepath, "rb") as f:
        compressed = f.read()

    # Decompress based on extension
    if filename.endswith(".zst"):
        import zstandard as zstd

        dctx = zstd.ZstdDecompressor()
        json_data = dctx.decompress(compressed).decode()
    elif filename.endswith(".gz"):
        import gzip

        json_data = gzip.decompress(compressed).decode()
    else:
        json_data = compressed.decode()

    return json.loads(json_data)


async def cleanup_old_backups():
    """Remove backups older than retention period."""
    if not BACKUP_DIR.exists():
        return

    cutoff = datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS)
    removed = 0

    for filepath in BACKUP_DIR.glob("chat_history_*"):
        stat = filepath.stat()
        if datetime.fromtimestamp(stat.st_ctime) < cutoff:
            filepath.unlink()
            removed += 1

    if removed:
        logger.info(f"Cleaned up {removed} old backups")
