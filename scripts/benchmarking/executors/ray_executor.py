"""
Ray executor for benchmark workloads.

Runs the simulated ADAS event processing pipeline using
Python's built-in multiprocessing (simulating Ray task
distribution) to match the Week 1 baseline behavior.

The pipeline:
  1. Generate synthetic events
  2. Filter to face-tagged events (confidence > 0.5)
  3. Enrich with derived fields (area, aspect_ratio)
  4. Group-by aggregation (per sensor_type × region)
  5. Collect results
"""

from __future__ import annotations

import math
import multiprocessing as mp
import time
from typing import Any, Callable, Dict, List

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ray_compute.benchmarking.models import BenchmarkResult, BenchmarkScenario
from scripts.benchmarking.executors import WorkloadSpec, generate_synthetic_events


def _process_chunk(args: tuple) -> dict:
    """Process a chunk of events (runs in worker process)."""
    chunk, chunk_id = args
    results = {"processed": 0, "face_events": 0, "failed": 0, "aggregates": {}}

    for event in chunk:
        try:
            # Step 1: Filter — face-tagged with confidence > 0.5
            if not event.get("is_face") or event.get("confidence", 0) < 0.5:
                results["processed"] += 1
                continue

            # Step 2: Enrich — compute derived fields
            area = event["bbox_w"] * event["bbox_h"]
            aspect_ratio = event["bbox_w"] / max(event["bbox_h"], 1)
            size_class = (
                "small" if area < 5000 else ("medium" if area < 50000 else "large")
            )

            # Step 3: Simulate a light compute workload (hash + math)
            # This simulates feature extraction cost
            feature_hash = hash(f"{event['event_id']}:{event['confidence']}:{area}")
            _ = math.sqrt(abs(feature_hash) % 1000000)

            results["face_events"] += 1

            # Step 4: Aggregate by sensor_type × region
            key = f"{event['sensor_type']}|{event['region']}"
            if key not in results["aggregates"]:
                results["aggregates"][key] = {
                    "count": 0,
                    "sum_confidence": 0.0,
                    "sum_area": 0,
                }
            results["aggregates"][key]["count"] += 1
            results["aggregates"][key]["sum_confidence"] += event["confidence"]
            results["aggregates"][key]["sum_area"] += area

            results["processed"] += 1
        except Exception:
            results["failed"] += 1
            results["processed"] += 1

    return results


def _merge_aggregates(agg_list: list[dict]) -> dict:
    """Merge per-chunk aggregation dicts."""
    merged = {}
    for agg in agg_list:
        for key, val in agg.items():
            if key not in merged:
                merged[key] = {"count": 0, "sum_confidence": 0.0, "sum_area": 0}
            merged[key]["count"] += val["count"]
            merged[key]["sum_confidence"] += val["sum_confidence"]
            merged[key]["sum_area"] += val["sum_area"]
    return merged


def create_ray_executor(
    config: dict | None = None,
) -> Callable[[BenchmarkScenario], BenchmarkResult]:
    """
    Factory: returns an executor closure that runs the simulated
    ADAS workload using multiprocessing (Ray-style parallelism).
    """
    config = config or {}

    def execute(scenario: BenchmarkScenario) -> BenchmarkResult:
        rows = int(scenario.parameters.get("rows", 100_000))
        workers = int(scenario.parameters.get("workers", 2))
        rep = int(scenario.parameters.get("rep", 1))

        # Simulate queue/scheduling overhead
        queue_start = time.time()
        time.sleep(0.5 + (workers * 0.3))  # Simulated scheduler latency
        queue_wait = time.time() - queue_start

        # Generate data
        t0 = time.time()
        events = generate_synthetic_events(rows, seed=42 + rep)

        # Chunk and distribute
        chunk_size = max(1, len(events) // workers)
        chunks = [
            (events[i : i + chunk_size], i // chunk_size)
            for i in range(0, len(events), chunk_size)
        ]

        # Process in parallel
        with mp.Pool(processes=workers) as pool:
            chunk_results = pool.map(_process_chunk, chunks)

        # Merge
        total_processed = sum(r["processed"] for r in chunk_results)
        total_faces = sum(r["face_events"] for r in chunk_results)
        total_failed = sum(r["failed"] for r in chunk_results)
        merged_agg = _merge_aggregates([r["aggregates"] for r in chunk_results])

        runtime = time.time() - t0
        throughput = total_processed / runtime if runtime > 0 else 0
        failure_rate = total_failed / max(total_processed, 1)

        return BenchmarkResult(
            metrics={
                "runtime_seconds": round(runtime, 4),
                "queue_wait_seconds": round(queue_wait, 4),
                "throughput_rows_per_sec": round(throughput, 4),
                "failure_rate": round(failure_rate, 5),
            },
            metadata={
                "rows": rows,
                "workers": workers,
                "retries": rep,
                "compute_profile": f"cpu={workers}x|engine=ray",
                "cost_proxy": round(runtime * workers, 3),
                "face_events_found": total_faces,
                "aggregation_groups": len(merged_agg),
            },
        )

    return execute
