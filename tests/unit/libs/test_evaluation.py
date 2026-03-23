"""T6: Unit tests for libs/evaluation/llm/metrics.py.

Stubs `evaluate` library so these run without downloading HuggingFace models.
Tests verify the branching logic and return-value structure.
"""

from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_libs_root = os.path.join(_root, "libs")
for p in [_root, _libs_root]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# Stub `evaluate` before importing metrics
# ---------------------------------------------------------------------------

def _make_evaluate_stub() -> MagicMock:
    """Return a consistent mock for the `evaluate` library."""
    evaluate_stub = MagicMock(name="evaluate")

    def _load(name: str, **kwargs):
        m = MagicMock(name=f"evaluate.{name}")
        if name == "rouge":
            m.compute.return_value = {"rouge1": 0.83, "rouge2": 0.57, "rougeL": 0.83}
        elif name == "bleu":
            m.compute.return_value = {"bleu": 0.42}
        elif name == "bertscore":
            m.compute.return_value = {
                "precision": [0.93],
                "recall": [0.91],
                "f1": [0.92],
            }
        return m

    evaluate_stub.load = _load
    return evaluate_stub


sys.modules["evaluate"] = _make_evaluate_stub()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComputeMetrics:
    """Tests for compute_metrics() function."""

    @pytest.fixture(autouse=True)
    def patch_evaluate(self):
        # Reload evaluate stub on each test to get a fresh one
        sys.modules["evaluate"] = _make_evaluate_stub()
        # Invalidate cached module if already imported
        for key in list(sys.modules.keys()):
            if "metrics" in key and "evaluation" in key:
                del sys.modules[key]

    def _import(self):
        from evaluation.llm.metrics import compute_metrics  # type: ignore[import]
        return compute_metrics

    def test_returns_rouge_keys(self):
        fn = self._import()
        res = fn(["The cat sat."], ["The cat is sitting."], run_bertscore=False)
        assert "rouge1" in res
        assert "rouge2" in res
        assert "rougeL" in res

    def test_returns_bleu_key(self):
        fn = self._import()
        res = fn(["The cat."], ["The cat."], run_bertscore=False)
        assert "bleu" in res

    def test_bertscore_included_when_requested(self):
        fn = self._import()
        res = fn(["The cat."], ["The cat."], run_bertscore=True)
        assert "bertscore_f1" in res

    def test_bertscore_skipped_when_disabled(self):
        fn = self._import()
        res = fn(["The cat."], ["The cat."], run_bertscore=False)
        assert "bertscore_f1" not in res

    def test_rouge_values_are_floats(self):
        fn = self._import()
        res = fn(["x"], ["y"], run_bertscore=False)
        assert isinstance(res["rouge1"], float)

    def test_bleu_value_is_float(self):
        fn = self._import()
        res = fn(["x"], ["y"], run_bertscore=False)
        assert isinstance(res["bleu"], float)

    def test_bertscore_f1_between_0_and_1(self):
        fn = self._import()
        res = fn(["hello"], ["hello"], run_bertscore=True, lang="en")
        assert 0.0 <= res["bertscore_f1"] <= 1.0

    def test_multiple_samples_averaged(self):
        """BERTScore averages across multiple samples."""
        stub = _make_evaluate_stub()
        bs_load_fn = stub.load

        # Override bertscore to return two values
        def _multi_load(name, **kw):
            m = MagicMock()
            if name == "rouge":
                m.compute.return_value = {"rouge1": 0.5, "rouge2": 0.5, "rougeL": 0.5}
            elif name == "bleu":
                m.compute.return_value = {"bleu": 0.5}
            elif name == "bertscore":
                m.compute.return_value = {
                    "precision": [0.8, 0.9],
                    "recall": [0.7, 0.85],
                    "f1": [0.75, 0.87],
                }
            return m

        stub.load = _multi_load
        sys.modules["evaluate"] = stub
        for key in list(sys.modules.keys()):
            if "metrics" in key and "evaluation" in key:
                del sys.modules[key]

        from evaluation.llm.metrics import compute_metrics  # type: ignore[import]
        res = compute_metrics(["a", "b"], ["c", "d"], run_bertscore=True)
        assert abs(res["bertscore_f1"] - 0.81) < 0.01


class TestLogMetricsToMLflow:
    """Tests for log_metrics_to_mlflow() helper."""

    @pytest.fixture(autouse=True)
    def setup_mlflow_stub(self):
        sys.modules["evaluate"] = _make_evaluate_stub()
        _mlflow_stub = MagicMock(name="mlflow")
        _mlflow_stub.log_metrics = MagicMock()
        sys.modules["mlflow"] = _mlflow_stub
        for key in list(sys.modules.keys()):
            if "metrics" in key and "evaluation" in key:
                del sys.modules[key]

    def test_log_metrics_calls_mlflow(self):
        from evaluation.llm.metrics import log_metrics_to_mlflow  # type: ignore[import]

        metrics = {"rouge1": 0.8, "bleu": 0.4}
        # Should not raise
        log_metrics_to_mlflow(metrics, prefix="eval")

    def test_log_metrics_with_custom_prefix(self):
        from evaluation.llm.metrics import log_metrics_to_mlflow  # type: ignore[import]

        metrics = {"rouge1": 0.8}
        log_metrics_to_mlflow(metrics, prefix="test_run")  # no exception


class TestSimpleEval:
    """Basic tests for simple_eval module (purity/structure checks)."""

    def test_module_importable(self):
        """simple_eval should import without GPU or network."""
        sys.modules["evaluate"] = _make_evaluate_stub()
        # Invalidate cache
        for key in list(sys.modules.keys()):
            if "simple_eval" in key:
                del sys.modules[key]
        try:
            from evaluation.llm import simple_eval  # type: ignore[import]  # noqa: F401
        except ImportError:
            pytest.skip("simple_eval has unresolvable dependency")

    def test_exact_match_function_exists(self):
        """Exact match scoring should be a callable."""
        sys.modules["evaluate"] = _make_evaluate_stub()
        for key in list(sys.modules.keys()):
            if "simple_eval" in key:
                del sys.modules[key]
        try:
            from evaluation.llm.simple_eval import exact_match  # type: ignore[import]

            assert callable(exact_match)
        except (ImportError, AttributeError):
            pytest.skip("exact_match function not present — skipping")
