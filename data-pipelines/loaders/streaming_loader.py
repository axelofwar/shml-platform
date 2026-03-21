import torch
from torch.utils.data import IterableDataset
import os
import math
import random
from PIL import Image
from typing import List, Optional, Callable


class StreamingImageDataset(IterableDataset):
    """
    Streaming Dataset for large image collections (e.g., YFCC100M).

    Features:
    - Supports multi-process data loading (sharding).
    - Streams images from disk to avoid OOM.
    - Optional shuffling.
    """

    def __init__(
        self,
        root_dir: str,
        file_list: Optional[List[str]] = None,
        transform: Optional[Callable] = None,
        shuffle: bool = True,
    ):
        self.root_dir = root_dir
        self.transform = transform
        self.shuffle = shuffle

        if file_list:
            self.image_paths = [os.path.join(root_dir, f) for f in file_list]
        else:
            # Fallback to glob if no list provided
            import glob

            # Look for common image extensions
            self.image_paths = []
            for ext in ["*.jpg", "*.jpeg", "*.png"]:
                self.image_paths.extend(
                    glob.glob(os.path.join(root_dir, "**", ext), recursive=True)
                )

    def __iter__(self):
        worker_info = torch.utils.data.get_worker_info()

        if worker_info is None:  # Single-process data loading
            iter_start = 0
            iter_end = len(self.image_paths)
        else:  # Multi-process data loading
            # Split workload across workers
            per_worker = int(
                math.ceil(len(self.image_paths) / float(worker_info.num_workers))
            )
            worker_id = worker_info.id
            iter_start = worker_id * per_worker
            iter_end = min(iter_start + per_worker, len(self.image_paths))

        # Create a copy of the slice to shuffle
        paths = self.image_paths[iter_start:iter_end]
        if self.shuffle:
            random.shuffle(paths)

        for path in paths:
            try:
                with Image.open(path) as img:
                    img = img.convert("RGB")
                    if self.transform:
                        img = self.transform(img)
                    yield img, path
            except Exception as e:
                # Log error but continue streaming
                # print(f"Error loading {path}: {e}")
                continue

    def __len__(self):
        return len(self.image_paths)
