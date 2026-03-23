from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

import mlflow

from .models import (
    BenchmarkResult,
    BenchmarkScenario,
    RegressionOutcome,
    RegressionRule,
)
from .regression import evaluate_regression


DEFAULT_BENCHMARK_EXPERIMENT = "platform-benchmarking"


class BenchmarkRunner:
    """
    MLflow-backed benchmark and regression runner.

    Principles:
    - Scenario metadata and results are always persisted in MLflow.
    - Baselines are sourced from prior MLflow runs.
    - Optional local report files are temporary and mirrored into MLflow artifacts.
    """

    def __init__(
        self,
        tracking_uri: Optional[str] = None,
        benchmark_experiment: str = DEFAULT_BENCHMARK_EXPERIMENT,
    ) -> None:
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        self.benchmark_experiment = benchmark_experiment

    def _get_or_create_experiment_id(self) -> str:
        exp = mlflow.get_experiment_by_name(self.benchmark_experiment)
        if exp is not None:
            return exp.experiment_id
        return mlflow.create_experiment(name=self.benchmark_experiment)

    def run_benchmark(
        self,
        scenario: BenchmarkScenario,
        executor: Callable[[BenchmarkScenario], BenchmarkResult],
    ) -> str:
        experiment_id = self._get_or_create_experiment_id()
        with mlflow.start_run(
            experiment_id=experiment_id,
            run_name=f"bench::{scenario.benchmark_id}::{scenario.engine}::{scenario.workload_name}",
            tags={
                "benchmark.id": scenario.benchmark_id,
                "benchmark.workload": scenario.workload_name,
                "benchmark.engine": scenario.engine,
                "dataset.name": scenario.dataset_name,
                "dataset.version": scenario.dataset_version,
                **scenario.tags,
            },
        ) as run:
            mlflow.log_params(
                {
                    "benchmark_id": scenario.benchmark_id,
                    "dataset_name": scenario.dataset_name,
                    "dataset_version": scenario.dataset_version,
                    "workload_name": scenario.workload_name,
                    "engine": scenario.engine,
                    **{f"param.{k}": str(v) for k, v in scenario.parameters.items()},
                }
            )

            result = executor(scenario)
            if result.metrics:
                mlflow.log_metrics(result.metrics)

            if result.metadata:
                with tempfile.TemporaryDirectory(prefix="bench-meta-") as tmp_dir:
                    metadata_file = Path(tmp_dir) / "benchmark_metadata.json"
                    metadata_file.write_text(
                        json.dumps(result.metadata, indent=2, sort_keys=True),
                        encoding="utf-8",
                    )
                    mlflow.log_artifact(str(metadata_file), artifact_path="benchmark")

            return run.info.run_id

    def load_run_metrics(self, run_id: str) -> Dict[str, float]:
        run = mlflow.get_run(run_id)
        return {k: float(v) for k, v in run.data.metrics.items()}

    def evaluate_regression_against_baseline(
        self,
        baseline_run_id: str,
        candidate_run_id: str,
        rules: Iterable[RegressionRule],
        persist_artifact: bool = True,
    ) -> RegressionOutcome:
        baseline_metrics = self.load_run_metrics(baseline_run_id)
        candidate_metrics = self.load_run_metrics(candidate_run_id)
        outcome = evaluate_regression(baseline_metrics, candidate_metrics, rules)

        if persist_artifact:
            with tempfile.TemporaryDirectory(prefix="regression-outcome-") as tmp_dir:
                result_file = Path(tmp_dir) / "regression_outcome.json"
                payload = {
                    "baseline_run_id": baseline_run_id,
                    "candidate_run_id": candidate_run_id,
                    "rules": [asdict(rule) for rule in rules],
                    "outcome": asdict(outcome),
                }
                result_file.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )

                with mlflow.start_run(run_id=candidate_run_id):
                    mlflow.log_artifact(str(result_file), artifact_path="regression")
                    mlflow.set_tag("regression.passed", str(outcome.passed).lower())

        return outcome
