"""
Artifact Compression Handler
Automatic compression/decompression using zstd for large artifacts
"""

import os
import zstandard as zstd
import logging
from pathlib import Path
from typing import Optional, Tuple
import mimetypes

logger = logging.getLogger(__name__)


class CompressionConfig:
    """Configuration for artifact compression"""

    # Compression settings
    COMPRESSION_LEVEL = 3  # Balance between speed and compression (1-22)
    THRESHOLD_MB = int(os.getenv("MLFLOW_COMPRESSION_THRESHOLD_MB", "10"))
    ENABLED = os.getenv("MLFLOW_AUTO_COMPRESS", "true").lower() == "true"

    # File types to always compress
    COMPRESSIBLE_EXTENSIONS = {
        ".pt",
        ".pth",
        ".h5",
        ".pkl",
        ".onnx",
        ".pb",
        ".safetensors",  # Models
        ".csv",
        ".json",
        ".yaml",
        ".yml",
        ".txt",
        ".log",  # Data/Config
        ".npy",
        ".npz",
        ".parquet",  # Numpy/Pandas
        ".jpg",
        ".jpeg",
        ".png",  # Images (re-compress with zstd)
    }

    # File types to never compress (already compressed)
    SKIP_COMPRESSION = {".zst", ".gz", ".zip", ".tar.gz", ".tgz", ".bz2", ".xz", ".7z"}

    # Magic bytes for detecting compressed files
    MAGIC_BYTES = {
        b"\x1f\x8b": "gzip",
        b"\x42\x5a": "bzip2",
        b"\x50\x4b": "zip",
        b"\x28\xb5\x2f\xfd": "zstd",
    }


class ArtifactCompressor:
    """Handle compression/decompression of MLflow artifacts"""

    def __init__(self):
        self.config = CompressionConfig()
        self.compressor = zstd.ZstdCompressor(level=self.config.COMPRESSION_LEVEL)
        self.decompressor = zstd.ZstdDecompressor()

    def should_compress(self, file_path: Path) -> bool:
        """Determine if file should be compressed"""
        if not self.config.ENABLED:
            return False

        # Check file extension
        ext = file_path.suffix.lower()

        # Skip if already compressed
        if ext in self.config.SKIP_COMPRESSION:
            logger.debug(f"Skipping {file_path.name} - already compressed format")
            return False

        # Check if file is compressible
        if ext not in self.config.COMPRESSIBLE_EXTENSIONS:
            # Check file size - only compress large files of unknown type
            size_mb = file_path.stat().st_size / (1024 * 1024)
            if size_mb < self.config.THRESHOLD_MB:
                return False

        # Check if already compressed (magic bytes)
        if self._is_compressed(file_path):
            logger.debug(f"Skipping {file_path.name} - detected as compressed")
            return False

        # Check size threshold
        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb < self.config.THRESHOLD_MB:
            logger.debug(
                f"Skipping {file_path.name} - below threshold ({size_mb:.2f}MB)"
            )
            return False

        return True

    def _is_compressed(self, file_path: Path) -> bool:
        """Check if file is already compressed using magic bytes"""
        try:
            with open(file_path, "rb") as f:
                header = f.read(4)
                for magic, fmt in self.config.MAGIC_BYTES.items():
                    if header.startswith(magic):
                        return True
        except Exception as e:
            logger.warning(f"Could not read file header: {e}")
        return False

    def compress_file(
        self, input_path: Path, output_path: Optional[Path] = None
    ) -> Tuple[Path, dict]:
        """
        Compress a file using zstd

        Args:
            input_path: Path to input file
            output_path: Optional output path (default: input_path + .zst)

        Returns:
            Tuple of (output_path, metadata)
        """
        if output_path is None:
            output_path = Path(str(input_path) + ".zst")

        original_size = input_path.stat().st_size

        logger.info(
            f"Compressing {input_path.name} ({original_size / 1024 / 1024:.2f}MB)..."
        )

        try:
            with open(input_path, "rb") as ifh:
                with open(output_path, "wb") as ofh:
                    self.compressor.copy_stream(ifh, ofh)

            compressed_size = output_path.stat().st_size
            ratio = (1 - compressed_size / original_size) * 100

            metadata = {
                "original_size": original_size,
                "compressed_size": compressed_size,
                "compression_ratio": f"{ratio:.1f}%",
                "compression_format": "zstd",
                "compression_level": self.config.COMPRESSION_LEVEL,
            }

            logger.info(
                f"✓ Compressed {input_path.name}: "
                f"{original_size / 1024 / 1024:.2f}MB → "
                f"{compressed_size / 1024 / 1024:.2f}MB "
                f"({ratio:.1f}% reduction)"
            )

            return output_path, metadata

        except Exception as e:
            logger.error(f"Compression failed for {input_path.name}: {e}")
            if output_path.exists():
                output_path.unlink()
            raise

    def decompress_file(
        self, input_path: Path, output_path: Optional[Path] = None
    ) -> Path:
        """
        Decompress a zstd file

        Args:
            input_path: Path to compressed file (.zst)
            output_path: Optional output path (default: input_path without .zst)

        Returns:
            Path to decompressed file
        """
        if output_path is None:
            if input_path.suffix == ".zst":
                output_path = input_path.with_suffix("")
            else:
                output_path = Path(str(input_path) + ".decompressed")

        compressed_size = input_path.stat().st_size

        logger.info(
            f"Decompressing {input_path.name} ({compressed_size / 1024 / 1024:.2f}MB)..."
        )

        try:
            with open(input_path, "rb") as ifh:
                with open(output_path, "wb") as ofh:
                    self.decompressor.copy_stream(ifh, ofh)

            decompressed_size = output_path.stat().st_size

            logger.info(
                f"✓ Decompressed {input_path.name}: "
                f"{compressed_size / 1024 / 1024:.2f}MB → "
                f"{decompressed_size / 1024 / 1024:.2f}MB"
            )

            return output_path

        except Exception as e:
            logger.error(f"Decompression failed for {input_path.name}: {e}")
            if output_path.exists():
                output_path.unlink()
            raise

    def compress_directory(self, dir_path: Path) -> dict:
        """
        Compress all eligible files in a directory

        Returns:
            Dict with compression statistics
        """
        stats = {
            "total_files": 0,
            "compressed_files": 0,
            "skipped_files": 0,
            "original_size": 0,
            "compressed_size": 0,
            "files": [],
        }

        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue

            stats["total_files"] += 1
            stats["original_size"] += file_path.stat().st_size

            if self.should_compress(file_path):
                try:
                    compressed_path, metadata = self.compress_file(file_path)
                    stats["compressed_files"] += 1
                    stats["compressed_size"] += metadata["compressed_size"]
                    stats["files"].append(
                        {
                            "original": str(file_path),
                            "compressed": str(compressed_path),
                            "metadata": metadata,
                        }
                    )
                except Exception as e:
                    logger.error(f"Failed to compress {file_path}: {e}")
                    stats["skipped_files"] += 1
            else:
                stats["skipped_files"] += 1

        return stats


# Global compressor instance
compressor = ArtifactCompressor()


def compress_artifact_on_upload(artifact_path: str) -> Tuple[str, dict]:
    """
    Hook for compressing artifacts during upload

    Args:
        artifact_path: Path to artifact file

    Returns:
        Tuple of (final_path, compression_metadata)
    """
    path = Path(artifact_path)

    if not path.exists():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")

    if compressor.should_compress(path):
        compressed_path, metadata = compressor.compress_file(path)
        return str(compressed_path), metadata
    else:
        return artifact_path, {"compressed": False}


def decompress_artifact_on_download(artifact_path: str, decompress: bool = True) -> str:
    """
    Hook for decompressing artifacts during download

    Args:
        artifact_path: Path to artifact file
        decompress: If False, return compressed file directly

    Returns:
        Path to artifact (decompressed or compressed based on flag)
    """
    path = Path(artifact_path)

    if not decompress:
        return artifact_path

    if path.suffix == ".zst":
        decompressed_path = compressor.decompress_file(path)
        return str(decompressed_path)

    return artifact_path
