from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MetricDirection(str, Enum):
    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"


@dataclass
class GoldenDatasetRef:
    name: str
    version: str
    source_run_id: str
    source_artifact_path: str
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None


@dataclass
class BenchmarkScenario:
    benchmark_id: str
    dataset_name: str
    dataset_version: str
    workload_name: str
    engine: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    metrics: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RegressionRule:
    metric: str
    direction: MetricDirection
    max_regression_pct: float
    required: bool = True


@dataclass
class RegressionOutcome:
    passed: bool
    summary: str
    failures: List[str] = field(default_factory=list)
    details: Dict[str, Dict[str, float]] = field(default_factory=dict)
