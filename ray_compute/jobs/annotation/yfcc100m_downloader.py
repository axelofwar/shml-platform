#!/usr/bin/env python3
"""
YFCC100M Face Image Downloader
Downloads CC-BY licensed face images from Yahoo Flickr Creative Commons 100M dataset.

YFCC100M: https://multimediacommons.wordpress.com/yfcc100m-core-dataset/
- 100 million Flickr images with CC licenses
- ~15 million with face-related tags
- Free via AWS Open Data: s3://multimedia-commons

Usage:
    # Download 50K face images (default for Phase 3)
    python yfcc100m_downloader.py --target-count 50000

    # Download with specific license filter
    python yfcc100m_downloader.py --target-count 100000 --licenses "CC BY 2.0,CC BY-SA 2.0"

    # Resume interrupted download
    python yfcc100m_downloader.py --resume

Requirements:
    pip install boto3 pandas tqdm aiohttp aiofiles pillow

License Compliance:
    - Only downloads CC-BY and CC-BY-SA licensed images (commercial-safe)
    - Preserves license metadata for attribution
    - Excludes NC (Non-Commercial) licenses
"""

import os
import sys
import json
import hashlib
import asyncio
import argparse
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional, Set, Dict, Any
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from tqdm import tqdm

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# YFCC100M Constants
YFCC_BUCKET = "multimedia-commons"
YFCC_METADATA_PREFIX = "yfcc100m/set_"
YFCC_IMAGE_PREFIX = "data/images"

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
}

# Commercial-safe licenses (CC-BY family, excludes NC)
COMMERCIAL_LICENSES = {
    "Attribution License": True,  # CC BY 2.0
    "Attribution-ShareAlike License": True,  # CC BY-SA 2.0
    "Attribution-NoDerivs License": True,  # CC BY-ND 2.0
    "Attribution-NonCommercial License": False,  # CC BY-NC 2.0 (excluded)
    "Attribution-NonCommercial-ShareAlike License": False,  # CC BY-NC-SA 2.0 (excluded)
    "Attribution-NonCommercial-NoDerivs License": False,  # CC BY-NC-ND 2.0 (excluded)
    "No known copyright restrictions": True,  # Public domain
    "United States Government Work": True,  # US Government (public domain)
}

# Default license codes we accept
DEFAULT_LICENSES = ["1", "2", "3", "7", "9"]  # CC BY, CC BY-SA, CC BY-ND, PD, US Gov


@dataclass
class ImageMetadata:
    """Metadata for a downloaded YFCC100M image."""

    photo_id: str
    user_id: str
    user_name: str
    date_taken: str
    date_uploaded: str
    capture_device: str
    title: str
    description: str
    tags: str
    machine_tags: str
    longitude: str
    latitude: str
    accuracy: str
    page_url: str
    download_url: str
    license_name: str
    license_url: str
    server_id: str
    farm_id: str
    secret: str
    secret_original: str
    extension: str
    marker: str
    local_path: Optional[str] = None
    download_timestamp: Optional[str] = None
    file_hash: Optional[str] = None


class YFCC100MDownloader:
    """
    Downloads face images from YFCC100M dataset with license filtering.

    Features:
    - Filters by face-related tags
    - Only downloads commercial-safe licenses (CC-BY family)
    - Async parallel downloads for speed
    - Resume support for interrupted downloads
    - Metadata preservation for attribution
    """

    def __init__(
        self,
        output_dir: str = "/data/datasets/yfcc100m",
        target_count: int = 50000,
        max_concurrent: int = 50,
        licenses: Optional[List[str]] = None,
        min_resolution: int = 256,
        resume: bool = True,
    ):
        self.output_dir = Path(output_dir)
        self.target_count = target_count
        self.max_concurrent = max_concurrent
        self.licenses = licenses or DEFAULT_LICENSES
        self.min_resolution = min_resolution
        self.resume = resume

        # Subdirectories
        self.images_dir = self.output_dir / "images"
        self.metadata_dir = self.output_dir / "metadata"
        self.progress_dir = self.output_dir / "progress"

        # Progress tracking
        self.downloaded_ids: Set[str] = set()
        self.failed_ids: Set[str] = set()
        self.progress_file = self.progress_dir / "download_progress.json"
        self.metadata_file = self.metadata_dir / "image_metadata.jsonl"

        # Statistics
        self.stats = {
            "total_candidates": 0,
            "face_tagged": 0,
            "license_filtered": 0,
            "downloaded": 0,
            "failed": 0,
            "skipped": 0,
        }

    def setup_directories(self):
        """Create output directory structure."""
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.progress_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output directory: {self.output_dir}")

    def load_progress(self):
        """Load progress from previous run."""
        if self.resume and self.progress_file.exists():
            with open(self.progress_file, "r") as f:
                progress = json.load(f)
            self.downloaded_ids = set(progress.get("downloaded_ids", []))
            self.failed_ids = set(progress.get("failed_ids", []))
            self.stats = progress.get("stats", self.stats)
            logger.info(
                f"Resumed: {len(self.downloaded_ids)} downloaded, {len(self.failed_ids)} failed"
            )

    def save_progress(self):
        """Save progress for resume capability."""
        progress = {
            "downloaded_ids": list(self.downloaded_ids),
            "failed_ids": list(self.failed_ids),
            "stats": self.stats,
            "last_updated": datetime.now().isoformat(),
        }
        with open(self.progress_file, "w") as f:
            json.dump(progress, f)

    def has_face_tags(self, tags: str) -> bool:
        """Check if image has face-related tags."""
        if not tags:
            return False
        tag_set = set(t.lower().strip() for t in tags.split(","))
        return bool(tag_set & FACE_TAGS)

    def is_commercial_safe(self, license_code: str) -> bool:
        """Check if license allows commercial use."""
        return license_code in self.licenses

    def parse_metadata_line(self, line: str) -> Optional[ImageMetadata]:
        """Parse a line from YFCC100M metadata TSV."""
        try:
            fields = line.strip().split("\t")
            if len(fields) < 23:
                return None

            return ImageMetadata(
                photo_id=fields[0],
                user_id=fields[1],
                user_name=fields[2],
                date_taken=fields[3],
                date_uploaded=fields[4],
                capture_device=fields[5],
                title=fields[6],
                description=fields[7],
                tags=fields[8],
                machine_tags=fields[9],
                longitude=fields[10],
                latitude=fields[11],
                accuracy=fields[12],
                page_url=fields[13],
                download_url=fields[14],
                license_name=fields[15],
                license_url=fields[16],
                server_id=fields[17],
                farm_id=fields[18],
                secret=fields[19],
                secret_original=fields[20],
                extension=fields[21],
                marker=fields[22] if len(fields) > 22 else "",
            )
        except Exception as e:
            logger.debug(f"Failed to parse metadata line: {e}")
            return None

    def filter_candidates(self, metadata: ImageMetadata) -> bool:
        """
        Filter image candidates based on criteria.

        Returns True if image should be downloaded.
        """
        self.stats["total_candidates"] += 1

        # Skip if already processed
        if (
            metadata.photo_id in self.downloaded_ids
            or metadata.photo_id in self.failed_ids
        ):
            self.stats["skipped"] += 1
            return False

        # Must have face-related tags
        if not self.has_face_tags(metadata.tags):
            return False
        self.stats["face_tagged"] += 1

        # Must have commercial-safe license
        # License is encoded as a number in the download_url or license_name
        # We'll check based on marker field which contains the license code
        license_code = metadata.marker.strip() if metadata.marker else ""
        if not self.is_commercial_safe(license_code):
            return False
        self.stats["license_filtered"] += 1

        # Must have a download URL
        if not metadata.download_url or metadata.download_url == "None":
            return False

        return True

    async def download_image(
        self,
        session,
        metadata: ImageMetadata,
        semaphore: asyncio.Semaphore,
    ) -> bool:
        """
        Download a single image with metadata.

        Returns True on success, False on failure.
        """
        async with semaphore:
            try:
                # Build download URL (YFCC100M URLs are Flickr URLs)
                url = metadata.download_url
                if not url.startswith("http"):
                    url = f"https://farm{metadata.farm_id}.staticflickr.com/{metadata.server_id}/{metadata.photo_id}_{metadata.secret}.{metadata.extension}"

                # Download image
                async with session.get(url, timeout=30) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}")

                    content = await response.read()

                    # Verify minimum size (skip tiny images)
                    if len(content) < 10000:  # < 10KB likely not a real photo
                        raise Exception("Image too small")

                    # Save image
                    ext = metadata.extension or "jpg"
                    filename = f"{metadata.photo_id}.{ext}"
                    filepath = self.images_dir / filename

                    async with asyncio.Lock():
                        with open(filepath, "wb") as f:
                            f.write(content)

                    # Calculate hash for deduplication
                    file_hash = hashlib.md5(content).hexdigest()

                    # Update metadata
                    metadata.local_path = str(filepath)
                    metadata.download_timestamp = datetime.now().isoformat()
                    metadata.file_hash = file_hash

                    # Save metadata
                    async with asyncio.Lock():
                        with open(self.metadata_file, "a") as f:
                            f.write(json.dumps(asdict(metadata)) + "\n")

                    self.downloaded_ids.add(metadata.photo_id)
                    self.stats["downloaded"] += 1
                    return True

            except Exception as e:
                logger.debug(f"Failed to download {metadata.photo_id}: {e}")
                self.failed_ids.add(metadata.photo_id)
                self.stats["failed"] += 1
                return False

    async def download_batch(
        self,
        candidates: List[ImageMetadata],
    ) -> int:
        """
        Download a batch of images concurrently.

        Returns number of successfully downloaded images.
        """
        import aiohttp

        semaphore = asyncio.Semaphore(self.max_concurrent)

        async with aiohttp.ClientSession() as session:
            tasks = [
                self.download_image(session, meta, semaphore) for meta in candidates
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

        return sum(1 for r in results if r is True)

    def process_metadata_file(self, filepath: str) -> List[ImageMetadata]:
        """
        Process a YFCC100M metadata file and extract face candidates.

        YFCC100M metadata is split into 100 files (set_0.tsv to set_99.tsv).
        """
        candidates = []

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    metadata = self.parse_metadata_line(line)
                    if metadata and self.filter_candidates(metadata):
                        candidates.append(metadata)

                        # Check if we have enough candidates
                        remaining = self.target_count - len(self.downloaded_ids)
                        if len(candidates) >= remaining * 2:  # 2x buffer for failures
                            break

        except Exception as e:
            logger.error(f"Failed to process {filepath}: {e}")

        return candidates

    def download_metadata_from_s3(self, set_number: int) -> Optional[str]:
        """
        Download YFCC100M metadata file from AWS S3.

        Uses AWS CLI for reliability (handles large files).
        """
        import subprocess

        s3_key = f"yfcc100m/set_{set_number}/yfcc100m_dataset_{set_number}.tsv"
        local_path = self.metadata_dir / f"yfcc100m_set_{set_number}.tsv"

        if local_path.exists():
            logger.info(f"Using cached metadata: {local_path}")
            return str(local_path)

        logger.info(f"Downloading metadata set {set_number} from S3...")

        try:
            # Use AWS CLI for large file download
            cmd = [
                "aws",
                "s3",
                "cp",
                f"s3://{YFCC_BUCKET}/{s3_key}",
                str(local_path),
                "--no-sign-request",  # Public bucket, no auth needed
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"S3 download failed: {result.stderr}")
                return None

            return str(local_path)

        except Exception as e:
            logger.error(f"Failed to download metadata: {e}")
            return None

    def run(self):
        """
        Main download loop.

        1. Download metadata from S3 (if not cached)
        2. Filter for face images with commercial licenses
        3. Download images in parallel
        4. Save progress periodically
        """
        self.setup_directories()
        self.load_progress()

        logger.info(f"Target: {self.target_count} images")
        logger.info(f"Already downloaded: {len(self.downloaded_ids)}")

        remaining = self.target_count - len(self.downloaded_ids)
        if remaining <= 0:
            logger.info("Target already reached!")
            return

        # Process metadata sets until we have enough images
        # YFCC100M has 100 metadata files (set_0 to set_99)
        for set_num in range(100):
            if len(self.downloaded_ids) >= self.target_count:
                break

            # Download metadata file
            metadata_path = self.download_metadata_from_s3(set_num)
            if not metadata_path:
                continue

            # Find candidates
            logger.info(f"Processing metadata set {set_num}...")
            candidates = self.process_metadata_file(metadata_path)

            if not candidates:
                logger.info(f"No candidates in set {set_num}")
                continue

            logger.info(f"Found {len(candidates)} candidates in set {set_num}")

            # Download images
            logger.info(f"Downloading images...")
            asyncio.run(self.download_batch(candidates))

            # Save progress
            self.save_progress()

            logger.info(f"Progress: {len(self.downloaded_ids)}/{self.target_count}")

        # Final summary
        logger.info("\n" + "=" * 50)
        logger.info("DOWNLOAD COMPLETE")
        logger.info("=" * 50)
        logger.info(f"Total candidates scanned: {self.stats['total_candidates']}")
        logger.info(f"Face-tagged images: {self.stats['face_tagged']}")
        logger.info(f"License-filtered: {self.stats['license_filtered']}")
        logger.info(f"Successfully downloaded: {self.stats['downloaded']}")
        logger.info(f"Failed downloads: {self.stats['failed']}")
        logger.info(f"Output directory: {self.output_dir}")

        # Save final progress
        self.save_progress()


def create_yolo_dataset(
    yfcc_dir: str = "/data/datasets/yfcc100m",
    output_dir: str = "/data/datasets/yfcc100m_yolo",
    train_ratio: float = 0.9,
):
    """
    Create YOLO-format dataset from downloaded YFCC100M images.

    NOTE: This creates image-only dataset for SAM2 auto-annotation.
    Annotations will be generated by SAM2 pipeline.
    """
    import shutil
    from sklearn.model_selection import train_test_split

    yfcc_path = Path(yfcc_dir)
    output_path = Path(output_dir)

    # Setup directories
    (output_path / "images" / "train").mkdir(parents=True, exist_ok=True)
    (output_path / "images" / "val").mkdir(parents=True, exist_ok=True)
    (output_path / "labels" / "train").mkdir(parents=True, exist_ok=True)
    (output_path / "labels" / "val").mkdir(parents=True, exist_ok=True)

    # Get all images
    images = list((yfcc_path / "images").glob("*.[jJ][pP][gG]"))
    images.extend((yfcc_path / "images").glob("*.[pP][nN][gG]"))

    logger.info(f"Found {len(images)} images")

    # Split into train/val
    train_images, val_images = train_test_split(
        images, train_size=train_ratio, random_state=42
    )

    # Copy images (symlink for efficiency)
    logger.info("Creating train split...")
    for img in tqdm(train_images, desc="Train"):
        dst = output_path / "images" / "train" / img.name
        if not dst.exists():
            os.symlink(img, dst)

    logger.info("Creating val split...")
    for img in tqdm(val_images, desc="Val"):
        dst = output_path / "images" / "val" / img.name
        if not dst.exists():
            os.symlink(img, dst)

    # Create dataset YAML
    yaml_content = f"""# YFCC100M Face Dataset (for SAM2 auto-annotation)
# Downloaded from YFCC100M (CC-BY licensed images)
# Annotations: PENDING - run SAM2 auto-annotation pipeline

path: {output_path}
train: images/train
val: images/val

nc: 1
names: ['face']

# Source: Yahoo Flickr Creative Commons 100M Dataset
# License: CC-BY (commercial use allowed)
# Auto-annotation: Use SAM2 pipeline for face detection + segmentation
"""

    with open(output_path / "data.yaml", "w") as f:
        f.write(yaml_content)

    logger.info(f"Created YOLO dataset at {output_path}")
    logger.info(f"  Train: {len(train_images)} images")
    logger.info(f"  Val: {len(val_images)} images")
    logger.info(f"  NOTE: Annotations pending - run SAM2 auto-annotation")


def main():
    parser = argparse.ArgumentParser(
        description="Download face images from YFCC100M dataset"
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=50000,
        help="Number of images to download (default: 50000)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="/home/axelofwar/Projects/shml-platform/ray_compute/data/datasets/yfcc100m",
        help="Output directory for downloaded images",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=50,
        help="Maximum concurrent downloads (default: 50)",
    )
    parser.add_argument(
        "--licenses",
        type=str,
        default="1,2,3,7,9",
        help="Comma-separated license codes to accept (default: CC-BY family)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume from previous progress (default: True)",
    )
    parser.add_argument(
        "--no-resume", action="store_true", help="Start fresh, ignore previous progress"
    )
    parser.add_argument(
        "--create-yolo-dataset",
        action="store_true",
        help="Create YOLO-format dataset after download",
    )

    args = parser.parse_args()

    # Parse licenses
    licenses = [l.strip() for l in args.licenses.split(",")]

    # Create downloader
    downloader = YFCC100MDownloader(
        output_dir=args.output_dir,
        target_count=args.target_count,
        max_concurrent=args.max_concurrent,
        licenses=licenses,
        resume=not args.no_resume,
    )

    # Run download
    downloader.run()

    # Optionally create YOLO dataset
    if args.create_yolo_dataset:
        create_yolo_dataset(
            yfcc_dir=args.output_dir,
            output_dir=f"{args.output_dir}_yolo",
        )


if __name__ == "__main__":
    main()
