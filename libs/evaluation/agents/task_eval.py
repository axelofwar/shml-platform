"""Agent task evaluation — JSONL fixture-based loop with MLflow logging.

Runs a batch of agent tasks defined in a JSONL fixture file, evaluates
tool-call correctness and response quality, and logs results to the
'agent-eval' MLflow experiment.

Fixture format (one JSON object per line):
    {
        "task_id": "search_01",
        "instruction": "Find the population of Tokyo.",
        "expected_tool": "web_search",
        "expected_answer_contains": ["13", "million", "tokyo"],
        "max_turns": 3
    }

Usage:
    from libs.evaluation.agents.task_eval import run_task_eval

    results = run_task_eval(
        fixture_path="tests/fixtures/agent_tasks.jsonl",
        agent_fn=my_agent_fn,
        mlflow_run_name="agent-task-eval-v1",
    )
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def _load_fixtures(fixture_path: str) -> List[Dict[str, Any]]:
    """Load task fixtures from a JSONL file."""
    fixtures = []
    path = Path(fixture_path)
    if not path.exists():
        raise FileNotFoundError(f"Fixture file not found: {fixture_path}")
    with path.open("r") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                fixtures.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Skip malformed JSON on line %d: %s", lineno, exc)
    return fixtures


def _check_answer(response: str, expected_contains: List[str]) -> bool:
    """Return True if all expected strings appear in the response (case-insensitive)."""
    if not expected_contains:
        return True
    lower = response.lower()
    return all(term.lower() in lower for term in expected_contains)


def _check_tool_called(tool_calls: List[str], expected_tool: Optional[str]) -> bool:
    """Return True if the expected tool was invoked at least once."""
    if expected_tool is None:
        return True
    return expected_tool in tool_calls


def run_task_eval(
    fixture_path: str,
    agent_fn: Callable[[str], Dict[str, Any]],
    mlflow_experiment: str = "agent-eval",
    mlflow_run_name: str = "task-eval",
    mlflow_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate an agent function against JSONL task fixtures.

    The agent_fn must accept a ``str`` (the task instruction) and return a dict:
        {
            "response": str,         # final text response
            "tool_calls": list[str]  # names of tools invoked
        }

    Args:
        fixture_path: Path to JSONL fixture file.
        agent_fn: Callable implementing the agent under test.
        mlflow_experiment: MLflow experiment name.
        mlflow_run_name: Name for a new MLflow run.
        mlflow_run_id: Log into existing run (None = create new).

    Returns:
        Summary dict: {
            "total": int,
            "passed": int,
            "failed": int,
            "pass_rate": float,
            "results": list[dict]
        }
    """
    fixtures = _load_fixtures(fixture_path)
    logger.info("Loaded %d task fixtures from %s", len(fixtures), fixture_path)

    task_results: List[Dict[str, Any]] = []
    passed = 0

    for task in fixtures:
        task_id = task.get("task_id", "unknown")
        instruction = task.get("instruction", "")
        expected_tool = task.get("expected_tool")
        expected_contains = task.get("expected_answer_contains", [])

        start = time.monotonic()
        try:
            out = agent_fn(instruction)
            response = out.get("response", "")
            tool_calls = out.get("tool_calls", [])
            error = None
        except Exception as exc:
            response = ""
            tool_calls = []
            error = str(exc)
            logger.warning("Task %s raised exception: %s", task_id, exc)

        elapsed = time.monotonic() - start

        answer_ok = _check_answer(response, expected_contains)
        tool_ok = _check_tool_called(tool_calls, expected_tool)
        task_passed = answer_ok and tool_ok and error is None

        if task_passed:
            passed += 1

        task_results.append({
            "task_id": task_id,
            "passed": task_passed,
            "answer_ok": answer_ok,
            "tool_ok": tool_ok,
            "error": error,
            "latency_s": round(elapsed, 3),
        })
        logger.debug(
            "Task %-20s %s (answer_ok=%s tool_ok=%s latency=%.2fs)",
            task_id,
            "PASS" if task_passed else "FAIL",
            answer_ok,
            tool_ok,
            elapsed,
        )

    total = len(fixtures)
    failed = total - passed
    pass_rate = round(passed / total, 4) if total else 0.0

    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "results": task_results,
    }

    logger.info(
        "Task eval complete: %d/%d passed (%.1f%%)", passed, total, pass_rate * 100
    )

    # Log to MLflow
    import mlflow

    mlflow.set_experiment(mlflow_experiment)
    ctx = (
        mlflow.start_run(run_id=mlflow_run_id)
        if mlflow_run_id
        else mlflow.start_run(run_name=mlflow_run_name)
    )
    with ctx:
        mlflow.log_params({
            "fixture_path": fixture_path,
            "total_tasks": total,
        })
        mlflow.log_metrics({
            "task_pass_rate": pass_rate,
            "task_passed": float(passed),
            "task_failed": float(failed),
            "avg_latency_s": round(
                sum(r["latency_s"] for r in task_results) / total, 3
            ) if total else 0.0,
        })
        # Log per-task failures as a JSONL artifact
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as tmp:
            for r in task_results:
                tmp.write(json.dumps(r) + "\n")
            tmp_path = tmp.name
        mlflow.log_artifact(tmp_path, artifact_path="task_results")
        os.unlink(tmp_path)

    return summary
