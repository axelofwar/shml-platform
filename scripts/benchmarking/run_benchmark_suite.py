#!/usr/bin/env python3
"""
Run benchmark suite across engines and workload sizes.

Usage:
    # Source OAuth first
    source scripts/auth/export_mlflow_oauth_env.sh
    source ~/.config/shml/mlflow_oauth.env

    # Run Ray baselines (re-run for remote MLflow)
    python scripts/benchmarking/run_benchmark_suite.py --engine ray --phase baseline --reps 3

    # Run Spark baselines (EB-02)
    python scripts/benchmarking/run_benchmark_suite.py --engine spark --phase baseline --reps 3

    # Run specific size only
    python scripts/benchmarking/run_benchmark_suite.py --engine spark --phase baseline --sizes M L --reps 3

    # Compare engines
    python scripts/benchmarking/run_benchmark_suite.py --engine spark --phase candidate --reps 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ray_compute.benchmarking import BenchmarkRunner, MetricDirection, RegressionRule
from scripts.benchmarking.backend_selector import (
    DEFAULT_ENGINE_CONFIGS,
    EngineConfig,
    build_scenario,
    get_executor,
)
from scripts.benchmarking.executors import WORKLOAD_CONFIGS

DEFAULT_RULES_FILE = (
    PROJECT_ROOT / "ray_compute" / "config" / "benchmark_regression_rules.json"
)


def _load_rules(path: Path) -> List[RegressionRule]:
    payload = json.loads(path.read_text())
    return [
        RegressionRule(
            metric=r["metric"],
            direction=MetricDirection(r["direction"]),
            max_regression_pct=float(r["max_regression_pct"]),
            required=bool(r.get("required", True)),
        )
        for r in payload.get("rules", [])
    ]


def run_suite(
    engine: str,
    phase: str,
    sizes: List[str],
    reps: int,
    spark_config: dict | None = None,
) -> dict:
    """
    Run the full benchmark suite for a given engine.

    Returns dict mapping size -> list of run_ids.
    """
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not tracking_uri:
        print("ERROR: MLFLOW_TRACKING_URI not set.")
        print("Run: source scripts/auth/export_mlflow_oauth_env.sh")
        print("     source ~/.config/shml/mlflow_oauth.env")
        sys.exit(1)

    runner = BenchmarkRunner(tracking_uri=tracking_uri)

    # Build engine config
    engine_config = DEFAULT_ENGINE_CONFIGS.get(engine, EngineConfig(engine=engine))
    if spark_config and engine == "spark":
        engine_config = EngineConfig(
            engine="spark", config={**engine_config.config, **spark_config}
        )

    executor = get_executor(engine_config)

    results: dict[str, list[str]] = {}
    all_run_ids = []

    print(f"{'=' * 60}")
    print(f"Benchmark Suite: engine={engine} phase={phase}")
    print(f"Sizes: {sizes}  Reps: {reps}")
    print(f"MLflow: {tracking_uri}")
    print(f"{'=' * 60}")

    for size in sizes:
        cfg = WORKLOAD_CONFIGS[size]
        results[size] = []
        print(
            f"\n--- Workload {size} ({cfg['rows']:,} rows, {cfg['workers']} workers) ---"
        )

        for rep in range(1, reps + 1):
            benchmark_id = f"eb02-{engine}-{phase}-{size.lower()}-r{rep}"
            scenario = build_scenario(
                benchmark_id=benchmark_id,
                engine=engine,
                workload_name=f"workload_{size}",
                rows=cfg["rows"],
                workers=cfg["workers"],
                rep=rep,
                phase=phase,
                size=size,
            )

            print(
                f"  Rep {rep}/{reps}: {scenario.benchmark_id} ... ", end="", flush=True
            )

            try:
                run_id = runner.run_benchmark(scenario, executor)
                results[size].append(run_id)
                all_run_ids.append(run_id)

                # Fetch and display metrics
                metrics = runner.load_run_metrics(run_id)
                rt = metrics.get("runtime_seconds", 0)
                tp = metrics.get("throughput_rows_per_sec", 0)
                qw = metrics.get("queue_wait_seconds", 0)
                fr = metrics.get("failure_rate", 0)
                print(f"✓ {rt:.1f}s | {tp:.0f} rows/s | qw={qw:.1f}s | fr={fr:.4f}")
            except Exception as e:
                print(f"✗ {e}")

    print(f"\n{'=' * 60}")
    print(f"Completed {len(all_run_ids)} runs")

    # Save run IDs for later regression comparison
    output = {
        "engine": engine,
        "phase": phase,
        "sizes": sizes,
        "reps": reps,
        "run_ids": results,
        "all_run_ids": all_run_ids,
    }
    output_file = PROJECT_ROOT / "runs" / f"eb02_{engine}_{phase}_run_ids.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(output, indent=2, sort_keys=True))
    print(f"Run IDs saved to: {output_file}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Run benchmark suite")
    parser.add_argument("--engine", required=True, choices=["ray", "spark"])
    parser.add_argument(
        "--phase", default="baseline", choices=["baseline", "candidate"]
    )
    parser.add_argument(
        "--sizes", nargs="+", default=["S", "M", "L"], choices=["S", "M", "L"]
    )
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument(
        "--shuffle-partitions",
        type=int,
        default=None,
        help="Spark shuffle partitions override",
    )
    parser.add_argument(
        "--aqe",
        type=str,
        default=None,
        choices=["true", "false"],
        help="Spark AQE override",
    )
    args = parser.parse_args()

    spark_config = {}
    if args.shuffle_partitions is not None:
        spark_config["shuffle_partitions"] = args.shuffle_partitions
    if args.aqe is not None:
        spark_config["aqe_enabled"] = args.aqe == "true"

    run_suite(
        engine=args.engine,
        phase=args.phase,
        sizes=args.sizes,
        reps=args.reps,
        spark_config=spark_config if spark_config else None,
    )


if __name__ == "__main__":
    main()
