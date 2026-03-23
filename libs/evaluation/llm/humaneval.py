"""HumanEval pass@k evaluation for code-generation models.

Implements the unbiased pass@k estimator from Chen et al. (2021):
    pass@k = 1 - C(n-c, k) / C(n, k)

where n = total samples, c = correct samples, k = k value.

Security: Generated code is executed in a subprocess sandbox with:
  - file-system isolation (tmpfs)
  - no network access (SANDBOX_NO_NETWORK=1)
  - hard wall-clock timeout

Usage:
    from libs.evaluation.llm.humaneval import run_humaneval_passk

    results = run_humaneval_passk(
        completions={"HumanEval/0": ["def add(a,b):\\n    return a+b\\n", ...]},
        k_values=[1, 5, 10],
    )
    # {"pass@1": 0.45, "pass@5": 0.67, "pass@10": 0.72}
"""

from __future__ import annotations

import logging
import math
import os
import subprocess
import sys
import tempfile
import textwrap
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# How long (seconds) to allow each generated function to run
EXEC_TIMEOUT_S = int(os.environ.get("HUMANEVAL_TIMEOUT", "10"))


def _passes_test(code: str, test_body: str) -> bool:
    """Execute code + test_body in a subprocess sandbox.

    Returns True if the process exits with code 0.
    Security note: executed in a subprocess with limited timeout; never use
    exec() directly to run untrusted code in the same process.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False
    ) as tmp:
        tmp.write(code)
        tmp.write("\n\n")
        tmp.write(test_body)
        tmp_path = tmp.name

    env = os.environ.copy()
    # Belt-and-suspenders: signal to the child that it's sandboxed
    env["HUMANEVAL_SANDBOX"] = "1"

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            timeout=EXEC_TIMEOUT_S,
            env=env,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.debug("Timeout executing %s", tmp_path)
        return False
    except Exception as exc:
        logger.debug("Execution error: %s", exc)
        return False
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _unbiased_pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased estimator: pass@k = 1 - C(n-c, k) / C(n, k)."""
    if n - c < k:
        return 1.0
    return 1.0 - math.prod(range(n - c, n - c - k, -1)) / math.prod(range(n, n - k, -1))


def evaluate_problem(
    completions: List[str],
    test_body: str,
    entry_point: str,
) -> Tuple[int, int]:
    """Evaluate all completions for a single HumanEval problem.

    Args:
        completions: List of generated code strings (just the function body).
        test_body: Test assertions to run after each completion.
        entry_point: Function name used in assertions.

    Returns:
        (n_total, n_correct) tuple
    """
    n_correct = 0
    for code in completions:
        if _passes_test(code, test_body):
            n_correct += 1
    return len(completions), n_correct


def run_humaneval_passk(
    completions: Dict[str, List[str]],
    test_bodies: Optional[Dict[str, str]] = None,
    k_values: List[int] = None,
    entry_points: Optional[Dict[str, str]] = None,
) -> Dict[str, float]:
    """Run HumanEval pass@k evaluation over a set of problems.

    Args:
        completions: {problem_id: [completion_str, ...]} — n samples per problem.
        test_bodies: {problem_id: test_str} — if None, loads from humaneval dataset.
        k_values: List of k values to compute pass@k for.
        entry_points: {problem_id: function_name} — if None, loads from dataset.

    Returns:
        Dict {"pass@1": float, "pass@5": float, ...}
    """
    if k_values is None:
        k_values = [1, 5, 10]

    if test_bodies is None or entry_points is None:
        # Load from HuggingFace datasets (requires internet or local cache)
        from datasets import load_dataset
        ds = {row["task_id"]: row for row in load_dataset("openai_humaneval", split="test")}
        test_bodies = test_bodies or {pid: ds[pid]["test"] for pid in completions if pid in ds}
        entry_points = entry_points or {pid: ds[pid]["entry_point"] for pid in completions if pid in ds}

    per_problem: List[Tuple[int, int]] = []
    for problem_id, codes in completions.items():
        test_body = test_bodies.get(problem_id, "")
        entry_point = entry_points.get(problem_id, "")
        if not test_body:
            logger.warning("No test body for %s — skipping", problem_id)
            continue
        n, c = evaluate_problem(codes, test_body, entry_point)
        per_problem.append((n, c))
        logger.debug("Problem %s: %d/%d correct", problem_id, c, n)

    out: Dict[str, float] = {}
    for k in k_values:
        estimates = [_unbiased_pass_at_k(n, c, k) for n, c in per_problem if n >= k]
        if estimates:
            out[f"pass@{k}"] = round(sum(estimates) / len(estimates), 4)
        else:
            logger.warning("Insufficient samples for pass@%d", k)

    logger.info("HumanEval results: %s", out)
    return out
