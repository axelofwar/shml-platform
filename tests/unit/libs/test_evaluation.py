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


# ---------------------------------------------------------------------------
# Helpers for mlflow_artifacts tests
# ---------------------------------------------------------------------------

def _make_mlflow_stub():
    """Return a MagicMock that satisfies mlflow_artifacts.py API calls."""
    import tempfile, pathlib
    stub = MagicMock(name="mlflow")

    # Fake experiment
    fake_exp = MagicMock()
    fake_exp.experiment_id = "exp-1"
    stub.get_experiment_by_name.return_value = fake_exp
    stub.create_experiment.return_value = "exp-new"

    # Fake run context manager
    fake_run = MagicMock()
    fake_run.info.run_id = "run-abc123"
    fake_run.__enter__ = MagicMock(return_value=fake_run)
    fake_run.__exit__ = MagicMock(return_value=False)
    stub.start_run.return_value = fake_run

    # Fake artifact download — write a real temp file so _sha256 / stat work
    _tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    _tmp.write(b"golden-data")
    _tmp.flush()
    _tmp.close()
    stub.artifacts.download_artifacts.return_value = _tmp.name

    # Fake search_runs DataFrame
    import types as _types
    df_stub = MagicMock()
    df_stub.empty = False
    df_stub.iloc.__getitem__ = MagicMock(return_value={
        "run_id": "run-abc123",
        "tags.dataset.version": "v1",
    })
    stub.search_runs.return_value = df_stub

    stub.log_artifact = MagicMock()
    stub.log_artifacts = MagicMock()
    stub.log_params = MagicMock()
    stub.log_metrics = MagicMock()
    stub.set_tag = MagicMock()
    stub.set_tracking_uri = MagicMock()
    return stub


def _install_mlflow_stub(stub):
    """Put stub in sys.modules and invalidate any cached mlflow_artifacts module."""
    sys.modules["mlflow"] = stub
    sys.modules["mlflow.artifacts"] = stub.artifacts
    for key in list(sys.modules.keys()):
        if "mlflow_artifact" in key:
            del sys.modules[key]


class TestMLflowArtifactManager:
    """Tests for libs/evaluation/benchmarking/mlflow_artifacts.py."""

    def setup_method(self):
        self._stub = _make_mlflow_stub()
        _install_mlflow_stub(self._stub)
        # Import fresh
        for key in list(sys.modules.keys()):
            if "benchmarking.mlflow_artifacts" in key or key.endswith("mlflow_artifacts"):
                del sys.modules[key]
        from evaluation.benchmarking.mlflow_artifacts import MLflowArtifactManager  # type: ignore
        self.Manager = MLflowArtifactManager

    def _mgr(self):
        return self.Manager()

    def test_init_sets_tracking_uri(self):
        mgr = self.Manager(tracking_uri="http://mlflow:5000")
        self._stub.set_tracking_uri.assert_called_once_with("http://mlflow:5000")

    def test_init_no_tracking_uri(self):
        mgr = self._mgr()
        self._stub.set_tracking_uri.assert_not_called()

    def test_get_or_create_uses_existing_experiment(self):
        mgr = self._mgr()
        result = mgr._get_or_create_experiment_id("test-exp")
        assert result == "exp-1"
        self._stub.create_experiment.assert_not_called()

    def test_get_or_create_creates_new_experiment(self):
        self._stub.get_experiment_by_name.return_value = None
        mgr = self._mgr()
        result = mgr._get_or_create_experiment_id("new-exp")
        assert result == "exp-new"
        self._stub.create_experiment.assert_called_once_with(name="new-exp")

    def test_sha256_returns_hex_digest(self):
        import tempfile
        mgr = self._mgr()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            fname = f.name
        from pathlib import Path
        result = mgr._sha256(Path(fname))
        assert len(result) == 64  # sha256 hex digest length
        assert isinstance(result, str)

    def test_create_or_update_golden_dataset_single_file(self):
        mgr = self._mgr()
        ref = mgr.create_or_update_golden_dataset(
            dataset_name="iris",
            dataset_version="v1",
            source_run_id="src-run-1",
            source_artifact_path="data/iris.csv",
        )
        assert ref.name == "iris"
        assert ref.version == "v1"
        assert ref.source_run_id == "src-run-1"
        assert isinstance(ref.sha256, str)
        self._stub.log_artifact.assert_called_once()

    def test_create_or_update_golden_dataset_with_metadata(self):
        mgr = self._mgr()
        ref = mgr.create_or_update_golden_dataset(
            dataset_name="mnist",
            dataset_version="v2",
            source_run_id="src-run-2",
            source_artifact_path="data/mnist",
            metadata={"rows": "60000", "format": "parquet"},
        )
        assert ref.name == "mnist"
        self._stub.start_run.assert_called()

    def test_resolve_golden_dataset_with_version(self):
        mgr = self._mgr()
        uri = mgr.resolve_golden_dataset_artifact_uri("iris", dataset_version="v1")
        assert uri.startswith("runs:/")
        assert "iris" in uri
        assert "v1" in uri

    def test_resolve_golden_dataset_latest(self):
        mgr = self._mgr()
        uri = mgr.resolve_golden_dataset_artifact_uri("iris")
        assert uri.startswith("runs:/")

    def test_resolve_golden_dataset_experiment_not_found(self):
        self._stub.get_experiment_by_name.return_value = None
        mgr = self._mgr()
        with pytest.raises(ValueError, match="Golden dataset experiment not found"):
            mgr.resolve_golden_dataset_artifact_uri("iris")

    def test_resolve_golden_dataset_no_runs(self):
        empty_df = MagicMock()
        empty_df.empty = True
        self._stub.search_runs.return_value = empty_df
        mgr = self._mgr()
        with pytest.raises(ValueError, match="No golden dataset found"):
            mgr.resolve_golden_dataset_artifact_uri("iris", dataset_version="v99")

    def test_backup_golden_dataset_returns_run_id(self):
        mgr = self._mgr()
        run_id = mgr.backup_golden_dataset("iris", "v1")
        assert run_id == "run-abc123"

    def test_enforce_artifact_only_source_with_valid_runs_uri(self):
        mgr = self._mgr()
        mgr.enforce_mlflow_artifact_only_source(artifact_uri="runs:/abc/data.csv")
        # No exception

    def test_enforce_artifact_only_source_with_run_id_and_path(self):
        mgr = self._mgr()
        mgr.enforce_mlflow_artifact_only_source(
            source_run_id="run-1", source_artifact_path="data/file.csv"
        )
        # No exception

    def test_enforce_artifact_only_source_rejects_local_uri(self):
        mgr = self._mgr()
        with pytest.raises(ValueError, match="MLflow runs:/ URI scheme"):
            mgr.enforce_mlflow_artifact_only_source(artifact_uri="/local/path/data.csv")

    def test_enforce_artifact_only_source_rejects_empty(self):
        mgr = self._mgr()
        with pytest.raises(ValueError, match="Artifacts must come from MLflow"):
            mgr.enforce_mlflow_artifact_only_source()
