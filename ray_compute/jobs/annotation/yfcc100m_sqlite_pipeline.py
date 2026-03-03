#!/usr/bin/env python3
"""
YFCC100M Face Image Downloader - SQLite Pipeline

Adapted from yfcc100m_face_pipeline.py to read from SQLite database instead of SQL dump.
"""

import os
import sys
import sqlite3
import hashlib
import asyncio
import argparse
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Generator
import psycopg2
import psycopg2.extras

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Commercial-safe licenses (CC-BY family, excludes NC)
# 1: Attribution (CC BY)
# 2: Attribution-ShareAlike (CC BY-SA)
# 3: Attribution-NoDerivs (CC BY-ND)
# 7: No Known Copyright (Public Domain)
# 8: United States Government Work
# 9: Public Domain Mark
# 10: CC0 Public Domain
COMMERCIAL_SAFE_LICENSES = {1, 2, 3, 7, 8, 9, 10}

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
    db_password = os.getenv("DB_PASSWORD", "")
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
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

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

    cursor.execute(f"SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
    if not cursor.fetchone():
        cursor.execute(f"CREATE DATABASE {db_name}")
        logger.info(f"Created database: {db_name}")

    cursor.close()
    conn.close()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(CREATE_TABLE_SQL)
    conn.commit()
    cursor.close()
    conn.close()

    logger.info("Database setup complete")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def has_face_tag(tags: str) -> bool:
    if not tags:
        return False
    tags_lower = tags.lower()
    return any(tag in tags_lower for tag in FACE_TAGS)


def get_license_id(url: str) -> int:
    if not url:
        return 0
    url = url.lower()
    if "by/2.0" in url and "nc" not in url and "nd" not in url and "sa" not in url:
        return 1  # CC BY
    if "by-sa/2.0" in url and "nc" not in url:
        return 2  # CC BY-SA
    if "by-nd/2.0" in url and "nc" not in url:
        return 3  # CC BY-ND
    if "by-nc/2.0" in url:
        return 4  # CC BY-NC
    if "by-nc-sa/2.0" in url:
        return 5  # CC BY-NC-SA
    if "by-nc-nd/2.0" in url:
        return 6  # CC BY-NC-ND
    if "commons/usage" in url:
        return 7  # PD
    if "usa.gov" in url:
        return 8  # Gov
    if "publicdomain/mark" in url:
        return 9  # PDM
    if "publicdomain/zero" in url:
        return 10  # CC0
    return 0


def is_commercial_safe(license_type: int) -> bool:
    return license_type in COMMERCIAL_SAFE_LICENSES


# =============================================================================
# SQLITE STREAMING
# =============================================================================


def stream_sqlite_records(sqlite_file: Path) -> Generator[Dict[str, Any], None, None]:
    """Stream records from SQLite database."""
    conn = sqlite3.connect(sqlite_file)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Query all records
    # Schema: photoid, uid, unickname, datetaken, dateuploaded, capturedevice,
    # title, description, usertags, machinetags, longitude, latitude, accuracy,
    # pageurl, downloadurl, license_name, license_url, server_id, farm_id,
    # secret, secret_original, ext, marker

    cursor.execute("SELECT * FROM yfcc100m_dataset")

    while True:
        rows = cursor.fetchmany(1000)
        if not rows:
            break

        for row in rows:
            try:
                license_url = row["license_url"]
                license_type = get_license_id(license_url)

                yield {
                    "photo_id": row["photoid"],
                    "user_nsid": row["uid"],
                    "user_nickname": row["unickname"],
                    "date_taken": row["datetaken"],
                    "date_uploaded": row["dateuploaded"],
                    "title": row["title"],
                    "description": row["description"],
                    "user_tags": row["usertags"],
                    "machine_tags": row["machinetags"],
                    "longitude": float(row["longitude"]) if row["longitude"] else None,
                    "latitude": float(row["latitude"]) if row["latitude"] else None,
                    "page_url": row["pageurl"],
                    "download_url": row["downloadurl"],
                    "license_type": license_type,
                    "server_id": row["server_id"],
                    "farm_id": int(row["farm_id"]) if row["farm_id"] else 0,
                    "secret": row["secret"],
                    "original_secret": row["secret_original"],
                    "extension": row["ext"],
                }
            except Exception as e:
                logger.debug(f"Error parsing row {row['photoid']}: {e}")
                continue

    conn.close()


# =============================================================================
# EXTRACTION PIPELINE
# =============================================================================


def extract_face_metadata(
    sqlite_file: Path,
    target_count: int = 100000,
    batch_size: int = 1000,
) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM yfcc_face_images")
    current_count = cursor.fetchone()[0]
    logger.info(f"Current database count: {current_count}")

    if current_count >= target_count:
        logger.info(f"Target already reached: {current_count} >= {target_count}")
        return current_count

    remaining = target_count - current_count
    logger.info(f"Extracting up to {remaining} more records...")

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

    for record in stream_sqlite_records(sqlite_file):
        processed += 1

        if not has_face_tag(record.get("user_tags", "")):
            continue
        if not is_commercial_safe(record.get("license_type", 0)):
            continue

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
                True,
                True,
            )
        )

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

        if processed % 100000 == 0:
            logger.info(
                f"Processed {processed:,} records, found {extracted + len(batch):,} face images"
            )

    if batch:
        psycopg2.extras.execute_values(cursor, insert_sql, batch)
        conn.commit()
        extracted += len(batch)

    cursor.close()
    conn.close()

    logger.info(f"Extraction complete: {extracted} face images extracted")
    return current_count + extracted


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="YFCC100M Face Image Pipeline (SQLite)"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    extract_parser = subparsers.add_parser(
        "extract", help="Extract face metadata from SQLite"
    )
    extract_parser.add_argument(
        "--sqlite-file",
        type=str,
        required=True,
        help="Path to yfcc100m_dataset.sql (SQLite) file",
    )
    extract_parser.add_argument(
        "--target-count",
        type=int,
        default=100000,
        help="Target number of face images to extract",
    )

    setup_parser = subparsers.add_parser("setup", help="Setup database")

    args = parser.parse_args()

    if args.command == "setup":
        setup_database()
    elif args.command == "extract":
        setup_database()
        sqlite_file = Path(args.sqlite_file)
        if not sqlite_file.exists():
            logger.error(f"SQLite file not found: {sqlite_file}")
            sys.exit(1)
        extract_face_metadata(sqlite_file, args.target_count)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
