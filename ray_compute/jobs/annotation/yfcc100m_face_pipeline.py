#!/usr/bin/env python3
"""
YFCC100M Face Image Downloader - Production Pipeline

Downloads CC-BY licensed face images from Yahoo Flickr Creative Commons 100M dataset
using proper SQL streaming and PostgreSQL for efficient filtering.

Architecture:
1. Stream 65GB SQL file from S3 using range requests (no full download)
2. Parse SQL INSERT statements and extract face-tagged rows
3. Store filtered metadata in local PostgreSQL
4. Download images in parallel from Flickr URLs

YFCC100M Metadata Schema (from SQL):
    - photo_id (bigint): Unique Flickr photo identifier
    - user_nsid (varchar): User namespace ID
    - user_nickname (varchar): Display name
    - date_taken (timestamp): When photo was taken
    - date_uploaded (timestamp): When uploaded to Flickr
    - capture_device (varchar): Camera/device info
    - title (text): Photo title
    - description (text): Photo description
    - user_tags (text): Comma-separated user tags
    - machine_tags (text): Auto-generated tags
    - longitude (float): GPS longitude
    - latitude (float): GPS latitude
    - accuracy (int): GPS accuracy level
    - page_url (text): Flickr page URL
    - download_url (text): Direct image URL
    - license_type (int): CC license code (1=BY, 2=BY-SA, etc.)
    - server_id (varchar): Flickr server
    - farm_id (int): Flickr farm
    - secret (varchar): URL secret
    - original_secret (varchar): Original secret
    - extension (varchar): File extension

License Codes:
    0: All Rights Reserved
    1: Attribution (CC BY)
    2: Attribution-ShareAlike (CC BY-SA)
    3: Attribution-NoDerivs (CC BY-ND)
    4: Attribution-NonCommercial (CC BY-NC) - EXCLUDED
    5: Attribution-NonCommercial-ShareAlike (CC BY-NC-SA) - EXCLUDED
    6: Attribution-NonCommercial-NoDerivs (CC BY-NC-ND) - EXCLUDED
    7: No Known Copyright (Public Domain)
    8: United States Government Work
    9: Public Domain Mark
    10: CC0 Public Domain

Usage:
    # Step 1: Extract face metadata to PostgreSQL (takes ~2-4 hours)
    python yfcc100m_face_pipeline.py extract --target-count 100000

    # Step 2: Download images from extracted metadata
    python yfcc100m_face_pipeline.py download --max-concurrent 100

    # Step 3: Create YOLO dataset for training
    python yfcc100m_face_pipeline.py create-dataset

Requirements:
    pip install boto3 psycopg2-binary aiohttp aiofiles tqdm
"""

import os
import re
import sys
import json
import gzip
import hashlib
import asyncio
import argparse
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional, Set, Dict, Any, Generator, Tuple
from concurrent.futures import ThreadPoolExecutor
import subprocess

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# S3 bucket info
S3_BUCKET = "multimedia-commons"
S3_SQL_KEY = "tools/etc/yfcc100m_dataset.sql"
S3_SQL_SIZE = 65644027904  # 65GB

# Commercial-safe licenses (CC-BY family, excludes NC)
COMMERCIAL_SAFE_LICENSES = {1, 2, 3, 7, 8, 9, 10}  # BY, BY-SA, BY-ND, PD, Gov, PDM, CC0

# Face-related tags for filtering (case-insensitive)
FACE_TAGS = {
    "face",
    "faces",
    "portrait",
    "selfie",
    "person",
    "people",
    "headshot",
    "closeup",
    "close-up",
    "smile",
    "smiling",
    "profile",
    "human",
    "man",
    "woman",
    "child",
    "baby",
    "girl",
    "boy",
    "adult",
    "senior",
    "elderly",
    "teenager",
    "family",
    "group",
    "crowd",
    "facial",
    "expression",
    "head",
    "eyes",
    "mouth",
    "nose",
    "selfportrait",
    "self-portrait",
}

# Default paths
DEFAULT_OUTPUT_DIR = (
    "/home/axelofwar/Projects/shml-platform/ray_compute/data/datasets/yfcc100m"
)
DEFAULT_DB_NAME = "yfcc100m_faces"

# =============================================================================
# DATABASE SETUP
# =============================================================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS yfcc_face_images (
    photo_id BIGINT PRIMARY KEY,
    user_nsid VARCHAR(255),
    user_nickname VARCHAR(255),
    date_taken TIMESTAMP,
    date_uploaded TIMESTAMP,
    title TEXT,
    description TEXT,
    user_tags TEXT,
    machine_tags TEXT,
    longitude FLOAT,
    latitude FLOAT,
    page_url TEXT,
    download_url TEXT,
    license_type INT,
    server_id VARCHAR(50),
    farm_id INT,
    secret VARCHAR(50),
    original_secret VARCHAR(50),
    extension VARCHAR(10),
    -- Computed fields
    has_face_tag BOOLEAN DEFAULT TRUE,
    is_commercial_safe BOOLEAN DEFAULT TRUE,
    -- Download tracking
    downloaded BOOLEAN DEFAULT FALSE,
    download_path TEXT,
    download_timestamp TIMESTAMP,
    file_hash VARCHAR(64),
    file_size_bytes BIGINT,
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_license ON yfcc_face_images(license_type);
CREATE INDEX IF NOT EXISTS idx_downloaded ON yfcc_face_images(downloaded);
CREATE INDEX IF NOT EXISTS idx_extension ON yfcc_face_images(extension);
"""


def get_db_connection():
    """Get PostgreSQL connection to the shared database."""
    import psycopg2

    # Use the shared PostgreSQL from ml-platform
    db_password = os.getenv("DB_PASSWORD", "")

    # Try to read from secrets file if env var not set
    if not db_password:
        secrets_file = Path("/run/secrets/shared_db_password")
        if secrets_file.exists():
            db_password = secrets_file.read_text().strip()

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("YFCC_DB_NAME", DEFAULT_DB_NAME),
        user=os.getenv("DB_USER", "postgres"),
        password=db_password,
    )
    return conn


def setup_database():
    """Create the YFCC face images table if it doesn't exist."""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    # First, create the database if it doesn't exist
    db_password = os.getenv("DB_PASSWORD", "")
    if not db_password:
        secrets_file = Path("/run/secrets/shared_db_password")
        if secrets_file.exists():
            db_password = secrets_file.read_text().strip()

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database="postgres",
        user=os.getenv("DB_USER", "postgres"),
        password=db_password,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

    cursor = conn.cursor()
    db_name = os.getenv("YFCC_DB_NAME", DEFAULT_DB_NAME)

    # Check if database exists
    cursor.execute(f"SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
    if not cursor.fetchone():
        cursor.execute(f"CREATE DATABASE {db_name}")
        logger.info(f"Created database: {db_name}")

    cursor.close()
    conn.close()

    # Now create the table
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(CREATE_TABLE_SQL)
    conn.commit()
    cursor.close()
    conn.close()

    logger.info("Database setup complete")


# =============================================================================
# SQL PARSING
# =============================================================================


def has_face_tag(tags: str) -> bool:
    """Check if tags contain face-related keywords."""
    if not tags:
        return False
    tags_lower = tags.lower()
    return any(tag in tags_lower for tag in FACE_TAGS)


def is_commercial_safe(license_type: int) -> bool:
    """Check if license allows commercial use."""
    return license_type in COMMERCIAL_SAFE_LICENSES


def parse_sql_values(values_str: str) -> Optional[Dict[str, Any]]:
    """
    Parse a SQL VALUES tuple into a dictionary.

    Handles escaped quotes, NULL values, and various data types.
    """
    try:
        # Remove outer parentheses
        values_str = values_str.strip()
        if values_str.startswith("(") and values_str.endswith(")"):
            values_str = values_str[1:-1]

        # Split by comma, respecting quoted strings
        values = []
        current = ""
        in_quotes = False
        escape_next = False

        for char in values_str:
            if escape_next:
                current += char
                escape_next = False
            elif char == "\\":
                escape_next = True
                current += char
            elif char == "'" and not in_quotes:
                in_quotes = True
                current += char
            elif char == "'" and in_quotes:
                in_quotes = False
                current += char
            elif char == "," and not in_quotes:
                values.append(current.strip())
                current = ""
            else:
                current += char

        if current:
            values.append(current.strip())

        # Parse values into appropriate types
        def parse_value(v):
            v = v.strip()
            if v.upper() == "NULL":
                return None
            if v.startswith("'") and v.endswith("'"):
                return v[1:-1].replace("\\'", "'").replace("\\\\", "\\")
            try:
                return int(v)
            except ValueError:
                try:
                    return float(v)
                except ValueError:
                    return v

        parsed = [parse_value(v) for v in values]

        # Map to field names (based on YFCC100M schema)
        # Schema: photo_id, user_nsid, user_nickname, date_taken, date_uploaded,
        #         capture_device, title, description, user_tags, machine_tags,
        #         longitude, latitude, accuracy, page_url, download_url,
        #         license_type, server_id, farm_id, secret, original_secret,
        #         extension, marker
        if len(parsed) >= 21:
            return {
                "photo_id": parsed[0],
                "user_nsid": parsed[1],
                "user_nickname": parsed[2],
                "date_taken": parsed[3],
                "date_uploaded": parsed[4],
                "title": parsed[6],
                "description": parsed[7],
                "user_tags": parsed[8],
                "machine_tags": parsed[9],
                "longitude": parsed[10],
                "latitude": parsed[11],
                "page_url": parsed[13],
                "download_url": parsed[14],
                "license_type": parsed[15] if isinstance(parsed[15], int) else 0,
                "server_id": parsed[16],
                "farm_id": parsed[17] if isinstance(parsed[17], int) else 0,
                "secret": parsed[18],
                "original_secret": parsed[19],
                "extension": parsed[20],
            }

        return None

    except Exception as e:
        logger.debug(f"Failed to parse values: {e}")
        return None


def stream_sql_inserts(sql_file: Path) -> Generator[Dict[str, Any], None, None]:
    """
    Stream INSERT statements from SQL file and yield parsed rows.

    Handles the large 65GB SQL file by streaming line by line.
    """
    insert_pattern = re.compile(r"INSERT INTO `?\w+`?\s+VALUES\s*\(", re.IGNORECASE)
    values_buffer = ""
    in_values = False

    # Detect compression
    if str(sql_file).endswith(".gz"):
        opener = gzip.open
    else:
        opener = open

    with opener(sql_file, "rt", encoding="utf-8", errors="ignore") as f:
        for line in f:
            # Look for INSERT statements
            if insert_pattern.search(line):
                in_values = True
                # Extract values portion
                values_start = line.find("(")
                if values_start >= 0:
                    values_buffer = line[values_start:]
            elif in_values:
                values_buffer += line

            # Process complete value tuples
            while in_values and "),(" in values_buffer:
                # Find complete tuple
                end_idx = values_buffer.find("),(")
                if end_idx > 0:
                    tuple_str = values_buffer[: end_idx + 1]
                    values_buffer = "(" + values_buffer[end_idx + 3 :]

                    # Parse and yield if it's a face image
                    record = parse_sql_values(tuple_str)
                    if record:
                        yield record

            # Handle end of INSERT statement
            if in_values and ");" in values_buffer:
                # Process remaining tuple
                end_idx = values_buffer.find(");")
                if end_idx > 0:
                    tuple_str = values_buffer[: end_idx + 1]
                    record = parse_sql_values(tuple_str)
                    if record:
                        yield record

                in_values = False
                values_buffer = ""


# =============================================================================
# EXTRACTION PIPELINE
# =============================================================================


def extract_face_metadata(
    sql_file: Path,
    target_count: int = 100000,
    batch_size: int = 1000,
) -> int:
    """
    Extract face-tagged, commercial-safe images from SQL file to PostgreSQL.

    Returns number of records extracted.
    """
    import psycopg2.extras

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get current count
    cursor.execute("SELECT COUNT(*) FROM yfcc_face_images")
    current_count = cursor.fetchone()[0]
    logger.info(f"Current database count: {current_count}")

    if current_count >= target_count:
        logger.info(f"Target already reached: {current_count} >= {target_count}")
        return current_count

    remaining = target_count - current_count
    logger.info(f"Extracting up to {remaining} more records...")

    # Prepare insert statement
    insert_sql = """
        INSERT INTO yfcc_face_images (
            photo_id, user_nsid, user_nickname, date_taken, date_uploaded,
            title, description, user_tags, machine_tags, longitude, latitude,
            page_url, download_url, license_type, server_id, farm_id,
            secret, original_secret, extension, has_face_tag, is_commercial_safe
        ) VALUES %s
        ON CONFLICT (photo_id) DO NOTHING
    """

    batch = []
    extracted = 0
    processed = 0

    for record in stream_sql_inserts(sql_file):
        processed += 1

        # Filter: must have face tags and commercial-safe license
        if not has_face_tag(record.get("user_tags", "")):
            continue
        if not is_commercial_safe(record.get("license_type", 0)):
            continue

        # Prepare record tuple
        batch.append(
            (
                record["photo_id"],
                record["user_nsid"],
                record["user_nickname"],
                record["date_taken"],
                record["date_uploaded"],
                record["title"],
                record["description"],
                record["user_tags"],
                record["machine_tags"],
                record["longitude"],
                record["latitude"],
                record["page_url"],
                record["download_url"],
                record["license_type"],
                record["server_id"],
                record["farm_id"],
                record["secret"],
                record["original_secret"],
                record["extension"],
                True,  # has_face_tag
                True,  # is_commercial_safe
            )
        )

        # Batch insert
        if len(batch) >= batch_size:
            psycopg2.extras.execute_values(cursor, insert_sql, batch)
            conn.commit()
            extracted += len(batch)
            batch = []

            logger.info(
                f"Progress: {extracted}/{target_count} extracted, {processed} processed"
            )

            if extracted >= remaining:
                break

        # Progress logging
        if processed % 100000 == 0:
            logger.info(
                f"Processed {processed:,} records, found {extracted + len(batch):,} face images"
            )

    # Final batch
    if batch:
        psycopg2.extras.execute_values(cursor, insert_sql, batch)
        conn.commit()
        extracted += len(batch)

    cursor.close()
    conn.close()

    logger.info(f"Extraction complete: {extracted} face images extracted")
    return current_count + extracted


# =============================================================================
# DOWNLOAD PIPELINE
# =============================================================================


async def download_image(
    session,
    record: Dict[str, Any],
    output_dir: Path,
    semaphore: asyncio.Semaphore,
) -> Optional[Dict[str, Any]]:
    """Download a single image and return metadata."""
    async with semaphore:
        try:
            photo_id = record["photo_id"]

            # Build Flickr URL
            # Format: https://farm{farm}.staticflickr.com/{server}/{id}_{secret}.{ext}
            farm_id = record.get("farm_id", 1)
            server_id = record.get("server_id", "")
            secret = record.get("secret", "")
            extension = record.get("extension", "jpg")

            if record.get("download_url"):
                url = record["download_url"]
            else:
                url = f"https://farm{farm_id}.staticflickr.com/{server_id}/{photo_id}_{secret}.{extension}"

            # Download
            async with session.get(url, timeout=30) as response:
                if response.status != 200:
                    return None

                content = await response.read()

                # Skip tiny images
                if len(content) < 5000:
                    return None

                # Save image
                filename = f"{photo_id}.{extension}"
                filepath = output_dir / filename

                with open(filepath, "wb") as f:
                    f.write(content)

                # Return metadata for database update
                return {
                    "photo_id": photo_id,
                    "download_path": str(filepath),
                    "file_size_bytes": len(content),
                    "file_hash": hashlib.md5(content).hexdigest(),
                }

        except Exception as e:
            logger.debug(f"Failed to download {record.get('photo_id')}: {e}")
            return None


async def download_images(
    output_dir: Path,
    max_concurrent: int = 100,
    batch_size: int = 500,
) -> int:
    """Download all undownloaded images from database."""
    import aiohttp

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get total to download
    cursor.execute("SELECT COUNT(*) FROM yfcc_face_images WHERE NOT downloaded")
    total = cursor.fetchone()[0]
    logger.info(f"Images to download: {total}")

    if total == 0:
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    semaphore = asyncio.Semaphore(max_concurrent)

    async with aiohttp.ClientSession() as session:
        offset = 0

        while offset < total:
            # Fetch batch of records
            cursor.execute(
                """
                SELECT photo_id, download_url, server_id, farm_id, secret, extension
                FROM yfcc_face_images
                WHERE NOT downloaded
                ORDER BY photo_id
                LIMIT %s OFFSET %s
            """,
                (batch_size, offset),
            )

            records = [
                {
                    "photo_id": row[0],
                    "download_url": row[1],
                    "server_id": row[2],
                    "farm_id": row[3],
                    "secret": row[4],
                    "extension": row[5],
                }
                for row in cursor.fetchall()
            ]

            if not records:
                break

            # Download batch
            tasks = [
                download_image(session, record, output_dir, semaphore)
                for record in records
            ]

            results = await asyncio.gather(*tasks)

            # Update database with download results
            for result in results:
                if result:
                    cursor.execute(
                        """
                        UPDATE yfcc_face_images
                        SET downloaded = TRUE,
                            download_path = %s,
                            file_size_bytes = %s,
                            file_hash = %s,
                            download_timestamp = NOW()
                        WHERE photo_id = %s
                    """,
                        (
                            result["download_path"],
                            result["file_size_bytes"],
                            result["file_hash"],
                            result["photo_id"],
                        ),
                    )
                    downloaded += 1

            conn.commit()
            offset += batch_size

            logger.info(f"Progress: {downloaded}/{total} downloaded")

    cursor.close()
    conn.close()

    logger.info(f"Download complete: {downloaded} images")
    return downloaded


# =============================================================================
# DATASET CREATION
# =============================================================================


def create_yolo_dataset(
    output_dir: Path,
    train_ratio: float = 0.9,
) -> None:
    """
    Create YOLO-format dataset from downloaded images.

    Note: Images only - annotations will be added by SAM2 auto-annotation pipeline.
    """
    from sklearn.model_selection import train_test_split

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get downloaded images
    cursor.execute(
        """
        SELECT download_path FROM yfcc_face_images
        WHERE downloaded AND download_path IS NOT NULL
    """
    )

    image_paths = [Path(row[0]) for row in cursor.fetchall()]
    cursor.close()
    conn.close()

    logger.info(f"Creating YOLO dataset from {len(image_paths)} images")

    # Split train/val
    train_images, val_images = train_test_split(
        image_paths, train_size=train_ratio, random_state=42
    )

    # Create directories
    yolo_dir = output_dir / "yolo"
    (yolo_dir / "images" / "train").mkdir(parents=True, exist_ok=True)
    (yolo_dir / "images" / "val").mkdir(parents=True, exist_ok=True)
    (yolo_dir / "labels" / "train").mkdir(parents=True, exist_ok=True)
    (yolo_dir / "labels" / "val").mkdir(parents=True, exist_ok=True)

    # Create symlinks
    for img in train_images:
        if img.exists():
            dst = yolo_dir / "images" / "train" / img.name
            if not dst.exists():
                os.symlink(img, dst)

    for img in val_images:
        if img.exists():
            dst = yolo_dir / "images" / "val" / img.name
            if not dst.exists():
                os.symlink(img, dst)

    # Create data.yaml
    yaml_content = f"""# YFCC100M Face Dataset (pending SAM2 annotation)
path: {yolo_dir}
train: images/train
val: images/val

nc: 1
names: ['face']

# Source: Yahoo Flickr Creative Commons 100M Dataset
# License: CC-BY family (commercial use allowed)
# Status: Images only - run SAM2 auto-annotation pipeline for labels
"""

    with open(yolo_dir / "data.yaml", "w") as f:
        f.write(yaml_content)

    logger.info(f"YOLO dataset created at {yolo_dir}")
    logger.info(f"  Train: {len(train_images)} images")
    logger.info(f"  Val: {len(val_images)} images")
    logger.info("  NOTE: Run SAM2 auto-annotation to generate labels")


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="YFCC100M Face Image Pipeline")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Extract command
    extract_parser = subparsers.add_parser(
        "extract", help="Extract face metadata from SQL"
    )
    extract_parser.add_argument(
        "--sql-file", type=str, required=True, help="Path to yfcc100m_dataset.sql file"
    )
    extract_parser.add_argument(
        "--target-count",
        type=int,
        default=100000,
        help="Target number of face images to extract",
    )

    # Download command
    download_parser = subparsers.add_parser(
        "download", help="Download images from metadata"
    )
    download_parser.add_argument(
        "--output-dir",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for images",
    )
    download_parser.add_argument(
        "--max-concurrent", type=int, default=100, help="Maximum concurrent downloads"
    )

    # Create dataset command
    dataset_parser = subparsers.add_parser("create-dataset", help="Create YOLO dataset")
    dataset_parser.add_argument(
        "--output-dir", type=str, default=DEFAULT_OUTPUT_DIR, help="Output directory"
    )

    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Setup database")

    args = parser.parse_args()

    if args.command == "setup":
        setup_database()

    elif args.command == "extract":
        setup_database()
        sql_file = Path(args.sql_file)
        if not sql_file.exists():
            logger.error(f"SQL file not found: {sql_file}")
            sys.exit(1)
        extract_face_metadata(sql_file, args.target_count)

    elif args.command == "download":
        output_dir = Path(args.output_dir) / "images"
        asyncio.run(download_images(output_dir, args.max_concurrent))

    elif args.command == "create-dataset":
        output_dir = Path(args.output_dir)
        create_yolo_dataset(output_dir)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
