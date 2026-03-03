import numpy as np
from typing import List, Optional


class TrajectorySegmentFilter:
    """
    Trajectory Segment Filter (TSF) for PII Training.

    Filters training data based on advantage estimates over trajectory segments.
    Inspired by PufferLib's implementation and Apple's self-driving RL paper.

    Goal: Filter out uninformative batches (too easy or too hard) to speed up convergence.
    """

    def __init__(
        self,
        segment_length: int = 64,
        threshold_min: float = 0.1,
        threshold_max: float = 2.0,
    ):
        """
        Args:
            segment_length: Number of steps to sum advantages over.
            threshold_min: Minimum absolute advantage sum to keep (filter "too easy").
            threshold_max: Maximum absolute advantage sum to keep (filter "too hard/outliers").
        """
        self.segment_length = segment_length
        self.threshold_min = threshold_min
        self.threshold_max = threshold_max
        self.stats = {"kept": 0, "filtered_easy": 0, "filtered_hard": 0}

    def filter_batch(self, advantages: np.ndarray, indices: np.ndarray) -> np.ndarray:
        """
        Filter a batch of indices based on their advantage values.

        Args:
            advantages: Array of advantage values (aligned with indices).
            indices: Array of data indices.

        Returns:
            Filtered array of indices.
        """
        if len(advantages) < self.segment_length:
            return indices  # Not enough data to segment

        keep_mask = np.zeros(len(indices), dtype=bool)

        # Process in segments
        for i in range(0, len(advantages), self.segment_length):
            segment_adv = advantages[i : i + self.segment_length]
            if len(segment_adv) == 0:
                continue

            # Calculate segment score (sum of absolute advantages or absolute sum)
            # "Sum of advantages" indicates if the whole segment was better/worse than expected.
            segment_score = np.abs(np.sum(segment_adv))

            if segment_score < self.threshold_min:
                self.stats["filtered_easy"] += len(segment_adv)
            elif segment_score > self.threshold_max:
                self.stats["filtered_hard"] += len(segment_adv)
            else:
                keep_mask[i : i + self.segment_length] = True
                self.stats["kept"] += len(segment_adv)

        return indices[keep_mask]

    def get_stats(self):
        return self.stats


if __name__ == "__main__":
    # Example Usage
    filter = TrajectorySegmentFilter(
        segment_length=4, threshold_min=1.0, threshold_max=10.0
    )

    # Mock advantages (some low, some high, some good)
    advs = np.array(
        [
            0.1,
            0.1,
            0.1,
            0.1,  # Sum=0.4 (Drop - too easy)
            2.0,
            2.0,
            2.0,
            2.0,  # Sum=8.0 (Keep)
            5.0,
            5.0,
            5.0,
            5.0,
        ]
    )  # Sum=20.0 (Drop - too hard)
    idxs = np.arange(12)

    filtered_idxs = filter.filter_batch(advs, idxs)
    print(f"Original: {len(idxs)}, Filtered: {len(filtered_idxs)}")
    print(f"Stats: {filter.get_stats()}")
