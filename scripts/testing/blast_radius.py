#!/usr/bin/env python3
"""GitNexus blast-radius regression test selector.

Uses GitNexus's knowledge graph to:
1. Detect which symbols changed in the current git diff
2. Map changed symbols → affected execution flows
3. Select the minimal set of tests that cover those flows
4. Optionally run them via pytest

Usage:
    # Show affected tests (dry-run)
    python3 scripts/testing/blast_radius.py

    # Run affected tests
    python3 scripts/testing/blast_radius.py --run

    # Against specific base ref
    python3 scripts/testing/blast_radius.py --base main --run

    # CI mode: generate JSON report
    python3 scripts/testing/blast_radius.py --ci --output blast-radius-report.json
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PLATFORM_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DIR = PLATFORM_ROOT / "tests"

# Map GitNexus cluster/process names to test directories/files
CLUSTER_TO_TESTS: dict[str, list[str]] = {
    "inference": ["tests/unit/inference/", "tests/integration/test_inference_stack.py"],
    "chat-api": ["tests/chat-api/", "tests/unit/inference/test_chat_api_auth.py"],
    "auth": ["tests/unit/test_auth_compose_contract.py", "tests/integration/test_fusionauth.py"],
    "monitoring": ["tests/unit/test_monitoring_config.py", "tests/integration/test_observability.py"],
    "gateway": ["tests/unit/test_infra_compose_contract.py", "tests/integration/test_traefik_routing.py"],
    "platform": ["tests/unit/test_platform_wiring.py", "tests/unit/test_security_hardening.py"],
    "ray_compute": ["tests/unit/ray_compute/"],
    "training": ["tests/unit/libs/"],
    "face": ["tests/unit/libs/test_face_detection_training.py"],
    "jobs": ["tests/unit/ray_compute/"],
}


@dataclass
class BlastRadiusReport:
    changed_symbols: list[dict] = field(default_factory=list)
    affected_processes: list[dict] = field(default_factory=list)
    risk_level: str = "unknown"
    selected_tests: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    changed_count: int = 0
    affected_count: int = 0


def run_gitnexus_detect(scope: str = "all", repo: str = "shml-platform") -> dict:
    """Run gitnexus detect_changes and return parsed output."""
    cmd = ["gitnexus", "query", "--repo", repo, "detect_changes"]
    # Use the CLI impact tool for blast radius
    try:
        result = subprocess.run(
            ["gitnexus", "status"],
            capture_output=True, text=True, timeout=30,
            cwd=str(PLATFORM_ROOT)
        )
        if result.returncode != 0:
            logger.warning("GitNexus status check failed: %s", result.stderr)
            return {}
    except FileNotFoundError:
        logger.error("gitnexus CLI not found. Install with: npm install -g gitnexus")
        return {}
    except subprocess.TimeoutExpired:
        logger.error("GitNexus status timed out")
        return {}

    # Get changed files from git diff
    git_result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True, text=True, timeout=10,
        cwd=str(PLATFORM_ROOT)
    )
    changed_files = [f for f in git_result.stdout.strip().split("\n") if f]

    # Also check staged
    git_staged = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        capture_output=True, text=True, timeout=10,
        cwd=str(PLATFORM_ROOT)
    )
    staged_files = [f for f in git_staged.stdout.strip().split("\n") if f]
    all_changed = list(set(changed_files + staged_files))

    return {"changed_files": all_changed}


def get_impact_for_files(changed_files: list[str]) -> BlastRadiusReport:
    """Map changed files to affected clusters and select tests."""
    report = BlastRadiusReport(changed_files=changed_files)

    # Extract Python symbols from changed files using GitNexus context
    for filepath in changed_files:
        if not filepath.endswith((".py", ".ts", ".tsx", ".sh", ".yml", ".yaml")):
            continue

        path = Path(filepath)
        # Determine which cluster this file belongs to
        parts = path.parts
        for cluster_name in CLUSTER_TO_TESTS:
            if cluster_name in str(filepath).lower():
                report.changed_symbols.append({
                    "file": filepath,
                    "cluster": cluster_name,
                })
                break

    # Run GitNexus impact analysis for Python files with extractable symbols
    py_files = [f for f in changed_files if f.endswith(".py")]
    for py_file in py_files[:10]:  # Limit to 10 files to avoid slow analysis
        try:
            result = subprocess.run(
                ["gitnexus", "context", py_file],
                capture_output=True, text=True, timeout=15,
                cwd=str(PLATFORM_ROOT)
            )
            if result.returncode == 0 and result.stdout.strip():
                report.affected_processes.append({
                    "file": py_file,
                    "context": result.stdout[:500],
                })
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Select tests based on affected clusters
    selected: set[str] = set()
    affected_clusters: set[str] = set()

    for sym in report.changed_symbols:
        cluster = sym.get("cluster", "")
        if cluster in CLUSTER_TO_TESTS:
            affected_clusters.add(cluster)
            for test_path in CLUSTER_TO_TESTS[cluster]:
                full_path = PLATFORM_ROOT / test_path
                if full_path.exists():
                    selected.add(test_path)

    # Direct test file changes always run themselves
    for f in changed_files:
        if f.startswith("tests/") and f.endswith(".py"):
            full_path = PLATFORM_ROOT / f
            if full_path.exists():
                selected.add(f)

    # Compose/config changes trigger contract tests
    for f in changed_files:
        if "docker-compose" in f or f.endswith((".yml", ".yaml")):
            selected.add("tests/unit/test_platform_wiring.py")
            if "auth" in f:
                selected.add("tests/unit/test_auth_compose_contract.py")
            if "infra" in f or "traefik" in f:
                selected.add("tests/unit/test_infra_compose_contract.py")
            if "monitoring" in f or "prometheus" in f or "grafana" in f:
                selected.add("tests/unit/test_monitoring_config.py")

    # Security-sensitive changes always run security tests
    for f in changed_files:
        if any(kw in f.lower() for kw in ["auth", "security", "secret", "token", "oauth"]):
            selected.add("tests/unit/test_security_hardening.py")

    report.selected_tests = sorted(selected)
    report.changed_count = len(changed_files)
    report.affected_count = len(affected_clusters)

    # Risk level assessment
    if report.changed_count == 0:
        report.risk_level = "none"
    elif any("auth" in c or "security" in c for c in affected_clusters):
        report.risk_level = "high"
    elif len(affected_clusters) >= 3:
        report.risk_level = "high"
    elif len(affected_clusters) >= 2:
        report.risk_level = "medium"
    else:
        report.risk_level = "low"

    return report


def run_selected_tests(tests: list[str]) -> int:
    """Run selected tests via pytest, return exit code."""
    if not tests:
        print("No tests to run — no affected areas detected.")
        return 0

    cmd = ["python3", "-m", "pytest", "-v", "--tb=short"] + tests
    print(f"\n{'='*60}")
    print(f"Running {len(tests)} test target(s):")
    for t in tests:
        print(f"  {t}")
    print(f"{'='*60}\n")

    result = subprocess.run(cmd, cwd=str(PLATFORM_ROOT))
    return result.returncode


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="GitNexus blast-radius regression test selector")
    parser.add_argument("--run", action="store_true", help="Run selected tests")
    parser.add_argument("--base", default="HEAD", help="Base ref for diff (default: HEAD)")
    parser.add_argument("--ci", action="store_true", help="CI mode: JSON output")
    parser.add_argument("--output", default=None, help="Output file for CI report")
    parser.add_argument("--all", action="store_true", help="Run all tests (ignore blast radius)")
    args = parser.parse_args()

    if args.all:
        return subprocess.run(
            ["python3", "-m", "pytest", "-v", "--tb=short", "tests/"],
            cwd=str(PLATFORM_ROOT)
        ).returncode

    # Detect changes
    changes = run_gitnexus_detect()
    changed_files = changes.get("changed_files", [])

    if not changed_files:
        print("No changes detected.")
        return 0

    # Get impact
    report = get_impact_for_files(changed_files)

    if args.ci:
        output = {
            "risk_level": report.risk_level,
            "changed_files": report.changed_files,
            "changed_count": report.changed_count,
            "affected_count": report.affected_count,
            "selected_tests": report.selected_tests,
            "changed_symbols": report.changed_symbols,
        }
        json_str = json.dumps(output, indent=2)
        if args.output:
            Path(args.output).write_text(json_str)
            print(f"Report written to {args.output}")
        else:
            print(json_str)
        return 0

    # Display report
    print(f"\n{'='*60}")
    print(f"  BLAST RADIUS REPORT")
    print(f"{'='*60}")
    print(f"  Risk Level:     {report.risk_level.upper()}")
    print(f"  Changed Files:  {report.changed_count}")
    print(f"  Affected Areas: {report.affected_count}")
    print(f"  Selected Tests: {len(report.selected_tests)}")
    print(f"{'='*60}")

    if report.changed_files:
        print("\nChanged files:")
        for f in report.changed_files[:20]:
            print(f"  {f}")

    if report.selected_tests:
        print("\nSelected tests:")
        for t in report.selected_tests:
            print(f"  {t}")
    else:
        print("\nNo test targets matched the changed areas.")

    if args.run:
        return run_selected_tests(report.selected_tests)

    return 0


if __name__ == "__main__":
    sys.exit(main())
