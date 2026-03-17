#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ray_compute.benchmarking import (
    BenchmarkRunner,
    MLflowArtifactManager,
    MetricDirection,
    RegressionRule,
)


def _parse_rules(path: Path) -> List[RegressionRule]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rules = []
    for item in payload.get("rules", []):
        rules.append(
            RegressionRule(
                metric=item["metric"],
                direction=MetricDirection(item["direction"]),
                max_regression_pct=float(item["max_regression_pct"]),
                required=bool(item.get("required", True)),
            )
        )
    return rules


def cmd_register_golden(args: argparse.Namespace) -> None:
    manager = MLflowArtifactManager(tracking_uri=args.tracking_uri)
    ref = manager.create_or_update_golden_dataset(
        dataset_name=args.dataset_name,
        dataset_version=args.dataset_version,
        source_run_id=args.source_run_id,
        source_artifact_path=args.source_artifact_path,
        metadata={"owner": args.owner, "purpose": args.purpose},
    )
    print(json.dumps(ref.__dict__, indent=2, sort_keys=True))


def cmd_backup_golden(args: argparse.Namespace) -> None:
    manager = MLflowArtifactManager(tracking_uri=args.tracking_uri)
    run_id = manager.backup_golden_dataset(
        dataset_name=args.dataset_name,
        dataset_version=args.dataset_version,
    )
    print(json.dumps({"backup_run_id": run_id}, indent=2))


def cmd_compare(args: argparse.Namespace) -> None:
    runner = BenchmarkRunner(tracking_uri=args.tracking_uri)
    rules = _parse_rules(Path(args.rules_file))
    outcome = runner.evaluate_regression_against_baseline(
        baseline_run_id=args.baseline_run_id,
        candidate_run_id=args.candidate_run_id,
        rules=rules,
        persist_artifact=True,
    )
    print(
        json.dumps(
            {
                "passed": outcome.passed,
                "summary": outcome.summary,
                "failures": outcome.failures,
                "details": outcome.details,
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Week 1 MLflow-first benchmark/regression framework tools"
    )
    parser.add_argument("--tracking-uri", default=None)
    sub = parser.add_subparsers(required=True)

    reg = sub.add_parser(
        "register-golden", help="Register golden dataset from MLflow run artifact"
    )
    reg.add_argument("--dataset-name", required=True)
    reg.add_argument("--dataset-version", required=True)
    reg.add_argument("--source-run-id", required=True)
    reg.add_argument("--source-artifact-path", required=True)
    reg.add_argument("--owner", default="platform")
    reg.add_argument("--purpose", default="benchmark-regression")
    reg.set_defaults(func=cmd_register_golden)

    bak = sub.add_parser(
        "backup-golden", help="Backup golden dataset into backup experiment"
    )
    bak.add_argument("--dataset-name", required=True)
    bak.add_argument("--dataset-version", required=True)
    bak.set_defaults(func=cmd_backup_golden)

    cmp_cmd = sub.add_parser(
        "compare", help="Run regression check using two MLflow run IDs"
    )
    cmp_cmd.add_argument("--baseline-run-id", required=True)
    cmp_cmd.add_argument("--candidate-run-id", required=True)
    cmp_cmd.add_argument("--rules-file", required=True)
    cmp_cmd.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
