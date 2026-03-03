"""
Simulated data processing workload executor for benchmarking.

Generates synthetic ADAS-style event data and runs a batch
processing pipeline that exercises:
  - Data generation (row-level)
  - Filtering / enrichment (simulates face-tag classification)
  - Aggregation (group-by statistics)
  - Output serialization

This is the ABSTRACT workload. Engine-specific executors
(ray_executor, spark_executor) implement the actual compute.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

# Workload size configs matching Week 1 baselines
WORKLOAD_CONFIGS = {
    "S": {"rows": 100_000, "workers": 2},
    "M": {"rows": 1_000_000, "workers": 4},
    "L": {"rows": 5_000_000, "workers": 8},
}


@dataclass
class WorkloadSpec:
    """Describes a benchmark workload independent of engine."""

    size: str  # S, M, L
    rows: int
    workers: int
    dataset_name: str = "adas-events-v1"
    dataset_version: str = "1.0.0"

    @classmethod
    def from_size(cls, size: str) -> "WorkloadSpec":
        cfg = WORKLOAD_CONFIGS[size.upper()]
        return cls(size=size.upper(), **cfg)


def generate_synthetic_events(num_rows: int, seed: int = 42) -> list[dict[str, Any]]:
    """
    Generate synthetic ADAS event records.

    Each record simulates a sensor event with:
      - event_id, timestamp, sensor_type
      - confidence score, object_class
      - bounding box (x, y, w, h)
      - face_tag boolean
      - region string

    This is deterministic given the seed for reproducibility.
    """
    import random

    rng = random.Random(seed)
    sensors = ["camera_front", "camera_rear", "lidar_top", "radar_front"]
    classes = ["pedestrian", "vehicle", "cyclist", "face", "sign", "unknown"]
    regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"]
    face_tags = ["face", "portrait", "person", "headshot", "none", "none", "none"]

    events = []
    for i in range(num_rows):
        obj_class = rng.choice(classes)
        events.append(
            {
                "event_id": i,
                "timestamp": 1700000000 + i * 0.001,
                "sensor_type": rng.choice(sensors),
                "confidence": round(rng.uniform(0.1, 1.0), 4),
                "object_class": obj_class,
                "bbox_x": rng.randint(0, 1920),
                "bbox_y": rng.randint(0, 1080),
                "bbox_w": rng.randint(10, 500),
                "bbox_h": rng.randint(10, 500),
                "face_tag": rng.choice(face_tags),
                "region": rng.choice(regions),
                "is_face": obj_class == "face" or rng.choice(face_tags) != "none",
            }
        )
    return events
