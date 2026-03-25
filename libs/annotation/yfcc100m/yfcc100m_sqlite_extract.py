#!/usr/bin/env python3
"""
YFCC100M SQLite Face Extractor

Directly queries the 64GB SQLite database to extract face-tagged,
commercial-safe images for the PII detection training pipeline.

The YFCC100M dataset is stored as SQLite (not SQL text dump).

Schema:
    photoid integer primary key
    uid text
    unickname text
    datetaken text
    dateuploaded text
    capturedevice text
    title text
    description text
    usertags text
    machinetags text
    longitude text
    latitude text
    accuracy integer
    pageurl text
    downloadurl text
    licensename text
    licenseurl text
    serverid integer
    farmid integer
    secret text
    secretoriginal text
    ext text
    marker integer

License Filter (Commercial-Safe):
    - "Attribution License" (CC BY)
    - "Attribution-ShareAlike License" (CC BY-SA)
    - "Attribution-NoDerivs License" (CC BY-ND)
    - "Public Domain" variants
    - "United States Government Work"

    EXCLUDED (Non-Commercial):
    - "Attribution-NonCommercial*" (CC BY-NC*)

Usage:
    python yfcc100m_sqlite_extract.py extract --target-count 100000
    python yfcc100m_sqlite_extract.py download --max-concurrent 50
    python yfcc100m_sqlite_extract.py stats
"""

import os
import sys
import sqlite3
import hashlib
import asyncio
import argparse
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Generator
from dataclasses import dataclass
from datetime import datetime
import json

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Platform root - avoid hardcoded paths
PLATFORM_ROOT = os.environ.get("PLATFORM_ROOT", str(Path(__file__).resolve().parents[3]))

# =============================================================================
# CONSTANTS
# =============================================================================

# Default paths
SQLITE_DB_PATH = os.environ.get("YFCC100M_SQLITE_PATH", "./yfcc100m_download/yfcc100m_dataset.sql")
OUTPUT_DIR = Path(
    f"{PLATFORM_ROOT}/ray_compute/data/datasets/yfcc100m"
)
METADATA_DB = OUTPUT_DIR / "face_metadata.db"

# Commercial-safe license patterns (case-insensitive contains)
COMMERCIAL_SAFE_LICENSES = [
    "Attribution License",  # CC BY
    "Attribution-ShareAlike",  # CC BY-SA
    "Attribution-NoDerivs License",  # CC BY-ND (but not NonCommercial-NoDerivs)
    "Public Domain",
    "United States Government",
    "No known copyright",
]

# Licenses to EXCLUDE (Non-Commercial)
EXCLUDED_LICENSES = [
    "NonCommercial",  # Catches all NC variants
]

# Face-related tags for filtering
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
    "selfportrait",
    "self-portrait",
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def is_commercial_safe(license_name: str) -> bool:
    """Check if license allows commercial use."""
    if not license_name:
        return False

    license_lower = license_name.lower()

    # First check exclusions (NonCommercial)
    for excluded in EXCLUDED_LICENSES:
        if excluded.lower() in license_lower:
            return False

    # Then check if it matches a safe license
    for safe in COMMERCIAL_SAFE_LICENSES:
        if safe.lower() in license_lower:
            return True

    return False


def has_face_tag(usertags: str, title: str = "", description: str = "") -> bool:
    """Check if any field contains face-related keywords."""
    if not usertags and not title and not description:
        return False

    # Combine all text fields
    combined = f"{usertags or ''} {title or ''} {description or ''}".lower()

    # URL decode common patterns
    combined = combined.replace("%20", " ").replace("+", " ").replace("%2c", ",")

    return any(tag in combined for tag in FACE_TAGS)


def url_decode(text: str) -> str:
    """Simple URL decode for common patterns."""
    if not text:
        return ""
    from urllib.parse import unquote

    try:
        return unquote(text.replace("+", " "))
    except:
        return text


# =============================================================================
# LOCAL METADATA DATABASE
# =============================================================================


def setup_local_db(db_path: Path) -> sqlite3.Connection:
    """Create local SQLite database for extracted metadata."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS face_images (
            photoid INTEGER PRIMARY KEY,
            uid TEXT,
            unickname TEXT,
            datetaken TEXT,
            title TEXT,
            description TEXT,
            usertags TEXT,
            downloadurl TEXT,
            licensename TEXT,
            ext TEXT,
            -- Download tracking
            downloaded INTEGER DEFAULT 0,
            download_path TEXT,
            file_size INTEGER,
            file_hash TEXT,
            download_time TEXT,
            -- Metadata
            extracted_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_downloaded ON face_images(downloaded)")
    conn.commit()

    return conn


# =============================================================================
# EXTRACTION
# =============================================================================


def extract_face_images(
    sqlite_path: str,
    output_db: Path,
    target_count: int = 100000,
    batch_size: int = 10000,
) -> int:
    """
    Extract face-tagged, commercial-safe images from YFCC100M SQLite.

    Uses streaming query to avoid loading entire 64GB database into memory.
    """
    logger.info(f"Opening YFCC100M database: {sqlite_path}")

    # Connect to source (read-only for safety)
    source_uri = f"file:{sqlite_path}?mode=ro"
    source_conn = sqlite3.connect(source_uri, uri=True)
    source_conn.row_factory = sqlite3.Row

    # Setup output database
    out_conn = setup_local_db(output_db)

    # Check current count
    current_count = out_conn.execute("SELECT COUNT(*) FROM face_images").fetchone()[0]
    logger.info(f"Current extracted count: {current_count}")

    if current_count >= target_count:
        logger.info(f"Target already reached: {current_count} >= {target_count}")
        return current_count

    remaining = target_count - current_count
    logger.info(f"Need to extract {remaining} more face images...")

    # Query for commercial-safe images with streaming
    # We filter by license patterns that indicate commercial use is OK
    query = """
        SELECT photoid, uid, unickname, datetaken, title, description,
               usertags, downloadurl, licensename, ext
        FROM yfcc100m_dataset
        WHERE downloadurl IS NOT NULL
          AND downloadurl != ''
          AND ext IN ('jpg', 'jpeg', 'png', 'JPG', 'JPEG', 'PNG')
          AND (
              licensename LIKE '%Attribution License%'
              OR licensename LIKE '%Attribution-ShareAlike%'
              OR licensename LIKE '%Public Domain%'
              OR licensename LIKE '%Government%'
          )
          AND licensename NOT LIKE '%NonCommercial%'
    """

    logger.info("Starting extraction query (this may take a while on 64GB database)...")

    extracted = 0
    processed = 0
    batch = []

    cursor = source_conn.execute(query)

    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break

        for row in rows:
            processed += 1

            # Check for face tags
            usertags = url_decode(row["usertags"] or "")
            title = url_decode(row["title"] or "")
            description = url_decode(row["description"] or "")

            if not has_face_tag(usertags, title, description):
                continue

            # Double-check license (defensive)
            if not is_commercial_safe(row["licensename"]):
                continue

            batch.append(
                (
                    row["photoid"],
                    row["uid"],
                    row["unickname"],
                    row["datetaken"],
                    title,
                    description,
                    usertags,
                    row["downloadurl"],
                    row["licensename"],
                    row["ext"],
                )
            )

            # Batch insert
            if len(batch) >= 1000:
                out_conn.executemany(
                    """
                    INSERT OR IGNORE INTO face_images
                    (photoid, uid, unickname, datetaken, title, description,
                     usertags, downloadurl, licensename, ext)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    batch,
                )
                out_conn.commit()

                extracted += len(batch)
                batch = []

                logger.info(
                    f"Progress: {extracted:,} extracted, {processed:,} processed"
                )

                if extracted >= remaining:
                    break

        if extracted >= remaining:
            break

        # Progress update
        if processed % 100000 == 0:
            logger.info(
                f"Scanned {processed:,} records, found {extracted + len(batch):,} face images"
            )

    # Final batch
    if batch:
        out_conn.executemany(
            """
            INSERT OR IGNORE INTO face_images
            (photoid, uid, unickname, datetaken, title, description,
             usertags, downloadurl, licensename, ext)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            batch,
        )
        out_conn.commit()
        extracted += len(batch)

    source_conn.close()
    out_conn.close()

    final_count = current_count + extracted
    logger.info(
        f"Extraction complete: {extracted:,} new records, {final_count:,} total"
    )

    return final_count


# =============================================================================
# DOWNLOAD
# =============================================================================


async def download_image(
    session,
    record: Dict[str, Any],
    output_dir: Path,
    semaphore: asyncio.Semaphore,
) -> Optional[Dict[str, Any]]:
    """Download a single image."""
    async with semaphore:
        try:
            url = record["downloadurl"]
            photoid = record["photoid"]
            ext = record["ext"] or "jpg"

            async with session.get(url, timeout=30) as response:
                if response.status != 200:
                    return None

                content = await response.read()

                # Skip tiny images (likely errors)
                if len(content) < 5000:
                    return None

                # Save
                filename = f"{photoid}.{ext}"
                filepath = output_dir / filename

                with open(filepath, "wb") as f:
                    f.write(content)

                return {
                    "photoid": photoid,
                    "path": str(filepath),
                    "size": len(content),
                    "hash": hashlib.md5(content).hexdigest(),
                }

        except Exception as e:
            logger.debug(f"Download failed for {record.get('photoid')}: {e}")
            return None


async def download_images(
    metadata_db: Path,
    output_dir: Path,
    max_concurrent: int = 50,
    batch_size: int = 500,
) -> int:
    """Download all undownloaded images."""
    import aiohttp

    conn = sqlite3.connect(str(metadata_db))
    conn.row_factory = sqlite3.Row

    # Count pending
    total = conn.execute(
        "SELECT COUNT(*) FROM face_images WHERE downloaded = 0"
    ).fetchone()[0]
    logger.info(f"Images to download: {total:,}")

    if total == 0:
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    semaphore = asyncio.Semaphore(max_concurrent)

    async with aiohttp.ClientSession() as session:
        offset = 0

        while offset < total:
            # Fetch batch
            rows = conn.execute(
                """
                SELECT photoid, downloadurl, ext
                FROM face_images
                WHERE downloaded = 0
                LIMIT ? OFFSET ?
            """,
                (batch_size, offset),
            ).fetchall()

            if not rows:
                break

            records = [dict(row) for row in rows]

            # Download batch
            tasks = [
                download_image(session, rec, output_dir, semaphore) for rec in records
            ]

            results = await asyncio.gather(*tasks)

            # Update database
            for result in results:
                if result:
                    conn.execute(
                        """
                        UPDATE face_images
                        SET downloaded = 1,
                            download_path = ?,
                            file_size = ?,
                            file_hash = ?,
                            download_time = ?
                        WHERE photoid = ?
                    """,
                        (
                            result["path"],
                            result["size"],
                            result["hash"],
                            datetime.now().isoformat(),
                            result["photoid"],
                        ),
                    )
                    downloaded += 1

            conn.commit()
            offset += batch_size

            logger.info(
                f"Progress: {downloaded:,}/{total:,} downloaded ({100*downloaded/total:.1f}%)"
            )

    conn.close()
    logger.info(f"Download complete: {downloaded:,} images")

    return downloaded


# =============================================================================
# STATS
# =============================================================================


def show_stats(metadata_db: Path):
    """Show extraction and download statistics."""
    if not metadata_db.exists():
        logger.info("No metadata database found. Run 'extract' first.")
        return

    conn = sqlite3.connect(str(metadata_db))

    total = conn.execute("SELECT COUNT(*) FROM face_images").fetchone()[0]
    downloaded = conn.execute(
        "SELECT COUNT(*) FROM face_images WHERE downloaded = 1"
    ).fetchone()[0]
    pending = total - downloaded

    # License breakdown
    licenses = conn.execute(
        """
        SELECT licensename, COUNT(*) as cnt
        FROM face_images
        GROUP BY licensename
        ORDER BY cnt DESC
    """
    ).fetchall()

    # Top tags
    tags = conn.execute(
        """
        SELECT usertags FROM face_images LIMIT 1000
    """
    ).fetchall()

    conn.close()

    print("\n" + "=" * 60)
    print("YFCC100M Face Images - Extraction Stats")
    print("=" * 60)
    print(f"Total extracted:    {total:,}")
    print(f"Downloaded:         {downloaded:,}")
    print(f"Pending download:   {pending:,}")
    print(f"\nMetadata DB: {metadata_db}")
    print(f"Images dir:  {metadata_db.parent / 'images'}")

    print("\nLicense breakdown:")
    for lic, cnt in licenses[:5]:
        print(f"  {lic}: {cnt:,}")

    print("=" * 60 + "\n")


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="YFCC100M Face Image Extractor")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Extract
    extract_p = subparsers.add_parser(
        "extract", help="Extract face metadata from SQLite"
    )
    extract_p.add_argument(
        "--sqlite-path",
        default=SQLITE_DB_PATH,
        help="Path to yfcc100m_dataset.sql SQLite database",
    )
    extract_p.add_argument(
        "--output-db",
        type=Path,
        default=METADATA_DB,
        help="Output metadata database path",
    )
    extract_p.add_argument(
        "--target-count", type=int, default=100000, help="Target number of face images"
    )

    # Download
    download_p = subparsers.add_parser("download", help="Download extracted images")
    download_p.add_argument(
        "--metadata-db", type=Path, default=METADATA_DB, help="Metadata database path"
    )
    download_p.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR / "images",
        help="Output directory for images",
    )
    download_p.add_argument(
        "--max-concurrent", type=int, default=50, help="Max concurrent downloads"
    )

    # Stats
    stats_p = subparsers.add_parser("stats", help="Show statistics")
    stats_p.add_argument(
        "--metadata-db", type=Path, default=METADATA_DB, help="Metadata database path"
    )

    args = parser.parse_args()

    if args.command == "extract":
        extract_face_images(
            args.sqlite_path,
            args.output_db,
            args.target_count,
        )

    elif args.command == "download":
        import aiohttp  # Check dependency

        asyncio.run(
            download_images(
                args.metadata_db,
                args.output_dir,
                args.max_concurrent,
            )
        )

    elif args.command == "stats":
        show_stats(args.metadata_db)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
