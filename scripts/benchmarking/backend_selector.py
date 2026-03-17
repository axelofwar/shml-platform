"""
Backend selector for benchmark execution.

Provides engine-agnostic entry point:
  selector.get_executor(engine_config) → Callable[[BenchmarkScenario], BenchmarkResult]

Convergence points (shared regardless of engine):
  - BenchmarkScenario dataclass (same metadata contract)
  - BenchmarkResult dataclass (same 4 metrics: runtime, queue_wait, throughput, failure_rate)
  - BenchmarkRunner (same MLflow logging, same experiment, same regression rules)
  - Golden dataset (same input data, same SHA-256)
  - Regression thresholds (same allowed regression %)

Divergence points (engine-specific):
  - Init: multiprocessing.Pool vs SparkSession.builder
  - Parallelism knob: worker count vs shuffle.partitions + local[N]
  - Transform style: row-level Python vs DataFrame API
  - Shuffle control: N/A vs AQE + exchange configs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ray_compute.benchmarking.models import BenchmarkResult, BenchmarkScenario


@dataclass
class EngineConfig:
    """Engine-specific configuration."""

    engine: str  # "ray" | "spark"
    config: Dict[str, Any] = field(default_factory=dict)


# Default configs per engine
DEFAULT_ENGINE_CONFIGS = {
    "ray": EngineConfig(
        engine="ray",
        config={},
    ),
    "spark": EngineConfig(
        engine="spark",
        config={
            "shuffle_partitions": 200,
            "aqe_enabled": True,
            "driver_memory": "2g",
        },
    ),
}


def get_executor(
    engine_config: EngineConfig,
) -> Callable[[BenchmarkScenario], BenchmarkResult]:
    """
    Return the benchmark executor callable for the given engine.

    Lazy-imports engine modules so you don't need PySpark installed
    to run Ray benchmarks, and vice versa.
    """
    if engine_config.engine == "ray":
        from scripts.benchmarking.executors.ray_executor import create_ray_executor

        return create_ray_executor(engine_config.config)
    elif engine_config.engine == "spark":
        from scripts.benchmarking.executors.spark_executor import create_spark_executor

        return create_spark_executor(engine_config.config)
    else:
        raise ValueError(
            f"Unknown engine '{engine_config.engine}'. Supported: ray, spark"
        )


def build_scenario(
    benchmark_id: str,
    engine: str,
    workload_name: str,
    rows: int,
    workers: int,
    rep: int,
    phase: str = "baseline",
    size: str = "M",
    dataset_name: str = "adas-events-v1",
    dataset_version: str = "1.0.0",
) -> BenchmarkScenario:
    """
    Build a BenchmarkScenario with standard tags and parameters.
    """
    return BenchmarkScenario(
        benchmark_id=benchmark_id,
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        workload_name=workload_name,
        engine=engine,
        parameters={
            "rows": str(rows),
            "workers": str(workers),
            "rep": str(rep),
        },
        tags={
            "phase": phase,
            "size": size,
        },
    )
