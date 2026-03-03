#!/usr/bin/env python3
"""Automated Improvement Planner — SHML Platform.

Analyzes platform state, training metrics, test results, and system health
to generate prioritized improvement recommendations.

Data sources:
  - Prometheus metrics (service health, SLO compliance, resource utilization)
  - MLflow (training experiments, model performance)
  - Test results (pytest output)
  - Watchdog audit logs (remediation history)
  - Docker compose configs (service inventory)

Output: Markdown improvement plan with priority, effort, and impact ratings.

Usage:
    python improvement_planner.py                  # Full analysis
    python improvement_planner.py --focus training  # Focus area
    python improvement_planner.py --output plan.md  # Write to file
    python improvement_planner.py --telegram        # Send summary to Telegram

Schedule: Weekly via cron or compose service.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("improvement-planner")

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://global-prometheus:9090")
MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-server:5000")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
WORKSPACE = os.getenv("WORKSPACE_DIR", "/workspace")


# ---------------------------------------------------------------------------
# Data collectors
# ---------------------------------------------------------------------------
def query_prometheus(query: str) -> list[dict[str, Any]]:
    """Run a PromQL query and return results."""
    if not requests:
        return []
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=10,
        )
        data = resp.json()
        return data.get("data", {}).get("result", [])
    except Exception as e:
        logger.warning("Prometheus query failed: %s — %s", query, e)
        return []


def get_slo_violations() -> list[dict[str, Any]]:
    """Check for active SLO violations."""
    results = query_prometheus('ALERTS{alertstate="firing"}')
    violations = []
    for r in results:
        labels = r.get("metric", {})
        violations.append(
            {
                "alert": labels.get("alertname", "unknown"),
                "severity": labels.get("severity", "unknown"),
                "instance": labels.get("instance", ""),
                "container": labels.get("container", ""),
            }
        )
    return violations


def get_resource_utilization() -> dict[str, Any]:
    """Get resource utilization summaries."""
    cpu = query_prometheus(
        '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'
    )
    memory = query_prometheus(
        "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100"
    )
    disk = query_prometheus(
        '(1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100'
    )

    def extract_value(results: list) -> float | None:
        if results and results[0].get("value"):
            try:
                return float(results[0]["value"][1])
            except (IndexError, ValueError):
                pass
        return None

    return {
        "cpu_percent": extract_value(cpu),
        "memory_percent": extract_value(memory),
        "disk_percent": extract_value(disk),
    }


def get_container_restart_counts() -> list[dict[str, Any]]:
    """Containers with high restart counts (indicates instability)."""
    results = query_prometheus("changes(container_start_time_seconds[24h]) > 2")
    restarts = []
    for r in results:
        labels = r.get("metric", {})
        value = r.get("value", [None, "0"])
        restarts.append(
            {
                "container": labels.get(
                    "name",
                    labels.get("container_label_com_docker_compose_service", "unknown"),
                ),
                "restarts_24h": int(float(value[1])) if len(value) > 1 else 0,
            }
        )
    return restarts


def get_mlflow_experiments() -> list[dict[str, Any]]:
    """Get recent MLflow experiment summaries."""
    if not requests:
        return []
    try:
        resp = requests.get(
            f"{MLFLOW_URL}/api/2.0/mlflow/experiments/search",
            params={"max_results": 20},
            timeout=10,
        )
        data = resp.json()
        return data.get("experiments", [])
    except Exception as e:
        logger.warning("MLflow query failed: %s", e)
        return []


def read_watchdog_audit() -> list[dict[str, str]]:
    """Read recent watchdog audit entries."""
    audit_file = Path("/var/lib/watchdog/audit.log")
    if not audit_file.exists():
        # Try workspace path
        audit_file = Path(WORKSPACE) / "logs" / "watchdog" / "audit.log"
    if not audit_file.exists():
        return []

    entries = []
    try:
        lines = audit_file.read_text().strip().split("\n")[-50:]  # Last 50 entries
        for line in lines:
            entries.append({"raw": line})
    except Exception:
        pass
    return entries


def read_test_results() -> dict[str, Any]:
    """Read latest pytest results if available."""
    results_file = Path(WORKSPACE) / "test-results.json"
    if results_file.exists():
        try:
            return json.loads(results_file.read_text())
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# Analysis engine
# ---------------------------------------------------------------------------
class Recommendation:
    """Single improvement recommendation."""

    def __init__(
        self,
        title: str,
        category: str,
        priority: str,  # P0, P1, P2, P3
        effort: str,  # low, medium, high
        impact: str,  # low, medium, high
        description: str,
        actions: list[str],
    ):
        self.title = title
        self.category = category
        self.priority = priority
        self.effort = effort
        self.impact = impact
        self.description = description
        self.actions = actions

    def to_markdown(self) -> str:
        priority_icon = {"P0": "🔴", "P1": "🟠", "P2": "🟡", "P3": "🟢"}.get(
            self.priority, "⚪"
        )
        return (
            f"### {priority_icon} [{self.priority}] {self.title}\n\n"
            f"**Category**: {self.category} | **Effort**: {self.effort} | **Impact**: {self.impact}\n\n"
            f"{self.description}\n\n"
            f"**Actions**:\n" + "\n".join(f"- [ ] {a}" for a in self.actions) + "\n"
        )


def analyze(focus: str | None = None) -> list[Recommendation]:
    """Run full analysis and generate recommendations."""
    recommendations: list[Recommendation] = []

    # --- SLO violations ---
    violations = get_slo_violations()
    if violations:
        alert_names = [v["alert"] for v in violations]
        recommendations.append(
            Recommendation(
                title=f"{len(violations)} Active SLO Violation(s)",
                category="reliability",
                priority="P0",
                effort="medium",
                impact="high",
                description=f"Active alerts: {', '.join(alert_names[:5])}",
                actions=[
                    f"Investigate and resolve: {v['alert']}" for v in violations[:5]
                ],
            )
        )

    # --- Resource utilization ---
    utilization = get_resource_utilization()
    if utilization.get("disk_percent") and utilization["disk_percent"] > 80:
        recommendations.append(
            Recommendation(
                title="High Disk Usage",
                category="infrastructure",
                priority="P1",
                effort="low",
                impact="high",
                description=f"Disk at {utilization['disk_percent']:.0f}%. Risk of service failure.",
                actions=[
                    "Run `docker system prune -f` to clean unused images/containers",
                    "Archive old MLflow artifacts",
                    "Check /tmp and log directories for large files",
                ],
            )
        )

    if utilization.get("memory_percent") and utilization["memory_percent"] > 85:
        recommendations.append(
            Recommendation(
                title="High Memory Usage",
                category="infrastructure",
                priority="P1",
                effort="medium",
                impact="high",
                description=f"Memory at {utilization['memory_percent']:.0f}%.",
                actions=[
                    "Review container memory limits in docker-compose",
                    "Check for memory leaks in inference services",
                    "Consider reducing batch sizes or model concurrency",
                ],
            )
        )

    # --- Container restarts ---
    restarts = get_container_restart_counts()
    if restarts:
        for r in restarts:
            recommendations.append(
                Recommendation(
                    title=f"Container Instability: {r['container']}",
                    category="reliability",
                    priority="P1" if r["restarts_24h"] > 5 else "P2",
                    effort="medium",
                    impact="medium",
                    description=f"{r['container']} restarted {r['restarts_24h']} times in 24h.",
                    actions=[
                        f"Check logs: `docker logs --tail 100 {r['container']}`",
                        "Review healthcheck configuration",
                        "Check resource limits (OOM kills)",
                    ],
                )
            )

    # --- Missing observability ---
    # Check if alertmanager is configured
    alertmanager_targets = query_prometheus('up{job="alertmanager"}')
    if not alertmanager_targets:
        recommendations.append(
            Recommendation(
                title="Alertmanager Not Connected",
                category="observability",
                priority="P1",
                effort="low",
                impact="high",
                description="Prometheus has no alertmanager target. Alerts won't be delivered.",
                actions=[
                    "Deploy alertmanager service",
                    "Configure alertmanager in global-prometheus.yml",
                    "Test alert routing to Telegram",
                ],
            )
        )

    # --- General improvements (always suggest) ---
    if not focus or focus == "training":
        recommendations.append(
            Recommendation(
                title="Set Up Automated Model Evaluation",
                category="ml-ops",
                priority="P2",
                effort="medium",
                impact="high",
                description="Automate model evaluation on held-out test sets after training.",
                actions=[
                    "Create evaluation pipeline that runs after each training job",
                    "Register evaluation metrics in MLflow",
                    "Set up model comparison dashboards",
                    "Configure auto-promotion for models exceeding threshold",
                ],
            )
        )

    if not focus or focus == "security":
        recommendations.append(
            Recommendation(
                title="Regular Secret Rotation",
                category="security",
                priority="P3",
                effort="low",
                impact="medium",
                description="Implement periodic rotation of secrets and API keys.",
                actions=[
                    "Generate new secrets via update_passwords.sh",
                    "Rotate FusionAuth API keys quarterly",
                    "Update Telegram bot token if exposed",
                ],
            )
        )

    # Sort by priority
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    recommendations.sort(key=lambda r: priority_order.get(r.priority, 99))

    return recommendations


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def generate_plan(recommendations: list[Recommendation]) -> str:
    """Generate full improvement plan as Markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# SHML Platform — Improvement Plan",
        f"\n_Generated: {now}_\n",
        f"**Total recommendations**: {len(recommendations)}\n",
    ]

    # Summary by priority
    by_priority: dict[str, int] = {}
    for r in recommendations:
        by_priority[r.priority] = by_priority.get(r.priority, 0) + 1
    lines.append("| Priority | Count |")
    lines.append("|----------|-------|")
    for p in ["P0", "P1", "P2", "P3"]:
        if p in by_priority:
            lines.append(f"| {p} | {by_priority[p]} |")
    lines.append("")

    # Grouped by category
    categories: dict[str, list[Recommendation]] = {}
    for r in recommendations:
        categories.setdefault(r.category, []).append(r)

    for cat, recs in sorted(categories.items()):
        lines.append(f"\n## {cat.replace('-', ' ').title()}\n")
        for r in recs:
            lines.append(r.to_markdown())

    return "\n".join(lines)


def send_telegram_summary(recommendations: list[Recommendation]) -> None:
    """Send condensed summary to Telegram."""
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT and requests):
        return

    p0 = sum(1 for r in recommendations if r.priority == "P0")
    p1 = sum(1 for r in recommendations if r.priority == "P1")
    p2 = sum(1 for r in recommendations if r.priority == "P2")

    msg = (
        f"📋 *Improvement Plan* ({len(recommendations)} items)\n\n"
        f"🔴 P0: {p0}  🟠 P1: {p1}  🟡 P2: {p2}\n\n"
    )

    for r in recommendations[:5]:
        icon = {"P0": "🔴", "P1": "🟠", "P2": "🟡", "P3": "🟢"}.get(r.priority, "⚪")
        msg += f"{icon} {r.title}\n"

    if len(recommendations) > 5:
        msg += f"\n_...and {len(recommendations) - 5} more_"

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Improvement Planner")
    parser.add_argument(
        "--focus",
        choices=["training", "infrastructure", "security", "reliability"],
        help="Focus analysis on a specific area",
    )
    parser.add_argument("--output", help="Write plan to this file")
    parser.add_argument(
        "--telegram", action="store_true", help="Send summary to Telegram"
    )

    args = parser.parse_args()

    logger.info("Running improvement analysis...")
    recommendations = analyze(focus=args.focus)
    plan = generate_plan(recommendations)

    if args.output:
        Path(args.output).write_text(plan)
        logger.info("Plan written to %s", args.output)
    else:
        print(plan)

    if args.telegram:
        send_telegram_summary(recommendations)
        logger.info("Telegram summary sent")


if __name__ == "__main__":
    main()
